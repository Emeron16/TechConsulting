"""NRG Energy Knowledge Copilot -- Streamlit UI body, factored into a
callable render() from the start (unlike copilot-demo's streamlit_app.py,
which needed a later extraction -- see NRG_Implementation_Plan.md Phase 9).
render() is called by both nrg_app.py (standalone) and
shell/nrg_wrapper.py (embedded in the multi-demo shell), so there's
exactly one implementation of each tab.

Reuses the exact same orchestration path as scripts/ask.py
(nrg_chains.chain.run_question) and the exact same ingest path as
scripts/ingest.py (nrg_chains.ingest.ingest_document) -- no logic
duplicated here, only presentation.

session_state keys are prefixed nrg_ throughout (not the bare names
copilot-demo's streamlit_app.py uses) so this can safely render inside the
same Streamlit session as the Novartis demo via the shell without any key
collision -- see NRG_Implementation_Plan.md Phase 9.
"""
import asyncio
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from nrg_chains.chain import run_question
from nrg_chains.ingest import ingest_document
from nrg_retrieval.kb_actions import (
    get_document_content,
    get_document_versions,
    list_all_kb_documents,
    search_kb,
)
from nrg_retrieval.postgres_client import (
    list_random_sampled_answers,
    list_recent_sampled_answers,
    record_sample_review,
)


def _init_session_state() -> None:
    if "nrg_run_history" not in st.session_state:
        st.session_state.nrg_run_history = []  # list of {"question": str, "result": AskResult, "asked_at": datetime}
    if "nrg_selected_run_index" not in st.session_state:
        st.session_state.nrg_selected_run_index = None
    if "nrg_ingest_history" not in st.session_state:
        st.session_state.nrg_ingest_history = []
    if "nrg_selected_ingest_index" not in st.session_state:
        st.session_state.nrg_selected_ingest_index = None
    if "nrg_selected_flow_kind" not in st.session_state:
        st.session_state.nrg_selected_flow_kind = None  # "query" | "ingest"
    if "nrg_selected_kb_doc" not in st.session_state:
        st.session_state.nrg_selected_kb_doc = None


def _render_ask_tab() -> None:
    st.subheader("Ask the copilot")
    example_questions = [
        "Does the FixedSaver 24 plan include a winter usage credit?",
        "Does the VarSaver plan include a winter usage credit?",
        "What is the renewable energy content percentage disclosed on the FixedSaver 24 EFL?",
        "What late fee applies if a payment is 10 days overdue?",
        "When should I escalate a billing dispute to the disputes team?",
    ]
    selected_example = st.selectbox(
        "Try an example question, or type your own below:",
        ["(type my own)"] + example_questions,
        key="nrg_example_select",
    )
    default_text = "" if selected_example == "(type my own)" else selected_example
    question = st.text_area("Question", value=default_text, height=80, key="nrg_question_input")

    if st.button("Ask", type="primary", disabled=not question.strip(), key="nrg_ask_btn"):
        with st.spinner("Classifying question, running hybrid retrieval, generating grounded answer..."):
            result = asyncio.run(run_question(question.strip()))

        st.session_state.nrg_run_history.insert(
            0, {"question": question.strip(), "result": result, "asked_at": datetime.now()}
        )
        st.session_state.nrg_selected_run_index = 0
        st.session_state.nrg_selected_flow_kind = "query"

        st.markdown("### Answer")
        st.markdown(result.final_answer)

        col1, col2, col3 = st.columns(3)
        col1.metric("Confidence", result.structured_answer.confidence)
        col2.metric("Classified as", result.structured_answer.doc_type_classified or "unclassified")
        col3.metric("Citations", len(result.structured_answer.citations))

        if result.structured_answer.citations:
            st.caption("Sources: " + ", ".join(result.structured_answer.citations))

        st.info(
            "This answer was logged immediately to the compliance sampling log (no approval gate) -- "
            "see the **Compliance Review** tab. See the **Flow** tab for the full pipeline diagram."
        )


def _render_flow_tab() -> None:
    # nrg_chains/flow_diagram.py and ingest_flow_diagram.py were built in
    # Phase 6. Kept as a lazy (function-body) import with a ModuleNotFoundError
    # guard rather than a module-level import -- harmless now, but this is
    # what let Phase 5 ship and run standalone before these modules existed
    # (Streamlit executes every tab's body on each script run regardless of
    # which tab is visually selected, so an unconditional top-level import
    # would have crashed the whole page, not just this tab).
    try:
        from nrg_chains.flow_diagram import render_flow_html
        from nrg_chains.ingest_flow_diagram import render_ingest_flow_html
    except ModuleNotFoundError:
        st.subheader("Pipeline flow")
        st.info("Flow diagrams are built in Phase 6 — not yet available.")
        return

    st.subheader("Pipeline flow")
    st.caption(
        "Visualizes exactly what happened for a given question or document upload. Greyed/dashed "
        "boxes are original-architecture layers not implemented locally."
    )

    has_queries = bool(st.session_state.nrg_run_history)
    has_ingests = bool(st.session_state.nrg_ingest_history)

    if not has_queries and not has_ingests:
        st.write("Nothing to show yet — ask a question in the **Ask** tab or upload a document in the **Knowledge Base** tab.")
        return

    col_list, col_diagram = st.columns([1, 3])

    with col_list:
        if has_queries:
            st.markdown("**Query runs**")
            for i, run in enumerate(st.session_state.nrg_run_history):
                label = f"{run['asked_at'].strftime('%H:%M:%S')} — {run['question'][:40]}"
                is_selected = st.session_state.nrg_selected_flow_kind == "query" and i == st.session_state.nrg_selected_run_index
                if st.button(label, key=f"nrg_run_{i}", type="primary" if is_selected else "secondary", use_container_width=True):
                    st.session_state.nrg_selected_run_index = i
                    st.session_state.nrg_selected_flow_kind = "query"
                    st.rerun()

        if has_ingests:
            st.markdown("**Ingestion runs**")
            for i, run in enumerate(st.session_state.nrg_ingest_history):
                label = f"{run['at'].strftime('%H:%M:%S')} — {run['filename']}"
                is_selected = st.session_state.nrg_selected_flow_kind == "ingest" and i == st.session_state.get("nrg_selected_ingest_index")
                if st.button(label, key=f"nrg_ingest_{i}", type="primary" if is_selected else "secondary", use_container_width=True):
                    st.session_state.nrg_selected_ingest_index = i
                    st.session_state.nrg_selected_flow_kind = "ingest"
                    st.rerun()

    with col_diagram:
        kind = st.session_state.nrg_selected_flow_kind
        if kind is None:
            kind = "query" if has_queries else "ingest"

        if kind == "query" and has_queries:
            idx = st.session_state.nrg_selected_run_index
            if idx is None or idx >= len(st.session_state.nrg_run_history):
                idx = 0
            selected = st.session_state.nrg_run_history[idx]
            diagram_html = render_flow_html(selected["result"], selected["question"])
            components.html(diagram_html, height=2200, scrolling=True)
        elif kind == "ingest" and has_ingests:
            idx = st.session_state.get("nrg_selected_ingest_index")
            if idx is None or idx >= len(st.session_state.nrg_ingest_history):
                idx = 0
            selected = st.session_state.nrg_ingest_history[idx]
            diagram_html = render_ingest_flow_html(
                selected["steps"], selected["filename"], selected["uploaded_by"]
            )
            components.html(diagram_html, height=1800, scrolling=True)
        else:
            st.write("No runs of this type yet.")


@st.dialog("Document viewer", width="large", on_dismiss="rerun")
def _kb_document_dialog(doc_id: str) -> None:
    versions = get_document_versions(doc_id)
    active_version = next((v for v in versions if v["status"] == "active"), None)

    st.markdown(f"### {doc_id}")

    if versions:
        version_options = {f"v{v['version']} ({v['status']})": v["version"] for v in versions}
        selected_label = st.selectbox("Version", list(version_options.keys()), key="nrg_kb_version_select")
        selected_version = version_options[selected_label]
    else:
        selected_version = None

    try:
        html_content, fmt = get_document_content(doc_id, version=selected_version)
        components.html(html_content, height=500, scrolling=True)
    except ValueError as e:
        st.error(str(e))

    if active_version:
        st.caption(f"Currently active: v{active_version['version']}, uploaded by {active_version['uploaded_by'] or 'bulk-ingest-script'}")


def _render_kb_tab() -> None:
    st.subheader("Knowledge base")
    st.caption(
        "Search, upload, and view documents backing the copilot's retrieval. Uploading a document "
        "whose doc_id already exists creates a new version and publishes an async re-index event -- "
        "see the **Flow** tab's Ingestion runs for the live async pipeline trace."
    )

    kb_browse_tab, kb_upload_tab = st.tabs(["Browse / Search", "Upload"])

    with kb_browse_tab:
        kb_query = st.text_input("Search (leave blank to browse all documents)", key="nrg_kb_search_query")

        if kb_query.strip():
            kb_results = search_kb(kb_query.strip())
            st.caption(f"{len(kb_results)} result(s) for \"{kb_query.strip()}\"")
            for i, r in enumerate(kb_results):
                with st.container(border=True):
                    st.markdown(f"**{r['doc_id']}** — {r['title']} (v{r.get('version', '?')}, {r['doc_type']})")
                    st.caption(f"Fusion score: {r.get('fusion_score')} · Rerank score: {r.get('rerank_score')} · Uploaded by: {r.get('uploaded_by') or 'n/a'}")
                    st.text(r["excerpt"])
                    if st.button("Open in viewer", key=f"nrg_view_from_search_{i}_{r['doc_id']}"):
                        st.session_state.nrg_selected_kb_doc = r["doc_id"]
                        st.rerun()
        else:
            all_docs = list_all_kb_documents()
            if not all_docs:
                st.write("No documents in the knowledge base yet.")
            else:
                st.caption(f"{len(all_docs)} document(s) total")
                st.dataframe(
                    [
                        {
                            "Doc ID": d["doc_id"],
                            "Title": d["title"],
                            "Type": d["doc_type"],
                            "Plan Type": d["plan_type"] or "—",
                            "Version": d["version"],
                            "Uploaded by": d["uploaded_by"] or "n/a",
                        }
                        for d in all_docs
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                doc_ids = [d["doc_id"] for d in all_docs]
                selected_doc_id = st.selectbox("Select a document to view", doc_ids, key="nrg_kb_browse_select")
                if st.button("Open in viewer", key="nrg_kb_open_viewer"):
                    st.session_state.nrg_selected_kb_doc = selected_doc_id
                    st.rerun()

    with kb_upload_tab:
        uploaded_file = st.file_uploader("Upload a document (.md or .pdf)", type=["md", "pdf"], key="nrg_kb_uploader")
        uploaded_by = st.text_input("Uploaded by", value="KB Curator", key="nrg_kb_uploaded_by")

        if uploaded_file is not None and st.button("Ingest document", type="primary", key="nrg_kb_ingest_btn"):
            file_bytes = uploaded_file.getvalue()
            filename = uploaded_file.name
            status_box = st.status(f"Ingesting {filename}...", expanded=True)
            steps = []
            gen = ingest_document(file_bytes, filename, uploaded_by.strip() or "Unknown")
            result = None
            try:
                while True:
                    step = next(gen)
                    steps.append(step)
                    status_box.write(f"**{step.stage}** — {step.detail}")
            except StopIteration as stop:
                result = stop.value
            except ValueError as e:
                status_box.update(label=f"Ingestion failed: {e}", state="error")
                steps.append(None)

            st.session_state.nrg_ingest_history.insert(
                0,
                {
                    "filename": filename,
                    "steps": [s for s in steps if s is not None],
                    "uploaded_by": uploaded_by.strip() or "Unknown",
                    "at": datetime.now(),
                },
            )
            st.session_state.nrg_selected_ingest_index = 0
            st.session_state.nrg_selected_flow_kind = "ingest"

            if result is not None:
                status_box.update(
                    label=f"Published — {result.doc_id} v{result.version} "
                    f"({'new version' if result.is_new_version else 'no change'})",
                    state="complete",
                )
                if result.status == "processing":
                    st.warning(
                        f"{result.doc_id} v{result.version} published to RabbitMQ for async indexing -- "
                        "not yet searchable until scripts/consume_ingestion_events.py processes it. "
                        "See the Flow tab's Ingestion runs for live status."
                    )
                else:
                    st.info(f"{result.doc_id}: identical content already active as version {result.version} -- nothing changed.")

    if st.session_state.nrg_selected_kb_doc:
        doc_to_view = st.session_state.nrg_selected_kb_doc
        st.session_state.nrg_selected_kb_doc = None
        _kb_document_dialog(doc_to_view)


def _render_compliance_tab() -> None:
    st.subheader("Compliance / Legal sampling review")
    st.caption(
        "Statistical sampling, not a per-answer gate: every answer is logged and delivered to the "
        "user immediately, before any reviewer ever sees it here. Marking a review below only "
        "annotates the record -- it never changes what the user already received. Matches "
        "NRG_Energy_Architecture_Deep_Dive.md's §2.1/§3 design contrast with the Novartis project's "
        "mandatory per-answer review."
    )

    sample_mode = st.radio(
        "Sample from:", ["Most recent", "Random sample"], horizontal=True, key="nrg_compliance_sample_mode"
    )
    limit = st.slider("Number of answers to show", 5, 50, 10, key="nrg_compliance_limit")

    if st.button("Refresh sample", key="nrg_compliance_refresh"):
        st.rerun()

    rows = (
        list_random_sampled_answers(limit)
        if sample_mode == "Random sample"
        else list_recent_sampled_answers(limit)
    )

    if not rows:
        st.write("No sampled answers yet -- ask a question in the **Ask** tab first.")
        return

    reviewed_count = sum(1 for r in rows if r["reviewed"])
    st.caption(f"{len(rows)} shown, {reviewed_count} already reviewed in this sample")

    for row in rows:
        with st.container(border=True):
            header = f"**#{row['id']}** — _{row['created_at']}_"
            if row["reviewed"]:
                verdict_emoji = "accurate" if row["review_verdict"] == "accurate" else "inaccurate"
                header += f" — already reviewed: **{verdict_emoji}** by {row['reviewed_by']}"
            st.markdown(header)
            st.markdown(f"**Question:** {row['question']}")
            with st.expander("Answer"):
                st.markdown(row["answer"])
                st.caption(
                    f"Classified: {row['doc_type_classified'] or 'unclassified'} · "
                    f"Confidence: {row['confidence']} · Citations: {row['citations']}"
                )
            if row["reviewed"] and row["review_notes"]:
                st.caption(f"Reviewer notes: {row['review_notes']}")

            if not row["reviewed"]:
                col1, col2, col3 = st.columns([2, 2, 3])
                reviewer_name = col1.text_input(
                    "Reviewer name", key=f"nrg_reviewer_{row['id']}", value="Compliance Reviewer"
                )
                notes = col3.text_input("Notes (optional)", key=f"nrg_notes_{row['id']}")
                if col2.button("Mark accurate", key=f"nrg_accurate_{row['id']}"):
                    if reviewer_name.strip():
                        record_sample_review(row["id"], reviewer_name.strip(), "accurate", notes.strip())
                        st.success(f"#{row['id']} marked accurate.")
                        st.rerun()
                    else:
                        st.warning("Enter a reviewer name first.")
                if col2.button("Mark inaccurate", key=f"nrg_inaccurate_{row['id']}"):
                    if reviewer_name.strip():
                        record_sample_review(row["id"], reviewer_name.strip(), "inaccurate", notes.strip())
                        st.warning(f"#{row['id']} marked inaccurate.")
                        st.rerun()
                    else:
                        st.warning("Enter a reviewer name first.")


def _render_audit_tab() -> None:
    from nrg_retrieval.audit import verify_chain
    from nrg_retrieval.postgres_client import get_pg_connection

    st.subheader("Immutable, hash-chained audit log")
    st.caption(
        "Every document ingestion and every compliance review annotation is chained via SHA-256 "
        "(each row hashes its own content + the previous row's hash). The DB also enforces "
        "insert-only at the trigger level."
    )

    if st.button("Verify chain integrity", key="nrg_verify_chain_btn"):
        conn = get_pg_connection()
        valid, err = verify_chain(conn)
        conn.close()
        if valid:
            st.success("Chain is VALID — no tampering detected.")
        else:
            st.error(f"Chain is TAMPERED: {err}")

    conn = get_pg_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, event_type, actor, created_at, record_hash "
            "FROM audit_log ORDER BY id DESC LIMIT 50"
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        st.write("No audit log entries yet — ingest a document or review a sampled answer to create one.")
    else:
        st.dataframe(
            [
                {
                    "ID": r[0],
                    "Event": r[1],
                    "Actor": r[2],
                    "Timestamp": r[3],
                    "Hash (truncated)": r[4][:16] + "...",
                }
                for r in rows
            ],
            use_container_width=True,
            hide_index=True,
        )


def render() -> None:
    """Entry point called by both nrg_app.py (standalone) and
    shell/nrg_wrapper.py (embedded shell) -- assumes st.set_page_config()
    has already been called exactly once by the caller.
    """
    _init_session_state()

    st.title("NRG Energy Retail & Operations Knowledge Copilot — Local Demo")
    st.caption(
        "LangChain classification+retrieval chain → Qdrant hybrid search (dense+sparse+RRF) → "
        "gpt-4o-mini generation. Statistical-sampling human-in-the-loop, not a mandatory gate."
    )

    tab_ask, tab_flow, tab_kb, tab_compliance, tab_audit = st.tabs(
        ["Ask", "Flow", "Knowledge Base", "Compliance Review", "Audit Log"]
    )

    with tab_ask:
        _render_ask_tab()
    with tab_flow:
        _render_flow_tab()
    with tab_kb:
        _render_kb_tab()
    with tab_compliance:
        _render_compliance_tab()
    with tab_audit:
        _render_audit_tab()

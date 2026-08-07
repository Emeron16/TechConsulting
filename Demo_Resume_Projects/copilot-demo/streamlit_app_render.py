"""Streamlit UI body -- extracted from streamlit_app.py's former module-
scope tab logic into a callable render() function (Phase 9 of
../NRG_Implementation_Plan.md), so the shared multi-demo shell
(../shell/shell_app.py) can call this exact same UI without either
duplicating ~420 lines of tab logic or triggering a second
st.set_page_config() call (Streamlit raises if that's called more than
once per session).

This is a pure code-movement extraction, not a behavior change: every
line below is identical to what streamlit_app.py used to run directly at
module scope. streamlit_app.py itself is now just
`st.set_page_config(...)` + `render()`, preserving standalone
`streamlit run streamlit_app.py` behavior exactly as before.

Reuses the exact same orchestration path as scripts/ask.py
(copilot_agents.ask_flow.run_question) and the exact same review actions as
scripts/review.py (mcp_servers.review_actions) -- no logic is duplicated
here, only presentation.
"""
import asyncio
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from copilot_agents.ask_flow import run_question
from copilot_agents.flow_diagram import render_flow_html
from copilot_agents.ingest_flow_diagram import render_ingest_flow_html
from copilot_agents.kb_ingest import ingest_document
from copilot_agents.tracing_setup import enable_langsmith_tracing
from mcp_servers.audit import verify_chain
from mcp_servers.common import get_pg_connection
from mcp_servers.kb_actions import (
    get_document_content,
    get_document_versions,
    list_all_kb_documents,
    search_kb,
    soft_delete_document,
)
from mcp_servers.review_actions import approve, get_by_id, list_history, list_pending, reject


def render() -> None:
    """Entry point called by both streamlit_app.py (standalone) and
    shell/novartis_wrapper.py (embedded shell) -- assumes
    st.set_page_config() has already been called exactly once by the
    caller.
    """
    if "tracing_enabled" not in st.session_state:
        st.session_state.tracing_enabled = enable_langsmith_tracing()
    if "run_history" not in st.session_state:
        st.session_state.run_history = []  # list of {"question": str, "result": AskResult, "asked_at": datetime}
    if "selected_run_index" not in st.session_state:
        st.session_state.selected_run_index = None
    if "ingest_history" not in st.session_state:
        st.session_state.ingest_history = []  # list of {"filename": str, "steps": [IngestStep], "uploaded_by": str, "at": datetime}
    if "selected_ingest_index" not in st.session_state:
        st.session_state.selected_ingest_index = None
    if "selected_flow_kind" not in st.session_state:
        st.session_state.selected_flow_kind = None  # "query" | "ingest"
    if "selected_kb_doc" not in st.session_state:
        st.session_state.selected_kb_doc = None  # doc_id currently open in the KB viewer

    st.title("Multi-Agent CMC Quality Copilot — Local Demo")
    st.caption(
        "Supervisor → 4 specialist agents → MCP-governed tools → ChromaDB/Postgres. "
        f"LangSmith tracing: {'enabled' if st.session_state.tracing_enabled else 'disabled'}."
    )

    tab_ask, tab_flow, tab_kb, tab_review, tab_audit = st.tabs(
        ["Ask", "Flow", "Knowledge Base", "Review Queue", "Audit Log"]
    )

    # ---------------------------------------------------------------------------
    # Ask tab
    # ---------------------------------------------------------------------------
    with tab_ask:
        st.subheader("Ask the copilot")
        example_questions = [
            "Does deviation DEV-2201 meet SOP-114 escalation criteria?",
            "What is the current status and monitoring window for CAPA-3390?",
            "What does SOP-089 say about releasing a batch with an open deviation?",
            "What is the disposition status of BATCH-4471?",
        ]
        selected_example = st.selectbox(
            "Try an example question, or type your own below:",
            ["(type my own)"] + example_questions,
        )
        default_text = "" if selected_example == "(type my own)" else selected_example
        question = st.text_area("Question", value=default_text, height=80)

        if st.button("Ask", type="primary", disabled=not question.strip()):
            with st.spinner("Supervisor routing to specialist agent, calling MCP tools..."):
                result = asyncio.run(run_question(question.strip()))

            st.session_state.run_history.insert(
                0, {"question": question.strip(), "result": result, "asked_at": datetime.now()}
            )
            st.session_state.selected_run_index = 0
            st.session_state.selected_flow_kind = "query"

            st.markdown("### Answer")
            st.markdown(result.final_answer)

            with st.expander("Agent path (Supervisor → specialist → tool calls)"):
                for step in result.trace_steps:
                    if step.step_type == "handoff":
                        st.text(f"[{step.agent_name}] handoff -> {step.target_agent}")
                    elif step.step_type == "tool_call":
                        st.text(f"[{step.agent_name}] tool_call: {step.tool_name}({step.arguments})")
                    elif step.step_type == "message":
                        st.text(f"[{step.agent_name}] message")

            st.info("See the **Flow** tab for a full visual pipeline diagram of this run.")

            if result.published_for_review:
                st.info(
                    f"This answer was drafted by **{result.responding_agent_name}** and has been "
                    "sent to the **Review Queue** tab for human sign-off before it becomes an "
                    "official record."
                )

    # ---------------------------------------------------------------------------
    # Flow tab
    # ---------------------------------------------------------------------------
    def _lookup_review_status(review_queue_id: int) -> dict | None:
        """Looks up this run's own review_queue row by id -- not by question
        text, which would collide across repeated identical questions (e.g. the
        example questions) and show a stale approval/rejection from an unrelated
        earlier run.
        """
        item = get_by_id(review_queue_id)
        if item is None:
            return None
        if item["status"] == "pending":
            return {"status": "pending"}
        return {
            "status": item["status"],
            "reviewed_by": item["reviewed_by"],
            "reason": "",
        }

    with tab_flow:
        st.subheader("Pipeline flow")
        st.caption(
            "Visualizes exactly what happened for a given question or document upload -- every "
            "handoff/tool call/ingestion step with real data, and the human-review or versioning "
            "outcome. Greyed/dashed boxes are original-architecture layers not implemented locally."
        )

        has_queries = bool(st.session_state.run_history)
        has_ingests = bool(st.session_state.ingest_history)

        if not has_queries and not has_ingests:
            st.write("Nothing to show yet — ask a question in the **Ask** tab or upload a document in the **Knowledge Base** tab.")
        else:
            col_list, col_diagram = st.columns([1, 3])

            with col_list:
                if has_queries:
                    st.markdown("**Query runs**")
                    for i, run in enumerate(st.session_state.run_history):
                        label = f"{run['asked_at'].strftime('%H:%M:%S')} — {run['question'][:40]}"
                        is_selected = st.session_state.selected_flow_kind == "query" and i == st.session_state.selected_run_index
                        if st.button(label, key=f"run_{i}", type="primary" if is_selected else "secondary", use_container_width=True):
                            st.session_state.selected_run_index = i
                            st.session_state.selected_flow_kind = "query"
                            st.rerun()

                if has_ingests:
                    st.markdown("**Ingestion runs**")
                    for i, run in enumerate(st.session_state.ingest_history):
                        label = f"{run['at'].strftime('%H:%M:%S')} — {run['filename']}"
                        is_selected = st.session_state.selected_flow_kind == "ingest" and i == st.session_state.get("selected_ingest_index")
                        if st.button(label, key=f"ingest_{i}", type="primary" if is_selected else "secondary", use_container_width=True):
                            st.session_state.selected_ingest_index = i
                            st.session_state.selected_flow_kind = "ingest"
                            st.rerun()

            with col_diagram:
                kind = st.session_state.selected_flow_kind
                if kind is None:
                    kind = "query" if has_queries else "ingest"

                if kind == "query" and has_queries:
                    idx = st.session_state.selected_run_index
                    if idx is None or idx >= len(st.session_state.run_history):
                        idx = 0
                    selected = st.session_state.run_history[idx]
                    review_status = (
                        _lookup_review_status(selected["result"].review_queue_id)
                        if selected["result"].published_for_review
                        else None
                    )
                    diagram_html = render_flow_html(selected["result"], selected["question"], review_status)
                    components.html(diagram_html, height=2200, scrolling=True)
                elif kind == "ingest" and has_ingests:
                    idx = st.session_state.get("selected_ingest_index")
                    if idx is None or idx >= len(st.session_state.ingest_history):
                        idx = 0
                    selected = st.session_state.ingest_history[idx]
                    diagram_html = render_ingest_flow_html(
                        selected["steps"], selected["filename"], selected["uploaded_by"]
                    )
                    components.html(diagram_html, height=1600, scrolling=True)
                else:
                    st.write("No runs of this type yet.")

    # ---------------------------------------------------------------------------
    # Knowledge Base tab
    # ---------------------------------------------------------------------------
    @st.dialog("Document viewer", width="large", on_dismiss="rerun")
    def _kb_document_dialog(doc_id: str) -> None:
        versions = get_document_versions(doc_id)
        active_version = next((v for v in versions if v["status"] == "active"), None)

        st.markdown(f"### {doc_id}")

        if versions:
            version_options = {f"v{v['version']} ({v['status']})": v["version"] for v in versions}
            selected_label = st.selectbox("Version", list(version_options.keys()), key="kb_version_select")
            selected_version = version_options[selected_label]
        else:
            st.caption("Bulk-ingested via the CLI corpus — no version history tracked (only one file exists).")
            selected_version = None

        try:
            html_content, fmt = get_document_content(doc_id, version=selected_version)
            components.html(html_content, height=500, scrolling=True)
        except ValueError as e:
            st.error(str(e))

        if active_version and (selected_version is None or selected_version == active_version["version"]):
            st.warning("Deleting removes this document from search/retrieval. The file and version history are kept for audit purposes.")
            deleted_by = st.text_input("Deleted by", value="KB Curator", key="kb_delete_by")
            if st.button("Delete this document", type="secondary", key="kb_delete_btn"):
                ok, msg = soft_delete_document(doc_id, deleted_by.strip() or "Unknown")
                (st.success if ok else st.error)(msg)
                if ok:
                    st.session_state.selected_kb_doc = None
                    st.rerun()
        elif not versions:
            st.caption(
                "This document has no kb_documents version record, so it can't be deleted through "
                "the GUI yet -- remove it from data/synthetic_docs/ and re-run scripts/ingest.py "
                "--full to remove it from the corpus."
            )

    with tab_kb:
        st.subheader("Knowledge base")
        st.caption(
            "Search, upload, view, and manage documents backing the agents' retrieval. Uploading a "
            "document whose doc_id already exists creates a new version and marks the prior one "
            "superseded -- it's never silently overwritten. See the **Flow** tab's Ingestion runs "
            "for a live step-by-step trace of any upload."
        )

        kb_browse_tab, kb_upload_tab = st.tabs(["Browse / Search / Manage", "Upload"])

        with kb_browse_tab:
            kb_query = st.text_input("Search (leave blank to browse all documents)", key="kb_search_query")

            if kb_query.strip():
                kb_results = search_kb(kb_query.strip())
                st.caption(f"{len(kb_results)} result(s) for \"{kb_query.strip()}\"")
                if not kb_results:
                    st.write("No matching documents.")
                for i, r in enumerate(kb_results):
                    with st.container(border=True):
                        st.markdown(f"**{r['doc_id']}** — {r['title']} (v{r.get('version', '?')}, {r['doc_type']})")
                        st.caption(f"Relevance: {r['relevance_score']} · Uploaded by: {r.get('uploaded_by') or 'n/a'}")
                        st.text(r["excerpt"][:300])
                        if st.button("Open in viewer", key=f"view_from_search_{i}_{r['doc_id']}"):
                            st.session_state.selected_kb_doc = r["doc_id"]
                            st.rerun()
            else:
                all_docs = list_all_kb_documents()
                if not all_docs:
                    st.write("No documents in the knowledge base yet.")
                else:
                    page_size = 10
                    total_pages = max(1, (len(all_docs) + page_size - 1) // page_size)
                    page = st.number_input(
                        "Page", min_value=1, max_value=total_pages, value=1, step=1, key="kb_browse_page"
                    )
                    start = (page - 1) * page_size
                    page_docs = all_docs[start : start + page_size]

                    st.caption(f"{len(all_docs)} document(s) total — page {page} of {total_pages}")
                    st.dataframe(
                        [
                            {
                                "Doc ID": d["doc_id"],
                                "Title": d["title"],
                                "Type": d["doc_type"],
                                "Version": d["version"],
                                "Uploaded by": d["uploaded_by"] or "n/a (bulk-ingested corpus)",
                                "Uploaded at": d["uploaded_at"],
                            }
                            for d in page_docs
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    doc_ids = [d["doc_id"] for d in page_docs]
                    selected_doc_id = st.selectbox("Select a document to view/manage", doc_ids, key="kb_browse_select")
                    if st.button("Open in viewer", key="kb_open_viewer"):
                        st.session_state.selected_kb_doc = selected_doc_id
                        st.rerun()

        with kb_upload_tab:
            uploaded_file = st.file_uploader("Upload a document (.md or .html)", type=["md", "html"])
            uploaded_by = st.text_input("Uploaded by", value="KB Curator", key="kb_uploaded_by")

            if uploaded_file is not None and st.button("Ingest document", type="primary"):
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

                st.session_state.ingest_history.insert(
                    0,
                    {
                        "filename": filename,
                        "steps": [s for s in steps if s is not None],
                        "uploaded_by": uploaded_by.strip() or "Unknown",
                        "at": datetime.now(),
                    },
                )
                st.session_state.selected_ingest_index = 0
                st.session_state.selected_flow_kind = "ingest"

                if result is not None:
                    status_box.update(
                        label=f"Done — {result.doc_id} v{result.version} "
                        f"({'new version' if result.is_new_version else 'no change'})",
                        state="complete",
                    )
                    if result.is_new_version:
                        st.success(f"{result.doc_id} ingested as version {result.version}.")
                    else:
                        st.info(f"{result.doc_id}: identical content already active as version {result.version} -- nothing changed.")
                    st.info("See the **Flow** tab's Ingestion runs for the full step-by-step trace.")

        # -- Viewer dialog: opens as a full modal overlay (not inline below the
        # list) whenever a document is selected from Search or Browse above.
        # on_dismiss="rerun" means closing via X/click-outside/ESC triggers a
        # rerun of the whole script -- clear selected_kb_doc *before* calling
        # the dialog so that rerun starts with it already unset and the dialog
        # doesn't pop back open on the very next unrelated interaction.
        if st.session_state.selected_kb_doc:
            doc_to_view = st.session_state.selected_kb_doc
            st.session_state.selected_kb_doc = None
            _kb_document_dialog(doc_to_view)

    # ---------------------------------------------------------------------------
    # Review Queue tab
    # ---------------------------------------------------------------------------
    with tab_review:
        st.subheader("Pending review")
        st.caption(
            "Deviation Review and CAPA Decision Support agent outputs require human review "
            "before becoming official records (matches the original architecture's QP sign-off "
            "requirement)."
        )

        if st.button("Refresh queue"):
            st.rerun()

        pending = list_pending()
        if not pending:
            st.write("No pending items.")
        else:
            for item in pending:
                with st.container(border=True):
                    st.markdown(f"**#{item['id']}** — {item['agent_name']} — _{item['created_at']}_")
                    st.markdown(f"**Question:** {item['question']}")
                    with st.expander("Draft answer"):
                        st.markdown(item["draft_answer"])

                    col1, col2, col3 = st.columns([2, 2, 3])
                    reviewer_name = col1.text_input(
                        "Reviewer name", key=f"reviewer_{item['id']}", value="Jane QP Reviewer"
                    )
                    if col2.button("Approve", key=f"approve_{item['id']}"):
                        if reviewer_name.strip():
                            success, message, audit_id = approve(item["id"], reviewer_name.strip())
                            (st.success if success else st.error)(message)
                            if success:
                                st.caption(f"E-signature recorded — audit_log id={audit_id}")
                            st.rerun()
                        else:
                            st.warning("Enter a reviewer name first.")

                    reason = col3.text_input("Rejection reason (if rejecting)", key=f"reason_{item['id']}")
                    if col3.button("Reject", key=f"reject_{item['id']}"):
                        if reviewer_name.strip() and reason.strip():
                            success, message, audit_id = reject(
                                item["id"], reviewer_name.strip(), reason.strip()
                            )
                            (st.success if success else st.error)(message)
                            if success:
                                st.caption(f"Rejection recorded — audit_log id={audit_id}")
                            st.rerun()
                        else:
                            st.warning("Reviewer name and rejection reason are both required.")

        st.subheader("Recent history")
        history = list_history()
        if not history:
            st.write("No reviewed items yet.")
        else:
            st.dataframe(
                [
                    {
                        "ID": h["id"],
                        "Agent": h["agent_name"],
                        "Question": h["question"][:60],
                        "Status": h["status"],
                        "Reviewed by": h["reviewed_by"],
                        "Reviewed at": h["reviewed_at"],
                    }
                    for h in history
                ],
                use_container_width=True,
                hide_index=True,
            )

    # ---------------------------------------------------------------------------
    # Audit Log tab
    # ---------------------------------------------------------------------------
    with tab_audit:
        st.subheader("Immutable, hash-chained audit log")
        st.caption(
            "Every approval/rejection is chained via SHA-256 (each row hashes its own content + "
            "the previous row's hash). The DB also enforces insert-only at the trigger level."
        )

        if st.button("Verify chain integrity"):
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
            st.write("No audit log entries yet.")
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

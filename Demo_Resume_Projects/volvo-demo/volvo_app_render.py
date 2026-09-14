"""Volvo Dealer Service & Warranty Intelligence Platform -- Streamlit UI
body, factored into a callable render() from the start (matching
nrg-demo's from-day-one pattern). render() is called by both volvo_app.py
(standalone) and shell/volvo_wrapper.py (embedded in the multi-demo
shell).

Unlike the other two demos, the live "Submit New Case" path doesn't call
any orchestration function in-process -- it triggers a real Airflow DAG
run via volvo_pipeline.dag_client and polls its task-instance states, per
Volvo_Implementation_Plan.md's FastAPI+Airflow architecture decision. Only
this tab depends on Airflow/FastAPI actually running; Case Lookup and the
other tabs read directly from Postgres/OpenSearch.

session_state keys are prefixed volvo_ throughout, matching nrg_'s own
prefixing convention, so this renders safely inside the same Streamlit
session as the other two demos via the shell.
"""
import time
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from volvo_pipeline.dag_client import get_dag_run_state, get_task_instances, trigger_dag_run, list_recent_dag_runs
from volvo_retrieval.audit import append_audit_entry, verify_chain
from volvo_retrieval.case_search import find_similar_cases, list_all_cases, search_by_keyword, search_by_vin
from volvo_retrieval.opensearch_client import ensure_index
from volvo_retrieval.postgres_client import (
    get_pg_connection,
    insert_airflow_dag_run,
    list_escalations,
    record_escalation_review,
    update_airflow_dag_run_state,
)
from volvo_models.labels import CATEGORIES

# Airflow task_id -> friendly label + order, used by the Submit New Case
# tab's live-progress display. Matches volvo_pipeline/schemas.py's CaseStep
# stage vocabulary and airflow/dags/volvo_case_pipeline_dag.py's task_ids.
PIPELINE_STAGES = [
    ("preprocess", "Preprocessing narrative text"),
    ("classify", "Classifying (multi-label BERT)"),
    ("extract_entities", "Extracting entities (spaCy NER)"),
    ("embed", "Generating similarity embedding (Sentence-BERT)"),
    ("find_similar_cases", "Searching for similar historical cases"),
    ("index_and_check_escalation", "Indexing + checking safety escalation"),
]


def _init_session_state() -> None:
    if "volvo_selected_case_id" not in st.session_state:
        st.session_state.volvo_selected_case_id = None
    if "volvo_submit_history" not in st.session_state:
        st.session_state.volvo_submit_history = []  # list of {"case_id", "result", "submitted_at"}
    if "volvo_search_results" not in st.session_state:
        st.session_state.volvo_search_results = None


@st.dialog("Case detail", width="large", on_dismiss="rerun")
def _case_detail_dialog(case: dict) -> None:
    st.markdown(f"### {case['case_id']}")
    st.caption(f"VIN: `{case['vin']}`")

    cols = st.columns(3)
    cols[0].metric("Vehicle", case.get("vehicle_model") or "—")
    cols[1].metric("Model year", case.get("model_year") or "—")
    cols[2].metric("Mileage", case.get("mileage") or "—")

    st.markdown("**Narrative**")
    st.write(case.get("narrative_text", ""))

    st.markdown("**Classifications**")
    categories = case.get("categories", [])
    if categories:
        st.write(", ".join(f"`{c}`" for c in categories))
    else:
        st.caption("No categories assigned.")

    entities = case.get("entities", [])
    st.markdown("**Extracted entities**")
    if entities:
        for e in entities:
            st.write(f"- **{e['label']}**: {e['text']}")
    else:
        st.caption("No entities extracted.")

    dealer_location = case.get("dealer_location")
    if dealer_location:
        st.caption(f"Dealer: {dealer_location}")

    st.markdown("**Similar historical cases**")
    vector = case.get("narrative_vector")
    if vector:
        client = ensure_index()
        similar = [c for c in find_similar_cases(client, vector, k=6) if c["case_id"] != case["case_id"]][:5]
        if similar:
            for s in similar:
                st.write(f"- `{s['case_id']}` ({', '.join(s['categories'])}) — score {s['score']:.3f}")
        else:
            st.caption("No similar cases found.")
    else:
        st.caption("No embedding available for similarity lookup.")


def _render_case_lookup_tab() -> None:
    st.subheader("Case Lookup / Search")
    st.caption(
        "Search by VIN (exact match), symptom/component keyword, or category. Mirrors the Dealer Case "
        "Management UI integration described in the architecture doc."
    )

    search_mode = st.radio("Search by", ["Symptom / keyword", "VIN"], horizontal=True, key="volvo_search_mode")

    client = ensure_index()

    if search_mode == "VIN":
        vin_query = st.text_input("VIN", key="volvo_vin_query")
        if st.button("Search", key="volvo_vin_search_btn"):
            st.session_state.volvo_search_results = search_by_vin(client, vin_query.strip()) if vin_query.strip() else []
    else:
        keyword_query = st.text_input("Symptom / component / keyword", key="volvo_keyword_query")
        category_filter = st.multiselect("Filter by category", list(CATEGORIES), key="volvo_category_filter")
        dealer_filter = st.text_input("Filter by dealer location (optional)", key="volvo_dealer_filter")
        if st.button("Search", key="volvo_keyword_search_btn"):
            if keyword_query.strip():
                st.session_state.volvo_search_results = search_by_keyword(
                    client,
                    keyword_query.strip(),
                    categories=category_filter or None,
                    dealer_location=dealer_filter.strip() or None,
                )
            else:
                st.session_state.volvo_search_results = list_all_cases(client, size=200)

    if st.button("Browse all cases", key="volvo_browse_all_btn"):
        st.session_state.volvo_search_results = list_all_cases(client, size=200)

    results = st.session_state.volvo_search_results
    if results is not None:
        st.caption(f"{len(results)} result(s)")
        for case in results:
            cols = st.columns([3, 2, 2, 1])
            cols[0].write(f"**{case['case_id']}** — {case.get('narrative_text', '')[:80]}")
            cols[1].write(", ".join(f"`{c}`" for c in case.get("categories", [])) or "—")
            cols[2].write(case.get("vin", ""))
            if cols[3].button("View", key=f"volvo_view_{case['case_id']}"):
                _case_detail_dialog(case)


def _poll_dag_run(dag_run_id: str, status_box, timeout_seconds: float = 60.0) -> tuple[str, list]:
    """Polls Airflow's task-instance states until the DAG run reaches a
    terminal state (success/failed) or timeout_seconds elapses, rendering
    each PIPELINE_STAGES entry's progress into status_box as it updates.
    Returns (final_state, last_task_instances).
    """
    seen_states: dict[str, str] = {}
    deadline = time.monotonic() + timeout_seconds
    task_instances: list = []

    while time.monotonic() < deadline:
        state = get_dag_run_state(dag_run_id)
        task_instances = get_task_instances(dag_run_id)

        for task_id, label in PIPELINE_STAGES:
            task_state = next((t["state"] for t in task_instances if t["task_id"] == task_id), None)
            if task_state and seen_states.get(task_id) != task_state:
                seen_states[task_id] = task_state
                icon = {"success": "✅", "running": "⏳", "failed": "❌", "upstream_failed": "⛔"}.get(task_state, "•")
                status_box.write(f"{icon} **{label}** — {task_state}")

        if state in ("success", "failed"):
            return state, task_instances

        time.sleep(1.5)

    return "timeout", task_instances


def _render_submit_new_case_tab() -> None:
    st.subheader("Submit New Case")
    st.caption(
        "Triggers a real Airflow DAG run (preprocess → classify → NER → embed → similarity search → "
        "index/escalation-check), polled live via Airflow's REST API -- not an in-process function call."
    )

    with st.form("volvo_submit_case_form"):
        vin = st.text_input("VIN", value="", key="volvo_new_vin")
        narrative_text = st.text_area("Warranty narrative", key="volvo_new_narrative", height=100)
        cols = st.columns(4)
        dealer_location = cols[0].text_input("Dealer location", key="volvo_new_dealer")
        vehicle_model = cols[1].text_input("Vehicle model", key="volvo_new_model")
        model_year = cols[2].number_input("Model year", min_value=2015, max_value=2027, value=2023, key="volvo_new_year")
        mileage = cols[3].number_input("Mileage", min_value=0, value=10000, step=1000, key="volvo_new_mileage")
        submitted_by = st.text_input("Submitted by", value="Dealer Analyst", key="volvo_new_submitted_by")
        submitted = st.form_submit_button("Submit case", type="primary")

    if submitted:
        if not vin.strip() or not narrative_text.strip():
            st.error("VIN and narrative text are required.")
            return

        case_id = f"CASE-LIVE-{int(time.time())}"
        case_data = {
            "case_id": case_id,
            "vin": vin.strip(),
            "narrative_text": narrative_text.strip(),
            "submitted_by": submitted_by.strip() or "Unknown",
            "dealer_location": dealer_location.strip() or None,
            "vehicle_model": vehicle_model.strip() or None,
            "model_year": int(model_year),
            "mileage": int(mileage),
        }

        status_box = st.status(f"Processing {case_id}...", expanded=True)
        try:
            dag_run_id = trigger_dag_run(case_data)
            status_box.write(f"Triggered Airflow DAG run: `{dag_run_id}`")

            conn = get_pg_connection()
            insert_airflow_dag_run(conn, case_id, dag_run_id)

            final_state, task_instances = _poll_dag_run(dag_run_id, status_box)
            update_airflow_dag_run_state(conn, dag_run_id, final_state)
            conn.close()

            if final_state == "success":
                status_box.update(label=f"{case_id} processed successfully.", state="complete")
            elif final_state == "timeout":
                status_box.update(label=f"{case_id} timed out waiting for the DAG run.", state="error")
            else:
                status_box.update(label=f"{case_id} failed during processing.", state="error")

            st.session_state.volvo_submit_history.insert(
                0,
                {
                    "case_id": case_id,
                    "dag_run_id": dag_run_id,
                    "final_state": final_state,
                    "task_instances": task_instances,
                    "submitted_at": datetime.now(),
                },
            )
        except Exception as e:
            status_box.update(label=f"Failed to trigger/poll DAG run: {e}", state="error")
            st.error(
                "Could not reach Airflow or FastAPI. Confirm both are running: "
                "`docker compose -f airflow/docker-compose.airflow.yml up -d` and "
                "`uvicorn api.main:app --port 8100`."
            )
            return

        if final_state == "success":
            client = ensure_index()
            results = search_by_vin(client, vin.strip())
            if results:
                case = results[0]
                st.success(f"Case `{case_id}` indexed.")
                categories = case.get("categories", [])
                if categories:
                    st.write("**Classified as:** " + ", ".join(f"`{c}`" for c in categories))
                if "safety_concern" in categories:
                    st.warning("⚠️ This case was flagged as a safety concern and routed to the Safety Escalation Review queue.")
                if st.button("View full case detail", key=f"volvo_view_new_{case_id}"):
                    _case_detail_dialog(case)


def _render_safety_escalation_tab() -> None:
    st.subheader("Safety Escalation Review")
    st.caption(
        "The Service Operations Manager's review queue -- a real routing decision, not a passive "
        "annotation. A row here means either a case was directly classified safety_concern, or "
        "similarity search surfaced a recurring pattern across multiple already-flagged cases. "
        "Routine (non-safety) classifications never produce a row here at all."
    )

    show_mode = st.radio("Show", ["Pending review", "All (including resolved)"], horizontal=True, key="volvo_escalation_show_mode")
    if st.button("Refresh", key="volvo_escalation_refresh"):
        st.rerun()

    conn = get_pg_connection()
    try:
        status_filter = "pending_review" if show_mode == "Pending review" else None
        rows = list_escalations(conn, status=status_filter, limit=100)

        if not rows:
            st.write("No escalations to review." if status_filter else "No escalations recorded yet.")
            return

        pending_count = sum(1 for r in rows if r["status"] == "pending_review")
        st.caption(f"{len(rows)} shown, {pending_count} pending review")

        for row in rows:
            with st.container(border=True):
                header = f"**Escalation #{row['id']}** — case `{row['case_id']}` — _{row['raised_at']}_"
                st.markdown(header)
                st.write(f"**Trigger:** `{row['trigger_reason']}`")

                if row["trigger_reason"] == "recurring_pattern" and row["related_case_ids"]:
                    st.write("**Related already-flagged cases:** " + ", ".join(f"`{c}`" for c in row["related_case_ids"]))

                if row["status"] != "pending_review":
                    verdict_label = "Field action recommended" if row["status"] == "field_action_recommended" else "No action needed"
                    st.info(f"Already reviewed: **{verdict_label}** by {row['reviewed_by']} on {row['reviewed_at']}")
                    if row["review_notes"]:
                        st.caption(f"Notes: {row['review_notes']}")
                else:
                    reviewer = st.text_input("Reviewer name", value="Service Ops Manager", key=f"volvo_reviewer_{row['id']}")
                    notes = st.text_area("Review notes", key=f"volvo_notes_{row['id']}", height=68)
                    action_cols = st.columns(2)
                    if action_cols[0].button("Field action recommended", key=f"volvo_field_action_{row['id']}"):
                        record_escalation_review(conn, row["id"], reviewer.strip() or "Unknown", "field_action_recommended", notes.strip())
                        append_audit_entry(
                            conn,
                            event_type="safety_escalation_reviewed",
                            payload={"escalation_id": row["id"], "case_id": row["case_id"], "verdict": "field_action_recommended"},
                            actor=reviewer.strip() or "Unknown",
                        )
                        st.rerun()
                    if action_cols[1].button("No action needed", key=f"volvo_no_action_{row['id']}"):
                        record_escalation_review(conn, row["id"], reviewer.strip() or "Unknown", "no_action_needed", notes.strip())
                        append_audit_entry(
                            conn,
                            event_type="safety_escalation_reviewed",
                            payload={"escalation_id": row["id"], "case_id": row["case_id"], "verdict": "no_action_needed"},
                            actor=reviewer.strip() or "Unknown",
                        )
                        st.rerun()
    finally:
        conn.close()


def _render_flow_tab() -> None:
    diagram_choice = st.radio(
        "Diagram", ["New-Case Pipeline", "Training Pipeline"], horizontal=True, key="volvo_flow_diagram_choice"
    )

    if diagram_choice == "New-Case Pipeline":
        try:
            from volvo_pipeline.flow_diagram import render_flow_html

            st.subheader("New-Case Flow Diagram")
            if not st.session_state.volvo_submit_history:
                st.info("Submit a case in the **Submit New Case** tab first to see a real pipeline trace here.")
                return
            run = st.session_state.volvo_submit_history[0]
            html = render_flow_html(run)
            components.html(html, height=900, scrolling=True)
        except ModuleNotFoundError:
            st.info("Flow diagram module not yet built (Phase 10).")
    else:
        try:
            from volvo_pipeline.training_flow_diagram import render_training_flow_html

            st.subheader("Training Pipeline Flow Diagram")
            html = render_training_flow_html()
            components.html(html, height=700, scrolling=True)
        except ModuleNotFoundError:
            st.info("Training flow diagram module not yet built (Phase 10).")


def _render_model_info_tab() -> None:
    st.subheader("Training / Model Info")
    st.caption(
        "MLflow experiment tracking for the fine-tuned DistilBERT multi-label classifier, plus "
        "read-only Airflow DAG-run history. Neither of the other two demos in this repo has an "
        "equivalent training/experiment-tracking capability."
    )

    try:
        import os
        from pathlib import Path

        import mlflow

        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(f"file:{Path(__file__).parent / 'mlruns'}")
        runs = mlflow.search_runs(experiment_names=["volvo_warranty_classifier"])

        if runs.empty:
            st.warning("No MLflow runs found. Run `scripts/train_classifier.py` first.")
        else:
            latest = runs.iloc[0]
            st.markdown("**Latest training run**")
            cols = st.columns(4)
            cols[0].metric("Micro F1", f"{latest.get('metrics.eval_micro_f1', 0):.3f}")
            cols[1].metric("Macro F1", f"{latest.get('metrics.eval_macro_f1', 0):.3f}")
            cols[2].metric("Micro Precision", f"{latest.get('metrics.eval_micro_precision', 0):.3f}")
            cols[3].metric("Micro Recall", f"{latest.get('metrics.eval_micro_recall', 0):.3f}")

            st.caption(
                f"Trained on {int(latest.get('params.train_size', 0))} examples, "
                f"{int(latest.get('params.num_epochs', 0))} epochs, base model `{latest.get('params.base_model', '?')}`. "
                "Note: this is a small, ~100-example synthetic demo dataset -- per-category F1 varies, and "
                "one category (software_update) scored 0.0 on the held-out validation set due to thin "
                "training vocabulary. Stated plainly, not oversold."
            )

            st.markdown("**Per-category F1 (latest run)**")
            f1_cols = st.columns(4)
            for i, category in enumerate(CATEGORIES):
                metric_key = f"metrics.eval_f1_{category}"
                if metric_key in latest:
                    f1_cols[i % 4].metric(category, f"{latest[metric_key]:.2f}")

            confusion_matrix_path = Path(__file__).parent / "models" / "confusion_matrix.png"
            if confusion_matrix_path.exists():
                st.markdown("**Confusion matrix grid (per category)**")
                st.image(str(confusion_matrix_path))
    except Exception as e:
        st.warning(f"Could not load MLflow data: {e}")

    st.markdown("---")
    st.markdown("**Recent Airflow DAG runs**")
    try:
        recent_runs = list_recent_dag_runs(limit=10)
        if not recent_runs:
            st.caption("No DAG runs yet -- submit a case in the Submit New Case tab.")
        else:
            for run in recent_runs:
                state_icon = {"success": "✅", "failed": "❌", "running": "⏳"}.get(run["state"], "•")
                st.write(f"{state_icon} `{run['dag_run_id']}` — {run['state']} — started {run['start_date']}")
    except Exception as e:
        st.caption(f"Could not reach Airflow: {e}")


def _render_audit_tab() -> None:
    st.subheader("Immutable, hash-chained audit log")
    st.caption(
        "Every case submission, safety escalation, and escalation review is chained via SHA-256 "
        "(each row hashes its own content + the previous row's hash). The DB also enforces "
        "insert-only at the trigger level."
    )

    if st.button("Verify chain integrity", key="volvo_verify_chain_btn"):
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
            "SELECT id, event_type, actor, created_at, record_hash FROM audit_log ORDER BY id DESC LIMIT 50"
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        st.write("No audit log entries yet — submit a case in the Submit New Case tab first.")
        return

    for audit_id, event_type, actor, created_at, record_hash in rows:
        st.write(f"**#{audit_id}** `{event_type}` by {actor} at {created_at} — hash `{record_hash[:16]}...`")


def render() -> None:
    """Entry point called by both volvo_app.py (standalone) and
    shell/volvo_wrapper.py (embedded shell) -- assumes st.set_page_config()
    has already been called exactly once by the caller.
    """
    _init_session_state()

    st.title("Volvo Dealer Service & Warranty Intelligence Platform — Local Demo")
    st.caption(
        "Fine-tuned DistilBERT multi-label classifier + Sentence-BERT similarity + spaCy NER → "
        "OpenSearch combined index, orchestrated by a real Airflow DAG behind a FastAPI serving layer. "
        "Safety-flag-triggered escalation, not a mandatory gate or statistical sampling."
    )

    (
        tab_lookup,
        tab_submit,
        tab_escalation,
        tab_flow,
        tab_model_info,
        tab_audit,
    ) = st.tabs(
        [
            "Case Lookup / Search",
            "Submit New Case",
            "Safety Escalation Review",
            "Flow Diagram",
            "Training / Model Info",
            "Audit Log",
        ]
    )

    with tab_lookup:
        _render_case_lookup_tab()
    with tab_submit:
        _render_submit_new_case_tab()
    with tab_escalation:
        _render_safety_escalation_tab()
    with tab_flow:
        _render_flow_tab()
    with tab_model_info:
        _render_model_info_tab()
    with tab_audit:
        _render_audit_tab()

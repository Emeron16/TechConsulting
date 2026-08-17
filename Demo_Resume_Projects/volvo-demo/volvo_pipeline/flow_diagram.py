"""Renders a self-contained HTML/CSS pipeline diagram for one submitted
case, combining real data (Postgres/OpenSearch, looked up by case_id) with
static placeholder stages representing parts of the original AWS
architecture not implemented locally (IAM, CloudWatch) -- same visual
language and real/placeholder convention as the other two demos'
flow_diagram.py modules, sibling module volvo_pipeline/diagram_common.py.

Unlike NRG/Novartis, there is no in-process orchestration trace object to
read from here: the live path genuinely runs through a real Airflow DAG
(volvo_app_render.py's Submit New Case tab triggers and polls it), so this
module looks up the case's actual classification/entities/similar-cases/
escalation state directly from Postgres and OpenSearch by case_id, plus the
Airflow task-instance states already captured in the submit_history entry.
Every real stage here reflects a genuine Airflow task that ran, styled with
the real-orchestration class -- distinct from NRG's diagram, where
orchestration was a side note limited to the async ingest boundary.
"""
from volvo_pipeline.diagram_common import (
    CSS,
    REAL_TAG,
    arrow,
    entity_chips,
    esc,
    label_score_table,
    placeholder,
    score_table,
    stage,
)
from volvo_retrieval.opensearch_client import ensure_index
from volvo_retrieval.postgres_client import get_pg_connection

TASK_LABELS = {
    "preprocess": "Preprocessing narrative text",
    "classify": "Classifying (multi-label DistilBERT)",
    "extract_entities": "Extracting entities (spaCy NER)",
    "embed": "Generating similarity embedding (Sentence-BERT)",
    "find_similar_cases": "Searching for similar historical cases",
    "index_and_check_escalation": "Indexing + checking safety escalation",
}


def _task_state(task_instances: list[dict], task_id: str) -> str | None:
    return next((t["state"] for t in task_instances if t["task_id"] == task_id), None)


def render_flow_html(submit_history_entry: dict) -> str:
    case_id = submit_history_entry["case_id"]
    task_instances = submit_history_entry.get("task_instances", [])

    parts: list[str] = [CSS, '<div class="flow-wrap"><div class="flow-col">']

    # -- IAM placeholder band (original architecture)
    parts.append(f'<div class="band-label">{esc("Identity Layer (original architecture)")}</div>')
    parts.append(placeholder("AWS IAM", "Authenticates/authorizes dealer + service requests"))
    parts.append(arrow())

    # -- Real: dealer submission
    parts.append('<div class="band-label">Live Run</div>')
    parts.append(stage("real-user", "Dealer Submission", detail=f"case_id = {case_id}", tag=REAL_TAG))
    parts.append(arrow())

    # -- Real: Airflow DAG triggered
    parts.append(
        stage(
            "real-orchestration",
            "Airflow DAG Triggered",
            sub=f"dag_run_id = {submit_history_entry.get('dag_run_id', '?')}",
            detail="volvo_case_pipeline — one real DAG run per submitted case",
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    # Look up the case's actual stored data (classification, entities,
    # similar cases) from OpenSearch -- the DAG's real output, not a trace
    # object, since there's no in-process orchestration to read from here.
    client = ensure_index()
    case_doc = None
    matches = client.search(index="volvo_warranty_cases", body={"query": {"term": {"case_id": case_id}}})
    hits = matches["hits"]["hits"]
    if hits:
        case_doc = hits[0]["_source"]

    for task_id in ["preprocess", "classify", "extract_entities", "embed", "find_similar_cases"]:
        state = _task_state(task_instances, task_id)
        label = TASK_LABELS[task_id]
        if state != "success":
            parts.append(
                stage(
                    "real-orchestration",
                    label,
                    sub=f"Airflow task state: {state or 'unknown'}",
                )
            )
            parts.append(arrow())
            continue

        if task_id == "classify" and case_doc:
            categories = case_doc.get("categories", [])
            category_scores = case_doc.get("category_scores") or {}
            # category_scores isn't populated by /index-case today (only
            # the final assigned categories are stored) -- render what we
            # have: the assigned categories as a simple label table at
            # score 1.0 (assigned) is misleading, so show them as chips
            # instead when per-category scores aren't available.
            if category_scores:
                extra = label_score_table(list(category_scores.items()))
            else:
                extra = entity_chips([{"label": "CATEGORY", "text": c} for c in categories])
            parts.append(
                stage("real-orchestration", label, sub="DistilBERT multi-label classifier", tag=REAL_TAG, extra_html=extra)
            )
        elif task_id == "extract_entities" and case_doc:
            extra = entity_chips(case_doc.get("entities", []))
            parts.append(
                stage("real-orchestration", label, sub="spaCy NER + custom EntityRuler", tag=REAL_TAG, extra_html=extra)
            )
        elif task_id == "find_similar_cases" and case_doc:
            # Similar cases aren't persisted on the case doc itself; query
            # live using the case's own narrative_vector for the diagram.
            similar = []
            if case_doc.get("narrative_vector"):
                sim_resp = client.search(
                    index="volvo_warranty_cases",
                    body={
                        "size": 6,
                        "query": {"knn": {"narrative_vector": {"vector": case_doc["narrative_vector"], "k": 6}}},
                    },
                )
                similar = [
                    {"case_id": h["_source"]["case_id"], "score": h["_score"]}
                    for h in sim_resp["hits"]["hits"]
                    if h["_source"]["case_id"] != case_id
                ][:5]
            extra = score_table(similar)
            parts.append(
                stage("real-orchestration", label, sub="Sentence-BERT cosine similarity, top-5", tag=REAL_TAG, extra_html=extra)
            )
        else:
            parts.append(stage("real-orchestration", label, tag=REAL_TAG))
        parts.append(arrow())

    # -- Real: index + escalation check
    index_state = _task_state(task_instances, "index_and_check_escalation")
    conn = get_pg_connection()
    escalation_row = None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, trigger_reason, status, related_case_ids FROM safety_escalations WHERE case_id = %s",
            (case_id,),
        )
        row = cur.fetchone()
        if row:
            escalation_row = {"id": row[0], "trigger_reason": row[1], "status": row[2], "related_case_ids": row[3]}
    conn.close()

    if index_state == "success":
        parts.append(
            stage(
                "real-orchestration",
                TASK_LABELS["index_and_check_escalation"],
                sub="OpenSearch index write + Postgres warranty_cases/case_classifications",
                tag=REAL_TAG,
            )
        )
    else:
        parts.append(stage("real-orchestration", TASK_LABELS["index_and_check_escalation"], sub=f"state: {index_state or 'unknown'}"))
    parts.append(arrow())

    # -- Conditional: safety escalation decision. Rendered only if an
    # escalation row actually exists for this case -- a non-escalated case
    # correctly omits this stage entirely rather than showing a false
    # pending state.
    if escalation_row:
        status = escalation_row["status"]
        css_class = {
            "pending_review": "decision-pending",
            "field_action_recommended": "decision-approved",
            "no_action_needed": "decision-rejected",
        }.get(status, "decision-pending")
        related = escalation_row.get("related_case_ids") or []
        sub = f"trigger: {escalation_row['trigger_reason']}"
        if related:
            sub += f" — related: {', '.join(related)}"
        parts.append(
            stage(
                css_class,
                "Safety Escalation Decision",
                sub=sub,
                detail=f"escalation_id={escalation_row['id']}, status={status}",
            )
        )
        parts.append(arrow())

    # -- CloudWatch placeholder band
    parts.append(f'<div class="band-label">{esc("Observability (original architecture)")}</div>')
    parts.append(placeholder("Amazon CloudWatch", "Logs, metrics, alarms"))

    parts.append("</div></div>")
    return "".join(parts)

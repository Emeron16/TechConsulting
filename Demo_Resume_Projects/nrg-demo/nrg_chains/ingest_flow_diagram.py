"""Renders a self-contained HTML/CSS pipeline diagram for one KB document
ingestion run, sibling to flow_diagram.py's Ask-run visualization. Built
from the real IngestStep sequence nrg_chains.ingest.ingest_document()
yields, same visual language as copilot-demo's ingest_flow_diagram.py.

Critical structural difference from copilot-demo's ingest diagram: this
one has a genuine synchronous/asynchronous split. Everything through the
RabbitMQ publish step happened synchronously in the same call that
produced this IngestStep sequence -- but the embed+index step happens in a
*separate OS process* (scripts/consume_ingestion_events.py) on its own
timeline. Since that consumer step didn't happen inside this function call,
its status has to be polled from Postgres (ingestion_events.status) at
render time rather than read off a completed step list -- if it hasn't
been consumed yet, that stage renders as a pending "Awaiting consumer..."
state rather than a real one, genuinely reflecting that it may not have
happened yet.
"""
from nrg_chains.diagram_common import CSS, REAL_TAG, arrow, esc, placeholder, stage
from nrg_chains.ingest import IngestStep
from nrg_retrieval.postgres_client import get_ingestion_event, get_pg_connection

_STAGE_CSS = {
    "parsing": "real-tool",
    "chunking": "real-tool",
}

_STAGE_TITLES = {
    "parsing": "Parse Document (unstructured.io)",
    "chunking": "Chunk Text",
}

_OUTCOME_CSS = {
    "new_document": "outcome-new",
    "new_version": "outcome-version",
    "no_op": "outcome-noop",
}

_OUTCOME_TITLES = {
    "new_document": "New Document — Version 1",
    "new_version": "New Version Created",
    "no_op": "No-Op — Identical Content",
}


def _steps_by_stage(steps: list[IngestStep]) -> dict[str, list[IngestStep]]:
    grouped: dict[str, list[IngestStep]] = {}
    for s in steps:
        grouped.setdefault(s.stage, []).append(s)
    return grouped


def _lookup_ingestion_event_status(event_id: int) -> str | None:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            event = get_ingestion_event(cur, event_id)
    finally:
        conn.close()
    return event["status"] if event else None


def render_ingest_flow_html(steps: list[IngestStep], filename: str, uploaded_by: str) -> str:
    parts: list[str] = [CSS, '<div class="flow-wrap"><div class="flow-col">']

    # -- Auth placeholder band, same framing as flow_diagram.py's
    parts.append(f'<div class="band-label">{esc("API & Identity Layer (original architecture)")}</div>')
    parts.append(placeholder("AWS IAM", "Would authorize who can add/modify KB docs"))
    parts.append(arrow())

    parts.append('<div class="band-label">Live Ingestion Run</div>')
    parts.append(
        stage("real-user", "File Upload", detail=f"{filename}\nuploaded by: {uploaded_by}", tag=REAL_TAG)
    )
    parts.append(arrow())

    grouped = _steps_by_stage(steps)
    error_steps = grouped.get("error", [])
    if error_steps:
        parts.append(
            stage("outcome-error", "Ingestion Failed", detail=error_steps[-1].detail.get("message", "Unknown error"))
        )
        parts.append("</div></div>")
        return "".join(parts)

    # -- Real: parse (unstructured.io -- Textract analog) + chunk
    for stage_key in ("parsing", "chunking"):
        stage_steps = grouped.get(stage_key, [])
        if not stage_steps:
            continue
        last = stage_steps[-1]
        detail_lines = [f"{k}: {v}" for k, v in last.detail.items()]
        sub = "Amazon Textract analog — layout/table-aware parsing" if stage_key == "parsing" else "Chunking for embedding"
        parts.append(stage(_STAGE_CSS[stage_key], _STAGE_TITLES[stage_key], sub=sub, detail="\n".join(detail_lines), tag=REAL_TAG))
        parts.append(arrow())

    # -- Real: version check (Postgres kb_documents)
    versioning_steps = grouped.get("versioning", [])
    outcome = None
    if versioning_steps:
        final_versioning = versioning_steps[-1]
        outcome = final_versioning.detail.get("outcome", "unknown")
        detail_lines = [f"{k}: {v}" for k, v in final_versioning.detail.items() if k != "outcome"]
        parts.append(
            stage(
                _OUTCOME_CSS.get(outcome, "real-supervisor"),
                _OUTCOME_TITLES.get(outcome, "Version Check"),
                sub="Postgres kb_documents table",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

        if outcome == "no_op":
            parts.append(
                stage(
                    "outcome-noop",
                    "Ingestion Complete (No Change)",
                    sub="Identical content was already the active version — nothing re-published",
                )
            )
            parts.append("</div></div>")
            return "".join(parts)

    # -- Real: RabbitMQ publish -- the sync/async boundary itself
    publishing_steps = grouped.get("publishing", [])
    event_id = None
    if publishing_steps:
        last = publishing_steps[-1]
        detail_lines = [f"{k}: {v}" for k, v in last.detail.items()]
        parts.append(
            stage(
                "real-event",
                "RabbitMQ: Publish document_processed",
                sub="Amazon SNS+SQS analog — exchange nrg.ingestion, queue document_processed",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )

    done_steps = grouped.get("done", [])
    if done_steps:
        event_id = done_steps[-1].detail.get("ingestion_event_id")

    # -- Async boundary: dashed arrow + band label mark that everything
    # from here on happened (or is happening) in a separate process on its
    # own timeline, decoupled from the synchronous call that produced
    # everything above this point.
    parts.append(arrow(async_boundary=True))
    parts.append(
        '<div class="band-label async-label">Async — consumed independently by '
        "scripts/consume_ingestion_events.py</div>"
    )

    consumed = False
    if event_id is not None:
        status = _lookup_ingestion_event_status(event_id)
        consumed = status == "consumed"

        if status == "consumed":
            parts.append(
                stage(
                    "real-llm",
                    "Consumer: Embed (dense + sparse)",
                    sub="OpenAI text-embedding-3-small + fastembed Qdrant/bm25",
                    tag=REAL_TAG,
                )
            )
            parts.append(arrow())
            parts.append(
                stage(
                    "real-agent",
                    "Qdrant: Upsert",
                    sub="OpenSearch Serverless analog — now searchable",
                    tag=REAL_TAG,
                )
            )
        elif status == "failed":
            parts.append(
                stage(
                    "outcome-error",
                    "Dead-Lettered",
                    sub="Consumer failed after max retries — routed to document_processed.dlq",
                )
            )
        else:
            parts.append(
                stage(
                    "decision-pending",
                    "Awaiting Consumer...",
                    sub="Message published, not yet consumed — start scripts/consume_ingestion_events.py or wait for it to drain the queue",
                )
            )
    else:
        parts.append(stage("decision-pending", "Awaiting Consumer...", sub="No ingestion_event_id recorded"))

    # -- Observability placeholder band
    parts.append(f'<div class="band-label">{esc("Observability (original architecture)")}</div>')
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Amazon CloudWatch", "Textract job status / processing metrics analog")
        + "</div>"
    )
    parts.append(arrow())

    if consumed:
        parts.append(stage("real-answer", "Ingestion Complete", detail="Document is now searchable.", tag=REAL_TAG))

    parts.append("</div></div>")
    return "".join(parts)

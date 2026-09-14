"""Renders a self-contained HTML/CSS pipeline diagram for one KB document
ingestion run (upload -> parse -> chunk -> version check -> embed -> store),
sibling to flow_diagram.py's agent-query visualization -- same visual
language (real stages solid/colored + REAL tag, placeholder stages for
original-architecture layers not implemented locally), built from the real
IngestStep sequence copilot_agents.kb_ingest.ingest_document() yields.
"""
import json

from copilot_agents.diagram_common import CSS, REAL_TAG, arrow, esc, placeholder, print_button, stage
from copilot_agents.kb_ingest import IngestStep

_STAGE_CSS = {
    "parsing": "real-tool",
    "chunking": "real-tool",
    "versioning": "real-supervisor",
    "embedding": "real-llm",
    "storing": "real-agent",
}

_STAGE_TITLES = {
    "parsing": "Parse Document",
    "chunking": "Chunk Text",
    "versioning": "Version Check",
    "embedding": "Generate Embeddings",
    "storing": "Store in ChromaDB",
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


def render_ingest_flow_html(steps: list[IngestStep], filename: str, uploaded_by: str) -> str:
    parts: list[str] = [CSS, '<div class="flow-wrap">', print_button(), '<div class="flow-col">']

    # -- Auth placeholder band, mirrors flow_diagram.py's framing for the
    # equivalent "who is allowed to upload" governance layer, not implemented
    # locally (no RBAC enforcement on who can add KB documents today).
    parts.append(f'<div class="band-label">{esc("API & Identity Layer (original architecture)")}</div>')
    parts.append(placeholder("Microsoft Entra ID (SSO)", "Would authenticate the uploading user"))
    parts.append(arrow())
    parts.append(placeholder("RBAC Policy Engine", "Would authorize who can add/modify KB docs"))
    parts.append(arrow())

    parts.append('<div class="band-label">Live Ingestion Run</div>')
    parts.append(
        stage(
            "real-user",
            "File Upload",
            detail=f"{filename}\nuploaded by: {uploaded_by}",
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    grouped = _steps_by_stage(steps)
    error_steps = grouped.get("error", [])
    if error_steps:
        parts.append(
            stage(
                "outcome-error",
                "Ingestion Failed",
                detail=error_steps[-1].detail.get("message", "Unknown error"),
            )
        )
        parts.append("</div></div>")
        return "".join(parts)

    for stage_key in ("parsing", "chunking"):
        stage_steps = grouped.get(stage_key, [])
        if not stage_steps:
            continue
        last = stage_steps[-1]
        detail_lines = [f"{k}: {v}" for k, v in last.detail.items()]
        parts.append(
            stage(
                _STAGE_CSS[stage_key],
                _STAGE_TITLES[stage_key],
                sub="Document parsing" if stage_key == "parsing" else "Chunking for embedding",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

    # -- Version check, called out as its own decision stage since this is
    # the versioning-conflict resolution the KB tab exists to make visible.
    versioning_steps = grouped.get("versioning", [])
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
            )
        )
        parts.append(arrow())

        if outcome == "no_op":
            parts.append(
                stage(
                    "outcome-noop",
                    "Ingestion Complete (No Change)",
                    sub="Identical content was already the active version -- nothing re-embedded",
                )
            )
            parts.append("</div></div>")
            return "".join(parts)

    for stage_key in ("embedding", "storing"):
        stage_steps = grouped.get(stage_key, [])
        if not stage_steps:
            continue
        last = stage_steps[-1]
        detail_lines = [f"{k}: {v}" for k, v in last.detail.items()]
        parts.append(
            stage(
                _STAGE_CSS[stage_key],
                _STAGE_TITLES[stage_key],
                sub="OpenAI text-embedding-3-small" if stage_key == "embedding" else "quality_documents collection",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

    # -- Observability placeholder, mirrors flow_diagram.py's equivalent band
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Azure Monitor + App Insights", "Original observability layer")
        + placeholder("Azure AI Foundry", "Content/prompt governance checkpoint")
        + "</div>"
    )
    parts.append(arrow())

    done_steps = grouped.get("done", [])
    if done_steps:
        final = done_steps[-1]
        detail_lines = [f"{k}: {v}" for k, v in final.detail.items()]
        parts.append(
            stage(
                "real-answer",
                "Ingestion Complete",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )

    parts.append("</div></div>")
    return "".join(parts)

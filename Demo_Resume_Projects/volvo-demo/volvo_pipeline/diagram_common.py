"""Shared CSS and stage-rendering helpers for the HTML/CSS pipeline
diagrams (flow_diagram.py for new-case runs, training_flow_diagram.py for
the DistilBERT training pipeline). Copied from nrg-demo's
nrg_chains/diagram_common.py (itself copied from copilot-demo's
copilot_agents/diagram_common.py) and diverged, per the established
"duplicate, don't cross-import" convention -- both are pure presentation
code with zero domain coupling, so duplicating this module keeps all three
demos' Python packages fully independent while rendering with a shared
visual language.

Additions beyond NRG's version:
  - `.stage.real-orchestration` (teal) -- marks a step that ran as a real
    Airflow task, used throughout the new-case diagram since (per
    Volvo_Implementation_Plan.md's architecture decision) the live UI path
    genuinely runs through Airflow, unlike NRG where async/orchestration
    was a side note limited to the ingest flow specifically.
  - `label_score_table()` -- per-category multi-label classification
    probabilities for ONE case, distinct from score_table()'s per-document
    retrieval-score shape.
  - `entity_chips()` -- compact NER entity rendering.
  - The existing `.decision-pending/approved/rejected` classes (already
    defined below, inherited from copilot-demo's original CSS but never
    used by NRG since NRG has no gating decision) are REUSED here, not
    reinvented, for the safety-escalation decision stage -- this genuinely
    IS a gating-style routing decision (unlike NRG's passive `.annotation`
    class), so almost no new CSS was needed, just new stage-content wiring
    in flow_diagram.py.
"""
import html

CSS = """
<style>
  * { box-sizing: border-box; }
  .flow-wrap {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1a1a1a;
    background: #fafafa;
    padding: 24px;
    border-radius: 12px;
  }
  .flow-col { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .arrow {
    width: 2px; height: 22px; background: #9aa0a6; position: relative;
  }
  .arrow::after {
    content: ""; position: absolute; bottom: -1px; left: -4px;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 7px solid #9aa0a6;
  }
  .arrow.async-boundary {
    background: transparent;
    border-left: 2px dashed #d97706;
  }
  .arrow.async-boundary::after {
    border-top-color: #d97706;
  }
  .band-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
    color: #6b7280; margin: 18px 0 6px; font-weight: 600;
  }
  .band-label.async-label { color: #b45309; }
  .stage {
    border-radius: 10px; padding: 12px 18px; min-width: 260px; max-width: 640px;
    text-align: left; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  .stage-title { font-weight: 700; font-size: 14px; margin-bottom: 2px; }
  .stage-sub { font-size: 12px; opacity: 0.85; }
  .stage-detail {
    margin-top: 8px; font-size: 12px; font-family: "SF Mono", Menlo, monospace;
    background: rgba(0,0,0,0.04); border-radius: 6px; padding: 8px 10px;
    white-space: pre-wrap; word-break: break-word; max-height: 160px; overflow-y: auto;
  }

  /* real, data-driven stages */
  .stage.real-user { background: #eef2ff; border: 1.5px solid #6366f1; }
  .stage.real-agent { background: #f0fdf4; border: 1.5px solid #22c55e; }
  .stage.real-tool { background: #fffbeb; border: 1.5px solid #f59e0b; }
  .stage.real-answer { background: #eff6ff; border: 1.5px solid #3b82f6; }
  .stage.real-audit { background: #f5f3ff; border: 1.5px solid #8b5cf6; }
  .stage.real-event { background: #fffbeb; border: 2px solid #d97706; }
  /* real-orchestration: a step that ran as a genuine Airflow task -- teal,
     distinct from every other real-* color, since the live path here
     genuinely runs through Airflow rather than orchestration being a side
     note limited to one diagram's async band. */
  .stage.real-orchestration { background: #ecfeff; border: 2px solid #0891b2; }

  /* accept/deny decision stages -- REUSED here for the safety-escalation
     routing decision (pending_review / field_action_recommended /
     no_action_needed), a genuine gating-style decision, unlike NRG's
     passive .annotation class. */
  .stage.decision-pending { background: #fffbeb; border: 2px dashed #f59e0b; }
  .stage.decision-approved { background: #f0fdf4; border: 2px solid #16a34a; }
  .stage.decision-rejected { background: #fef2f2; border: 2px solid #dc2626; }

  .stage.annotation {
    background: #fafafa; border: 1px dashed #9ca3af; opacity: 0.8;
  }
  .stage.annotation .stage-title { font-size: 12px; font-weight: 600; }

  /* placeholder (not implemented locally) stages */
  .stage.placeholder {
    background: #f3f4f6; border: 1.5px dashed #b0b4ba; color: #6b7280;
  }
  .stage.placeholder .stage-title { color: #6b7280; }
  .placeholder-tag {
    display: inline-block; font-size: 10px; font-weight: 600; letter-spacing: 0.03em;
    background: #e5e7eb; color: #6b7280; border-radius: 4px; padding: 1px 6px;
    margin-left: 8px; vertical-align: middle;
  }
  .real-tag {
    display: inline-block; font-size: 10px; font-weight: 600; letter-spacing: 0.03em;
    background: #dcfce7; color: #15803d; border-radius: 4px; padding: 1px 6px;
    margin-left: 8px; vertical-align: middle;
  }

  .side-by-side { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }

  .score-table {
    margin-top: 8px; width: 100%; border-collapse: collapse; font-size: 10.5px;
  }
  .score-table th, .score-table td {
    padding: 3px 6px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.08);
  }
  .score-table th:first-child, .score-table td:first-child { text-align: left; }
  .score-table th {
    font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.02em;
    font-size: 9px;
  }
  .score-table td.doc-id { font-family: "SF Mono", Menlo, monospace; font-weight: 600; }

  /* per-category multi-label classification probability table -- ONE
     case's scores across all 8 categories, distinct from score_table()'s
     per-document retrieval-score shape. Categories crossing threshold are
     bolded/highlighted so it's visually obvious which ones the classifier
     actually assigned versus which merely scored non-zero. */
  .label-score-table {
    margin-top: 8px; width: 100%; border-collapse: collapse; font-size: 10.5px;
  }
  .label-score-table th, .label-score-table td {
    padding: 3px 6px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.08);
  }
  .label-score-table th:first-child, .label-score-table td:first-child { text-align: left; }
  .label-score-table th {
    font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.02em;
    font-size: 9px;
  }
  .label-score-table td.category { font-family: "SF Mono", Menlo, monospace; }
  .label-score-table tr.above-threshold td.category { font-weight: 700; color: #15803d; }
  .label-score-table tr.above-threshold td.score { font-weight: 700; color: #15803d; }

  /* NER entity chips */
  .entity-chips { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
  .entity-chip {
    display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px;
    background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 999px;
    padding: 2px 10px;
  }
  .entity-chip .entity-label {
    font-weight: 700; text-transform: uppercase; font-size: 9px; color: #4338ca;
  }

  .cache-badge {
    display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.03em;
    border-radius: 4px; padding: 1px 7px; margin-left: 8px; vertical-align: middle;
  }
  .cache-badge.hit { background: #dcfce7; color: #15803d; }
  .cache-badge.miss { background: #f3f4f6; color: #6b7280; }
</style>
"""


def esc(text: str | None) -> str:
    return html.escape(text or "")


def stage(
    css_class: str, title: str, sub: str = "", detail: str = "", tag: str = "", extra_html: str = ""
) -> str:
    """extra_html is inserted raw (not escaped) after the sub line -- only
    pass pre-built trusted HTML fragments here, never raw user/LLM text.
    """
    detail_html = f'<div class="stage-detail">{esc(detail)}</div>' if detail else ""
    sub_html = f'<div class="stage-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="stage {css_class}">'
        f'<div class="stage-title">{esc(title)}{tag}</div>'
        f"{sub_html}{extra_html}{detail_html}"
        f"</div>"
    )


def arrow(async_boundary: bool = False) -> str:
    css_class = "arrow async-boundary" if async_boundary else "arrow"
    return f'<div class="{css_class}"></div>'


def placeholder(title: str, sub: str = "") -> str:
    return stage(
        "placeholder", title, sub, tag='<span class="placeholder-tag">NOT IMPLEMENTED LOCALLY</span>'
    )


def score_table(results: list[dict]) -> str:
    """Per-case similar-case results: case_id + cosine score columns.
    Reuses score_table()'s shape fairly directly from NRG's version, just
    relabeled for "similar case ID" + "cosine score" instead of NRG's
    fusion/rerank retrieval scores.
    """
    if not results:
        return ""
    row_html = []
    for r in results:
        case_id = esc(str(r.get("case_id", "")))
        score = r.get("score")
        cell = esc("{:.4f}".format(score)) if score is not None else "&mdash;"
        row_html.append(f'<tr><td class="doc-id">{case_id}</td><td>{cell}</td></tr>')
    return (
        '<table class="score-table"><thead><tr>'
        "<th>Case</th><th>Cosine score</th>"
        "</tr></thead><tbody>" + "".join(row_html) + "</tbody></table>"
    )


def label_score_table(scores: list[tuple[str, float]], threshold: float = 0.5) -> str:
    """Renders per-category multi-label classification probabilities for
    one case. Rows crossing `threshold` are visually highlighted, since
    those are the categories actually assigned -- the rest are shown for
    context (how close a non-assigned category came) but not bolded.
    """
    if not scores:
        return ""
    row_html = []
    for category, score in sorted(scores, key=lambda pair: pair[1], reverse=True):
        row_class = "above-threshold" if score >= threshold else ""
        row_html.append(
            f'<tr class="{row_class}">'
            f'<td class="category">{esc(category)}</td>'
            f'<td class="score">{esc("{:.4f}".format(score))}</td>'
            "</tr>"
        )
    return (
        '<table class="label-score-table"><thead><tr>'
        "<th>Category</th><th>Probability</th>"
        "</tr></thead><tbody>" + "".join(row_html) + "</tbody></table>"
    )


def entity_chips(entities: list[dict]) -> str:
    """Compact chip rendering of extracted {label, text} entity pairs."""
    if not entities:
        return ""
    chip_html = [
        f'<span class="entity-chip"><span class="entity-label">{esc(e["label"])}</span>{esc(e["text"])}</span>'
        for e in entities
    ]
    return '<div class="entity-chips">' + "".join(chip_html) + "</div>"


def cache_badge(cache_hit: bool | None) -> str:
    if cache_hit is None:
        return ""
    if cache_hit:
        return '<span class="cache-badge hit">CACHE HIT</span>'
    return '<span class="cache-badge miss">CACHE MISS</span>'


REAL_TAG = '<span class="real-tag">REAL</span>'

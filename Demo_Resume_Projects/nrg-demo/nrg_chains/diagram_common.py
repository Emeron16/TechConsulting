"""Shared CSS and stage-rendering helpers for the HTML/CSS pipeline
diagrams (flow_diagram.py for Ask runs, ingest_flow_diagram.py for KB
document ingestion). Duplicated from copilot-demo's copilot_agents/
diagram_common.py rather than cross-imported -- both are pure presentation
code with zero domain coupling, so duplicating this one small module keeps
the two demos' Python packages fully independent (no nrg_chains import
ever reaches into copilot_agents, or vice versa) while still rendering
with identical visual language. One addition beyond the original: a
`real-event` stage class (amber) and a dashed arrow variant, used to mark
the RabbitMQ publish step and the asynchronous boundary that follows it --
NRG's ingest pipeline is genuinely async past that point (a separate OS
process consumes the event on its own timeline), which copilot-demo's
synchronous embed-in-the-same-call ingest has no equivalent for.
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
  /* dashed arrow: marks the asynchronous boundary in the ingest diagram --
     everything below this arrow happens in a separate process, on its own
     timeline, decoupled from the publisher that drew the solid arrows
     above it. */
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
  .stage.real-supervisor { background: #ecfeff; border: 1.5px solid #06b6d4; }
  .stage.real-agent { background: #f0fdf4; border: 1.5px solid #22c55e; }
  .stage.real-tool { background: #fffbeb; border: 1.5px solid #f59e0b; }
  .stage.real-llm { background: #faf5ff; border: 1.5px solid #a855f7; }
  .stage.real-answer { background: #eff6ff; border: 1.5px solid #3b82f6; }
  .stage.real-audit { background: #f5f3ff; border: 1.5px solid #8b5cf6; }
  .stage.real-cache { background: #ecfdf5; border: 1.5px solid #10b981; }
  /* real-event: the RabbitMQ publish stage specifically -- amber/orange to
     read as "in-flight / async", distinct from every other solid real-*
     stage color, so it visually announces the sync/async handoff point. */
  .stage.real-event { background: #fffbeb; border: 2px solid #d97706; }

  /* accept/deny decision stages */
  .stage.decision-pending { background: #fffbeb; border: 2px dashed #f59e0b; }
  .stage.decision-approved { background: #f0fdf4; border: 2px solid #16a34a; }
  .stage.decision-rejected { background: #fef2f2; border: 2px solid #dc2626; }

  /* retrospective annotation (not a gate) -- lighter/secondary styling,
     used for "later reviewed by Compliance" on the Ask-flow diagram, which
     must never read as a blocking stage the way decision-pending does. */
  .stage.annotation {
    background: #fafafa; border: 1px dashed #9ca3af; opacity: 0.8;
  }
  .stage.annotation .stage-title { font-size: 12px; font-weight: 600; }

  /* ingestion-specific outcome stages */
  .stage.outcome-new { background: #f0fdf4; border: 2px solid #16a34a; }
  .stage.outcome-version { background: #eff6ff; border: 2px solid #3b82f6; }
  .stage.outcome-noop { background: #f9fafb; border: 2px dashed #9ca3af; }
  .stage.outcome-error { background: #fef2f2; border: 2px solid #dc2626; }

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

  /* per-document score breakdown table on retrieval stages */
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

  /* cache hit/miss badge */
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
    """Renders a compact per-document score breakdown (fusion / rerank) for
    a retrieval stage's results -- Qdrant's native hybrid fusion doesn't
    expose separable per-space dense/sparse scores post-fusion (see
    nrg_retrieval/hybrid_search.py's docstring), so only fusion_score and
    rerank_score columns are shown, unlike copilot-demo's 4-column
    bm25/vector/fusion-rank/rerank table.
    """
    if not results:
        return ""
    row_html = []
    for r in results:
        doc_id = esc(str(r.get("doc_id", "")))
        fusion = r.get("fusion_score")
        rerank = r.get("rerank_score")
        cell = lambda v: esc("{:.4f}".format(v)) if v is not None else "&mdash;"
        row_html.append(
            "<tr>"
            f'<td class="doc-id">{doc_id}</td>'
            f"<td>{cell(fusion)}</td>"
            f"<td>{cell(rerank)}</td>"
            "</tr>"
        )
    return (
        '<table class="score-table"><thead><tr>'
        "<th>Doc</th><th>Fusion (RRF)</th><th>Rerank</th>"
        "</tr></thead><tbody>" + "".join(row_html) + "</tbody></table>"
    )


def cache_badge(cache_hit: bool | None) -> str:
    if cache_hit is None:
        return ""
    if cache_hit:
        return '<span class="cache-badge hit">CACHE HIT</span>'
    return '<span class="cache-badge miss">CACHE MISS</span>'


REAL_TAG = '<span class="real-tag">REAL</span>'

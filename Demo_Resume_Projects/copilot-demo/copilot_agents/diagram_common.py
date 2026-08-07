"""Shared CSS and stage-rendering helpers for the HTML/CSS pipeline
diagrams (flow_diagram.py for agent-query runs, ingest_flow_diagram.py for
KB document ingestion) -- kept in one place so both diagrams stay visually
consistent and a fix to one (e.g. escaping) doesn't need to be duplicated
into the other.
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
  .band-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
    color: #6b7280; margin: 18px 0 6px; font-weight: 600;
  }
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

  /* accept/deny decision stages */
  .stage.decision-pending { background: #fffbeb; border: 2px dashed #f59e0b; }
  .stage.decision-approved { background: #f0fdf4; border: 2px solid #16a34a; }
  .stage.decision-rejected { background: #fef2f2; border: 2px solid #dc2626; }

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
  .not-selected {
    opacity: 0.45; font-size: 11px; color: #6b7280; border: 1px dashed #d1d5db;
    border-radius: 8px; padding: 6px 10px; background: #fff;
  }
  .not-selected-row { display: flex; gap: 8px; justify-content: center; margin-top: 4px; flex-wrap: wrap; }

  /* retrieval-strategy badge + hover tooltip on tool-call stages */
  .retrieval-badge {
    display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; font-weight: 600;
    background: #e0e7ff; color: #3730a3; border-radius: 4px; padding: 2px 7px;
    margin-top: 6px; cursor: help; position: relative;
  }
  .retrieval-badge.sql { background: #fee2e2; color: #991b1b; }
  .retrieval-badge .info-dot {
    display: inline-block; width: 13px; height: 13px; border-radius: 50%;
    background: rgba(0,0,0,0.15); color: inherit; font-size: 9px; text-align: center;
    line-height: 13px; font-weight: 700;
  }
  .retrieval-tooltip {
    display: none; position: absolute; left: 0; top: calc(100% + 6px); z-index: 20;
    width: 320px; background: #1f2937; color: #f3f4f6; border-radius: 8px;
    padding: 10px 12px; font-size: 11.5px; line-height: 1.5; font-weight: 400;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25); text-align: left; white-space: normal;
  }
  .retrieval-tooltip b { color: #fff; }
  .retrieval-badge:hover .retrieval-tooltip { display: block; }

  /* per-document score breakdown table on search tool-call stages */
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

  /* cache hit/miss badge on tool-call stages */
  .cache-badge {
    display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.03em;
    border-radius: 4px; padding: 1px 7px; margin-left: 8px; vertical-align: middle;
  }
  .cache-badge.hit { background: #dcfce7; color: #15803d; }
  .cache-badge.miss { background: #f3f4f6; color: #6b7280; }

  /* critic review stages */
  .stage.critic-pass { background: #f0fdf4; border: 2px solid #16a34a; }
  .stage.critic-fail { background: #fef2f2; border: 2px dashed #dc2626; }
  .attempt-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: #9333ea; font-weight: 700; margin: 14px 0 4px;
  }

  /* parallel tool-call batch: same-turn calls the SDK actually executed
     concurrently, rendered side by side instead of one arrow-chain */
  .parallel-label {
    display: flex; align-items: center; gap: 6px; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.06em; color: #b45309;
    font-weight: 700; margin: 10px 0 6px;
  }
  .parallel-label::before, .parallel-label::after {
    content: ""; flex: 1; height: 1px; background: #fcd34d;
  }
  .side-by-side.parallel-batch {
    background: #fffbeb; border: 1.5px dashed #f59e0b; border-radius: 12px;
    padding: 14px; align-items: stretch;
  }
</style>
"""


def esc(text: str | None) -> str:
    return html.escape(text or "")


def stage(
    css_class: str, title: str, sub: str = "", detail: str = "", tag: str = "", extra_html: str = ""
) -> str:
    """extra_html is inserted raw (not escaped) after the sub line -- only
    pass pre-built trusted HTML fragments here (e.g. retrieval_badge()
    output), never raw user/LLM text.
    """
    detail_html = f'<div class="stage-detail">{esc(detail)}</div>' if detail else ""
    sub_html = f'<div class="stage-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="stage {css_class}">'
        f'<div class="stage-title">{esc(title)}{tag}</div>'
        f"{sub_html}{extra_html}{detail_html}"
        f"</div>"
    )


def arrow() -> str:
    return '<div class="arrow"></div>'


def placeholder(title: str, sub: str = "") -> str:
    return stage(
        "placeholder", title, sub, tag='<span class="placeholder-tag">NOT IMPLEMENTED LOCALLY</span>'
    )


def retrieval_badge(retrieval_info: dict | None) -> str:
    """Renders a small badge naming the actual search backend (ChromaDB vs
    PostgreSQL) directly in the visible diagram, with a hover tooltip for
    the full retrieval-strategy breakdown (embedding model, ranking,
    metadata filter). Returns "" if no retrieval_info is available.
    """
    if not retrieval_info:
        return ""
    backend = retrieval_info.get("backend", "")
    is_sql = "postgres" in backend.lower() or "sql" in backend.lower()
    css_class = "sql" if is_sql else "vector"

    tooltip_lines = []
    for key in ("strategy", "embedding_model", "ranking", "filter"):
        if retrieval_info.get(key):
            label = key.replace("_", " ").title()
            tooltip_lines.append(f"<b>{esc(label)}:</b> {esc(retrieval_info[key])}")
    tooltip_html = "<br>".join(tooltip_lines)

    return (
        f'<span class="retrieval-badge {css_class}">'
        f"{esc(backend)} <span class=\"info-dot\">i</span>"
        f'<span class="retrieval-tooltip">{tooltip_html}</span>'
        f"</span>"
    )


def score_table(results: list[dict]) -> str:
    """Renders a compact per-document score breakdown (BM25 / vector /
    fusion rank / rerank) for a search tool call's results -- makes the
    hybrid pipeline's ranking justification visible directly on the
    diagram, not just the final combined relevance_score. results: list of
    SearchResult-shaped dicts (parsed from the tool call's JSON output).
    """
    if not results:
        return ""
    row_html = []
    for r in results:
        doc_id = esc(str(r.get("doc_id", "")))
        bm25 = r.get("bm25_score")
        vector = r.get("vector_score")
        fusion = r.get("fusion_rank")
        rerank = r.get("rerank_score")
        cell = lambda v, fmt="{:.2f}": esc(fmt.format(v)) if v is not None else "&mdash;"
        row_html.append(
            "<tr>"
            f'<td class="doc-id">{doc_id}</td>'
            f"<td>{cell(bm25)}</td>"
            f"<td>{cell(vector)}</td>"
            f'<td>{cell(fusion, "{:.0f}")}</td>'
            f"<td>{cell(rerank)}</td>"
            "</tr>"
        )
    return (
        '<table class="score-table"><thead><tr>'
        "<th>Doc</th><th>BM25</th><th>Vector</th><th>Fusion #</th><th>Rerank</th>"
        "</tr></thead><tbody>" + "".join(row_html) + "</tbody></table>"
    )


def cache_badge(cache_hit: bool | None) -> str:
    """Small hit/miss badge for a tool call's retrieval-cache status.
    Returns "" if cache_hit is None (not applicable, e.g. non-search tools).
    """
    if cache_hit is None:
        return ""
    if cache_hit:
        return '<span class="cache-badge hit">CACHE HIT</span>'
    return '<span class="cache-badge miss">CACHE MISS</span>'


def attempt_label(attempt: int, total: int) -> str:
    suffix = "" if total <= 1 else f" of {total}"
    return f'<div class="attempt-label">Attempt {attempt}{suffix}</div>'


def parallel_label(count: int) -> str:
    return f'<div class="parallel-label">{count} tool calls, executed in parallel</div>'


REAL_TAG = '<span class="real-tag">REAL</span>'

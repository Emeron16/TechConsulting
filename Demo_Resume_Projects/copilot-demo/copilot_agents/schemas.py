"""Pydantic models for MCP tool outputs and agent final outputs.

Replaces the plain dict/list[dict] shapes every MCP server previously
returned, and gives each of the 4 specialist agents a validated output_type
(GroundedAnswer) instead of free text -- the two boundaries where malformed
data would actually cause downstream problems (the critic step in
copilot_agents/critic.py validates against these shapes directly).
"""
from typing import Literal

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    """Returned instead of the normal shape when a lookup finds nothing --
    e.g. get_capa_status("CAPA-9999"). Kept as an explicit typed shape
    rather than a bare {"error": ...} dict so callers can validate either
    branch.
    """

    error: str


class SearchResult(BaseModel):
    """One retrieved document/chunk from the hybrid search pipeline
    (mcp_servers/hybrid_search.py) -- score fields are kept separate, not
    collapsed into one number, so the retrieval justification is auditable.
    """

    doc_id: str
    title: str
    doc_type: str
    version: int | str
    effective_date: str
    excerpt: str
    relevance_score: float = Field(description="Legacy combined score, kept for backward compatibility")
    bm25_score: float | None = Field(default=None, description="Raw BM25 keyword-match score")
    vector_score: float | None = Field(default=None, description="Cosine similarity vs. query embedding")
    fusion_rank: int | None = Field(default=None, description="Rank after Reciprocal Rank Fusion of BM25 + vector")
    rerank_score: float | None = Field(default=None, description="Cross-encoder rerank score (final ranking signal)")
    cache_hit: bool = Field(
        default=False,
        description="UI-only metadata: whether this result set came from the retrieval cache "
        "rather than a fresh hybrid_search() run. Not part of the retrieval logic itself -- "
        "surfaced so the Flow tab can show cache hit/miss without a separate side-channel, "
        "since MCP servers run as isolated subprocesses (see copilot_agents/critic.py's notes "
        "on why in-process state can't cross that boundary another way).",
    )


class DeviationRef(BaseModel):
    deviation_id: str
    classification: str | None
    investigation_status: str
    related_deviation_id: str | None


class BatchMetadata(BaseModel):
    batch_id: str
    product_name: str
    manufacturing_line: str
    manufacturing_date: str
    disposition_status: str
    deviations: list[DeviationRef] = Field(default_factory=list)


class CapaStatus(BaseModel):
    capa_id: str
    related_deviation_id: str | None
    status: str
    monitoring_start: str | None
    monitoring_end: str | None


class CapaDraft(BaseModel):
    draft_capa_id: str
    related_deviation_id: str
    root_cause_summary: str
    proposed_action: str
    status: Literal["draft_pending_review"]
    note: str


class SopDocument(BaseModel):
    doc_id: str
    title: str
    version: int | str
    effective_date: str
    full_text: str


class GroundedAnswer(BaseModel):
    """Specialist agents' structured final output (set via output_type in
    copilot_agents/specialists.py). citations must be doc_ids that actually
    appear in this run's retrieved SearchResults -- checked by
    copilot_agents/critic.py's deterministic layer.
    """

    answer: str = Field(description="The grounded answer to the user's question")
    citations: list[str] = Field(
        default_factory=list, description="doc_ids of the sources this answer is grounded in"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Self-assessed confidence based on how directly the retrieved sources support the answer"
    )
    requires_human_review: bool = Field(
        default=False, description="True if this answer touches a quality decision needing QP/reviewer sign-off"
    )


class CriticResult(BaseModel):
    """Output of both the deterministic checks and the LLM critic in
    copilot_agents/critic.py -- same shape for both so ask_flow.py's retry
    loop can treat either layer's failure identically.
    """

    passed: bool
    feedback: str = Field(default="", description="Explanation of what failed, empty if passed")
    layer: Literal["deterministic", "llm"] = Field(description="Which critic layer produced this result")

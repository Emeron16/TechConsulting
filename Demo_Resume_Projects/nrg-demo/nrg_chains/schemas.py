"""Pydantic models for the LangChain classification step and the final
grounded answer -- the validated-output-shape boundaries where malformed
data would actually cause downstream problems, same rationale as
copilot-demo's copilot_agents/schemas.py.
"""
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal[
    "plan_rate", "billing_policy", "outage_procedure", "escalation_playbook", "compliance_disclosure"
]


class ClassifiedQuery(BaseModel):
    """Output of the doc_type classification step (nrg_chains/classifier.py)
    -- doc_type is None when the question doesn't clearly belong to one of
    NRG's five document categories (e.g. small talk, out-of-scope
    questions), in which case nrg_chains/chain.py's fallback logic retries
    retrieval unfiltered rather than forcing a wrong-category filter.
    """

    doc_type: DocType | None = Field(
        description="Which document category this question is about, or null if unclear/out of scope"
    )
    plan_type_hint: str | None = Field(
        default=None, description="If the question names a specific plan type (fixed/variable/free_nights), extract it"
    )
    reasoning: str = Field(description="Brief explanation of the classification decision")


class SearchResultNRG(BaseModel):
    """One retrieved document from the hybrid search pipeline
    (nrg_retrieval/hybrid_search.py). Score fields kept separate, not
    collapsed into one number, so the ranking is auditable -- same
    reasoning as copilot-demo's SearchResult. dense_score/sparse_score are
    always None here since Qdrant's native fusion doesn't expose separable
    per-space scores post-fusion (see hybrid_search.py's docstring);
    fusion_score and rerank_score are the scores that actually drive
    ranking.
    """

    doc_id: str
    title: str
    doc_type: str
    version: int | str
    effective_date: str
    excerpt: str
    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = Field(default=None, description="RRF score from Qdrant's native fusion")
    rerank_score: float | None = Field(default=None, description="Cross-encoder rerank score (final ranking signal)")
    cache_hit: bool = Field(default=False, description="Whether this result came from the retrieval cache")


class GroundedAnswerNRG(BaseModel):
    """The chain's final structured output (set via with_structured_output
    in nrg_chains/chain.py). citations must be doc_ids that actually appear
    in this run's retrieved SearchResultNRG list.

    Deliberately no `requires_human_review` field, unlike copilot-demo's
    GroundedAnswer -- decision: NRG's human-in-the-loop is statistical
    sampling (every answer logged unconditionally via nrg_chains/sampling.py
    and shown to the user immediately), not a per-answer gate, so there is
    no per-answer flag to set. See NRG_Energy_Architecture_Deep_Dive.md
    §2.1/§3 for why this differs from the Novartis project's mandatory
    per-answer review.
    """

    answer: str = Field(description="The grounded answer to the user's question")
    citations: list[str] = Field(
        default_factory=list, description="doc_ids of the sources this answer is grounded in"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Self-assessed confidence based on how directly the retrieved sources support the answer"
    )
    doc_type_classified: DocType | None = Field(
        default=None, description="The doc_type the classifier routed this question to, if any"
    )

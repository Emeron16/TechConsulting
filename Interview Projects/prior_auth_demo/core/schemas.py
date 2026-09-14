"""Pydantic models shared across the pipeline. Kept small and explicit so every
LLM call has a typed, validated shape (OpenAI structured outputs parse directly into these).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Urgency = Literal["routine", "urgent", "stat"]
Recommendation = Literal["likely_approve", "needs_review", "likely_deny"]
Pathway = Literal["auto_approve", "urgent", "fast_track", "standard_review"]
Decision = Literal["approved", "denied", "information_requested"]


class ExtractedRequest(BaseModel):
    """Structured fields pulled from the raw intake document (Component 1: Intelligent
    Document Intake). Diagnosis/procedure codes must be taken verbatim, never inferred."""

    patient_id: str = Field(description="Patient identifier as it appears in the document")
    date_of_birth: str = Field(description="Patient date of birth, as written in the document")
    diagnosis_codes: list[str] = Field(
        default_factory=list, description="ICD-10 codes exactly as they appear, never inferred"
    )
    procedure_codes: list[str] = Field(
        default_factory=list, description="CPT/HCPCS codes exactly as they appear in the request"
    )
    requesting_provider: str = Field(description="Name of the requesting/treating provider")
    ordering_npi: str = Field(default="", description="Ordering provider NPI, if present")
    clinical_notes: str = Field(
        description="Verbatim relevant clinical narrative preserved from the document"
    )
    urgency: Urgency = Field(description="routine / urgent / stat, inferred from clinical context")
    confidence_score: float = Field(
        description="Extraction confidence (document/OCR clarity), as a number from 0.0 to 1.0"
    )
    extraction_notes: str = Field(
        default="", description="Anything ambiguous or low-confidence about this extraction"
    )

    # NOTE: numeric bounds are enforced here (not via Field(ge=..., le=...)) because OpenAI's
    # Structured Outputs strict mode does not support the "minimum"/"maximum" JSON Schema
    # keywords that Field(ge=, le=) would add — the API call would fail schema validation.
    @field_validator("confidence_score")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class MissingItem(BaseModel):
    item: str
    why_needed: str


class CompletenessResult(BaseModel):
    is_complete: bool
    missing_items: list[MissingItem] = Field(default_factory=list)
    matched_policy_id: str | None = None


class PolicyAnalysis(BaseModel):
    """Component 3 (Policy RAG) + Component 5 (Nurse Dashboard) combined: the model produces
    a structured analysis AND the nurse-facing summaries in one call, since both draw on the
    same read of the record. The AI never outputs a final approve/deny decision here."""

    patient_summary: str = Field(description="2-3 sentence patient context: diagnosis, history")
    request_summary: str = Field(description="What is being requested, why, and by whom")
    recommendation: Recommendation
    confidence: float = Field(description="Confidence in the recommendation, from 0.0 to 1.0")
    met_criteria: list[str] = Field(default_factory=list)
    unmet_criteria: list[str] = Field(default_factory=list)
    reviewer_focus_areas: list[str] = Field(
        default_factory=list, description="Specific questions the nurse should answer"
    )
    citations: list[str] = Field(
        default_factory=list, description="Policy IDs / criterion text referenced"
    )
    risk_flags: list[str] = Field(
        default_factory=list, description="Fraud indicators, contradictions, regulatory concerns"
    )
    estimated_review_minutes: int = Field(
        description="Realistic nurse review time in minutes, from 1 to 60"
    )
    rationale: str = Field(description="Brief explanation supporting the recommendation")

    # See the NOTE on ExtractedRequest.confidence_score above — same reason these are clamped
    # here rather than declared via Field(ge=, le=).
    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("estimated_review_minutes")
    @classmethod
    def _clamp_review_minutes(cls, v: int) -> int:
        return max(1, min(60, v))


class RiskRouting(BaseModel):
    pathway: Pathway
    sla_hours: float
    requires_human_review: bool
    reason: str

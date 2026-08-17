"""Pydantic request/response models for the FastAPI serving layer."""
from __future__ import annotations

from pydantic import BaseModel


class PreprocessRequest(BaseModel):
    text: str


class PreprocessResponse(BaseModel):
    normalized_text: str


class ClassifyRequest(BaseModel):
    text: str


class ClassificationResult(BaseModel):
    category: str
    confidence: float


class ClassifyResponse(BaseModel):
    classifications: list[ClassificationResult]


class ExtractEntitiesRequest(BaseModel):
    text: str


class Entity(BaseModel):
    label: str
    text: str
    start: int
    end: int


class ExtractEntitiesResponse(BaseModel):
    entities: list[Entity]


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    vector: list[float]


class SimilarCasesRequest(BaseModel):
    text: str
    k: int = 5


class SimilarCase(BaseModel):
    case_id: str
    vin: str
    narrative_text: str
    categories: list[str]
    score: float


class SimilarCasesResponse(BaseModel):
    similar_cases: list[SimilarCase]
    vector: list[float]


class IndexCaseRequest(BaseModel):
    case_id: str
    vin: str
    narrative_text: str
    submitted_by: str
    dealer_location: str | None = None
    mileage: int | None = None
    vehicle_model: str | None = None
    model_year: int | None = None
    classifications: list[ClassificationResult]
    entities: list[Entity]
    narrative_vector: list[float]
    similar_cases: list[SimilarCase] = []


class IndexCaseResponse(BaseModel):
    case_id: str
    status: str
    escalation_raised: bool
    escalation_trigger_reason: str | None = None
    escalation_id: int | None = None

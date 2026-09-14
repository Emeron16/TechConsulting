"""The FastAPI serving layer -- the single access point for
classify/NER/embed/similarity-search/index operations described in
Volvo_Architecture_Deep_Dive.md's FastAPI serving layer. Both Streamlit
(Phase 9) and Airflow's DAG tasks (Phase 7) call these endpoints over
HTTP; neither imports volvo_models/volvo_pipeline/volvo_retrieval
directly, per the "one true serving layer" decision in
Volvo_Implementation_Plan.md.

Run via: uvicorn api.main:app --port 8100 (from volvo-demo/)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI  # noqa: E402

from api.schemas import (  # noqa: E402
    ClassificationResult,
    ClassifyRequest,
    ClassifyResponse,
    EmbedRequest,
    EmbedResponse,
    Entity,
    ExtractEntitiesRequest,
    ExtractEntitiesResponse,
    IndexCaseRequest,
    IndexCaseResponse,
    PreprocessRequest,
    PreprocessResponse,
    SimilarCase,
    SimilarCasesRequest,
    SimilarCasesResponse,
)
from volvo_models.classifier import classify as run_classify  # noqa: E402
from volvo_models.ner import extract_entities as run_extract_entities  # noqa: E402
from volvo_models.similarity import embed as run_embed  # noqa: E402
from volvo_models.text_normalize import normalize_text  # noqa: E402
from volvo_pipeline.escalation import check_escalation  # noqa: E402
from volvo_retrieval.audit import append_audit_entry  # noqa: E402
from volvo_retrieval.case_search import find_similar_cases, index_case  # noqa: E402
from volvo_retrieval.opensearch_client import ensure_index  # noqa: E402
from volvo_retrieval.postgres_client import (  # noqa: E402
    get_pg_connection,
    insert_case_classifications,
    insert_extracted_entities,
    insert_safety_escalation,
    insert_warranty_case,
    update_case_status,
)

app = FastAPI(title="Volvo Dealer Service & Warranty Intelligence API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/preprocess", response_model=PreprocessResponse)
def preprocess(request: PreprocessRequest) -> PreprocessResponse:
    return PreprocessResponse(normalized_text=normalize_text(request.text))


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest) -> ClassifyResponse:
    results = run_classify(request.text)
    return ClassifyResponse(
        classifications=[ClassificationResult(category=c, confidence=conf) for c, conf in results]
    )


@app.post("/extract-entities", response_model=ExtractEntitiesResponse)
def extract_entities(request: ExtractEntitiesRequest) -> ExtractEntitiesResponse:
    entities = run_extract_entities(request.text)
    return ExtractEntitiesResponse(entities=[Entity(**e) for e in entities])


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    return EmbedResponse(vector=run_embed(request.text))


@app.post("/similar-cases", response_model=SimilarCasesResponse)
def similar_cases(request: SimilarCasesRequest) -> SimilarCasesResponse:
    vector = run_embed(request.text)
    client = ensure_index()
    results = find_similar_cases(client, vector, k=request.k)
    return SimilarCasesResponse(
        similar_cases=[SimilarCase(**r) for r in results],
        vector=vector,
    )


@app.post("/index-case", response_model=IndexCaseResponse)
def index_case_endpoint(request: IndexCaseRequest) -> IndexCaseResponse:
    categories = [c.category for c in request.classifications]

    conn = get_pg_connection()
    try:
        insert_warranty_case(
            conn,
            case_id=request.case_id,
            vin=request.vin,
            narrative_text=request.narrative_text,
            submitted_by=request.submitted_by,
            dealer_location=request.dealer_location,
            mileage=request.mileage,
            vehicle_model=request.vehicle_model,
            model_year=request.model_year,
        )
        insert_case_classifications(
            conn, request.case_id, [(c.category, c.confidence) for c in request.classifications]
        )
        insert_extracted_entities(conn, request.case_id, [e.model_dump() for e in request.entities])

        opensearch_client = ensure_index()
        index_case(
            opensearch_client,
            case_id=request.case_id,
            vin=request.vin,
            narrative_text=request.narrative_text,
            categories=categories,
            entities=[e.model_dump() for e in request.entities],
            narrative_vector=request.narrative_vector,
            dealer_location=request.dealer_location,
            vehicle_model=request.vehicle_model,
            model_year=request.model_year,
            mileage=request.mileage,
        )

        append_audit_entry(
            conn,
            event_type="case_submitted",
            payload={
                "case_id": request.case_id,
                "vin": request.vin,
                "categories": categories,
            },
            actor=request.submitted_by,
        )

        similar_cases_dicts = [c.model_dump() for c in request.similar_cases]
        decision = check_escalation(conn, request.case_id, categories, similar_cases_dicts)

        escalation_id = None
        if decision is not None:
            update_case_status(conn, request.case_id, "escalated")
            escalation_id = insert_safety_escalation(
                conn, request.case_id, decision.trigger_reason, decision.related_case_ids
            )
            append_audit_entry(
                conn,
                event_type="safety_escalation_raised",
                payload={
                    "case_id": request.case_id,
                    "trigger_reason": decision.trigger_reason,
                    "related_case_ids": decision.related_case_ids,
                },
                actor="system",
            )

        return IndexCaseResponse(
            case_id=request.case_id,
            status="escalated" if decision is not None else "indexed",
            escalation_raised=decision is not None,
            escalation_trigger_reason=decision.trigger_reason if decision else None,
            escalation_id=escalation_id,
        )
    finally:
        conn.close()

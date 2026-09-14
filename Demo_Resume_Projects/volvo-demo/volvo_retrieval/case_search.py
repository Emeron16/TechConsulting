"""OpenSearch read/write wrappers for warranty cases -- indexing a
classified+embedded case, and querying it back by VIN (exact), symptom
(keyword+semantic hybrid), or narrative-vector similarity (kNN). Only this
module touches the OpenSearch client directly outside of
opensearch_client.py itself.
"""
from __future__ import annotations

from opensearchpy import OpenSearch

from volvo_retrieval.opensearch_client import INDEX_NAME, get_opensearch_client


def index_case(
    client: OpenSearch,
    case_id: str,
    vin: str,
    narrative_text: str,
    categories: list[str],
    entities: list[dict],
    narrative_vector: list[float],
    dealer_location: str | None = None,
    vehicle_model: str | None = None,
    model_year: int | None = None,
    mileage: int | None = None,
) -> None:
    doc = {
        "case_id": case_id,
        "vin": vin,
        "narrative_text": narrative_text,
        "dealer_location": dealer_location,
        "vehicle_model": vehicle_model,
        "model_year": model_year,
        "mileage": mileage,
        "categories": categories,
        "entities": entities,
        "narrative_vector": narrative_vector,
    }
    client.index(index=INDEX_NAME, id=case_id, body=doc, refresh=True)


def find_similar_cases(client: OpenSearch, narrative_vector: list[float], k: int = 5) -> list[dict]:
    """Returns up to k most similar cases by narrative-vector cosine
    similarity, excluding no case in particular (callers filter out the
    case being processed by case_id if it happens to already be indexed).
    """
    response = client.search(
        index=INDEX_NAME,
        body={
            "size": k,
            "query": {"knn": {"narrative_vector": {"vector": narrative_vector, "k": k}}},
        },
    )
    return [
        {
            "case_id": hit["_source"]["case_id"],
            "vin": hit["_source"]["vin"],
            "narrative_text": hit["_source"]["narrative_text"],
            "categories": hit["_source"]["categories"],
            "score": hit["_score"],
        }
        for hit in response["hits"]["hits"]
    ]


def search_by_vin(client: OpenSearch, vin: str) -> list[dict]:
    response = client.search(index=INDEX_NAME, body={"query": {"term": {"vin": vin}}})
    return [hit["_source"] for hit in response["hits"]["hits"]]


def search_by_keyword(
    client: OpenSearch, query_text: str, categories: list[str] | None = None, dealer_location: str | None = None
) -> list[dict]:
    must_clauses: list[dict] = [{"match": {"narrative_text": query_text}}]
    filter_clauses: list[dict] = []
    if categories:
        filter_clauses.append({"terms": {"categories": categories}})
    if dealer_location:
        filter_clauses.append({"term": {"dealer_location": dealer_location}})

    body = {"query": {"bool": {"must": must_clauses, "filter": filter_clauses}}}
    response = client.search(index=INDEX_NAME, body=body)
    return [
        {**hit["_source"], "score": hit["_score"]}
        for hit in response["hits"]["hits"]
    ]


def list_all_cases(client: OpenSearch, size: int = 200) -> list[dict]:
    response = client.search(index=INDEX_NAME, body={"query": {"match_all": {}}, "size": size})
    return [hit["_source"] for hit in response["hits"]["hits"]]

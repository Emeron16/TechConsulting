"""OpenSearch connection + index schema -- the combined structured-filter +
full-text + vector index described in Volvo_Architecture_Deep_Dive.md §2.7.
Only volvo_retrieval touches OpenSearch directly; other packages call
through case_search.py's wrapper functions, never this module's client
object.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent / ".env")

INDEX_NAME = os.environ.get("OPENSEARCH_INDEX", "volvo_warranty_cases")
VECTOR_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2

CATEGORIES = (
    "powertrain",
    "infotainment",
    "electrical",
    "braking",
    "software_update",
    "safety_concern",
    "parts_delay",
    "dealer_escalation",
)

INDEX_BODY = {
    "settings": {
        "index.knn": True,
    },
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "vin": {"type": "keyword"},
            "narrative_text": {"type": "text"},
            "dealer_location": {"type": "keyword"},
            "vehicle_model": {"type": "keyword"},
            "model_year": {"type": "integer"},
            "mileage": {"type": "integer"},
            "categories": {"type": "keyword"},
            "category_scores": {"type": "object", "enabled": False},
            "entities": {
                "type": "nested",
                "properties": {
                    "label": {"type": "keyword"},
                    "text": {"type": "text"},
                },
            },
            "narrative_vector": {
                "type": "knn_vector",
                "dimension": VECTOR_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "lucene",
                    "space_type": "cosinesimil",
                },
            },
            "created_at": {"type": "date"},
        }
    },
}


def get_opensearch_client() -> OpenSearch:
    return OpenSearch(
        hosts=[
            {
                "host": os.environ.get("OPENSEARCH_HOST", "localhost"),
                "port": int(os.environ.get("OPENSEARCH_PORT", "9201")),
            }
        ],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
    )


def ensure_index(client: OpenSearch | None = None) -> OpenSearch:
    """Creates the volvo_warranty_cases index if it doesn't already exist.
    Idempotent: safe to call on every app/script startup.
    """
    client = client or get_opensearch_client()
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_BODY)
    return client

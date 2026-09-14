"""Qdrant connection + collection schema -- the OpenSearch Serverless analog.
Only nrg_retrieval touches Qdrant directly; nrg_chains calls through
hybrid_search.py's wrapper functions, never this module's client object.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, SparseVectorParams, VectorParams

load_dotenv(Path(__file__).parent.parent / ".env")

COLLECTION_NAME = "nrg_knowledge_base"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_VECTOR_SIZE = 1536  # text-embedding-3-small

DOC_TYPES = (
    "plan_rate",
    "billing_policy",
    "outage_procedure",
    "escalation_playbook",
    "compliance_disclosure",
)


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "localhost"),
        port=int(os.environ.get("QDRANT_HTTP_PORT", "6343")),
        grpc_port=int(os.environ.get("QDRANT_GRPC_PORT", "6344")),
    )


def ensure_collection(client: QdrantClient | None = None) -> QdrantClient:
    """Creates the nrg_knowledge_base collection if it doesn't already
    exist -- named vectors for dense (OpenAI text-embedding-3-small,
    cosine) + sparse (fastembed, e.g. Qdrant/bm25), so a single point
    carries both retrieval signals and Qdrant's Query API can fuse them
    server-side (see nrg_retrieval/hybrid_search.py). Idempotent: safe to
    call on every app/script startup.
    """
    client = client or get_qdrant_client()
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(size=DENSE_VECTOR_SIZE, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(),
            },
        )
    return client

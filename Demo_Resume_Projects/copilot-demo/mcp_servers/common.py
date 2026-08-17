"""Shared data-access helpers for MCP servers.

Each MCP server is the only thing that talks to Chroma/Postgres directly --
agents never get raw DB/vector-store access, only the narrow tool surface
each server exposes.
"""
import os
from pathlib import Path

import chromadb
import psycopg
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

from copilot_agents.cache import CachedEmbeddingFunction, get_cached_retrieval, set_cached_retrieval
from mcp_servers.hybrid_search import hybrid_search

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# CHROMA_PERSIST_DIR is conventionally a relative path (./chroma_db) --
# resolve it against this project's root, not the process's cwd. Without
# this, a caller that imports this module from a different working
# directory (e.g. shell/novartis_wrapper.py, which loads this demo's .env
# but launches from shell/'s own cwd) would silently open/create an empty
# chroma_db/ under whatever cwd it happens to run from, instead of this
# project's actual persisted collection.
CHROMA_DIR = str(ROOT / os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db"))
COLLECTION_NAME = "quality_documents"
EMBEDDING_MODEL = "text-embedding-3-small"


def get_chroma_collection():
    raw_embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"], model_name=EMBEDDING_MODEL
    )
    cached_embedding_fn = CachedEmbeddingFunction(raw_embedding_fn, EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_collection(COLLECTION_NAME, embedding_function=cached_embedding_fn)


def get_pg_connection():
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "copilot"),
        user=os.environ.get("POSTGRES_USER", "copilot"),
        password=os.environ.get("POSTGRES_PASSWORD", "copilot"),
    )


def search_documents(query: str, doc_type: str | None = None, n_results: int = 3) -> list[dict]:
    """Hybrid retrieval: BM25 + dense vector search, fused via RRF, then
    cross-encoder reranked (mcp_servers/hybrid_search.py). Retrieval
    results are cached for a short TTL (copilot_agents/cache.py) since
    identical queries within that window are common in a demo session and
    the reranker is the most expensive step per call.
    """
    cached = get_cached_retrieval(query, doc_type, n_results)
    if cached is not None:
        for r in cached:
            r["cache_hit"] = True
        return cached

    collection = get_chroma_collection()
    results = hybrid_search(collection, query, doc_type=doc_type, n_results=n_results)
    for r in results:
        r["cache_hit"] = False

    set_cached_retrieval(query, doc_type, n_results, results)
    return results

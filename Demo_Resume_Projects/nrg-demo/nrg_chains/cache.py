"""Local disk-backed caching -- the Redis analog (per
NRG_Free_Alternative_Stack.md: diskcache chosen over Redis to match
copilot-demo's proven implementation and this project's priority on local
tools). Two namespaces:

  - embeddings: keyed on hash(model, text), never expires -- embeddings for
    a given text + model are deterministic.
  - retrieval: keyed on hash(query, doc_type, top_k), short TTL (5 min) so
    results reflect recent KB changes reasonably promptly.

Deliberately does NOT cache LLM final answers, same governance stance as
copilot-demo: a cached answer going stale against updated source documents
(a new plan version, a rate change) is a real business/regulatory risk in
a way a cached embedding is not.
"""
import hashlib
import json
import os
from pathlib import Path

import diskcache

CACHE_DIR = os.environ.get("CACHE_DIR", "./cache")
RETRIEVAL_TTL_SECONDS = 5 * 60

_embedding_cache: diskcache.Cache | None = None
_retrieval_cache: diskcache.Cache | None = None


def _get_embedding_cache() -> diskcache.Cache:
    global _embedding_cache
    if _embedding_cache is None:
        _embedding_cache = diskcache.Cache(str(Path(CACHE_DIR) / "embeddings"))
    return _embedding_cache


def _get_retrieval_cache() -> diskcache.Cache:
    global _retrieval_cache
    if _retrieval_cache is None:
        _retrieval_cache = diskcache.Cache(str(Path(CACHE_DIR) / "retrieval"))
    return _retrieval_cache


def _text_key(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}::{text}".encode()).hexdigest()


def get_cached_embedding(text: str, model: str) -> list[float] | None:
    return _get_embedding_cache().get(_text_key(text, model))


def set_cached_embedding(text: str, model: str, embedding: list[float]) -> None:
    _get_embedding_cache().set(_text_key(text, model), embedding)


def get_cached_embeddings_batch(texts: list[str], model: str, embed_fn) -> list[list[float]]:
    """embed_fn(list[str]) -> list[list[float]] is the raw (uncached)
    embedding call -- called once with only the cache-miss texts, same
    batching approach as copilot-demo's CachedEmbeddingFunction.__call__,
    just as a plain function instead of a class wrapping Chroma's
    EmbeddingFunction protocol, since NRG calls OpenAI's embeddings API
    directly rather than through Chroma's embedding-function indirection.
    """
    results: list[list[float] | None] = [get_cached_embedding(t, model) for t in texts]
    missing_indices = [i for i, r in enumerate(results) if r is None]

    if missing_indices:
        missing_texts = [texts[i] for i in missing_indices]
        fresh = embed_fn(missing_texts)
        for idx, text, embedding in zip(missing_indices, missing_texts, fresh):
            embedding_list = list(embedding)
            set_cached_embedding(text, model, embedding_list)
            results[idx] = embedding_list

    return results  # type: ignore[return-value]


def _retrieval_key(query: str, doc_type: str | None, top_k: int) -> str:
    payload = json.dumps({"query": query, "doc_type": doc_type, "top_k": top_k}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get_cached_retrieval(query: str, doc_type: str | None, top_k: int) -> list[dict] | None:
    return _get_retrieval_cache().get(_retrieval_key(query, doc_type, top_k))


def set_cached_retrieval(query: str, doc_type: str | None, top_k: int, results: list[dict]) -> None:
    _get_retrieval_cache().set(
        _retrieval_key(query, doc_type, top_k), results, expire=RETRIEVAL_TTL_SECONDS
    )


def invalidate_retrieval_cache() -> None:
    """Called whenever the KB corpus changes (nrg_chains/ingest.py's
    consumer-side embed+upsert step) -- full clear, same reasoning as
    copilot-demo: retrieval cache keys are hash(query, doc_type, top_k),
    not doc_id, so there's no way to know which cached queries' results
    included the changed document without re-running them.
    """
    _get_retrieval_cache().clear()

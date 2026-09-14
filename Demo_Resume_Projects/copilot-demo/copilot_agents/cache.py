"""Local disk-backed caching -- two namespaces:

  - embeddings: keyed on hash(text), never expires (embeddings for a given
    text + model are deterministic -- the only way they go stale is if the
    text itself changes, which is a different cache key).
  - retrieval: keyed on hash(query, doc_type, n_results), short TTL (5 min)
    since retrieval results should reflect recent KB changes reasonably
    promptly, not be served from an arbitrarily old cache.

Deliberately does NOT cache LLM final answers -- every agent run reasons
fresh over the (possibly cached) retrieved context, per the project's
governance stance: a cached compliance answer going stale against updated
source documents is a real regulatory risk in a way a cached embedding
is not.
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


def _retrieval_key(query: str, doc_type: str | None, n_results: int) -> str:
    payload = json.dumps({"query": query, "doc_type": doc_type, "n_results": n_results}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get_cached_retrieval(query: str, doc_type: str | None, n_results: int) -> list[dict] | None:
    return _get_retrieval_cache().get(_retrieval_key(query, doc_type, n_results))


def set_cached_retrieval(query: str, doc_type: str | None, n_results: int, results: list[dict]) -> None:
    _get_retrieval_cache().set(
        _retrieval_key(query, doc_type, n_results), results, expire=RETRIEVAL_TTL_SECONDS
    )


def invalidate_retrieval_cache() -> None:
    """Called whenever the KB corpus changes (copilot_agents/kb_ingest.py's
    ingest_document()) -- full clear rather than doc_id-scoped invalidation.
    Retrieval cache keys are hash(query, doc_type, n_results), not doc_id,
    so there's no way to know which cached queries' results included the
    changed document without re-running them -- a full clear is the only
    correct option at this granularity, and safe given the demo's low
    query volume and short TTL.
    """
    _get_retrieval_cache().clear()


class CachedEmbeddingFunction:
    """Wraps a ChromaDB EmbeddingFunction (e.g. OpenAIEmbeddingFunction) with
    a disk cache. Chroma's EmbeddingFunction protocol is more than just
    __call__ (name(), get_config(), is_legacy(), etc. -- used for config
    persistence/validation on the collection) -- __getattr__ transparently
    proxies all of that to the wrapped function so this remains a true
    drop-in replacement without having to reimplement Chroma's interface.
    """

    def __init__(self, wrapped, model_name: str):
        self._wrapped = wrapped
        self._model_name = model_name

    def __getattr__(self, name):
        # Only reached for attributes not found normally (i.e. not
        # __init__/__call__/_wrapped/_model_name) -- proxies everything
        # else Chroma's EmbeddingFunction protocol needs to self._wrapped.
        return getattr(self._wrapped, name)

    def __call__(self, input: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [get_cached_embedding(t, self._model_name) for t in input]
        missing_indices = [i for i, r in enumerate(results) if r is None]

        if missing_indices:
            missing_texts = [input[i] for i in missing_indices]
            fresh = self._wrapped(missing_texts)
            for idx, text, embedding in zip(missing_indices, missing_texts, fresh):
                embedding_list = list(embedding)
                set_cached_embedding(text, self._model_name, embedding_list)
                results[idx] = embedding_list

        return results

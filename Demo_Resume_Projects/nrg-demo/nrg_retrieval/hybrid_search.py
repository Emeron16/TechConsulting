"""Hybrid retrieval pipeline -- the OpenSearch Serverless (BM25 + vector)
analog. Unlike copilot-demo's hand-rolled BM25/vector/RRF pipeline
(mcp_servers/hybrid_search.py, ~270 lines), Qdrant's Query API does dense
retrieval, sparse (BM25-style) retrieval, and Reciprocal Rank Fusion
server-side in one round trip via query_points(prefetch=[...],
query=FusionQuery(fusion=Fusion.RRF)) -- no in-process BM25 index to build
or keep in sync with the corpus. A cross-encoder rerank is still layered on
top of the fused results, for scoring parity with copilot-demo's pipeline
and because Qdrant's RRF fusion alone doesn't read query/document semantics
the way a cross-encoder does.

Results are cached (nrg_chains/cache.py, diskcache) same as copilot-demo's
retrieval cache -- short TTL, invalidated on any ingestion event.
"""
import os

from fastembed import SparseTextEmbedding
from langchain_openai import OpenAIEmbeddings
from qdrant_client.models import (
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)
from sentence_transformers import CrossEncoder

from nrg_chains.cache import get_cached_retrieval, set_cached_retrieval
from nrg_retrieval.qdrant_client import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ensure_collection,
)

DENSE_MODEL = "text-embedding-3-small"
SPARSE_MODEL = "Qdrant/bm25"
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

PREFETCH_LIMIT = 20
FUSION_TOP_K = 10

_dense_embedder: OpenAIEmbeddings | None = None
_sparse_embedder: SparseTextEmbedding | None = None
_reranker: CrossEncoder | None = None


def _get_dense_embedder() -> OpenAIEmbeddings:
    global _dense_embedder
    if _dense_embedder is None:
        _dense_embedder = OpenAIEmbeddings(model=DENSE_MODEL)
    return _dense_embedder


def _get_sparse_embedder() -> SparseTextEmbedding:
    global _sparse_embedder
    if _sparse_embedder is None:
        _sparse_embedder = SparseTextEmbedding(model_name=SPARSE_MODEL)
    return _sparse_embedder


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        # Same offline-mode-if-cached optimization as copilot-demo's
        # hybrid_search.py -- avoids a network round-trip to the HF Hub on
        # every call once the model is locally cached.
        from pathlib import Path

        model_cache_name = RERANK_MODEL_NAME.replace("/", "--")
        if any(Path.home().glob(f".cache/huggingface/hub/models--{model_cache_name}")):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        _reranker = CrossEncoder(RERANK_MODEL_NAME)
    return _reranker


def _fused_search(query: str, doc_type: str | None, limit: int) -> list[dict]:
    client = ensure_collection()

    dense_vec = _get_dense_embedder().embed_query(query)
    sparse_vec = list(_get_sparse_embedder().embed([query]))[0]

    query_filter = None
    if doc_type:
        query_filter = Filter(must=[FieldCondition(key="doc_type", match=MatchValue(value=doc_type))])

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using=DENSE_VECTOR_NAME, limit=PREFETCH_LIMIT, filter=query_filter),
            Prefetch(
                query=SparseVector(indices=sparse_vec.indices.tolist(), values=sparse_vec.values.tolist()),
                using=SPARSE_VECTOR_NAME,
                limit=PREFETCH_LIMIT,
                filter=query_filter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    )

    return [
        {
            "chunk_id": str(point.id),
            "text": point.payload.get("text", ""),
            "metadata": point.payload,
            "fusion_score": point.score,
        }
        for point in results.points
    ]


def _rerank(query: str, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return candidates
    reranker = _get_reranker()
    pairs = [(query, c["text"]) for c in candidates]
    scores = reranker.predict(pairs)
    for candidate, score in zip(candidates, scores):
        candidate["rerank_score"] = float(score)
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    return candidates


def _merge_chunks_by_doc_id(reranked: list[dict], top_k: int) -> list[dict]:
    """Collapses multiple chunks of the same doc_id into one entry per
    document, same reasoning as copilot-demo's merge step: without this, a
    single search can return the same document 2-3 times as separate
    entries with different scores, which reads as ambiguous/untrustworthy
    to a downstream LLM and drives unnecessary re-querying.
    """
    seen_order: list[str] = []
    merged: dict[str, dict] = {}

    for item in reranked:
        doc_id = item["metadata"]["doc_id"]
        if doc_id not in merged:
            seen_order.append(doc_id)
            merged[doc_id] = dict(item)
            merged[doc_id]["_extra_texts"] = []
        else:
            merged[doc_id]["_extra_texts"].append(item["text"])

    output = []
    for doc_id in seen_order[:top_k]:
        entry = merged[doc_id]
        extra = entry.pop("_extra_texts")
        text = entry["text"]
        if extra:
            text = text + "\n\n[...additional excerpt(s) from the same document...]\n\n" + "\n\n".join(extra)
        entry["text"] = text
        output.append(entry)
    return output


def hybrid_search(query: str, doc_type: str | None = None, top_k: int = 5) -> list[dict]:
    """Full pipeline: Qdrant dense+sparse+RRF fusion -> cross-encoder
    rerank -> merge chunks by doc_id -> top top_k. Returns dicts shaped to
    build SearchResultNRG models from directly (see nrg_chains/schemas.py):
    doc_id, title, doc_type, version, effective_date, excerpt, plus
    dense_score/sparse_score/fusion_score/rerank_score/cache_hit.

    Note: Qdrant's fused point.score is the RRF score, not separable back
    into per-space dense/sparse contributions after fusion -- dense_score
    and sparse_score are surfaced as None here (fusion_score is the
    meaningful signal post-fusion); a caller wanting the pre-fusion
    per-space scores would need to also run the two Prefetch queries
    standalone, which _fused_search deliberately avoids doing twice.
    """
    cached = get_cached_retrieval(query, doc_type, top_k)
    if cached is not None:
        for r in cached:
            r["cache_hit"] = True
        return cached

    fused = _fused_search(query, doc_type, PREFETCH_LIMIT)
    reranked = _rerank(query, fused)
    merged = _merge_chunks_by_doc_id(reranked, top_k)

    output = []
    for item in merged:
        meta = item["metadata"]
        output.append(
            {
                "doc_id": meta["doc_id"],
                "title": meta["title"],
                "doc_type": meta["doc_type"],
                "version": meta["version"],
                "effective_date": meta.get("effective_date", ""),
                "excerpt": item["text"],
                "dense_score": None,
                "sparse_score": None,
                "fusion_score": round(item["fusion_score"], 4) if item.get("fusion_score") is not None else None,
                "rerank_score": round(item["rerank_score"], 4) if item.get("rerank_score") is not None else None,
                "cache_hit": False,
            }
        )

    set_cached_retrieval(query, doc_type, top_k, output)
    return output

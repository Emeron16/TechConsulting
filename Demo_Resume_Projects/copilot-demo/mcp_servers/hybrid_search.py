"""Hybrid retrieval pipeline: BM25 keyword search + ChromaDB dense vector
search, fused via Reciprocal Rank Fusion, then reranked with a local
cross-encoder -- replaces the pure-vector search mcp_servers/common.py used
previously. Every stage's score is kept on the result (not collapsed into
one number) so the ranking is auditable, per this project's governance
stance for a regulated-industry system.

BM25 index is built once per process from the full Chroma corpus and
rebuilt on demand via rebuild_bm25_index() -- called from
copilot_agents/kb_ingest.py whenever the corpus changes, so it can't
silently go stale after an upload/versioning change.
"""
import os
import re
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi

RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Every question spawns brand-new MCP server subprocesses (see
# copilot_agents/mcp_connections.py), so the reranker model gets
# instantiated fresh on every single query. sentence-transformers/HF hub
# does a network round-trip to check for model updates even when the model
# is already cached locally, adding real latency to every query and
# contributing to the MCP tool-call timeout (see mcp_connections.py's
# TOOL_TIMEOUT_SECONDS comment). If the model is already in the local HF
# cache, force offline mode so CrossEncoder() loads from disk only --
# skips the network check entirely. Falls through to normal (online) mode
# on first-ever run, when the model genuinely needs to be downloaded.
_hf_cache_has_model = any(
    Path.home().glob(f".cache/huggingface/hub/models--{RERANK_MODEL_NAME.replace('/', '--')}")
)
if _hf_cache_has_model:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

from sentence_transformers import CrossEncoder  # noqa: E402 -- must follow HF_HUB_OFFLINE setdefault
VECTOR_TOP_N = 15
BM25_TOP_N = 15
FUSION_TOP_K = 10
RRF_K = 60  # standard RRF damping constant

_bm25_lock = threading.Lock()
_bm25_index: BM25Okapi | None = None
_bm25_chunk_ids: list[str] = []
_bm25_chunk_texts: list[str] = []
_bm25_metadatas: list[dict] = []

_reranker_lock = threading.Lock()
_reranker: CrossEncoder | None = None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = CrossEncoder(RERANK_MODEL_NAME)
    return _reranker


def rebuild_bm25_index(collection) -> None:
    """Pulls every chunk out of the given Chroma collection and rebuilds
    the in-memory BM25 index from scratch. Call after any ingestion event
    (new doc, new version, soft delete) -- there is no incremental update
    path, a full rebuild is simple and fast enough at this corpus scale.
    """
    global _bm25_index, _bm25_chunk_ids, _bm25_chunk_texts, _bm25_metadatas
    with _bm25_lock:
        all_chunks = collection.get()
        ids = all_chunks["ids"]
        texts = all_chunks["documents"]
        metadatas = all_chunks["metadatas"]

        tokenized = [_tokenize(t) for t in texts]
        _bm25_index = BM25Okapi(tokenized) if tokenized else None
        _bm25_chunk_ids = ids
        _bm25_chunk_texts = texts
        _bm25_metadatas = metadatas


def _ensure_bm25_index(collection) -> None:
    if _bm25_index is None:
        rebuild_bm25_index(collection)


def _bm25_search(
    collection, query: str, doc_type: str | None, top_n: int
) -> list[tuple[str, str, dict, float]]:
    """Returns list of (chunk_id, chunk_text, metadata, bm25_score),
    filtered by the same criteria the vector search uses (status=approved,
    optional doc_type), so both retrieval modes see the same eligible
    document set.
    """
    _ensure_bm25_index(collection)
    if _bm25_index is None:
        return []

    scores = _bm25_index.get_scores(_tokenize(query))

    def matches_filter(meta: dict) -> bool:
        if meta.get("status") != "approved":
            return False
        if doc_type and meta.get("doc_type") != doc_type:
            return False
        return True

    scored = [
        (_bm25_chunk_ids[i], _bm25_chunk_texts[i], _bm25_metadatas[i], float(scores[i]))
        for i in range(len(_bm25_chunk_ids))
        if matches_filter(_bm25_metadatas[i]) and scores[i] > 0
    ]
    scored.sort(key=lambda x: x[3], reverse=True)
    return scored[:top_n]


def _vector_search(collection, query: str, where: dict, top_n: int) -> list[tuple[str, str, dict, float]]:
    """Returns list of (chunk_id, chunk_text, metadata, vector_score) where
    vector_score = 1 - cosine_distance (higher is better, matches the
    existing relevance_score convention).
    """
    results = collection.query(query_texts=[query], n_results=top_n, where=where)
    if not results["ids"] or not results["ids"][0]:
        return []
    return [
        (chunk_id, doc_text, meta, round(1 - dist, 4))
        for chunk_id, doc_text, meta, dist in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
    ]


def _reciprocal_rank_fusion(
    bm25_results: list[tuple[str, str, dict, float]],
    vector_results: list[tuple[str, str, dict, float]],
    top_k: int,
) -> list[dict]:
    """RRF: fused_score(doc) = sum(1 / (RRF_K + rank)) across each ranking
    the doc appears in. Chosen over a weighted/learned blend because it's
    parameter-light and its behavior is easy to explain to an auditor --
    a document's fused rank depends only on where it placed in each
    individual ranking, not on a tuned weight that would need its own
    justification.
    """
    bm25_ranks = {chunk_id: rank for rank, (chunk_id, *_rest) in enumerate(bm25_results, start=1)}
    vector_ranks = {chunk_id: rank for rank, (chunk_id, *_rest) in enumerate(vector_results, start=1)}
    bm25_scores = {chunk_id: score for chunk_id, _text, _meta, score in bm25_results}
    vector_scores = {chunk_id: score for chunk_id, _text, _meta, score in vector_results}

    all_chunk_data = {cid: (text, meta) for cid, text, meta, _ in bm25_results}
    all_chunk_data.update({cid: (text, meta) for cid, text, meta, _ in vector_results})

    fused: list[tuple[str, float]] = []
    for chunk_id in all_chunk_data:
        score = 0.0
        if chunk_id in bm25_ranks:
            score += 1.0 / (RRF_K + bm25_ranks[chunk_id])
        if chunk_id in vector_ranks:
            score += 1.0 / (RRF_K + vector_ranks[chunk_id])
        fused.append((chunk_id, score))

    fused.sort(key=lambda x: x[1], reverse=True)
    top_fused = fused[:top_k]

    return [
        {
            "chunk_id": chunk_id,
            "text": all_chunk_data[chunk_id][0],
            "metadata": all_chunk_data[chunk_id][1],
            "bm25_score": bm25_scores.get(chunk_id),
            "vector_score": vector_scores.get(chunk_id),
            "fusion_rank": rank,
        }
        for rank, (chunk_id, _score) in enumerate(top_fused, start=1)
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


def _merge_chunks_by_doc_id(reranked: list[dict], n_results: int) -> list[dict]:
    """Collapses multiple chunks of the same doc_id into one entry per
    document, keeping the best-scoring chunk's scores as representative and
    concatenating additional same-doc chunk text into the excerpt.

    Without this, a single search can return the same document 2-3 times
    as separate list entries with different scores and no indication
    they're fragments of one document -- confirmed via live tracing to
    cause the model to distrust good results and re-query with
    near-identical phrasing instead of recognizing it already has what it
    needs, driving MaxTurnsExceeded failures. One row per document, with
    one clear score, gives the model an unambiguous signal to stop.
    """
    seen_order: list[str] = []
    merged: dict[str, dict] = {}

    for item in reranked:
        doc_id = item["metadata"]["doc_id"]
        if doc_id not in merged:
            seen_order.append(doc_id)
            merged[doc_id] = dict(item)  # best-scoring chunk for this doc (reranked is sorted)
            merged[doc_id]["_extra_texts"] = []
        else:
            # Lower-ranked chunk of an already-seen doc -- fold its text in
            # rather than surfacing it as a separate, confusing entry.
            merged[doc_id]["_extra_texts"].append(item["text"])

    output = []
    for doc_id in seen_order[:n_results]:
        entry = merged[doc_id]
        extra = entry.pop("_extra_texts")
        text = entry["text"]
        if extra:
            text = text + "\n\n[...additional excerpt(s) from the same document...]\n\n" + "\n\n".join(extra)
        entry["text"] = text
        output.append(entry)
    return output


def hybrid_search(collection, query: str, doc_type: str | None, n_results: int) -> list[dict]:
    """Full pipeline: BM25 + vector retrieval -> RRF fusion -> cross-encoder
    rerank -> merge chunks by doc_id -> top n_results. Both retrieval modes
    are filtered to status=approved plus the optional doc_type. Returns
    dicts with all score fields populated (doc_id, title, doc_type,
    version, effective_date, excerpt, plus bm25_score/vector_score/
    fusion_rank/rerank_score/relevance_score) -- shaped to build
    SearchResult models from directly (see copilot_agents/schemas.py).
    Exactly one entry per doc_id -- the agent sees one clear relevance
    signal per document, never split across multiple ambiguous rows.
    """
    where = {"status": "approved"}
    if doc_type:
        where = {"$and": [{"status": "approved"}, {"doc_type": doc_type}]}

    bm25_results = _bm25_search(collection, query, doc_type, BM25_TOP_N)
    vector_results = _vector_search(collection, query, where, VECTOR_TOP_N)

    fused = _reciprocal_rank_fusion(bm25_results, vector_results, FUSION_TOP_K)
    reranked = _rerank(query, fused)
    merged = _merge_chunks_by_doc_id(reranked, n_results)

    output = []
    for item in merged:
        meta = item["metadata"]
        output.append(
            {
                "doc_id": meta["doc_id"],
                "title": meta["title"],
                "doc_type": meta["doc_type"],
                "version": meta["version"],
                "effective_date": meta["effective_date"],
                "excerpt": item["text"],
                "relevance_score": round(item.get("rerank_score", 0.0), 4),
                "bm25_score": item["bm25_score"],
                "vector_score": item["vector_score"],
                "fusion_rank": item["fusion_rank"],
                "rerank_score": round(item["rerank_score"], 4) if item.get("rerank_score") is not None else None,
            }
        )
    return output

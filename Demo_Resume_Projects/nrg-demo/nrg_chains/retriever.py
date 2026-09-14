"""LangChain retriever wrapping nrg_retrieval.hybrid_search.hybrid_search().
A fresh instance is created per question with doc_type set via the
constructor, rather than threading a dynamic filter arg through LCEL's
.invoke() interface -- simpler for this demo's needs and avoids fighting
the Runnable interface for a single per-call parameter.
"""
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from nrg_retrieval.hybrid_search import hybrid_search


class NRGHybridRetriever(BaseRetriever):
    doc_type: str | None = None
    top_k: int = 5

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        results = hybrid_search(query, doc_type=self.doc_type, top_k=self.top_k)
        return [self._to_document(r) for r in results]

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        # hybrid_search() is synchronous (OpenAI/fastembed/Qdrant client
        # calls are all blocking) -- no separate async path exists to call
        # into, so the sync implementation is reused directly here rather
        # than duplicating it. Acceptable for this demo's query volume.
        return self._get_relevant_documents(query, run_manager=run_manager)

    @staticmethod
    def _to_document(result: dict[str, Any]) -> Document:
        return Document(
            page_content=result["excerpt"],
            metadata={
                "doc_id": result["doc_id"],
                "title": result["title"],
                "doc_type": result["doc_type"],
                "version": result["version"],
                "effective_date": result["effective_date"],
                "dense_score": result.get("dense_score"),
                "sparse_score": result.get("sparse_score"),
                "fusion_score": result.get("fusion_score"),
                "rerank_score": result.get("rerank_score"),
                "cache_hit": result.get("cache_hit", False),
            },
        )

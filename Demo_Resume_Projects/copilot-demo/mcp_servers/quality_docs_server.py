"""MCP Server: Quality Documents.

Exposes search over approved quality documents (SOPs, deviation reports,
CAPA records) generally -- narrower servers (sop_server, capa_server) expose
type-scoped variants of the same underlying search for agents that should
only see one document type.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from copilot_agents.schemas import SearchResult
from mcp_servers.common import search_documents

mcp = FastMCP("quality-documents")


@mcp.tool()
def search_quality_docs(query: str, doc_type: str | None = None) -> list[SearchResult]:
    """Search approved quality documents (SOPs, deviations, CAPAs, batch records)
    using hybrid retrieval: BM25 keyword search + dense vector search, fused
    via Reciprocal Rank Fusion, then reranked with a cross-encoder. Metadata
    filtering (status=approved only, optional doc_type) is applied in both
    the BM25 and vector stages.

    Args:
        query: Natural-language search query.
        doc_type: Optional filter -- one of "sop", "deviation", "capa", "batch_record".
    """
    return [SearchResult(**r) for r in search_documents(query, doc_type=doc_type)]


if __name__ == "__main__":
    mcp.run()

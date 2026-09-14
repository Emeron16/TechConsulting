"""MCP Server: SOP Repository.

Exposes search and direct lookup over approved SOP documents only --
scoped narrower than the general Quality Documents server so the SOP
Interpretation Agent can't accidentally retrieve deviation/CAPA content.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from copilot_agents.schemas import SearchResult, SopDocument, ToolError
from mcp_servers.common import get_chroma_collection, search_documents

mcp = FastMCP("sop-repository")


@mcp.tool()
def search_sops(query: str) -> list[SearchResult]:
    """Search approved SOP documents using hybrid retrieval: BM25 keyword
    search + dense vector search, fused via Reciprocal Rank Fusion, then
    reranked with a cross-encoder. Metadata filtering (status=approved,
    latest effective version only) is applied in both retrieval stages.

    Args:
        query: Natural-language search query, e.g. "escalation criteria for critical deviations".
    """
    return [SearchResult(**r) for r in search_documents(query, doc_type="sop")]


@mcp.tool()
def get_sop_by_id(sop_id: str) -> SopDocument | ToolError:
    """Fetch the full text of a specific approved SOP by its document ID.

    Args:
        sop_id: The SOP identifier, e.g. "SOP-114".
    """
    collection = get_chroma_collection()
    results = collection.get(
        where={"$and": [{"doc_id": sop_id}, {"status": "approved"}]},
        include=["documents", "metadatas"],
    )
    if not results["ids"]:
        return ToolError(error=f"No approved SOP found with id {sop_id}")

    chunks = sorted(zip(results["ids"], results["documents"]), key=lambda x: x[0])
    meta = results["metadatas"][0]
    return SopDocument(
        doc_id=meta["doc_id"],
        title=meta["title"],
        version=meta["version"],
        effective_date=meta["effective_date"],
        full_text="\n\n".join(chunk_text for _, chunk_text in chunks),
    )


if __name__ == "__main__":
    mcp.run()

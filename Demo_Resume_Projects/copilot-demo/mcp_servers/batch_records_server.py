"""MCP Server: Batch Records.

Exposes structured batch/deviation metadata from Postgres, plus semantic
search over batch record documents in Chroma -- mirrors the original
architecture's SQL-vs-search split for this domain.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from copilot_agents.schemas import BatchMetadata, DeviationRef, SearchResult, ToolError
from mcp_servers.common import get_pg_connection, search_documents

mcp = FastMCP("batch-records")


@mcp.tool()
def get_batch_metadata(batch_id: str) -> BatchMetadata | ToolError:
    """Fetch structured batch metadata (product, line, disposition status) and
    any associated deviations, from the batch/deviation tracking database.

    Args:
        batch_id: The batch identifier, e.g. "BATCH-4471".
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT batch_id, product_name, manufacturing_line, manufacturing_date, disposition_status
            FROM batches WHERE batch_id = %s
            """,
            (batch_id,),
        )
        row = cur.fetchone()
        if not row:
            return ToolError(error=f"No batch found with id {batch_id}")

        cur.execute(
            """
            SELECT deviation_id, classification, investigation_status, related_deviation_id
            FROM deviations WHERE batch_id = %s
            """,
            (batch_id,),
        )
        deviations = [
            DeviationRef(
                deviation_id=r[0],
                classification=r[1],
                investigation_status=r[2],
                related_deviation_id=r[3],
            )
            for r in cur.fetchall()
        ]

        return BatchMetadata(
            batch_id=row[0],
            product_name=row[1],
            manufacturing_line=row[2],
            manufacturing_date=str(row[3]),
            disposition_status=row[4],
            deviations=deviations,
        )


@mcp.tool()
def search_batch_records(query: str) -> list[SearchResult]:
    """Hybrid retrieval (BM25 + dense vector + cross-encoder rerank) over
    batch record documents (process parameters, disposition notes) for
    approved batch records.

    Args:
        query: Natural-language search query.
    """
    return [SearchResult(**r) for r in search_documents(query, doc_type="batch_record")]


if __name__ == "__main__":
    mcp.run()

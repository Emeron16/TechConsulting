"""MCP Server: CAPA / Enterprise Systems.

Exposes CAPA status lookups and CAPA draft creation. The "needs review"
event publish (Service Bus equivalent) is wired in Phase 4 -- for now
create_capa_draft just writes the draft status, matching the original
diagram's CAPACAGENT --> SERVICEBUS edge which gets built out later.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from copilot_agents.schemas import CapaDraft, CapaStatus, SearchResult, ToolError
from mcp_servers.common import get_pg_connection, search_documents

mcp = FastMCP("capa-enterprise")


@mcp.tool()
def get_capa_status(capa_id: str) -> CapaStatus | ToolError:
    """Fetch structured CAPA status (open/effective/ineffective/closed) and
    monitoring window from the CAPA tracking database.

    Args:
        capa_id: The CAPA identifier, e.g. "CAPA-3390".
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT capa_id, related_deviation_id, status, monitoring_start, monitoring_end
            FROM capas WHERE capa_id = %s
            """,
            (capa_id,),
        )
        row = cur.fetchone()
        if not row:
            return ToolError(error=f"No CAPA found with id {capa_id}")
        return CapaStatus(
            capa_id=row[0],
            related_deviation_id=row[1],
            status=row[2],
            monitoring_start=str(row[3]) if row[3] else None,
            monitoring_end=str(row[4]) if row[4] else None,
        )


@mcp.tool()
def search_capa_records(query: str) -> list[SearchResult]:
    """Hybrid retrieval (BM25 + dense vector + cross-encoder rerank) over
    approved CAPA record documents.

    Args:
        query: Natural-language search query.
    """
    return [SearchResult(**r) for r in search_documents(query, doc_type="capa")]


@mcp.tool()
def create_capa_draft(related_deviation_id: str, root_cause_summary: str, proposed_action: str) -> CapaDraft:
    """Create a draft CAPA record linked to a deviation, pending human review
    and approval before it becomes an official record.

    Args:
        related_deviation_id: The deviation this CAPA addresses, e.g. "DEV-2201".
        root_cause_summary: Brief root cause statement this CAPA traces back to.
        proposed_action: Proposed corrective/preventive action.
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM capas WHERE related_deviation_id = %s", (related_deviation_id,)
        )
        existing_count = cur.fetchone()[0]
        draft_capa_id = f"CAPA-DRAFT-{related_deviation_id}-{existing_count + 1}"

    return CapaDraft(
        draft_capa_id=draft_capa_id,
        related_deviation_id=related_deviation_id,
        root_cause_summary=root_cause_summary,
        proposed_action=proposed_action,
        status="draft_pending_review",
        note="This is a draft only -- requires human review/approval before becoming an official CAPA record (see Phase 4 review queue).",
    )


if __name__ == "__main__":
    mcp.run()

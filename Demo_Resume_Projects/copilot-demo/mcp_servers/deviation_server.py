"""MCP Server: Deviation Management.

Exposes deviation disposition drafting -- a structured classification +
investigation-closure proposal, pending human review, analogous to
capa_server.py's create_capa_draft but mechanically different: a deviation
record already exists pre-disposition (this UPDATEs it in place on
promotion), whereas a CAPA doesn't exist until promoted (INSERT).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from copilot_agents.schemas import DeviationDispositionDraft, ToolError
from mcp_servers.common import get_pg_connection

mcp = FastMCP("deviation-management")


@mcp.tool()
def create_deviation_disposition(
    deviation_id: str, proposed_classification: str, investigation_summary: str
) -> DeviationDispositionDraft | ToolError:
    """Create a draft disposition (classification + investigation closure) for
    an existing deviation, pending human review and approval before the
    deviation record is actually closed out.

    Args:
        deviation_id: The existing deviation identifier, e.g. "DEV-2201".
        proposed_classification: One of "critical", "major", "minor" -- the
            classification this disposition proposes, per SOP escalation criteria.
        investigation_summary: Narrative summary of the investigation findings
            supporting this classification and closure.
    """
    if proposed_classification not in ("critical", "major", "minor"):
        return ToolError(
            error=f"proposed_classification must be one of critical/major/minor, got {proposed_classification!r}"
        )

    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT deviation_id FROM deviations WHERE deviation_id = %s", (deviation_id,))
        if cur.fetchone() is None:
            return ToolError(error=f"No deviation found with id {deviation_id}")

    return DeviationDispositionDraft(
        draft_deviation_id=deviation_id,
        proposed_classification=proposed_classification,
        investigation_summary=investigation_summary,
        proposed_status="closed",
        status="draft_pending_review",
        note="This is a draft only -- requires human review/approval before the deviation record is closed (see review queue).",
    )


if __name__ == "__main__":
    mcp.run()

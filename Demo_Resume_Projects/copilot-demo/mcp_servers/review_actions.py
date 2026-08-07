"""Shared review_queue read/write operations -- used by both scripts/review.py
(CLI) and the Streamlit UI (Phase 5) so there's exactly one implementation
of approve/reject/list against Postgres.
"""
from mcp_servers.audit import append_audit_entry
from mcp_servers.common import get_pg_connection


def list_pending() -> list[dict]:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, draft_answer, created_at
            FROM review_queue WHERE status = 'pending'
            ORDER BY created_at ASC
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "agent_name": r[1],
            "question": r[2],
            "draft_answer": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def get_by_id(review_id: int) -> dict | None:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, status, reviewed_by, reviewed_at
            FROM review_queue WHERE id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "agent_name": row[1],
        "question": row[2],
        "status": row[3],
        "reviewed_by": row[4],
        "reviewed_at": row[5],
    }


def list_history(limit: int = 20) -> list[dict]:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, status, reviewed_by, reviewed_at
            FROM review_queue WHERE status != 'pending'
            ORDER BY reviewed_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "agent_name": r[1],
            "question": r[2],
            "status": r[3],
            "reviewed_by": r[4],
            "reviewed_at": r[5],
        }
        for r in rows
    ]


def approve(review_id: int, reviewer_name: str) -> tuple[bool, str, int | None]:
    """Returns (success, message, audit_id)."""
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT question, draft_answer, agent_name, status FROM review_queue WHERE id = %s",
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, f"No review_queue item with id {review_id}", None
        question, draft_answer, agent_name, status = row
        if status != "pending":
            return False, f"review_queue #{review_id} is already '{status}', not pending.", None

        cur.execute(
            """
            UPDATE review_queue
            SET status = 'approved', reviewed_at = now(), reviewed_by = %s
            WHERE id = %s
            """,
            (reviewer_name, review_id),
        )
        conn.commit()

        esign_payload = {
            "review_queue_id": review_id,
            "question": question,
            "approved_answer": draft_answer,
            "agent_name": agent_name,
            "attestation": (
                f"I, {reviewer_name}, have reviewed the AI-assisted answer above and "
                "approve it as accurate and appropriately grounded in the cited records."
            ),
        }
        audit_id = append_audit_entry(
            conn, event_type="e_signature_approval", payload=esign_payload, actor=reviewer_name
        )

    return True, f"review_queue #{review_id} approved by {reviewer_name}.", audit_id


def reject(review_id: int, reviewer_name: str, reason: str) -> tuple[bool, str, int | None]:
    """Returns (success, message, audit_id)."""
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT question, draft_answer, agent_name, status FROM review_queue WHERE id = %s",
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, f"No review_queue item with id {review_id}", None
        question, draft_answer, agent_name, status = row
        if status != "pending":
            return False, f"review_queue #{review_id} is already '{status}', not pending.", None

        cur.execute(
            """
            UPDATE review_queue
            SET status = 'rejected', reviewed_at = now(), reviewed_by = %s
            WHERE id = %s
            """,
            (reviewer_name, review_id),
        )
        conn.commit()

        audit_id = append_audit_entry(
            conn,
            event_type="review_rejection",
            payload={
                "review_queue_id": review_id,
                "question": question,
                "rejected_answer": draft_answer,
                "agent_name": agent_name,
                "reason": reason,
            },
            actor=reviewer_name,
        )

    return True, f"review_queue #{review_id} rejected by {reviewer_name}.", audit_id

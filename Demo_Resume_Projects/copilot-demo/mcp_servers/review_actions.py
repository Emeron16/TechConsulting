"""Shared review_queue read/write operations -- used by both scripts/review.py
(CLI) and the Streamlit UI (Phase 5) so there's exactly one implementation
of approve/reject/list against Postgres.
"""
import hashlib
import json

from mcp_servers.audit import append_audit_entry
from mcp_servers.auth import verify_qp_credentials
from mcp_servers.common import get_pg_connection


def _signed_record_hash(review_row: dict) -> str:
    """Binds the e-signature to the exact content being signed -- a SHA-256
    over the canonical JSON of the fields a QP is actually attesting to
    (question, draft answer, and the structured draft payload if any).
    Stored in the audit payload alongside the signature so a later change
    to what this review item represents (not possible today, since nothing
    updates review_queue's content after creation, but this makes that
    guarantee explicit and independently checkable rather than assumed)
    would produce a hash mismatch against the signed record.
    """
    canonical = json.dumps(
        {
            "review_id": review_row["review_id"],
            "question": review_row["question"],
            "draft_answer": review_row["draft_answer"],
            "linked_record_type": review_row["linked_record_type"],
            "linked_record_id": review_row["linked_record_id"],
            "structured_payload": review_row["structured_payload"],
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def list_pending() -> list[dict]:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, draft_answer, created_at,
                   linked_record_type, linked_record_id, structured_payload
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
            "linked_record_type": r[5],
            "linked_record_id": r[6],
            "structured_payload": r[7],
        }
        for r in rows
    ]


def get_by_id(review_id: int) -> dict | None:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, status, reviewed_by, reviewed_at,
                   linked_record_type, linked_record_id, structured_payload
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
        "linked_record_type": row[6],
        "linked_record_id": row[7],
        "structured_payload": row[8],
    }


def list_history(limit: int = 20) -> list[dict]:
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, question, status, reviewed_by, reviewed_at,
                   linked_record_type, linked_record_id, structured_payload
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
            "linked_record_type": r[6],
            "linked_record_id": r[7],
            "structured_payload": r[8],
        }
        for r in rows
    ]


def _promote_capa(cur, related_deviation_id: str, payload: dict) -> str:
    """Inserts a real capas row from a CapaDraft payload, synthesizing the
    real capa_id at promotion time (not reusing draft_capa_id) to avoid a
    TOCTOU collision if another CAPA for the same deviation was promoted
    while this draft was pending. Returns the new capa_id.
    """
    cur.execute("SELECT count(*) FROM capas WHERE related_deviation_id = %s", (related_deviation_id,))
    existing_count = cur.fetchone()[0]
    capa_id = f"CAPA-{related_deviation_id}-{existing_count + 1}"
    cur.execute(
        """
        INSERT INTO capas (capa_id, related_deviation_id, status, root_cause_summary, proposed_action)
        VALUES (%s, %s, 'open', %s, %s)
        """,
        (capa_id, related_deviation_id, payload.get("root_cause_summary"), payload.get("proposed_action")),
    )
    return capa_id


def _promote_deviation(cur, deviation_id: str, payload: dict) -> str | None:
    """Updates the existing deviations row in place from a
    DeviationDispositionDraft payload -- disposition closes out an existing
    investigation, it does not create a new entity. No-ops if the deviation
    is already closed, so a second approved disposition for the same
    deviation can't silently overwrite a prior QP's decision -- returns
    None in that case (not deviation_id) so approve() can tell "nothing
    changed" apart from "promoted," and doesn't log a false
    deviation_disposition_finalized audit event for a no-op.
    """
    cur.execute("SELECT investigation_status FROM deviations WHERE deviation_id = %s", (deviation_id,))
    current_status = cur.fetchone()[0]
    if current_status == "closed":
        return None  # already disposed by an earlier approval -- no-op

    cur.execute(
        """
        UPDATE deviations
        SET classification = %s, investigation_status = %s, investigation_summary = %s
        WHERE deviation_id = %s
        """,
        (
            payload.get("proposed_classification"),
            payload.get("proposed_status", "closed"),
            payload.get("investigation_summary"),
            deviation_id,
        ),
    )
    return deviation_id


def approve(review_id: int, username: str, password: str) -> tuple[bool, str, int | None]:
    """Returns (success, message, audit_id). Requires re-authentication --
    username/password are verified against qp_users (mcp_servers/auth.py)
    BEFORE any row is touched, so a failed signature attempt can never
    leave review_queue flipped to 'approved' with no valid e-signature
    behind it. This is the actual electronic-signature step (21 CFR Part
    11: re-authentication with a credential at the moment of signing, a
    captured meaning of "approved", and a hash binding the signature to
    the exact record content) -- previously reviewer_name was an
    unverified free-text string.

    If this review_queue item is linked to a CAPA draft or deviation
    disposition draft (see copilot_agents/ask_flow.py's
    _extract_promotable_draft), approval also promotes that draft into a
    real capas/deviations record, in the same transaction as the
    review_queue status update.
    """
    identity = verify_qp_credentials(username, password)
    if identity is None:
        return False, "Signature failed: invalid username or password.", None

    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT question, draft_answer, agent_name, status,
                   linked_record_type, linked_record_id, structured_payload
            FROM review_queue WHERE id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, f"No review_queue item with id {review_id}", None
        question, draft_answer, agent_name, status, linked_type, linked_id, structured_payload = row
        if status != "pending":
            return False, f"review_queue #{review_id} is already '{status}', not pending.", None

        record_hash = _signed_record_hash(
            {
                "review_id": review_id,
                "question": question,
                "draft_answer": draft_answer,
                "linked_record_type": linked_type,
                "linked_record_id": linked_id,
                "structured_payload": structured_payload,
            }
        )

        cur.execute(
            """
            UPDATE review_queue
            SET status = 'approved', reviewed_at = now(), reviewed_by = %s
            WHERE id = %s
            """,
            (identity.display_name, review_id),
        )

        promoted_record_id = None
        promotion_event_type = None
        if linked_type == "capa" and structured_payload:
            promoted_record_id = _promote_capa(cur, linked_id, structured_payload)
            if promoted_record_id:
                promotion_event_type = "capa_promoted"
        elif linked_type == "deviation" and structured_payload:
            promoted_record_id = _promote_deviation(cur, linked_id, structured_payload)
            if promoted_record_id:
                promotion_event_type = "deviation_disposition_finalized"

        conn.commit()  # one commit: review_queue status update + capas/deviations write

        esign_payload = {
            "review_queue_id": review_id,
            "question": question,
            "approved_answer": draft_answer,
            "agent_name": agent_name,
            "signature_meaning": "approved",
            "signer_username": identity.username,
            "signer_display_name": identity.display_name,
            "signer_role": identity.role,
            "signed_record_hash": record_hash,
            "attestation": (
                f"I, {identity.display_name}, have reviewed the AI-assisted answer above and "
                "approve it as accurate and appropriately grounded in the cited records."
            ),
            "linked_record_type": linked_type,
            "linked_record_id": linked_id,
            "promoted_record_id": promoted_record_id,
        }
        audit_id = append_audit_entry(
            conn,
            event_type=promotion_event_type or "e_signature_approval",
            payload=esign_payload,
            actor=identity.username,
        )

    message = f"review_queue #{review_id} approved and signed by {identity.display_name}."
    if promoted_record_id:
        message += f" Promoted: {promotion_event_type} -> {promoted_record_id}."
    return True, message, audit_id


def reject(review_id: int, username: str, password: str, reason: str) -> tuple[bool, str, int | None]:
    """Returns (success, message, audit_id). Requires re-authentication,
    verified BEFORE any row is touched -- same signature requirement as
    approve() (a rejection is also a formal, signed quality decision, not
    just a UI action). No capas/deviations writes happen here -- a rejected
    draft is never promoted, matching what a real QMS rejection audit trail
    would show (what was proposed and rejected, not a record that never
    came to exist).
    """
    identity = verify_qp_credentials(username, password)
    if identity is None:
        return False, "Signature failed: invalid username or password.", None

    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT question, draft_answer, agent_name, status,
                   linked_record_type, linked_record_id, structured_payload
            FROM review_queue WHERE id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, f"No review_queue item with id {review_id}", None
        question, draft_answer, agent_name, status, linked_type, linked_id, structured_payload = row
        if status != "pending":
            return False, f"review_queue #{review_id} is already '{status}', not pending.", None

        record_hash = _signed_record_hash(
            {
                "review_id": review_id,
                "question": question,
                "draft_answer": draft_answer,
                "linked_record_type": linked_type,
                "linked_record_id": linked_id,
                "structured_payload": structured_payload,
            }
        )

        cur.execute(
            """
            UPDATE review_queue
            SET status = 'rejected', reviewed_at = now(), reviewed_by = %s
            WHERE id = %s
            """,
            (identity.display_name, review_id),
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
                "signature_meaning": "rejected",
                "signer_username": identity.username,
                "signer_display_name": identity.display_name,
                "signer_role": identity.role,
                "signed_record_hash": record_hash,
                "linked_record_type": linked_type,
                "linked_record_id": linked_id,
            },
            actor=identity.username,
        )

    return True, f"review_queue #{review_id} rejected and signed by {identity.display_name}.", audit_id

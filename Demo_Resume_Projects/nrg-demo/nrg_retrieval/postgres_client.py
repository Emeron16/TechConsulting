"""Postgres connection + query helpers -- the S3 (kb_documents source of
truth)/audit-trail analog. Only nrg_retrieval touches Postgres directly;
nrg_chains calls through these functions.
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from nrg_retrieval.audit import append_audit_entry

load_dotenv(Path(__file__).parent.parent / ".env")


def get_pg_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        dbname=os.environ.get("POSTGRES_DB", "nrg"),
        user=os.environ.get("POSTGRES_USER", "nrg"),
        password=os.environ.get("POSTGRES_PASSWORD", "nrg"),
    )


# ---------------------------------------------------------------------------
# kb_documents -- version history / source of truth for what's active
# ---------------------------------------------------------------------------
def get_active_version(cur, doc_id: str) -> tuple | None:
    cur.execute(
        "SELECT id, version, content_hash, file_path FROM kb_documents "
        "WHERE doc_id = %s AND status = 'active'",
        (doc_id,),
    )
    return cur.fetchone()


def insert_kb_document(
    cur,
    *,
    doc_id: str,
    version: int,
    title: str,
    doc_type: str,
    plan_type: str | None,
    file_path: str,
    file_format: str,
    content_hash: str,
    effective_date: str | None,
    uploaded_by: str,
) -> int:
    cur.execute(
        """
        INSERT INTO kb_documents
            (doc_id, version, title, doc_type, plan_type, file_path, file_format,
             content_hash, status, effective_date, uploaded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
        RETURNING id
        """,
        (
            doc_id, version, title, doc_type, plan_type, file_path, file_format,
            content_hash, effective_date, uploaded_by,
        ),
    )
    return cur.fetchone()[0]


def supersede_kb_document(cur, kb_document_id: int) -> None:
    cur.execute("UPDATE kb_documents SET status = 'superseded' WHERE id = %s", (kb_document_id,))


# ---------------------------------------------------------------------------
# ingestion_events -- durable mirror of the RabbitMQ document_processed
# publish/consume lifecycle, queried by the Flow tab without re-draining
# the queue.
# ---------------------------------------------------------------------------
def insert_ingestion_event(cur, *, doc_id: str, version: int, chunk_count: int, payload: dict) -> int:
    import json

    cur.execute(
        """
        INSERT INTO ingestion_events (doc_id, version, chunk_count, payload)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (doc_id, version, chunk_count, json.dumps(payload)),
    )
    return cur.fetchone()[0]


def get_ingestion_event(cur, event_id: int) -> dict | None:
    cur.execute(
        "SELECT id, doc_id, version, status, chunk_count, published_at, consumed_at "
        "FROM ingestion_events WHERE id = %s",
        (event_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "doc_id": row[1],
        "version": row[2],
        "status": row[3],
        "chunk_count": row[4],
        "published_at": row[5],
        "consumed_at": row[6],
    }


def mark_ingestion_event_consumed(cur, doc_id: str, version: int) -> None:
    cur.execute(
        "UPDATE ingestion_events SET status = 'consumed', consumed_at = now() "
        "WHERE doc_id = %s AND version = %s AND status = 'published'",
        (doc_id, version),
    )


def mark_ingestion_event_failed(cur, doc_id: str, version: int) -> None:
    cur.execute(
        "UPDATE ingestion_events SET status = 'failed' "
        "WHERE doc_id = %s AND version = %s AND status = 'published'",
        (doc_id, version),
    )


# ---------------------------------------------------------------------------
# sampled_answers -- statistical sampling log, not a review_queue. Every
# answer is written here unconditionally by nrg_chains/sampling.py and
# already delivered to the user by the time any row exists -- the review_*
# functions below only ever ANNOTATE an existing row after the fact
# (reviewed/reviewed_by/reviewed_at/review_verdict/review_notes), never
# gate or mutate the original question/answer/citations/confidence fields.
# See NRG_Energy_Architecture_Deep_Dive.md §2.1/§3 for why this is
# structurally different from copilot-demo's review_queue approve/reject
# flow (mcp_servers/review_actions.py), which this module deliberately does
# NOT mirror the status-transition shape of.
# ---------------------------------------------------------------------------
def list_recent_sampled_answers(limit: int = 20) -> list[dict]:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, question, answer, doc_type_classified, citations, confidence,
                       created_at, reviewed, reviewed_by, reviewed_at, review_verdict, review_notes
                FROM sampled_answers ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_sampled_answer_row_to_dict(r) for r in rows]


def list_random_sampled_answers(limit: int = 10) -> list[dict]:
    """A genuinely random sample (ORDER BY random()), distinct from
    list_recent_sampled_answers()'s newest-first ordering -- statistical
    sampling per the deep-dive's design is meant to catch issues across the
    whole population of answers, not just the latest ones.
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, question, answer, doc_type_classified, citations, confidence,
                       created_at, reviewed, reviewed_by, reviewed_at, review_verdict, review_notes
                FROM sampled_answers ORDER BY random() LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_sampled_answer_row_to_dict(r) for r in rows]


def get_sampled_answer(answer_id: int) -> dict | None:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, question, answer, doc_type_classified, citations, confidence,
                       created_at, reviewed, reviewed_by, reviewed_at, review_verdict, review_notes
                FROM sampled_answers WHERE id = %s
                """,
                (answer_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _sampled_answer_row_to_dict(row) if row else None


def record_sample_review(answer_id: int, reviewer_name: str, verdict: str, notes: str) -> bool:
    """Annotates an existing sampled_answers row -- returns False if
    answer_id doesn't exist, True on success. Never touches question/
    answer/citations/confidence: only the review_* columns are written.
    Also appends an answer_sampled_reviewed audit_log entry.
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sampled_answers
                SET reviewed = true, reviewed_by = %s, reviewed_at = now(),
                    review_verdict = %s, review_notes = %s
                WHERE id = %s
                """,
                (reviewer_name, verdict, notes, answer_id),
            )
            updated = cur.rowcount > 0
        conn.commit()

        if updated:
            append_audit_entry(
                get_pg_connection(),
                event_type="answer_sampled_reviewed",
                payload={"sampled_answer_id": answer_id, "verdict": verdict, "notes": notes},
                actor=reviewer_name,
            )

        return updated
    finally:
        conn.close()


def _sampled_answer_row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "question": row[1],
        "answer": row[2],
        "doc_type_classified": row[3],
        "citations": row[4],
        "confidence": row[5],
        "created_at": row[6],
        "reviewed": row[7],
        "reviewed_by": row[8],
        "reviewed_at": row[9],
        "review_verdict": row[10],
        "review_notes": row[11],
    }

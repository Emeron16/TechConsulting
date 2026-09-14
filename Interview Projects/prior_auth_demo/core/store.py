"""SQLite persistence: the `requests` table (one row per prior-auth request, tracking status
across the whole lifecycle) and the `audit_log` table (the PDF's "Complete Audit Trail" control
— every AI inference and every human decision, immutable/append-only in this demo).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from core.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT,
    raw_text TEXT,
    extracted_json TEXT,
    completeness_json TEXT,
    policy_analysis_json TEXT,
    routing_json TEXT,
    matched_policy_id TEXT,
    pathway TEXT,
    status TEXT NOT NULL,
    decision TEXT,
    reviewer TEXT,
    reviewer_notes TEXT,
    missing_info_letter TEXT,
    decision_letter TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    component TEXT NOT NULL,
    model TEXT,
    summary TEXT,
    confidence REAL,
    detail_json TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def next_request_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"PA-{today}-"
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE id LIKE ?", (f"{prefix}%",)
        ).fetchone()
        seq = (row["n"] or 0) + 1
    return f"{prefix}{seq:04d}"


def create_request(
    *,
    source: str,
    raw_text: str,
    extracted_json: str,
    completeness_json: str,
    matched_policy_id: str | None,
    status: str,
) -> str:
    request_id = next_request_id()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO requests
               (id, created_at, updated_at, source, raw_text, extracted_json,
                completeness_json, matched_policy_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                now,
                now,
                source,
                raw_text,
                extracted_json,
                completeness_json,
                matched_policy_id,
                status,
            ),
        )
    return request_id


def update_request(request_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [request_id]
    with _connect() as conn:
        conn.execute(f"UPDATE requests SET {columns} WHERE id = ?", values)


def get_request(request_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def list_requests(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM requests"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def log_audit(
    *,
    request_id: str,
    actor: str,
    component: str,
    model: str | None = None,
    summary: str = "",
    confidence: float | None = None,
    detail: dict | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO audit_log
               (request_id, timestamp, actor, component, model, summary, confidence, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                _now(),
                actor,
                component,
                model,
                summary,
                confidence,
                json.dumps(detail) if detail is not None else None,
            ),
        )


def list_audit(request_id: str | None = None) -> list[dict]:
    query = "SELECT * FROM audit_log"
    params: tuple = ()
    if request_id:
        query += " WHERE request_id = ?"
        params = (request_id,)
    query += " ORDER BY timestamp ASC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

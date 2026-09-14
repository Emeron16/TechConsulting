"""Postgres connection + CRUD helpers for warranty_cases,
case_classifications, extracted_entities, and safety_escalations.
airflow_dag_runs helpers are added in Phase 7 once the DAG-trigger flow
exists to populate them.
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def get_pg_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5434")),
        user=os.environ.get("POSTGRES_USER", "volvo"),
        password=os.environ.get("POSTGRES_PASSWORD", "volvo_local_dev"),
        dbname=os.environ.get("POSTGRES_DB", "volvo_warranty"),
        autocommit=True,
    )


def insert_warranty_case(
    conn: psycopg.Connection,
    case_id: str,
    vin: str,
    narrative_text: str,
    submitted_by: str,
    dealer_location: str | None = None,
    mileage: int | None = None,
    vehicle_model: str | None = None,
    model_year: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO warranty_cases
            (case_id, vin, narrative_text, dealer_location, mileage, vehicle_model, model_year, submitted_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (case_id, vin, narrative_text, dealer_location, mileage, vehicle_model, model_year, submitted_by),
    )


def insert_case_classifications(
    conn: psycopg.Connection, case_id: str, classifications: list[tuple[str, float]]
) -> None:
    for category, confidence in classifications:
        conn.execute(
            "INSERT INTO case_classifications (case_id, category, confidence) VALUES (%s, %s, %s)",
            (case_id, category, confidence),
        )


def insert_extracted_entities(conn: psycopg.Connection, case_id: str, entities: list[dict]) -> None:
    import json

    conn.execute(
        "INSERT INTO extracted_entities (case_id, entities) VALUES (%s, %s)",
        (case_id, json.dumps(entities)),
    )


def update_case_status(conn: psycopg.Connection, case_id: str, status: str) -> None:
    conn.execute("UPDATE warranty_cases SET status = %s WHERE case_id = %s", (status, case_id))


def insert_safety_escalation(
    conn: psycopg.Connection,
    case_id: str,
    trigger_reason: str,
    related_case_ids: list[str] | None = None,
) -> int:
    import json

    cursor = conn.execute(
        """
        INSERT INTO safety_escalations (case_id, trigger_reason, related_case_ids)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (case_id, trigger_reason, json.dumps(related_case_ids or [])),
    )
    return cursor.fetchone()[0]


def get_warranty_case(conn: psycopg.Connection, case_id: str) -> dict | None:
    cursor = conn.execute(
        """
        SELECT case_id, vin, narrative_text, dealer_location, mileage,
               vehicle_model, model_year, status, submitted_by, created_at
        FROM warranty_cases WHERE case_id = %s
        """,
        (case_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [
        "case_id", "vin", "narrative_text", "dealer_location", "mileage",
        "vehicle_model", "model_year", "status", "submitted_by", "created_at",
    ]
    return dict(zip(columns, row))


def get_safety_flagged_case_ids(conn: psycopg.Connection, case_ids: list[str]) -> set[str]:
    """Given a list of case_ids, returns the subset that are either
    classified safety_concern OR already have a safety_escalations row --
    used by escalation.py's recurring_pattern trigger to check whether a
    new case's top-K similar cases are themselves already flagged.
    """
    if not case_ids:
        return set()
    cursor = conn.execute(
        """
        SELECT DISTINCT case_id FROM case_classifications
        WHERE category = 'safety_concern' AND case_id = ANY(%s)
        UNION
        SELECT DISTINCT case_id FROM safety_escalations WHERE case_id = ANY(%s)
        """,
        (case_ids, case_ids),
    )
    return {row[0] for row in cursor.fetchall()}


def insert_airflow_dag_run(conn: psycopg.Connection, case_id: str, dag_run_id: str) -> None:
    """The thin join key between a submitted case_id and the Airflow
    dag_run_id processing it -- written by Streamlit's Submit New Case tab
    (Phase 9) immediately after volvo_pipeline.dag_client.trigger_dag_run()
    returns. Does NOT duplicate Airflow's own metadata DB.
    """
    conn.execute(
        "INSERT INTO airflow_dag_runs (case_id, dag_run_id) VALUES (%s, %s)",
        (case_id, dag_run_id),
    )


def update_airflow_dag_run_state(conn: psycopg.Connection, dag_run_id: str, state: str) -> None:
    is_terminal = state in ("success", "failed")
    conn.execute(
        """
        UPDATE airflow_dag_runs
        SET last_polled_state = %s, completed_at = CASE WHEN %s THEN now() ELSE completed_at END
        WHERE dag_run_id = %s
        """,
        (state, is_terminal, dag_run_id),
    )


def get_dag_run_id_for_case(conn: psycopg.Connection, case_id: str) -> str | None:
    cursor = conn.execute(
        "SELECT dag_run_id FROM airflow_dag_runs WHERE case_id = %s ORDER BY id DESC LIMIT 1",
        (case_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def list_escalations(conn: psycopg.Connection, status: str | None = "pending_review", limit: int = 50) -> list[dict]:
    """The Service Operations Manager's review queue -- the Safety
    Escalation Review tab's data source. Defaults to only pending_review
    rows; pass status=None to show all statuses (e.g. an "already reviewed"
    history view).
    """
    if status:
        cursor = conn.execute(
            """
            SELECT id, case_id, trigger_reason, related_case_ids, status,
                   raised_at, reviewed_by, reviewed_at, review_notes
            FROM safety_escalations WHERE status = %s ORDER BY raised_at DESC LIMIT %s
            """,
            (status, limit),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, case_id, trigger_reason, related_case_ids, status,
                   raised_at, reviewed_by, reviewed_at, review_notes
            FROM safety_escalations ORDER BY raised_at DESC LIMIT %s
            """,
            (limit,),
        )
    columns = [
        "id", "case_id", "trigger_reason", "related_case_ids", "status",
        "raised_at", "reviewed_by", "reviewed_at", "review_notes",
    ]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def record_escalation_review(
    conn: psycopg.Connection, escalation_id: int, reviewed_by: str, new_status: str, review_notes: str
) -> None:
    """Annotates an escalation with a Service Operations Manager's
    determination (field_action_recommended or no_action_needed). Also
    resolves the underlying warranty_case's status, since an actioned
    escalation is no longer "escalated" in the same open-ended sense.
    """
    cursor = conn.execute(
        """
        UPDATE safety_escalations
        SET status = %s, reviewed_by = %s, reviewed_at = now(), review_notes = %s
        WHERE id = %s
        RETURNING case_id
        """,
        (new_status, reviewed_by, review_notes, escalation_id),
    )
    row = cursor.fetchone()
    if row:
        conn.execute(
            "UPDATE warranty_cases SET status = 'escalation_resolved' WHERE case_id = %s",
            (row[0],),
        )


def get_escalation(conn: psycopg.Connection, escalation_id: int) -> dict | None:
    cursor = conn.execute(
        """
        SELECT id, case_id, trigger_reason, related_case_ids, status,
               raised_at, reviewed_by, reviewed_at, review_notes
        FROM safety_escalations WHERE id = %s
        """,
        (escalation_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [
        "id", "case_id", "trigger_reason", "related_case_ids", "status",
        "raised_at", "reviewed_by", "reviewed_at", "review_notes",
    ]
    return dict(zip(columns, row))

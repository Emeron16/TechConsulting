"""Hash-chained, insert-only audit log writer -- each row's record_hash
covers its own content plus the previous row's hash, so altering any past
row breaks every hash after it. The audit_log table's UPDATE/DELETE
triggers (db/init/01_schema.sql) enforce insert-only at the DB level; this
module enforces the chain's content integrity at the application level.
"""
import hashlib
import json

GENESIS_HASH = "0" * 64


def compute_record_hash(event_type: str, payload: dict, actor: str, previous_hash: str) -> str:
    canonical = json.dumps(
        {"event_type": event_type, "payload": payload, "actor": actor, "previous_hash": previous_hash},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def append_audit_entry(conn, event_type: str, payload: dict, actor: str) -> int:
    """Appends a new audit_log row, chaining to the current last row's hash.
    Must be called with a connection where no concurrent writer can race
    between reading the last hash and inserting -- fine for this single-
    process demo CLI; a production system would need a serializable
    transaction or advisory lock here.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT record_hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        previous_hash = row[0] if row else GENESIS_HASH

        record_hash = compute_record_hash(event_type, payload, actor, previous_hash)

        cur.execute(
            """
            INSERT INTO audit_log (event_type, payload, actor, record_hash, previous_hash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (event_type, json.dumps(payload), actor, record_hash, previous_hash),
        )
        audit_id = cur.fetchone()[0]
    conn.commit()
    return audit_id


def verify_chain(conn) -> tuple[bool, str | None]:
    """Walks the full audit_log in order and recomputes each hash, comparing
    against the stored record_hash and previous_hash linkage. Returns
    (is_valid, error_message).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, event_type, payload, actor, record_hash, previous_hash "
            "FROM audit_log ORDER BY id ASC"
        )
        rows = cur.fetchall()

    expected_previous = GENESIS_HASH
    for audit_id, event_type, payload, actor, record_hash, previous_hash in rows:
        if previous_hash != expected_previous:
            return False, f"audit_log id={audit_id}: previous_hash link broken"
        recomputed = compute_record_hash(event_type, payload, actor, previous_hash)
        if recomputed != record_hash:
            return False, f"audit_log id={audit_id}: record_hash mismatch (content tampered)"
        expected_previous = record_hash

    return True, None

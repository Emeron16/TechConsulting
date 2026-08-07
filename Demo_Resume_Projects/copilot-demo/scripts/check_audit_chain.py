"""Verifies the audit_log hash chain end-to-end, and (with --demo-tamper)
demonstrates that tampering is detectable even if someone bypasses the
insert-only trigger (e.g. a superuser running ALTER TABLE ... DISABLE
TRIGGER, which normal application roles cannot do, but a DBA could).

Usage:
  python scripts/check_audit_chain.py                # verify only
  python scripts/check_audit_chain.py --demo-tamper   # tamper then verify, then restore
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mcp_servers.audit import verify_chain
from mcp_servers.common import get_pg_connection


def run_verification(label: str) -> None:
    conn = get_pg_connection()
    valid, err = verify_chain(conn)
    conn.close()
    status = "VALID" if valid else "TAMPERED"
    print(f"[{label}] Chain status: {status}" + (f" -- {err}" if err else ""))


def demo_tamper() -> None:
    conn = get_pg_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id, payload FROM audit_log ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            print("No audit_log rows to tamper with -- run scripts/review.py approve first.")
            conn.close()
            return
        target_id = row[0]

        print(f"Bypassing insert-only trigger to tamper with audit_log id={target_id}...")
        cur.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update")
        cur.execute(
            "UPDATE audit_log SET payload = payload || '{\"tampered\": true}'::jsonb WHERE id = %s",
            (target_id,),
        )
        cur.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update")
        conn.commit()
    conn.close()

    run_verification("AFTER TAMPER")

    conn = get_pg_connection()
    with conn.cursor() as cur:
        print(f"\nRestoring audit_log id={target_id} to its original content...")
        cur.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update")
        cur.execute(
            "UPDATE audit_log SET payload = payload - 'tampered' WHERE id = %s",
            (target_id,),
        )
        cur.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update")
        conn.commit()
    conn.close()

    run_verification("AFTER RESTORE")


if __name__ == "__main__":
    run_verification("BEFORE")
    if "--demo-tamper" in sys.argv:
        print()
        demo_tamper()

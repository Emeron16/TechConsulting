"""CLI review/approve tool -- lists pending items in the review_queue and
lets a QP approve or reject one, signing with a re-entered password (checked
against db/init/04_qp_users.sql's qp_users table) and writing an entry to
the hash-chained audit log. Matches the original architecture's
Review & Approval Queue -> Electronic Signature -> Audit flow, with a real
password re-authentication step per 21 CFR Part 11's requirement to
re-authenticate at the moment of signing (see mcp_servers/auth.py).

Usage:
  python scripts/review.py list
  python scripts/review.py approve <id> <username>
  python scripts/review.py reject <id> <username> "<reason>"

Password is prompted interactively (not passed as an argument, so it never
lands in shell history or process listings).
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mcp_servers.review_actions import approve, list_pending, reject


def cmd_list() -> None:
    rows = list_pending()
    if not rows:
        print("No pending items in the review queue.")
        return

    print(f"{'ID':<5} {'Agent':<28} {'Created':<20} {'Linked record':<22} Question")
    print("-" * 122)
    for row in rows:
        linked = f"{row.get('linked_record_type') or '-'}:{row.get('linked_record_id') or '-'}"
        print(
            f"{row['id']:<5} {row['agent_name']:<28} {str(row['created_at'])[:19]:<20} {linked:<22} "
            f"{row['question'][:50]}"
        )


def cmd_approve(review_id: int, username: str) -> None:
    password = getpass.getpass(f"Password for {username} (to sign): ")
    success, message, audit_id = approve(review_id, username, password)
    print(message)
    if success:
        print(f"E-signature + audit_log entry recorded (audit_log id={audit_id}).")


def cmd_reject(review_id: int, username: str, reason: str) -> None:
    password = getpass.getpass(f"Password for {username} (to sign): ")
    success, message, audit_id = reject(review_id, username, password, reason)
    print(message)
    if success:
        print(f"Audit_log entry recorded (audit_log id={audit_id}).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "list":
        cmd_list()
    elif command == "approve" and len(sys.argv) == 4:
        cmd_approve(int(sys.argv[2]), sys.argv[3])
    elif command == "reject" and len(sys.argv) == 5:
        cmd_reject(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(1)

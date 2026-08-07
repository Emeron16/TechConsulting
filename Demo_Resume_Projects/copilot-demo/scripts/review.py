"""CLI review/approve tool -- lists pending items in the review_queue and
lets a user approve one, writing a mock e-signature record and an entry to
the hash-chained audit log. Matches the original architecture's
Review & Approval Queue -> Electronic Signature -> Audit flow (with a
simulated e-signature, not real 21 CFR Part 11 compliance).

Usage:
  python scripts/review.py list
  python scripts/review.py approve <id> "<reviewer name>"
  python scripts/review.py reject <id> "<reviewer name>" "<reason>"
"""
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

    print(f"{'ID':<5} {'Agent':<28} {'Created':<20} Question")
    print("-" * 100)
    for row in rows:
        print(
            f"{row['id']:<5} {row['agent_name']:<28} {str(row['created_at'])[:19]:<20} "
            f"{row['question'][:50]}"
        )


def cmd_approve(review_id: int, reviewer_name: str) -> None:
    success, message, audit_id = approve(review_id, reviewer_name)
    print(message)
    if success:
        print(f"E-signature + audit_log entry recorded (audit_log id={audit_id}).")


def cmd_reject(review_id: int, reviewer_name: str, reason: str) -> None:
    success, message, audit_id = reject(review_id, reviewer_name, reason)
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

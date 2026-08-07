"""CLI compliance sampling tool -- lists sampled answers and lets a
reviewer mark one accurate/inaccurate with notes. Unlike copilot-demo's
scripts/review.py (approve/reject a *pending* item before it becomes an
official record), every answer here was ALREADY delivered to the user
before this script ever runs -- marking a review only annotates the
sampled_answers row, it never gates, blocks, or retroactively changes what
the user saw. Matches NRG_Energy_Architecture_Deep_Dive.md's periodic
statistical-sampling design (§2.1, §3), not a mandatory sign-off queue.

Usage:
  python scripts/review.py list [--random] [--limit N]
  python scripts/review.py mark <id> "<reviewer name>" <accurate|inaccurate> "<notes>"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from nrg_retrieval.postgres_client import (
    get_sampled_answer,
    list_random_sampled_answers,
    list_recent_sampled_answers,
    record_sample_review,
)


def cmd_list(random: bool, limit: int) -> None:
    rows = list_random_sampled_answers(limit) if random else list_recent_sampled_answers(limit)
    if not rows:
        print("No sampled answers yet.")
        return

    print(f"{'ID':<5} {'Reviewed':<10} {'Verdict':<12} {'Created':<20} Question")
    print("-" * 100)
    for row in rows:
        verdict = row["review_verdict"] or "-"
        print(
            f"{row['id']:<5} {str(row['reviewed']):<10} {verdict:<12} "
            f"{str(row['created_at'])[:19]:<20} {row['question'][:45]}"
        )


def cmd_mark(answer_id: int, reviewer_name: str, verdict: str, notes: str) -> None:
    if verdict not in ("accurate", "inaccurate"):
        print(f"Verdict must be 'accurate' or 'inaccurate', got: {verdict!r}")
        sys.exit(1)

    existing = get_sampled_answer(answer_id)
    if existing is None:
        print(f"No sampled_answers row with id {answer_id}")
        sys.exit(1)

    success = record_sample_review(answer_id, reviewer_name, verdict, notes)
    if success:
        print(f"sampled_answers #{answer_id} marked '{verdict}' by {reviewer_name}.")
        print("(This is an annotation only -- the original answer already delivered to the user is unchanged.)")
    else:
        print(f"Failed to record review for #{answer_id}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "list":
        random = "--random" in sys.argv
        limit = 20
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        cmd_list(random, limit)
    elif command == "mark" and len(sys.argv) == 6:
        cmd_mark(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        print(__doc__)
        sys.exit(1)

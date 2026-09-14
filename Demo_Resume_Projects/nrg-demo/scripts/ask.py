"""CLI entry point: ask a question, watch it flow through
classification -> hybrid retrieval -> grounded generation -> unconditional
sampling log.

Usage: python scripts/ask.py "Does the FixedSaver 24 plan include a winter usage credit?"
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from nrg_chains.chain import run_question


async def main(question: str) -> None:
    print(f"Question: {question}\n")
    print("Running classification -> hybrid retrieval -> generation...\n")

    result = await run_question(question)

    print("=" * 70)
    print("FINAL ANSWER")
    print("=" * 70)
    print(result.final_answer)
    print()
    print(f"Confidence: {result.structured_answer.confidence}")
    print(f"Citations: {result.structured_answer.citations}")
    print(f"Classified doc_type: {result.structured_answer.doc_type_classified}")
    print()
    print("=" * 70)
    print("CHAIN TRACE")
    print("=" * 70)
    for step in result.trace_steps:
        print(f"  [{step.step_type}] {step.detail}")

    print(f"\n[Logged unconditionally to sampled_answers, id={result.sampled_answer_id} -- "
          f"answer already delivered above, this is a background QA record, not a gate.]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

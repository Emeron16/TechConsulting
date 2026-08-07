"""CLI entry point: ask a question, watch it flow through
Supervisor -> specialist agent -> MCP tool calls -> grounded answer.

Usage: python scripts/ask.py "Does deviation DEV-2201 meet SOP-114 escalation criteria?"
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from copilot_agents.ask_flow import run_question
from copilot_agents.tracing_setup import enable_langsmith_tracing


async def main(question: str) -> None:
    tracing_enabled = enable_langsmith_tracing()
    print(f"[LangSmith tracing: {'enabled' if tracing_enabled else 'disabled (no API key)'}]\n")

    print(f"Question: {question}\n")
    print("Running Supervisor -> specialist agent -> MCP tools...\n")

    result = await run_question(question)

    print("=" * 70)
    print("FINAL ANSWER")
    print("=" * 70)
    print(result.final_answer)
    print()
    print("=" * 70)
    print("AGENT PATH")
    print("=" * 70)
    for step in result.trace_steps:
        if step.step_type == "handoff":
            print(f"  [{step.agent_name}] handoff -> {step.target_agent}")
        elif step.step_type == "tool_call":
            print(f"  [{step.agent_name}] tool_call: {step.tool_name}({step.arguments})")
        elif step.step_type == "message":
            print(f"  [{step.agent_name}] message")

    if result.published_for_review:
        print(
            f"\n[{result.responding_agent_name} output is pending human review -- "
            f"review_queue #{result.review_queue_id}. Run "
            f"'python scripts/review.py list' then 'approve'/'reject' it.]"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

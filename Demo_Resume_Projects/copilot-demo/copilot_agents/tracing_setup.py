"""Wires the OpenAI Agents SDK's built-in tracing into LangSmith, so every
Supervisor -> specialist -> MCP tool call -> LLM generation run produces a
full trace in the LangSmith dashboard.
"""
import os

from agents.tracing import add_trace_processor
from langsmith.wrappers import OpenAIAgentsTracingProcessor


def enable_langsmith_tracing() -> bool:
    """Returns True if tracing was enabled, False if LANGSMITH_API_KEY is unset."""
    api_key = os.environ.get("LANGSMITH_API_KEY", "")
    if not api_key or api_key.startswith("ls__..."):
        return False
    add_trace_processor(OpenAIAgentsTracingProcessor())
    return True

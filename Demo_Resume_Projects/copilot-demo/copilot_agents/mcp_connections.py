"""MCP server connections for the specialist agents.

Each helper spins up an MCPServerStdio pointed at one of the mcp_servers/*.py
processes -- this is the governance boundary from the original architecture:
an agent only gets the MCP connections it's explicitly given, never raw
DB/Chroma access.
"""
import sys
from pathlib import Path

from agents.mcp import MCPServerStdio

ROOT = Path(__file__).parent.parent

# MCPServerStdio's default client_session_timeout_seconds is 5 -- fine for
# the old pure-vector search_documents(), but the hybrid search pipeline
# (mcp_servers/hybrid_search.py: BM25 + vector + cross-encoder rerank) can
# comfortably exceed that, especially on a cold process where the
# cross-encoder model has to load (and potentially download from
# HuggingFace) before the first search completes. A 5s timeout there
# produces a silent tool-call failure ("Timed out while waiting for
# response to ClientRequest"), which the agent retries, burning through
# Runner.run()'s turn budget until MaxTurnsExceeded -- not a hang, just a
# genuinely slower tool call than the SDK's conservative default assumes.
TOOL_TIMEOUT_SECONDS = 60


def quality_docs_server() -> MCPServerStdio:
    return MCPServerStdio(
        name="quality-documents",
        params={
            "command": sys.executable,
            "args": ["-m", "mcp_servers.quality_docs_server"],
            "cwd": str(ROOT),
        },
        client_session_timeout_seconds=TOOL_TIMEOUT_SECONDS,
    )


def batch_records_server() -> MCPServerStdio:
    return MCPServerStdio(
        name="batch-records",
        params={
            "command": sys.executable,
            "args": ["-m", "mcp_servers.batch_records_server"],
            "cwd": str(ROOT),
        },
        client_session_timeout_seconds=TOOL_TIMEOUT_SECONDS,
    )


def sop_repository_server() -> MCPServerStdio:
    return MCPServerStdio(
        name="sop-repository",
        params={
            "command": sys.executable,
            "args": ["-m", "mcp_servers.sop_repository_server"],
            "cwd": str(ROOT),
        },
        client_session_timeout_seconds=TOOL_TIMEOUT_SECONDS,
    )


def capa_server() -> MCPServerStdio:
    return MCPServerStdio(
        name="capa-enterprise",
        params={
            "command": sys.executable,
            "args": ["-m", "mcp_servers.capa_server"],
            "cwd": str(ROOT),
        },
        client_session_timeout_seconds=TOOL_TIMEOUT_SECONDS,
    )

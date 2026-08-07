"""Standalone MCP server smoke test: starts a server as a subprocess over
stdio, lists its tools, and calls one to confirm end-to-end wiring.

Usage: python scripts/test_mcp_server.py <server_module> <tool_name> <json_args>
Example: python scripts/test_mcp_server.py mcp_servers.sop_repository_server search_sops '{"query": "escalation criteria"}'
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).parent.parent


async def main(server_module: str, tool_name: str, args_json: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", server_module],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"Tools exposed by {server_module}:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description.strip().splitlines()[0]}")

            args = json.loads(args_json)
            print(f"\nCalling {tool_name}({args})...")
            result = await session.call_tool(tool_name, arguments=args)
            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))

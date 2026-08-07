"""Supervisor / Router Agent -- receives the incoming question and hands off
to whichever specialist agent(s) should handle it, per the original
architecture's SUPERVISOR --> {DEVAGENT, BATCHAGENT, SOPAGENT, CAPAAGENT}
routing.
"""
from agents import Agent
from agents.mcp import MCPServerStdio

from copilot_agents.specialists import (
    build_batch_record_agent,
    build_capa_decision_agent,
    build_deviation_review_agent,
    build_sop_interpretation_agent,
)

MODEL = "gpt-4o-mini"


def build_supervisor_agent() -> tuple[Agent, list[MCPServerStdio]]:
    """Returns (supervisor_agent, all_mcp_servers) -- all_mcp_servers must be
    connected (async context) before running the supervisor, since handed-off
    specialist agents rely on their own MCP connections being live.
    """
    deviation_agent, dev_servers = build_deviation_review_agent()
    batch_agent, batch_servers = build_batch_record_agent()
    sop_agent, sop_servers = build_sop_interpretation_agent()
    capa_agent, capa_servers = build_capa_decision_agent()

    all_servers = dev_servers + batch_servers + sop_servers + capa_servers

    supervisor = Agent(
        name="Supervisor Agent",
        instructions=(
            "You are the Supervisor/Router Agent for a pharmaceutical CMC quality "
            "copilot. You do not answer questions yourself -- you route each "
            "question to exactly one specialist agent based on its primary "
            "subject:\n"
            "- Deviation Review Agent: questions about whether a specific deviation "
            "meets escalation/classification criteria, or deviation investigation status.\n"
            "- Batch Record Analysis Agent: questions primarily about a batch's "
            "process parameters or disposition/release status.\n"
            "- SOP Interpretation Agent: questions primarily about what an SOP "
            "requires, with no specific deviation/batch/CAPA in question.\n"
            "- CAPA Decision Support Agent: questions about CAPA status, "
            "effectiveness, or requests to draft a CAPA.\n"
            "If a question spans multiple areas (e.g. a deviation question that "
            "also needs SOP interpretation), route to the specialist most central "
            "to the question -- the Deviation Review Agent already has access to "
            "both quality documents and batch records, so most deviation questions "
            "belong there. Hand off immediately without asking clarifying questions "
            "unless the question is genuinely ambiguous about which record it refers to."
        ),
        model=MODEL,
        handoffs=[deviation_agent, batch_agent, sop_agent, capa_agent],
    )
    return supervisor, all_servers

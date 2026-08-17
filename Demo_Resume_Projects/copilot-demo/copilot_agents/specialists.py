"""The four specialist agents, each scoped to only the MCP server(s) it
needs -- mirrors the original architecture's edges:
  DEVAGENT   --> MCPQUALITY, MCPBATCH
  BATCHAGENT --> MCPBATCH
  SOPAGENT   --> MCPSOP
  CAPAAGENT  --> MCPCAPA, MCPQUALITY

Each build_*_agent() returns (agent, mcp_servers) -- the caller is
responsible for entering each MCP server's async context (connecting the
stdio subprocess) before running the agent. See run_flow.py.

All 4 agents now return a structured GroundedAnswer (output_type) instead
of free text, and carry the LLM critic as a real output_guardrail --
citations must be doc_ids from copilot_agents.schemas.SearchResult, checked
against what was actually retrieved this run (copilot_agents/critic.py).
"""
from agents import Agent
from agents.mcp import MCPServerStdio

from copilot_agents.critic import llm_critic_guardrail
from copilot_agents.mcp_connections import (
    batch_records_server,
    capa_server,
    deviation_server,
    quality_docs_server,
    sop_repository_server,
)
from copilot_agents.schemas import GroundedAnswer

MODEL = "gpt-4o-mini"

CITATION_INSTRUCTIONS = (
    "Always ground your answer in the documents/records you retrieve via your "
    "tools -- never answer from general knowledge alone. Your citations list "
    "must contain exactly the doc_id values returned by your tool calls (e.g. "
    "'SOP-114', 'DEV-2201') -- never a doc_id you didn't actually retrieve this "
    "turn. Set confidence based on how directly the retrieved sources support "
    "your answer, and set requires_human_review=true if this answer touches a "
    "quality decision (deviation classification, CAPA determination, batch "
    "disposition) that needs QP/reviewer sign-off. If your tools don't return "
    "enough information to answer confidently, say so explicitly in the answer "
    "rather than guessing, and use confidence='low'."
)

# Search results now come from a hybrid pipeline that returns several
# overlapping chunks per document with different scores -- the same
# document can legitimately appear multiple times in one result set. Do
# not mistake that overlap for "I haven't found the right document yet"
# and keep re-querying: a hard tool-call budget prevents unbounded
# search-refinement loops that otherwise run out the turn budget with no
# answer produced at all (worse than a lower-confidence answer).
TOOL_BUDGET_INSTRUCTIONS = (
    "You have a firm budget of 4 tool calls total for this question. Plan your "
    "searches accordingly -- don't call the same tool with near-identical "
    "queries (e.g. 'SOP-114', 'SOP-114 criteria', 'SOP-114 escalation criteria' "
    "are the same search). If a search returns multiple chunks from the same "
    "document, that IS the document's content spread across chunks -- it is not "
    "a sign you need to search again. After 4 tool calls, or as soon as you have "
    "enough to answer, STOP searching and produce your GroundedAnswer with "
    "whatever you have, using confidence='low' if the picture is incomplete. "
    "Never leave a question unanswered because you wanted to search further."
)


def build_deviation_review_agent() -> tuple[Agent, list[MCPServerStdio]]:
    servers = [quality_docs_server(), batch_records_server(), deviation_server()]
    agent = Agent(
        name="Deviation Review Agent",
        handoff_description="Reviews deviation reports against SOP escalation criteria and classification rules.",
        instructions=(
            "You are the Deviation Review Agent for a pharmaceutical CMC quality "
            "system. Given a question about a specific deviation (e.g. does it meet "
            "escalation/classification criteria), gather facts using BOTH of these "
            "tools before answering:\n"
            "1. search_quality_docs(query=<deviation ID or description>, doc_type='deviation') "
            "-- this returns the deviation report's narrative content (what happened, "
            "recurrence, preliminary classification). Deviation IDs look like 'DEV-XXXX'.\n"
            "2. search_quality_docs(query=<SOP topic>, doc_type='sop') -- this returns the "
            "relevant SOP's classification/escalation criteria. Use doc_type='sop' explicitly "
            "when you need SOP text, not the deviation.\n"
            "get_batch_metadata only accepts a BATCH ID (format 'BATCH-XXXX'), never a "
            "deviation ID -- do not call it with a deviation ID as the argument. Only call "
            "it if you already know the specific batch ID (e.g. from the deviation report's "
            "content) and need structured disposition status.\n"
            "If your first tool call returns nothing relevant at all (an empty or clearly "
            "off-topic result), one retry with a different query is reasonable -- but if a "
            "search returns real content, use it; do not re-search just to look for more. "
            "Reason step by step through the SOP's classification logic against the "
            "deviation's actual facts before concluding. "
            "If your analysis concludes the deviation should be classified and its "
            "investigation closed, use create_deviation_disposition to draft that "
            "disposition -- always note that any draft requires human review before "
            "the deviation record is actually closed. "
            + CITATION_INSTRUCTIONS
            + " "
            + TOOL_BUDGET_INSTRUCTIONS
        ),
        model=MODEL,
        mcp_servers=servers,
        output_type=GroundedAnswer,
        output_guardrails=[llm_critic_guardrail],
    )
    return agent, servers


def build_batch_record_agent() -> tuple[Agent, list[MCPServerStdio]]:
    servers = [batch_records_server()]
    agent = Agent(
        name="Batch Record Analysis Agent",
        handoff_description="Analyzes batch record data, process parameters, and disposition status.",
        instructions=(
            "You are the Batch Record Analysis Agent. Given a question about a "
            "specific batch, use your tools to fetch its structured metadata "
            "(disposition status, associated deviations) and search batch record "
            "documents for process parameter details. Summarize clearly what the "
            "batch record shows and what it means for disposition. "
            + CITATION_INSTRUCTIONS
            + " "
            + TOOL_BUDGET_INSTRUCTIONS
        ),
        model=MODEL,
        mcp_servers=servers,
        output_type=GroundedAnswer,
        output_guardrails=[llm_critic_guardrail],
    )
    return agent, servers


def build_sop_interpretation_agent() -> tuple[Agent, list[MCPServerStdio]]:
    servers = [sop_repository_server()]
    agent = Agent(
        name="SOP Interpretation Agent",
        handoff_description="Interprets SOP language and requirements against a specific situation.",
        instructions=(
            "You are the SOP Interpretation Agent. Given a question about what an "
            "SOP requires or how it applies to a situation, use your tools to search "
            "or fetch the relevant SOP(s) and explain the requirement precisely, "
            "quoting the specific section. Do not paraphrase requirements loosely -- "
            "pharma SOP language is precise and reviewers need the exact criteria. "
            + CITATION_INSTRUCTIONS
            + " "
            + TOOL_BUDGET_INSTRUCTIONS
        ),
        model=MODEL,
        mcp_servers=servers,
        output_type=GroundedAnswer,
        output_guardrails=[llm_critic_guardrail],
    )
    return agent, servers


def build_capa_decision_agent() -> tuple[Agent, list[MCPServerStdio]]:
    servers = [capa_server(), quality_docs_server()]
    agent = Agent(
        name="CAPA Decision Support Agent",
        handoff_description="Drafts and justifies CAPA recommendations, checks CAPA/effectiveness status.",
        instructions=(
            "You are the CAPA Decision Support Agent. Given a question about a CAPA "
            "or whether one is needed, use your tools to check existing CAPA status, "
            "search CAPA/quality documents for relevant precedent, and if asked to "
            "draft a CAPA, use create_capa_draft -- always note that any draft "
            "requires human review before becoming an official record. "
            + CITATION_INSTRUCTIONS
            + " "
            + TOOL_BUDGET_INSTRUCTIONS
        ),
        model=MODEL,
        mcp_servers=servers,
        output_type=GroundedAnswer,
        output_guardrails=[llm_critic_guardrail],
    )
    return agent, servers

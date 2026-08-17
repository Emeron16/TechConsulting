"""Shared "ask a question" orchestration flow: connects MCP servers, runs
the Supervisor, and publishes to the needs-review queue if the responding
agent is one that requires human review. Used by both scripts/ask.py (CLI)
and the Streamlit UI so there's exactly one orchestration path.

Also captures the full per-step trace (handoffs, tool calls with arguments/
outputs, final message, critic review outcomes) so the UI can render an
accurate pipeline visualization without re-deriving anything -- see
copilot_agents/flow_diagram.py.

Retry loop: specialist agents now return a structured GroundedAnswer
(output_type) and carry the LLM critic as a real output_guardrail
(copilot_agents/critic.py). A guardrail trip raises
OutputGuardrailTripwireTriggered rather than returning a value, so the
retry here works by catching that exception, appending the critic's
feedback to the input, and re-running -- up to MAX_ATTEMPTS total. If every
attempt fails, the last draft answer is still returned (never silently
dropped), but forced to requires_human_review=True since it never passed
its own quality bar -- the existing human review queue is the final
backstop, not a replacement for the critic.
"""
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from agents import Runner
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError, OutputGuardrailTripwireTriggered

from copilot_agents.critic import RecordingHooks, RunContext
from copilot_agents.review_queue import REVIEW_TRIGGERING_AGENTS, publish_needs_review
from copilot_agents.schemas import CriticResult, GroundedAnswer
from copilot_agents.supervisor import build_supervisor_agent

MAX_ATTEMPTS = 3  # first attempt + up to 2 retries

# The 4 specialist agents the Supervisor can hand off to (copilot_agents/
# specialists.py) -- shared with flow_diagram.py (for the "not selected"
# row) and used here to validate an agent_name before synthesizing a
# handoff step in _build_trace_steps_from_context.
ALL_SPECIALIST_AGENTS = [
    "Deviation Review Agent",
    "Batch Record Analysis Agent",
    "SOP Interpretation Agent",
    "CAPA Decision Support Agent",
]

# Tool name -> owning MCP server display name, derived from each specialist
# agent's scoped mcp_servers list in copilot_agents/specialists.py. Used only
# for trace/diagram labeling, kept here (not in specialists.py) so the agent
# definitions stay focused on behavior, not presentation.
TOOL_TO_MCP_SERVER = {
    "search_quality_docs": "MCP: Quality Documents",
    "get_batch_metadata": "MCP: Batch Records",
    "search_batch_records": "MCP: Batch Records",
    "search_sops": "MCP: SOP Repository",
    "get_sop_by_id": "MCP: SOP Repository",
    "get_capa_status": "MCP: CAPA / Enterprise",
    "search_capa_records": "MCP: CAPA / Enterprise",
    "create_capa_draft": "MCP: CAPA / Enterprise",
    "create_deviation_disposition": "MCP: Deviation Management",
}

# Tool name -> linked_record_type, for tools whose structured output is a
# draft record (status="draft_pending_review") that review_actions.approve()
# can promote into a real capas/deviations row on QP approval -- see
# _extract_promotable_draft below and mcp_servers/review_actions.py.
PROMOTABLE_TOOLS = {
    "create_capa_draft": "capa",
    "create_deviation_disposition": "deviation",
}

# Tool name -> what retrieval backend/strategy it actually uses. Search
# tools go through the hybrid pipeline (mcp_servers/hybrid_search.py: BM25
# + dense vector search, fused via RRF, then cross-encoder reranked); exact-
# ID lookup tools hit Postgres or a Chroma metadata filter with no ranking
# at all. Used only for diagram labeling.
TOOL_RETRIEVAL_INFO = {
    "search_quality_docs": {
        "backend": "ChromaDB + BM25 (hybrid)",
        "strategy": "BM25 keyword search + dense vector search, fused via Reciprocal Rank Fusion, reranked with a cross-encoder",
        "embedding_model": "text-embedding-3-small",
        "ranking": "Cross-encoder rerank score (cross-encoder/ms-marco-MiniLM-L-6-v2) over RRF-fused candidates",
        "filter": "Metadata pre-filter: status=approved, optional doc_type",
    },
    "search_sops": {
        "backend": "ChromaDB + BM25 (hybrid)",
        "strategy": "BM25 keyword search + dense vector search, fused via Reciprocal Rank Fusion, reranked with a cross-encoder",
        "embedding_model": "text-embedding-3-small",
        "ranking": "Cross-encoder rerank score (cross-encoder/ms-marco-MiniLM-L-6-v2) over RRF-fused candidates",
        "filter": "Metadata pre-filter: status=approved, doc_type=sop",
    },
    "search_batch_records": {
        "backend": "ChromaDB + BM25 (hybrid)",
        "strategy": "BM25 keyword search + dense vector search, fused via Reciprocal Rank Fusion, reranked with a cross-encoder",
        "embedding_model": "text-embedding-3-small",
        "ranking": "Cross-encoder rerank score (cross-encoder/ms-marco-MiniLM-L-6-v2) over RRF-fused candidates",
        "filter": "Metadata pre-filter: status=approved, doc_type=batch_record",
    },
    "search_capa_records": {
        "backend": "ChromaDB + BM25 (hybrid)",
        "strategy": "BM25 keyword search + dense vector search, fused via Reciprocal Rank Fusion, reranked with a cross-encoder",
        "embedding_model": "text-embedding-3-small",
        "ranking": "Cross-encoder rerank score (cross-encoder/ms-marco-MiniLM-L-6-v2) over RRF-fused candidates",
        "filter": "Metadata pre-filter: status=approved, doc_type=capa",
    },
    "get_batch_metadata": {
        "backend": "PostgreSQL",
        "strategy": "Exact-match SQL lookup by batch_id (no retrieval/ranking)",
    },
    "get_sop_by_id": {
        "backend": "ChromaDB (vector store)",
        "strategy": "Exact-match metadata filter by doc_id (no similarity ranking)",
    },
    "get_capa_status": {
        "backend": "PostgreSQL",
        "strategy": "Exact-match SQL lookup by capa_id (no retrieval/ranking)",
    },
    "create_capa_draft": {
        "backend": "PostgreSQL",
        "strategy": "Write operation (draft insert) -- not a retrieval call",
    },
    "create_deviation_disposition": {
        "backend": "PostgreSQL",
        "strategy": "Write operation (draft update -- disposes an existing deviation, not a retrieval call)",
    },
}


@dataclass
class TraceStep:
    step_type: str  # "handoff" | "tool_call" | "message" | "critic_check"
    agent_name: str
    tool_name: str | None = None
    mcp_server: str | None = None
    arguments: dict | None = None
    output: str | None = None
    target_agent: str | None = None
    message_text: str | None = None
    retrieval_info: dict | None = None  # backend/strategy/embedding_model/ranking/filter, see TOOL_RETRIEVAL_INFO
    cache_hit: bool | None = None
    result_payloads: list[dict] = field(default_factory=list)  # parsed SearchResult dicts, for the score table
    critic_result: CriticResult | None = None  # for step_type == "critic_check"
    attempt: int = 1  # which retry attempt this step belongs to
    batch: int | None = None  # tool_call steps only: index shared by calls the model emitted in
    # the same turn -- the SDK executes same-batch calls concurrently (see
    # RunContext.call_id_to_batch in copilot_agents/critic.py), so the Flow tab renders
    # same-batch steps side by side instead of one flat sequential chain.


@dataclass
class AskResult:
    final_answer: str
    trace_steps: list[TraceStep] = field(default_factory=list)
    responding_agent_name: str | None = None
    published_for_review: bool = False
    review_queue_id: int | None = None
    structured_answer: GroundedAnswer | None = None
    attempt_count: int = 1


def _extract_text_output(raw_output) -> str:
    """ToolCallOutputItem.raw_item['output'] is either a plain string or a
    list of {"type": "input_text", "text": ...} content blocks, depending on
    the MCP transport -- normalize to a single string for display.
    """
    if isinstance(raw_output, str):
        return raw_output
    if isinstance(raw_output, list):
        parts = [block.get("text", "") for block in raw_output if isinstance(block, dict)]
        return "\n".join(p for p in parts if p)
    return str(raw_output)


def _parse_tool_result_payloads(raw_output) -> list[dict]:
    """List-returning tools (search_*) produce one {"type": "input_text",
    "text": "<json>"} block per SearchResult -- _extract_text_output joins
    them newline-separated, which isn't a single valid JSON document. This
    parses each block's text independently instead, returning one dict per
    successfully-parsed block (works for both single-object and multi-block
    list-shaped tool outputs).
    """
    blocks = raw_output if isinstance(raw_output, list) else [raw_output]
    payloads = []
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else None
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
        elif isinstance(parsed, list):
            payloads.extend(p for p in parsed if isinstance(p, dict))
    return payloads


def _extract_cache_hit(payloads: list[dict]) -> bool | None:
    """Returns True/False if any parsed payload carries a cache_hit field
    (only SearchResult does), else None (not applicable for this tool).
    """
    for p in payloads:
        if "cache_hit" in p:
            return bool(p["cache_hit"])
    return None


def _extract_promotable_draft(steps: list["TraceStep"]) -> tuple[str, str, dict] | None:
    """Scans trace_steps (already-built, in call order) for the LAST
    tool_call step whose tool_name is create_capa_draft or
    create_deviation_disposition and has a successfully-parsed
    result_payloads entry. "Last" (not "first") matters because an agent
    could in principle redraft after critic feedback on a retry attempt --
    the final draft it settled on before producing its GroundedAnswer is
    the one that should be promotable, not an earlier abandoned attempt.

    Returns (linked_record_type, linked_record_id, structured_payload) or
    None if no such call happened this run -- see mcp_servers/review_actions.py's
    approve(), which promotes this payload into a real capas/deviations row
    on QP approval.

    linked_record_id means different things per tool, matching what each
    promotion function in review_actions.py actually needs as its lookup
    key: for a CapaDraft it's related_deviation_id (the deviation the new
    CAPA will be FK'd to and whose count() drives the synthesized capa_id
    -- NOT draft_capa_id, which is only the draft's own placeholder
    identifier and was never a valid deviations.deviation_id to begin
    with). For a DeviationDispositionDraft it's draft_deviation_id (the
    existing deviation row _promote_deviation updates in place).
    """
    for step in reversed(steps):
        if step.step_type != "tool_call" or step.tool_name not in PROMOTABLE_TOOLS:
            continue
        if not step.result_payloads:
            continue
        payload = step.result_payloads[0]
        if payload.get("status") != "draft_pending_review":
            continue
        record_type = PROMOTABLE_TOOLS[step.tool_name]
        if step.tool_name == "create_capa_draft":
            record_id = payload.get("related_deviation_id")
        else:
            record_id = payload.get("draft_deviation_id")
        if not record_id:
            continue
        return record_type, record_id, payload
    return None


def _build_trace_steps(new_items, attempt: int, call_id_to_batch: dict[str, int] | None = None) -> list[TraceStep]:
    steps: list[TraceStep] = []
    call_id_to_batch = call_id_to_batch or {}
    # tool call_id -> index into steps, so the matching ToolCallOutputItem
    # can attach its output to the same step instead of creating a new one.
    call_id_to_step_index: dict[str, int] = {}

    for item in new_items:
        item_type = type(item).__name__
        agent_name = getattr(getattr(item, "agent", None), "name", "?")
        raw = item.raw_item

        if item_type == "HandoffCallItem":
            continue  # paired HandoffOutputItem carries the useful target info

        if item_type == "HandoffOutputItem":
            target = getattr(getattr(item, "target_agent", None), "name", None)
            steps.append(
                TraceStep(step_type="handoff", agent_name=agent_name, target_agent=target, attempt=attempt)
            )

        elif item_type == "ToolCallItem":
            tool_name = getattr(raw, "name", None)
            call_id = getattr(raw, "call_id", None)
            try:
                arguments = json.loads(getattr(raw, "arguments", "") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            step = TraceStep(
                step_type="tool_call",
                agent_name=agent_name,
                tool_name=tool_name,
                mcp_server=TOOL_TO_MCP_SERVER.get(tool_name, "MCP: Unknown"),
                arguments=arguments,
                retrieval_info=TOOL_RETRIEVAL_INFO.get(tool_name),
                attempt=attempt,
                batch=call_id_to_batch.get(call_id),
            )
            steps.append(step)
            if call_id:
                call_id_to_step_index[call_id] = len(steps) - 1

        elif item_type == "ToolCallOutputItem":
            call_id = raw.get("call_id") if isinstance(raw, dict) else None
            raw_output = raw.get("output") if isinstance(raw, dict) else None
            output_text = _extract_text_output(raw_output)
            payloads = _parse_tool_result_payloads(raw_output)
            idx = call_id_to_step_index.get(call_id)
            if idx is not None:
                steps[idx].output = output_text
                steps[idx].result_payloads = payloads
                steps[idx].cache_hit = _extract_cache_hit(payloads)
            else:
                steps.append(
                    TraceStep(
                        step_type="tool_call", agent_name=agent_name, output=output_text, attempt=attempt
                    )
                )

        elif item_type == "MessageOutputItem":
            text = ""
            content = getattr(raw, "content", None) or []
            for block in content:
                text += getattr(block, "text", "") or ""
            # text is the raw JSON of a GroundedAnswer (structured output_type),
            # not free prose -- extract the human-readable .answer for display,
            # falling back to the raw text if parsing fails for any reason.
            display_text = text
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "answer" in parsed:
                    display_text = parsed["answer"]
            except (json.JSONDecodeError, TypeError):
                pass
            steps.append(
                TraceStep(
                    step_type="message", agent_name=agent_name, message_text=display_text, attempt=attempt
                )
            )

    return steps


def _build_trace_steps_from_context(run_context: RunContext, agent_name: str, attempt: int) -> list[TraceStep]:
    """Fallback trace builder for an attempt that failed its output
    guardrail -- reconstructs tool_call steps from what RecordingHooks
    captured in run_context, since the guardrail exception doesn't carry the
    run's new_items. run_context.tool_calls records each call's real
    tool_name/arguments in call order, tagged with is_search_result so the
    matching output can be pulled from retrieved_docs or structured_lookups
    (each call appends to exactly one of those two, in the same order).
    Less detailed than _build_trace_steps (e.g. unrecognized tool names fall
    back to "MCP: Unknown"), but real tool names and arguments instead of a
    generic "(search tool)" placeholder with empty args.

    Also synthesizes a leading "handoff" TraceStep when agent_name names a
    known specialist. The Supervisor Agent has no mcp_servers at all (see
    copilot_agents/supervisor.py) -- it is architecturally incapable of
    issuing a tool call -- so any tool_calls recorded this run only exist
    because a handoff happened, even if the real HandoffOutputItem never
    made it into new_items (the guardrail/MaxTurnsExceeded exceptions lose
    that history). Without this, flow_diagram.py finds no "handoff" step,
    shows "No handoff recorded" on the Supervisor stage, and renders the
    tool calls directly below it with nothing attributing them to the
    specialist that actually made them -- which reads as the Supervisor
    calling tools itself, contradicting the architecture.
    """
    steps: list[TraceStep] = []
    if run_context.tool_calls and agent_name and agent_name in ALL_SPECIALIST_AGENTS:
        steps.append(
            TraceStep(
                step_type="handoff",
                agent_name="Supervisor Agent",
                target_agent=agent_name,
                attempt=attempt,
            )
        )

    docs = list(run_context.retrieved_docs)
    lookups = list(run_context.structured_lookups)
    doc_idx = 0
    lookup_idx = 0

    for call in run_context.tool_calls:
        if call.get("is_search_result"):
            output = docs[doc_idx].model_dump_json()
            doc_idx += 1
        else:
            output = json.dumps(lookups[lookup_idx])
            lookup_idx += 1

        tool_name = call.get("tool_name", "unknown_tool")
        steps.append(
            TraceStep(
                step_type="tool_call",
                agent_name=agent_name,
                tool_name=tool_name,
                mcp_server=TOOL_TO_MCP_SERVER.get(tool_name, "MCP: Unknown"),
                retrieval_info=TOOL_RETRIEVAL_INFO.get(tool_name),
                arguments=call.get("arguments") or {},
                output=output,
                attempt=attempt,
                batch=call.get("batch"),
            )
        )

    return steps


async def run_question(question: str) -> AskResult:
    all_trace_steps: list[TraceStep] = []
    last_structured_answer: GroundedAnswer | None = None
    last_responding_agent_name: str | None = None
    attempt_input = question

    for attempt in range(1, MAX_ATTEMPTS + 1):
        supervisor, mcp_servers = build_supervisor_agent()
        run_context = RunContext()

        async with AsyncExitStack() as stack:
            for server in mcp_servers:
                await stack.enter_async_context(server)

            try:
                result = await Runner.run(
                    supervisor,
                    attempt_input,
                    context=run_context,
                    hooks=RecordingHooks(),
                    # This is a hard, code-level bound -- NOT a substitute
                    # for the prompt-level "4 tool call budget" instruction
                    # in copilot_agents/specialists.py, which turned out to
                    # be unreliable in practice: gpt-4o-mini sometimes
                    # ignores it entirely and keeps re-querying with
                    # near-identical phrasing ("SOP-114", "SOP-114
                    # escalation", "SOP-114 escalation criteria" as three
                    # separate calls), confirmed via live tracing across
                    # several runs. Once a run is in that state it doesn't
                    # self-correct, so raising max_turns further only wastes
                    # more time/cost on a doomed attempt -- 12 is enough for
                    # a well-behaved run (handoff + ~4 tool calls + message +
                    # guardrail) with some margin, but fails fast instead of
                    # burning 25+ turns. MaxTurnsExceeded is caught below and
                    # degrades to a requires_human_review=True answer rather
                    # than crashing, so failing faster has no downside beyond
                    # this specific run's own answer quality.
                    max_turns=12,
                )
            except OutputGuardrailTripwireTriggered as exc:
                # OutputGuardrailResult (inside the exception) doesn't carry
                # the run's new_items -- the SDK raises this deep inside
                # Runner.run() after that item history is out of scope. Fall
                # back to what RecordingHooks already captured in
                # run_context for this attempt (retrieved docs + structured
                # lookups) to build an approximate trace, so a failed
                # attempt still shows real tool-call data in the Flow tab
                # instead of nothing.
                guardrail_result = exc.guardrail_result
                critic_result: CriticResult = guardrail_result.output.output_info
                failed_answer: GroundedAnswer = guardrail_result.agent_output
                agent_name = guardrail_result.agent.name

                trace_steps = _build_trace_steps_from_context(run_context, agent_name, attempt)
                trace_steps.append(
                    TraceStep(
                        step_type="critic_check",
                        agent_name=agent_name,
                        critic_result=critic_result,
                        attempt=attempt,
                    )
                )
                all_trace_steps.extend(trace_steps)
                last_structured_answer = failed_answer
                last_responding_agent_name = agent_name

                if attempt >= MAX_ATTEMPTS:
                    break

                attempt_input = (
                    f"{question}\n\n"
                    f"[Revision needed] Your previous answer was: {failed_answer.answer!r} "
                    f"(citations: {failed_answer.citations}). A reviewer found this issue: "
                    f"{critic_result.feedback}\n"
                    f"Revise your answer to address this specifically, using your tools again "
                    f"if you need additional information."
                )
                continue

            except (MaxTurnsExceeded, ModelBehaviorError) as exc:
                # SDK-internal run failures unrelated to the critic (e.g. the
                # agent looping on tool calls until it hits the SDK's own
                # turn cap). Not caught by the OutputGuardrailTripwireTriggered
                # branch above since no output was ever produced to guard, so
                # unlike that branch there's no guardrail_result.agent.name --
                # fall back to run_context.responding_agent_name, set by
                # RecordingHooks.on_tool_end from the real agent each tool
                # call actually belonged to (see copilot_agents/critic.py).
                # run_context still has whatever RecordingHooks captured
                # before the cap was hit -- use the same fallback trace
                # builder the guardrail-trip branch uses, so a MaxTurnsExceeded
                # failure still shows real tool-call data instead of nothing
                # (this was previously silently dropped here).
                fallback_agent_name = run_context.responding_agent_name or "?"
                all_trace_steps.extend(
                    _build_trace_steps_from_context(run_context, fallback_agent_name, attempt)
                )
                all_trace_steps.append(
                    TraceStep(
                        step_type="critic_check",
                        agent_name=fallback_agent_name,
                        critic_result=CriticResult(
                            passed=False,
                            feedback=f"Run failed before producing an answer: {exc}",
                            layer="deterministic",
                        ),
                        attempt=attempt,
                    )
                )
                last_structured_answer = GroundedAnswer(
                    answer=(
                        "I was unable to produce a grounded answer for this question -- the "
                        "underlying agent run did not complete successfully. This has been "
                        "flagged for human review."
                    ),
                    citations=[],
                    confidence="low",
                    requires_human_review=True,
                )
                last_responding_agent_name = None
                break

            # Success: critic passed (no exception raised).
            trace_steps = _build_trace_steps(result.new_items, attempt, run_context.call_id_to_batch)
            responding_agent_name = next(
                (s.agent_name for s in reversed(trace_steps) if s.step_type == "message"), "?"
            )
            trace_steps.append(
                TraceStep(
                    step_type="critic_check",
                    agent_name=responding_agent_name,
                    critic_result=CriticResult(passed=True, layer="llm"),
                    attempt=attempt,
                )
            )
            all_trace_steps.extend(trace_steps)

            # result.final_output is only a GroundedAnswer when a specialist
            # (which has output_type=GroundedAnswer) actually produced the
            # final message. The Supervisor itself has no output_type -- if
            # the question doesn't match any routing category (e.g. small
            # talk, out-of-scope questions), the Supervisor answers directly
            # and final_output is a plain str. Normalize either case to a
            # GroundedAnswer so downstream code has one shape to work with.
            if isinstance(result.final_output, GroundedAnswer):
                structured_answer = result.final_output
            else:
                structured_answer = GroundedAnswer(
                    answer=str(result.final_output),
                    citations=[],
                    confidence="low",
                    requires_human_review=False,
                )

            published = False
            review_queue_id = None
            if responding_agent_name in REVIEW_TRIGGERING_AGENTS:
                draft = _extract_promotable_draft(all_trace_steps)
                review_queue_id = await publish_needs_review(
                    question,
                    structured_answer.answer,
                    responding_agent_name,
                    linked_record_type=draft[0] if draft else None,
                    linked_record_id=draft[1] if draft else None,
                    structured_payload=draft[2] if draft else None,
                )
                published = True

            return AskResult(
                final_answer=structured_answer.answer,
                trace_steps=all_trace_steps,
                responding_agent_name=responding_agent_name,
                published_for_review=published,
                review_queue_id=review_queue_id,
                structured_answer=structured_answer,
                attempt_count=attempt,
            )

    # Exhausted all attempts without passing the critic -- return the last
    # draft anyway (never silently drop an answer), forced to
    # requires_human_review=True since it never cleared its own quality
    # bar. The existing human review queue is the final backstop.
    if last_structured_answer is not None:
        last_structured_answer = last_structured_answer.model_copy(update={"requires_human_review": True})

    final_text = (
        last_structured_answer.answer
        if last_structured_answer is not None
        else "Unable to produce a grounded answer after multiple attempts."
    )

    published = False
    review_queue_id = None
    if last_responding_agent_name and last_structured_answer is not None:
        draft = _extract_promotable_draft(all_trace_steps)
        review_queue_id = await publish_needs_review(
            question,
            final_text,
            last_responding_agent_name,
            linked_record_type=draft[0] if draft else None,
            linked_record_id=draft[1] if draft else None,
            structured_payload=draft[2] if draft else None,
        )
        published = True

    return AskResult(
        final_answer=final_text,
        trace_steps=all_trace_steps,
        responding_agent_name=last_responding_agent_name,
        published_for_review=published,
        review_queue_id=review_queue_id,
        structured_answer=last_structured_answer,
        attempt_count=attempt,
    )

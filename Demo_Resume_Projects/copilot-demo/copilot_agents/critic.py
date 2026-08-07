"""Critic review: deterministic checks + a genuine SDK output_guardrail LLM
critic, layered before an answer is considered done -- sits in front of the
existing human-review queue, not instead of it (see copilot_agents/review_queue.py).

Architecture note on how the LLM critic gets access to what was retrieved:
output_guardrail functions only receive (context, agent, agent_output) --
no direct handle on the run's tool-call history. MCP tools are internally
converted to SDK FunctionTools (confirmed via agents.mcp.util), so they DO
flow through RunHooks.on_tool_end like any other tool call. RunContext
(below) is passed as Runner.run(..., context=...) and RecordingHooks
(passed as Runner.run(..., hooks=...)) appends every SearchResult it sees
into that shared context object as tool calls complete -- by the time the
agent produces its final output and the guardrail fires, context.context
already has the full list of documents this run actually retrieved, with
no extra plumbing inside the MCP servers themselves.
"""
import json
from dataclasses import dataclass, field

from agents import Agent, GuardrailFunctionOutput, Runner, RunHooks, output_guardrail
from agents.run_context import RunContextWrapper

from copilot_agents.schemas import CriticResult, GroundedAnswer, SearchResult

CRITIC_MODEL = "gpt-4o-mini"


@dataclass
class RunContext:
    """Shared per-run state, threaded through Runner.run(context=...) and
    read by both RecordingHooks (writes) and the LLM critic guardrail
    (reads). Not passed to the LLM itself -- SDK contexts are app-side only.

    retrieved_docs: full SearchResult objects (with excerpt text) from
      search_* tool calls.
    structured_lookups: raw JSON payloads from non-search tool calls
      (get_batch_metadata, get_capa_status, get_sop_by_id, create_capa_draft)
      -- these carry facts (disposition_status, deviation classification,
      CAPA monitoring window, etc.) that never appear as SearchResult
      excerpts, so without this the LLM critic would be checking answers
      against a source-text pool that's missing most of what the answering
      agent actually saw.
    seen_record_ids: every identifier the agent could legitimately have
      learned about from ANY tool call this run -- SearchResult.doc_id,
      but also BatchMetadata.batch_id + its nested deviation_ids,
      CapaStatus.capa_id, SopDocument.doc_id, CapaDraft.draft_capa_id.
      This is what citations are actually checked against: a citation to
      an ID surfaced by a structured lookup (e.g. a deviation_id nested in
      get_batch_metadata's response) is just as grounded as one from a
      search hit, and flagging it as fabricated would be a false positive.
    tool_calls: one entry per recorded tool call, in call order, each
      {"tool_name": str, "arguments": dict}. Kept as a plain parallel record
      (not folded into retrieved_docs/structured_lookups, which the critic
      logic above already depends on) purely so ask_flow.py's fallback trace
      builder can show which tool was called with what arguments for an
      attempt that failed its output guardrail -- see
      copilot_agents/ask_flow.py's _build_trace_steps_from_context.
    call_id_to_batch: maps each ToolCallItem's call_id to a batch index
      (0, 1, 2, ...) -- one index per model turn that emitted tool calls.
      When the model emits several tool calls in a single response, the SDK
      genuinely executes them concurrently (see
      agents.run_internal.tool_execution._FunctionToolBatchExecutor), so
      calls sharing a batch index actually ran in parallel, not in sequence
      -- ask_flow.py uses this to group them in the Flow tab instead of
      drawing one flat arrow-chain that implies serial execution that never
      happened.
    responding_agent_name: the .name of the agent that actually issued the
      most recent tool call this run (set from on_tool_end's own `agent`
      param, which the SDK always supplies -- the Supervisor never has
      mcp_servers, so any tool_call this run recorded can only have come
      from whichever specialist the Supervisor handed off to). Exists so a
      fallback-reconstructed trace (guardrail trip / MaxTurnsExceeded, see
      ask_flow.py's _build_trace_steps_from_context) can attribute its tool
      calls to the real specialist agent instead of leaving agent identity
      unknown, which would otherwise make the diagram default to implying
      the Supervisor made the calls it structurally cannot make.
    """

    retrieved_docs: list[SearchResult] = field(default_factory=list)
    structured_lookups: list[dict] = field(default_factory=list)
    seen_record_ids: set[str] = field(default_factory=set)
    tool_calls: list[dict] = field(default_factory=list)
    call_id_to_batch: dict[str, int] = field(default_factory=dict)
    _next_batch_index: int = field(default=0, repr=False)
    responding_agent_name: str | None = None


# Keys, per tool-output shape, whose values are IDs the agent may
# legitimately cite -- checked in order; a payload can match multiple
# shapes' key sets loosely, so all matching ID fields are collected.
_ID_FIELD_NAMES = ("doc_id", "batch_id", "deviation_id", "capa_id", "draft_capa_id", "related_deviation_id")


class RecordingHooks(RunHooks[RunContext]):
    """Passed to Runner.run(hooks=...) -- parses each MCP tool's raw result
    (a {"type": "text", "text": "<json>"} dict, or a list of them for
    search/list tools) and records:
      - full SearchResult objects into context.context.retrieved_docs
        (only search_* tools return this shape)
      - everything else (get_batch_metadata/get_capa_status/get_sop_by_id/
        create_capa_draft payloads) into context.context.structured_lookups,
        so the LLM critic can see the same facts the answering agent saw,
        not just search excerpts
      - every ID-shaped field value (doc_id, batch_id, deviation_id, etc.,
        including nested ones like BatchMetadata.deviations[].deviation_id)
        into context.context.seen_record_ids, recursively, so any
        structured lookup's identifiers count as legitimately grounded.
    Skips ToolError payloads ({"error": ...}) -- nothing to ground against.

    Also implements on_llm_end, which fires once per model turn with the
    full ModelResponse -- every ResponseFunctionToolCall in response.output
    was emitted together and (per _FunctionToolBatchExecutor) actually
    executes concurrently, so this assigns all of them the same batch index
    in context.context.call_id_to_batch before on_tool_start/on_tool_end
    ever fire for them.
    """

    async def on_llm_end(self, context: RunContextWrapper[RunContext], agent, response) -> None:
        call_ids = [
            getattr(item, "call_id", None)
            for item in getattr(response, "output", [])
            if type(item).__name__ == "ResponseFunctionToolCall"
        ]
        call_ids = [c for c in call_ids if c]
        if not call_ids:
            return
        batch_index = context.context._next_batch_index
        context.context._next_batch_index += 1
        for call_id in call_ids:
            context.context.call_id_to_batch[call_id] = batch_index

    async def on_tool_end(self, context: RunContextWrapper[RunContext], agent, tool, result) -> None:
        # context is actually a ToolContext at runtime (the SDK passes the
        # same object to on_tool_start/on_tool_end as executes the call) --
        # tool_name/tool_arguments live there, not on RunContextWrapper's
        # declared type. Best-effort: fall back to the tool's own .name and
        # {} if this ever runs against a plain RunContextWrapper instead.
        tool_name = getattr(context, "tool_name", None) or getattr(tool, "name", "unknown_tool")
        raw_arguments = getattr(context, "tool_arguments", None)
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        call_id = getattr(context, "tool_call_id", None)
        batch = context.context.call_id_to_batch.get(call_id) if call_id else None
        agent_name = getattr(agent, "name", None)
        if agent_name:
            context.context.responding_agent_name = agent_name

        items = result if isinstance(result, list) else [result]
        for item in items:
            text = item.get("text") if isinstance(item, dict) else None
            if not text:
                continue
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict) or "error" in payload:
                continue

            is_search_result = False
            if {"doc_id", "excerpt", "relevance_score"} <= payload.keys():
                try:
                    context.context.retrieved_docs.append(SearchResult(**payload))
                    is_search_result = True
                except Exception:
                    pass
            if not is_search_result:
                context.context.structured_lookups.append(payload)

            context.context.tool_calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "is_search_result": is_search_result,
                    "batch": batch,
                }
            )

            self._collect_ids(payload, context.context.seen_record_ids)

    def _collect_ids(self, obj, sink: set[str]) -> None:
        """Recursively walks any dict/list structure, adding the value of
        any key in _ID_FIELD_NAMES (if it's a non-empty string) to sink.
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in _ID_FIELD_NAMES and isinstance(value, str) and value:
                    sink.add(value)
                self._collect_ids(value, sink)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_ids(item, sink)


def run_deterministic_checks(
    answer: GroundedAnswer, retrieved_docs: list[SearchResult], seen_record_ids: set[str]
) -> CriticResult:
    """Fast, free, no LLM call. The single highest-value check for a
    grounded-answer system: every citation must correspond to an
    identifier the agent actually saw this run -- from a search hit
    (retrieved_docs) OR a structured lookup (seen_record_ids, which also
    includes every doc_id/batch_id/deviation_id/capa_id surfaced by any
    tool call, not just search results) -- catches hallucinated/fabricated
    citations, which an LLM critic could in principle also catch but far
    less reliably and far more expensively.
    """
    if not answer.answer.strip():
        return CriticResult(passed=False, feedback="Answer text is empty.", layer="deterministic")

    fabricated = [c for c in answer.citations if c not in seen_record_ids]
    if fabricated:
        return CriticResult(
            passed=False,
            feedback=(
                f"Citation(s) {fabricated} do not correspond to any document or record ID "
                f"actually surfaced by a tool call this run (seen: {sorted(seen_record_ids) or 'none'}). "
                f"Only cite doc_ids/batch_ids/deviation_ids/capa_ids returned by your own tool calls."
            ),
            layer="deterministic",
        )

    if answer.citations and not seen_record_ids:
        return CriticResult(
            passed=False,
            feedback="Answer includes citations but no tool calls were made this run.",
            layer="deterministic",
        )

    return CriticResult(passed=True, layer="deterministic")


_critic_agent: Agent | None = None


def _get_critic_agent() -> Agent:
    """Lazily built, module-level singleton -- the critic agent has no
    tools/handoffs, so it's cheap to keep around rather than rebuild per
    guardrail invocation.
    """
    global _critic_agent
    if _critic_agent is None:
        _critic_agent = Agent(
            name="Answer Critic",
            instructions=(
                "You are a strict critic reviewing a draft answer from a pharmaceutical quality "
                "copilot before it is shown to a user. You will be given the original question, "
                "the draft answer with its citations, and the full text of the source documents "
                "that were retrieved and cited.\n\n"
                "Judge ONLY whether the answer's claims are actually supported by the cited source "
                "text -- not whether the answer is well-written or whether you would phrase it "
                "differently. Fail the answer if: it asserts something the cited sources don't "
                "actually say; it draws a conclusion (e.g. a classification, a disposition) that "
                "the cited SOP/record text doesn't support; or it ignores directly relevant "
                "information present in the retrieved sources.\n\n"
                "Set passed=true if the answer is adequately grounded, even if imperfectly phrased. "
                "Set passed=false only for genuine grounding failures, and make feedback specific "
                "and actionable -- it will be given back to the answering agent to revise."
            ),
            model=CRITIC_MODEL,
            output_type=CriticResult,
        )
    return _critic_agent


@output_guardrail
async def llm_critic_guardrail(
    context: RunContextWrapper[RunContext], agent: Agent, agent_output: GroundedAnswer
) -> GuardrailFunctionOutput:
    """Real SDK output_guardrail, attached to every specialist agent's
    output_guardrails list (see copilot_agents/specialists.py). Runs the
    LLM critic against the specialist's GroundedAnswer plus whatever
    RecordingHooks recorded in context.context.retrieved_docs for this run,
    and trips the tripwire on a failed verdict -- ask_flow.py's retry loop
    catches OutputGuardrailTripwireTriggered and retries with the critic's
    feedback appended to the input.
    """
    retrieved_docs = context.context.retrieved_docs if context.context else []
    structured_lookups = context.context.structured_lookups if context.context else []
    seen_record_ids = context.context.seen_record_ids if context.context else set()

    deterministic = run_deterministic_checks(agent_output, retrieved_docs, seen_record_ids)
    if not deterministic.passed:
        return GuardrailFunctionOutput(output_info=deterministic, tripwire_triggered=True)

    source_blocks = [f"[{doc.doc_id}] {doc.title}\n{doc.excerpt}" for doc in retrieved_docs]
    source_blocks += [f"[structured lookup] {json.dumps(lookup)}" for lookup in structured_lookups]
    sources_text = "\n\n---\n\n".join(source_blocks) or "(no data was retrieved this run)"
    critic_input = (
        f"Draft answer: {agent_output.answer}\n"
        f"Citations: {agent_output.citations}\n"
        f"Confidence: {agent_output.confidence}\n\n"
        f"Retrieved source documents:\n{sources_text}"
    )

    critic_result = await Runner.run(_get_critic_agent(), critic_input)
    verdict: CriticResult = critic_result.final_output
    llm_result = CriticResult(passed=verdict.passed, feedback=verdict.feedback, layer="llm")

    return GuardrailFunctionOutput(output_info=llm_result, tripwire_triggered=not llm_result.passed)

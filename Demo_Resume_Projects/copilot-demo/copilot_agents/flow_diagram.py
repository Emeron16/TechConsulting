"""Renders a self-contained HTML/CSS pipeline diagram for one Ask run,
combining real trace data (from copilot_agents.ask_flow.AskResult) with
static placeholder stages representing the parts of the original Azure
architecture not implemented in this local build (Entra ID, API Gateway,
AKS, etc.) -- so the diagram stays visually complete against the original
12-layer design without ever fabricating data for what isn't real here.

A run may span multiple attempts (copilot_agents/critic.py's output
guardrail + copilot_agents/ask_flow.py's retry loop) -- each attempt's
handoff/tool-call/message/critic-check steps are grouped under its own
"Attempt N" label so a failed-then-retried-then-passed run is fully
visible, not collapsed into one flat sequence.

Pure function, no I/O of its own -- the caller (streamlit_app.py) is
responsible for fetching review status and passing it in. Shared CSS/stage
helpers live in copilot_agents/diagram_common.py (also used by
ingest_flow_diagram.py) so both diagrams stay visually consistent.
"""
import json

from copilot_agents.ask_flow import ALL_SPECIALIST_AGENTS, AskResult
from copilot_agents.diagram_common import (
    CSS,
    REAL_TAG,
    arrow,
    attempt_label,
    cache_badge,
    esc,
    parallel_label,
    placeholder,
    print_button,
    retrieval_badge,
    score_table,
    stage,
)


def _group_by_batch(tool_steps: list) -> list[list]:
    """Groups consecutive tool_call steps that share a non-None batch index
    into one sub-list each; a step with batch=None (unknown -- e.g. an
    older-shaped trace) gets its own single-item group. Steps are already in
    call order and same-batch calls are always contiguous (assigned
    together in RecordingHooks.on_llm_end), so a simple consecutive-run
    grouping is sufficient -- no need to sort or bucket by batch value
    globally.
    """
    groups: list[list] = []
    for step in tool_steps:
        if (
            groups
            and step.batch is not None
            and groups[-1]
            and groups[-1][-1].batch == step.batch
        ):
            groups[-1].append(step)
        else:
            groups.append([step])
    return groups


def _render_attempt(steps: list, attempt: int, total_attempts: int) -> list[str]:
    """Renders one attempt's handoff -> tool calls -> message -> critic
    check as a sequence of stage/arrow HTML fragments.
    """
    parts: list[str] = []
    if total_attempts > 1:
        parts.append(attempt_label(attempt, total_attempts))

    handoff_step = next((s for s in steps if s.step_type == "handoff"), None)
    target_agent = handoff_step.target_agent if handoff_step else None
    parts.append(
        stage(
            "real-supervisor",
            "Supervisor / Router Agent",
            sub=f"Routed to: {target_agent}" if target_agent else "No handoff recorded",
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    not_selected = [a for a in ALL_SPECIALIST_AGENTS if a != target_agent]
    if not_selected:
        row = "".join(f'<div class="not-selected">{esc(a)}<br>(not selected)</div>' for a in not_selected)
        parts.append(f'<div class="not-selected-row">{row}</div>')
        parts.append(arrow())

    if target_agent:
        parts.append(stage("real-agent", target_agent, sub="Specialist agent", tag=REAL_TAG))
        parts.append(arrow())

    tool_steps = [s for s in steps if s.step_type == "tool_call"]
    for batch_steps in _group_by_batch(tool_steps):
        batch_html = []
        for step in batch_steps:
            args_str = json.dumps(step.arguments or {}, indent=2)
            detail = f"args: {args_str}\n\noutput:\n{(step.output or '')[:600]}"
            extra = retrieval_badge(step.retrieval_info) + cache_badge(step.cache_hit)
            if len(step.result_payloads) > 1 or (step.result_payloads and "bm25_score" in step.result_payloads[0]):
                extra += score_table(step.result_payloads)
            batch_html.append(
                stage(
                    "real-tool",
                    step.tool_name or "tool",
                    sub=step.mcp_server or "MCP server",
                    detail=detail,
                    tag=REAL_TAG,
                    extra_html=extra,
                )
            )
        if len(batch_html) > 1:
            parts.append(parallel_label(len(batch_html)))
            parts.append('<div class="side-by-side parallel-batch">' + "".join(batch_html) + "</div>")
        else:
            parts.extend(batch_html)
        parts.append(arrow())

    message_step = next((s for s in steps if s.step_type == "message"), None)
    if message_step:
        answer_preview = message_step.message_text or ""
        parts.append(
            stage(
                "real-answer",
                "Draft Answer",
                detail=answer_preview[:500] + ("..." if len(answer_preview) > 500 else ""),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

    critic_step = next((s for s in steps if s.step_type == "critic_check"), None)
    if critic_step and critic_step.critic_result:
        result = critic_step.critic_result
        css_class = "critic-pass" if result.passed else "critic-fail"
        title = "Critic Review: PASSED" if result.passed else "Critic Review: FAILED"
        parts.append(
            stage(
                css_class,
                title,
                sub=f"{result.layer} layer",
                detail=result.feedback if not result.passed else "",
            )
        )
        parts.append(arrow())

    return parts


def render_flow_html(ask_result: AskResult, question: str, review_status: dict | None) -> str:
    """review_status: None if this run never triggered review, otherwise a
    dict like {"status": "pending"|"approved"|"rejected", "reviewed_by": ...,
    "reason": ...} looked up by the caller (see streamlit_app.py).
    """
    parts: list[str] = [CSS, '<div class="flow-wrap">', print_button(), '<div class="flow-col">']

    # -- Auth / Gateway placeholder band (precedes everything, per original architecture)
    parts.append(f'<div class="band-label">{esc("API & Identity Layer (original architecture)")}</div>')
    parts.append(placeholder("Microsoft Entra ID (SSO)", "Authenticates the requesting user"))
    parts.append(arrow())
    parts.append(placeholder("RBAC Policy Engine", "Authorizes the request by role"))
    parts.append(arrow())
    parts.append(placeholder("FastAPI Gateway Service", "Single entry point, request routing"))
    parts.append(arrow())

    # -- Real: user question
    parts.append('<div class="band-label">Live Run</div>')
    parts.append(stage("real-user", "User Question", detail=question, tag=REAL_TAG))
    parts.append(arrow())

    # -- Real: one block per attempt (handoff -> tool calls -> draft -> critic check)
    total_attempts = ask_result.attempt_count
    for attempt_num in range(1, total_attempts + 1):
        attempt_steps = [s for s in ask_result.trace_steps if s.attempt == attempt_num]
        if not attempt_steps:
            continue
        parts.extend(_render_attempt(attempt_steps, attempt_num, total_attempts))

    # -- Secrets/identity placeholder alongside the MCP layer
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Azure Key Vault", "Secrets for MCP servers")
        + placeholder("Managed Identity", "Service-to-service auth")
        + "</div>"
    )
    parts.append(arrow())

    # -- Real: LLM reasoning
    parts.append(
        stage("real-llm", "Reasoning: gpt-4o-mini", sub="OpenAI API (local substitute for Azure OpenAI)", tag=REAL_TAG)
    )
    parts.append(arrow())

    # -- Real: final answer (the one that actually cleared the critic, or
    # the last draft if every attempt was exhausted)
    parts.append(
        stage(
            "real-answer",
            "Final Answer",
            sub=f"After {total_attempts} attempt(s)" if total_attempts > 1 else "",
            detail=ask_result.final_answer[:500] + ("..." if len(ask_result.final_answer) > 500 else ""),
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    # -- Observability placeholder + real LangSmith side by side
    parts.append(
        '<div class="side-by-side">'
        + stage("real-llm", "LangSmith", sub="Trace export (real, local substitute)", tag=REAL_TAG)
        + placeholder("Azure Monitor + App Insights", "Original observability layer")
        + placeholder("Azure AI Foundry", "Prompt versioning & RAI governance")
        + "</div>"
    )

    # -- Accept/deny decision (only if this run triggered review)
    if ask_result.published_for_review:
        parts.append(arrow())
        if review_status is None or review_status.get("status") == "pending":
            parts.append(
                stage(
                    "decision-pending",
                    "Human Review: PENDING",
                    sub="Awaiting Quality Reviewer / QP approve or reject",
                )
            )
        elif review_status.get("status") == "approved":
            parts.append(
                stage(
                    "decision-approved",
                    "Human Review: APPROVED",
                    sub=f"Approved by {review_status.get('reviewed_by', '?')}",
                )
            )
            parts.append(arrow())
            parts.append(
                stage(
                    "real-audit",
                    "Audit Log Entry",
                    sub="E-signature recorded, hash-chained, insert-only",
                    tag=REAL_TAG,
                )
            )
        elif review_status.get("status") == "rejected":
            parts.append(
                stage(
                    "decision-rejected",
                    "Human Review: REJECTED",
                    sub=f"Rejected by {review_status.get('reviewed_by', '?')}",
                    detail=review_status.get("reason", ""),
                )
            )
            parts.append(arrow())
            parts.append(
                stage(
                    "real-audit",
                    "Audit Log Entry",
                    sub="Rejection reason recorded, hash-chained, insert-only",
                    tag=REAL_TAG,
                )
            )

    # -- Infra placeholder band (always shown, static, at the very end)
    parts.append(f'<div class="band-label">{esc("Infrastructure & Deployment (original architecture)")}</div>')
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Azure Kubernetes Service")
        + placeholder("Azure Container Registry")
        + placeholder("GitHub Actions CI/CD")
        + "</div>"
    )

    parts.append("</div></div>")
    return "".join(parts)

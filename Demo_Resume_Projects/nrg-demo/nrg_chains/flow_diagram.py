"""Renders a self-contained HTML/CSS pipeline diagram for one Ask run,
combining real chain-trace data (from nrg_chains.chain.AskResult) with
static placeholder stages representing parts of the original AWS
architecture not implemented locally (IAM, API Gateway, KMS, Secrets
Manager, CloudWatch, CloudTrail, ECS Fargate) -- same visual language and
real/placeholder convention as copilot-demo's flow_diagram.py, sibling
module nrg_chains/diagram_common.py.

Critical distinction from copilot-demo's diagram: there is no conditional
"Human Review: PENDING/APPROVED/REJECTED" gate stage here. Every run
writes an unconditional sampled_answers row (nrg_chains/sampling.py) --
that write is rendered as a normal solid "real" stage on every single run,
never a dashed/pending decision stage, because nothing about it ever
blocks the answer the user already received. See
NRG_Energy_Architecture_Deep_Dive.md §2.1/§3 for the underlying design
contrast with the Novartis project's mandatory per-answer sign-off.
"""
from nrg_chains.chain import AskResult
from nrg_chains.diagram_common import CSS, REAL_TAG, arrow, cache_badge, esc, placeholder, score_table, stage


def render_flow_html(ask_result: AskResult, question: str) -> str:
    parts: list[str] = [CSS, '<div class="flow-wrap"><div class="flow-col">']

    # -- API Gateway / IAM placeholder band (original architecture)
    parts.append(f'<div class="band-label">{esc("API & Identity Layer (original architecture)")}</div>')
    parts.append(placeholder("Amazon API Gateway", "Routing, throttling, request validation"))
    parts.append(arrow())
    parts.append(placeholder("AWS IAM", "Authenticates/authorizes the request"))
    parts.append(arrow())

    # -- Real: user question
    parts.append('<div class="band-label">Live Run</div>')
    parts.append(stage("real-user", "User Question", detail=question, tag=REAL_TAG))
    parts.append(arrow())

    classification_step = next((s for s in ask_result.trace_steps if s.step_type == "classification"), None)
    retrieval_step = next((s for s in ask_result.trace_steps if s.step_type == "retrieval"), None)
    fallback_step = next((s for s in ask_result.trace_steps if s.step_type == "fallback"), None)
    generation_step = next((s for s in ask_result.trace_steps if s.step_type == "generation"), None)
    sampling_step = next((s for s in ask_result.trace_steps if s.step_type == "sampling"), None)

    # -- diskcache lookup badge, shown inline on the retrieval stage below
    # rather than as its own stage, since a cache check is a property of
    # the retrieval call, not a separate pipeline step.

    # -- Real: LangChain Orchestrator -- doc-type classification
    if classification_step:
        d = classification_step.detail
        parts.append(
            stage(
                "real-supervisor",
                "LangChain Orchestrator: Classification",
                sub=f"doc_type = {d.get('doc_type') or '(unclassified)'}",
                detail=d.get("reasoning", ""),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

    # -- Real: Qdrant hybrid retrieval
    if retrieval_step:
        d = retrieval_step.detail
        results = retrieval_step.result_payloads
        cache_hit = retrieval_step.cache_hit
        extra = cache_badge(cache_hit) + score_table(results)
        parts.append(
            stage(
                "real-tool",
                "Qdrant: Hybrid Retrieval",
                sub="OpenSearch Serverless analog — dense + sparse (BM25) + native RRF fusion",
                detail=f"doc_type filter: {d.get('doc_type_filter') or '(none)'}\nresults: {d.get('result_count')}",
                tag=REAL_TAG,
                extra_html=extra,
            )
        )
        parts.append(arrow())

    if fallback_step:
        d = fallback_step.detail
        parts.append(
            stage(
                "real-tool",
                "Fallback: Unfiltered Retrieval Retry",
                sub=d.get("reason", ""),
                detail=f"results: {d.get('result_count')}",
                extra_html=score_table(fallback_step.result_payloads),
            )
        )
        parts.append(arrow())

    # -- Secrets/identity placeholder alongside generation
    parts.append(
        '<div class="side-by-side">'
        + placeholder("AWS Secrets Manager", "API keys for the orchestrator")
        + placeholder("AWS KMS", "Encryption keys for stored data")
        + "</div>"
    )
    parts.append(arrow())

    # -- Real: LLM generation
    if generation_step and not generation_step.detail.get("skipped"):
        d = generation_step.detail
        parts.append(
            stage(
                "real-llm",
                "Reasoning: gpt-4o-mini",
                sub="OpenAI API — Amazon Bedrock analog",
                detail=f"confidence: {d.get('confidence')}\ncitations: {d.get('citations')}",
                tag=REAL_TAG,
            )
        )
    else:
        parts.append(
            stage(
                "outcome-noop",
                "Generation Skipped",
                sub="No retrieved context to ground an answer — canned low-confidence response returned",
            )
        )
    parts.append(arrow())

    # -- Real: final answer
    parts.append(
        stage(
            "real-answer",
            "Final Answer",
            detail=ask_result.final_answer[:500] + ("..." if len(ask_result.final_answer) > 500 else ""),
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    # -- Real, UNCONDITIONAL: sampled_answers write. Always shown, never a
    # pending/gate stage -- this is the visual proof that nothing here
    # blocks the answer the user already has.
    sampled_id = sampling_step.detail.get("sampled_answer_id") if sampling_step else None
    parts.append(
        stage(
            "real-audit",
            "Postgres: Logged to sampled_answers",
            sub=f"id={sampled_id} — statistical sampling model, no approval gate",
            detail=(
                "Every answer is logged here immediately and was already delivered to the user "
                "above. Compliance/Legal may sample this row later via the Compliance Review tab "
                "(contrast with the Novartis demo's mandatory pre-publish review queue)."
            ),
            tag=REAL_TAG,
        )
    )

    # -- Observability placeholder band
    parts.append(f'<div class="band-label">{esc("Observability & Evaluation (original architecture)")}</div>')
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Amazon CloudWatch", "Logs, latency metrics, alarms")
        + placeholder("AWS CloudTrail", "API-level account activity audit")
        + placeholder("RAGAS + G-Eval + LLM-as-Judge", "Offline evaluation framework")
        + "</div>"
    )

    # -- Infra placeholder band
    parts.append(f'<div class="band-label">{esc("Infrastructure & Deployment (original architecture)")}</div>')
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Amazon ECS Fargate")
        + placeholder("Amazon ECR")
        + placeholder("GitHub Actions CI/CD")
        + "</div>"
    )

    parts.append("</div></div>")
    return "".join(parts)

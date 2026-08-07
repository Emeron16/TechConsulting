"""The single LangChain retrieval chain -- NRG's equivalent of
copilot-demo's copilot_agents/ask_flow.py. run_question() is the one
orchestration entry point both scripts/ask.py (CLI) and nrg_app.py (UI)
call, so there's exactly one code path.

Written as an explicit async function rather than one piped LCEL
`.invoke()` call, same reasoning as ask_flow.py wrapping Runner.run()
explicitly: each stage needs to populate a ChainTraceStep for the Flow
tab's diagram, which is easier to do with real control flow than by trying
to make the trace itself a Runnable.

Fallback logic (per NRG_Energy_Architecture_Deep_Dive.md's "LangChain
Orchestrator... fallback logic" line): if classification doesn't resolve
to a doc_type, or filtered retrieval returns nothing, retry retrieval
unfiltered once before generating; if that's also empty, short-circuit to
a canned low-confidence answer without calling the generation LLM at all.
"""
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI

from nrg_chains.classifier import classify_question
from nrg_chains.prompts import ANSWER_PROMPT, format_context
from nrg_chains.retriever import NRGHybridRetriever
from nrg_chains.sampling import log_sampled_answer
from nrg_chains.schemas import ClassifiedQuery, GroundedAnswerNRG

GENERATION_MODEL = "gpt-4o-mini"
MIN_RESULTS_BEFORE_FALLBACK = 1

_generation_llm = ChatOpenAI(model=GENERATION_MODEL, temperature=0.2)
_generation_chain = ANSWER_PROMPT | _generation_llm.with_structured_output(GroundedAnswerNRG)

NO_GROUNDED_SOURCE_ANSWER = GroundedAnswerNRG(
    answer=(
        "I wasn't able to find a relevant source document to ground an answer to this question. "
        "Please rephrase, or escalate per ESC-BILLING-DISPUTE / ESC-SAFETY-CONCERN if this is a "
        "customer-facing situation that needs immediate handling."
    ),
    citations=[],
    confidence="low",
    doc_type_classified=None,
)


@dataclass
class ChainTraceStep:
    step_type: str  # "classification" | "retrieval" | "generation" | "sampling" | "fallback"
    detail: dict = field(default_factory=dict)
    result_payloads: list[dict] = field(default_factory=list)
    cache_hit: bool | None = None


@dataclass
class AskResult:
    final_answer: str
    trace_steps: list[ChainTraceStep] = field(default_factory=list)
    structured_answer: GroundedAnswerNRG | None = None
    sampled_answer_id: int | None = None


def _search_result_to_dict(doc) -> dict:
    return {
        "doc_id": doc.metadata["doc_id"],
        "title": doc.metadata["title"],
        "doc_type": doc.metadata["doc_type"],
        "version": doc.metadata["version"],
        "effective_date": doc.metadata["effective_date"],
        "excerpt": doc.page_content,
        "dense_score": doc.metadata.get("dense_score"),
        "sparse_score": doc.metadata.get("sparse_score"),
        "fusion_score": doc.metadata.get("fusion_score"),
        "rerank_score": doc.metadata.get("rerank_score"),
        "cache_hit": doc.metadata.get("cache_hit", False),
    }


async def run_question(question: str) -> AskResult:
    trace_steps: list[ChainTraceStep] = []

    classification: ClassifiedQuery = await classify_question(question)
    trace_steps.append(
        ChainTraceStep(
            step_type="classification",
            detail={
                "doc_type": classification.doc_type,
                "plan_type_hint": classification.plan_type_hint,
                "reasoning": classification.reasoning,
            },
        )
    )

    retriever = NRGHybridRetriever(doc_type=classification.doc_type, top_k=5)
    docs = await retriever.ainvoke(question)
    payloads = [_search_result_to_dict(d) for d in docs]
    trace_steps.append(
        ChainTraceStep(
            step_type="retrieval",
            detail={"doc_type_filter": classification.doc_type, "result_count": len(docs)},
            result_payloads=payloads,
            cache_hit=payloads[0]["cache_hit"] if payloads else None,
        )
    )

    if len(docs) < MIN_RESULTS_BEFORE_FALLBACK and classification.doc_type is not None:
        # Filtered retrieval came up empty -- retry unfiltered once before
        # giving up, since the classifier's category guess may simply be
        # wrong for this question even though the right document exists.
        fallback_retriever = NRGHybridRetriever(doc_type=None, top_k=5)
        docs = await fallback_retriever.ainvoke(question)
        payloads = [_search_result_to_dict(d) for d in docs]
        trace_steps.append(
            ChainTraceStep(
                step_type="fallback",
                detail={"reason": "filtered retrieval empty, retried unfiltered", "result_count": len(docs)},
                result_payloads=payloads,
            )
        )

    if not docs:
        structured_answer = NO_GROUNDED_SOURCE_ANSWER
        trace_steps.append(
            ChainTraceStep(step_type="generation", detail={"skipped": True, "reason": "no retrieved context"})
        )
    else:
        context = format_context(payloads)
        structured_answer = await _generation_chain.ainvoke({"question": question, "context": context})
        structured_answer = structured_answer.model_copy(
            update={"doc_type_classified": classification.doc_type}
        )
        trace_steps.append(
            ChainTraceStep(
                step_type="generation",
                detail={
                    "confidence": structured_answer.confidence,
                    "citations": structured_answer.citations,
                },
            )
        )

    sampled_id = log_sampled_answer(
        question=question,
        answer=structured_answer.answer,
        doc_type_classified=structured_answer.doc_type_classified,
        citations=structured_answer.citations,
        confidence=structured_answer.confidence,
    )
    trace_steps.append(ChainTraceStep(step_type="sampling", detail={"sampled_answer_id": sampled_id}))

    return AskResult(
        final_answer=structured_answer.answer,
        trace_steps=trace_steps,
        structured_answer=structured_answer,
        sampled_answer_id=sampled_id,
    )

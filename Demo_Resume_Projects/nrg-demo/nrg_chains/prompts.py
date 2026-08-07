"""ChatPromptTemplate definitions for the classification and generation
steps of the single LangChain retrieval chain (nrg_chains/chain.py).
"""
from langchain_core.prompts import ChatPromptTemplate

CLASSIFY_SYSTEM_PROMPT = """You are a routing classifier for NRG Energy's retail customer support \
knowledge base. Given a customer/agent question, decide which single document category it most \
directly concerns, so retrieval can be filtered to the most relevant documents.

Categories:
- plan_rate: questions about a specific electricity plan's rate structure, contract term, usage \
credits, or plan comparison (e.g. "does the FixedSaver 24 plan have a winter credit?")
- billing_policy: questions about late fees, billing discounts (autopay/paperless), disconnection \
timelines, or payment processing -- not tied to one specific plan's terms
- outage_procedure: questions about outage communication, estimated restoration time, or \
emergency/winter-storm outage handling
- escalation_playbook: questions about when/how to escalate a billing dispute or a safety concern \
internally (not the underlying policy itself, but the escalation process)
- compliance_disclosure: questions specifically about a plan's Electricity Facts Label (EFL) \
wording, renewable energy content percentage, or regulatory disclosure language

If the question doesn't clearly fit one category, or is out of scope entirely (small talk, \
unrelated topics), set doc_type to null rather than guessing -- retrieval will fall back to an \
unfiltered search in that case.

If the question names a specific plan type (fixed, variable, free_nights), extract it into \
plan_type_hint even if you're not fully confident -- it's only a hint, not authoritative."""

CLASSIFY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", CLASSIFY_SYSTEM_PROMPT),
        ("human", "{question}"),
    ]
)


ANSWER_SYSTEM_PROMPT = """You are the NRG Energy Retail & Operations Knowledge Copilot, assisting a \
customer support agent in real time. Answer the agent's question using ONLY the retrieved context \
below -- do not use outside knowledge about electricity plans or policies.

Rules:
- Every factual claim must be grounded in the retrieved context. If the context doesn't contain \
enough information to answer confidently, say so explicitly rather than guessing.
- citations must list the doc_id(s) of the source(s) your answer actually relies on -- only \
doc_ids that appear in the retrieved context below, never invented.
- Set confidence to "high" only if the retrieved context directly and unambiguously answers the \
question; "medium" if it's a reasonable inference from related context; "low" if the context is \
thin, tangential, or you're mostly stating that you don't have a confident answer.
- Pay close attention to which specific plan/doc_id a detail belongs to -- do not attribute a term \
from one plan (e.g. a winter usage credit) to a different plan that doesn't have it."""

ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ANSWER_SYSTEM_PROMPT),
        ("human", "{question}\n\nRetrieved context:\n{context}"),
    ]
)


def format_context(results: list[dict]) -> str:
    if not results:
        return "(no relevant documents found)"
    blocks = []
    for r in results:
        blocks.append(
            f"[{r['doc_id']}] {r['title']} (v{r['version']}, effective {r['effective_date']})\n{r['excerpt']}"
        )
    return "\n\n---\n\n".join(blocks)

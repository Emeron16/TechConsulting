"""Component 3: Policy RAG system.

Retrieval is intentionally simple for this demo: an exact CPT/HCPCS code match against the
synthetic policy knowledge base first (keyword precision, mirroring the "BM25" half of the
PDF's hybrid search), falling back to a BM25 search over policy titles/criteria text using the
diagnosis + clinical notes as the query when no code matches (a stand-in for the "semantic"
half). Production would replace this with the real hybrid BM25 + embedding search and a
cross-encoder reranker over the full InterQual/MCG/CMS/plan-policy corpus described in the
proposal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.config import DATA_DIR, DEFAULT_MODEL, get_client
from core.schemas import ExtractedRequest, PolicyAnalysis

POLICY_KB_DIR = DATA_DIR / "policy_kb"


@dataclass(frozen=True)
class Policy:
    policy_id: str
    title: str
    source: str
    cpt_codes: tuple[str, ...]
    auto_approvable: bool
    low_cost: bool
    required_documentation: tuple[dict, ...]
    criteria: tuple[str, ...]
    notes: str

    @property
    def corpus_text(self) -> str:
        return " ".join([self.title, self.source, *self.criteria])


@lru_cache(maxsize=1)
def load_policies() -> tuple[Policy, ...]:
    policies = []
    for path in sorted(POLICY_KB_DIR.glob("*.json")):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        policies.append(
            Policy(
                policy_id=raw["policy_id"],
                title=raw["title"],
                source=raw["source"],
                cpt_codes=tuple(raw.get("cpt_codes", [])),
                auto_approvable=bool(raw.get("auto_approvable", False)),
                low_cost=bool(raw.get("low_cost", False)),
                required_documentation=tuple(raw.get("required_documentation", [])),
                criteria=tuple(raw.get("criteria", [])),
                notes=raw.get("notes", ""),
            )
        )
    return tuple(policies)


def get_policy(policy_id: str) -> Policy | None:
    for policy in load_policies():
        if policy.policy_id == policy_id:
            return policy
    return None


def match_by_cpt(procedure_codes: list[str]) -> Policy | None:
    codes = {c.strip().upper() for c in procedure_codes}
    for policy in load_policies():
        if codes & {c.upper() for c in policy.cpt_codes}:
            return policy
    return None


def bm25_search(query: str, top_k: int = 1) -> list[Policy]:
    from rank_bm25 import BM25Okapi

    policies = load_policies()
    if not policies:
        return []
    tokenized_corpus = [p.corpus_text.lower().split() for p in policies]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(zip(policies, scores), key=lambda pair: pair[1], reverse=True)
    return [p for p, score in ranked[:top_k] if score > 0]


def retrieve_policy(extracted: ExtractedRequest) -> Policy | None:
    """Exact CPT match first; BM25 fallback over diagnosis + clinical notes."""
    matched = match_by_cpt(extracted.procedure_codes)
    if matched:
        return matched
    query = " ".join(extracted.diagnosis_codes) + " " + extracted.clinical_notes
    results = bm25_search(query, top_k=1)
    return results[0] if results else None


SYSTEM_PROMPT = """You are the clinical policy analysis agent in a prior-authorization \
pipeline. You provide STRUCTURED ANALYSIS ONLY — you never issue a final approval or denial. \
A human nurse reviewer always makes the final call (except for a small set of pre-approved \
low-risk auto-approval cases, which is decided outside of you by a separate routing step).

You will be given the extracted request data and the applicable policy's criteria (with a \
policy ID for citation). Determine:
- Which specific criteria are clearly met by the documentation, and which are unmet or unclear.
- A recommendation: "likely_approve" (criteria clearly met), "needs_review" (mixed/ambiguous \
or minor gaps), or "likely_deny" (criteria clearly not met and no red flags requiring urgent \
override).
- A confidence score (0-1) in that recommendation.
- reviewer_focus_areas: the specific questions a nurse should answer to finalize the decision.
- citations: reference the policy_id and the specific criterion text you relied on.
- risk_flags: anything suggesting fraud, internal contradiction, or a regulatory concern — \
leave empty if none.
- estimated_review_minutes: a realistic nurse review time (5-8 min for clear-cut cases, up to \
20-30 for complex ones), reflecting how much independent judgment is really required.
- patient_summary and request_summary: concise, factual, written for a nurse skimming a queue.

Be conservative: never claim a criterion is met unless the documentation actually supports it.
"""


def _build_user_prompt(extracted: ExtractedRequest, policy: Policy | None) -> str:
    if policy is None:
        policy_block = (
            "No matching policy was found in the knowledge base for this procedure code. "
            "Analyze using general clinical-necessity reasoning, note this gap in risk_flags, "
            "and set citations to an empty list."
        )
    else:
        criteria_block = "\n".join(f"- {c}" for c in policy.criteria)
        policy_block = (
            f"Applicable policy: {policy.policy_id} — {policy.title} (source: {policy.source})\n"
            f"Criteria:\n{criteria_block}"
        )

    return (
        f"Extracted request:\n"
        f"- Patient ID: {extracted.patient_id}\n"
        f"- Diagnosis codes: {', '.join(extracted.diagnosis_codes) or 'none extracted'}\n"
        f"- Procedure codes: {', '.join(extracted.procedure_codes) or 'none extracted'}\n"
        f"- Requesting provider: {extracted.requesting_provider}\n"
        f"- Urgency: {extracted.urgency}\n"
        f"- Clinical notes: {extracted.clinical_notes}\n\n"
        f"{policy_block}"
    )


def analyze(extracted: ExtractedRequest, policy: Policy | None) -> PolicyAnalysis:
    client = get_client()
    completion = client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(extracted, policy)},
        ],
        response_format=PolicyAnalysis,
        temperature=0,
    )
    result = completion.choices[0].message.parsed
    if result is None:
        raise ValueError("Policy analysis failed to parse a structured result from the model.")
    return result

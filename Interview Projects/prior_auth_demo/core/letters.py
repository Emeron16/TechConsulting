"""GPT-4o-mini letter generation: the missing-information letter (Component 2) and the
approval/denial decision letter (Communication Layer)."""
from __future__ import annotations

from core.config import DEFAULT_MODEL, get_client
from core.policy_rag import Policy
from core.schemas import CompletenessResult, ExtractedRequest, PolicyAnalysis

MISSING_INFO_SYSTEM_PROMPT = """You draft missing-information letters for a health plan's \
prior authorization team. Write a short, clear, professional letter to the requesting \
provider's office. For each missing item, state exactly what is needed and reference why \
(the clinical criterion or documentation requirement). Do not invent additional requirements \
beyond what you're given. Keep it under 200 words. Sign off as "Prior Authorization Team, \
[Regional Health Plan — Demo]"."""

DECISION_SYSTEM_PROMPT = """You draft prior-authorization decision letters for a health plan. \
Write a clear, professional letter to the requesting provider stating the decision (approved \
or denied), the request details, and — for approvals — the authorization validity, or — for \
denials — the specific unmet criteria relied upon, plus a standard appeal-rights paragraph \
(providers/members may appeal within 180 days; expedited appeals available for urgent cases). \
Keep it under 220 words. Sign off as "Prior Authorization Team, [Regional Health Plan — Demo]"."""


def generate_missing_info_letter(
    extracted: ExtractedRequest, completeness: CompletenessResult, request_id: str
) -> str:
    client = get_client()
    missing_lines = "\n".join(
        f"- {m.item}: {m.why_needed}" for m in completeness.missing_items
    )
    user_prompt = (
        f"Request ID: {request_id}\n"
        f"Patient ID: {extracted.patient_id}\n"
        f"Requesting provider: {extracted.requesting_provider}\n"
        f"Procedure code(s): {', '.join(extracted.procedure_codes) or 'not specified'}\n\n"
        f"Missing items:\n{missing_lines}"
    )
    completion = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": MISSING_INFO_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    return completion.choices[0].message.content or ""


def generate_decision_letter(
    extracted: ExtractedRequest,
    analysis: PolicyAnalysis,
    policy: Policy | None,
    decision: str,
    request_id: str,
    reviewer: str,
    reviewer_notes: str = "",
) -> str:
    client = get_client()
    unmet_lines = "\n".join(f"- {c}" for c in analysis.unmet_criteria) or "- none"
    user_prompt = (
        f"Request ID: {request_id}\n"
        f"Decision: {decision.upper()}\n"
        f"Reviewer: {reviewer}\n"
        f"Reviewer notes: {reviewer_notes or '(none)'}\n"
        f"Patient ID: {extracted.patient_id}\n"
        f"Requesting provider: {extracted.requesting_provider}\n"
        f"Procedure code(s): {', '.join(extracted.procedure_codes) or 'not specified'}\n"
        f"Diagnosis code(s): {', '.join(extracted.diagnosis_codes) or 'not specified'}\n"
        f"Applicable policy: {policy.policy_id + ' — ' + policy.title if policy else 'none matched'}\n"
        f"Unmet criteria relied upon (for denials):\n{unmet_lines}"
    )
    completion = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    return completion.choices[0].message.content or ""

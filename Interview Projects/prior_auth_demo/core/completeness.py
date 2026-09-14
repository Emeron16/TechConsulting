"""Component 2: Completeness Validator — the highest-ROI piece per the proposal, since it
eliminates the 22% rework rate by catching missing information before a nurse ever sees the
request.

For this demo, completeness is checked two ways, both deterministic (no LLM call needed here):
  1. Baseline structured fields must be present (patient ID, DOB, at least one diagnosis and
     procedure code, provider, clinical notes).
  2. Policy-specific required documentation (per the matched policy's `required_documentation`
     list) is checked via keyword presence in the clinical notes — a lightweight stand-in for
     the clinical NLP a production system would use to confirm a topic is actually documented.
"""
from __future__ import annotations

from core.policy_rag import Policy, retrieve_policy
from core.schemas import CompletenessResult, ExtractedRequest, MissingItem

BASELINE_FIELDS: list[tuple[str, str]] = [
    ("patient_id", "Patient identifier"),
    ("date_of_birth", "Patient date of birth"),
    ("requesting_provider", "Requesting/treating provider name"),
    ("clinical_notes", "Clinical notes / documentation"),
]


def _baseline_missing(extracted: ExtractedRequest) -> list[MissingItem]:
    missing: list[MissingItem] = []
    for field_name, label in BASELINE_FIELDS:
        value = getattr(extracted, field_name, "")
        if not value or not str(value).strip():
            missing.append(
                MissingItem(item=label, why_needed=f"{label} is required on every request.")
            )
    if not extracted.diagnosis_codes:
        missing.append(
            MissingItem(
                item="Diagnosis code (ICD-10)",
                why_needed="At least one diagnosis code is required to establish medical necessity.",
            )
        )
    if not extracted.procedure_codes:
        missing.append(
            MissingItem(
                item="Procedure code (CPT/HCPCS)",
                why_needed="At least one procedure code is required to determine the applicable policy.",
            )
        )
    return missing


def _policy_missing(extracted: ExtractedRequest, policy: Policy | None) -> list[MissingItem]:
    if policy is None:
        return []
    notes_lower = extracted.clinical_notes.lower()
    missing: list[MissingItem] = []
    for requirement in policy.required_documentation:
        keywords = [kw.lower() for kw in requirement.get("keywords", [])]
        if keywords and not any(kw in notes_lower for kw in keywords):
            missing.append(
                MissingItem(
                    item=requirement.get("item", "documentation"),
                    why_needed=requirement.get(
                        "description", f"Required by policy {policy.policy_id}."
                    ),
                )
            )
    return missing


def check(extracted: ExtractedRequest) -> CompletenessResult:
    policy = retrieve_policy(extracted)
    missing = _baseline_missing(extracted) + _policy_missing(extracted, policy)
    return CompletenessResult(
        is_complete=len(missing) == 0,
        missing_items=missing,
        matched_policy_id=policy.policy_id if policy else None,
    )

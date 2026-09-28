"""Component 4: Risk Stratification and Smart Routing.

Implements the proposal's pathway table (page 5-6 of the PDF):
  - Urgent/STAT:      urgency flag present                              -> < 4h,  human review
  - Auto-Approve:     confidence > 95%, all criteria met, low-cost,
                       complete docs, policy pre-approved for auto-approval -> < 1h, NO human review
  - Fast-Track:       clear criteria match, at most one minor open item -> < 8h,  human review (~5 min)
  - Standard Review:  complex clinical judgment required                -> < 24h, full human review

Only the Auto-Approve pathway skips the nurse, and only for policies the CMO has pre-approved
for that tier (`policy.auto_approvable`) — mirroring the PDF's "Auto-approvals only for
pre-defined low-risk criteria reviewed and approved by the CMO."
"""
from __future__ import annotations

from core.policy_rag import Policy
from core.schemas import ExtractedRequest, PolicyAnalysis, RiskRouting

AUTO_APPROVE_CONFIDENCE_THRESHOLD = 0.95
FAST_TRACK_CONFIDENCE_THRESHOLD = 0.75


def route(
    extracted: ExtractedRequest,
    analysis: PolicyAnalysis,
    policy: Policy | None,
) -> RiskRouting:
    if extracted.urgency in ("urgent", "stat"):
        return RiskRouting(
            pathway="urgent",
            sla_hours=4,
            requires_human_review=True,
            reason=f"Document flagged urgency='{extracted.urgency}' — escalated regardless of "
            "other criteria per policy.",
        )

    can_auto_approve = (
        policy is not None
        and policy.auto_approvable
        and policy.low_cost
        and analysis.recommendation == "likely_approve"
        and analysis.confidence >= AUTO_APPROVE_CONFIDENCE_THRESHOLD
        and not analysis.unmet_criteria
        and not analysis.risk_flags
    )
    if can_auto_approve:
        return RiskRouting(
            pathway="auto_approve",
            sla_hours=1,
            requires_human_review=False,
            reason=(
                f"Policy {policy.policy_id} is pre-approved for auto-approval; confidence "
                f"{analysis.confidence:.0%} with all criteria met and no risk flags."
            ),
        )

    if (
        analysis.recommendation in ("likely_approve", "needs_review")
        and analysis.confidence >= FAST_TRACK_CONFIDENCE_THRESHOLD
        and len(analysis.unmet_criteria) <= 1
        and not analysis.risk_flags
    ):
        return RiskRouting(
            pathway="fast_track",
            sla_hours=8,
            requires_human_review=True,
            reason="Clear criteria match with at most one minor open item — priority nurse queue.",
        )

    return RiskRouting(
        pathway="standard_review",
        sla_hours=24,
        requires_human_review=True,
        reason="Complex clinical situation, multiple unmet/unclear criteria, or risk flags "
        "present — requires full nurse judgment.",
    )

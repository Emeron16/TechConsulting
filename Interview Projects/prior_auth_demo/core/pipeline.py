"""Orchestrates the full intake -> completeness -> policy RAG -> routing flow, and persists
every step to the store (requests table + audit log). Shared by the New Request page (first
submission) and the Provider Portal (re-validation after a provider uploads additional docs),
so both paths log identically.
"""
from __future__ import annotations

from dataclasses import dataclass

from core import completeness as completeness_mod
from core import extraction as extraction_mod
from core import letters as letters_mod
from core import policy_rag
from core import routing as routing_mod
from core import store
from core.config import DEFAULT_MODEL
from core.schemas import CompletenessResult, ExtractedRequest, PolicyAnalysis, RiskRouting


@dataclass
class PipelineResult:
    request_id: str
    extracted: ExtractedRequest
    completeness: CompletenessResult
    policy: policy_rag.Policy | None
    analysis: PolicyAnalysis | None
    routing: RiskRouting | None
    status: str
    decision: str | None
    missing_info_letter: str | None
    decision_letter: str | None


def run_pipeline(raw_text: str, source: str, request_id: str | None = None) -> PipelineResult:
    """Run the pipeline on `raw_text`. If `request_id` is given, update that existing request
    (the Provider Portal re-validation loop); otherwise create a new one (fresh submission)."""

    # Step 1: Document Extraction
    extracted = extraction_mod.extract(raw_text)

    # Step 2: Completeness Validation
    completeness = completeness_mod.check(extracted)
    policy = policy_rag.get_policy(completeness.matched_policy_id) if completeness.matched_policy_id else None

    if request_id is None:
        request_id = store.create_request(
            source=source,
            raw_text=raw_text,
            extracted_json=extracted.model_dump_json(),
            completeness_json=completeness.model_dump_json(),
            matched_policy_id=completeness.matched_policy_id,
            status="processing",
        )
    else:
        store.update_request(
            request_id,
            raw_text=raw_text,
            extracted_json=extracted.model_dump_json(),
            completeness_json=completeness.model_dump_json(),
            matched_policy_id=completeness.matched_policy_id,
        )

    store.log_audit(
        request_id=request_id,
        actor="ai",
        component="Document Extraction",
        model=DEFAULT_MODEL,
        summary=f"Extracted {len(extracted.diagnosis_codes)} diagnosis code(s), "
        f"{len(extracted.procedure_codes)} procedure code(s); urgency={extracted.urgency}.",
        confidence=extracted.confidence_score,
        detail=extracted.model_dump(),
    )
    store.log_audit(
        request_id=request_id,
        actor="ai",
        component="Completeness Validator",
        model=None,
        summary=(
            "Complete — proceeding to policy analysis."
            if completeness.is_complete
            else f"Incomplete — {len(completeness.missing_items)} item(s) missing."
        ),
        confidence=None,
        detail=completeness.model_dump(),
    )

    if not completeness.is_complete:
        letter = letters_mod.generate_missing_info_letter(extracted, completeness, request_id)
        store.update_request(
            request_id,
            status="information_requested",
            pathway=None,
            missing_info_letter=letter,
        )
        store.log_audit(
            request_id=request_id,
            actor="ai",
            component="Missing-Information Letter",
            model=DEFAULT_MODEL,
            summary="Generated missing-information letter to requesting provider.",
            confidence=None,
        )
        return PipelineResult(
            request_id=request_id,
            extracted=extracted,
            completeness=completeness,
            policy=policy,
            analysis=None,
            routing=None,
            status="information_requested",
            decision=None,
            missing_info_letter=letter,
            decision_letter=None,
        )

    # Step 3: Policy RAG Analysis
    analysis = policy_rag.analyze(extracted, policy)
    store.update_request(request_id, policy_analysis_json=analysis.model_dump_json())
    store.log_audit(
        request_id=request_id,
        actor="ai",
        component="Policy RAG Analysis",
        model=DEFAULT_MODEL,
        summary=f"Recommendation: {analysis.recommendation} (confidence {analysis.confidence:.0%}); "
        f"{len(analysis.met_criteria)} criteria met, {len(analysis.unmet_criteria)} unmet.",
        confidence=analysis.confidence,
        detail=analysis.model_dump(),
    )

    # Step 4: Risk Stratification & Routing
    risk_routing = routing_mod.route(extracted, analysis, policy)
    store.update_request(
        request_id, routing_json=risk_routing.model_dump_json(), pathway=risk_routing.pathway
    )
    store.log_audit(
        request_id=request_id,
        actor="ai",
        component="Risk Stratification & Routing",
        model=None,
        summary=f"Routed to '{risk_routing.pathway}' (SLA {risk_routing.sla_hours}h). "
        f"{risk_routing.reason}",
        confidence=None,
        detail=risk_routing.model_dump(),
    )

    if risk_routing.pathway == "auto_approve":
        decision_letter = letters_mod.generate_decision_letter(
            extracted, analysis, policy, "approved", request_id, reviewer="AI Auto-Approval"
        )
        store.update_request(
            request_id,
            status="decided",
            decision="approved",
            reviewer="AI Auto-Approval (pre-approved policy tier)",
            decision_letter=decision_letter,
        )
        store.log_audit(
            request_id=request_id,
            actor="ai",
            component="Auto-Approval Decision",
            model=DEFAULT_MODEL,
            summary="Auto-approved under pre-defined low-risk policy tier; no human review.",
            confidence=analysis.confidence,
        )
        status, decision = "decided", "approved"
    else:
        store.update_request(request_id, status="queued_for_review")
        status, decision = "queued_for_review", None
        decision_letter = None

    return PipelineResult(
        request_id=request_id,
        extracted=extracted,
        completeness=completeness,
        policy=policy,
        analysis=analysis,
        routing=risk_routing,
        status=status,
        decision=decision,
        missing_info_letter=None,
        decision_letter=decision_letter,
    )

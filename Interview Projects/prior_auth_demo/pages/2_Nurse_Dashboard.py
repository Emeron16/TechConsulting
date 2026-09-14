import streamlit as st

from core import letters as letters_mod
from core import store
from core.config import require_client_or_stop
from core.policy_rag import get_policy
from core.schemas import CompletenessResult, ExtractedRequest, MissingItem, PolicyAnalysis, RiskRouting

st.set_page_config(page_title="Nurse Dashboard — Prior Auth Demo", page_icon="🩺", layout="wide")
require_client_or_stop()

st.title("🩺 Nurse Review Dashboard")
st.caption(
    "Component 5 of the proposal: the AI pre-summarizes everything so the nurse focuses on "
    "the judgment call, not the paperwork. Human-in-the-loop — every decision here is yours."
)

PATHWAY_PRIORITY = {"urgent": 0, "fast_track": 1, "standard_review": 2}
PATHWAY_LABELS = {
    "urgent": "🔴 Urgent / STAT (< 4h)",
    "fast_track": "🟡 Fast-Track (< 8h)",
    "standard_review": "🔵 Standard Review (< 24h)",
}

reviewer_name = st.sidebar.text_input("Nurse name (for the audit trail)", value=st.session_state.get("reviewer_name", ""))
st.session_state["reviewer_name"] = reviewer_name

queued = store.list_requests(status="queued_for_review")
queued.sort(key=lambda r: (PATHWAY_PRIORITY.get(r["pathway"], 9), r["created_at"]))

if not queued:
    st.info("No requests currently queued for nurse review. Submit one on **New Request** first.")
    st.stop()

st.subheader(f"Queue ({len(queued)} case{'s' if len(queued) != 1 else ''})")
labels = {
    r["id"]: f"{PATHWAY_LABELS.get(r['pathway'], r['pathway'])} — {r['id']} — {r['matched_policy_id'] or 'unmatched policy'}"
    for r in queued
}
selected_id = st.selectbox("Select a case", options=list(labels.keys()), format_func=lambda k: labels[k])
row = next(r for r in queued if r["id"] == selected_id)

extracted = ExtractedRequest.model_validate_json(row["extracted_json"])
analysis = PolicyAnalysis.model_validate_json(row["policy_analysis_json"])
routing = RiskRouting.model_validate_json(row["routing_json"])
policy = get_policy(row["matched_policy_id"]) if row["matched_policy_id"] else None

st.divider()
st.markdown(f"### {row['id']} — {PATHWAY_LABELS.get(routing.pathway, routing.pathway)}")
st.caption(routing.reason)

c1, c2 = st.columns([2, 1])
with c1:
    st.markdown("**Patient summary**")
    st.write(analysis.patient_summary)
    st.markdown("**Request summary**")
    st.write(analysis.request_summary)
    with st.expander("Full clinical notes (as extracted)"):
        st.write(extracted.clinical_notes)
with c2:
    badge = {"likely_approve": "🟢", "needs_review": "🟡", "likely_deny": "🔴"}[analysis.recommendation]
    st.metric("AI recommendation", f"{badge} {analysis.recommendation}")
    st.metric("Confidence", f"{analysis.confidence:.0%}")
    st.metric("Est. review time", f"~{analysis.estimated_review_minutes} min")
    st.caption(f"Policy: {policy.policy_id if policy else 'none matched'}")

c3, c4 = st.columns(2)
with c3:
    st.markdown("**✅ Met criteria**")
    for c in analysis.met_criteria:
        st.write(f"- {c}")
    if not analysis.met_criteria:
        st.caption("None identified.")
with c4:
    st.markdown("**⚠️ Unmet / unclear criteria**")
    for c in analysis.unmet_criteria:
        st.write(f"- {c}")
    if not analysis.unmet_criteria:
        st.caption("None identified.")

if analysis.reviewer_focus_areas:
    st.markdown("**🎯 Reviewer focus areas**")
    for f in analysis.reviewer_focus_areas:
        st.write(f"- {f}")

if analysis.citations:
    st.markdown("**📚 Policy citations**")
    st.caption(" | ".join(analysis.citations))

if analysis.risk_flags:
    st.warning("**Risk flags:** " + "; ".join(analysis.risk_flags))

st.divider()
st.markdown("#### Your decision")

reviewer_notes = st.text_area("Notes (included in the letter and audit log)", key=f"notes_{selected_id}")

col_a, col_b, col_c = st.columns(3)


def _finalize(decision: str) -> None:
    if not reviewer_name.strip():
        st.error("Enter a nurse name in the sidebar before recording a decision.")
        return
    letter = letters_mod.generate_decision_letter(
        extracted, analysis, policy, decision, selected_id, reviewer_name, reviewer_notes
    )
    store.update_request(
        selected_id,
        status="decided",
        decision=decision,
        reviewer=reviewer_name,
        reviewer_notes=reviewer_notes,
        decision_letter=letter,
    )
    store.log_audit(
        request_id=selected_id,
        actor="human",
        component="Nurse Decision",
        model=None,
        summary=f"{reviewer_name} decided '{decision}'. {reviewer_notes or ''}".strip(),
        confidence=None,
        detail={"decision": decision, "reviewer": reviewer_name, "notes": reviewer_notes},
    )
    st.success(f"Recorded: {decision}. Letter generated — visible on Provider Portal.")
    st.rerun()


with col_a:
    if st.button("✅ Approve", use_container_width=True):
        _finalize("approved")
with col_b:
    if st.button("❌ Deny", use_container_width=True):
        _finalize("denied")
with col_c:
    if st.button("✉️ Request more info", use_container_width=True):
        if not reviewer_notes.strip():
            st.error("Describe what's needed in the notes box above before requesting more info.")
        else:
            completeness = CompletenessResult(
                is_complete=False,
                missing_items=[MissingItem(item="Additional information requested by nurse", why_needed=reviewer_notes)],
                matched_policy_id=row["matched_policy_id"],
            )
            letter = letters_mod.generate_missing_info_letter(extracted, completeness, selected_id)
            store.update_request(
                selected_id, status="information_requested", pathway=None, missing_info_letter=letter
            )
            store.log_audit(
                request_id=selected_id,
                actor="human",
                component="Nurse Requested More Info",
                model=None,
                summary=f"{reviewer_name} requested: {reviewer_notes}",
                confidence=None,
            )
            st.success("Sent — request moved back to 'information requested' status.")
            st.rerun()

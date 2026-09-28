from html import escape

import streamlit as st

from core import letters as letters_mod
from core import store
from core.config import require_client_or_stop
from core.policy_rag import get_policy
from core.schemas import CompletenessResult, ExtractedRequest, MissingItem, PolicyAnalysis, RiskRouting

st.set_page_config(page_title="Nurse Dashboard — Prior Auth Demo", page_icon="🩺", layout="wide")
require_client_or_stop()

st.html("""
<style>
.stApp:has(.nd-page) { background: #f4f7f9; }
.stApp:has(.nd-page) [data-testid="stHeader"] { background: #f4f7f9; }
.stApp:has(.nd-page) .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 3rem; }
.stApp:has(.nd-page) [data-testid="stSidebar"] { background: #eaf0f3; border-right: 1px solid #d9e3e8; }
.nd-page { color: #203745; }
.nd-page * { box-sizing: border-box; }
.nd-hero { background: linear-gradient(120deg,#113c49,#176d72); border-radius: 22px; padding: 32px 36px; margin-bottom: 14px; }
.nd-hero .nd-eyebrow { color: #bce5df; text-transform: uppercase; font-size: 12px; font-weight: 700; letter-spacing: .12em; margin: 0 0 12px; }
.nd-hero h1 { color: #fff; font-size: clamp(28px,3vw,38px); letter-spacing: -.03em; line-height: 1.2; margin: 0; padding: 0; }
.nd-hero p { color: #e2f0f0; font-size: 16px; line-height: 1.7; margin: 14px 0 0; max-width: 750px; }
.nd-counts { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; margin-bottom: 16px; }
.nd-count { background: #fff; border: 1px solid #d8e3e8; border-radius: 13px; padding: 17px 20px; }
.nd-count.urgent { background: #fff0ed; border-color: #efd0c7; }
.nd-count.fast { background: #fff8e8; border-color: #e9dfbf; }
.nd-count.standard { background: #edf3fc; border-color: #cfdff2; }
.nd-count p { font-size: 13px; color: #506471; margin: 0 0 8px; }
.nd-count strong { font-size: 29px; color: #203e4b; }
.nd-section { background: #e8f2f4; border-radius: 10px; padding: 15px 19px; margin: 16px 0 8px; }
.nd-section h2 { font-size: 21px; color: #214b59; line-height: 1.4; margin: 0; padding: 0; }
.nd-section p { font-size: 14px; color: #506674; margin: 6px 0 0; }
.nd-section.decision { background: #edf0fa; }
.nd-case { padding: 22px 24px; background: #fff; border: 1px solid #d8e3e8; border-radius: 13px; margin: 14px 0; }
.nd-case h2 { color: #203f4d; font-size: 23px; line-height: 1.4; margin: 10px 0; padding: 0; overflow-wrap: anywhere; }
.nd-case p { color: #546a76; font-size: 14px; line-height: 1.65; margin: 0; }
.nd-path { display: inline-block; background: #e8f1f7; color: #28506b; padding: 5px 10px; border-radius: 6px; font-size: 13px; font-weight: 600; }
.nd-evidence { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; }
.nd-evidence article { padding: 22px; border-radius: 13px; }
.nd-evidence .met { background: #eaf5ef; border: 1px solid #c6dfd2; }
.nd-evidence .unmet { background: #fff6e8; border: 1px solid #ead8b8; }
.nd-evidence h3 { color: #244b52; font-size: 18px; margin: 0 0 12px; padding: 0; }
.nd-evidence li, .nd-evidence p { color: #415862; font-size: 14px; line-height: 1.75; overflow-wrap: anywhere; }
.nd-evidence ul { margin: 0; padding-left: 20px; }
.nd-evidence li + li { margin-top: 8px; }
.nd-recommendation { border: 1px solid #d6e2e8; border-radius: 12px; background: #edf3f7; padding: 18px; margin-bottom: 12px; }
.nd-recommendation p { color: #506674; font-size: 13px; margin: 0 0 8px; }
.nd-recommendation strong { color: #234858; font-size: 23px; line-height: 1.3; }
.stApp:has(.nd-page) [data-testid="stMetric"] { background: #fff; border: 1px solid #d9e4e9; border-radius: 12px; padding: 14px 18px; }
.stApp:has(.nd-page) [data-testid="stMetricValue"] { font-size: 27px; color: #234858; }
.stApp:has(.nd-page) [data-testid="stExpander"] { background: #fff; border-radius: 12px; }
.stApp:has(.nd-page) [data-testid="stExpander"] summary { background: #edf2f6; color: #294958; border-radius: 10px; }
.stApp:has(.nd-page) [data-testid="stTextArea"] textarea { background: #fff; color: #253d49; border-radius: 10px; font-size: 14px; line-height: 1.6; }
.stApp:has(.nd-page) [data-testid="stButton"] button { background: #fff; border: 1px solid #82a2ad; color: #244c59; border-radius: 10px; min-height: 48px; font-weight: 600; }
.stApp:has(.nd-page) [data-testid="stButton"] button:hover { background: #e4f1f0; border-color: #347d7f; }
.stApp:has(.nd-page) button:focus-visible { outline: 3px solid #16818a; outline-offset: 2px; }
@media(max-width: 780px) { .nd-counts { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width: 560px) { .nd-evidence { grid-template-columns: 1fr; } .nd-hero { padding: 24px; } }
</style>
<div class="nd-page nd-hero">
<p class="nd-eyebrow">Clinical review · Synthetic demo</p>
<h1>Nurse Review Dashboard</h1>
<p>Review the evidence. Decide the next step.<br>AI organizes the request and policy findings; you make the review decision.</p>
</div>
""")

PATHWAY_PRIORITY = {"urgent": 0, "fast_track": 1, "standard_review": 2}
PATHWAY_LABELS = {
    "urgent": "🔴 Urgent / STAT (< 4h)",
    "fast_track": "🟡 Fast-Track (< 8h)",
    "standard_review": "🔵 Standard Review (< 24h)",
}

st.sidebar.markdown("### Reviewer workspace")
st.sidebar.caption("Your name identifies your actions in the audit trail.")
reviewer_name = st.sidebar.text_input("Nurse name (for the audit trail)", value=st.session_state.get("reviewer_name", ""))
st.session_state["reviewer_name"] = reviewer_name

queued = store.list_requests(status="queued_for_review")
queued.sort(key=lambda r: (PATHWAY_PRIORITY.get(r["pathway"], 9), r["created_at"]))

counts = {key: sum(r["pathway"] == key for r in queued) for key in PATHWAY_PRIORITY}
st.html(
    '<div class="nd-page nd-counts">'
    f'<div class="nd-count"><p>Awaiting review</p><strong>{len(queued)}</strong></div>'
    f'<div class="nd-count urgent"><p>Urgent / STAT</p><strong>{counts["urgent"]}</strong></div>'
    f'<div class="nd-count fast"><p>Fast-track</p><strong>{counts["fast_track"]}</strong></div>'
    f'<div class="nd-count standard"><p>Standard review</p><strong>{counts["standard_review"]}</strong></div>'
    '</div>'
)
if not queued:
    st.success("The review queue is clear. New requests needing a nurse decision will appear here.")
    st.caption("Use New Request in the sidebar to submit a demo case.")
    st.stop()

st.html('<div class="nd-page nd-section"><h2>Review queue</h2><p>Urgent cases first, then fast-track and standard review. Oldest requests appear first within each pathway.</p></div>')
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

st.html(
    '<section class="nd-page nd-case">'
    f'<span class="nd-path">{escape(PATHWAY_LABELS.get(routing.pathway, routing.pathway))}</span>'
    f'<h2>Request {escape(row["id"])}</h2>'
    f'<p>{escape(routing.reason)}</p></section>'
)

c1, c2 = st.columns([2, 1], gap="large")
with c1:
    with st.container(border=True):
        st.markdown("#### Patient summary")
        st.write(analysis.patient_summary)
        st.markdown("#### Request summary")
        st.write(analysis.request_summary)
        with st.expander("Full clinical notes (as extracted)"):
            st.write(extracted.clinical_notes)
with c2:
    recommendation_labels = {
        "likely_approve": "Likely approve",
        "needs_review": "Needs review",
        "likely_deny": "Likely deny",
    }
    st.html(
        '<div class="nd-page nd-recommendation"><p>AI recommendation</p>'
        f'<strong>{escape(recommendation_labels[analysis.recommendation])}</strong></div>'
    )
    st.metric("AI confidence", f"{analysis.confidence:.0%}")
    st.metric("Estimated review time", f"~{analysis.estimated_review_minutes} min")
    st.caption("Model estimates, not measured accuracy or elapsed time.")
    st.caption(f"Policy: {policy.policy_id if policy else 'none matched'}")

st.html('<div class="nd-page nd-section"><h2>Policy findings</h2><p>Compare the supporting evidence with the items that need attention.</p></div>')

def _criteria_html(items: list[str]) -> str:
    if not items:
        return '<p>None identified.</p>'
    return '<ul>' + ''.join(f'<li>{escape(item)}</li>' for item in items) + '</ul>'

st.html(
    '<div class="nd-page nd-evidence">'
    '<article class="met"><h3>Met criteria</h3>' + _criteria_html(analysis.met_criteria) + '</article>'
    '<article class="unmet"><h3>Unmet / unclear criteria</h3>' + _criteria_html(analysis.unmet_criteria) + '</article>'
    '</div>'
)

if analysis.reviewer_focus_areas:
    with st.container(border=True):
        st.markdown("#### Reviewer focus areas")
        for f in analysis.reviewer_focus_areas:
            st.write(f"- {f}")

if analysis.citations:
    with st.expander("Policy citations", expanded=True):
        for citation in analysis.citations:
            st.write(citation)

if analysis.risk_flags:
    st.warning("**Risk flags:** " + "; ".join(analysis.risk_flags))

st.html('<div class="nd-page nd-section decision"><h2>Your decision</h2><p>Review the evidence, add your notes, and choose the appropriate next step.</p></div>')
reviewer_notes = st.text_area(
    "Notes (included in the letter and audit log)",
    key=f"notes_{selected_id}",
    height=150,
    placeholder="Document your reasoning, or describe exactly what additional information the provider should supply.",
)
st.caption("Enter your nurse name in the sidebar. Notes are required when requesting more information.")
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

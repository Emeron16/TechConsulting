from datetime import datetime, timedelta

import streamlit as st

from core import store
from core.config import require_client_or_stop
from core.pipeline import run_pipeline
from core.schemas import ExtractedRequest, RiskRouting

st.set_page_config(page_title="Request Status — Provider Workspace", page_icon="🌐", layout="wide")
require_client_or_stop()

st.html("""
<style>
.stApp:has(.pp-page), .stApp:has(.pp-page) [data-testid="stHeader"] { background: #f4f7f9; }
.stApp:has(.pp-page) .block-container { max-width: 1100px; padding: 32px; margin-top: 2rem; margin-bottom: 3rem; background: white; border-radius: 20px; box-sizing: border-box; }
.stApp:has(.pp-page) [data-testid="stSidebar"] { background: #eaf0f3; border-right: 1px solid #d9e3e8; }
.pp-hero { background: linear-gradient(120deg, #113c49, #176d72); border-radius: 22px; padding: 32px 36px; margin-bottom: 12px; }
.pp-hero .pp-eyebrow { color: #bce5df; text-transform: uppercase; font-size: 12px; font-weight: 700; letter-spacing: .12em; }
.pp-hero h1 { color: white; font-size: 36px; margin: 0; padding: 0; }
.pp-hero p { color: #e2f0f0; line-height: 1.7; }

.stApp:has(.pp-page) [data-testid="stTextArea"] textarea { background: white; color: #253d49; }
.stApp:has(.pp-page) button[kind="primary"] { background: #176d72; border-color: #176d72; }
@media (max-width: 650px) { .stApp:has(.pp-page) .block-container { padding: 20px; } .pp-hero { padding: 24px; } }
</style>
<div class="pp-page pp-hero">
<p class="pp-eyebrow">Provider workspace · Synthetic demo</p>
<h1>Request Status</h1>
<p>Track submitted requests, respond to information requests, and view decision letters.</p>
</div>
""")
if st.button("Submit a new request", key="portal_new_request"):
    st.switch_page("pages/1_New_Request.py")
st.caption("This demo shows all synthetic requests. Select a request to follow its progress.")

all_requests = store.list_requests()
if not all_requests:
    st.info("No requests submitted yet. Start on **New Request**.")
    st.stop()

options = {r["id"]: f"{r['id']} — {r['status'].replace('_', ' ')}" for r in all_requests}
recent_ids = st.session_state.get("recent_requests") or []
default_id = next((rid for rid in recent_ids if rid in options), next(iter(options)))
request_id = st.selectbox(
    "Request ID",
    options=list(options.keys()),
    index=list(options.keys()).index(default_id) if default_id in options else 0,
    format_func=lambda k: options[k],
)

row = store.get_request(request_id)
extracted = ExtractedRequest.model_validate_json(row["extracted_json"])

STATUS_STEPS = ["submitted", "information_requested", "queued_for_review", "decided"]
STATUS_LABELS = {
    "submitted": "Submitted",
    "information_requested": "Information Requested",
    "queued_for_review": "Under Review",
    "decided": "Decided",
}
current_status = row["status"] if row["status"] in STATUS_STEPS else "submitted"

with st.container(border=True):
    st.subheader(STATUS_LABELS[current_status])
    st.caption({
        "submitted": "Your request has been received.",
        "information_requested": "Action needed: review the letter and provide additional documentation below.",
        "queued_for_review": "Your request is awaiting review by the health plan.",
        "decided": "A decision is available. Read or download the letter below.",
    }[current_status])

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Request details**")
    st.write(f"Patient ID: `{extracted.patient_id}`")
    st.write(f"Procedure code(s): {', '.join(extracted.procedure_codes) or '—'}")
    st.write(f"Diagnosis code(s): {', '.join(extracted.diagnosis_codes) or '—'}")
    st.write(f"Submitted: {row['created_at']}")
with c2:
    st.markdown("**Status**")
    st.write(f"Current status: **{STATUS_LABELS[current_status]}**")
    if row.get("routing_json") and current_status == "queued_for_review":
        routing = RiskRouting.model_validate_json(row["routing_json"])
        st.write(f"Pathway: `{routing.pathway}` — SLA {routing.sla_hours:g}h")
        submitted_at = datetime.fromisoformat(row["created_at"])
        est_decision = submitted_at + timedelta(hours=routing.sla_hours)
        st.write(f"Estimated decision by: {est_decision.strftime('%Y-%m-%d %H:%M UTC')}")

st.divider()

if current_status == "information_requested":
    st.subheader("📨 Missing / additional information requested")
    st.text_area("Letter from the health plan", value=row.get("missing_info_letter") or "", height=180, disabled=True)
    st.markdown("**Provide the requested documentation as text**")
    addition = st.text_area(
        "Additional documentation / clarifying notes from the provider",
        placeholder="e.g. Patient completed 6 weeks of physical therapy and NSAIDs from 3/1/2026 to 4/12/2026 without improvement...",
    )
    if st.button("📤 Submit additional documentation", type="primary", disabled=not addition.strip()):
        combined_text = row["raw_text"] + "\n\nADDITIONAL DOCUMENTATION PROVIDED BY PROVIDER:\n" + addition
        with st.spinner("Re-validating request with the new documentation..."):
            run_pipeline(combined_text, source=row["source"], request_id=request_id)
        st.success("Documentation submitted — request re-validated. Status updated below.")
        st.rerun()

elif current_status == "queued_for_review":
    st.info(
        "This request is complete and is queued for nurse review. Check back, or see the "
        "**Nurse Dashboard** page for the reviewer's view."
    )

elif current_status == "decided":
    st.subheader(f"Decision: {(row.get('decision') or '').upper()}")
    st.write(f"Reviewer: {row.get('reviewer') or '—'}")
    st.text_area("Decision letter", value=row.get("decision_letter") or "", height=220, disabled=True)
    st.download_button(
        "⬇️ Download decision letter",
        data=row.get("decision_letter") or "",
        file_name=f"{request_id}_decision_letter.txt",
        mime="text/plain",
    )
    st.caption("An appeal-submission flow would live here in production — out of scope for this demo.")

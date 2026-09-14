from datetime import datetime, timedelta

import streamlit as st

from core import store
from core.config import require_client_or_stop
from core.pipeline import run_pipeline
from core.schemas import ExtractedRequest, RiskRouting

st.set_page_config(page_title="Provider Portal — Prior Auth Demo", page_icon="🌐", layout="wide")
require_client_or_stop()

st.title("🌐 Provider Portal")
st.caption(
    "Component 6 of the proposal: providers self-serve status instead of calling. Uploading "
    "additional documentation here automatically triggers re-validation — no nurse involved "
    "unless it's still incomplete or ready for review."
)

all_requests = store.list_requests()
if not all_requests:
    st.info("No requests submitted yet. Start on **New Request**.")
    st.stop()

options = {r["id"]: f"{r['id']} — {r['status'].replace('_', ' ')}" for r in all_requests}
default_id = st.session_state.get("recent_requests", [None])[0] or list(options.keys())[0]
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

st.divider()
cols = st.columns(len(STATUS_STEPS))
current_idx = STATUS_STEPS.index(current_status)
for i, (col, step) in enumerate(zip(cols, STATUS_STEPS)):
    marker = "✅" if i < current_idx else ("🟢" if i == current_idx else "⬜")
    col.markdown(f"**{marker} {STATUS_LABELS[step]}**")

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
    if row.get("routing_json"):
        routing = RiskRouting.model_validate_json(row["routing_json"])
        st.write(f"Pathway: `{routing.pathway}` — SLA {routing.sla_hours:g}h")
        submitted_at = datetime.fromisoformat(row["created_at"])
        est_decision = submitted_at + timedelta(hours=routing.sla_hours)
        st.write(f"Estimated decision by: {est_decision.strftime('%Y-%m-%d %H:%M UTC')}")

st.divider()

if current_status == "information_requested":
    st.subheader("📨 Missing / additional information requested")
    st.text_area("Letter from the health plan", value=row.get("missing_info_letter") or "", height=180, disabled=True)
    st.markdown("**Simulate: upload the requested documentation**")
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

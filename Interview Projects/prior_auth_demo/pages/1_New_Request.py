from pathlib import Path

import streamlit as st

from core import ocr
from core.config import DATA_DIR, require_client_or_stop
from core.pipeline import PipelineResult, run_pipeline

st.set_page_config(page_title="New Request — Prior Auth Demo", page_icon="📥", layout="wide")
require_client_or_stop()

SAMPLES_DIR = DATA_DIR / "sample_requests"
SAMPLE_LABELS = {
    "A_pt_eval_auto_approve.txt": "A — Physical therapy eval (expect: Auto-Approve)",
    "B_mri_lumbar_incomplete.txt": "B — Lumbar MRI, missing conservative treatment (expect: Rework / info requested)",
    "C_knee_arthroscopy_fast_track.txt": "C — Knee arthroscopy, minor documentation gap (expect: Fast-Track)",
    "D_bariatric_standard_review.txt": "D — Bariatric surgery, complex case (expect: Standard Review)",
    "E_cta_chest_urgent_stat.txt": "E — CT angiography, STAT (expect: Urgent escalation)",
}

st.title("📥 New Request — Intelligent Document Intake")
st.caption(
    "Component 1 (Intake) through Component 4 (Risk Stratification) of the proposal, run live."
)

if "recent_requests" not in st.session_state:
    st.session_state.recent_requests = []

mode = st.radio(
    "How is this document arriving?",
    ["Sample case", "Paste text", "Upload PDF / image"],
    horizontal=True,
)

raw_text = ""
source = "sample"

if mode == "Sample case":
    source = "sample"
    file_name = st.selectbox(
        "Choose a sample request",
        options=list(SAMPLE_LABELS.keys()),
        format_func=lambda k: SAMPLE_LABELS[k],
    )
    default_text = (SAMPLES_DIR / file_name).read_text(encoding="utf-8")
    raw_text = st.text_area("Document text (editable)", value=default_text, height=320)

elif mode == "Paste text":
    source = "paste"
    raw_text = st.text_area(
        "Paste the raw text of a prior authorization request",
        height=320,
        placeholder="Paste fax/portal/PDF text here...",
    )

else:
    source = "upload"
    uploaded = st.file_uploader("Upload a PDF or image (PNG/JPG)", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded is not None:
        try:
            extracted_text = ocr.extract_text(uploaded.name, uploaded.getvalue())
            raw_text = st.text_area(
                "Extracted text (editable before processing)", value=extracted_text, height=320
            )
        except ocr.OcrUnavailableError as exc:
            st.warning(str(exc))

run_clicked = st.button("▶️ Run Intake Pipeline", type="primary", disabled=not raw_text.strip())


def render_result(result: PipelineResult) -> None:
    st.success(f"Request **{result.request_id}** created.")
    st.session_state.recent_requests.insert(0, result.request_id)
    st.session_state.recent_requests = st.session_state.recent_requests[:8]

    with st.expander("Step 1 — Document Extraction (GPT-4o-mini)", expanded=True):
        e = result.extracted
        c1, c2 = st.columns(2)
        c1.write(f"**Patient ID:** {e.patient_id}")
        c1.write(f"**Date of birth:** {e.date_of_birth}")
        c1.write(f"**Requesting provider:** {e.requesting_provider}")
        c1.write(f"**Ordering NPI:** {e.ordering_npi or '—'}")
        c2.write(f"**Diagnosis codes:** {', '.join(e.diagnosis_codes) or '—'}")
        c2.write(f"**Procedure codes:** {', '.join(e.procedure_codes) or '—'}")
        c2.write(f"**Urgency:** {e.urgency}")
        c2.write(f"**Extraction confidence:** {e.confidence_score:.0%}")
        if e.extraction_notes:
            st.caption(f"Extraction notes: {e.extraction_notes}")
        st.text_area("Clinical notes (as extracted)", value=e.clinical_notes, height=100, disabled=True)

    with st.expander("Step 2 — Completeness Validator", expanded=True):
        comp = result.completeness
        if comp.is_complete:
            st.success("✅ Complete — all baseline and policy-required documentation present.")
        else:
            st.error(f"❌ Incomplete — {len(comp.missing_items)} item(s) missing.")
            for item in comp.missing_items:
                st.write(f"- **{item.item}** — {item.why_needed}")
        if comp.matched_policy_id:
            st.caption(f"Matched policy: `{comp.matched_policy_id}`")

    if result.status == "information_requested":
        st.subheader("📨 Missing-information letter (sent to provider)")
        st.text_area("Letter", value=result.missing_info_letter or "", height=200)
        st.info(
            "Pipeline stopped here — this request will not reach a nurse until the provider "
            "supplies the missing documentation via the **Provider Portal**."
        )
        return

    with st.expander("Step 3 — Policy RAG Analysis (GPT-4o-mini)", expanded=True):
        a = result.analysis
        p = result.policy
        st.write(f"**Matched policy:** {p.policy_id + ' — ' + p.title if p else 'None found — general reasoning used'}")
        badge = {"likely_approve": "🟢", "needs_review": "🟡", "likely_deny": "🔴"}[a.recommendation]
        st.write(f"**AI recommendation:** {badge} `{a.recommendation}` (confidence {a.confidence:.0%})")
        st.write(f"**Patient summary:** {a.patient_summary}")
        st.write(f"**Request summary:** {a.request_summary}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**✅ Met criteria**")
            for c in a.met_criteria:
                st.write(f"- {c}")
        with c2:
            st.markdown("**⚠️ Unmet / unclear criteria**")
            for c in a.unmet_criteria:
                st.write(f"- {c}")
        if a.reviewer_focus_areas:
            st.markdown("**Reviewer focus areas**")
            for f in a.reviewer_focus_areas:
                st.write(f"- {f}")
        if a.citations:
            st.caption("Citations: " + " | ".join(a.citations))
        if a.risk_flags:
            st.warning("Risk flags: " + "; ".join(a.risk_flags))
        st.caption(f"Estimated nurse review time: ~{a.estimated_review_minutes} min")

    with st.expander("Step 4 — Risk Stratification & Routing", expanded=True):
        r = result.routing
        pathway_labels = {
            "auto_approve": "🟢 Auto-Approve",
            "urgent": "🔴 Urgent / STAT",
            "fast_track": "🟡 Fast-Track",
            "standard_review": "🔵 Standard Review",
        }
        st.write(f"**Pathway:** {pathway_labels[r.pathway]}  ·  **SLA:** < {r.sla_hours:g}h  ·  "
                 f"**Human review required:** {'No' if not r.requires_human_review else 'Yes'}")
        st.caption(r.reason)

    if result.status == "decided":
        st.subheader("✅ Auto-approved — decision letter")
        st.text_area("Letter", value=result.decision_letter or "", height=200)
    else:
        st.info(
            f"Queued for nurse review on the **{result.routing.pathway.replace('_', ' ')}** "
            f"pathway. Head to **Nurse Dashboard** to review it, or **Provider Portal** to "
            f"check status by request ID (`{result.request_id}`)."
        )


if run_clicked:
    with st.spinner("Running intake pipeline — extraction, completeness check, policy analysis, routing..."):
        result = run_pipeline(raw_text, source=source)
    render_result(result)

if st.session_state.recent_requests:
    st.sidebar.divider()
    st.sidebar.markdown("**Recent request IDs (this session)**")
    for rid in st.session_state.recent_requests:
        st.sidebar.code(rid)

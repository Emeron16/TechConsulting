from pathlib import Path

import streamlit as st

from core import ocr
from core.config import DATA_DIR, require_client_or_stop
from core.pipeline import PipelineResult, run_pipeline

st.set_page_config(page_title="New Request — Provider Submission", page_icon="📥", layout="wide")
require_client_or_stop()

SAMPLES_DIR = DATA_DIR / "sample_requests"
SAMPLE_LABELS = {
    "A_pt_eval_auto_approve.txt": "A — Physical therapy eval (expect: Auto-Approve)",
    "B_mri_lumbar_incomplete.txt": "B — Lumbar MRI, missing conservative treatment (expect: Rework / info requested)",
    "C_knee_arthroscopy_fast_track.txt": "C — Knee arthroscopy, minor documentation gap (expect: Fast-Track)",
    "D_bariatric_standard_review.txt": "D — Bariatric surgery, complex case (expect: Standard Review)",
    "E_cta_chest_urgent_stat.txt": "E — CT angiography, STAT (expect: Urgent escalation)",
}

st.html("""
<style>
.stApp:has(.nr-page) { background: #f4f7f9; }
.stApp:has(.nr-page) [data-testid="stHeader"] { background: #f4f7f9; }
.stApp:has(.nr-page) .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 3rem; }
.stApp:has(.nr-page) [data-testid="stSidebar"] { background: #eaf0f3; border-right: 1px solid #d9e3e8; }
.nr-page { color: #203745; }
.nr-hero { background: linear-gradient(120deg, #113c49, #176d72); border-radius: 22px; padding: 32px 36px; margin-bottom: 12px; }
.nr-hero .nr-eyebrow { color: #bce5df; text-transform: uppercase; font-size: 12px; font-weight: 700; letter-spacing: .12em; margin: 0 0 12px; }
.nr-hero h1 { color: #fff; font-size: clamp(28px,3vw,38px); letter-spacing: -.03em; line-height: 1.2; margin: 0; padding: 0; }
.nr-hero p { color: #e2f0f0; font-size: 16px; line-height: 1.7; margin: 14px 0 0; max-width: 750px; }
.nr-section { border-radius: 10px; background: #e8f2f4; padding: 15px 19px; margin: 0 0 8px; }
.nr-section h2 { color: #194b59; font-size: 21px; line-height: 1.4; margin: 0; padding: 0; }
.nr-section p { color: #526974; font-size: 14px; margin: 5px 0 0; }
.nr-section.document { background: #edf3fc; }
.nr-section.results { background: #e5f3ec; margin-top: 22px; }
.nr-options { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; margin-bottom: 10px; }
.nr-option { padding: 17px 18px; border: 1px solid #d6e3e8; border-radius: 12px; background: #fff; }
.nr-option.selected { background: #e8f5ef; border-color: #5b9c8a; }
.nr-option h3 { margin: 0 0 8px; padding: 0; font-size: 16px; color: #244e5a; }
.nr-option p { margin: 0; font-size: 13px; line-height: 1.65; color: #4d626e; }
.nr-route { color: #576e79; background: #eaf0f4; padding: 12px 16px; border-radius: 10px; font-size: 13px; line-height: 1.6; margin: 10px 0 4px; }
.stApp:has(.nr-page) [data-testid="stRadio"] label { color: #274b57; }
.stApp:has(.nr-page) [data-testid="stTextArea"] textarea { background: #fff; color: #253d49; border-radius: 10px; font-size: 14px; line-height: 1.65; }
.stApp:has(.nr-page) [data-testid="stFileUploader"] section { background: #edf3fc; border: 1px dashed #809ead; border-radius: 12px; }
.stApp:has(.nr-page) [data-testid="stButton"] button[kind="primary"] { background: #176d72; border-color: #176d72; border-radius: 10px; min-height: 48px; font-weight: 600; }
.stApp:has(.nr-page) [data-testid="stButton"] button[kind="primary"]:hover:not(:disabled) { background: #114f56; border-color: #114f56; }
.stApp:has(.nr-page) [data-testid="stButton"] button[kind="primary"]:disabled { background: #e0e7ea; border-color: #cad6db; color: #647883; }
.stApp:has(.nr-page) [data-testid="stExpander"] { background: #fff; border-radius: 12px; }
.stApp:has(.nr-page) [data-testid="stExpander"] summary { background: #eaf1f5; color: #234858; border-radius: 10px; padding: 14px; }
.stApp:has(.nr-page) button:focus-visible, .stApp:has(.nr-page) textarea:focus-visible { outline: 3px solid #16818a; outline-offset: 2px; }
@media(max-width: 650px) { .nr-options { grid-template-columns: 1fr; } .nr-hero { padding: 24px; } }
</style>
<div class="nr-page nr-hero">
<p class="nr-eyebrow">Provider workspace · Synthetic demo</p>
<h1>New Request — Provider Submission</h1>
<p>Submit a prior authorization request on behalf of a patient.<br>Choose an input, review the document, and run the intake pipeline.</p>
</div>
""")

if st.button("View request status", key="new_request_status"):
    st.switch_page("pages/3_Provider_Portal.py")

if "recent_requests" not in st.session_state:
    st.session_state.recent_requests = []

with st.container(border=True):
    st.html('<div class="nr-page nr-section"><h2>Choose your input</h2><p>Three ways to start the same request workflow.</p></div>')
    mode = st.radio(
        "How is this document arriving?",
        ["Sample case", "Paste text", "Upload PDF / image"],
        horizontal=True,
    )
    descriptions = {
        "Sample case": "Use a ready-made example to quickly demonstrate a scenario and its expected review pathway.",
        "Paste text": "Copy your own request or tweak its details. Skip PDF text extraction and image OCR to isolate document-reading issues.",
        "Upload PDF / image": "Use a document to demonstrate PDF text extraction or image OCR before the request is analyzed.",
    }
    cards = "".join(
        f'<article class="nr-option {"selected" if label == mode else ""}"><h3>{label}</h3><p>{description}</p></article>'
        for label, description in descriptions.items()
    )
    st.html(f'<div class="nr-page nr-options">{cards}</div>')

raw_text = ""
source = "sample"

with st.container(border=True):
    st.html('<div class="nr-page nr-section document"><h2>Prepare the document</h2><p>Review the text before submitting. Use fictional patient information for this demo.</p></div>')
    if mode == "Sample case":
        source = "sample"
        file_name = st.selectbox(
            "Choose a sample request",
            options=list(SAMPLE_LABELS.keys()),
            format_func=lambda k: SAMPLE_LABELS[k],
        )
        default_text = (SAMPLES_DIR / file_name).read_text(encoding="utf-8")
        raw_text = st.text_area("Document text (editable)", value=default_text, height=300)
    elif mode == "Paste text":
        source = "paste"
        raw_text = st.text_area(
            "Paste the raw text of a prior authorization request",
            height=300,
            placeholder="Paste the patient details, provider, diagnosis and procedure codes, and supporting clinical notes...",
        )
    else:
        source = "upload"
        st.caption("Text-based PDFs and PNG/JPG images are supported. Image OCR requires Tesseract; scanned PDFs need a text layer.")
        uploaded = st.file_uploader("Upload a PDF or image (PNG/JPG)", type=["pdf", "png", "jpg", "jpeg"])
        if uploaded is not None:
            try:
                extracted_text = ocr.extract_text(uploaded.name, uploaded.getvalue())
                raw_text = st.text_area(
                    "Extracted text (editable before processing)", value=extracted_text, height=300
                )
            except ocr.OcrUnavailableError as exc:
                st.warning(str(exc))
    st.html('<div class="nr-page nr-route"><strong>All inputs follow the same pipeline:</strong> AI field extraction, completeness checks, policy analysis, and routing.</div>')
    run_clicked = st.button("Run Intake Pipeline", type="primary", disabled=not raw_text.strip(), use_container_width=True)
    if not raw_text.strip():
        st.caption("Add request text or upload a document to begin.")


def render_result(result: PipelineResult) -> None:
    st.html('<div class="nr-page nr-section results"><h2>Request results</h2><p>Review the extracted information, policy findings, and next steps.</p></div>')
    st.success(f"Request **{result.request_id}** created.")
    st.session_state.recent_requests.insert(0, result.request_id)
    st.session_state.recent_requests = st.session_state.recent_requests[:8]

    with st.expander("Step 1 — Document Extraction (Claude Cowork)", expanded=True):
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
        st.subheader("📨 Missing-information letter (available in Provider Portal)")
        st.text_area("Letter", value=result.missing_info_letter or "", height=200)
        st.info(
            "Pipeline stopped here — this request will not reach a nurse until the provider "
            "supplies the missing documentation via the **Provider Portal**."
        )
        return

    with st.expander("Step 3 — Policy RAG Analysis (Claude Cowork)", expanded=True):
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

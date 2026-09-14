import streamlit as st

from core.config import DEFAULT_MODEL, get_client
from core.store import init_db

st.set_page_config(
    page_title="AI-Powered Prior Authorization — Demo",
    page_icon="🩺",
    layout="wide",
)

init_db()


def _api_key_status() -> None:
    st.sidebar.subheader("OpenAI connection")
    try:
        get_client()
        st.sidebar.success(f"Connected — using `{DEFAULT_MODEL}`")
    except Exception as exc:  # noqa: BLE001 - show any config error plainly
        st.sidebar.error(str(exc))


_api_key_status()

st.sidebar.divider()
st.sidebar.markdown(
    "**Pages**\n"
    "1. New Request — run the intake pipeline on a document\n"
    "2. Nurse Dashboard — review queued cases, decide\n"
    "3. Provider Portal — check status, upload more info\n"
    "4. Analytics & Audit — outcomes + audit trail\n"
)
st.sidebar.caption(
    "All patient data, requests, and policy text on this site are synthetic and generated "
    "for this demo — no real PHI or payer policy content is used."
)

st.title("🩺 AI-Powered Prior Authorization")
st.caption("A working demo of the Regional Health Plan Transformation Blueprint — every AI step below runs live on gpt-4o-mini.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Monthly prior auth requests", "15,000")
col2.metric("Current avg turnaround", "4.2 days")
col3.metric("Requests requiring rework", "22%")
col4.metric("AI-augmented target", "2.5 days")

st.info(
    "**The Chief Medical Officer asks:** \"How can AI improve this process while maintaining "
    "clinical quality and regulatory compliance?\" This demo walks through the proposed "
    "architecture end-to-end, using live AI calls at every step — nothing here is pre-scripted."
)

st.subheader("Where the 4.2 days actually go")
st.table(
    {
        "Timeline": ["Day 0", "Day 0–1", "Rework", "Day 1–3", "Day 3–4", "Throughout"],
        "What happens": [
            "Request arrives via fax, PDF, portal, or upload — sits unread in an unstructured queue",
            "Nurse manually identifies request type, checks documentation completeness, routes to reviewer",
            "22% of requests sent back for missing information — clock resets, adding 2-3 days",
            "Clinical review — nurse reads notes, cross-references payer policy guidelines manually",
            "Approval/denial letter generated; provider notified, often by phone",
            "Providers call constantly for status updates, consuming additional nurse time",
        ],
    }
)

st.subheader("Four-layer AI architecture (what this demo implements)")
st.table(
    {
        "Layer": ["Intake", "Intelligence", "Decision Support", "Communication"],
        "Approach": [
            "OCR + Document AI",
            "Multi-Modal RAG + Clinical NLP",
            "Auto-Approval + Nurse Queue",
            "Provider Portal + Notifications",
        ],
        "What it does": [
            "Fax, PDF, portal, or upload → converted to structured data",
            "Completeness check, policy lookup, medical necessity analysis",
            "Risk stratification routes cases to auto-approve or human review",
            "Real-time status, automated letters, missing-info requests",
        ],
        "In this demo": [
            "pdfplumber (PDF) / pytesseract (image) → GPT-4o-mini structured extraction",
            "Rule-based completeness check + BM25 policy retrieval → GPT-4o-mini analysis",
            "Deterministic routing logic over the AI's confidence/recommendation",
            "Streamlit pages: New Request, Nurse Dashboard, Provider Portal",
        ],
    }
)

st.success(
    "**Governance reminder:** AI recommends — humans decide. Only pre-approved, low-risk "
    "policies (see the Nurse Dashboard / routing logic) can be auto-approved; every other case "
    "requires an explicit nurse decision, and every AI inference plus every human decision is "
    "written to an audit log (see **Analytics & Audit**)."
)

st.caption(
    "Start with **1 · New Request** in the sidebar to submit a sample case, paste your own "
    "text, or upload a PDF/image."
)

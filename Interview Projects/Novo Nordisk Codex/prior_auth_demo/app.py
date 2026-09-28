"""Home overview for the synthetic prior authorization demonstration."""
import plotly.graph_objects as go
import streamlit as st

from core.config import DEFAULT_MODEL, get_client
from core.store import init_db

def render_overview() -> None:
    st.set_page_config(page_title="Prior Authorization | Overview", page_icon="🩺", layout="wide")
    init_db()

    st.html("""
    <style>
    .stApp:has(.pa-home) { background: #f4f7f9; }
    .stApp:has(.pa-home) [data-testid="stHeader"] { background: #f4f7f9; }
    .stApp:has(.pa-home) .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 3rem; }
    .stApp:has(.pa-home) [data-testid="stSidebar"] { background: #eaf0f3; border-right: 1px solid #d9e3e8; }
    .stApp:has(.pa-home) [data-testid="stPageLink"] a { background: white; border: 1px solid #d0dfe5; border-radius: 12px; padding: 14px 18px; color: #174b57; font-weight: 600; }
    .stApp:has(.pa-home) [data-testid="stPageLink"] a:hover { background: #e7f4f2; border-color: #398578; }
    .stApp:has(.pa-home) a:focus-visible { outline: 3px solid #007e87; outline-offset: 3px; }
    .pa-home { color: #203745; font-family: inherit; }
    .pa-home * { box-sizing: border-box; }
    .pa-home h1, .pa-home h2, .pa-home h3, .pa-home p { margin: 0; padding: 0; }
    .pa-hero { background: linear-gradient(120deg, #113c49, #176d72); color: #fff; border-radius: 22px; padding: 36px 40px; margin-bottom: 24px; }
    .pa-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 14px !important; }
    .pa-hero .pa-eyebrow { color: #bce5df; }
    .pa-hero h1 { color: #fff; font-size: clamp(28px, 3.4vw, 42px); line-height: 1.18; max-width: 750px; letter-spacing: -.035em; }
    .pa-hero p.pa-lead { color: #e2f0f0; font-size: 17px; line-height: 1.65; max-width: 690px; margin-top: 16px; }
    .pa-hero .pa-disclosure { display: inline-block; margin-top: 22px; border: 1px solid #6b9a9d; border-radius: 6px; padding: 6px 10px; color: #e7f3f2; font-size: 12px; }
    .pa-section-label { color: #566b78; font-size: 13px; margin: 0 0 12px !important; }
    .pa-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 8px; }
    .pa-metric { background: #fff; border: 1px solid #dce5e9; border-radius: 14px; padding: 20px; }
    .pa-metric.target { background: #e2f3ed; border-color: #b5dace; }
    .pa-metric dt { color: #526574; font-size: 13px; line-height: 1.4; min-height: 37px; }
    .pa-metric dd { margin: 8px 0 0; font-weight: 700; font-size: 32px; line-height: 1.15; letter-spacing: -.03em; color: #163f4d; }
    .pa-metric dd span { font-size: 15px; font-weight: 500; letter-spacing: 0; }
    .pa-metric dl { margin: 0; }
    .pa-section { border-radius: 18px; padding: 30px; margin-top: 26px; border: 1px solid #dce5e9; background: #fff; }
    .pa-section h2 { color: #183d49; font-size: 25px; line-height: 1.3; letter-spacing: -.02em; }
    .pa-section .pa-intro { color: #526574; line-height: 1.6; font-size: 15px; margin-top: 8px; }
    .pa-problem { background: #fff8ed; border-color: #eadcc2; }
    .pa-problem .pa-eyebrow { color: #856021; }
    .pa-timeline { list-style: none; margin: 24px 0 0; padding: 0; }
    .pa-timeline li { display: grid; grid-template-columns: 106px minmax(0,1fr); gap: 18px; padding: 13px 0; border-top: 1px solid #e9ddc7; font-size: 14px; line-height: 1.6; }
    .pa-time { color: #78551b; font-weight: 700; }
    .pa-step strong { color: #3f413c; margin-right: 6px; }
    .pa-step { color: #5b615c; }
    .pa-layers { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; margin-top: 24px; }
    .pa-layer { padding: 24px; border-radius: 12px; border: 1px solid transparent; }
    .pa-layer.teal { background: #eaf5f1; border-color: #c8e2d7; }
    .pa-layer.blue { background: #edf3fc; border-color: #d1dff3; }
    .pa-layer.purple { background: #f3effb; border-color: #dfd5f1; }
    .pa-layer.peach { background: #fcf0e9; border-color: #efdbcc; }
    .pa-layer .pa-number { font-size: 12px; font-weight: 700; letter-spacing: .1em; color: #596a74; margin-bottom: 10px; }
    .pa-layer h3 { font-size: 20px; color: #203e4b; line-height: 1.4; }
    .pa-layer p { font-size: 14px; line-height: 1.7; color: #475b68; margin-top: 9px; }
    .pa-layer .pa-result { font-weight: 600; color: #264d59; margin-top: 18px; }
    .pa-governance { background: #e8f1f4; border-color: #cfdee5; display: grid; grid-template-columns: 1fr 1.3fr; gap: 30px; }
    .pa-governance p { color: #455e6a; font-size: 14px; line-height: 1.8; }
    @media (max-width: 850px) { .pa-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); } .pa-governance { grid-template-columns: 1fr; gap: 12px; } }
    @media (max-width: 560px) { .pa-hero, .pa-section { padding: 24px 20px; } .pa-layers { grid-template-columns: 1fr; } .pa-metric { padding: 15px; } .pa-metric dd { font-size: 27px; } .pa-timeline li { grid-template-columns: 1fr; gap: 3px; } }
    </style>
    """)

    st.sidebar.markdown("### Demo workspace")
    st.sidebar.caption("Follow a request from provider submission to review and a decision letter.")
    try:
        get_client()
        st.sidebar.success("AI configuration ready")
    except Exception:
        st.sidebar.warning("AI setup needed before processing requests.")
    st.sidebar.divider()
    st.sidebar.markdown("**Synthetic data only**")
    st.sidebar.caption("Fictional patients and policies. Designed for an interview walkthrough, not clinical use.")

    st.html("""
    <div class="pa-home">
      <header class="pa-hero">
        <p class="pa-eyebrow">Regional health plan · Interactive demo</p>
        <h1>AI-powered<br>prior authorization</h1>
        <p class="pa-lead">Less paperwork. More time for clinical review.<br>Explore how a provider request moves through intake, policy analysis, and a decision.</p>
        <span class="pa-disclosure">Synthetic cases and policies</span>
      </header>
      <p class="pa-section-label">The business case · Illustrative baseline and proposed target, not measured demo results</p>
      <div class="pa-metrics">
        <div class="pa-metric"><dl><dt>Requests per month</dt><dd>15,000</dd></dl></div>
        <div class="pa-metric"><dl><dt>Current turnaround</dt><dd>4.2 <span>days</span></dd></dl></div>
        <div class="pa-metric"><dl><dt>Requests needing rework</dt><dd>22<span>%</span></dd></dl></div>
        <div class="pa-metric target"><dl><dt>Proposed turnaround</dt><dd>2.5 <span>days</span></dd></dl></div>
      </div>
    </div>
    """)

    left, right = st.columns(2)
    with left:
        st.page_link(request_page, label="Start a provider request", icon="📄", use_container_width=True)
    with right:
        st.page_link(nurse_page, label="Open the nurse dashboard", icon="🩺", use_container_width=True)

    st.html("""
    <div class="pa-home">
      <section class="pa-section pa-problem" aria-labelledby="problem-title">
        <p class="pa-eyebrow">The challenge</p>
        <h2 id="problem-title">Where the waiting happens</h2>
        <p class="pa-intro">In the proposed scenario, manual handoffs and missing information stretch the process across several days.</p>
        <ol class="pa-timeline">
          <li><span class="pa-time">Day 0</span><span class="pa-step"><strong>Documents arrive.</strong> Requests wait in an unstructured intake queue.</span></li>
          <li><span class="pa-time">Day 0–1</span><span class="pa-step"><strong>Manual triage.</strong> A nurse checks documentation and routes the request.</span></li>
          <li><span class="pa-time">Rework</span><span class="pa-step"><strong>Information is missing.</strong> Requests go back to the provider, adding time and repeat work.</span></li>
          <li><span class="pa-time">Day 1–3</span><span class="pa-step"><strong>Clinical review.</strong> Notes and coverage criteria are compared manually.</span></li>
          <li><span class="pa-time">Day 3–4</span><span class="pa-step"><strong>Decision communication.</strong> A letter is prepared and the provider is notified.</span></li>
          <li><span class="pa-time">Throughout</span><span class="pa-step"><strong>Status calls.</strong> Providers follow up while nurses manage the queue.</span></li>
        </ol>
      </section>
      <section class="pa-section" aria-labelledby="workflow-title">
        <p class="pa-eyebrow" style="color:#476776">The demo workflow</p>
        <h2 id="workflow-title">Four layers, one request</h2>
        <p class="pa-intro">Each layer prepares the information needed for the next step.</p>
        <div class="pa-layers">
          <article class="pa-layer teal"><div class="pa-number">01 / INTAKE</div><h3>Turn documents into information</h3><p>Choose a sample, paste text, or upload a PDF or image. Extract patient details, procedure codes, and clinical notes.</p><p class="pa-result">Output: a structured request</p></article>
          <article class="pa-layer blue"><div class="pa-number">02 / INTELLIGENCE</div><h3>Check the right requirements</h3><p>Check for missing information, find a matching synthetic policy, and compare the documented case with its criteria.</p><p class="pa-result">Output: missing items or a policy analysis</p></article>
          <article class="pa-layer purple"><div class="pa-number">03 / DECISION SUPPORT</div><h3>Focus the review</h3><p>Route complete requests to an eligible low-risk approval path or a nurse queue, with summaries, criteria, and risk flags.</p><p class="pa-result">Output: an approval or a review pathway</p></article>
          <article class="pa-layer peach"><div class="pa-number">04 / COMMUNICATION</div><h3>Make the next step clear</h3><p>Providers check status, view letters, and submit additional notes. Updated requests return to the same review pipeline.</p><p class="pa-result">Output: status and actionable next steps</p></article>
        </div>
      </section>
      <section class="pa-section pa-governance" aria-labelledby="review-title">
        <div><p class="pa-eyebrow" style="color:#476776">Human oversight</p><h2 id="review-title">Clinical judgment stays central</h2></div>
        <p>Only eligible low-risk cases can be automatically approved. Other complete requests go to a nurse for review. Incomplete requests return for more information. Processing events and decisions appear in the audit trail.</p>
      </section>
    </div>
    """)

    st.html('<div class="pa-section"><h2>Proposal targets</h2><p>Illustrative baseline assumptions and proposed targets from the blueprint. Validate these goals in a pilot; no delivery date or measured improvement is implied.</p></div>')

    STAGES = ["Illustrative<br>baseline", "Proposed<br>target"]
    # Consistent colors distinguish baseline assumptions from proposed targets.
    COMPARISON_COLORS = ["#90a8bc", "#176d72"]


    def target_bar(title: str, values: list[float], suffix: str = "") -> go.Figure:
        fig = go.Figure(
            go.Bar(
                x=STAGES,
                y=values,
                marker_color=COMPARISON_COLORS,
                text=[f"{v:g}{suffix}" for v in values],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=title,
            template="plotly_white",
            showlegend=False,
            margin=dict(t=64, b=64, l=40, r=20),
            height=350,
            font=dict(color="#294653", size=12),
            title_font_size=16,
            paper_bgcolor="#f8fafc",
            plot_bgcolor="#f8fafc",
            yaxis=dict(showgrid=True, gridcolor="#e1e8ed", zeroline=False, range=[0, max(values) * 1.25], ticksuffix=suffix),
            xaxis=dict(showgrid=False, tickfont=dict(size=11), fixedrange=True),
        )
        return fig


    c1, c2, c3 = st.columns(3)
    with c1:
        st.plotly_chart(target_bar("Turnaround time (days)", [4.2, 2.5]), use_container_width=True)
    with c2:
        st.plotly_chart(target_bar("Rework rate", [22, 5], suffix="%"), use_container_width=True)
    with c3:
        st.plotly_chart(target_bar("Auto-approved", [0, 35], suffix="%"), use_container_width=True)

    st.caption(
        "Source: proposal blueprint, pages 9–10. Figures are assumptions and goals, not measured results. "
        "The unsupported intermediate phase estimates have been removed."
    )


    st.info(
        "How we would validate the targets: pilot the complete workflow with a small provider group, "
        "measure end-to-end turnaround and rework, then expand based on observed results. "
        "Earlier missing-information checks, less manual document review, and faster routing may reduce delays. "
        "Provider response times and nurse queues still affect turnaround; automation does not guarantee these targets within three months."
    )

    with st.expander("How this demo is implemented"):
        st.markdown(
            "- **Intake:** PDF text extraction and Tesseract image OCR, followed by AI field extraction.\n"
            "- **Intelligence:** rule-based completeness checks and procedure-code matching with BM25 fallback over six synthetic policies.\n"
            "- **Decision support:** routing rules use the policy, AI recommendation, confidence, and risk flags.\n"
            "- **Communication:** local provider portal, generated letters, and audit records. External notifications and appeals are not implemented."
        )
        st.caption(f"AI model: {DEFAULT_MODEL}. A configured key is not a verified live connection.")


request_page = st.Page("pages/1_New_Request.py", title="New Request", url_path="New_Request")
nurse_page = st.Page("pages/2_Nurse_Dashboard.py", title="Nurse Dashboard", url_path="Nurse_Dashboard")

navigation = st.navigation(
    {
        "Overview": [st.Page(render_overview, title="App Overview", default=True)],
        "Provider Workspace": [
            request_page,
            st.Page("pages/3_Provider_Portal.py", title="Request Status", url_path="Provider_Portal"),
        ],
        "Health Plan Workspace": [
            nurse_page,
            st.Page("pages/4_Analytics_Audit.py", title="Analytics Audit", url_path="Analytics_Audit"),
        ],
    }
)
navigation.run()

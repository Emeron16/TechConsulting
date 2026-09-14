import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store
from core.config import require_client_or_stop

st.set_page_config(page_title="Analytics & Audit — Prior Auth Demo", page_icon="📊", layout="wide")
require_client_or_stop()

st.title("📊 Analytics & Audit")
st.caption(
    "The proposal's projected outcomes (static, from the blueprint) alongside this session's "
    "live activity, plus the immutable audit trail required for clinical governance."
)

# ---------------------------------------------------------------------------
# 1. Proposal's projected outcomes — static reference, NOT live data.
#    One metric per chart (single axis each) since turnaround (days), rework (%),
#    and auto-approval (%) are different units — never combined on one scale.
# ---------------------------------------------------------------------------
st.subheader("Proposal's projected outcomes (Blueprint, pages 9-10 — not live data)")

STAGES = ["Current", "Phase 1\n(mo. 1-3)", "Phase 2\n(mo. 4-6)", "Phase 3\n(mo. 7-9)"]
# Ordinal sequential-blue ramp, darkening with each phase (per dataviz skill's ordinal-ramp rule).
ORDINAL_BLUES = ["#86b6ef", "#5598e7", "#2a78d6", "#184f95"]


def ordinal_bar(title: str, values: list[float], suffix: str = "") -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=STAGES,
            y=values,
            marker_color=ORDINAL_BLUES,
            text=[f"{v:g}{suffix}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        showlegend=False,
        margin=dict(t=48, b=8, l=8, r=8),
        height=280,
        yaxis=dict(showgrid=True, gridcolor="#e1e0d9", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    return fig


c1, c2, c3 = st.columns(3)
with c1:
    st.plotly_chart(ordinal_bar("Turnaround time (days)", [4.2, 2.7, 2.2, 2.5]), use_container_width=True)
with c2:
    st.plotly_chart(ordinal_bar("Rework rate", [22, 12, 8, 5], suffix="%"), use_container_width=True)
with c3:
    st.plotly_chart(ordinal_bar("Auto-approved", [0, 0, 15, 35], suffix="%"), use_container_width=True)

st.caption(
    "Source: proposal blueprint. This demo implements the architecture; it does not have "
    "9 months of production volume to reproduce these figures live."
)

st.divider()

# ---------------------------------------------------------------------------
# 2. Live session metrics — from this session's actual pipeline runs.
# ---------------------------------------------------------------------------
st.subheader("This session's activity (live)")

requests = store.list_requests()
if not requests:
    st.info("No requests processed yet this session. Submit one on **New Request**.")
else:
    df = pd.DataFrame(requests)
    total = len(df)
    rework_rate = (df["status"].eq("information_requested")).mean() * 100
    decided = df[df["status"] == "decided"]
    auto_approved = df["pathway"].eq("auto_approve").sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Requests processed", total)
    m2.metric("Rework rate (this session)", f"{rework_rate:.0f}%")
    m3.metric("Auto-approved", auto_approved)
    m4.metric("Decided by a nurse", len(decided) - auto_approved if len(decided) else 0)

    STATUS_COLORS = {
        "auto_approve": "#0ca30c",   # good
        "urgent": "#d03b3b",         # critical
        "fast_track": "#fab219",     # warning
        "standard_review": "#2a78d6",  # categorical blue (neutral identity)
        "information_requested": "#898781",  # muted
    }
    pathway_counts = (
        df.assign(pathway=df["pathway"].fillna("information_requested"))
        .groupby("pathway")
        .size()
        .reindex(list(STATUS_COLORS.keys()))
        .fillna(0)
    )
    fig = go.Figure(
        go.Bar(
            x=[p.replace("_", " ") for p in pathway_counts.index],
            y=pathway_counts.values,
            marker_color=[STATUS_COLORS[p] for p in pathway_counts.index],
            text=[int(v) for v in pathway_counts.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Requests by pathway",
        template="plotly_white",
        showlegend=False,
        margin=dict(t=48, b=8, l=8, r=8),
        height=320,
        yaxis=dict(showgrid=True, gridcolor="#e1e0d9", zeroline=False, title="Count"),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# 3. Audit trail — every AI inference + every human decision.
# ---------------------------------------------------------------------------
st.subheader("Audit trail")
st.caption(
    "Every AI inference (model, confidence, output summary) and every human decision, "
    "append-only — the proposal's 'Complete Audit Trail' governance control."
)

filter_id = st.selectbox(
    "Filter by request ID",
    options=["(all)"] + [r["id"] for r in requests],
)
audit_rows = store.list_audit(request_id=None if filter_id == "(all)" else filter_id)

if not audit_rows:
    st.info("No audit entries yet.")
else:
    audit_df = pd.DataFrame(audit_rows)[
        ["timestamp", "request_id", "actor", "component", "model", "summary", "confidence"]
    ]
    st.dataframe(audit_df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download audit log (CSV)",
        data=audit_df.to_csv(index=False),
        file_name="prior_auth_audit_log.csv",
        mime="text/csv",
    )

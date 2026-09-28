import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store
from core.config import require_client_or_stop

st.set_page_config(page_title="Analytics & Audit — Prior Auth Demo", page_icon="📊", layout="wide")
require_client_or_stop()

st.html("""
<style>
.stApp:has(.aa-page), .stApp:has(.aa-page) [data-testid="stHeader"] { background: #f4f7f9; }
.stApp:has(.aa-page) .block-container { max-width: 1300px; padding: 32px; margin-top: 2rem; margin-bottom: 3rem; background: white; border-radius: 20px; box-sizing: border-box; }
.stApp:has(.aa-page) [data-testid="stSidebar"] { background: #eaf0f3; border-right: 1px solid #d9e3e8; }
.aa-hero { background: linear-gradient(120deg, #113c49, #176d72); border-radius: 20px; padding: 30px 34px; margin-bottom: 16px; }
.aa-hero .eyebrow { color: #bce5df; text-transform: uppercase; font-size: 12px; font-weight: 700; letter-spacing: .12em; }
.aa-hero h1 { color: white; font-size: 36px; margin: 0; padding: 0; }
.aa-hero p { color: #e2f0f0; line-height: 1.7; }
.aa-section { padding: 18px 22px; border-radius: 12px; background: #edf3fc; margin: 12px 0; }
.aa-section.live { background: #e6f3ee; }
.aa-section.audit { background: #fff3dd; }
.aa-section h2 { color: #234b59; font-size: 23px; margin: 0; padding: 0; }
.aa-section p { color: #506571; margin: 8px 0 0; font-size: 14px; }
.stApp:has(.aa-page) [data-testid="stMetric"] { background: #edf6f4; border: 1px solid #d8e8e3; border-radius: 12px; padding: 16px; }
@media(max-width: 650px) { .stApp:has(.aa-page) .block-container { padding: 18px; } .aa-hero { padding: 22px; } }
</style>
<div class="aa-page aa-hero"><p class="eyebrow">Health plan workspace · Synthetic demo</p>
<h1>Analytics &amp; Audit</h1><p>Monitor saved demo request activity and review recorded processing events.</p></div>
""")

if st.session_state.pop("demo_reset_complete", False):
    st.success("Demo reset complete. Requests and audit entries were cleared; a database backup was saved.")

with st.expander("Start a fresh demo"):
    st.write("Clear all saved requests and audit entries across the demo. Sample documents and policies remain available. A database backup is saved before clearing.")
    confirmed = st.checkbox("Clear all demo requests and audit history", key="confirm_demo_reset")
    if st.button("Reset demo data", disabled=not confirmed, key="reset_demo_data"):
        try:
            store.reset_demo_data()
        except Exception:
            st.error("Reset failed. No reset was confirmed. Check database access and try again.")
        else:
            for key in list(st.session_state):
                del st.session_state[key]
            st.session_state["demo_reset_complete"] = True
            st.rerun()

# ---------------------------------------------------------------------------
# 2. Live session metrics — from this session's actual pipeline runs.
# ---------------------------------------------------------------------------
st.html('<div class="aa-section live"><h2>Demo request activity</h2><p>Current counts from requests saved in the demo database.</p></div>')

requests = store.list_requests()
if not requests:
    st.info("No requests processed yet. Submit one on **New Request**.")
else:
    df = pd.DataFrame(requests)
    total = len(df)
    rework_rate = (df["status"].eq("information_requested")).mean() * 100
    decided = df[df["status"] == "decided"]
    auto_approved = df["pathway"].eq("auto_approve").sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Requests processed", total)
    m2.metric("Awaiting information", f"{rework_rate:.0f}%")
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
        margin=dict(t=64, b=64, l=50, r=24),
        height=380,
        font=dict(color="#294653", size=13),
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#f8fafc",
        yaxis=dict(showgrid=True, gridcolor="#e1e8ed", zeroline=False, title="Requests", dtick=1, range=[0, max(1, pathway_counts.max()) * 1.3]),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# 3. Audit trail — every AI inference + every human decision.
# ---------------------------------------------------------------------------
st.html('<div class="aa-section audit"><h2>Audit trail</h2><p>Review recorded AI processing and human decisions. Filter by request or export the log.</p></div>')

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

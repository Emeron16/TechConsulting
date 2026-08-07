"""Top-level multi-demo shell -- a left-sidebar switch between the
Novartis CMC Quality Copilot and the NRG Energy Knowledge Copilot, both of
which remain fully independent codebases (copilot-demo/, nrg-demo/) that
this shell is the ONLY thing that touches both of.

Cross-repo import mechanism: novartis_wrapper.py and nrg_wrapper.py each do
their own sys.path.insert() pointed at their respective demo's root and
their own load_dotenv() pointed at that demo's .env -- the same
sys.path-hacking trick each demo's own scripts/servers already use
internally (see e.g. copilot-demo/scripts/ask.py's
`sys.path.insert(0, str(Path(__file__).parent.parent))`), just pointed
cross-repo from here instead of within one repo.

The import happens INSIDE the selected branch below, not at module top --
this guarantees only one demo's modules and sys.path entry are ever loaded
per script run, which is what actually enforces "NRG never imports from
copilot_agents/mcp_servers, and vice versa" at the code level rather than
just by convention (see NRG_Implementation_Plan.md Phase 9's verification:
`grep -r "copilot_agents\\|mcp_servers" nrg-demo/` and
`grep -r "nrg_chains\\|nrg_retrieval" copilot-demo/` both return zero hits).

Run with: streamlit run shell_app.py
"""
import streamlit as st

st.set_page_config(page_title="AI Copilot Demos", layout="wide")

demo = st.sidebar.radio(
    "Demo",
    ["Novartis CMC Quality Copilot", "NRG Energy Knowledge Copilot"],
    key="shell_demo_selector",
)

if demo.startswith("Novartis"):
    from novartis_wrapper import render_novartis

    render_novartis()
else:
    from nrg_wrapper import render_nrg

    render_nrg()

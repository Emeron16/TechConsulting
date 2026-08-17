"""Top-level multi-demo shell -- a left-sidebar switch between the
Novartis CMC Quality Copilot, the NRG Energy Knowledge Copilot, and the
Volvo Dealer Service & Warranty Intelligence Platform, all three of which
remain fully independent codebases (copilot-demo/, nrg-demo/, volvo-demo/)
that this shell is the ONLY thing that touches all of.

Cross-repo import mechanism: novartis_wrapper.py, nrg_wrapper.py, and
volvo_wrapper.py each do their own sys.path.insert() pointed at their
respective demo's root and their own load_dotenv() pointed at that demo's
.env -- the same sys.path-hacking trick each demo's own scripts/servers
already use internally (see e.g. copilot-demo/scripts/ask.py's
`sys.path.insert(0, str(Path(__file__).parent.parent))`), just pointed
cross-repo from here instead of within one repo.

The import happens INSIDE the selected branch below, not at module top --
this guarantees only one demo's modules and sys.path entry are ever loaded
per script run, which is what actually enforces "NRG never imports from
copilot_agents/mcp_servers, Volvo never imports from either, and vice
versa" at the code level rather than just by convention (see
NRG_Implementation_Plan.md Phase 9's verification, extended to a three-way
check in Volvo_Implementation_Plan.md Phase 12).

Volvo is the only demo with additional runtime prerequisites beyond
Postgres/OpenSearch containers: the FastAPI serving layer (port 8100) and
the Airflow stack (port 8180) must already be running for its Submit New
Case tab to work -- see volvo-demo/volvo_app.py's docstring.

Run with: streamlit run shell_app.py
"""
import streamlit as st

st.set_page_config(page_title="AI Copilot Demos", layout="wide")

demo = st.sidebar.radio(
    "Demo",
    [
        "Novartis CMC Quality Copilot",
        "NRG Energy Knowledge Copilot",
        "Volvo Dealer Service & Warranty Intelligence",
    ],
    key="shell_demo_selector",
)

if demo.startswith("Novartis"):
    from novartis_wrapper import render_novartis

    render_novartis()
elif demo.startswith("NRG"):
    from nrg_wrapper import render_nrg

    render_nrg()
else:
    from volvo_wrapper import render_volvo

    render_volvo()

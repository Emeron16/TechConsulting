"""Standalone Streamlit entrypoint for the NRG Energy Knowledge Copilot --
the closest free/local analog to the original architecture's "Copilot
Widget" layer.

Built as a thin set_page_config() + render() wrapper from the start (see
nrg_app_render.py), so shell/nrg_wrapper.py can call render() directly
without a duplicate set_page_config() call or 400+ lines of duplicated tab
logic -- no later extraction needed, unlike copilot-demo/streamlit_app.py
(see NRG_Implementation_Plan.md Phase 9).

Run with: streamlit run nrg_app.py
"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(page_title="NRG Energy Knowledge Copilot (Local Demo)", layout="wide")

from nrg_app_render import render

render()

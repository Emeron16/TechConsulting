"""Streamlit UI -- the closest free/local analog to the original
architecture's "Copilot Web UI" layer (chat + citation panel + review
queue). Thin wrapper: st.set_page_config() + render(). All actual tab
logic lives in streamlit_app_render.py (extracted here in Phase 9 of
../NRG_Implementation_Plan.md so the shared multi-demo shell,
../shell/shell_app.py, can call render() directly without duplicating
this file's logic or triggering a second st.set_page_config() call).

Run with: streamlit run streamlit_app.py
"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(page_title="CMC Quality Copilot (Local Demo)", layout="wide")

from streamlit_app_render import render

render()

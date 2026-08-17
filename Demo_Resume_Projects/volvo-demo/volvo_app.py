"""Standalone Streamlit entrypoint for the Volvo BERT Dealer Service and
Warranty Intelligence Platform demo.

Built as a thin set_page_config() + render() wrapper from the start (see
volvo_app_render.py), matching nrg-demo's from-day-one pattern -- no later
extraction needed, unlike copilot-demo's original streamlit_app.py.

Run with: streamlit run volvo_app.py

Prerequisites (more moving parts than the other two demos): Postgres +
OpenSearch (`docker compose up -d`), the FastAPI serving layer
(`uvicorn api.main:app --port 8100`), and the Airflow stack
(`docker compose -f airflow/docker-compose.airflow.yml up -d`) must all
already be running -- Submit New Case genuinely depends on all three.
"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(page_title="Volvo Dealer Service & Warranty Intelligence (Local Demo)", layout="wide")

from volvo_app_render import render

render()

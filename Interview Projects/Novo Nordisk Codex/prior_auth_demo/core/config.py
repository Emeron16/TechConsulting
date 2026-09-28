"""
Environment / OpenAI client setup.

This demo intentionally uses a single small model (gpt-4o-mini) for every AI step
(extraction, policy analysis, letter generation) to keep it cheap and fast to run live.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "demo.db"

# Load .env from the project root (no-op if the file doesn't exist).
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = os.getenv("PRIOR_AUTH_MODEL", "gpt-4o-mini")


class MissingApiKeyError(RuntimeError):
    """Raised when OPENAI_API_KEY isn't set, so pages can show a friendly message."""


@lru_cache(maxsize=1)
def get_client():
    """Return a cached OpenAI client, or raise MissingApiKeyError with a helpful message."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Copy `.env.example` to `.env` in the "
            "prior_auth_demo folder and paste your OpenAI API key into it, then "
            "restart the app."
        )
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def require_client_or_stop():
    """Convenience for pages: shows a Streamlit error + stops if no API key is configured."""
    import streamlit as st

    try:
        return get_client()
    except MissingApiKeyError as exc:
        st.error(str(exc))
        st.stop()

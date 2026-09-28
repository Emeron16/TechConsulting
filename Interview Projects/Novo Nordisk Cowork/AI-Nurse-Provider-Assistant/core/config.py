"""Local Cowork adapter. No OpenAI or Anthropic API credentials are used."""
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlencode
from html import escape
PROJECT_ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=PROJECT_ROOT/'data'
DB_PATH=DATA_DIR/'demo.db'
DEFAULT_MODEL='Claude Cowork (active session)'
class MissingApiKeyError(RuntimeError): pass
@lru_cache(maxsize=1)
def get_client():
    from core.cowork_bridge import CoworkClient
    return CoworkClient()
def require_client_or_stop():
    import streamlit as st
    from core.cowork_bridge import session_status
    state=session_status()
    if not state['active']:
        st.sidebar.warning('Cowork session offline. Start the full-app session skill before processing.')
        launch_url = 'claude://cowork/new?' + urlencode({
            'q': 'Run the run-full-app-session skill for this synthetic prior authorization demo. The skill is in skills/run-full-app-session/SKILL.md in the attached folder.',
            'folder': str(PROJECT_ROOT),
        })
        st.sidebar.markdown(
            '<a href="' + escape(launch_url, quote=True) + '" target="_self" '
            'style="display:block;padding:0.7rem 1rem;border-radius:8px;'
            'background:#087f8c;color:white;text-align:center;text-decoration:none;'
            'font-weight:600">Open session in Cowork</a>',
            unsafe_allow_html=True,
        )
        st.sidebar.caption('Confirm the demo folder in Claude, then press Send on the prefilled request. Return here after processing connects. Each session lasts up to 15 minutes.')
    else: st.sidebar.success('Cowork session connected')
    st.sidebar.caption('Synthetic demo · Live AI processing in Cowork')
    return get_client()

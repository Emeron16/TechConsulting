"""Thin wrapper that imports and calls copilot-demo's own render() --
copilot-demo's tab logic is not duplicated here, only invoked. Does its
own sys.path insert + load_dotenv pointed at copilot-demo/'s root, exactly
mirroring the pattern copilot-demo's own internal scripts/servers already
use for themselves (see e.g. scripts/ask.py), just pointed cross-repo from
the shell instead of within copilot-demo itself.

load_dotenv(override=True) is called INSIDE render_novartis(), not at
module scope, and is re-run on every call -- both demos' .env files use
identical variable names (POSTGRES_PORT, POSTGRES_USER, RABBITMQ_*, etc.,
each demo having no reason to know the other exists), so simply setting
override=True at module scope was not sufficient: Python caches imported
modules in sys.modules, so a module-scope load_dotenv() call only actually
executes once per process, on the very first `from novartis_wrapper import
render_novartis` -- switching demo -> demo -> demo again in one shell
session would silently keep querying whichever demo's Postgres/RabbitMQ/
Qdrant connection info was loaded first. Found and fixed during Phase 9
verification (surfaced as a genuinely confusing "relation does not exist"
error on the *second* switch back to a demo, not the first switch away
from it).
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

COPILOT_DEMO_ROOT = Path(__file__).parent.parent / "copilot-demo"
sys.path.insert(0, str(COPILOT_DEMO_ROOT))

# The import itself is still safe to do once at module scope (sys.modules
# caching is exactly what we want for the render function object -- it's
# only the *environment variable* freshness that needs to happen on every
# call, not the import).
from streamlit_app_render import render as _render  # noqa: E402 -- must follow sys.path insert


def render_novartis() -> None:
    load_dotenv(COPILOT_DEMO_ROOT / ".env", override=True)
    _render()

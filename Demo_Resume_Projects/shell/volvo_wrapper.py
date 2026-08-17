"""Thin wrapper that imports and calls volvo-demo's own render() -- see
novartis_wrapper.py/nrg_wrapper.py for the identical pattern applied to the
other two demos, including why load_dotenv(override=True) must be called
fresh inside render_volvo() on every invocation rather than once at module
scope (Python caches imported modules, so a module-scope load_dotenv()
call would only ever actually execute on the very first import).

Volvo's Submit New Case tab additionally depends on FastAPI (port 8100)
and the Airflow stack (port 8180) already running -- this wrapper doesn't
start them, matching the standalone volvo_app.py's own documented
prerequisite order.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

VOLVO_DEMO_ROOT = Path(__file__).parent.parent / "volvo-demo"
sys.path.insert(0, str(VOLVO_DEMO_ROOT))

from volvo_app_render import render as _render  # noqa: E402 -- must follow sys.path insert


def render_volvo() -> None:
    load_dotenv(VOLVO_DEMO_ROOT / ".env", override=True)
    _render()

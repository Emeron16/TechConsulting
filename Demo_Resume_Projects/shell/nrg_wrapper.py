"""Thin wrapper that imports and calls nrg-demo's own render() -- see
novartis_wrapper.py for the identical pattern applied to the other demo,
including why load_dotenv(override=True) must be called fresh inside
render_nrg() on every invocation rather than once at module scope (Python
caches imported modules, so a module-scope load_dotenv() call would only
ever actually execute on the very first import).
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

NRG_DEMO_ROOT = Path(__file__).parent.parent / "nrg-demo"
sys.path.insert(0, str(NRG_DEMO_ROOT))

from nrg_app_render import render as _render  # noqa: E402 -- must follow sys.path insert


def render_nrg() -> None:
    load_dotenv(NRG_DEMO_ROOT / ".env", override=True)
    _render()

"""Shared narrative text normalization -- abbreviation expansion and
boilerplate-prefix stripping. A single plain Python function, not
duplicated between the PySpark UDF (scripts/preprocess_pyspark.py, Phase 3)
and the live single-case pipeline (the FastAPI /preprocess endpoint,
Phase 6): both call this exact function, so the training corpus and live
inference see identical normalization.

Volvo_Architecture_Deep_Dive.md §3's "independent dealer network... varying
documentation habits" is why this step exists at all -- a single-company
system like the Novartis/NRG demos doesn't have this problem in the same
way, since Volvo's data originates from many independently operated
dealers rather than one company's own systems.
"""
from __future__ import annotations

import re

# Common dealer-shop abbreviations, expanded to their full form. Matched
# case-insensitively with a word-boundary regex so e.g. "chk eng lt" and
# "check engine light" both normalize to the same phrase, and the
# classifier/embedder always see consistent text regardless of which
# individual dealer's typing habits produced it.
ABBREVIATION_EXPANSIONS: dict[str, str] = {
    r"\bchk eng lt\b": "check engine light",
    r"\bchk eng\b": "check engine",
    r"\basap\b": "as soon as possible",
}

# Boilerplate lead-in phrases some dealer narratives are prefixed with --
# stripped since they carry no signal for classification/NER/similarity.
BOILERPLATE_PREFIXES = (
    "customer states:",
    "cust reports:",
    "per customer:",
)


def normalize_text(text: str) -> str:
    """Expands known shop abbreviations and strips a leading boilerplate
    phrase, if present. Whitespace is collapsed and the result is
    re-capitalized at the start if the boilerplate strip left a
    lowercase-continuation sentence.
    """
    normalized = text.strip()

    for prefix in BOILERPLATE_PREFIXES:
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break

    for pattern, expansion in ABBREVIATION_EXPANSIONS.items():
        normalized = re.sub(pattern, expansion, normalized, flags=re.IGNORECASE)

    normalized = re.sub(r"\s+", " ", normalized).strip()

    if normalized and normalized[0].islower():
        normalized = normalized[0].upper() + normalized[1:]

    return normalized

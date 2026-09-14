"""Explicit, inspectable keyword/rule table used to auto-label synthetic
warranty narratives into Volvo_Architecture_Deep_Dive.md's 8 categories.

This rule table IS the ground truth the DistilBERT classifier is trained
against in Phase 4 -- it is deliberately kept as a plain, readable data
structure (not hidden inline string-matching logic) so the labeling
process is auditable: anyone can see exactly why a given narrative was
tagged the way it was, which matters for a demo standing in for a process
that would normally involve human-labeled training data.
"""
from __future__ import annotations

import re

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "powertrain": [
        "engine", "transmission", "stall", "stalling", "misfire", "turbocharger",
        "turbo", "coolant", "overheating", "oil leak", "rough idle", "hesitation",
        "acceleration", "drivetrain", "clutch",
    ],
    "infotainment": [
        "infotainment", "touchscreen", "head unit", "navigation", "nav system",
        "bluetooth", "apple carplay", "android auto", "radio", "sound system",
        "backup camera", "display freeze", "screen frozen", "software glitch",
    ],
    "electrical": [
        "battery drain", "battery dead", "electrical", "short circuit", "fuse",
        "wiring", "alternator", "dashboard lights", "warning light", "won't start",
        "power window", "interior lights",
    ],
    "braking": [
        "brake", "brakes", "braking", "abs", "pedal", "brake pedal", "brake fluid",
        "squealing brakes", "grinding brakes", "brake failure",
    ],
    "software_update": [
        "software update", "firmware", "ota update", "over-the-air", "update failed",
        "system update", "reflash", "recalibration needed",
    ],
    "safety_concern": [
        "recall", "on fire", "caught fire", "airbag", "airbag warning", "steering lock",
        "steering loss", "brake failure", "seatbelt failure", "smoke", "burning smell",
        "sudden stop", "loss of control", "unintended acceleration",
    ],
    "parts_delay": [
        "backordered", "back-ordered", "parts delay", "waiting on a part",
        "waiting on part", "part on order", "supply delay", "no eta", "parts shortage",
    ],
    "dealer_escalation": [
        "escalate", "escalation", "unresolved", "multiple visits", "third visit",
        "still not fixed", "dealer could not diagnose", "management review",
    ],
}

ALL_CATEGORIES = tuple(CATEGORY_KEYWORDS.keys())


def label_narrative(narrative_text: str) -> list[str]:
    """Returns every category whose keyword list matches somewhere in the
    (lowercased) narrative text. A narrative can match zero, one, or
    several categories -- multiple matches are exactly the multi-label
    cases Volvo_Architecture_Deep_Dive.md §2.4 describes (e.g. an
    infotainment failure that also causes unexpected battery drain).

    Matching requires a word boundary immediately BEFORE the keyword but
    not after, so plurals/suffixes still match (e.g. "stall" matches
    "stalls", "window" matches "windows") while a keyword embedded mid-word
    does not (e.g. "fire" does NOT match inside "misfire", since there is
    no word boundary right before "fire" there). A first attempt using
    \\b on both sides was too strict and missed exactly these plural cases
    during Phase 2 verification; requiring \\b only on the left side is
    the fix that satisfies both concerns at once.
    """
    text_lower = narrative_text.lower()
    matched = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword)
            if re.search(pattern, text_lower):
                matched.append(category)
                break
    return matched

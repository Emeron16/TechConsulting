"""Authors the spaCy EntityRuler pattern file as a versioned, inspectable
artifact -- same auditability reasoning as scripts/label_heuristics.py:
these patterns ARE what the NER pipeline recognizes as VIN/DTC/COMPONENT
entities, so they're kept as plain, readable data rather than hardcoded
inline in volvo_models/ner.py.

Usage: python scripts/build_ner_patterns.py
"""
import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent.parent / "volvo_models" / "ner_patterns.jsonl"

# VIN: 17-char alphanumeric, matching Phase 2's synthetic format
# ("YV1VOLVO" + 9 digits). Matched via a TOKEN pattern on shape, not a
# literal string, so it generalizes to any 17-char alphanumeric token, not
# just synthetic-corpus VINs specifically.
VIN_PATTERN = {
    "label": "VIN",
    "pattern": [{"TEXT": {"REGEX": r"^[A-Za-z0-9]{17}$"}}],
}

# DTC (diagnostic trouble code): SAE J2012 format -- one letter (P/B/C/U)
# followed by 4 digits, e.g. P0300, B1000, C0035, U0100.
DTC_PATTERN = {
    "label": "DTC",
    "pattern": [{"TEXT": {"REGEX": r"^[PBCU]\d{4}$"}}],
}

# COMPONENT / SYMPTOM gazetteer patterns -- base en_core_web_sm's NER
# doesn't tag domain terms like "turbocharger" or "infotainment head unit"
# as anything meaningful without help, so these are seeded from the same
# vocabulary scripts/label_heuristics.py already uses to auto-label
# training data, giving the NER pipeline a matching sense of the domain.
COMPONENT_TERMS = [
    "engine", "transmission", "turbocharger", "coolant", "clutch",
    "infotainment", "touchscreen", "navigation system", "backup camera",
    "battery", "alternator", "fuse box", "power window",
    "brake pedal", "brake fluid", "abs",
]
SYMPTOM_TERMS = [
    "stalling", "misfire", "overheating", "rough idle",
    "freezing", "rebooting", "disconnecting",
    "battery drain", "warning light", "short circuit",
    "grinding", "squealing", "soft pedal",
]


def build_patterns() -> list[dict]:
    patterns = [VIN_PATTERN, DTC_PATTERN]
    for term in COMPONENT_TERMS:
        patterns.append({"label": "COMPONENT", "pattern": term})
    for term in SYMPTOM_TERMS:
        patterns.append({"label": "SYMPTOM", "pattern": term})
    return patterns


def main() -> None:
    patterns = build_patterns()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for pattern in patterns:
            f.write(json.dumps(pattern) + "\n")
    print(f"Wrote {len(patterns)} patterns to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

"""spaCy NER pipeline for warranty-narrative entity extraction --
Volvo_Architecture_Deep_Dive.md §2.4: base `en_core_web_sm` plus a custom
EntityRuler (scripts/build_ner_patterns.py's output) for domain-specific
entities (VIN, DTC, COMPONENT, SYMPTOM) the base pretrained NER model has
no reason to recognize on its own. No fine-tuning -- combining spaCy's
pipeline architecture with authored patterns is deliberately lighter-weight
than training a full custom NER model, per the architecture doc's own
reasoning.
"""
from __future__ import annotations

import json
from pathlib import Path

import spacy

PATTERNS_PATH = Path(__file__).parent / "ner_patterns.jsonl"

_nlp: spacy.Language | None = None


def load_ner_pipeline() -> spacy.Language:
    global _nlp
    if _nlp is None:
        nlp = spacy.load("en_core_web_sm")
        ruler = nlp.add_pipe("entity_ruler", before="ner")
        with open(PATTERNS_PATH) as f:
            patterns = [json.loads(line) for line in f]
        ruler.add_patterns(patterns)
        _nlp = nlp
    return _nlp


def extract_entities(text: str) -> list[dict]:
    nlp = load_ner_pipeline()
    doc = nlp(text)
    return [
        {"label": ent.label_, "text": ent.text, "start": ent.start_char, "end": ent.end_char}
        for ent in doc.ents
    ]

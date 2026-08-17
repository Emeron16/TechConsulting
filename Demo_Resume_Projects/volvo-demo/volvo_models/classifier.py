"""Loads the fine-tuned DistilBERT multi-label classifier (Phase 4's
scripts/train_classifier.py output) and exposes a simple classify()
function. Imported by api/main.py's /classify endpoint -- Streamlit and
Airflow's DAG tasks never import this module directly, per the Phase 6
FastAPI-as-single-serving-layer decision.
"""
from __future__ import annotations

from pathlib import Path

import torch
from transformers import DistilBertForSequenceClassification, DistilBertTokenizerFast

from volvo_models.labels import CATEGORIES

MODEL_DIR = Path(__file__).parent.parent / "models" / "distilbert_classifier"
CONFIDENCE_THRESHOLD = 0.5

_model: DistilBertForSequenceClassification | None = None
_tokenizer: DistilBertTokenizerFast | None = None


def load_classifier() -> tuple[DistilBertForSequenceClassification, DistilBertTokenizerFast]:
    """Loads the model+tokenizer once per process and caches them at module
    scope -- avoids re-reading the checkpoint from disk on every classify()
    call.
    """
    global _model, _tokenizer
    if _model is None or _tokenizer is None:
        _model = DistilBertForSequenceClassification.from_pretrained(str(MODEL_DIR))
        _tokenizer = DistilBertTokenizerFast.from_pretrained(str(MODEL_DIR))
        _model.eval()
    return _model, _tokenizer


def classify(text: str) -> list[tuple[str, float]]:
    """Returns (category, confidence) pairs for every category whose
    sigmoid score is >= CONFIDENCE_THRESHOLD, sorted by confidence
    descending. An empty list means no category crossed threshold.
    """
    model, tokenizer = load_classifier()
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.sigmoid(logits)[0].tolist()

    scored = [(category, prob) for category, prob in zip(CATEGORIES, probs) if prob >= CONFIDENCE_THRESHOLD]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored

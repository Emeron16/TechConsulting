"""Sentence-BERT embedding for warranty-narrative similarity/duplicate
detection -- Volvo_Architecture_Deep_Dive.md §2.4's "no fine-tuning
needed" design: `all-MiniLM-L6-v2` pretrained is used as-is, since its
siamese-network training objective already optimizes for direct
sentence-to-sentence comparison (the specific reason the architecture doc
gives for choosing Sentence-BERT over raw BERT [CLS] embeddings).

Output dimension (384) matches volvo_retrieval/opensearch_client.py's
narrative_vector mapping.
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_DIM = 384

_model: SentenceTransformer | None = None


def load_similarity_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    model = load_similarity_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batched embedding -- used by the bulk historical-case seed step
    (Phase 8), which would otherwise pay per-call model overhead once per
    narrative.
    """
    model = load_similarity_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()

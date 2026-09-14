"""Component 1 (intelligence half): GPT-4o-mini turns raw intake text into structured fields."""
from __future__ import annotations

from core.config import DEFAULT_MODEL, get_client
from core.schemas import ExtractedRequest

SYSTEM_PROMPT = """You are the document-intake extraction agent in a prior-authorization \
pipeline for a regional health plan. You will be given the raw text of a prior authorization \
request (from a fax, PDF, portal submission, or provider upload).

Extract the structured fields exactly as specified. Rules:
- Diagnosis codes (ICD-10) and procedure codes (CPT/HCPCS) must be taken VERBATIM from the \
text. Never infer or guess a code that is not explicitly written down. If none are present, \
return an empty list for that field.
- Preserve the clinically relevant narrative verbatim in clinical_notes (you may trim obvious \
boilerplate/header noise, but do not paraphrase clinical content).
- urgency must reflect what the document actually says or clearly implies (e.g. "STAT", \
"urgent", explicit time pressure) — default to "routine" if nothing indicates otherwise.
- confidence_score reflects how clearly and unambiguously the document text supports this \
extraction (document/OCR clarity), NOT your opinion of the clinical case. Use lower scores if \
text is garbled, fields are ambiguous, or required fields are simply absent.
- Use extraction_notes to flag anything ambiguous, contradictory, or low-confidence.
"""


def extract(raw_text: str) -> ExtractedRequest:
    client = get_client()
    completion = client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Raw intake document text:\n\n{raw_text}"},
        ],
        response_format=ExtractedRequest,
        temperature=0,
    )
    result = completion.choices[0].message.parsed
    if result is None:
        raise ValueError("Extraction failed to parse a structured result from the model.")
    return result

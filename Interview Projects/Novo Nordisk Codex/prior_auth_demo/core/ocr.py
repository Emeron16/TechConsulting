"""
Text extraction for uploaded files — the "OCR + Document AI" half of Component 1.

Real Azure Form Recognizer isn't wired up for this demo (no Azure credentials involved).
Instead:
  - PDFs: extracted with pdfplumber (pure Python, no external binary). This handles the
    common case of digitally-generated PDFs/portal exports fine, and even lets you feed this
    demo's own proposal PDF through the pipeline as a sanity check.
  - Images (scanned faxes): extracted with pytesseract, which requires the Tesseract OCR
    binary to be installed separately on the machine. If it isn't found, we fail gracefully
    with a clear message instead of crashing the app.
"""
from __future__ import annotations

import io

TESSERACT_INSTALL_HINT = (
    "Image OCR requires the Tesseract binary, which isn't bundled with this demo. "
    "Install it from https://github.com/UB-Mannheim/tesseract/wiki (Windows) or your OS "
    "package manager, then restart the app. In the meantime, use a sample case or paste "
    "text instead."
)


class OcrUnavailableError(RuntimeError):
    pass


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import pdfplumber

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text)
    text = "\n\n".join(text_parts).strip()
    if not text:
        raise OcrUnavailableError(
            "No extractable text found in this PDF (it may be a scanned image with no "
            "embedded text layer). Try a sample case or paste the text directly."
        )
    return text


def extract_text_from_image(file_bytes: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - defensive
        raise OcrUnavailableError(TESSERACT_INSTALL_HINT) from exc

    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image).strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(TESSERACT_INSTALL_HINT) from exc

    if not text:
        raise OcrUnavailableError(
            "OCR ran but found no text in this image. Try a clearer scan, a sample case, "
            "or paste the text directly."
        )
    return text


def extract_text(file_name: str, file_bytes: bytes) -> str:
    """Dispatch by file extension. Raises OcrUnavailableError with a UI-friendly message."""
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    if lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
        return extract_text_from_image(file_bytes)
    raise OcrUnavailableError(
        f"Unsupported file type for '{file_name}'. Upload a PDF or an image (PNG/JPG), "
        "or use a sample case / paste text instead."
    )

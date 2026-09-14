# AI-Powered Prior Authorization — Demo

A working Streamlit demo of the architecture described in `Prior_Auth_AI_Solution.pdf` — a
regional health plan prior-authorization pipeline with four layers: Intake, Intelligence
(policy RAG), Decision Support (risk stratification/routing), and Communication (provider
portal). Every AI step runs live on **OpenAI gpt-4o-mini**.

**Everything here is synthetic** — sample patients, requests, and the policy knowledge base
were all written for this demo. No real PHI or proprietary payer policy content is used.

## Setup

1. **Python**: 3.10+ recommended.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Add your OpenAI key:
   ```
   copy .env.example .env
   ```
   Open `.env` and replace `your-key-here` with your real OpenAI API key. `.env` is
   gitignored — never commit it.
4. (Optional, for real image OCR) Install the Tesseract OCR binary if you want to upload
   scanned images (PNG/JPG) on the New Request page:
   - Windows: https://github.com/UB-Mannheim/tesseract/wiki
   - macOS: `brew install tesseract`
   - Linux: `apt-get install tesseract-ocr`

   PDF uploads work without any extra install (via `pdfplumber`, as long as the PDF has an
   embedded text layer — true of most digitally-generated PDFs, including this proposal's own
   PDF). If Tesseract isn't installed, image upload will show a friendly warning instead of
   crashing — use a sample case or paste text instead.

## Run

```
streamlit run app.py
```

## Tour

- **Home** — recaps the problem (where the 4.2 days go) and the four-layer architecture.
- **1 · New Request** — pick a sample case (each one is tuned to land on a different pathway),
  paste your own text, or upload a PDF/image. Watch the pipeline run: extraction → completeness
  check → policy RAG analysis → risk-based routing.
- **2 · Nurse Dashboard** — every case that isn't auto-approved lands here with an AI-generated
  summary, met/unmet criteria, citations, and risk flags. You (the nurse) approve, deny, or
  request more info — nothing is decided by the AI on these cases.
- **3 · Provider Portal** — check a request's status by ID, see the letter, and (if info was
  requested) simulate the provider uploading additional documentation to re-trigger validation.
- **4 · Analytics & Audit** — the proposal's projected outcomes (static reference) next to this
  session's live activity, plus the full audit trail (every AI call + every human decision),
  exportable as CSV.

## Notes on what's simplified for the demo

- **OCR**: text-based PDFs via `pdfplumber`; images via `pytesseract` (needs the Tesseract
  binary). Production would use Azure Form Recognizer / Document AI as in the proposal.
- **Policy retrieval**: exact CPT/HCPCS code match against a 6-policy synthetic knowledge base,
  falling back to BM25 keyword search. Production would use hybrid BM25 + semantic embedding
  search with a cross-encoder reranker over the full InterQual/MCG/CMS/plan-policy corpus.
- **Completeness validator**: rule-based field checks plus keyword-presence heuristics for
  policy-required documentation. Production would use the same clinical NLP layer used
  elsewhere in the pipeline for this.
- **Storage**: a local SQLite file (`data/demo.db`, gitignored) — good enough for a live
  single-machine walkthrough, not multi-user production storage.

## Project structure

```
app.py                  Home page
pages/                  Streamlit multipage app (New Request, Nurse Dashboard, Provider Portal, Analytics & Audit)
core/                   Pipeline logic (extraction, completeness, policy RAG, routing, letters, storage)
data/policy_kb/         Synthetic policy documents
data/sample_requests/   Synthetic sample prior-auth requests
```

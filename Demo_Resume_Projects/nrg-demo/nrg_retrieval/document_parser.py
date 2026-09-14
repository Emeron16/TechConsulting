"""Document parsing -- the Amazon Textract analog (per
NRG_Energy_Architecture_Deep_Dive.md §2.6). Handles NRG's two source
formats:

- .md: YAML frontmatter + Markdown body, same convention as copilot-demo's
  kb_ingest.parse_markdown() -- parsed directly, no unstructured.io needed
  (plain text has no layout/table complexity to extract).
- .pdf: parsed via unstructured.partition.pdf.partition_pdf() with
  strategy="hi_res" and infer_table_structure=True, so tables (e.g. rate
  tiers, EFL price tables) are detected as genuine Table elements with a
  structured HTML representation (element.metadata.text_as_html), not just
  flattened prose. Metadata for PDFs is a plain-text block at the top of
  the document (`key: value` lines between `---` markers, mirroring the
  YAML frontmatter convention as closely as a PDF allows) since PDFs have
  no native frontmatter concept -- extracted via regex over the parsed
  Title/NarrativeText/Text elements before the second `---` marker.
"""
import re
from pathlib import Path

import yaml
from unstructured.partition.pdf import partition_pdf

REQUIRED_FIELDS = ("doc_id", "doc_type", "title", "status", "effective_date", "version")
# Only plan_rate docs strictly require a plan_type (the deep-dive's
# metadata-filtered-by-plan-type retrieval applies to plan/rate terms
# specifically). compliance_disclosure docs (EFLs) are plan-specific in
# practice but not structurally required to name one; billing_policy,
# outage_procedure, and escalation_playbook docs are typically plan-agnostic
# (plan_type: null in their frontmatter).
DOC_TYPES_REQUIRING_PLAN_TYPE = ("plan_rate",)


def parse_markdown(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError("Markdown document missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    return metadata, body


def _parse_pdf_metadata_block(elements) -> tuple[dict, int]:
    """The first two Text elements whose content is exactly '---' bracket a
    metadata block of 'key: value' Title/NarrativeText elements (see the
    generator script that authored these PDFs -- each metadata line is its
    own paragraph, so unstructured.io emits one element per line rather
    than one block of multiple lines). Returns (metadata_dict,
    index_of_element_after_the_closing_marker) so the caller knows where
    the real document body starts.
    """
    dash_indices = [i for i, el in enumerate(elements) if str(el).strip() == "---"]
    if len(dash_indices) < 2:
        raise ValueError("PDF document missing '---' metadata block markers")

    start, end = dash_indices[0], dash_indices[1]
    metadata: dict = {}
    for el in elements[start + 1 : end]:
        line = str(el).strip()
        # A NarrativeText element can bundle multiple "key: value" lines
        # together if unstructured.io's layout model merges adjacent short
        # lines -- split on whitespace-separated "key: value" pairs using a
        # lookahead so "plan_type: fixed version: 3" still parses as two
        # pairs instead of one malformed one.
        for key, value in re.findall(r"(\w+):\s*(.*?)(?=\s+\w+:|$)", line):
            metadata[key] = value.strip()

    return metadata, end + 1


def parse_pdf(file_path: Path) -> tuple[dict, str, list]:
    """Returns (metadata, body_text, table_elements) -- table_elements is
    the list of unstructured Table elements (if any), kept separate from
    body_text so nrg_chains/ingest.py's chunker can decide whether to
    inline each table's HTML into the surrounding chunk or treat it as its
    own chunk, rather than losing the table structure by only using
    str(element) (which unstructured.io renders as flattened text.
    """
    elements = partition_pdf(str(file_path), strategy="hi_res", infer_table_structure=True)
    metadata, body_start_idx = _parse_pdf_metadata_block(elements)

    body_parts = []
    table_elements = []
    for el in elements[body_start_idx:]:
        el_type = type(el).__name__
        if el_type == "Table":
            table_elements.append(el)
            html = getattr(el.metadata, "text_as_html", None)
            body_parts.append(html if html else str(el))
        else:
            body_parts.append(str(el))

    body = "\n\n".join(body_parts)
    if "version" in metadata:
        try:
            metadata["version"] = int(metadata["version"])
        except ValueError:
            pass
    # PDF metadata has no native null -- the doc-authoring convention writes
    # the literal text "null" for an absent plan_type, since a blank line
    # would be ambiguous with a missing key entirely once flattened through
    # unstructured.io's element parsing. Normalize back to a real absence.
    if metadata.get("plan_type") == "null":
        del metadata["plan_type"]
    return metadata, body, table_elements


def load_document(path: Path) -> tuple[dict, str]:
    suffix = path.suffix
    if suffix == ".md":
        metadata, body = parse_markdown(path.read_text())
    elif suffix == ".pdf":
        metadata, body, _tables = parse_pdf(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    missing = [f for f in REQUIRED_FIELDS if not metadata.get(f)]
    if missing:
        raise ValueError(f"Missing required metadata field(s): {missing}")
    if metadata["doc_type"] in DOC_TYPES_REQUIRING_PLAN_TYPE and not metadata.get("plan_type"):
        raise ValueError(f"doc_type={metadata['doc_type']!r} requires a plan_type field")

    return metadata, body


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

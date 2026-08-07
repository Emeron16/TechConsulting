"""Knowledge-base read/management operations for the Streamlit KB tab --
search, browse, version history, content viewing, and soft delete. Parallel
to mcp_servers/review_actions.py's pattern: one shared implementation the
UI calls directly (no MCP round-trip needed for admin/GUI operations,
unlike agent tool calls which go through the governed MCP servers).
"""
from pathlib import Path

import markdown as md_lib

from copilot_agents.kb_ingest import (
    DOCS_DIR,
    get_chroma_collection,
    ingest_document,
    load_document,
    refresh_search_indexes,
)
from mcp_servers.common import get_pg_connection, search_documents


def _render_content(raw: str, file_format: str) -> tuple[str, str]:
    """Shared .md-to-HTML conversion (or HTML passthrough) so both the
    kb_documents-backed path and the CLI-corpus fallback path render
    identically.
    """
    if file_format == "html":
        return raw, "html"

    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            body = parts[2].strip()
    html_body = md_lib.markdown(body, extensions=["tables", "fenced_code"])
    wrapped = (
        "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:800px;margin:0 auto;padding:24px;line-height:1.6;color:#1a1a1a;'>"
        f"{html_body}</div>"
    )
    return wrapped, "md"


def _find_corpus_file(doc_id: str) -> Path | None:
    """Fallback for documents that were bulk-ingested via scripts/ingest.py
    and never got a kb_documents row -- locate their source file directly
    by matching parsed doc_id, same lookup scripts/ingest.py's loader uses.
    """
    for path in sorted(DOCS_DIR.glob("*.md")) + sorted(DOCS_DIR.glob("*.html")):
        try:
            metadata, _ = load_document(path)
        except ValueError:
            continue
        if metadata.get("doc_id") == doc_id:
            return path
    return None


def search_kb(query: str, doc_type: str | None = None) -> list[dict]:
    """Search + enrich with version/uploader metadata from kb_documents."""
    results = search_documents(query, doc_type=doc_type, n_results=10)
    if not results:
        return results

    doc_ids = list({r["doc_id"] for r in results})
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT doc_id, version, status, uploaded_by, uploaded_at "
            "FROM kb_documents WHERE doc_id = ANY(%s) AND status = 'active'",
            (doc_ids,),
        )
        by_doc_id = {r[0]: r for r in cur.fetchall()}

    for r in results:
        kb_row = by_doc_id.get(r["doc_id"])
        r["uploaded_by"] = kb_row[3] if kb_row else None
        r["uploaded_at"] = kb_row[4] if kb_row else None
    return results


def list_all_documents() -> list[dict]:
    """Every doc_id's current active version *that was uploaded through the
    KB GUI* (i.e. has a kb_documents row). Use list_all_kb_documents() for
    the full searchable corpus, including CLI-ingested documents, which is
    what the Browse tab's default listing should show.
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_id, version, title, doc_type, file_format, status,
                   uploaded_by, uploaded_at
            FROM kb_documents WHERE status = 'active'
            ORDER BY doc_id
            """
        )
        rows = cur.fetchall()
    return [
        {
            "doc_id": r[0],
            "version": r[1],
            "title": r[2],
            "doc_type": r[3],
            "file_format": r[4],
            "status": r[5],
            "uploaded_by": r[6],
            "uploaded_at": r[7],
        }
        for r in rows
    ]


def list_all_kb_documents() -> list[dict]:
    """Every unique, currently-retrievable doc_id in the full corpus --
    Chroma is the source of truth for "what's actually searchable," so this
    covers both CLI-bulk-ingested documents and GUI uploads, unlike
    list_all_documents() which only sees GUI uploads. Enriched with
    kb_documents version/uploader metadata where a GUI upload exists.
    Deduplicated to one row per doc_id (Chroma stores one row per chunk).
    """
    collection = get_chroma_collection()
    all_chunks = collection.get()

    by_doc_id: dict[str, dict] = {}
    for meta in all_chunks["metadatas"]:
        doc_id = meta["doc_id"]
        if doc_id not in by_doc_id:
            by_doc_id[doc_id] = {
                "doc_id": doc_id,
                "title": meta["title"],
                "doc_type": meta["doc_type"],
                "version": meta.get("version"),
                "effective_date": meta.get("effective_date"),
                "uploaded_by": None,
                "uploaded_at": None,
            }

    doc_ids = list(by_doc_id.keys())
    if doc_ids:
        with get_pg_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, version, uploaded_by, uploaded_at "
                "FROM kb_documents WHERE doc_id = ANY(%s) AND status = 'active'",
                (doc_ids,),
            )
            for doc_id, version, uploaded_by, uploaded_at in cur.fetchall():
                by_doc_id[doc_id]["version"] = version
                by_doc_id[doc_id]["uploaded_by"] = uploaded_by
                by_doc_id[doc_id]["uploaded_at"] = uploaded_at

    return sorted(by_doc_id.values(), key=lambda d: d["doc_id"])


def get_document_versions(doc_id: str) -> list[dict]:
    """Full version history (all statuses) for one doc_id, newest first."""
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, status, file_path, file_format, uploaded_by, uploaded_at
            FROM kb_documents WHERE doc_id = %s
            ORDER BY version DESC
            """,
            (doc_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "version": r[1],
            "status": r[2],
            "file_path": r[3],
            "file_format": r[4],
            "uploaded_by": r[5],
            "uploaded_at": r[6],
        }
        for r in rows
    ]


def get_document_content(doc_id: str, version: int | None = None) -> tuple[str, str]:
    """Returns (html_content, file_format) for viewing. If version is None,
    fetches the current active version; otherwise fetches that specific
    (possibly superseded) version, read-only.

    Falls back to scanning data/synthetic_docs/ directly for documents that
    were bulk-ingested via scripts/ingest.py and never got a kb_documents
    row (no version history in that case -- there's only ever "the file").
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        if version is None:
            cur.execute(
                "SELECT file_path, file_format FROM kb_documents "
                "WHERE doc_id = %s AND status = 'active'",
                (doc_id,),
            )
        else:
            cur.execute(
                "SELECT file_path, file_format FROM kb_documents "
                "WHERE doc_id = %s AND version = %s",
                (doc_id, version),
            )
        row = cur.fetchone()

    if row is not None:
        file_path, file_format = row
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        return _render_content(raw, file_format)

    corpus_path = _find_corpus_file(doc_id)
    if corpus_path is None:
        raise ValueError(f"No document found for doc_id={doc_id!r} version={version!r}")
    raw = corpus_path.read_text(encoding="utf-8")
    file_format = "html" if corpus_path.suffix == ".html" else "md"
    return _render_content(raw, file_format)


def soft_delete_document(doc_id: str, deleted_by: str) -> tuple[bool, str]:
    """Marks the active kb_documents row 'deleted' and removes its chunks
    from Chroma (so it stops being retrieved) -- file on disk and the
    Postgres row remain for audit/undo.
    """
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, version FROM kb_documents WHERE doc_id = %s AND status = 'active'",
            (doc_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False, f"No active document found for doc_id={doc_id!r}"

        cur.execute("UPDATE kb_documents SET status = 'deleted' WHERE id = %s", (row[0],))
        conn.commit()

    collection = get_chroma_collection()
    existing = collection.get(where={"doc_id": doc_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
    refresh_search_indexes(collection)

    return True, f"{doc_id} (v{row[1]}) marked deleted by {deleted_by}, removed from search."


def ingest_document_and_collect(file_bytes: bytes, filename: str, uploaded_by: str):
    """Drains the ingest_document() generator, returning (steps, result).
    Kept separate from the generator itself so callers that don't need
    live per-step UI updates (e.g. tests) can get the final result simply.
    """
    steps = []
    gen = ingest_document(file_bytes, filename, uploaded_by)
    result = None
    try:
        while True:
            steps.append(next(gen))
    except StopIteration as stop:
        result = stop.value
    return steps, result

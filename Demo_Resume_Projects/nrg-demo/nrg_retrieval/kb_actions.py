"""Knowledge-base read/management operations for the Streamlit KB tab --
search, browse, version history, content viewing. Parallel to
copilot-demo's mcp_servers/kb_actions.py, simplified since NRG has no
bypass-Postgres bulk path: every document (CLI bulk-ingest or GUI upload)
goes through nrg_chains.ingest.ingest_document(), so kb_documents is always
the source of truth for what's active -- no corpus-file fallback needed.
"""
import markdown as md_lib

from nrg_retrieval.hybrid_search import hybrid_search
from nrg_retrieval.postgres_client import get_pg_connection


def _render_content(raw: str, file_format: str) -> tuple[str, str]:
    if file_format == "pdf":
        # PDFs aren't re-rendered from source here (that would mean
        # re-running unstructured.io just to view a document) -- the raw
        # parsed text isn't persisted separately from the ingest payload,
        # so PDF viewing shows a notice instead of full content. A future
        # enhancement could persist parsed text at ingest time if inline
        # PDF viewing becomes a priority.
        return (
            "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
            "max-width:800px;margin:0 auto;padding:24px;'>"
            "<p><em>This document was ingested from a PDF. Open the original file directly "
            f"to view its full content: {raw}</em></p></div>"
        ), "pdf"

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


def search_kb(query: str, doc_type: str | None = None) -> list[dict]:
    """Search + enrich with uploader metadata from kb_documents."""
    results = hybrid_search(query, doc_type=doc_type, top_k=10)
    if not results:
        return results

    doc_ids = list({r["doc_id"] for r in results})
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, plan_type, uploaded_by, uploaded_at "
                "FROM kb_documents WHERE doc_id = ANY(%s) AND status = 'active'",
                (doc_ids,),
            )
            by_doc_id = {r[0]: r for r in cur.fetchall()}
    finally:
        conn.close()

    for r in results:
        kb_row = by_doc_id.get(r["doc_id"])
        r["plan_type"] = kb_row[1] if kb_row else None
        r["uploaded_by"] = kb_row[2] if kb_row else None
        r["uploaded_at"] = kb_row[3] if kb_row else None
        r["excerpt"] = r.pop("excerpt")[:300]
    return results


def list_all_kb_documents() -> list[dict]:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_id, version, title, doc_type, plan_type, file_format,
                       status, uploaded_by, uploaded_at
                FROM kb_documents WHERE status = 'active'
                ORDER BY doc_id
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "doc_id": r[0],
            "version": r[1],
            "title": r[2],
            "doc_type": r[3],
            "plan_type": r[4],
            "file_format": r[5],
            "status": r[6],
            "uploaded_by": r[7],
            "uploaded_at": r[8],
        }
        for r in rows
    ]


def get_document_versions(doc_id: str) -> list[dict]:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, version, status, file_path, file_format, uploaded_by, uploaded_at
                FROM kb_documents WHERE doc_id = %s
                ORDER BY version DESC
                """,
                (doc_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
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
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
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
    finally:
        conn.close()

    if row is None:
        raise ValueError(f"No document found for doc_id={doc_id!r} version={version!r}")

    file_path, file_format = row
    if file_format == "pdf":
        return _render_content(file_path, "pdf")

    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    return _render_content(raw, file_format)

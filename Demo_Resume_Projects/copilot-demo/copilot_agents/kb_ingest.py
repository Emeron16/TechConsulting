"""Shared knowledge-base ingestion logic: document parsing (.md/.html) and
chunking, used by both the CLI bulk-ingest (scripts/ingest.py, folder scan +
manifest) and the Streamlit KB tab's single-file upload flow.

The single-file path (ingest_document) additionally does version/conflict
resolution against the kb_documents Postgres table: same doc_id + same
content is a no-op, same doc_id + different content creates a new version
and marks the prior one superseded, brand new doc_id becomes version 1.
Only one 'active' row per doc_id is ever retrievable (enforced by both this
logic and a partial unique index in db/init/02_kb_documents.sql).
"""
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Generator

import chromadb
import yaml
from chromadb.utils import embedding_functions

from copilot_agents.cache import CachedEmbeddingFunction, invalidate_retrieval_cache
from mcp_servers.common import get_pg_connection

_ROOT = Path(__file__).parent.parent
# Resolved against this project's root, not the process's cwd -- see
# mcp_servers/common.py's CHROMA_DIR comment for why (a caller launched
# from a different cwd, e.g. shell/novartis_wrapper.py, would otherwise
# silently open/create an empty chroma_db/ elsewhere).
CHROMA_DIR = str(_ROOT / os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db"))
COLLECTION_NAME = "quality_documents"
EMBEDDING_MODEL = "text-embedding-3-small"
DOCS_DIR = _ROOT / "data" / "synthetic_docs"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

REQUIRED_FIELDS = ("doc_id", "doc_type", "title", "status", "effective_date", "version")


# ---------------------------------------------------------------------------
# Parsing (shared by CLI bulk-ingest and GUI single-file upload)
# ---------------------------------------------------------------------------
def parse_markdown(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError("Markdown document missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    return metadata, body


class _HTMLTextExtractor(HTMLParser):
    """Strips tags/scripts/styles, keeps readable body text and <meta
    name="doc-*"> values -- enough to feed the same chunk/embed pipeline
    as the .md docs without a full HTML->markdown conversion.
    """

    _SKIP_TAGS = {"script", "style"}

    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "meta" and attrs_dict.get("name", "").startswith("doc-"):
            key = attrs_dict["name"][len("doc-") :]
            self.meta[key] = attrs_dict.get("content", "")
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._text_parts.append(stripped)

    @property
    def body_text(self) -> str:
        return "\n".join(self._text_parts)


def parse_html(text: str) -> tuple[dict, str]:
    parser = _HTMLTextExtractor()
    parser.feed(text)
    meta = parser.meta
    if "id" not in meta:
        raise ValueError('HTML document missing <meta name="doc-id" content="..."> in <head>')
    metadata = {
        "doc_id": meta["id"],
        "doc_type": meta.get("type", "unknown"),
        "title": meta.get("title") or parser.title.strip() or meta["id"],
        "status": meta.get("status", "approved"),
        "effective_date": meta.get("effective-date", ""),
        "version": meta.get("version", "1"),
    }
    return metadata, parser.body_text


def load_document(path: Path) -> tuple[dict, str]:
    return load_document_text(path.read_text(), path.suffix)


def load_document_text(text: str, suffix: str) -> tuple[dict, str]:
    if suffix == ".md":
        metadata, body = parse_markdown(text)
    elif suffix == ".html":
        metadata, body = parse_html(text)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    missing = [f for f in REQUIRED_FIELDS if not metadata.get(f)]
    if missing:
        raise ValueError(f"Missing required metadata field(s): {missing}")
    return metadata, body


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(content_bytes: bytes) -> str:
    return hashlib.sha256(content_bytes).hexdigest()


def get_chroma_collection():
    raw_embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
        api_key=os.environ["OPENAI_API_KEY"], model_name=EMBEDDING_MODEL
    )
    embedding_fn = CachedEmbeddingFunction(raw_embedding_fn, EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        return client.get_collection(COLLECTION_NAME, embedding_function=embedding_fn)
    return client.create_collection(COLLECTION_NAME, embedding_function=embedding_fn)


def refresh_search_indexes(collection) -> None:
    """Called after any corpus-changing write (new doc, new version, soft
    delete) -- clears the disk-backed retrieval cache so it can't silently
    serve stale results after this change.

    Does NOT rebuild the in-memory BM25 index here: each MCP server runs
    as its own short-lived subprocess (spawned fresh per question via
    MCPServerStdio -- see copilot_agents/mcp_connections.py), so there's no
    long-lived BM25 index in *this* process for agent queries to hit in the
    first place. The subprocess that actually serves the next search lazily
    builds its own fresh index from Chroma on first use
    (hybrid_search._ensure_bm25_index), which is already correct by
    construction. The retrieval cache is the one piece of state that
    genuinely persists across processes (disk-backed), so it's the only
    thing that needs explicit invalidation here.
    """
    invalidate_retrieval_cache()


# ---------------------------------------------------------------------------
# Single-file upload + versioning (GUI path)
# ---------------------------------------------------------------------------
@dataclass
class IngestStep:
    stage: str  # "parsing" | "chunking" | "embedding" | "versioning" | "storing" | "done" | "error"
    detail: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class KBDocument:
    doc_id: str
    version: int
    title: str
    doc_type: str
    file_path: str
    file_format: str
    content_hash: str
    status: str
    is_new_version: bool  # False if this was a no-op (identical content already active)


def _get_active_version(cur, doc_id: str) -> tuple | None:
    cur.execute(
        "SELECT id, version, content_hash, file_path FROM kb_documents "
        "WHERE doc_id = %s AND status = 'active'",
        (doc_id,),
    )
    return cur.fetchone()


def _get_max_version(cur, doc_id: str) -> int | None:
    """Highest version number ever used for doc_id, across ALL statuses
    (active, superseded, AND deleted) -- version numbers are never reused.
    Without this, re-uploading a doc whose only row was soft-deleted (see
    mcp_servers/kb_actions.py's soft_delete_document) would compute
    new_version=1 again (since _get_active_version finds no active row) and
    collide with the deleted row's still-occupied (doc_id, version) unique
    constraint.
    """
    cur.execute("SELECT MAX(version) FROM kb_documents WHERE doc_id = %s", (doc_id,))
    row = cur.fetchone()
    return row[0] if row else None


def ingest_document(
    file_bytes: bytes, filename: str, uploaded_by: str
) -> Generator[IngestStep, None, KBDocument]:
    """Generator so the caller (Streamlit's st.status()) can show live
    progress. The final `return` value (accessible via StopIteration.value
    when driven manually, or by exhausting the generator) is the resulting
    KBDocument -- callers typically use a small helper to drain it, see
    mcp_servers/kb_actions.py's ingest_document_and_collect().
    """
    suffix = Path(filename).suffix
    if suffix not in (".md", ".html"):
        yield IngestStep("error", {"message": f"Unsupported file type: {suffix}"})
        raise ValueError(f"Unsupported file type: {suffix}")

    yield IngestStep("parsing", {"filename": filename})
    text = file_bytes.decode("utf-8")
    metadata, body = load_document_text(text, suffix)
    doc_id = metadata["doc_id"]
    digest = content_hash(file_bytes)
    yield IngestStep(
        "parsing",
        {"doc_id": doc_id, "doc_type": metadata["doc_type"], "title": metadata["title"]},
    )

    yield IngestStep("chunking", {"doc_id": doc_id})
    chunks = chunk_text(body)
    yield IngestStep(
        "chunking",
        {
            "doc_id": doc_id,
            "chunk_count": len(chunks),
            "strategy": "fixed-size character window",
            "chunk_size": CHUNK_SIZE,
            "overlap": CHUNK_OVERLAP,
        },
    )

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            yield IngestStep("versioning", {"doc_id": doc_id, "checking_for": "existing active version"})
            active = _get_active_version(cur, doc_id)

            if active is not None and active[2] == digest:
                yield IngestStep(
                    "versioning",
                    {
                        "doc_id": doc_id,
                        "outcome": "no_op",
                        "reason": "identical content already active as this version",
                        "version": active[1],
                    },
                )
                yield IngestStep("done", {"doc_id": doc_id, "outcome": "no_op", "version": active[1]})
                return KBDocument(
                    doc_id=doc_id,
                    version=active[1],
                    title=metadata["title"],
                    doc_type=metadata["doc_type"],
                    file_path=active[3],
                    file_format=suffix.lstrip("."),
                    content_hash=digest,
                    status="active",
                    is_new_version=False,
                )

            max_version = _get_max_version(cur, doc_id)
            new_version = (max_version or 0) + 1
            if active is not None:
                cur.execute("UPDATE kb_documents SET status = 'superseded' WHERE id = %s", (active[0],))
                yield IngestStep(
                    "versioning",
                    {
                        "doc_id": doc_id,
                        "outcome": "new_version",
                        "previous_version": active[1],
                        "new_version": new_version,
                    },
                )
            elif max_version is not None:
                yield IngestStep(
                    "versioning",
                    {
                        "doc_id": doc_id,
                        "outcome": "new_version",
                        "reason": "prior version(s) exist but none are active (e.g. soft-deleted)",
                        "new_version": new_version,
                    },
                )
            else:
                yield IngestStep(
                    "versioning", {"doc_id": doc_id, "outcome": "new_document", "version": new_version}
                )

            # Each version gets its own immutable file on disk (doc_id-vN.suffix)
            # so a superseded version's content stays viewable after a newer
            # version overwrites what "the current file" means -- without this,
            # version history would silently show the latest content for every
            # past version.
            versioned_filename = f"{doc_id}-v{new_version}{suffix}"
            file_path = DOCS_DIR / versioned_filename
            file_path.write_bytes(file_bytes)

            cur.execute(
                """
                INSERT INTO kb_documents
                    (doc_id, version, title, doc_type, file_path, file_format,
                     content_hash, status, effective_date, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                """,
                (
                    doc_id,
                    new_version,
                    metadata["title"],
                    metadata["doc_type"],
                    str(file_path),
                    suffix.lstrip("."),
                    digest,
                    metadata.get("effective_date") or None,
                    uploaded_by,
                ),
            )
        conn.commit()

        yield IngestStep("embedding", {"doc_id": doc_id, "model": "text-embedding-3-small", "chunk_count": len(chunks)})
        collection = get_chroma_collection()

        existing_chunks = collection.get(where={"doc_id": doc_id})
        if existing_chunks["ids"]:
            collection.delete(ids=existing_chunks["ids"])

        ids = [f"{doc_id}-chunk-{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_id,
                "doc_type": metadata["doc_type"],
                "title": metadata["title"],
                "status": metadata["status"],
                "effective_date": str(metadata["effective_date"]),
                "version": new_version,
            }
            for _ in chunks
        ]
        yield IngestStep("storing", {"doc_id": doc_id, "collection": COLLECTION_NAME})
        collection.add(ids=ids, documents=chunks, metadatas=metadatas)
        refresh_search_indexes(collection)

        yield IngestStep(
            "done",
            {"doc_id": doc_id, "version": new_version, "chunk_count": len(chunks), "outcome": "ingested"},
        )
        return KBDocument(
            doc_id=doc_id,
            version=new_version,
            title=metadata["title"],
            doc_type=metadata["doc_type"],
            file_path=str(file_path),
            file_format=suffix.lstrip("."),
            content_hash=digest,
            status="active",
            is_new_version=True,
        )
    finally:
        conn.close()

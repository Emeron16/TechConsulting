"""Bulk-ingest synthetic docs (data/synthetic_docs/) into a local ChromaDB
persistent collection, chunked and embedded via OpenAI, with metadata
(doc_id, doc_type, status, effective_date) for filtered retrieval --
mirrors the original architecture's "hybrid + metadata filtering"
requirement (approved, latest version only).

Supports two source formats:
  - .md files with YAML frontmatter (---\\n...\\n---\\n<body>)
  - .html files with <meta name="doc-..." content="..."> tags in <head>,
    body text extracted by stripping tags/scripts/styles
Parsing logic lives in copilot_agents/kb_ingest.py, shared with the
Streamlit KB tab's single-file upload flow.

Incremental: a manifest (chroma_db/.ingest_manifest.json) tracks each
source file's content hash. Re-running only re-embeds files that are new
or changed since the last run -- unchanged files are left alone. Delete
the manifest (or pass --full) to force a full rebuild.

Note: this CLI path does NOT write to the kb_documents Postgres version-
history table (that's specific to the GUI's per-file upload/versioning
flow) -- it's a separate, simpler bulk path for the hand-authored corpus.

Note on search indexes: the in-memory BM25 index (mcp_servers/hybrid_search.py)
and retrieval cache are process-local state that doesn't need refreshing
here -- each MCP server runs as its own subprocess and lazily builds/rebuilds
its BM25 index from whatever's in Chroma the first time it searches, so
running this script in a separate process is automatically picked up.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from copilot_agents.kb_ingest import chunk_text, file_hash, get_chroma_collection, load_document

DOCS_DIR = Path(__file__).parent.parent / "data" / "synthetic_docs"
CHROMA_DIR = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
COLLECTION_NAME = "quality_documents"
MANIFEST_PATH = Path(CHROMA_DIR) / ".ingest_manifest.json"


def load_manifest() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def main() -> None:
    full_rebuild = "--full" in sys.argv

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or api_key.startswith("sk-..."):
        print("ERROR: OPENAI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    import chromadb

    if full_rebuild:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        if COLLECTION_NAME in [c.name for c in client.list_collections()]:
            client.delete_collection(COLLECTION_NAME)

    collection = get_chroma_collection()

    doc_files = sorted(DOCS_DIR.glob("*.md")) + sorted(DOCS_DIR.glob("*.html"))
    if not doc_files:
        print(f"ERROR: no documents found in {DOCS_DIR}", file=sys.stderr)
        sys.exit(1)

    manifest = {} if full_rebuild else load_manifest()
    new_manifest = dict(manifest)

    changed_files = [(p, file_hash(p)) for p in doc_files]
    to_ingest = [(p, h) for p, h in changed_files if manifest.get(str(p)) != h]
    unchanged_count = len(changed_files) - len(to_ingest)

    if not to_ingest:
        print(f"No new or changed documents ({unchanged_count} already up to date). Nothing to do.")
        print("Pass --full to force a full rebuild.")
        return

    total_chunks = 0
    for path, digest in to_ingest:
        metadata, body = load_document(path)
        doc_id = metadata["doc_id"]

        # Remove any existing chunks for this doc_id (covers the case where
        # a changed file has a different chunk count than before).
        existing = collection.get(where={"doc_id": doc_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

        chunks = chunk_text(body)
        ids = [f"{doc_id}-chunk-{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_id,
                "doc_type": metadata["doc_type"],
                "title": metadata["title"],
                "status": metadata["status"],
                "effective_date": str(metadata["effective_date"]),
                "version": metadata["version"],
            }
            for _ in chunks
        ]
        collection.add(ids=ids, documents=chunks, metadatas=metadatas)
        total_chunks += len(chunks)
        new_manifest[str(path)] = digest
        print(f"  {doc_id} ({metadata['doc_type']}, {path.suffix}): {len(chunks)} chunk(s) [ingested]")

    save_manifest(new_manifest)
    print(
        f"\nIngested {len(to_ingest)} new/changed document(s), {total_chunks} chunk(s) "
        f"into '{COLLECTION_NAME}' ({unchanged_count} unchanged, skipped)."
    )
    print(f"Chroma persisted at: {CHROMA_DIR}")


if __name__ == "__main__":
    main()

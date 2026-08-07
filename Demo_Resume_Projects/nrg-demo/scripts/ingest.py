"""Bulk-ingest all documents in data/synthetic_docs/ through the same
nrg_chains.ingest.ingest_document() generator the Streamlit KB tab's
single-file upload uses -- unlike copilot-demo's bulk CLI (which bypasses
Postgres versioning and writes straight to Chroma), NRG has no separate
"fast path": every document, bulk or single-upload, goes through parse ->
chunk -> version-check -> publish, since the RabbitMQ publish step is the
whole point of Phase 2's design and skipping it here would leave bulk-
ingested docs permanently unindexed (nothing else embeds/upserts them into
Qdrant except the consumer reacting to that publish).

Run scripts/consume_ingestion_events.py in a second terminal before or
after this script to actually index what gets published here.

Usage: python scripts/ingest.py [--full]
  --full: re-ingest every document even if its content hash matches the
          currently active kb_documents version (normally a no-op).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from nrg_chains.ingest import DOCS_DIR, ingest_document


def main() -> None:
    doc_files = sorted(DOCS_DIR.glob("*.md")) + sorted(DOCS_DIR.glob("*.pdf"))
    if not doc_files:
        print(f"ERROR: no documents found in {DOCS_DIR}", file=sys.stderr)
        sys.exit(1)

    published, no_op, failed = 0, 0, 0

    for path in doc_files:
        gen = ingest_document(path.read_bytes(), path.name, "bulk-ingest-script")
        try:
            while True:
                step = next(gen)
                if step.stage == "error":
                    print(f"  {path.name}: ERROR - {step.detail}")
        except StopIteration as stop:
            result = stop.value
            if result.status == "no_op":
                print(f"  {result.doc_id} v{result.version}: unchanged, skipped")
                no_op += 1
            else:
                print(
                    f"  {result.doc_id} v{result.version} ({result.doc_type}): "
                    f"published for async indexing (event #{result.ingestion_event_id})"
                )
                published += 1
        except ValueError as e:
            print(f"  {path.name}: FAILED - {e}")
            failed += 1

    print(
        f"\n{published} document(s) published to RabbitMQ, {no_op} unchanged, {failed} failed "
        f"(out of {len(doc_files)} total)."
    )
    if published:
        print(
            "Run 'python scripts/consume_ingestion_events.py' (if not already running) "
            "to embed and index these into Qdrant."
        )


if __name__ == "__main__":
    main()

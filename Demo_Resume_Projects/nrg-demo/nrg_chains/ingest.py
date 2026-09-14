"""Synchronous half of the ingestion pipeline: parse -> chunk ->
version-check against Postgres kb_documents -> publish a `document_processed`
event to RabbitMQ. Deliberately does NOT embed or write to Qdrant here --
that happens asynchronously in scripts/consume_ingestion_events.py, which is
the deliberate visual/architectural contrast with copilot-demo's ingest
(which embeds+stores synchronously in the same call). This mirrors
NRG_Energy_Architecture_Deep_Dive.md's Textract --> SNS/SQS --> OpenSearch
async pattern (§2.6).

ingest_document() is a Generator[IngestStep, None, KBDocument], same shape
as copilot-demo's copilot_agents/kb_ingest.ingest_document(), so the
Streamlit KB tab can show live progress via st.status(). The one behavioral
difference: the final "done" step here means "published, awaiting async
indexing" rather than "fully indexed and searchable" -- KBDocument.status
reflects that ("processing" vs "active").
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Generator

from nrg_retrieval.audit import append_audit_entry
from nrg_retrieval.document_parser import chunk_text, load_document
from nrg_retrieval.postgres_client import (
    get_active_version,
    get_pg_connection,
    insert_ingestion_event,
    insert_kb_document,
    supersede_kb_document,
)
from nrg_retrieval.rabbitmq_events import publish_document_processed

DOCS_DIR = Path(__file__).parent.parent / "data" / "synthetic_docs"


@dataclass
class IngestStep:
    stage: str  # "parsing" | "chunking" | "versioning" | "publishing" | "done" | "error"
    detail: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class KBDocument:
    doc_id: str
    version: int
    title: str
    doc_type: str
    plan_type: str | None
    file_path: str
    file_format: str
    content_hash: str
    status: str  # "processing" (published, not yet indexed) | "no_op"
    is_new_version: bool
    ingestion_event_id: int | None = None


def content_hash(content_bytes: bytes) -> str:
    import hashlib

    return hashlib.sha256(content_bytes).hexdigest()


def ingest_document(
    file_bytes: bytes, filename: str, uploaded_by: str
) -> Generator[IngestStep, None, KBDocument]:
    suffix = Path(filename).suffix
    if suffix not in (".md", ".pdf"):
        yield IngestStep("error", {"message": f"Unsupported file type: {suffix}"})
        raise ValueError(f"Unsupported file type: {suffix}")

    yield IngestStep("parsing", {"filename": filename})

    # load_document() takes a path (unstructured.io's PDF partitioner reads
    # from disk, not bytes), so a temp copy is written first if this came
    # from an in-memory upload rather than the bulk-ingest folder scan.
    tmp_path = DOCS_DIR / f".tmp-{filename}"
    tmp_path.write_bytes(file_bytes)
    try:
        metadata, body = load_document(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    doc_id = metadata["doc_id"]
    digest = content_hash(file_bytes)
    # load_document() already validated plan_rate docs carry a plan_type;
    # other doc_types may or may not, so just pass through whatever's there.
    plan_type = metadata.get("plan_type")

    yield IngestStep(
        "parsing",
        {"doc_id": doc_id, "doc_type": metadata["doc_type"], "title": metadata["title"]},
    )

    yield IngestStep("chunking", {"doc_id": doc_id})
    chunks = chunk_text(body)
    yield IngestStep("chunking", {"doc_id": doc_id, "chunk_count": len(chunks)})

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            yield IngestStep("versioning", {"doc_id": doc_id, "checking_for": "existing active version"})
            active = get_active_version(cur, doc_id)

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
                    plan_type=plan_type,
                    file_path=active[3],
                    file_format=suffix.lstrip("."),
                    content_hash=digest,
                    status="no_op",
                    is_new_version=False,
                )

            new_version = 1
            if active is not None:
                new_version = active[1] + 1
                supersede_kb_document(cur, active[0])
                yield IngestStep(
                    "versioning",
                    {
                        "doc_id": doc_id,
                        "outcome": "new_version",
                        "previous_version": active[1],
                        "new_version": new_version,
                    },
                )
            else:
                yield IngestStep(
                    "versioning", {"doc_id": doc_id, "outcome": "new_document", "version": new_version}
                )

            versioned_filename = f"{doc_id}-v{new_version}{suffix}"
            file_path = DOCS_DIR / versioned_filename
            file_path.write_bytes(file_bytes)

            insert_kb_document(
                cur,
                doc_id=doc_id,
                version=new_version,
                title=metadata["title"],
                doc_type=metadata["doc_type"],
                plan_type=plan_type,
                file_path=str(file_path),
                file_format=suffix.lstrip("."),
                content_hash=digest,
                effective_date=metadata.get("effective_date") or None,
                uploaded_by=uploaded_by,
            )

            yield IngestStep(
                "publishing",
                {"doc_id": doc_id, "queue": "document_processed", "chunk_count": len(chunks)},
            )

            chunk_payloads = [
                {
                    "chunk_index": i,
                    "text": chunk,
                    "metadata": {
                        "doc_id": doc_id,
                        "doc_type": metadata["doc_type"],
                        "title": metadata["title"],
                        "status": "active",
                        "effective_date": str(metadata.get("effective_date") or ""),
                        "plan_type": plan_type,
                        "version": new_version,
                        "chunk_index": i,
                        "source_file": filename,
                    },
                }
                for i, chunk in enumerate(chunks)
            ]

            published_payload = asyncio.run(
                publish_document_processed(
                    doc_id=doc_id,
                    version=new_version,
                    file_path=str(file_path),
                    content_hash=digest,
                    chunks=chunk_payloads,
                )
            )

            event_id = insert_ingestion_event(
                cur,
                doc_id=doc_id,
                version=new_version,
                chunk_count=len(chunks),
                payload=published_payload,
            )

        conn.commit()

        # audit_log write happens on its own connection/transaction, same
        # convention as copilot-demo's append_audit_entry() calls -- keeps
        # the hash-chain append decoupled from the kb_documents/
        # ingestion_events transaction above (a failure writing the audit
        # entry shouldn't roll back a publish that already succeeded).
        append_audit_entry(
            get_pg_connection(),
            event_type="document_ingested",
            payload={"doc_id": doc_id, "version": new_version, "chunk_count": len(chunks), "ingestion_event_id": event_id},
            actor=uploaded_by,
        )

        yield IngestStep(
            "done",
            {
                "doc_id": doc_id,
                "version": new_version,
                "chunk_count": len(chunks),
                "outcome": "published",
                "ingestion_event_id": event_id,
            },
        )
        return KBDocument(
            doc_id=doc_id,
            version=new_version,
            title=metadata["title"],
            doc_type=metadata["doc_type"],
            plan_type=plan_type,
            file_path=str(file_path),
            file_format=suffix.lstrip("."),
            content_hash=digest,
            status="processing",
            is_new_version=True,
            ingestion_event_id=event_id,
        )
    finally:
        conn.close()

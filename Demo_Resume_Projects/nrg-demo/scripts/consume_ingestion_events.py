"""Standalone RabbitMQ consumer -- the asynchronous half of ingestion.
Runs as its own OS process (`python scripts/consume_ingestion_events.py`),
separate from the Streamlit UI, deliberately: Streamlit reruns the whole
script on every interaction, so a background thread started inside the app
would either leak/duplicate consumers across reruns or need fragile
session_state singleton bookkeeping. A real second process is also the more
convincing "this is genuinely async" demo -- it can be killed, restarted,
and inspected independently of the UI (see NRG_Implementation_Plan.md
Phase 2 verification: stop this script, re-ingest a doc, confirm the
message sits durably in RabbitMQ's management UI until this script runs
again).

Per message: computes a dense embedding (OpenAI text-embedding-3-small,
diskcache-wrapped) and a sparse embedding (fastembed Qdrant/bm25) for each
chunk, upserts into Qdrant, marks the corresponding ingestion_events row
'consumed'. On failure, nacks with requeue up to MAX_DELIVERY_ATTEMPTS,
after which requeue=False routes the message to the DLQ (RabbitMQ does
this automatically via the x-dead-letter-exchange binding declared in
nrg_retrieval/rabbitmq_events.py).

Usage: python scripts/consume_ingestion_events.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import aio_pika
from fastembed import SparseTextEmbedding
from langchain_openai import OpenAIEmbeddings
from qdrant_client.models import PointStruct, SparseVector

from nrg_chains.cache import get_cached_embeddings_batch, invalidate_retrieval_cache
from nrg_retrieval.postgres_client import get_pg_connection, mark_ingestion_event_consumed, mark_ingestion_event_failed
from nrg_retrieval.qdrant_client import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ensure_collection,
)
from nrg_retrieval.rabbitmq_events import MAX_DELIVERY_ATTEMPTS, QUEUE_NAME, rabbitmq_url

DENSE_MODEL = "text-embedding-3-small"

_dense_embedder = OpenAIEmbeddings(model=DENSE_MODEL)
_sparse_embedder = SparseTextEmbedding(model_name="Qdrant/bm25")


def _embed_dense_batch(texts: list[str]) -> list[list[float]]:
    return _dense_embedder.embed_documents(texts)


def _point_id(doc_id: str, chunk_index: int) -> str:
    # Qdrant requires point IDs to be an unsigned int or a UUID -- a plain
    # "{doc_id}-chunk-{i}" string (Chroma's convention, used by
    # copilot-demo) is rejected, so a deterministic UUID5 derived from that
    # same string is used instead. Deterministic means re-ingesting the
    # same doc_id/chunk_index always maps to the same point, so an upsert
    # correctly replaces rather than duplicates.
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}-chunk-{chunk_index}"))


async def process_message(message: aio_pika.abc.AbstractIncomingMessage, qdrant_client) -> None:
    payload = json.loads(message.body)
    doc_id = payload["doc_id"]
    version = payload["version"]
    chunks = payload["chunks"]

    texts = [c["text"] for c in chunks]
    dense_vectors = get_cached_embeddings_batch(texts, DENSE_MODEL, _embed_dense_batch)
    sparse_vectors = list(_sparse_embedder.embed(texts))

    points = []
    for chunk, dense_vec, sparse_vec in zip(chunks, dense_vectors, sparse_vectors):
        # payload carries both the metadata fields (doc_id, doc_type, etc.,
        # used for filtering) and the chunk's own text (needed at query time
        # to build the excerpt/context passed to the LLM -- hybrid_search.py
        # reads it back via point.payload["text"]).
        point_payload = {**chunk["metadata"], "text": chunk["text"]}
        points.append(
            PointStruct(
                id=_point_id(doc_id, chunk["chunk_index"]),
                vector={
                    DENSE_VECTOR_NAME: dense_vec,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=sparse_vec.indices.tolist(), values=sparse_vec.values.tolist()
                    ),
                },
                payload=point_payload,
            )
        )

    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            mark_ingestion_event_consumed(cur, doc_id, version)
        conn.commit()
    finally:
        conn.close()

    invalidate_retrieval_cache()

    print(f"[consumed] {doc_id} v{version} -- {len(points)} points upserted into Qdrant")


async def on_message(
    message: aio_pika.abc.AbstractIncomingMessage,
    qdrant_client,
    channel: aio_pika.abc.AbstractChannel,
) -> None:
    attempts = (message.headers or {}).get("x-delivery-attempts", 0) + 1

    try:
        await process_message(message, qdrant_client)
        await message.ack()
    except Exception as exc:
        print(f"[error] attempt {attempts}/{MAX_DELIVERY_ATTEMPTS} failed: {exc}")

        if attempts >= MAX_DELIVERY_ATTEMPTS:
            payload = json.loads(message.body)
            conn = get_pg_connection()
            try:
                with conn.cursor() as cur:
                    mark_ingestion_event_failed(cur, payload["doc_id"], payload["version"])
                conn.commit()
            finally:
                conn.close()
            print(f"[dead-lettered] {payload['doc_id']} v{payload['version']} after {attempts} attempts")
            # requeue=False routes to the DLQ via the queue's
            # x-dead-letter-exchange binding, rather than being discarded.
            await message.nack(requeue=False)
        else:
            # Re-publish with an incremented attempt counter rather than a
            # plain requeue=True nack -- AMQP's basic.nack requeue doesn't
            # let us mutate headers, and RabbitMQ has no built-in per-message
            # retry counter, so tracking attempts requires the consumer to
            # own the increment itself via re-publish.
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=message.body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers={"x-delivery-attempts": attempts},
                ),
                routing_key=QUEUE_NAME,
            )
            await message.ack()  # ack the original; the re-published copy is the retry


async def main() -> None:
    print("Ensuring Qdrant collection exists...")
    qdrant_client = ensure_collection()

    print(f"Connecting to RabbitMQ ({rabbitmq_url().split('@')[-1]})...")
    connection = await aio_pika.connect_robust(rabbitmq_url())
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        from nrg_retrieval.rabbitmq_events import declare_topology

        queue = await declare_topology(channel)

        print(f"Consuming from '{QUEUE_NAME}' -- Ctrl+C to stop.")

        # Manual ack/nack throughout (on_message calls message.ack()/
        # message.nack() itself, including the re-publish-with-incremented-
        # attempts retry path) -- no_ack=False is the default, and no
        # message.process() context manager is used here since that would
        # auto-ack/reject on top of the manual calls on_message already
        # makes, which is redundant at best and double-acks at worst.
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                await on_message(message, qdrant_client, channel)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")

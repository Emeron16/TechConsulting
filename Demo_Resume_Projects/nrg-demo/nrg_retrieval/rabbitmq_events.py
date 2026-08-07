"""Async ingestion messaging -- the Amazon SNS+SQS analog (per
NRG_Energy_Architecture_Deep_Dive.md §2.6: "Textract's asynchronous API...
publishes a completion notification via SNS, which is typically consumed
through an SQS queue to trigger the next step -- re-embedding and
re-indexing"). Here: nrg_chains/ingest.py parses+chunks a document
synchronously, then publishes a `document_processed` event; a standalone
consumer (scripts/consume_ingestion_events.py) embeds and indexes into
Qdrant asynchronously, decoupled from the publisher.

Exchange/queue topology:
  nrg.ingestion (direct exchange)
    -> document_processed (durable queue, routing key "document.processed")
         -> on repeated nack (retry exhausted): dead-lettered to
    -> document_processed.dlq (durable queue, routing key "document.processed.dlq")

A direct exchange is sufficient here (not fanout/topic) since there is
exactly one consumer type for this event in this demo -- fanout/topic
would only earn their complexity if multiple independent consumer types
existed.
"""
import json
import os
from datetime import datetime, timezone

import aio_pika

EXCHANGE_NAME = "nrg.ingestion"
QUEUE_NAME = "document_processed"
ROUTING_KEY = "document.processed"

DLQ_EXCHANGE_NAME = "nrg.ingestion.dlq"
DLQ_QUEUE_NAME = "document_processed.dlq"
DLQ_ROUTING_KEY = "document.processed.dlq"

MAX_DELIVERY_ATTEMPTS = 3


def rabbitmq_url() -> str:
    user = os.environ.get("RABBITMQ_USER", "nrg")
    password = os.environ.get("RABBITMQ_PASSWORD", "nrg")
    host = os.environ.get("RABBITMQ_HOST", "localhost")
    port = os.environ.get("RABBITMQ_PORT", "5673")
    return f"amqp://{user}:{password}@{host}:{port}/"


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> aio_pika.abc.AbstractQueue:
    """Idempotent -- declares the DLQ exchange/queue first, then the
    primary exchange/queue with its `x-dead-letter-exchange` pointed at the
    DLQ, so a message that's nacked with requeue=False after exhausting
    MAX_DELIVERY_ATTEMPTS is automatically routed to the DLQ by RabbitMQ
    itself rather than the consumer having to re-publish it manually.
    Called by both the publisher and the consumer at connection time (same
    pattern as copilot-demo's review_queue.py declaring its queue on every
    publish), so whichever side starts first creates the topology.
    """
    dlq_exchange = await channel.declare_exchange(
        DLQ_EXCHANGE_NAME, aio_pika.ExchangeType.DIRECT, durable=True
    )
    dlq_queue = await channel.declare_queue(DLQ_QUEUE_NAME, durable=True)
    await dlq_queue.bind(dlq_exchange, routing_key=DLQ_ROUTING_KEY)

    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.DIRECT, durable=True
    )
    queue = await channel.declare_queue(
        QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLQ_EXCHANGE_NAME,
            "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
        },
    )
    await queue.bind(exchange, routing_key=ROUTING_KEY)
    return queue


async def publish_document_processed(
    doc_id: str,
    version: int,
    file_path: str,
    content_hash: str,
    chunks: list[dict],
) -> dict:
    """Publishes the 'document processed' event -- chunks are included in
    the message body (not just a doc_id pointer) since the synchronous
    parse+chunk step already did the expensive work; the consumer only
    needs to embed and upsert, not re-parse. Returns the payload dict that
    was published, so the caller can also write it into the
    ingestion_events.payload JSONB column for the Flow/Audit tabs.
    """
    payload = {
        "doc_id": doc_id,
        "version": version,
        "file_path": file_path,
        "content_hash": content_hash,
        "chunks": chunks,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    connection = await aio_pika.connect_robust(rabbitmq_url())
    async with connection:
        channel = await connection.channel()
        await declare_topology(channel)
        ingestion_exchange = await channel.get_exchange(EXCHANGE_NAME)
        await ingestion_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers={"x-delivery-attempts": 0},
            ),
            routing_key=ROUTING_KEY,
        )

    return payload

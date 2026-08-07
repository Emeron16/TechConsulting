"""Async workflow layer: publishes "needs review" events to RabbitMQ after
the Deviation Review or CAPA Decision Support agent drafts an answer --
mirrors the original architecture's DEVAGENT/CAPAAGENT --> SERVICEBUS edges.

The RabbitMQ message is the durable, replayable event record (what
scripts/consume_review_queue.py can re-drain from if the review_queue table
is ever rebuilt) -- but the row is also written straight to Postgres as
'pending' here, synchronously, so a run is visibly awaiting human review the
moment it completes, without a separate manual drain step in between. Two
writes of the same fact, same as the original architecture's Service Bus
message existing independently of the Review & Approval Queue's own
persisted state.
"""
import json
import os

import aio_pika

from mcp_servers.common import get_pg_connection

QUEUE_NAME = "needs_review"

REVIEW_TRIGGERING_AGENTS = {"Deviation Review Agent", "CAPA Decision Support Agent"}


def rabbitmq_url() -> str:
    user = os.environ.get("RABBITMQ_USER", "copilot")
    password = os.environ.get("RABBITMQ_PASSWORD", "copilot")
    host = os.environ.get("RABBITMQ_HOST", "localhost")
    port = os.environ.get("RABBITMQ_PORT", "5672")
    return f"amqp://{user}:{password}@{host}:{port}/"


async def publish_needs_review(question: str, draft_answer: str, agent_name: str) -> int:
    """Publishes a durable "needs human review" message to RabbitMQ and
    inserts the corresponding review_queue row as 'pending'. Only called for
    agents whose output becomes a quality decision (Deviation, CAPA) --
    matches the original diagram, where SOP/Batch agents don't route through
    the review queue on their own. Returns the new review_queue.id so the
    caller can track this specific run's review status (rather than matching
    on question text, which collides across repeated identical questions).
    """
    connection = await aio_pika.connect_robust(rabbitmq_url())
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        payload = {
            "question": question,
            "draft_answer": draft_answer,
            "agent_name": agent_name,
        }
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue.name,
        )

    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO review_queue (question, draft_answer, citations, agent_name)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (question, draft_answer, json.dumps([]), agent_name),
        )
        review_id = cur.fetchone()[0]
        conn.commit()

    return review_id

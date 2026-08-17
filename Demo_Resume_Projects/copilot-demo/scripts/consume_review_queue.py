"""Disaster-recovery replay tool: drains any messages still sitting in the
RabbitMQ 'needs_review' queue into the Postgres review_queue table.

Under normal operation this is a no-op -- copilot_agents.review_queue.
publish_needs_review() now writes the review_queue row synchronously at
publish time, so items already appear as 'pending' without running this
script. This exists for the case where the review_queue table was reset/lost
but RabbitMQ (a durable queue) still holds undelivered messages -- running
this replays them back into Postgres.

Usage: python scripts/consume_review_queue.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import aio_pika
import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from copilot_agents.review_queue import QUEUE_NAME, rabbitmq_url
from mcp_servers.common import get_pg_connection


async def main() -> None:
    connection = await aio_pika.connect_robust(rabbitmq_url())
    drained = 0
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        with get_pg_connection() as conn, conn.cursor() as cur:
            while True:
                message = await queue.get(fail=False, timeout=2)
                if message is None:
                    break
                async with message.process():
                    payload = json.loads(message.body.decode())
                    structured_payload = payload.get("structured_payload")
                    cur.execute(
                        """
                        INSERT INTO review_queue (question, draft_answer, citations, agent_name,
                                                   linked_record_type, linked_record_id, structured_payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            payload["question"],
                            payload["draft_answer"],
                            json.dumps([]),
                            payload["agent_name"],
                            payload.get("linked_record_type"),
                            payload.get("linked_record_id"),
                            json.dumps(structured_payload) if structured_payload is not None else None,
                        ),
                    )
                    review_id = cur.fetchone()[0]
                    conn.commit()
                    drained += 1
                    print(f"  Queued review_queue #{review_id}: {payload['question'][:60]}...")

    print(f"\nDrained {drained} message(s) into review_queue.")


if __name__ == "__main__":
    asyncio.run(main())

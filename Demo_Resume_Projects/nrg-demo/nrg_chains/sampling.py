"""Statistical sampling write -- the human-in-the-loop layer, and the
deliberate architectural contrast with copilot-demo's mandatory pre-publish
review queue. EVERY answer is logged here immediately, unconditionally,
and the user already has the answer by the time this runs -- nothing here
ever blocks, gates, or gets awaited by the response path. Compliance/Legal
samples from this log after the fact (see the Compliance Review tab, built
in Phase 7) rather than approving each answer before it reaches the agent.
See NRG_Energy_Architecture_Deep_Dive.md §2.1 and §3 for why this differs
from the Novartis project's per-answer sign-off requirement.
"""
import json

from nrg_retrieval.postgres_client import get_pg_connection


def log_sampled_answer(
    question: str,
    answer: str,
    doc_type_classified: str | None,
    citations: list[str],
    confidence: str | None,
) -> int:
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sampled_answers (question, answer, doc_type_classified, citations, confidence)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (question, answer, doc_type_classified, json.dumps(citations), confidence),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    finally:
        conn.close()

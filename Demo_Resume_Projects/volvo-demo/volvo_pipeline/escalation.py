"""The safety-escalation decision -- the third, distinct human-in-the-loop
pattern across this repo's three demos (not Novartis's mandatory
pre-publish gate, not NRG's after-the-fact statistical sampling). Per
Volvo_Architecture_Deep_Dive.md §2.1/§3, a misclassified safety_concern
complaint risks delaying a legally mandated TREAD Act report, so this is a
real routing decision to a Service Operations Manager review queue, not a
passive annotation.

Two trigger conditions:
  - direct_classification: the case itself was classified safety_concern
    above threshold.
  - recurring_pattern: the case's own classification didn't flag
    safety_concern, but RECURRING_PATTERN_THRESHOLD or more of its top-K
    similar cases are themselves already safety-flagged -- catching a
    slow-building pattern across multiple non-obviously-worded cases,
    which is the specific capability the architecture doc's Service
    Operations Manager role exists to use.
"""
from __future__ import annotations

import psycopg

from volvo_pipeline.schemas import EscalationDecision
from volvo_retrieval.postgres_client import get_safety_flagged_case_ids

# Reasonable, demo-scale default -- 2 or more of the top-5 similar cases
# already flagged is treated as a recurring pattern. No architecture-doc
# citation backs this specific number; it's a stated, defensible design
# assumption per Volvo_Implementation_Plan.md's "Remaining Minor Assumptions".
RECURRING_PATTERN_THRESHOLD = 2


def check_escalation(
    conn: psycopg.Connection,
    case_id: str,
    categories: list[str],
    similar_cases: list[dict],
) -> EscalationDecision | None:
    if "safety_concern" in categories:
        return EscalationDecision(trigger_reason="direct_classification")

    similar_case_ids = [c["case_id"] for c in similar_cases if c["case_id"] != case_id]
    flagged = get_safety_flagged_case_ids(conn, similar_case_ids)
    if len(flagged) >= RECURRING_PATTERN_THRESHOLD:
        return EscalationDecision(trigger_reason="recurring_pattern", related_case_ids=sorted(flagged))

    return None

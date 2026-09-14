"""Shared dataclasses for the new-case pipeline. CaseStep's `stage` values
map 1:1 to Airflow task IDs (Phase 7), so Streamlit's polling loop (Phase 9)
can translate Airflow task-instance states directly into CaseStep-shaped
progress without a separate parallel vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CaseStep:
    stage: str  # "preprocess" | "classify" | "extract_entities" | "embed" |
    # "find_similar_cases" | "index_and_check_escalation" | "queued" | "done" | "failed"
    detail: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class EscalationDecision:
    trigger_reason: str  # "direct_classification" | "recurring_pattern"
    related_case_ids: list[str] = field(default_factory=list)

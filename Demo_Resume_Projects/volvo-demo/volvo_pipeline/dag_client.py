"""Client for triggering and polling the volvo_case_pipeline Airflow DAG
via its REST API -- called by Streamlit's Submit New Case tab (Phase 9) to
drive one real DAG run per submitted case, and by the Model Info tab's
read-only DAG-run-history panel.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "volvo_case_pipeline")


def _base_url() -> str:
    return os.environ.get("AIRFLOW_BASE_URL", "http://localhost:8180")


def _auth() -> tuple[str, str]:
    return (
        os.environ.get("AIRFLOW_USERNAME", "airflow"),
        os.environ.get("AIRFLOW_PASSWORD", "airflow"),
    )


def trigger_dag_run(case_data: dict) -> str:
    """Triggers one DAG run with case_data passed as `conf`. Returns the
    generated dag_run_id.
    """
    response = requests.post(
        f"{_base_url()}/api/v1/dags/{DAG_ID}/dagRuns",
        json={"conf": case_data},
        auth=_auth(),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["dag_run_id"]


def get_dag_run_state(dag_run_id: str) -> str:
    response = requests.get(
        f"{_base_url()}/api/v1/dags/{DAG_ID}/dagRuns/{dag_run_id}",
        auth=_auth(),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["state"]


def get_task_instances(dag_run_id: str) -> list[dict]:
    """Returns each task instance's id and state for a given dag_run_id --
    Streamlit's polling loop maps these onto CaseStep stages for live
    per-stage UI progress.
    """
    response = requests.get(
        f"{_base_url()}/api/v1/dags/{DAG_ID}/dagRuns/{dag_run_id}/taskInstances",
        auth=_auth(),
        timeout=10,
    )
    response.raise_for_status()
    return [
        {"task_id": t["task_id"], "state": t["state"]}
        for t in response.json()["task_instances"]
    ]


def list_recent_dag_runs(limit: int = 20) -> list[dict]:
    response = requests.get(
        f"{_base_url()}/api/v1/dags/{DAG_ID}/dagRuns",
        params={"order_by": "-start_date", "limit": limit},
        auth=_auth(),
        timeout=10,
    )
    response.raise_for_status()
    return [
        {
            "dag_run_id": r["dag_run_id"],
            "state": r["state"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
        }
        for r in response.json()["dag_runs"]
    ]

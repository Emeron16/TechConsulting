"""Real Airflow DAG modeling Volvo_Architecture_Deep_Dive.md's new-case
sequence: preprocess -> classify -> extract entities -> embed -> find
similar cases -> index + escalation check. Triggered once per submitted
case via POST /dags/volvo_case_pipeline/dagRuns with case data as `conf`
(Streamlit's Submit New Case tab, Phase 9) -- schedule=None, purely
trigger-driven, never cron.

Every task calls the Phase 6 FastAPI service over HTTP
(host.docker.internal:8100, confirmed reachable from inside this Docker
network during Phase 7 setup) -- this DAG never imports
volvo_models/volvo_pipeline/volvo_retrieval directly, keeping FastAPI as
the single serving layer per Volvo_Implementation_Plan.md's design
decision.
"""
from __future__ import annotations

import json
from datetime import datetime

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

FASTAPI_BASE_URL = "http://host.docker.internal:8100"


def _preprocess(**context) -> None:
    conf = context["dag_run"].conf
    response = requests.post(f"{FASTAPI_BASE_URL}/preprocess", json={"text": conf["narrative_text"]}, timeout=30)
    response.raise_for_status()
    context["ti"].xcom_push(key="normalized_text", value=response.json()["normalized_text"])


def _classify(**context) -> None:
    text = context["ti"].xcom_pull(key="normalized_text", task_ids="preprocess")
    response = requests.post(f"{FASTAPI_BASE_URL}/classify", json={"text": text}, timeout=30)
    response.raise_for_status()
    context["ti"].xcom_push(key="classifications", value=response.json()["classifications"])


def _extract_entities(**context) -> None:
    text = context["ti"].xcom_pull(key="normalized_text", task_ids="preprocess")
    response = requests.post(f"{FASTAPI_BASE_URL}/extract-entities", json={"text": text}, timeout=30)
    response.raise_for_status()
    context["ti"].xcom_push(key="entities", value=response.json()["entities"])


def _embed(**context) -> None:
    text = context["ti"].xcom_pull(key="normalized_text", task_ids="preprocess")
    response = requests.post(f"{FASTAPI_BASE_URL}/embed", json={"text": text}, timeout=30)
    response.raise_for_status()
    context["ti"].xcom_push(key="vector", value=response.json()["vector"])


def _find_similar_cases(**context) -> None:
    text = context["ti"].xcom_pull(key="normalized_text", task_ids="preprocess")
    response = requests.post(f"{FASTAPI_BASE_URL}/similar-cases", json={"text": text, "k": 5}, timeout=30)
    response.raise_for_status()
    context["ti"].xcom_push(key="similar_cases", value=response.json()["similar_cases"])


def _index_and_check_escalation(**context) -> None:
    conf = context["dag_run"].conf
    ti = context["ti"]
    text = ti.xcom_pull(key="normalized_text", task_ids="preprocess")
    classifications = ti.xcom_pull(key="classifications", task_ids="classify")
    entities = ti.xcom_pull(key="entities", task_ids="extract_entities")
    vector = ti.xcom_pull(key="vector", task_ids="embed")
    similar_cases = ti.xcom_pull(key="similar_cases", task_ids="find_similar_cases")

    payload = {
        "case_id": conf["case_id"],
        "vin": conf["vin"],
        "narrative_text": text,
        "submitted_by": conf["submitted_by"],
        "dealer_location": conf.get("dealer_location"),
        "mileage": conf.get("mileage"),
        "vehicle_model": conf.get("vehicle_model"),
        "model_year": conf.get("model_year"),
        "classifications": classifications,
        "entities": entities,
        "narrative_vector": vector,
        "similar_cases": similar_cases,
    }
    response = requests.post(f"{FASTAPI_BASE_URL}/index-case", json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    ti.xcom_push(key="index_result", value=result)
    print(f"index-case result: {json.dumps(result)}")


with DAG(
    dag_id="volvo_case_pipeline",
    description="New warranty case: preprocess -> classify -> NER -> embed -> similarity -> index/escalate",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["volvo", "warranty"],
) as dag:
    preprocess = PythonOperator(task_id="preprocess", python_callable=_preprocess)
    classify = PythonOperator(task_id="classify", python_callable=_classify)
    extract_entities = PythonOperator(task_id="extract_entities", python_callable=_extract_entities)
    embed = PythonOperator(task_id="embed", python_callable=_embed)
    find_similar_cases = PythonOperator(task_id="find_similar_cases", python_callable=_find_similar_cases)
    index_and_check_escalation = PythonOperator(
        task_id="index_and_check_escalation", python_callable=_index_and_check_escalation
    )

    preprocess >> classify >> extract_entities >> embed >> find_similar_cases >> index_and_check_escalation

"""Renders the training pipeline diagram: synthetic data -> PySpark
preprocessing -> DistilBERT fine-tuning (SageMaker analog) -> MLflow
logging. Second diagram, matching NRG's two-diagram precedent (ask-flow +
ingest-flow) -- this repo's Volvo demo has an equivalent split between the
live per-case pipeline (flow_diagram.py) and the offline training pipeline
that produced the model that pipeline uses.

Reads real MLflow run data by mlflow.search_runs() rather than a trace
object, since training runs as a standalone script (scripts/
train_classifier.py), not something Streamlit triggers live.
"""
import os
from pathlib import Path

from volvo_pipeline.diagram_common import CSS, REAL_TAG, arrow, esc, placeholder, stage

ROOT = Path(__file__).parent.parent


def render_training_flow_html() -> str:
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    import mlflow

    mlflow.set_tracking_uri(f"file:{ROOT / 'mlruns'}")

    parts: list[str] = [CSS, '<div class="flow-wrap"><div class="flow-col">']

    parts.append('<div class="band-label">Live Run</div>')
    parts.append(
        stage(
            "real-tool",
            "Synthetic Training Data",
            sub="scripts/generate_synthetic_cases.py",
            detail="120 authored warranty narratives, heuristically multi-label-tagged into 8 categories",
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    parts.append(
        stage(
            "real-tool",
            "PySpark Preprocessing",
            sub="local[*] mode — abbreviation expansion + boilerplate stripping",
            detail="scripts/preprocess_pyspark.py",
            tag=REAL_TAG,
        )
    )
    parts.append(arrow())

    try:
        runs = mlflow.search_runs(experiment_names=["volvo_warranty_classifier"])
    except Exception:
        runs = None

    if runs is not None and not runs.empty:
        latest = runs.iloc[0]
        detail_lines = [
            f"base_model = {latest.get('params.base_model', '?')}",
            f"epochs = {int(latest.get('params.num_epochs', 0))}",
            f"train_size = {int(latest.get('params.train_size', 0))}",
            f"micro_f1 = {latest.get('metrics.eval_micro_f1', 0):.3f}",
            f"macro_f1 = {latest.get('metrics.eval_macro_f1', 0):.3f}",
        ]
        parts.append(
            stage(
                "real-tool",
                "DistilBERT Fine-Tuning",
                sub="SageMaker analog — local CPU Trainer run",
                detail="\n".join(detail_lines),
                tag=REAL_TAG,
            )
        )
        parts.append(arrow())

        parts.append(
            stage(
                "real-audit",
                "MLflow: Experiment Logged",
                sub=f"run_id = {latest.get('run_id', '?')}",
                detail="Params, per-epoch + final metrics, confusion-matrix artifact, and model all logged.",
                tag=REAL_TAG,
            )
        )
    else:
        parts.append(
            stage(
                "outcome-noop",
                "DistilBERT Fine-Tuning",
                sub="No MLflow run found — run scripts/train_classifier.py first",
            )
        )

    parts.append(f'<div class="band-label">{esc("Data & Cataloging (original architecture)")}</div>')
    parts.append(
        '<div class="side-by-side">'
        + placeholder("Amazon S3", "Raw dealer records — plain local filesystem used instead")
        + placeholder("AWS Glue", "ETL + data catalog — PySpark covers the ETL half; no catalog tool stood up")
        + "</div>"
    )

    parts.append(f'<div class="band-label">{esc("Observability (original architecture)")}</div>')
    parts.append(placeholder("Amazon CloudWatch", "Training-job monitoring"))

    parts.append("</div></div>")
    return "".join(parts)

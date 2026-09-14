"""Fine-tunes a real DistilBERT multi-label classifier on the synthetic
warranty-narrative corpus (Phase 2/3's output), tracked via MLflow --
Volvo_Architecture_Deep_Dive.md §2.4/§2.5/§2.9's SageMaker training +
MLflow experiment-tracking responsibilities, done locally on CPU.

Usage: python scripts/train_classifier.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# MLflow 3.x puts the plain filesystem tracking backend ("file:./mlruns")
# into maintenance mode by default and raises unless this is set -- the
# free-alternative-stack doc's explicit choice was "local file-store
# backend, no server needed for a demo", so this opts back into that
# documented behavior rather than silently switching to a SQLite backend.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import mlflow  # noqa: E402
import torch  # noqa: E402
from sklearn.metrics import classification_report, multilabel_confusion_matrix  # noqa: E402
from torch.utils.data import Dataset  # noqa: E402
from transformers import (  # noqa: E402
    DistilBertForSequenceClassification,
    DistilBertTokenizerFast,
    Trainer,
    TrainingArguments,
)

from volvo_models.labels import CATEGORIES  # noqa: E402

BASE_MODEL = "distilbert-base-uncased"
TRAIN_PATH = ROOT / "data" / "training" / "train.jsonl"
VAL_PATH = ROOT / "data" / "training" / "val.jsonl"
MODEL_OUTPUT_DIR = ROOT / "models" / "distilbert_classifier"
CONFUSION_MATRIX_PATH = ROOT / "models" / "confusion_matrix.png"

# NUM_EPOCHS raised from an initial 8 to 20 after inspecting real
# per-example validation predictions: at 8 epochs the model was already
# ranking the correct category highest in most cases but confidence hadn't
# crossed the 0.5 threshold yet (e.g. a true infotainment case scoring
# infotainment=0.399), i.e. genuinely under-trained rather than confused --
# more epochs on this small a dataset is the right lever, not a threshold
# change that would mask the real cause.
NUM_EPOCHS = 20
BATCH_SIZE = 8
LEARNING_RATE = 3e-5
CONFIDENCE_THRESHOLD = 0.5


def load_cases(path: Path) -> tuple[list[str], np.ndarray]:
    texts = []
    labels = []
    with open(path) as f:
        for line in f:
            case = json.loads(line)
            texts.append(case["narrative_text"])
            multi_hot = [1.0 if c in case["categories"] else 0.0 for c in CATEGORIES]
            labels.append(multi_hot)
    return texts, np.array(labels, dtype=np.float32)


class WarrantyCaseDataset(Dataset):
    def __init__(self, encodings, labels: np.ndarray):
        self.encodings = encodings
        self.labels = labels

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> dict:
        item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.float32)
        return item


def compute_metrics(eval_pred) -> dict:
    logits, labels = eval_pred
    probs = 1 / (1 + np.exp(-logits))  # sigmoid
    preds = (probs >= CONFIDENCE_THRESHOLD).astype(int)

    report = classification_report(
        labels, preds, target_names=list(CATEGORIES), output_dict=True, zero_division=0
    )
    metrics = {
        "micro_f1": report["micro avg"]["f1-score"],
        "macro_f1": report["macro avg"]["f1-score"],
        "micro_precision": report["micro avg"]["precision"],
        "micro_recall": report["micro avg"]["recall"],
    }
    for category in CATEGORIES:
        metrics[f"f1_{category}"] = report[category]["f1-score"]
    return metrics


def main() -> None:
    print("Loading data...")
    train_texts, train_labels = load_cases(TRAIN_PATH)
    val_texts, val_labels = load_cases(VAL_PATH)
    print(f"Train: {len(train_texts)} examples, Val: {len(val_texts)} examples")

    tokenizer = DistilBertTokenizerFast.from_pretrained(BASE_MODEL)
    train_encodings = tokenizer(train_texts, truncation=True, padding=True, max_length=128)
    val_encodings = tokenizer(val_texts, truncation=True, padding=True, max_length=128)

    train_dataset = WarrantyCaseDataset(train_encodings, train_labels)
    val_dataset = WarrantyCaseDataset(val_encodings, val_labels)

    model = DistilBertForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(CATEGORIES),
        problem_type="multi_label_classification",
    )

    training_args = TrainingArguments(
        output_dir=str(ROOT / "models" / "_trainer_checkpoints"),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        eval_strategy="epoch",
        logging_strategy="epoch",
        save_strategy="no",
        report_to=[],
        disable_tqdm=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    # Absolute path, not the relative "file:./mlruns" a first version used --
    # a relative URI resolves against the process's current working
    # directory at invocation time, not this script's location, so running
    # `python volvo-demo/scripts/train_classifier.py` from the repo root
    # silently wrote a stray mlruns/ at the repo root instead of
    # volvo-demo/mlruns/ as intended. Caught by querying mlflow.search_runs()
    # afterward and finding the experiment missing from the expected path.
    mlflow.set_tracking_uri(f"file:{ROOT / 'mlruns'}")
    mlflow.set_experiment("volvo_warranty_classifier")

    with mlflow.start_run() as run:
        print(f"MLflow run ID: {run.info.run_id}")

        mlflow.log_params(
            {
                "base_model": BASE_MODEL,
                "num_epochs": NUM_EPOCHS,
                "batch_size": BATCH_SIZE,
                "learning_rate": LEARNING_RATE,
                "confidence_threshold": CONFIDENCE_THRESHOLD,
                "train_size": len(train_texts),
                "val_size": len(val_texts),
                "num_categories": len(CATEGORIES),
            }
        )

        print("Training...")
        train_result = trainer.train()

        for entry in trainer.state.log_history:
            step = entry.get("epoch")
            if step is None:
                continue
            loggable = {k: v for k, v in entry.items() if isinstance(v, (int, float)) and k != "epoch"}
            if loggable:
                mlflow.log_metrics(loggable, step=int(step))

        print("Evaluating...")
        eval_metrics = trainer.evaluate()
        mlflow.log_metrics({k: v for k, v in eval_metrics.items() if isinstance(v, (int, float))})

        print("\nFinal validation metrics:")
        for k, v in eval_metrics.items():
            if isinstance(v, (int, float)):
                print(f"  {k}: {v:.4f}")

        # Confusion matrix grid (one 2x2 per label)
        val_predictions = trainer.predict(val_dataset)
        probs = 1 / (1 + np.exp(-val_predictions.predictions))
        preds = (probs >= CONFIDENCE_THRESHOLD).astype(int)
        cms = multilabel_confusion_matrix(val_labels, preds)

        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 4, figsize=(16, 8))
        for i, (category, cm) in enumerate(zip(CATEGORIES, cms)):
            ax = axes[i // 4][i % 4]
            ax.imshow(cm, cmap="Blues")
            ax.set_title(category, fontsize=10)
            for r in range(2):
                for c in range(2):
                    ax.text(c, r, str(cm[r, c]), ha="center", va="center")
            ax.set_xticks([0, 1])
            ax.set_yticks([0, 1])
            ax.set_xticklabels(["Pred 0", "Pred 1"], fontsize=8)
            ax.set_yticklabels(["True 0", "True 1"], fontsize=8)
        fig.tight_layout()
        CONFUSION_MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(CONFUSION_MATRIX_PATH)
        mlflow.log_artifact(str(CONFUSION_MATRIX_PATH))
        print(f"\nConfusion matrix grid saved to {CONFUSION_MATRIX_PATH}")

        # Save model + tokenizer to a fixed local path for fast-loading at
        # inference time, in addition to (not instead of) MLflow's own
        # tracked model artifact.
        MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        trainer.save_model(str(MODEL_OUTPUT_DIR))
        tokenizer.save_pretrained(str(MODEL_OUTPUT_DIR))
        print(f"Model + tokenizer saved to {MODEL_OUTPUT_DIR}")

        # pip_requirements passed explicitly: mlflow's default requirement
        # auto-detection imports every optional transformers extra
        # (including torchvision, for image pipelines) to read its version,
        # which crashes with ModuleNotFoundError since this project never
        # installs torchvision -- it's irrelevant to a text classifier.
        mlflow.transformers.log_model(
            transformers_model={"model": model, "tokenizer": tokenizer},
            name="model",
            task="text-classification",
            pip_requirements=["torch", "transformers"],
        )

        print(f"\nTraining wall time: {train_result.metrics.get('train_runtime', 'unknown')} seconds")
        print(f"MLflow run: {run.info.run_id} (tracking URI: file:{ROOT / 'mlruns'})")


if __name__ == "__main__":
    main()

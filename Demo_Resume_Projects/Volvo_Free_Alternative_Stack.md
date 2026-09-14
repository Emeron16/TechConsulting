# Free / Open-Source Alternative Stack for the Volvo BERT Dealer Service and Warranty Intelligence Platform

**Purpose:** A layer-by-layer substitution for [Volvo_Architecture_Deep_Dive.md](Volvo_Architecture_Deep_Dive.md) that preserves the same architectural *shape* (batch ingestion → classical NLP model layer → training/experiment tracking → hybrid index/retrieval → human escalation) using entirely free or free-tier tools, so the full pattern can be demoed locally or on a laptop without an AWS subscription. Local/self-hosted tools are prioritized over hosted free tiers wherever a credible local option exists — this project is a better fit for that than the NRG/Novartis copilots since there's no LLM API call in the critical path at all, everything here can genuinely run offline.

---

## Layer-by-Layer Substitution

| Layer | AWS/Original | Free Alternative | Notes |
|---|---|---|---|
| **Classifier Model (BERT/DistilBERT, PyTorch)** | Hugging Face Transformers + PyTorch (already free/open-source) | **Unchanged** — Hugging Face Transformers + PyTorch | No substitution needed — this layer was already free/open-source in the original. Fine-tuning DistilBERT runs fine on a laptop CPU for a demo-sized dataset, or a free Colab/Kaggle GPU tier if you want faster iteration |
| **Semantic Similarity (Sentence-BERT)** | Sentence-BERT (already free/open-source) | **Unchanged** — `sentence-transformers` library | No substitution needed — already free. Any of the small pretrained models (e.g. `all-MiniLM-L6-v2`) run comfortably locally |
| **NER Pipeline (spaCy)** | spaCy (already free/open-source) | **Unchanged** — spaCy, `en_core_web_sm`/`trf` + custom `EntityRuler` patterns for VINs/DTCs | No substitution needed — already free |
| **Model Training & Hosting** | Amazon SageMaker (training jobs + hosted inference endpoints) | **Local training via PyTorch/Transformers `Trainer`** (laptop or free Colab GPU), served via **FastAPI loading the model directly** (in-process inference) or **BentoML** / **Ray Serve** (free, self-hosted model-serving frameworks) | For a demo, skip a "hosted endpoint" concept entirely — load the fine-tuned model straight into the FastAPI process. BentoML/Ray Serve are the closer analogs if you want to demo a distinct model-serving layer separate from the API layer, the way SageMaker endpoints were architecturally separate from the FastAPI service |
| **Experiment Tracking / Model Registry** | MLflow (already free/open-source) | **Unchanged** — MLflow, self-hosted (local file-store or SQLite backend, no server needed for a demo) | No substitution needed — MLflow was already free/open-source in the original; just point it at a local `mlruns/` directory instead of an S3-backed artifact store |
| **Pipeline Orchestration** | Apache Airflow (already free/open-source, but typically AWS-hosted via MWAA) | **Airflow itself, self-hosted via Docker Compose** (`docker-compose` LocalExecutor setup), or **Prefect** / **Dagster** (free, open-source, lighter-weight local dev experience) | Airflow unchanged is the closest analog and the most direct "same tool, no cloud" swap; Prefect/Dagster are worth mentioning as alternatives with an easier local-dev loop if Airflow's setup overhead isn't worth it for a demo |
| **Large-Scale Preprocessing (PySpark)** | PySpark (already free/open-source, typically run on EMR/Glue infra) | **PySpark in local mode** (`local[*]`) for a demo-sized dataset, or **Polars/Pandas** if the dataset is small enough that distributed processing isn't actually needed to make the point | PySpark local mode is the honest "same tool, no cluster" answer; swapping to Polars is reasonable if you want to show a lighter-weight option and the demo dataset doesn't need real distribution to be convincing |
| **ETL + Data Catalog** | AWS Glue | **dbt** (free, open-source) for transformation + a lightweight catalog like **DataHub** (free, self-hosted) or simply a documented schema in the ingestion repo for a laptop demo | dbt is the closer modern analog for the transformation half; a full open-source catalog (DataHub/Amundsen) is real overhead for a demo — worth calling out as "this is what Glue's catalog half maps to" without necessarily standing it up |
| **Object Storage** | Amazon S3 | **MinIO** (free, self-hosted, S3-compatible — same SDK/API) or plain local filesystem for a laptop demo | MinIO is the drop-in replacement since Airflow/PySpark/boto3-based code can point at it with zero code changes, just a different endpoint URL |
| **Index & Retrieval (OpenSearch: structured filter + full-text + vector, combined)** | OpenSearch | **OpenSearch itself, self-hosted via Docker** (free, open-source — AWS's managed OpenSearch *Service* costs money, but the OpenSearch project is free) or **Qdrant + a lightweight SQL store** if you want to split vector search and structured filtering into separate tools | Self-hosted OpenSearch is the truest "same tool, no managed-service fee" swap and keeps the single "one engine, one query" story from the original intact; Qdrant is worth mentioning only if you'd rather demo a purpose-built vector database instead |
| **API & Serving Layer** | FastAPI (already free/open-source, running on ECS) | **Unchanged** — FastAPI | No substitution needed — already free |
| **Identity/Access Control** | AWS IAM (assumed) | **None for a laptop demo**, or **Keycloak** (free, open-source, full OIDC/RBAC) if you want to demonstrate service-to-service access control as a distinct pattern | Keycloak is the closer enterprise-IAM analog; for a demo scoped to the NLP pipeline itself, it's reasonable to note this layer conceptually rather than stand it up |
| **Container Orchestration** | Amazon ECS | **Docker Compose** (single-machine) or **k3s/kind** (free, lightweight local Kubernetes) | k3s/kind lets you say "this runs on real Kubernetes," just not managed/cloud; Compose is simplest for a laptop demo |
| **Container Registry** | Container Registry / ECR (assumed) | **Docker Hub free tier** or a local registry via the `registry:2` image | |
| **CI/CD** | GitHub Actions | **GitHub Actions** (already free for public repos, generous free minutes for private) | No substitution needed |
| **Observability (logs/metrics/alarms)** | Amazon CloudWatch | **Grafana + Prometheus + Loki** (all free, self-hosted) | Standard free OSS observability stack — Prometheus for metrics, Loki for logs, Grafana for dashboards/alarms, roughly mirroring CloudWatch's combined role across the FastAPI service, model inference, Airflow runs, and OpenSearch |

---

## The Practical Path

This project is the most "already free" of the three architectures — the core NLP stack (Transformers, PyTorch, Sentence-BERT, spaCy, MLflow, Airflow, PySpark, FastAPI) was open-source from the start. The only real substitutions are for the *managed AWS infrastructure* wrapped around that stack, which is exactly the part that's easiest to run locally since there's no LLM API dependency anywhere in this pipeline.

**Local / Docker Compose (covers almost the entire stack):**
- **Model training:** PyTorch + Hugging Face Transformers `Trainer`, run locally (laptop CPU is fine for a small fine-tuning demo; use a free Colab/Kaggle GPU tier for faster iteration if needed)
- **Model serving:** FastAPI loading the fine-tuned model directly in-process, or BentoML/Ray Serve if you want a distinct serving layer
- **Experiment tracking:** MLflow, local file-store backend
- **Orchestration:** Airflow (Docker Compose LocalExecutor) or Prefect/Dagster
- **Preprocessing:** PySpark in local mode, or Polars for a lighter footprint
- **Storage:** MinIO (S3-compatible) or local filesystem
- **Index/retrieval:** OpenSearch, self-hosted via Docker
- **Observability:** Grafana + Prometheus + Loki
- **Identity/SSO (optional):** Keycloak — only if you want to demo IAM-style access control as a distinct pattern

**Hosted (free tier, optional — only if local compute is a constraint):**
- **GPU for training:** Google Colab free tier or Kaggle Notebooks, instead of a local CPU or paid SageMaker GPU instance
- **Vector/search (optional hosted route):** Qdrant Cloud free tier, if you'd rather not self-host OpenSearch

This reproduces every architectural layer and design decision in the original — multi-label classification over single-label, Sentence-BERT over raw BERT embeddings, spaCy's lightweight pipeline over a full custom NER model, one combined structured+text+vector index over separate specialized stores — entirely on a laptop, with nothing behind a metered API.

---

## Open Question

Since almost the entire NLP stack here is already free/open-source, the highest-value thing to actually demo end-to-end is probably the full pipeline shape — Airflow triggering PySpark preprocessing, feeding the fine-tuned classifier + spaCy NER + Sentence-BERT, landing in a self-hosted OpenSearch index queryable by VIN/symptom/component — since that's the part of this project most distinct from the LLM-centric NRG and Novartis architectures and most likely to draw follow-up questions about why a classical NLP approach was the right call over a generative one.

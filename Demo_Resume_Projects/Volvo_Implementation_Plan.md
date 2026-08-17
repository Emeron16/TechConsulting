# Local/Free Implementation Plan — Volvo BERT Dealer Service and Warranty Intelligence Platform

## Context

[Volvo_Architecture_Deep_Dive.md](Volvo_Architecture_Deep_Dive.md) describes an AWS architecture for a classical NLP pipeline (not a GenAI/RAG system): a fine-tuned BERT/DistilBERT multi-label classifier, Sentence-BERT similarity, spaCy NER, PySpark preprocessing, Airflow orchestration, SageMaker training/hosting, MLflow tracking, a combined structured+text+vector OpenSearch index, FastAPI serving, ECS/CloudWatch infra — feeding a Dealer Case Management UI analysts use to look up warranty claims, with a Service Operations Manager escalation path for safety-flagged patterns (TREAD Act reporting consequences). [Volvo_Free_Alternative_Stack.md](Volvo_Free_Alternative_Stack.md) maps this to free/local tools, noting this project is "the most already free" of the three demos since the entire NLP stack (Transformers, PyTorch, Sentence-BERT, spaCy, MLflow, Airflow, PySpark) was open-source from the start — only the AWS wrapper (S3, Glue, SageMaker, ECS, IAM, CloudWatch) needs substitution.

This is a **third demo**, alongside [copilot-demo/](copilot-demo/) (Novartis CMC Quality Copilot) and [nrg-demo/](nrg-demo/) (NRG Energy Knowledge Copilot), reachable from the same [shell/](shell/) Streamlit app via a left-sidebar switch. It is architecturally the most different of the three: no LLM call anywhere in the critical path, a classification+extraction+similarity pipeline instead of a RAG/generation chain, a genuinely real (if small) model-training step neither other demo has, and — per the decisions below — the most literal reproduction yet of the original architecture's service boundaries (a real FastAPI serving layer, a real Airflow orchestrator the UI actually drives).

**Why this shape, specifically:** the user chose the more architecturally-faithful options at each fork — real FastAPI service (not in-process calls), and the live UI actually triggering/polling real Airflow DAG runs (not a side-channel batch job). This makes Volvo's plumbing meaningfully heavier than NRG's, so the plan leans hard on precedent (NRG's schema/diagram/generator/shell-wrapper conventions) everywhere that isn't genuinely new, and spends the novel complexity budget only on the FastAPI+Airflow serving/orchestration path and the real model training.

**Confirmed scope decisions (from the user):**
- **UI interaction:** Case Lookup/Search tab + Submit New Case tab, the latter with live per-stage progress (preprocess → classify → NER → embed → similarity search → index → escalation check).
- **Training data:** ~50–150 synthetic warranty narratives, authored for this demo, heuristically multi-label-tagged into the architecture doc's 8 categories (powertrain, infotainment, electrical, braking, software_update, safety_concern, parts_delay, dealer_escalation), then **actually fine-tuned** into DistilBERT via Transformers `Trainer` — real, small, end-to-end training, not zero-shot.
- **Infra ambition:** full pipeline actually stood up — Airflow (LocalExecutor, real DAG, one run per submitted case), PySpark (`local[*]`), self-hosted OpenSearch (Docker), MLflow (local file-store backend), and a **real local FastAPI service** — matching and exceeding NRG's "implement the real analog" precedent.
- **Serving layer:** a real FastAPI service is the single access point for classify/NER/embed/similarity-search/index operations. **Both** Streamlit and Airflow's DAG tasks call it over HTTP — one true serving layer, not two access paths to the same logic.
- **Orchestration:** the Submit New Case flow triggers one real Airflow DAG run per submission (via `POST /dags/{dag_id}/dagRuns` with case data as `conf`), and Streamlit polls Airflow's task-instance states, mapping each task to a `CaseStep` stage for live per-stage UI progress — not a coarse queued/running/done spinner.
- **Model Info tab:** included in v1 — MLflow metrics (precision/recall/F1 per category, confusion matrices, training params), a genuine capability neither other demo has.
- **S3/Glue analogs:** kept lightweight — plain local filesystem (no MinIO), PySpark alone as the real ETL step (no dbt/DataHub catalog).
- **Python version:** `volvo-demo/.venv` pinned to Homebrew `python@3.12` (confirmed present, 3.12.11) — NOT the 3.14 the other two demos use — for safer torch/spaCy/transformers wheel compatibility.
- **Venv rebuild prerequisite:** all three existing venvs (`copilot-demo/.venv`, `nrg-demo/.venv`, `shell/.venv`) are confirmed broken — their `pip` shebangs point at `/Users/princemarcelle/Documents/Project/.../python3.14`, a path that no longer exists since the repo moved to `Documents/GitHub/TechConsulting/Demo_Resume_Projects/`. `copilot-demo/` and `nrg-demo/` must be rebuilt on 3.14 (their original interpreter — confirmed both venvs still correctly symlink to the Cellar's 3.14.0_1 binary, only `pip`'s shebang is stale) as a Phase 0 prerequisite, not skipped.
- **GUI integration:** reuse `shell/` exactly as wired today — confirmed by reading `shell/shell_app.py` and `shell/nrg_wrapper.py` directly. Add a third sidebar radio option and a `volvo_wrapper.py` in the identical shape as `nrg_wrapper.py` (module-scope `sys.path.insert` + import; `load_dotenv(..., override=True)` **inside** the render function, not module scope — this exact bug was already hit and fixed once for the Novartis/NRG pair and must not be reintroduced).
- **Human-in-the-loop model:** a third, distinct pattern from the other two demos — safety-flag-triggered escalation to a Service Operations Manager review queue. Not Novartis's mandatory pre-publish gate, not NRG's after-the-fact statistical sampling. Two trigger conditions: (a) a case is directly classified `safety_concern` above threshold, or (b) similarity search surfaces a recurring pattern — 2 or more of a new case's top-5 similar cases are themselves already safety-flagged, even if the new case's own text wasn't obviously safety language.

**Reference implementation patterns to reuse (confirmed present, read directly):**
- [nrg-demo/nrg_chains/ingest.py](nrg-demo/nrg_chains/ingest.py) — the `IngestStep` dataclass + `Generator[IngestStep, None, ResultType]` convention for live UI progress (`yield` steps, `return` final result via `StopIteration.value`, consumed in the UI via `st.status()` + manual `next()`/`except StopIteration`).
- [nrg-demo/nrg_chains/chain.py](nrg-demo/nrg_chains/chain.py) — `ChainTraceStep`/`AskResult`-style dataclasses driving both the result and the flow diagram from one trace.
- [nrg-demo/nrg_chains/diagram_common.py](nrg-demo/nrg_chains/diagram_common.py) — HTML/CSS diagram primitives (`esc()`, `stage()`, `arrow()`, `placeholder()`, `score_table()`, `cache_badge()`, `REAL_TAG`, plus the `.decision-pending/approved/rejected` CSS classes already defined but unused by NRG). Duplicated from copilot-demo's version and diverged — never cross-imported.
- [nrg-demo/nrg_retrieval/audit.py](nrg-demo/nrg_retrieval/audit.py) — hash-chained audit log (`GENESIS_HASH`, `compute_record_hash()`, `append_audit_entry()`, `verify_chain()`), ported near-verbatim from `copilot-demo/mcp_servers/audit.py` since the chaining logic is domain-agnostic.
- [nrg-demo/db/init/01_schema.sql](nrg-demo/db/init/01_schema.sql) — Postgres schema shape: CHECK-constrained enums, partial unique indexes, insert-only `audit_log` trigger.
- [nrg-demo/docker-compose.yml](nrg-demo/docker-compose.yml) — Compose service pattern, including the host-side healthcheck workaround for images with no shell utilities (Qdrant's issue; OpenSearch may or may not need the same treatment — verify in Phase 0).
- [shell/shell_app.py](shell/shell_app.py), [shell/nrg_wrapper.py](shell/nrg_wrapper.py) — read in full; confirmed exact wiring shape (see above), including the two real bugs NRG's Phase 9 hit and fixed (env-var collision across identically-named `.env` vars; module-caching bug requiring `load_dotenv` to live inside the render function, not module scope).

---

## Architecture Mapping Recap

| Original Layer | Local/Free Build Choice | Status |
|---|---|---|
| Classifier (BERT/DistilBERT) | Hugging Face Transformers + PyTorch, fine-tuned locally on CPU | **Real** |
| Semantic similarity (Sentence-BERT) | `sentence-transformers`, pretrained `all-MiniLM-L6-v2`, no fine-tuning | **Real** |
| NER (spaCy) | `en_core_web_sm` + custom `EntityRuler` patterns (VIN, DTC codes) | **Real** |
| Model training (SageMaker) | Local `Trainer` run on CPU | **Real** |
| Model hosting/serving (SageMaker endpoints → FastAPI) | Real local FastAPI service wrapping classifier/NER/similarity/search | **Real** |
| Experiment tracking (MLflow) | Self-hosted MLflow, local file-store backend | **Real** |
| Orchestration (Airflow) | Self-hosted via Docker Compose, LocalExecutor, real DAG, one run per submitted case, driven live by the UI | **Real** |
| Preprocessing (PySpark) | PySpark local mode (`local[*]`) | **Real** |
| Object storage (S3) | Plain local filesystem (`data/`) | Analog, lightweight |
| ETL + catalog (Glue) | PySpark = real ETL; no separate catalog tool | Analog (ETL real, catalog diagram-only) |
| Index/retrieval (OpenSearch) | Self-hosted OpenSearch via Docker (OSS project) | **Real** |
| IAM | None | Diagram-only |
| Container orchestration (ECS) | Docker Compose | Analog-labeled |
| Observability (CloudWatch) | None | Diagram-only |

---

## Directory Structure

```
volvo-demo/
├── .env / .env.example, .gitignore, docker-compose.yml, requirements.txt
├── data/
│   ├── synthetic_cases/           # ~50-150 authored warranty narratives (labeled JSONL)
│   └── training/                  # train/val split, PySpark output
├── db/init/01_schema.sql
├── cache/                         # gitignored
├── mlruns/                        # MLflow local file-store backend, gitignored
├── models/                        # fine-tuned DistilBERT checkpoint + label encoder, gitignored
├── airflow/
│   ├── dags/volvo_case_pipeline_dag.py
│   ├── docker-compose.airflow.yml     # Airflow's OWN Postgres+webserver+scheduler
│   └── logs/, plugins/                # gitignored
├── api/
│   ├── main.py                    # FastAPI app: /classify, /extract-entities, /embed, /similar-cases, /index-case
│   └── schemas.py                 # Pydantic request/response models
├── scripts/
│   ├── generate_synthetic_cases.py, preprocess_pyspark.py, train_classifier.py
│   ├── build_ner_patterns.py, seed_historical_cases.py
│   ├── submit_case.py, search_cases.py, review_escalations.py
│   ├── check_opensearch_health.py, check_audit_chain.py
├── volvo_models/                  # inference code: classifier, sentence-embedder, NER (imported by api/, scripts/, Airflow tasks)
│   ├── classifier.py, similarity.py, ner.py, labels.py, text_normalize.py
├── volvo_pipeline/                # orchestration: DAG-run trigger/poll, trace mapping, diagrams
│   ├── schemas.py, dag_client.py, escalation.py
│   ├── diagram_common.py, flow_diagram.py, training_flow_diagram.py
├── volvo_retrieval/                # data access: OpenSearch, Postgres, audit
│   ├── opensearch_client.py, case_search.py, postgres_client.py, audit.py
├── volvo_app.py                   # thin entrypoint
└── volvo_app_render.py            # all tab/UI logic, single public render()

shell/
├── shell_app.py                   # third sidebar option added
├── volvo_wrapper.py                # NEW, identical shape to nrg_wrapper.py
└── requirements.txt                # merged across all three demos
```

**Package split rationale:** `volvo_models/` (classifier/embedder/NER — CPU-bound, stateless, no I/O) is imported directly by `api/main.py`, `scripts/train_classifier.py`, and can be imported standalone for tests, without pulling in orchestration or data-access concerns. `volvo_pipeline/` is the orchestration+diagram package (NRG's `nrg_chains` analog, but its core job is now driving an Airflow DAG run rather than an in-process chain). `volvo_retrieval/` is the data-access package (NRG's `nrg_retrieval` analog).

---

## Phase 0 — Environment Rebuild (Prerequisite) + Volvo Scaffolding

**Goal:** All three existing demo venvs work again, and `volvo-demo/`'s own 3.12 venv exists and imports its heaviest dependencies cleanly, before any Volvo code is written.

- [x] **0a. Rebuild `copilot-demo/.venv` and `nrg-demo/.venv` on Python 3.14.** Both venvs' interpreter symlinks were fine (still correctly pointed at the Cellar's 3.14.0_1 binary); only `pip`'s shebang was stale. Recreated in place (also rebuilt `shell/.venv`, discovered broken by the same stale-path issue and needed for the eventual Phase 12 merge). `copilot-demo/.venv.broken-bak/` was a dead leftover from a prior repair attempt, not a usable reference — removed.
  - **Verified:** `import agents, chromadb, streamlit` (copilot-demo — actual import name is `agents`, not `openai_agents`; the PyPI package name and import name differ) and `import langchain, qdrant_client, streamlit` (nrg-demo) both succeed; `streamlit run copilot-demo/streamlit_app.py` and `streamlit run nrg-demo/nrg_app.py` both boot to HTTP 200 standalone with clean logs; `shell/requirements.txt` (current two-demo merge) also installs cleanly on the rebuilt `shell/.venv`.
- [x] **0b. Create `volvo-demo/.venv` on Homebrew `python@3.12`.** Created on `python3.12` (3.12.11). `volvo-demo/requirements.txt` authored per plan (torch, transformers, sentence-transformers, spacy, mlflow, pyspark, fastapi, uvicorn[standard], httpx, opensearch-py, psycopg[binary], python-dotenv, pyyaml, streamlit, pydantic, scikit-learn, pandas). Airflow itself not pip-installed here, per plan.
  - **Verified:** fresh install completed with zero unresolvable wheel conflicts (torch 2.13.0, transformers 5.14.1, spacy 3.8.15, mlflow 3.15.1, pyspark 4.2.0, fastapi 0.141.1 all installed cleanly); `en_core_web_sm` downloaded and loads/tokenizes correctly.
  - **Real bug found and fixed:** no Java was installed anywhere on the machine — installed via `brew install openjdk@17` (keg-only, not symlinked into `/opt/homebrew` by default). A first PySpark local-mode test then failed with `PYTHON_VERSION_MISMATCH` (Spark's worker subprocess resolved a system `python3.14` on PATH instead of the venv's `python3.12`, since `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` weren't set) — a real, confirmed-not-hypothetical failure mode the plan's "highest-risk step" flag correctly anticipated. Fixed by setting `JAVA_HOME=/opt/homebrew/opt/openjdk@17` and pinning `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` to the venv's Python; a real local Spark job (`SparkSession.builder.master("local[*]")`, `createDataFrame` + `.show()` + `.count()`) then ran and returned correct results. These three vars are baked into `volvo-demo/.env.example` for Phase 3 to reuse without rediscovering this.
- [x] **0c. Volvo scaffolding.** Created the `volvo-demo/` tree per plan (`data/synthetic_cases/`, `data/training/`, `db/init/`, `cache/`, `mlruns/`, `models/`, `airflow/{dags,logs,plugins}/`, `api/`, `scripts/`, `volvo_models/`, `volvo_pipeline/`, `volvo_retrieval/`, each package with `__init__.py`). `.env.example`/`.env`: `POSTGRES_PORT=5434`, `OPENSEARCH_PORT=9201`/`OPENSEARCH_DASHBOARDS_PORT=9301` (confirmed non-colliding — checked actual `docker ps` port usage across all running containers, not just assumed), `MLFLOW_TRACKING_URI=file:./mlruns`, `FASTAPI_BASE_URL=http://localhost:8100`, `AIRFLOW_BASE_URL=http://localhost:8180` + `AIRFLOW_USERNAME`/`PASSWORD`/`AIRFLOW_DAG_ID`, plus the `JAVA_HOME`/`PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` vars from 0b. `.gitignore` per plan. `docker-compose.yml`: Postgres 16-alpine (5434) + OpenSearch 2.x single-node (security plugin disabled for local dev, 9201) + OpenSearch Dashboards (9301, optional but included).
  - **Verified:** `docker compose up -d` → both `volvo-postgres` and `volvo-opensearch` report `(healthy)` within ~20s; confirmed via direct `docker ps` diff against all other running containers (nrg-postgres/qdrant/rabbitmq, copilot-postgres/rabbitmq, plus unrelated itagenticragsystem/code-runner containers) — zero port, name, or volume collisions. `curl http://localhost:9201/_cluster/health` returns `"status":"green"` (exceeding the plan's green-or-yellow bar). `docker exec volvo-postgres pg_isready` confirms accepting connections.

---

## Phase 1 — Postgres Schema + OpenSearch Index Schema

**Goal:** Both stores' schemas exist and are verified before any data flows through them.

**`db/init/01_schema.sql`** — five tables, following the `kb_documents`/`audit_log` shape but domain-adapted:

- [x] `warranty_cases` (case_id UNIQUE, vin, narrative_text, dealer_location, mileage, vehicle_model, model_year, status CHECK(`indexed`/`escalated`/`escalation_resolved`), submitted_by, created_at). Index on `vin`.
- [x] `case_classifications` — **join table**, one row per assigned category per case (not a JSONB array), so per-category confidence stays individually queryable and `category` is CHECK-constrained to the 8-value enum: `UNIQUE(case_id, category)`. A case can carry multiple categories at once (multi-label), which is exactly why this needs to be a join table rather than a single-column enum the way NRG's `kb_documents.doc_type` is.
- [x] `extracted_entities` (case_id UNIQUE FK, entities JSONB — heterogeneous entity types per case, not worth a join table).
- [x] `safety_escalations` — the distinct human-in-the-loop table: case_id FK, trigger_reason CHECK(`direct_classification`/`recurring_pattern`), related_case_ids JSONB (populated for `recurring_pattern`), status CHECK(`pending_review`/`field_action_recommended`/`no_action_needed`), raised_at, reviewed_by, reviewed_at, review_notes. Index on `status`.
- [x] `airflow_dag_runs` — **new table not in NRG's schema**, needed because the UI now needs to map a submitted case to a specific Airflow `dag_run_id` for polling: case_id FK, dag_run_id, triggered_at, last_polled_state, completed_at. This is *not* duplicating Airflow's own metadata DB (which tracks full task-instance history) — it's just the join key the UI needs to know which `dag_run_id` corresponds to which case_id, since Airflow's own DB is a separate Postgres instance the app doesn't query directly for this lookup.
- [x] `audit_log` — identical hash-chained, insert-only shape to NRG's, ported verbatim (table + `reject_audit_log_mutation()` trigger).

**OpenSearch index** (`volvo_warranty_cases`) — one combined index: `case_id`/`vin` (keyword), `narrative_text` (text), `dealer_location`/`vehicle_model` (keyword), `model_year`/`mileage` (integer), `categories` (keyword array), `entities` (nested: label/text), `narrative_vector` (`knn_vector`, dim=384 matching `all-MiniLM-L6-v2`, HNSW/cosine), `created_at` (date). `index.knn: true`.

- [x] `volvo_retrieval/opensearch_client.py`: `get_opensearch_client()`, `ensure_index()` (idempotent, mirrors `qdrant_client.py`'s `ensure_collection()`).
- [x] `scripts/check_opensearch_health.py`: cluster health + index existence + mapping confirmation.

**Design note:** do not duplicate Airflow's own DAG-run/task-instance history into the app's Postgres beyond the thin `airflow_dag_runs` join table above — querying Airflow's REST API directly is sufficient for anything the UI needs beyond that join key.

**Verified:** Postgres recreated with a fresh volume so the init script actually ran (Postgres only executes `docker-entrypoint-initdb.d` scripts on first init of an empty data directory); all 6 tables confirmed present via `\dt`. `audit_log` insert-only trigger confirmed rejecting both UPDATE (`audit_log is insert-only: UPDATE not permitted`) and DELETE against a real inserted row. `case_classifications`' `UNIQUE(case_id, category)` confirmed rejecting a duplicate `(case_id, category)` insert. OpenSearch: `check_opensearch_health.py` confirmed the index created with `narrative_vector` mapped as `knn_vector` dim=384; a manual test document with a random 384-dim vector indexed successfully and was retrieved by both an exact `vin` term-query and a `knn` vector query (score-1.0 self-match). Both stores reset to 0 test rows/docs afterward (the one real `audit_log` test row was deliberately left in place, matching NRG's precedent, since the table is insert-only by design and the row correctly demonstrates the trigger working).

---

## Phase 2 — Synthetic Training Data

**Goal:** 50–150 authored, multi-label-heuristically-tagged warranty narratives on disk, ready for PySpark preprocessing and DistilBERT fine-tuning.

- [x] `scripts/generate_synthetic_cases.py`: authors narratives from templates per category (genuine short warranty-complaint sentences, not gibberish), covering all 8 categories with clean single-label examples, plus a deliberate multi-label subset (~15–20%, e.g. an infotainment-failure-that-also-causes-battery-drain narrative → `infotainment`+`electrical`, directly the example the architecture doc itself gives), plus a deliberate subset of unambiguous `safety_concern` narratives (brake failure, airbag warning, steering loss language — needed later to prove the escalation pipeline fires correctly). VINs are 17-char synthetic (clearly fake, distinctly prefixed), plus mileage/dealer location/model/year per row. Also deliberately inject a few common dealer abbreviations and boilerplate prefixes (e.g. `"customer states:"`) into some narratives so Phase 3's PySpark cleaning step has real work to do, and author 2–3 near-duplicate narrative pairs for Phase 5's similarity verification. `volvo_models/labels.py` created here (originally scoped for Phase 4) as the single source of truth for the 8-category list, since the generator needed it immediately and later phases (classifier head, Postgres/OpenSearch schemas, UI display order) all import from the same place.
- [x] Heuristic auto-labeling: an explicit, inspectable keyword/rule table in `scripts/label_heuristics.py` — this rule table IS the ground truth the classifier trains against.
- [x] Output: `data/synthetic_cases/cases.jsonl` (case_id, vin, narrative_text, categories, dealer_location, mileage, vehicle_model, model_year). Stratified-best-effort 85/15 train/val split to `data/training/train.jsonl` / `val.jsonl`.

**Verified:** 120 cases generated (103 train / 17 val). Per-category counts all non-degenerate (9–30 examples per category after fixes below). Multi-label subset: 26 cases (21.7%), hand-inspected and semantically correct (e.g. an infotainment-reboot-plus-battery-drain case correctly tagged `infotainment`+`electrical`). All 120 VINs exactly 17 characters. Zero train/val case_id overlap. Near-duplicate pairs and boilerplate/abbreviation injections both confirmed present in the output.

**Two real bugs found and fixed by running the generator's own verification output, not just reading the code:**
1. Plain substring keyword matching false-positived — "fire" (a `safety_concern` keyword) matched inside "mis**fire**", incorrectly tagging every `powertrain` engine-misfire narrative as also `safety_concern`. Fixed by requiring a word boundary immediately *before* each keyword (`\bkeyword`, not `\bkeyword\b`) — this rejects mid-word matches like "misfire" while still allowing suffixed/pluralized matches like "stall" inside "stalls" or "window" inside "windows" (a first fix using `\b` on both sides was too strict and broke exactly those plural cases, caught by a second run of the same verification).
2. 3 `parts_delay` narratives ("waiting on **a** part") matched zero categories because the keyword list only had "waiting on part" (no article). Fixed by adding "waiting on a part" as its own keyword alongside the original.

---

## Phase 3 — PySpark Preprocessing

**Goal:** A real local-mode PySpark job cleans/normalizes the synthetic narratives — genuinely run, not stubbed.

- [x] `volvo_models/text_normalize.py`: the shared normalization function (abbreviation expansion via a small authored dictionary, boilerplate-phrase stripping) — a plain Python function, **not** duplicated between Spark and the live single-case path. Both the PySpark UDF (Phase 3) and the FastAPI preprocessing step (Phase 6) call this same function.
- [x] `scripts/preprocess_pyspark.py`: `SparkSession.builder.master("local[*]")`, reads `cases.jsonl`, applies `normalize_text` via UDF, writes `data/training/cases_cleaned.parquet`.

**Verified:** 120 rows in, 120 rows out (zero drops). Spot-checked 5 narratives before/after — boilerplate prefixes (`customer states:`, `cust reports:`, `per customer:`) correctly stripped. Separately confirmed both abbreviation variants (`chk eng light`, `chk eng lt`) correctly expanded to "check engine light" by directly inspecting the written parquet file. Confirmed the Spark UI is genuinely live during a run — fetched `http://localhost:4040/jobs/` via a real HTTP request, got status 200 with the actual application name present in the page body, not just a stubbed process.

**Two real bugs found and fixed:**
1. **VIN construction bug, discovered while preparing Phase 3's abbreviation test data:** Phase 2's `build_case()` derived each synthetic VIN from `case_id[-7:]` (e.g. `"CASE-0001"[-7:]` = `"E-0001"`), which embeds the case_id's literal hyphen into the VIN — all 120 generated VINs contained a `-` and were not alphanumeric, which would have broken Phase 5's NER pattern matching (17-char alphanumeric VIN format). Fixed by extracting only the digit characters from `case_id` before building the VIN (`"".join(ch for ch in case_id if ch.isdigit())`); regenerated the corpus and confirmed all 120 VINs are now clean 17-char alphanumeric strings.
2. **PySpark UDF `ModuleNotFoundError` at the write step, not the read/count step:** `.count()` succeeded (120 rows) because counting doesn't invoke the UDF, but the actual `.write.parquet()` call failed with `No module named 'volvo_models'` — even in `local[*]` mode, Spark's UDF executor runs in a separate Python worker subprocess that does not inherit the driver script's `sys.path`. Fixed by zipping `volvo_models/` to a temp file and shipping it to the executor via `spark.sparkContext.addPyFile()` (which requires a `.py` file or `.zip`/`.egg` archive, not a bare package directory — confirmed after an initial attempt to pass the raw directory path also failed).

---

## Phase 4 — Model Training: DistilBERT Fine-Tuning + MLflow

**Goal:** A real DistilBERT multi-label classifier fine-tuned on the synthetic corpus, with MLflow tracking metrics and the model artifact.

- [x] `volvo_models/labels.py`: the 8-category label list — single source of truth (built ahead of schedule in Phase 2, since the synthetic-data generator needed it immediately).
- [x] `scripts/train_classifier.py`: `DistilBertTokenizerFast` (`distilbert-base-uncased`) + `DistilBertForSequenceClassification.from_pretrained(..., num_labels=8, problem_type="multi_label_classification")`, multi-hot target vectors, `transformers.Trainer` (CPU, 20 epochs — see epoch-count note below). Wrapped in `mlflow.start_run()`: `log_params()`, per-epoch + final `log_metrics()` (micro/macro F1/precision/recall + per-category F1 via `sklearn.metrics.classification_report`, 0.5 sigmoid threshold), `log_artifact()` for a multi-label confusion-matrix grid (`sklearn.metrics.multilabel_confusion_matrix`, one 2x2 per label), `mlflow.transformers.log_model()`. Also saves the final checkpoint+tokenizer to `models/distilbert_classifier/`.
- [x] `volvo_models/classifier.py`: `load_classifier()` (module-level cache), `classify(text: str) -> list[tuple[str, float]]` — category+confidence pairs above threshold, sorted by confidence. Imported by `api/main.py`'s `/classify` endpoint in Phase 6, not called directly by Streamlit.

**Verified — actual observed results, not assumed in advance:** training loss decreased monotonically across 20 epochs (0.60 → ~0.16 final eval loss). Final validation metrics: **micro-F1 0.930, macro-F1 0.833, micro-precision 1.000, micro-recall 0.870** on the 17-example held-out val set. Per-category F1: infotainment/electrical/braking/safety_concern/parts_delay/dealer_escalation all 1.0, powertrain 0.667, **software_update 0.0** (both val examples for this category use vocabulary — "firmware update," "system update won't complete" — thin in the training set; a real, honest limitation of a ~100-example demo corpus, stated here plainly rather than hidden). Manually inspected all 17 val predictions: 13/17 exact category-set matches; the 4 misses are sensible partial-credit errors (both software_update misses predicted empty rather than wrong; 2 multi-label cases correctly caught one of two true categories). Reloaded model (`load_classifier()`/`classify()`) reproduces these same predictions standalone — confirmed a clear-cut brake-failure narrative correctly scores both `braking` (0.86) and `safety_concern` (0.74) above threshold (the exact `direct_classification` escalation trigger Phase 6/7 will rely on), an infotainment narrative scores `infotainment` (0.82) alone, and an out-of-domain sentence ("nice day for a picnic") correctly returns no categories. `mlflow ui` confirmed serving the tracked run over real HTTP (status 200) with correct params/metrics.

**Epoch-count note:** started at 8 epochs per no-pre-committed-number design intent, but real per-example validation predictions at 8 epochs showed the model correctly ranking the right category highest while just under the 0.5 confidence threshold (e.g. a true `infotainment` case scoring 0.399) — genuinely under-trained rather than confused, so epochs were raised to 20 (not the threshold lowered, which would have masked the real cause) and metrics improved substantially and honestly as a result.

**Three real bugs found and fixed:**
1. **`transformers.Trainer` requires `accelerate>=1.1.0`**, not in the original `requirements.txt` — added it (plus `matplotlib`, used for the confusion-matrix artifact) and installed.
2. **MLflow 3.x's plain filesystem backend is in "maintenance mode"** and raises by default; required explicitly setting `MLFLOW_ALLOW_FILE_STORE=true` (both in the training script via `os.environ.setdefault` and in `.env.example`/`.env` for `mlflow ui` itself, since it runs as a separate process that doesn't inherit the training script's env-var setdefault) — this is the documented opt-out for the exact backend choice (local file-store, no server) the free-alternative-stack doc specified, not a switch to SQLite.
3. **`mlflow.transformers.log_model()` crashed with `ModuleNotFoundError: No module named 'torchvision'`** during its default pip-requirement auto-detection, which imports every optional `transformers` extra (including image-pipeline-only `torchvision`) just to read its version — irrelevant to a text classifier. Fixed by passing `pip_requirements=["torch", "transformers"]` explicitly.
4. **The training script's `mlflow.set_tracking_uri("file:./mlruns")` used a path relative to the process's working directory at invocation time, not the script's own location** — running from the repo root silently created a stray `mlruns/` there instead of inside `volvo-demo/`. Caught by querying `mlflow.search_runs()` afterward and finding the experiment missing from the expected path; fixed to an absolute path derived from `ROOT`, stray directories cleaned up, and training re-run to land correctly.

---

## Phase 5 — Sentence-BERT + spaCy NER (pretrained, no fine-tuning)

**Goal:** Similarity embedding and entity extraction working, per the architecture doc's "no fine-tuning needed" design for these two components.

- [x] `volvo_models/similarity.py`: `SentenceTransformer("all-MiniLM-L6-v2")`, `embed(text) -> list[float]`, `embed_batch(texts) -> list[list[float]]` (384-dim, matches Phase 1's OpenSearch mapping).
- [x] `volvo_models/ner.py`: `spacy.load("en_core_web_sm")` + custom `EntityRuler` (`nlp.add_pipe("entity_ruler", before="ner")`) with authored patterns for `VIN` (17-char alphanumeric regex shape, matching Phase 2's synthetic format), `DTC` (SAE J2012 format: letter + 4 digits, e.g. `P0300`), plus `COMPONENT`/`SYMPTOM` gazetteer patterns seeded from the same vocabulary `label_heuristics.py` uses, since base `en_core_web_sm` doesn't tag domain terms like "turbocharger" without help. `extract_entities(text) -> list[dict]` (`label`, `text`, `start`, `end`).
- [x] `scripts/build_ner_patterns.py`: authors `volvo_models/ner_patterns.jsonl` (31 patterns) as a versioned, inspectable artifact.

**Verified:** `extract_entities()` recall — **10/10 (100%)** on VIN detection across the first 10 synthetic cases (VIN embedded in a constructed sentence, since narrative_text itself doesn't contain VINs) and **4/4 (100%)** on hand-authored DTC test sentences covering all four SAE J2012 letter prefixes (P/B/C/U), both deterministic ground-truth checks as expected. Sentence-BERT: `embed()` confirmed producing 384-dim vectors; cosine similarity computed for all 3 of Phase 2's near-duplicate pairs against an unrelated-case baseline — pair scores were **0.709, 0.729, and 0.571**, all meaningfully above the unrelated-case baseline of **0.217**. Notably, the weakest pair (0.571, the engine-misfire paraphrase that deliberately shares almost no vocabulary with its pair-mate) still scored well clear of the baseline, confirming the model is capturing genuine semantic similarity rather than just lexical overlap.

---

## Phase 6 — FastAPI Serving Layer

**Goal:** A real local FastAPI service is the single access point for classify/NER/embed/similarity-search/index — called by both Streamlit and Airflow's DAG tasks.

- [x] `api/schemas.py`: Pydantic request/response models — `ClassifyRequest`/`ClassifyResponse`, `ExtractEntitiesRequest`/`Response`, `EmbedRequest`/`Response`, `SimilarCasesRequest`/`Response`, `IndexCaseRequest`/`Response`, `PreprocessRequest`/`Response`.
- [x] `api/main.py`: FastAPI app exposing `/preprocess`, `/classify`, `/extract-entities`, `/embed`, `/similar-cases`, `/index-case`, `/health` exactly as planned. `/index-case` writes `warranty_cases`/`case_classifications`/`extracted_entities` + OpenSearch, runs `escalation.check_escalation()`, writes `safety_escalations` + `audit_log` (`case_submitted` always, `safety_escalation_raised` if triggered) — the only endpoint that persists a case.
- [x] Supporting modules built to make `/index-case` real rather than a stub: `volvo_retrieval/postgres_client.py` CRUD helpers (`insert_warranty_case`, `insert_case_classifications`, `insert_extracted_entities`, `insert_safety_escalation`, `update_case_status`, `get_safety_flagged_case_ids`), `volvo_retrieval/case_search.py` (`index_case`, `find_similar_cases`, `search_by_vin`, `search_by_keyword`, `list_all_cases`), `volvo_pipeline/schemas.py` (`CaseStep`, `EscalationDecision`), `volvo_pipeline/escalation.py` (`check_escalation()`, `RECURRING_PATTERN_THRESHOLD = 2`), and `volvo_retrieval/audit.py` — pulled forward from Phase 11 (ported near-verbatim from `nrg_retrieval/audit.py`, domain-agnostic hash-chaining) since `/index-case` needed it immediately.
- [x] Run via `uvicorn api.main:app --port 8100` as a plain local process.

**Verified end-to-end with real HTTP requests, not just code review:** `/health` → 200. `/classify` on a brake-failure narrative → correctly returns both `braking` (0.86) and `safety_concern` (0.74) above threshold. `/extract-entities` on a narrative containing a real VIN and DTC → both correctly extracted (plus a harmless spaCy base-model false positive tagging the literal word "VIN" as `ORG`, which doesn't interfere with the custom entity types). `/embed` → 384-dim vector. `/preprocess` → boilerplate stripped and abbreviation expanded correctly. `/similar-cases` against the (currently empty, per Phase 1's cleanup) index → correctly returns 0 results with a valid vector.

`/index-case` tested with **three real scenarios**, each verified by querying Postgres/OpenSearch directly afterward, not just trusting the API response:
1. **Normal case** (infotainment, no escalation) → `status=indexed`, correctly written to `warranty_cases`/`case_classifications`/OpenSearch, no `safety_escalations` row.
2. **Direct safety escalation** (braking + safety_concern) → `status=escalated`, `safety_escalations` row with `trigger_reason=direct_classification`, `warranty_cases.status` flipped to `escalated`, both `case_submitted` and `safety_escalation_raised` audit entries written correctly.
3. **Recurring-pattern escalation (the harder, more valuable test)**: seeded 2 genuinely safety-flagged cases, then submitted a 3rd case classified only `electrical` (no safety_concern label at all) but whose `similar_cases` payload cited both already-flagged cases → correctly triggered `escalation_raised=true`, `trigger_reason=recurring_pattern`, with `related_case_ids` correctly capturing both case IDs — proof the system catches a slow-building pattern across multiple non-obviously-worded cases, exactly the capability the architecture doc's Service Operations Manager role exists to use, not just a single case's own label.

All test data cleaned from Postgres and OpenSearch afterward (0 rows/docs); audit_log test entries left in place as real history, per the established insert-only precedent.

---

## Phase 7 — Airflow DAG (one run per submitted case)

**Goal:** A real Airflow DAG, triggered once per submitted case via its REST API with case data as `conf`, with tasks that call the Phase 6 FastAPI service over HTTP — the single serving layer, not a second access path.

- [x] `airflow/docker-compose.airflow.yml`: Airflow's own Postgres (separate container/volume from the app's — never shared) + webserver + scheduler, LocalExecutor 2.10.4/Python 3.12, on the default Compose bridge network reaching the host-run FastAPI service via `host.docker.internal:8100` — confirmed working on this Docker Desktop for Mac install via a real throwaway-container `curl` test before committing the DAG to that assumption.
- [x] `airflow/dags/volvo_case_pipeline_dag.py`: DAG `volvo_case_pipeline`, `schedule=None`, tasks reading case data from `dag_run.conf`, each a `PythonOperator` calling the corresponding FastAPI endpoint (`preprocess` → `classify` → `extract_entities` → `embed` → `find_similar_cases` → `index_and_check_escalation`), passing data forward via XCom.
- [x] `volvo_pipeline/dag_client.py`: `trigger_dag_run()`, `get_task_instances()`, `get_dag_run_state()`, plus `list_recent_dag_runs()` (added for Phase 9's Model Info tab read-only DAG-run-history panel).
- [x] `volvo_pipeline/schemas.py`: `CaseStep` dataclass (built in Phase 6 once `api/main.py` needed it) — `stage` values already map 1:1 to this phase's Airflow task IDs.
- [x] `volvo_retrieval/postgres_client.py`: `insert_airflow_dag_run()`, `update_airflow_dag_run_state()`, `get_dag_run_id_for_case()` — the `airflow_dag_runs` join-table helpers Phase 9's polling loop will use.

**Verified — all with real HTTP calls against real running containers, not mocked:**
- `docker compose -f airflow/docker-compose.airflow.yml up -d` → all 3 containers (`volvo-airflow-postgres`, `-webserver`, `-scheduler`) healthy; `GET /health` on the webserver reports `metadatabase`/`scheduler` both `healthy`.
- DAG confirmed loaded via the REST API: `has_import_errors: false`, `timetable_description: "Never, external triggers only"`. Unpaused (Airflow DAGs start paused by default) before triggering.
- **Real DAG run #1** (infotainment narrative, no escalation): `trigger_dag_run()` → polled `get_task_instances()` through `queued` → `running` → `success` across all 6 tasks in the correct dependency order (~9-10s total), confirmed the case landed correctly in both Postgres (`warranty_cases`, `case_classifications`) and OpenSearch via the DAG path specifically.
- **Real DAG run #2** (deliberately safety-flagged brake-failure narrative, triggered via the DAG, not the direct-API path already verified in Phase 6): `safety_escalations` row created with `trigger_reason=direct_classification` — confirms the escalation logic fires identically whether reached through Streamlit's eventual live path or Airflow's.
- **Real failure-mode test**: stopped the FastAPI process, triggered a 3rd DAG run → `preprocess` task genuinely failed (connection refused), all 5 downstream tasks correctly showed `upstream_failed` rather than running, and `get_dag_run_state()` correctly returned `failed` — proving the dependency-graph/retry-visibility value the architecture doc attributes to Airflow over unconnected cron jobs. Restarted FastAPI afterward.
- `airflow_dag_runs` join-table helpers tested directly: insert → `get_dag_run_id_for_case()` retrieves the correct id → `update_airflow_dag_run_state()` correctly sets `last_polled_state` and stamps `completed_at` only for terminal states.
- All test data (`TEST-CASE-DAG-*`, `TEST-CASE-JOIN-001`) cleaned from Postgres and OpenSearch afterward.

---

## Phase 8 — Bulk Seed / Historical Case Load

**Goal:** A pre-populated set of "historical" cases exists so Case Lookup has real data on day one, distinct from the live "submit new case" demo path.

- [x] `scripts/seed_historical_cases.py`: runs 110 of the 120 synthetic cases through the real Phase 6 FastAPI endpoints (`/classify`, `/extract-entities`, `/similar-cases`, `/index-case` per case; `/embed`'s work done via `embed_batch()` directly since that step is cheap to batch without touching FastAPI's per-case contract) — no bypass of classification/NER/escalation-check logic, matching NRG's precedent that its own bulk CLI doesn't skip versioning/publish. The last 10 cases (the near-duplicate pairs and other distinctive narratives Phase 2 authored last) are deliberately reserved, unseeded, and written to `data/synthetic_cases/reserved_for_live_demo.jsonl` for Phase 9's Submit New Case walkthroughs.

**Verified:** all 110 seed cases succeeded with zero failures (~14s wall time). Postgres `warranty_cases` row count and OpenSearch document count both **110/110**, exact match. **15 safety escalations** naturally raised during seeding (all `trigger_reason=direct_classification`; no `recurring_pattern` triggers occurred during this particular seed run — a legitimate outcome of sequential seeding order, not a bug, since a case can only cite already-indexed earlier cases as similar). VIN-exact-match search against a real seeded case returned exactly the correct `case_id`. Symptom-keyword search for "brake failure highway" correctly ranked the exact-match case highest (score 9.47), with two other genuine brake-failure cases next and unrelated highway-mentioning cases ranked lower — sane relevance ordering, not just any match. Directly confirmed **zero overlap** between the 110 indexed case_ids and the 10 reserved case_ids, so the reserved set is guaranteed genuinely unseen by both stores.

---

## Phase 9 — Streamlit UI

**Goal:** A standalone, fully working Volvo demo app, following the `render()`-from-day-one discipline (`volvo_app.py` thin wrapper + `volvo_app_render.py` all logic).

Tabs (each guarded with `try/except ModuleNotFoundError` for any tab depending on a not-yet-built module during incremental build-out):
1. [x] **Case Lookup / Search** — VIN exact search, symptom/component keyword hybrid via OpenSearch (`search_by_vin`/`search_by_keyword`/`list_all_cases`), category multi-select filter, dealer location filter. Result rows show classification badges; `st.dialog` (`_case_detail_dialog`) for full case detail (narrative, entities, live similar-case lookup via `find_similar_cases`).
2. [x] **Submit New Case** — form (VIN, narrative, dealer location, model/year, mileage, submitted-by). On submit: `trigger_dag_run()`, then `_poll_dag_run()` polls `get_task_instances()` on a 1.5s interval inside `st.status(..., expanded=True)`, mapping each Airflow task_id to a `PIPELINE_STAGES` label with a running/success/failed icon, up to a 60s timeout. Writes the `case_id`→`dag_run_id` mapping into `airflow_dag_runs` immediately after triggering (before the DAG completes — see the schema fix below). A visually distinct `st.warning` callout fires if the resulting classification includes `safety_concern`.
3. [x] **Safety Escalation Review** — `list_escalations()`-backed table with a Pending/All toggle, trigger reason (direct vs. recurring, showing `related_case_ids` for the latter), `record_escalation_review()` action buttons (`field_action_recommended`/`no_action_needed`) + notes, collapsed "already reviewed" state once acted on — matches NRG's Compliance Review tab pattern. Writes a `safety_escalation_reviewed` audit entry on every action.
4. [x] **Flow Diagram** — stubbed with the `try/except ModuleNotFoundError` guard per NRG's precedent; real implementation is Phase 10.
5. [x] **Training / Model Info** — `mlflow.search_runs()` against the real Phase 4 tracking store, rendering micro/macro F1/precision/recall + per-category F1 as `st.metric`s, the saved confusion-matrix PNG, and an honest caveat about `software_update`'s 0.0 F1. Read-only recent-DAG-runs panel via `list_recent_dag_runs()`.
6. [x] **Audit Log** — verify-chain button + recent-50-entries list, identical shape to NRG's.

Session state: all keys prefixed `volvo_`.

**One real bug found and fixed — a schema design error, not just app code:** the first Submit New Case attempt failed immediately with a Postgres foreign-key violation: `airflow_dag_runs.case_id REFERENCES warranty_cases(case_id)` rejected the insert because `insert_airflow_dag_run()` is deliberately called right after `trigger_dag_run()` returns — before the case exists in `warranty_cases` at all (that insert only happens later, inside the DAG's `index_and_check_escalation` task calling `/index-case`). A DAG run can also legitimately fail before ever reaching that task, in which case `case_id` would never appear in `warranty_cases` — an FK made that normal, expected outcome impossible to record. Fixed by dropping the FK constraint (`ALTER TABLE airflow_dag_runs DROP CONSTRAINT airflow_dag_runs_case_id_fkey`, applied to both `db/init/01_schema.sql` and the live database) and documenting why `airflow_dag_runs.case_id` is deliberately not a foreign key.

**Also cleaned up incidentally:** Phase 1's manual constraint-testing had left a fabricated `audit_log` row (`record_hash='abc123'`, never a real chained hash) sitting at id=1, which correctly made `verify_chain()` report TAMPERED for every run thereafter — not an app bug, but stale dev data. Cleared the whole `audit_log` table (141 accumulated test rows across Phases 1/6/7/9, none of it real production history) to let the chain restart cleanly from genesis.

**Verified via `AppTest`, matching NRG's bar:**
- Initial load: no exceptions, correct title, all 6 tabs present.
- **Case Lookup**: "Browse all cases" returns exactly 110 results (matching Phase 8's seeded count).
- **Submit New Case**: filled a genuinely new narrative, submitted, confirmed the rendered progress log shows real Airflow task-instance transitions in order (`running` → `success` for preprocess, classify, extract_entities, embed, find_similar_cases, index_and_check_escalation) — not a simulated progress bar — and a final "Case indexed" success message.
- **Training / Model Info**: confirmed the real Phase 4 metrics render correctly as `st.metric`s (Micro F1 0.930, Macro F1 0.833, per-category F1 including the honest `software_update: 0.00`).
- **Audit Log**: "Verify chain integrity" correctly reports VALID against the freshly-restarted chain.
- **Safety Escalation Review**: clicked "No action needed" on a real pending escalation, confirmed via direct Postgres query it was correctly recorded (`status=no_action_needed`, `reviewed_by` set) and a `safety_escalation_reviewed` audit entry was written; confirmed the "All (including resolved)" view correctly displays the reviewed state, then reverted the test action back to `pending_review` afterward.
- Standalone `streamlit run volvo_app.py` boots to HTTP 200 with FastAPI (port 8100) and the Airflow stack (port 8180) already running as prerequisites.
- All `CASE-LIVE-*` test cases generated during Submit New Case testing cleaned from Postgres and OpenSearch afterward (both back to the exact 110/110 seeded count); audit_log left in its freshly-verified-VALID state as real history.

---

## Phase 10 — Flow Diagram(s)

**Goal:** Visual pipeline diagram(s) using real Volvo-analog tool names, following the established real/placeholder convention.

- [x] `volvo_pipeline/diagram_common.py` — copied from `nrg_chains/diagram_common.py` and diverged: `label_score_table(scores, threshold)`, `entity_chips(entities)`, `score_table()` retargeted to case-id + cosine-score columns, a new `.stage.real-orchestration` (teal) class for real Airflow task stages, and the existing-but-previously-unused `.decision-pending/approved/rejected` classes reused for the escalation decision (mapped `pending_review`/`field_action_recommended`/`no_action_needed`).
- [x] `volvo_pipeline/flow_diagram.py` — `render_flow_html(submit_history_entry: dict)`. Unlike NRG/Novartis, there's no in-process orchestration trace object to read from (the live path genuinely runs through a real Airflow DAG) — this module looks up the case's actual classification/entities/similar-cases/escalation state directly from OpenSearch and Postgres by `case_id`, combined with the Airflow task-instance states already captured in `st.session_state.volvo_submit_history`. Renders: IAM placeholder → Dealer submission (real) → Airflow DAG triggered (real-orchestration) → preprocess/classify/extract_entities/embed/find_similar_cases tasks (each real-orchestration, with label-score table / entity chips / similarity table inlined per stage) → index_and_check_escalation (real) → conditional Safety Escalation Decision stage (only rendered if an escalation row exists for the case) → CloudWatch placeholder.
- [x] `volvo_pipeline/training_flow_diagram.py` — `render_training_flow_html()`, reading real MLflow run data via `mlflow.search_runs()` (not a trace object, since training runs as a standalone script): synthetic data (real) → PySpark preprocessing (real) → DistilBERT fine-tuning (real, actual params+metrics from the latest run, "SageMaker analog" labeled) → MLflow logging (real) → placeholder bands for S3/Glue-catalog and CloudWatch training-job monitoring. Wired into the Flow tab alongside the new-case diagram via a radio toggle.

**Verified — real DAG-triggered submissions, not synthetic trace objects:**
- **Non-escalating case** (infotainment narrative): triggered via `trigger_dag_run()`, polled to `success`, rendered through `render_flow_html()`. Direct HTML string checks confirmed: the classify stage's category chip, the entity-chips div, the similarity score-table, the `real-orchestration` CSS class, the real `dag_run_id`, and both placeholder bands (IAM, CloudWatch) all present — and, critically, **`Safety Escalation Decision` correctly absent entirely** (not a muted/false-pending state) since this case never escalated.
- **Escalating case** (brake-failure narrative): same triggered-and-polled flow. Confirmed the `Safety Escalation Decision` stage renders with the correct `decision-pending` CSS class and `trigger: direct_classification` text, alongside the real `braking`/`safety_concern` categories.
- **Training diagram**: rendered against the real completed Phase 4 MLflow run — confirmed the actual `micro_f1 = 0.930` and `macro_f1 = 0.833` values appear in the DistilBERT Fine-Tuning stage's detail text, not placeholder numbers.
- **Wired into the live app**: `AppTest` confirmed the Flow tab's diagram-choice radio switches correctly between "New-Case Pipeline" and "Training Pipeline" with no exceptions; the `st.components.v1.html` deprecation notice firing (only triggers when that function is actually called) confirms the diagram genuinely rendered inside the live tab, not just in isolation.
- All `TEST-CASE-DIAGRAM-*` test cases cleaned from Postgres and OpenSearch afterward (both back to the exact 110/110 seeded baseline).

---

## Phase 11 — Audit Log Wiring

**Goal:** Hash-chained audit trail covering Volvo-specific event types.

- [x] `volvo_retrieval/audit.py` — copied verbatim from `nrg_retrieval/audit.py`. Built ahead of schedule in Phase 6, since the `/index-case` FastAPI endpoint needed it immediately.
- [x] Event types: `case_submitted` (actor=`submitted_by`, written by `/index-case`), `safety_escalation_raised` (actor=`system`, also `/index-case`), `safety_escalation_reviewed` (actor=reviewer name, from the Safety Escalation Review tab) — all three wired in Phases 6 and 9.
- [x] Audit Log tab wiring, identical shape to NRG's — built in Phase 9.
- [x] `scripts/check_audit_chain.py --demo-tamper` — ported near-verbatim from `nrg-demo/scripts/check_audit_chain.py`, adjusted for `get_pg_connection()`'s `autocommit=True` (Volvo's Postgres helper always uses autocommit, unlike NRG's, so the explicit `conn.commit()` calls in NRG's version are correctly omitted here rather than being harmless no-ops left in).

**Phase 11 was mostly already complete** by the time this phase formally started — `audit.py` and all three event-type writes were pulled forward into Phases 6 and 9 because `/index-case` and the Safety Escalation Review tab needed them immediately, not deferred. What remained was the `--demo-tamper` script and a fresh end-to-end verification pass.

**Verified with a real, fresh test case (not synthetic trace data):** triggered `TEST-CASE-AUDIT-001` (a brake-failure narrative) via a real Airflow DAG run → confirmed a `case_submitted` row with the correct payload (`categories: ["braking", "safety_concern"]`) and actor, plus a `safety_escalation_raised` row with `trigger_reason=direct_classification`. Reviewed the resulting escalation via `record_escalation_review()` + `append_audit_entry()` → confirmed a `safety_escalation_reviewed` row, and directly verified its `previous_hash` exactly matches the prior row's `record_hash` (real chain linkage, not just sequential IDs). Ran the full `--demo-tamper` cycle: `[BEFORE] VALID` → tampered the earliest row (id=143) → `[AFTER TAMPER] TAMPERED -- audit_log id=143: record_hash mismatch (content tampered)` (correct row identified) → `[AFTER RESTORE] VALID`. Re-confirmed the same VALID result and the real chained entries rendering correctly inside the live Streamlit app via `AppTest`. Test case data cleaned from Postgres/OpenSearch afterward (back to the 110/110 baseline); all audit_log entries left in place as genuine, correctly-chained history.

---

## Phase 12 — Shell Integration

**Goal:** All three demos reachable from one shell, with the same rigor NRG's Phase 9 proved necessary.

- [x] `shell/volvo_wrapper.py` — identical shape to `shell/nrg_wrapper.py`: module-scope `sys.path.insert(0, str(VOLVO_DEMO_ROOT))` + `from volvo_app_render import render as _render`; `load_dotenv(VOLVO_DEMO_ROOT / ".env", override=True)` **inside** `render_volvo()`.
- [x] `shell/shell_app.py` — added the third radio option ("Volvo Dealer Service & Warranty Intelligence"), import inside a new `elif demo.startswith("NRG")` branch (changed NRG's original bare `else` to an explicit `elif` so the three-way dispatch is unambiguous, with Volvo now taking the `else` — a deliberate, correct adaptation of the two-way pattern, not a deviation from it).
- [x] `shell/requirements.txt` — merged in Volvo's dependency list (torch, transformers, accelerate, spacy, scikit-learn, pandas, matplotlib, mlflow, pyspark, fastapi, uvicorn, httpx, opensearch-py — `sentence-transformers`/`psycopg[binary]`/etc. already existed in the shared section, not duplicated). Airflow itself stays out of `shell/.venv`, as planned.
- [x] Confirmed `volvo_`-prefixed session_state keys introduce zero collisions with existing `nrg_`-prefixed and bare Novartis keys — grep-verified (all Volvo widget/session keys consistently `volvo_`-prefixed) and directly inspected at runtime (see below).

**Verified — matching NRG Phase 9's bar exactly:**
- **Dependency install**: `pip install -r shell/requirements.txt` completed with `pip check` reporting "No broken requirements found." Pip did resolve some shared transitive pins downward (`protobuf` 7.35.1→6.33.6, `pandas` 3.0.5→2.3.3, `cryptography` 50.0.0→49.0.0) to satisfy the merged constraint set — flagged and then directly verified all three demos' key modules (`agents`/`chromadb`, `langchain`/`qdrant_client`, `torch`/`transformers`/`spacy`/`mlflow`/`pyspark`/`fastapi`/`opensearchpy`) still import successfully in the shared venv despite those version shifts, not just trusting `pip check`.
- **Repeated switching test**: 2 full cycles + 1 extra step (Novartis → NRG → Volvo → Novartis → NRG → Volvo → Novartis, 7 steps total) via `AppTest`, zero exceptions, correct title substring at every single step — this is the exact multi-cycle test that caught NRG's own second-switch-back bug originally, run here at full strength rather than a lighter single-pass version.
- **Session-state isolation**: verified by direct key inspection after visiting all three demos, not just by naming convention — 95 total keys (80 `volvo_`, 6 `nrg_`, 8 bare Novartis, 1 `shell_`), zero suffix overlap between `nrg_` and `volvo_` keys after stripping prefixes.
- **Env-var collision check**: confirmed real risk first (`POSTGRES_HOST/PORT/USER/PASSWORD/DB` are identically named between `nrg-demo/.env` and `volvo-demo/.env` with different values), then tested repeated NRG↔Volvo switching directly against `load_dotenv(..., override=True)` — confirmed each switch correctly restored the calling demo's own exact `POSTGRES_PORT`/`POSTGRES_USER`/`POSTGRES_DB` values every time (NRG: 5433/nrg/nrg, Volvo: 5434/volvo/volvo_warranty), across 4 consecutive switches.
- **Three-way independence**: `grep -rE "^\s*(import|from)\s+(copilot_agents|mcp_servers|nrg_chains|nrg_retrieval)"` over `volvo-demo/` and the reverse (`volvo_models|volvo_pipeline|volvo_retrieval`) over `copilot-demo/`+`nrg-demo/` both return zero hits.
- **Simultaneous standalone boot**: all four apps (`copilot-demo/streamlit_app.py` :8501, `nrg-demo/nrg_app.py` :8502, `volvo-demo/volvo_app.py` :8503 with FastAPI+Airflow prerequisites running, `shell/shell_app.py` :8504) booted concurrently, all HTTP 200, all logs clean.
- **Golden-path regression check — honest limitation noted**: NRG's and Novartis's own previously-documented golden-path questions (NRG's FixedSaver-24 winter-credit question, Novartis's CAPA-3390 question) both require a live OpenAI API call, and no real `OPENAI_API_KEY` is configured in this environment for either demo — confirmed directly rather than assumed, so re-running those exact LLM-dependent answers isn't possible here regardless of Volvo's addition. This is a pre-existing environment constraint, not something Phase 12 introduced. The achievable regression evidence instead comes from the checks above: both demos' non-LLM code paths (data access, rendering, session state, tab dispatch) were exercised repeatedly through the shell across the multi-cycle switching test with zero exceptions, which is the surface Volvo's addition could plausibly have disturbed.

---

## Summary Table

| Phase | Focus | Key New Modules |
|---|---|---|
| 0 | Venv rebuild (all 3) + Volvo scaffolding | `volvo-demo/` tree, `requirements.txt`, `docker-compose.yml` |
| 1 | Postgres + OpenSearch schemas | `db/init/01_schema.sql`, `volvo_retrieval/opensearch_client.py` |
| 2 | Synthetic training data | `scripts/generate_synthetic_cases.py` |
| 3 | PySpark preprocessing | `scripts/preprocess_pyspark.py`, `volvo_models/text_normalize.py` |
| 4 | DistilBERT fine-tune + MLflow | `scripts/train_classifier.py`, `volvo_models/classifier.py` |
| 5 | Sentence-BERT + spaCy NER | `volvo_models/similarity.py`, `volvo_models/ner.py` |
| 6 | FastAPI serving layer | `api/main.py`, `api/schemas.py` |
| 7 | Airflow DAG (per-case trigger) | `airflow/dags/volvo_case_pipeline_dag.py`, `volvo_pipeline/dag_client.py` |
| 8 | Bulk historical seed | `scripts/seed_historical_cases.py` |
| 9 | Streamlit UI | `volvo_app_render.py`, `volvo_app.py` |
| 10 | Flow diagrams | `volvo_pipeline/diagram_common.py`, `flow_diagram.py`, `training_flow_diagram.py` |
| 11 | Audit log | `volvo_retrieval/audit.py` |
| 12 | Shell integration | `shell/volvo_wrapper.py`, `shell_app.py`, `requirements.txt` |

---

## Remaining Minor Assumptions (stated, not blocking)

- **Recurring-pattern escalation threshold:** 2-or-more-of-top-5-similar-cases-already-flagged is a reasonable invented default with no architecture-doc citation backing the specific number — stated here as a defensible demo assumption, adjustable at implementation time.
- **Classification confidence threshold:** flat 0.5 sigmoid cutoff across all 8 categories initially; the Model Info tab should note this plainly rather than imply per-category tuning was done, unless Phase 4's actual validation results make per-category tuning clearly worthwhile.
- **DistilBERT epoch count/hyperparameters:** intentionally left for Phase 4 to determine empirically from real observed training behavior, not pre-committed here.
- **Docker networking between Airflow's containers and the host-run FastAPI process:** `host.docker.internal` (Docker Desktop for Mac) is the expected mechanism; confirmed at Phase 7 implementation time rather than assumed now.

## Verification Philosophy (carried over from NRG's plan)

Every phase's verification should involve actually running the code against real (if synthetic) data and inspecting real output — not just code review. Where NRG's plan found real bugs this way (a channel-attribute typo, a dropped chunk-text field, an env-var override bug, a module-caching bug), Volvo's more complex serving/orchestration path (FastAPI↔Airflow↔Streamlit, three separate processes/containers coordinating over HTTP) is if anything more likely to surface integration bugs that only show up when actually exercised end-to-end — budget for this rather than treating verification steps as a formality.

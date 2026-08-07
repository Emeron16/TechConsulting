# Local/Free Implementation Plan — NRG Energy Knowledge Copilot (LangChain + Qdrant)

## Context

[NRG_Energy_Architecture_Deep_Dive.md](NRG_Energy_Architecture_Deep_Dive.md) describes an AWS architecture (LangChain orchestrator, Bedrock, Titan Embeddings, OpenSearch Serverless hybrid retrieval, S3/Textract, SNS+SQS async ingestion, Redis, ECS Fargate, IAM/KMS/Secrets Manager, CloudWatch/CloudTrail, RAGAS/G-Eval, periodic Compliance/Legal statistical sampling instead of mandatory per-answer review). [NRG_Free_Alternative_Stack.md](NRG_Free_Alternative_Stack.md) maps each AWS service to a free/local equivalent.

This is a **second, mostly-independent demo** alongside [copilot-demo/](copilot-demo/) (the Novartis CMC Quality Copilot), reachable from the same running Streamlit app via a left-sidebar switch. It deliberately diverges from Novartis's proven tool choices — LangChain instead of the OpenAI Agents SDK, Qdrant instead of ChromaDB — so the two demos showcase different real tools while sharing the same architectural rigor (versioned KB, audit log, hybrid retrieval, human-in-the-loop, flow diagrams) and UI shell.

**Confirmed scope decisions:**
- Orchestration: **LangChain** (LCEL), not OpenAI Agents SDK
- Vector store: **Qdrant** (Docker, dense + sparse named vectors, native hybrid RRF fusion), not ChromaDB
- Chain shape: **one retrieval chain with doc_type-classification-based metadata filtering**, not a multi-agent router — matches the deep-dive's single "LangChain Orchestrator" box
- LLM: **OpenAI API, `gpt-4o-mini`**. Embeddings: **`text-embedding-3-small`**
- Human-in-the-loop: **statistical sampling**, not a mandatory pre-publish gate — every answer is logged and shown immediately; Compliance/Legal reviews a sample after the fact (the documented contrast with Novartis in the deep-dive itself)
- Local infra: **Docker Compose with Postgres + Qdrant + RabbitMQ**. RabbitMQ models the deep-dive's SNS+SQS "document processed" async event — ingestion parsing/chunking is synchronous, but embedding+indexing into Qdrant happens asynchronously via a queue consumer, including dead-letter-queue wiring for failed consumption
- Document parsing: **unstructured.io** (Textract analog), including 2–3 real PDF sample documents so table/layout extraction is actually exercised
- Caching: **diskcache**, matching Novartis's proven implementation (not Redis, per priority on local tools)
- Project lives in `nrg-demo/`, sibling to `copilot-demo/`, split into `nrg_chains/` (LangChain orchestration + diagrams + sampling) and `nrg_retrieval/` (Qdrant/Postgres/RabbitMQ/unstructured.io access) — mirrors Novartis's `copilot_agents/`+`mcp_servers/` separation without implying an MCP-style process boundary that doesn't exist in this architecture
- Shell: a **new top-level `shell/` Streamlit app** with a sidebar radio, importing each demo's rendering logic via a thin per-demo wrapper doing its own `sys.path` shim. `copilot-demo/` and `nrg-demo/` never import each other's internals

**Reference implementation patterns from copilot-demo (adapt, don't copy):**
- [copilot-demo/streamlit_app.py](copilot-demo/streamlit_app.py) — UI idioms (tabs, `st.dialog` doc viewer, `st.status` live ingest progress)
- [copilot-demo/copilot_agents/ask_flow.py](copilot-demo/copilot_agents/ask_flow.py) — single orchestration function shared by CLI + UI, full trace for diagramming
- [copilot-demo/copilot_agents/kb_ingest.py](copilot-demo/copilot_agents/kb_ingest.py) — parse → chunk → version-check → embed → store as `Generator[IngestStep, ...]`
- [copilot-demo/copilot_agents/schemas.py](copilot-demo/copilot_agents/schemas.py) — Pydantic shapes for search results / grounded answers
- [copilot-demo/mcp_servers/common.py](copilot-demo/mcp_servers/common.py), [hybrid_search.py](copilot-demo/mcp_servers/hybrid_search.py) — retrieval + caching pattern to reimplement against Qdrant
- [copilot-demo/copilot_agents/diagram_common.py](copilot-demo/copilot_agents/diagram_common.py), [flow_diagram.py](copilot-demo/copilot_agents/flow_diagram.py), [ingest_flow_diagram.py](copilot-demo/copilot_agents/ingest_flow_diagram.py) — HTML/CSS diagram rendering, real-vs-`placeholder` convention, to duplicate and extend
- [copilot-demo/docker-compose.yml](copilot-demo/docker-compose.yml), [db/init/](copilot-demo/db/init) — Compose + schema-init pattern

---

## Architecture Mapping Recap (from [NRG_Free_Alternative_Stack.md](NRG_Free_Alternative_Stack.md))

| Original Layer | Local/Free Build Choice |
|---|---|
| Reasoning | OpenAI API, `gpt-4o-mini` |
| Agent/Chain Orchestration | LangChain (single LCEL retrieval chain + doc_type classifier, not multi-agent) |
| Vector/Hybrid Search | Qdrant (dense + sparse named vectors, native Query API RRF fusion) |
| Embeddings | OpenAI `text-embedding-3-small` |
| OCR/Document Intelligence | unstructured.io (partition/table extraction) |
| Object Storage | Postgres `kb_documents` + local filesystem (S3 analog) |
| Async Messaging | RabbitMQ (SNS+SQS analog), with DLQ |
| Caching | diskcache (not Redis, matches Novartis's proven implementation) |
| Human-in-the-loop | Statistical sampling — `sampled_answers` table, never gates the answer |
| Audit Log | Postgres append-only table with hash chaining |
| Identity/Secrets/Observability (IAM, KMS, Secrets Manager, CloudWatch, CloudTrail, ECS Fargate) | Deferred / diagrammed only — no local analog implemented |

---

## Directory Structure

```
nrg-demo/
├── .env / .env.example, .gitignore, docker-compose.yml, requirements.txt
├── data/synthetic_docs/           # 11 docs (8 .md, 3 .pdf)
├── db/init/01_schema.sql
├── cache/                         # diskcache dirs, gitignored
├── scripts/
│   ├── ingest.py, ask.py, review.py
│   ├── consume_ingestion_events.py
│   ├── check_qdrant_health.py, check_audit_chain.py
├── nrg_chains/                    # orchestration (LangChain)
│   ├── schemas.py, classifier.py, retriever.py, prompts.py, chain.py
│   ├── cache.py, sampling.py, ingest.py
│   ├── diagram_common.py, flow_diagram.py, ingest_flow_diagram.py
├── nrg_retrieval/                 # data access (Qdrant/Postgres/RabbitMQ/unstructured)
│   ├── qdrant_client.py, hybrid_search.py, postgres_client.py
│   ├── rabbitmq_events.py, document_parser.py, audit.py
├── nrg_app.py                     # standalone entrypoint: set_page_config() + render()
└── nrg_app_render.py              # actual tabs/UI

shell/                             # NEW top-level nav shell (built last, Phase 9)
├── shell_app.py, novartis_wrapper.py, nrg_wrapper.py, requirements.txt
```

---

## Phase 0 — Project Scaffolding & Environment ✅ Complete

**Goal:** A working local dev environment before any chain code is written.

- [x] Created `nrg-demo/` with subfolders: `nrg_chains/`, `nrg_retrieval/`, `data/synthetic_docs/`, `db/init/`, `scripts/`, `cache/`
- [x] `docker-compose.yml` with **Postgres** (5433), **Qdrant** (6343/6344 — bumped from the planned 6333/6334 after discovering those ports already in use by an unrelated running container), **RabbitMQ** (5673/15673) — distinct ports/container names/volumes from copilot-demo so both stacks run concurrently
- [x] Python venv (`.venv`, Python 3.14) + `requirements.txt`: `langchain`, `langchain-openai`, `langchain-core`, `qdrant-client`, `fastembed`, `unstructured[pdf]`, `aio-pika`, `psycopg[binary]`, `python-dotenv`, `pyyaml`, `streamlit`, `pydantic`, `diskcache`, `tenacity`, `sentence-transformers`
- [x] `.env.example` / `.env`: `OPENAI_API_KEY` (copied from copilot-demo's own key), `POSTGRES_*`, `RABBITMQ_*`, `QDRANT_*`
- [x] `.gitignore` — same Drive-sync exclusions as copilot-demo (`.venv/`, `cache/`, `.env`, container-owned data via named volumes not bind-mounts)
- [x] **Qdrant healthcheck fix:** the `qdrant/qdrant` image has no `wget`/`curl`/`bash` (distroless-style), so a `wget`-based `CMD-SHELL` healthcheck fails every time even though the service itself is healthy (confirmed via `curl http://localhost:6343/readyz` from the host → `"all shards are ready"`). Removed the in-container healthcheck for the `qdrant` service and documented that readiness is verified from the host instead (Phase 1's `check_qdrant_health.py`).
- [x] Verified: `docker compose up -d` in `nrg-demo/` → all 3 containers up, Postgres+RabbitMQ healthy, Qdrant confirmed ready via host-side `readyz` check — running simultaneously with copilot-demo's own stack (`copilot-postgres`, `copilot-rabbitmq`) with zero port/name/volume collisions; all key packages (`langchain` 1.3.14, `qdrant-client` 1.19.0, `langchain-openai` 1.4.1, `fastembed` 0.8.0, `unstructured` 0.18.32, `streamlit`, etc.) import cleanly
- [x] **API-surface flags resolved:** confirmed on installed versions — `QdrantClient.create_collection(vectors_config=..., sparse_vectors_config=...)` and `QdrantClient.query_points(query=FusionQuery(...), prefetch=[Prefetch(...)])` (modern Query API) both present as designed; `ChatOpenAI.with_structured_output` available. No fallback paths needed for Phases 1/3/4.

## Phase 1 — Schemas ✅ Complete

**Goal:** Qdrant collection and Postgres schema exist and are verified before any data flows through them.

- [x] `db/init/01_schema.sql`: `kb_documents`, `ingestion_events`, `sampled_answers`, `audit_log` (hash-chained, insert-only trigger)
- [x] `nrg_retrieval/qdrant_client.py`: `get_qdrant_client()`, `ensure_collection()` — collection `nrg_knowledge_base`, named vectors `dense` (1536-dim cosine) + `sparse` (fastembed), payload fields to be written per-point during ingestion (`doc_id`/`doc_type`/`title`/`version`/`status`/`effective_date`/`plan_type`/`chunk_index`/`source_file`)
- [x] `scripts/check_qdrant_health.py`
- [x] Verified: Postgres recreated with a fresh volume after schema authoring (the container had already initialized once against an empty `db/init/`) → all 4 tables present; `audit_log` insert-only trigger confirmed rejecting both UPDATE and DELETE; `kb_documents` one-active-per-doc_id partial unique index confirmed rejecting a second active row for the same `doc_id`; Postgres reset to a clean (0-row) state afterward since the audit trigger makes test rows undeletable. `check_qdrant_health.py` confirms collection `nrg_knowledge_base` exists with `dense` (size=1536) and `sparse` named vectors both OK, 0 points (expected pre-ingestion)

## Phase 2 — Ingestion Pipeline + Sample Docs ✅ Complete

**Goal:** Real (if synthetic) NRG documents, parsed via unstructured.io, chunked, and flowing asynchronously into Qdrant via RabbitMQ.

- [x] Authored 11 synthetic docs (12 files) in `data/synthetic_docs/`: `PLAN-FIXED24-TX` (PDF), `PLAN-VAR-TX`, `PLAN-FREENIGHTS-TX` (v1+v2), `BILL-LATEFEE-POLICY` (PDF), `BILL-AUTOPAY-DISCOUNT`, `OUTAGE-COMMS-PROTOCOL`, `OUTAGE-WINTER-STORM-PLAYBOOK`, `ESC-BILLING-DISPUTE`, `ESC-SAFETY-CONCERN`, `EFL-FIXEDSAVER24-TX` (PDF), `EFL-VARRATE-TX`. PDFs generated via `reportlab` (added to `requirements.txt`) with genuine tables (rate tiers, EFL price tables), not just prose. `plan_type` required only for `plan_rate` docs (discovered during build that `billing_policy`/`escalation_playbook`/`outage_procedure` docs are typically plan-agnostic — narrowed `DOC_TYPES_REQUIRING_PLAN_TYPE` from the original two-doc-type plan to just `plan_rate`)
- [x] `nrg_retrieval/document_parser.py` — `.md` via YAML frontmatter (same convention as copilot-demo); `.pdf` via `unstructured.partition.pdf.partition_pdf(strategy="hi_res", infer_table_structure=True)`, with metadata read from a plain-text `key: value` block (PDFs have no YAML frontmatter concept) and `Table` elements preserved as structured HTML via `element.metadata.text_as_html` rather than flattened prose
- [x] `nrg_chains/cache.py` — diskcache port (embeddings + retrieval namespaces, ported from `copilot_agents/cache.py` minus the Chroma-specific `CachedEmbeddingFunction` wrapper, replaced with a plain `get_cached_embeddings_batch()` function since NRG calls OpenAI embeddings directly)
- [x] `nrg_retrieval/postgres_client.py` — connection + `kb_documents`/`ingestion_events` helpers
- [x] `nrg_chains/ingest.py` — `ingest_document()` generator: parse → chunk → version-check against Postgres `kb_documents` → publish to RabbitMQ (synchronous steps end here — no embed/store yet)
- [x] `nrg_retrieval/rabbitmq_events.py` — exchange `nrg.ingestion` (direct), queue `document_processed` (durable), DLQ exchange `nrg.ingestion.dlq` + queue `document_processed.dlq` via `x-dead-letter-exchange`/`x-dead-letter-routing-key`, `publish_document_processed()`, `declare_topology()`
- [x] `scripts/consume_ingestion_events.py` — standalone `aio-pika` consumer: dense (OpenAI `text-embedding-3-small`, diskcache-wrapped) + sparse (`fastembed` `Qdrant/bm25`) embed per chunk, upsert to Qdrant via deterministic UUID5 point IDs (so re-ingesting a doc_id/chunk_index overwrites rather than duplicates), marks `ingestion_events.status='consumed'`; tracks delivery attempts via a re-publish-with-incremented-header retry (AMQP has no native per-message retry counter), nacks to DLQ (`requeue=False`) after `MAX_DELIVERY_ATTEMPTS=3`
- [x] `scripts/ingest.py` — CLI bulk-ingest driving all sample docs through `nrg_chains.ingest.ingest_document()` (unlike copilot-demo's bulk CLI, this does NOT bypass versioning/publish — there is no separate fast path, since skipping the RabbitMQ publish would leave bulk-ingested docs permanently unindexed)
- [x] **Bug found and fixed during verification:** `on_message()`'s retry re-publish originally used `message.channel.default_exchange`, but `message.channel` is the raw low-level channel object without that attribute — surfaced immediately on the first real retry test (`AttributeError: 'Channel' object has no attribute 'default_exchange'`). Fixed by threading the actual `aio_pika.Channel` object from `main()` into `on_message()` as an explicit parameter instead of trying to derive it from the message.
- [x] **Verified end-to-end:** ingested all 12 files with the consumer running → all 12 published, all 12 consumed, Qdrant point count (34) matches the sum of per-doc chunk counts exactly; confirmed `PLAN-FREENIGHTS-TX`'s v2 upsert correctly overwrote v1's points (same deterministic point IDs) rather than duplicating; a live hybrid-search sanity query for "winter usage credit for fixed rate plan" correctly ranked `PLAN-FIXED24-TX` first with a perfect fused score, proving the full PDF→parse→chunk→publish→consume→embed→index pipeline is genuinely working, not just structurally present
- [x] **Message durability verified:** stopped the consumer, re-ingested a doc, confirmed the message sat durably in RabbitMQ (visible via the management API at :15673, 0 active consumers) until the consumer restarted and drained it immediately
- [x] **DLQ verified:** published a deliberately malformed message (missing required `chunks` key) with the consumer running → 3 failed attempts logged, then correctly dead-lettered; confirmed via the management API that the primary queue returned to 0 messages and the DLQ received exactly 1
- [x] All test-generated artifacts (extra document versions, malformed test message) cleaned up afterward; Postgres/Qdrant/RabbitMQ reset to a fully clean state (0 rows/points/messages) for Phase 3 to build on

## Phase 3 — Retrieval ✅ Complete

**Goal:** Qdrant hybrid search proven non-degenerate — both dense and sparse signals genuinely contribute.

- [x] `nrg_retrieval/hybrid_search.py` — Qdrant Query API (`query_points` + `Prefetch` + `FusionQuery(fusion=Fusion.RRF)`), plus a cross-encoder rerank layer (`cross-encoder/ms-marco-MiniLM-L-6-v2`, same model as copilot-demo) applied on top of the fused results, plus a "merge chunks by doc_id" collapse step (ported from copilot-demo's reasoning: multiple chunks of the same doc reading as ambiguous/duplicate results to a downstream LLM)
- [x] `nrg_chains/cache.py` — diskcache wrapper (ports `copilot_agents/cache.py`'s embeddings + retrieval namespaces; the Chroma-specific `CachedEmbeddingFunction` class was replaced with a plain `get_cached_embeddings_batch()` function since NRG calls OpenAI embeddings directly rather than through Chroma's embedding-function protocol)
- [x] **Design note (deviation from the original checklist wording):** Qdrant's Query API returns one fused `point.score` per result after RRF combines the dense and sparse rankings server-side — the pre-fusion per-space scores aren't separately recoverable from that single call without re-running both `Prefetch` queries standalone, which `hybrid_search()` deliberately avoids doing twice. So `dense_score`/`sparse_score` are surfaced as `None` by design (documented in the module's docstring); `fusion_score` and `rerank_score` are the scores that actually drive ranking and are always populated. This is a real simplification Qdrant's native hybrid API provides over copilot-demo's hand-rolled pipeline (which does expose separate `bm25_score`/`vector_score` because it runs both searches as fully separate steps) — not a shortfall, but worth being explicit that "non-null dense/sparse scores" as originally phrased doesn't apply verbatim here.
- [x] **Bug found and fixed before first real test:** the RabbitMQ message payload stored chunk text and chunk metadata as sibling keys (`chunk["text"]`, `chunk["metadata"]`), but `scripts/consume_ingestion_events.py`'s `process_message()` was writing only `chunk["metadata"]` as the Qdrant point payload — silently dropping the chunk text needed to build search excerpts. Fixed by merging `{**chunk["metadata"], "text": chunk["text"]}` into the point payload before upsert.
- [x] **Verified:** re-ingested the full 12-file corpus (consumer + bulk ingest) to repopulate Qdrant; an **exact-terminology** query (`"$10.00 flat late fee"`) correctly ranked `BILL-LATEFEE-POLICY` first with a strong margin (fusion=0.83, rerank=+3.5); a **paraphrased** query (`"does the two year fixed plan give you money back in winter"` — deliberately avoiding the source doc's actual wording "24-month"/"Winter Usage Credit"/"$25 bill credit") correctly ranked `PLAN-FIXED24-TX` first (fusion=0.75) on semantic similarity alone, proving dense retrieval is carrying real weight; a `doc_type="outage_procedure"` filter correctly narrowed a generic "plan" query down to only the 2 outage documents, excluding the more lexically-related `plan_rate` docs; retrieval caching confirmed working (`cache_hit: False` then `True` on a repeat identical call). All stores reset to clean (0 rows/points) afterward, test-generated versioned document copies removed, keeping only the 12 originally authored files

## Phase 4 — LangChain Chain ✅ Complete

**Goal:** The single retrieval chain — classify → filter → retrieve → generate grounded, cited answer.

- [x] `nrg_chains/schemas.py` — `ClassifiedQuery`, `SearchResultNRG`, `GroundedAnswerNRG` (deliberately no `requires_human_review` field, per the statistical-sampling design)
- [x] `nrg_chains/prompts.py` — `CLASSIFY_PROMPT` (5 doc_type categories + null/out-of-scope fallback) and `ANSWER_PROMPT` (grounded-answer + citation rules), `nrg_chains/classifier.py` (`ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(ClassifiedQuery)` — confirmed working on the installed `langchain-openai` version, no `PydanticOutputParser` fallback needed)
- [x] `nrg_chains/retriever.py` — `NRGHybridRetriever(BaseRetriever)` subclass wrapping `hybrid_search()`, `doc_type` set per-instance
- [x] `nrg_chains/chain.py` — `run_question(question) -> AskResult`, explicit async function populating `ChainTraceStep`s per stage (classification/retrieval/fallback/generation/sampling); fallback logic (unfiltered retry if filtered retrieval comes up empty, then a canned low-confidence answer with no LLM call if still empty)
- [x] `nrg_chains/sampling.py` — `log_sampled_answer()`, unconditional `sampled_answers` write on every call, no gating
- [x] `scripts/ask.py` — CLI entry point
- [x] **Verified end-to-end** with 4 real questions run through the full chain against the re-ingested 12-document corpus:
  1. *"Does the FixedSaver 24 plan include a winter usage credit?"* → classified `plan_rate`, retrieved and correctly cited only `PLAN-FIXED24-TX`, answered "Yes" with the exact $25/1,000 kWh/Dec–Feb detail pulled from the PDF-sourced table, confidence `high`
  2. *"Does the VarSaver plan include a winter usage credit?"* (discrimination test) → classified `plan_rate`, correctly cited only `PLAN-VAR-TX`, answered "No" — confirmed **no cross-plan bleed** from `PLAN-FIXED24-TX`'s credit
  3. *"What is the renewable energy content percentage disclosed on the FixedSaver 24 EFL?"* (near-duplicate discrimination test) → correctly classified `compliance_disclosure` (not `plan_rate`, despite "FixedSaver 24" appearing in the question) and cited `EFL-FIXEDSAVER24-TX` specifically, not the plan doc — proves the classifier distinguishes "plan terms" from "EFL disclosure wording" questions about the same plan, exactly the test case the sample corpus was designed for in Phase 2
  4. *"What's your favorite movie?"* (out-of-scope) → classifier correctly returned `doc_type=None`, unfiltered retrieval ran (5 results, none relevant), generation correctly refused to answer rather than hallucinating (`confidence=low`, `citations=[]`)
- [x] Confirmed via direct Postgres query that all 4 runs — including the out-of-scope one — produced exactly one `sampled_answers` row each (ids 1–4), all with `reviewed=false`: every answer is logged unconditionally and nothing is held back pending review, exactly the statistical-sampling design requirement

## Phase 5 — Streamlit Page ✅ Complete

**Goal:** A standalone, fully working NRG demo app before shell integration.

- [x] `nrg_app_render.py` (built as `render()` from the start, exactly as designed to avoid the extraction copilot-demo needs in Phase 9) + `nrg_app.py` (thin `set_page_config()` + `render()` wrapper)
- [x] `nrg_retrieval/kb_actions.py` — search/browse/version-history/content-viewing helpers (parallel to copilot-demo's `mcp_servers/kb_actions.py`, simplified since NRG has no bypass-Postgres bulk path — `kb_documents` is always the source of truth)
- [x] Ask tab, Knowledge Base tab (browse/search/upload, reusing the `st.dialog` doc-viewer pattern); Flow/Compliance/Audit tabs stubbed with `st.info()` placeholders (Phases 6/7/8) — the Flow tab's stub is wrapped in a `try/except ModuleNotFoundError` since Streamlit executes every tab's body on every script run regardless of which tab is visually selected (`st.tabs()` isn't lazy), so an unconditional import of not-yet-built Phase 6 modules would crash the whole page, not just that tab
- [x] **Testing methodology note:** no browser-driving tool (`chromium-cli` or equivalent) was available in this environment. Verified instead via Streamlit's own `streamlit.testing.v1.AppTest` harness, which runs the real app script through Streamlit's actual execution engine (not just calling the underlying Python functions in isolation) — fills real widgets, clicks real buttons, and inspects real rendered output, the legitimate headless-equivalent to browser-driving for a Streamlit app specifically.
- [x] **Two real bugs found and fixed by actually running the app, not just reading the code:**
  1. `nrg_retrieval/kb_actions.py` imports the `markdown` package (copied from copilot-demo's pattern) but it was never added to `nrg-demo/requirements.txt` — surfaced immediately as a `ModuleNotFoundError` on the very first `AppTest` run. Fixed by adding `markdown` to `requirements.txt` and installing it.
  2. `_render_flow_tab()` unconditionally imported `nrg_chains.flow_diagram`/`nrg_chains.ingest_flow_diagram`, which don't exist until Phase 6 — crashed the entire page on load (not just the Flow tab) because Streamlit renders every tab's body on every run. Fixed with a `try/except ModuleNotFoundError` around the import, falling back to an `st.info()` placeholder until Phase 6 builds those modules.
- [x] **Verified end-to-end via `AppTest`:** initial page load (no exceptions, correct title, tabs present); full Ask-tab flow (typed the EFL renewable-content question, clicked Ask, confirmed the rendered answer contained the correct "20%" figure, confirmed the Confidence/Classified-as/Citations metrics rendered correctly: `high`/`plan_rate`/`1`, source shown as `PLAN-FIXED24-TX` for the winter-credit question); Knowledge Base search (`"late fee"` → correct result count) and browse-all (11 documents listed); direct `get_document_content()` checks confirmed markdown docs render full HTML, PDF-sourced docs show the documented "view original file" fallback notice, and `PLAN-FREENIGHTS-TX` version history correctly shows v2 active / v1 superseded
- [x] **Process discipline note:** discovered mid-testing that deleting versioned document copies from disk (routine test cleanup in Phases 2–4) left stale `kb_documents.file_path` rows pointing at now-deleted files, breaking the document viewer. Not an application bug — a byproduct of manual disk cleanup outrunning the DB state. Resolved with a full clean reset (Postgres + Qdrant volumes dropped, RabbitMQ queue purged) followed by one fresh, consistent re-ingest of all 12 files; going forward, cleanup should reset DB/Qdrant state alongside any disk file removal, not disk files alone
- [x] Confirmed the standalone app also serves correctly outside `AppTest` — `streamlit run nrg_app.py` on port 8502, `curl` returns HTTP 200 with the real Streamlit app shell (not an error page), confirming no top-level exception on actual server boot either

## Phase 6 — Flow Diagrams ✅ Complete

**Goal:** Visual pipeline diagrams showing real NRG-analog tool names, following Novartis's real/placeholder convention.

- [x] `nrg_chains/diagram_common.py` — duplicated + extended from copilot-demo's `copilot_agents/diagram_common.py` (pure presentation code, deliberately duplicated rather than cross-imported to preserve the two demos' independence). New `real-event` amber stage class for the RabbitMQ publish stage, new `.arrow.async-boundary` dashed-arrow CSS variant and `arrow(async_boundary=True)` parameter, new `.stage.annotation` class for future retrospective (non-gating) review annotations, new `score_table()` shaped for Qdrant's fusion+rerank columns (2 columns, not copilot-demo's 4, since Qdrant's native fusion doesn't expose separable pre-fusion dense/sparse scores — see Phase 3's design note)
- [x] `nrg_chains/flow_diagram.py` — Ask-flow: API Gateway/IAM (placeholder) → User Question → LangChain Orchestrator classification (real) → Qdrant hybrid retrieval with fusion/rerank score table + cache badge (labeled "OpenSearch Serverless analog") → Secrets Manager/KMS (placeholder) → gpt-4o-mini (labeled "Amazon Bedrock analog") → Final Answer → **unconditional** Postgres `sampled_answers` write, always rendered as a normal solid real stage — no pending/gate stage exists in this diagram at all, unlike Novartis's conditional Human Review stage → CloudWatch/CloudTrail/RAGAS (placeholder) → ECS Fargate/ECR/GitHub Actions (placeholder)
- [x] `nrg_chains/ingest_flow_diagram.py` — Ingest-flow: IAM (placeholder) → File Upload → unstructured.io parse (labeled "Amazon Textract analog") → Chunk → Version Check (Postgres, new/version/no-op 3-way outcome) → **RabbitMQ publish** (new amber `real-event` stage) → **dashed async-boundary arrow** → "Async — consumed independently by scripts/consume_ingestion_events.py" band label → live-polled consume+embed/Qdrant-upsert stages (rendered as "Awaiting Consumer..." pending state if `ingestion_events.status` isn't yet `consumed` at render time, or the real completed stages if it is) → CloudWatch (placeholder) → Ingestion Complete
- [x] Wired into `nrg_app_render.py`'s Flow tab (already stubbed with a lazy, guarded import in Phase 5 specifically so this phase's wiring required zero changes to the tab-dispatch code, just the modules themselves now existing)
- [x] **Verified with real generated HTML, not just code review:** ran an actual `run_question()` call and rendered its `AskResult` through `render_flow_html()` — confirmed via direct string checks on real output that the Qdrant stage, the Bedrock-analog label, the unconditional `sampled_answers` audit stage, and AWS IAM placeholder all appear, and confirmed **no** "Human Review" text appears anywhere (the critical contrast with Novartis's diagram). Inspected the raw HTML directly and confirmed correct stage nesting, real fusion/rerank numbers in the score table, and correct HTML escaping.
- [x] **Verified the async-boundary polling live, not just structurally:** first attempted the test against `PLAN-VAR-TX.md`, which correctly short-circuited to the `no_op` path (identical content already active) since it had already been ingested in an earlier phase — proved the no-op early-return path renders correctly, but not the publish path. Created a genuinely new test document (`TEST-DIAGRAM-DOC`), ingested it with no consumer running → confirmed the diagram rendered the RabbitMQ publish stage, the dashed async-boundary arrow, the async band label, and the "Awaiting Consumer..." pending state, all correctly. Started the consumer, confirmed via direct Postgres query that `ingestion_events.status` flipped to `consumed`, then **re-rendered the identical diagram from the same step data** and confirmed it now shows the real embed/Qdrant-upsert/Ingestion-Complete stages instead of the pending state — proof the polling-based live-status design genuinely works, not simulated. Test document and its Postgres/Qdrant/disk traces cleaned up afterward.
- [x] **Verified inside the real running app, not just standalone function calls:** an `AppTest` run through the Ask tab followed by the Flow tab's body executing (Streamlit renders every tab's body every rerun) produced no exception, and the log's `st.components.v1.html` deprecation notice — which only fires when that function is actually called — confirmed the diagram genuinely rendered inside the live Flow tab, not just in isolation. Also reconfirmed the standalone `streamlit run nrg_app.py` server boots clean (HTTP 200, no errors in server log) with all of Phase 6's code now wired in.

## Phase 7 — Compliance Sampling Tab ✅ Complete

**Goal:** Human-in-the-loop as statistical sampling, not a gate — the documented contrast with Novartis.

- [x] `nrg_retrieval/postgres_client.py` — `list_recent_sampled_answers()`, `list_random_sampled_answers()` (genuine `ORDER BY random()`, distinct from newest-first, since statistical sampling per the deep-dive is meant to catch issues across the whole answer population, not just recent ones), `get_sampled_answer()`, `record_sample_review()` (annotates only the `reviewed*`/`review_verdict`/`review_notes` columns, never touches `question`/`answer`/`citations`/`confidence`)
- [x] Compliance Review tab in `nrg_app_render.py` — recent-vs-random sample mode toggle, adjustable sample size, per-row "Mark accurate"/"Mark inaccurate" + notes (buttons hidden once a row is already reviewed, showing the recorded verdict/reviewer/notes instead)
- [x] `scripts/review.py` — CLI with `list [--random] [--limit N]` and `mark <id> "<reviewer>" <accurate|inaccurate> "<notes>"`
- [x] **Verified end-to-end via both surfaces:** CLI `list` and `mark` commands tested directly against real `sampled_answers` rows (from earlier phases' Ask-tab testing) — confirmed the row's `reviewed`/`review_verdict` flip correctly and reappear correctly in a subsequent `list --random` call; UI tested via `AppTest` — filled the reviewer-name and notes fields, clicked "Mark accurate," confirmed via direct Postgres query that `reviewed_by`/`review_verdict`/`review_notes` persisted exactly as entered, then reran the app and confirmed the row now displays "already reviewed: **accurate** by Jane Compliance Reviewer" with the button form correctly hidden (no double-review possible) and the reviewed-count caption updated from 0 to 1
- [x] **Confirmed the core invariant directly:** compared `answer`/`citations`/`confidence` before and after both the CLI and UI review flows — byte-identical in both cases, proving review is purely annotative and never touches what the user already received, exactly the architectural contrast with copilot-demo's mandatory-approval `review_queue` this phase exists to demonstrate
- [x] Test annotations reset to a clean (`reviewed=false`) state on all 3 rows afterward

## Phase 8 — Audit Log ✅ Complete

**Goal:** Hash-chained, tamper-evident audit trail, same design as Novartis's.

- [x] `nrg_retrieval/audit.py` — hash-chained writer, ported near-verbatim from `mcp_servers/audit.py` (the SHA-256 chaining algorithm is domain-agnostic): `compute_record_hash()`, `append_audit_entry()`, `verify_chain()`
- [x] Wired into two event sources: `nrg_chains/ingest.py` writes `document_ingested` on every successful publish (actor = `uploaded_by`), on its own connection/transaction so an audit-write failure can't roll back an already-successful publish; `nrg_retrieval/postgres_client.py`'s `record_sample_review()` writes `answer_sampled_reviewed` after a successful annotation (actor = reviewer name) — no e-signature/approval event type exists here, unlike copilot-demo, since there's no approval gate to sign off on
- [x] Audit Log tab in `nrg_app_render.py` — "Verify chain integrity" button + a table of the 50 most recent entries (id/event/actor/timestamp/truncated hash)
- [x] `scripts/check_audit_chain.py --demo-tamper` — ported verbatim from copilot-demo's version (bypasses the insert-only trigger via `ALTER TABLE ... DISABLE TRIGGER` to simulate a privileged actor, tampers a row's payload, verifies TAMPERED is detected with the correct row identified, restores, verifies VALID again)
- [x] **Verified end-to-end with real data, both event types:** ingested a test document → confirmed a real `document_ingested` audit_log row was written with the correct actor; reviewed a sampled answer via the CLI → confirmed a real `answer_sampled_reviewed` row was written, correctly hash-chained to the prior row (`previous_hash` linkage confirmed); ran the full `--demo-tamper` cycle against these real entries → `[BEFORE] VALID` → `[AFTER TAMPER] TAMPERED -- audit_log id=1: record_hash mismatch (content tampered)` (correct row identified) → `[AFTER RESTORE] VALID`
- [x] **Verified inside the real running app via `AppTest`:** clicked the "Verify chain integrity" button and confirmed the UI rendered "Chain is VALID — no tampering detected."; confirmed the audit entries dataframe rendered both real rows correctly (id/event_type/actor/timestamp/truncated hash)
- [x] Test document's `kb_documents`/`ingestion_events`/disk-file traces cleaned up afterward; the 2 genuine `audit_log` entries deliberately left in place as real (uncorrupted) history rather than force-reset, since `audit_log` is insert-only by design and these rows correctly demonstrate both event types surviving a full tamper/restore cycle

## Phase 9 — Shell Integration ✅ Complete

**Goal:** Both demos reachable from one Streamlit app via a left-sidebar switch, with zero cross-repo coupling beyond the shell itself.

- [x] Extracted `copilot-demo/streamlit_app_render.py` from `copilot-demo/streamlit_app.py` — the one disclosed cross-repo touch. Verified as a genuinely pure code-movement extraction via an automated diff (not just eyeballed): programmatically diffed the extracted `render()` body against the original file's module-scope code (with indentation normalized) — the only differences across the entire ~420-line body were 2 collapsed blank lines, zero logic changes. `streamlit_app.py` is now a thin `set_page_config()` + `render()` wrapper.
- [x] `shell/shell_app.py` — `set_page_config()` + `st.sidebar.radio(...)`, with the render import happening inside the selected branch
- [x] `shell/novartis_wrapper.py`, `shell/nrg_wrapper.py` — each does its own `sys.path.insert` + `load_dotenv` into its demo's root
- [x] `shell/requirements.txt` — **changed from the original plan's minimal streamlit+python-dotenv-only design**: discovered during setup that the shell genuinely needs *both* demos' full dependency trees available in the same venv (whichever demo is selected first fully imports its own modules — `openai-agents`/`chromadb` for Novartis, `langchain`/`qdrant-client` for NRG — and switching to the other demo later in the same session needs its tree too). Merged both `requirements.txt` files into one; verified both full dependency trees import together with zero version conflicts in a fresh venv.
- [x] session_state isolation: NRG uses distinctly-prefixed keys (`nrg_run_history`, etc.) from the start
- [x] **Two real, non-obvious bugs found and fixed by actually switching between demos repeatedly, not just loading each once:**
  1. **Env var collision on first switch:** both demos' `.env` files use identical variable names (`POSTGRES_PORT`, `POSTGRES_USER`, `RABBITMQ_*`, etc. — neither demo has any reason to know the other exists) and `load_dotenv()` defaults to `override=False`. Switching from Novartis to NRG left NRG's Postgres connection silently pointed at Novartis's Postgres instance (port 5432 instead of 5433), surfacing as a confusing `UndefinedColumn: column "plan_type" does not exist` rather than an obvious connection error. Fixed by passing `override=True` to both wrappers' `load_dotenv()` calls.
  2. **`override=True` alone was insufficient — module-caching bug on the *second* switch back:** `override=True` only fixed the first Novartis→NRG transition. Switching back to Novartis afterward failed with `UndefinedTable: relation "review_queue" does not exist` — NRG's Postgres connection info was still active. Root cause: the `load_dotenv()` call lived at module scope in each wrapper, but Python caches imported modules in `sys.modules`, so a module-scope call only actually executes once per process (on the very first import) — later `from novartis_wrapper import render_novartis` calls are cache hits that never re-run `load_dotenv`. Fixed by restructuring both wrappers so `sys.path.insert` + the module import stay at module scope (safe to run once), while `load_dotenv(..., override=True)` moved inside `render_novartis()`/`render_nrg()` themselves, re-executed fresh on every single call.
- [x] **Verified end-to-end via `AppTest`, not just single-direction switching:** confirmed 5 consecutive transitions (Novartis default → NRG → Novartis → NRG → Novartis) all rendered the correct title with zero exceptions, proving the fix holds under repeated switching, not just once
- [x] **Verified session_state isolation directly, not just by naming convention on paper:** inspected the real `session_state` after visiting both demos in one session — confirmed 31 real keys existed (Novartis's 7 bare keys like `run_history`/`tracing_enabled`, NRG's ~23 `nrg_`-prefixed keys, plus the shell's own `shell_demo_selector`), and confirmed zero literal key-name collisions between the two sets
- [x] **Verified independence via grep, not just by convention:** `grep -rE "^\s*(import|from)\s+(copilot_agents|mcp_servers)"` over `nrg-demo/` and the equivalent for `nrg_chains|nrg_retrieval` over `copilot-demo/` both return zero real import statements (a looser grep without the `import|from` anchor does match several docstring/comment lines like "ported near-verbatim from copilot-demo's..." — confirmed these are all prose, not code, before treating the check as passed)
- [x] **Verified all three apps boot as real standalone servers, simultaneously:** `streamlit run copilot-demo/streamlit_app.py` (port 8501), `streamlit run nrg-demo/nrg_app.py` (port 8502), and `streamlit run shell/shell_app.py` (port 8503) all confirmed HTTP 200 with clean server logs, run concurrently with no port/process conflicts
- [x] copilot-demo's real agent pipeline (Supervisor → specialist handoff → MCP tool call → grounded answer → review queue publish) reconfirmed still fully functional post-extraction using a real, previously-verified-working question ("What is the current status and monitoring window for CAPA-3390?") — both via the CLI (`scripts/ask.py`) and through the extracted `streamlit_app.py` via `AppTest`, both producing the identical correct answer and correctly populating the Review Queue tab

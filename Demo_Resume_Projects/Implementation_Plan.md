# Local/Free Implementation Plan — Multi-Agent CMC Quality Copilot (Orchestration-First)

## Context

[Novartis_Architecture_Deep_Dive copy.md](Novartis_Architecture_Deep_Dive%20copy.md) describes a 12-layer Azure architecture for a multi-agent pharma quality copilot, built for an interview/architecture-review narrative. [Free_Alternative_Stack.md](Free_Alternative_Stack.md) mapped each Azure service to a free/local equivalent. The user doesn't have Azure services available and wants to actually **build and run** the architecture, not just diagram it — with priority on the part they care about most: **the agent orchestration flow** (Supervisor → 4 specialist agents → MCP governance layer). Cloud free-tier services (Supabase, LangSmith) are acceptable but **local/self-hosted is preferred wherever practical**.

This plan sequences implementation in phases so the orchestration core is real and testable early, then layers in retrieval, governance, human-in-the-loop, and observability around it — mirroring the original architecture's layers but reprioritized so the highest-value piece (agents talking to MCP servers, making real tool calls, producing grounded answers) comes first, not last.

**Confirmed scope decisions:**
- Synthetic pharma documents (SOPs, batch records, deviations) generated for this project — realistic enough for retrieval/citations to mean something
- All 4 MCP servers (Quality Docs, Batch Records, SOP Repository, CAPA/Enterprise) built from the start, matching the original diagram
- Human-in-the-loop: a real review queue table + approve action, with a mocked e-signature record (not full Part 11 fidelity)
- CLI/API only — no chat UI yet
- LLM: OpenAI `gpt-4o-mini` directly via existing API key
- Project lives in `copilot-demo/` inside this Project folder; no git repo for now

**Known risk:** the Project folder is inside Google Drive's synced directory. Docker bind-mounts, Python virtualenvs, and local DB/vector-store files (SQLite, Chroma) can conflict with Drive's sync daemon (file-lock contention, partial syncs, phantom conflict copies). Mitigation baked into Phase 0: use Docker **named volumes** (not bind-mounts) for any container-owned data, and a `.gitignore`-equivalent exclusion list for `.venv/`, `__pycache__/`, and any local Chroma/SQLite files so Drive doesn't try to sync fast-changing binary state mid-write. Verified working in practice during Phase 0 (venv install, pip, Docker all completed cleanly from the Drive-synced path).

---

## Architecture Mapping Recap (from [Free_Alternative_Stack.md](Free_Alternative_Stack.md))

| Original Layer | Local/Free Build Choice |
|---|---|
| Reasoning | OpenAI API, `gpt-4o-mini` |
| Agent Orchestration | OpenAI Agents SDK (Supervisor + 4 specialist agents) |
| MCP Governance | MCP Python SDK, 4 local servers |
| Retrieval | ChromaDB (embedded, local) |
| OCR/Doc processing | `unstructured` (or skipped — synthetic docs are already clean markdown) |
| Structured data (batch metadata, deviation status, review queue) | Postgres via Docker (local container, not Supabase — per "prioritize local") |
| Async workflow | RabbitMQ via Docker (local) |
| Human-in-the-loop | Review queue table in Postgres + CLI approve command + mock e-sign record |
| Identity/RBAC | Deferred — see Phase 5 |
| Secrets | `.env` file (local only, gitignored) |
| Observability/tracing | LangSmith free tier (hosted — only cloud dependency besides OpenAI itself) |
| Audit log | Postgres append-only table with hash chaining |

---

## Phase 0 — Project Scaffolding & Environment ✅ Complete

**Goal:** A working local dev environment before any agent code is written.

- [x] Created `copilot-demo/` with subfolders: `agents/`, `mcp_servers/`, `data/synthetic_docs/`, `db/`, `scripts/`
- [x] `docker-compose.yml` with **Postgres** and **RabbitMQ** (named volumes, not bind-mounts)
- [x] Python venv + `requirements.txt`: `openai-agents`, `mcp`, `chromadb`, `psycopg`, `aio-pika`, `python-dotenv`, `langsmith`, `pyyaml`
- [x] `.env.example` / `.env` documenting required vars: `OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `POSTGRES_*`, `RABBITMQ_*`
- [x] `.gitignore` exclusion list: `.venv/`, `chroma_db/`, `.env`, etc.
- [x] Verified: `docker compose up -d` → both containers healthy; all key packages import successfully; Python connects to both Postgres and RabbitMQ

## Phase 1 — Synthetic Data & Retrieval Layer ✅ Complete

**Goal:** Real (if synthetic) documents to ground agent answers, indexed and queryable.

- [x] Wrote 7 synthetic documents in `data/synthetic_docs/`: 4 SOPs (SOP-114 escalation criteria, SOP-220 investigation/RCA, SOP-301 CAPA effectiveness, SOP-089 batch disposition), 2 deviation reports (DEV-2201, DEV-2144 — deliberately cross-referenced so DEV-2201 is a recurrence of DEV-2144), 1 CAPA record (CAPA-3390), 1 batch record summary (BATCH-4471) — all with YAML frontmatter (`doc_id`, `doc_type`, `status`, `effective_date`, `version`) for metadata filtering
- [x] Postgres schema (`db/init/01_schema.sql`): `batches`, `deviations`, `capas` tables (relational/structured data), plus `review_queue` and `audit_log` tables built in early for Phase 4, seeded with data matching the synthetic docs
- [x] Verified: schema loads on container init, seed data queries correctly (DEV-2201 correctly linked to DEV-2144 via `related_deviation_id`)
- [x] `scripts/ingest.py` written and run — chunked 8 documents into 20 chunks, embedded via OpenAI `text-embedding-3-small`, loaded into a local persistent ChromaDB collection with metadata (`doc_id`, `doc_type`, `status`, `effective_date`, `version`)
- [x] Verified: retrieval query for "SOP-114 escalation criteria for critical deviation" (with `status=approved` metadata filter) correctly returns SOP-114 chunks ranked top-3, and the top chunk's content matches the actual escalation-criteria section

## Phase 2 — MCP Servers (4 servers) ✅ Complete

**Goal:** Narrow, purpose-scoped tool interfaces the agents will call — no agent gets raw DB/Chroma access.

- [x] `mcp_servers/common.py` — shared Chroma/Postgres access helpers (only the MCP servers touch data stores directly)
- [x] Built 4 MCP servers using FastMCP (MCP Python SDK's high-level decorator API), each exposing a small number of named tools:
  - **MCP Quality Documents** (`quality_docs_server.py`) — `search_quality_docs(query, doc_type)`
  - **MCP Batch Records** (`batch_records_server.py`) — `get_batch_metadata(batch_id)`, `search_batch_records(query)`
  - **MCP SOP Repository** (`sop_repository_server.py`) — `search_sops(query)`, `get_sop_by_id(sop_id)`
  - **MCP CAPA / Enterprise** (`capa_server.py`) — `get_capa_status(capa_id)`, `search_capa_records(query)`, `create_capa_draft(...)` (RabbitMQ "needs review" publish deferred to Phase 4)
- [x] Each server runs as its own local process over stdio transport
- [x] `scripts/test_mcp_server.py` — generic stdio MCP client test harness
- [x] Verified: all 4 servers tested standalone — tools list correctly, and tool calls correctly hit Chroma (semantic search, metadata-filtered) or Postgres (structured lookups incl. linked deviations), e.g. `get_batch_metadata("BATCH-4471")` correctly surfaces the linked open deviation DEV-2201

## Phase 3 — Agent Orchestration Core (the priority layer) ✅ Core Complete

**Goal:** Supervisor Agent routes to 4 specialist agents, each calling only its scoped MCP server(s), producing a grounded, cited answer — this is the heart of the demo.

- [x] `copilot_agents/` package (renamed from `agents/` to avoid shadowing the installed `agents` SDK package — a real footgun caught during build)
- [x] `copilot_agents/mcp_connections.py` — factory functions for each `MCPServerStdio` connection
- [x] `copilot_agents/specialists.py` — 4 specialist agents built with the OpenAI Agents SDK, each wired to only its scoped MCP server(s) per the original diagram's edges (Deviation Review → Quality Docs + Batch Records; Batch Record Analysis → Batch Records; SOP Interpretation → SOP Repository; CAPA Decision Support → CAPA + Quality Docs), each with citation-grounding instructions
- [x] `copilot_agents/supervisor.py` — Supervisor/Router Agent using the Agents SDK's native `handoffs=[...]` mechanism
- [x] `copilot_agents/tracing_setup.py` — LangSmith integration via `langsmith.wrappers.OpenAIAgentsTracingProcessor` registered through `agents.tracing.add_trace_processor` (SDK's built-in hook); gracefully disables if no real API key present
- [x] `scripts/ask.py` — CLI entry point; connects all MCP servers via `AsyncExitStack`, runs the Supervisor, prints final answer + agent path
- [x] **Verified end-to-end** with the original sequence diagram's exact question: `"Does deviation DEV-2201 meet SOP-114 escalation criteria?"` → Supervisor correctly routed to Deviation Review Agent → agent made 2 real MCP tool calls (SOP search + batch/deviation lookup) → produced a grounded, correctly-reasoned answer citing SOP-114 Section 3.1 and DEV-2201's actual facts (recurrence, critical process step)
- [x] Verified routing discrimination with a second question type ("CAPA-3390 status") → correctly routed to CAPA Decision Support Agent instead, answer matched Postgres data exactly
- [x] LangSmith tracing confirmed enabled (`[LangSmith tracing: enabled]` on every run) once the API key was added — traces of Supervisor → handoff → specialist → MCP tool calls now land in the LangSmith dashboard
- [x] **Reliability fix:** initial runs with `gpt-4o-mini` intermittently failed to resolve DEV-2201 correctly — the model sometimes called `get_batch_metadata(batch_id="DEV-2201")` (wrong ID type: that tool only accepts batch IDs, not deviation IDs) and gave up after one failed call instead of retrying with `search_quality_docs`. Root-caused via manual MCP tool testing (confirmed retrieval itself was correct) and LangSmith trace inspection. Fixed by tightening the Deviation Review Agent's instructions in `copilot_agents/specialists.py` to explicitly specify which tool/argument format to use for which ID type, and to retry with a different tool before concluding failure. Verified reliable across 3 repeat runs post-fix.

## Phase 4 — Async Handoff & Human-in-the-Loop ✅ Complete

**Goal:** Agent-drafted answers that need review get queued, and a reviewer can approve them, producing an audit record — matching the original's Service Bus → Review Queue → e-signature → Audit flow.

- [x] `copilot_agents/review_queue.py` — publishes a durable "needs review" message to RabbitMQ (`needs_review` queue) after the Deviation Review or CAPA Decision Support agent drafts an answer. Wired into `scripts/ask.py`, keyed off which agent actually produced the final message (matches the original diagram's DEVAGENT/CAPAAGENT → SERVICEBUS edges — SOP/Batch agents don't trigger review)
- [x] `scripts/consume_review_queue.py` — drains pending RabbitMQ messages into the Postgres `review_queue` table
- [x] `mcp_servers/audit.py` — hash-chained audit log writer: each row's `record_hash` covers its own content + the previous row's hash (SHA-256 over canonical JSON), so altering any past row breaks every hash after it. `verify_chain()` walks the full log and recomputes/validates
- [x] `scripts/review.py` — CLI with `list` / `approve <id> <reviewer>` / `reject <id> <reviewer> <reason>`. Approve writes a mock e-signature record (reviewer name, timestamp, attestation text — not real Part 11 crypto/compliance) into the audit log; reject writes a rejection reason entry
- [x] `scripts/check_audit_chain.py` — verifies chain integrity, with a `--demo-tamper` mode that bypasses the DB's insert-only trigger (`ALTER TABLE ... DISABLE TRIGGER`, simulating a privileged actor) to prove the **hash chain** catches tampering even when DB-level protection is circumvented — then restores the original content
- [x] **Verified end-to-end twice**: (1) deviation question → published to RabbitMQ → drained to `review_queue` → approved via CLI → audit log entry recorded and chain valid; (2) CAPA question → same flow → **rejected** via CLI with a reason → audit log entry recorded, chain still valid
- [x] **Verified tamper detection**: chain reported `VALID` → simulated privileged tampering with a past row's payload → chain correctly reported `TAMPERED` with the exact broken row identified → restored → chain reported `VALID` again
- [x] Also confirmed the DB trigger itself blocks normal UPDATE/DELETE outright (`audit_log is insert-only` exception) — the hash chain is the second layer of defense for the case where DB-level protection is bypassed

## Phase 5 — Streamlit UI ✅ Complete

**Goal:** A UI layer reusing the exact same orchestration/review logic already built — no duplicated business logic, presentation only. Closest free/local analog to the original architecture's "Copilot Web UI" layer (chat + citation panel + review queue).

- [x] **Refactored for reuse before building the UI:** extracted `copilot_agents/ask_flow.py` (`run_question()` — connects MCP servers, runs the Supervisor, publishes to review queue if needed) out of `scripts/ask.py`, and `mcp_servers/review_actions.py` (`list_pending`, `list_history`, `approve`, `reject`) out of `scripts/review.py`. Both CLI scripts now call these shared modules — confirmed still working identically after the refactor (re-ran `scripts/ask.py` and `scripts/review.py list`)
- [x] `streamlit_app.py` — three tabs:
  - **Ask** — question input (with example-question dropdown), runs `ask_flow.run_question()`, shows the grounded answer, an expandable agent-path trace, and a notice when the answer was routed to the review queue
  - **Review Queue** — lists pending items with approve/reject actions (reviewer name + rejection reason inputs) calling `review_actions.approve()`/`reject()` directly, plus a recent-history table
  - **Audit Log** — a "Verify chain integrity" button calling `mcp_servers.audit.verify_chain()`, plus a table of recent audit entries
- [x] Verified server starts cleanly (`streamlit run streamlit_app.py`, HTTP 200, `/_stcore/health` → `ok`, no errors in server log)
- [x] Verified the one genuinely risky integration point — calling `asyncio.run()` on the agent orchestration flow from inside Streamlit's per-session execution thread (not the main thread) — works correctly end-to-end (tested by simulating the exact threading pattern directly: MCP tool calls + LLM inference completed successfully from a worker thread)
- [x] Verified all underlying data calls the UI depends on (`list_pending`, `list_history`, `verify_chain`) return correct data matching Phase 4's test runs

**Deferred (not built):** FastAPI wrapper (Streamlit already provides the HTTP-accessible UI layer) and RBAC/Keycloak-style role enforcement — remain optional if wanted later, not required for the core demo.

## Phase 6 — Visual Pipeline Flow Tab ✅ Complete

**Goal:** Show the full flow of every query visually — every handoff, every MCP tool call with real arguments/output, and the human review accept/deny decision — "as visually pleasing as possible with no technical pipeline missing." Requested after using the Phase 5 UI and wanting to see what LangSmith tracks, but rendered natively in-app rather than pulled from LangSmith's API.

- [x] **Investigation finding:** the OpenAI Agents SDK's `Runner.run()` result (`result.new_items`) already carries full trace detail — tool names, parsed arguments, outputs (matched via `call_id`), and handoff targets — with no LangSmith API call needed. LangSmith keeps recording the same run in parallel as the external/durable store; the on-screen diagram is built directly from SDK trace data for instant rendering with full styling control.
- [x] `copilot_agents/ask_flow.py` — reworked to capture full detail: new `TraceStep` dataclass (`step_type`, `agent_name`, `tool_name`, `mcp_server`, `arguments`, `output`, `target_agent`, `message_text`); `AskResult.trace_steps` replaces the old flattened `(agent_name, item_type)` tuple list. `TOOL_TO_MCP_SERVER` maps each tool name to its owning MCP server for diagram labeling.
- [x] `copilot_agents/flow_diagram.py` (new) — pure function `render_flow_html()` builds a self-contained HTML/CSS pipeline diagram (top-to-bottom boxes + arrows, no external assets/CDN): real stages (solid, colored, populated with actual trace data — user question, Supervisor routing decision with non-selected specialists shown greyed for contrast, each MCP tool call with real args/output, LLM reasoning step, final answer) plus placeholder stages for original-architecture layers not implemented locally (Entra ID, RBAC, API Gateway, Key Vault, Managed Identity, Azure Monitor, AI Foundry, AKS, ACR, GitHub Actions) rendered dashed/grey with a "NOT IMPLEMENTED LOCALLY" tag, clearly distinct from real stages tagged "REAL" — and a review accept/deny decision box (pending/approved/rejected, color-coded amber/green/red) when the run triggered human review.
- [x] **Bug caught and fixed during build:** initial placeholder labels double-escaped HTML entities (`&amp;` in Python source + `html.escape()` in `_esc()` → `&amp;amp;` in output). Fixed by using literal `&` in source and letting `_esc()` do the only escaping pass. Verified fixed by checking rendered output for `&amp;amp;`.
- [x] `streamlit_app.py` — added a 4th **Flow** tab: sidebar list of past questions (newest-first, from new `st.session_state.run_history`, populated every time "Ask" succeeds), clicking one renders that run's diagram via `st.components.v1.html()`. Review status for the decision box is cross-referenced by exact question-text match against `review_actions.list_pending()`/`list_history()` (no direct FK from trace to `review_queue` row — a known limitation: duplicate question text across multiple runs can't be disambiguated, verified and documented, acceptable for a demo)
- [x] Updated `scripts/ask.py`'s CLI output to match the new `trace_steps` structure (was still using the old `agent_path` attribute name, which no longer exists post-refactor)
- [x] **Verified end-to-end:** server starts cleanly on 3 separate launches (HTTP 200, `/_stcore/health` → `ok`, no errors); trace extraction confirmed accurate against real runs (tool names, parsed arguments, and outputs all match what was actually retrieved); diagram renders correctly with real data populated in real-stage boxes and static labels in placeholder boxes; full review lifecycle tested (pending → approved via CLI → re-lookup correctly shows "approved" with reviewer name in the diagram's decision box)

## Phase 7 — HTML Document Support & Incremental Ingestion ✅ Complete

**Goal:** Support adding new knowledge-base documents as styled `.html` files (not just `.md`), and make re-ingestion incremental — only new/changed files get re-embedded, instead of a full wipe-and-rebuild every run. Triggered by the user adding `DEV-2024-0417-A.html` (and two `SPECIMEN_*.html` reference docs) to `data/synthetic_docs/`, which the old `.md`-only ingestion script silently skipped.

- [x] **Root cause:** `scripts/ingest.py` only globbed `*.md` and required YAML frontmatter — `.html` files were never eligible for ingestion, regardless of staleness. Not a versioning bug, a missing format.
- [x] Added `<meta name="doc-id/doc-type/doc-title/doc-status/doc-effective-date/doc-version" content="...">` tags to each HTML file's `<head>` — the HTML equivalent of the `.md` files' YAML frontmatter block.
- [x] **Collision caught before ingesting:** `SPECIMEN_Synthetic_SOP.html`'s visible doc-id field said "SOP-114, Rev. 4" — colliding with the real, already-ingested `SOP-114_Deviation_Escalation_Criteria.md` (same doc_id, different content/date). Flagged to the user; re-IDed as `SOP-114-SPECIMEN` in its meta tag to avoid silently overwriting or duplicating the canonical SOP-114 in Chroma. Confirmed post-ingestion: `SOP-114` and `SOP-114-SPECIMEN` are distinct entries, and SOP Repository searches still correctly rank the real SOP-114 for its canonical content.
- [x] `scripts/ingest.py` rewritten:
  - `parse_html()` — new `_HTMLTextExtractor(HTMLParser)` strips `<script>`/`<style>` and all tags, keeps readable body text plus the `doc-*` meta values; falls back to `<title>` if no `doc-title` meta present
  - `load_document()` — dispatches to markdown or HTML parsing by file extension, validates required metadata fields present either way
  - **Incremental ingestion:** new manifest file `chroma_db/.ingest_manifest.json` maps each source file path → SHA-256 content hash. Each run only re-chunks/re-embeds/re-writes-to-Chroma files whose hash changed since the last run (deletes and replaces that doc_id's old chunks first, so a changed chunk count doesn't leave orphaned chunks behind). `--full` flag forces a full rebuild, ignoring the manifest.
- [x] **Verified end-to-end:**
  - First run (no manifest): all 8 existing `.md` + 3 new `.html` docs ingested (11 docs, 45 chunks total)
  - Second run, no changes: correctly reported "0 changed, 11 up to date, nothing to do"
  - Edited one `.md` file: correctly re-ingested only that 1 file, left the other 10 untouched
  - Added `doc-title` meta tags to the 3 HTML files, re-ran: correctly re-ingested only those 3 (title metadata confirmed clean afterward, e.g. `"Deviation Investigation Report DEV-2024-0417-A"` instead of falling back to the generic `<title>` tag)
  - Confirmed `DEV-2024-0417-A` (the originally-missing doc) is now retrievable via the MCP Quality Documents server with clean extracted text (all CSS/markup stripped) and correct metadata
  - Full corpus check: 11 unique `doc_id`s, no duplicates, `SOP-114` vs `SOP-114-SPECIMEN` correctly distinct

**Note on "versioning policy":** there still isn't automatic file-watching — ingestion remains a manually-triggered command (`python scripts/ingest.py`), per the user's confirmed preference (smarter/incremental over automatic/watched). Editing or adding a doc requires running that command before it's searchable.

## Phase 8 — Knowledge Base GUI: Search, Upload/Delete, Viewer, Real Versioning, Live Ingestion Tab ✅ Complete

**Goal:** A proper KB management surface in the Streamlit app — search, upload, delete, view documents in clean HTML — with system-enforced versioning (not the manual eyeball-catch that found the `SOP-114`/`SOP-114-SPECIMEN` collision in Phase 7), plus a live view of the ingestion pipeline itself in the Flow tab.

**Confirmed scope decisions:** uploads write into the existing `data/synthetic_docs/` folder (one source of truth); same `doc_id` re-upload creates a new version and marks the prior one `superseded` (never silently overwritten); live ingestion view covers GUI uploads only, not external CLI runs; both `.md` and `.html` render as clean HTML in the viewer; version history tracked in a new Postgres table (Chroma stays the search index); delete is soft (excluded from search, file + history retained) — consistent with the project's existing insert-only/superseded-not-deleted patterns (audit log, and now KB versions).

- [x] `db/init/02_kb_documents.sql` (new) — `kb_documents` table: `doc_id`, `version`, `title`, `doc_type`, `file_path`, `file_format`, `content_hash`, `status` (`active`/`superseded`/`deleted`), `uploaded_by`, `uploaded_at`, `UNIQUE(doc_id, version)`. **Strengthened beyond the plan:** added a partial unique index (`UNIQUE (doc_id) WHERE status = 'active'`) so "at most one active version per doc_id" is a hard DB invariant, not just application logic — same philosophy as the audit log's insert-only trigger. Applied to the already-running Postgres container (schema files only auto-run on fresh volume creation) via `psql` piped against the live container; confirmed via `\d kb_documents`.
- [x] `copilot_agents/kb_ingest.py` (new) — parsing functions (`parse_markdown`, `parse_html`, `_HTMLTextExtractor`, `load_document`, `chunk_text`, `file_hash`) moved here from `scripts/ingest.py` so both the CLI bulk-ingest and the GUI's single-file upload share one implementation. New `ingest_document()` generator yields `IngestStep`s (`parsing` → `chunking` → `versioning` → `embedding` → `storing` → `done`) for live progress, and does the actual version/conflict resolution: identical content re-upload is a no-op, different content increments the version and marks the prior row `superseded`, brand-new `doc_id` becomes version 1.
- [x] `scripts/ingest.py` updated to import parsing/Chroma helpers from `kb_ingest.py` instead of defining them locally — bulk-ingest/manifest behavior for the CLI path unchanged. Verified identical post-refactor behavior (`11 already up to date` on a no-change run).
- [x] `mcp_servers/kb_actions.py` (new) — `search_kb()` (wraps `mcp_servers.common.search_documents`, enriches with uploader/version metadata), `list_all_documents()`, `get_document_versions()`, `get_document_content()` (`.md`→HTML via the new `markdown` dependency, `.html` passed through), `soft_delete_document()`, `ingest_document_and_collect()` (drains the generator for callers that don't need live per-step UI).
- [x] **Real bug caught and fixed during build:** the first version of `ingest_document()` wrote every version of a `doc_id` to the *same* filename on disk (`data/synthetic_docs/{filename}`), so requesting "view version 1" after a v2 upload silently showed v2's content — the version-history feature would have been actively misleading. Caught by testing the version-history viewer against two different contents before wiring it into the UI, not after. Fixed by giving each version its own immutable file (`{doc_id}-v{version}{suffix}`); verified the fix with a targeted before/after test (confirmed v1 showed "Original" not "Revised", v2 showed "Revised", file paths differed) before proceeding.
- [x] `copilot_agents/diagram_common.py` (new) — extracted the shared CSS and `stage()`/`arrow()`/`placeholder()`/`esc()` helpers out of `flow_diagram.py` into a common module both the query-flow diagram and the new ingestion-flow diagram import, so a fix to one (e.g. the Phase 6 double-escaping bug) can't silently drift out of sync with the other. `flow_diagram.py` refactored to use it; confirmed no regression (re-ran the render smoke test, no double-escaping).
- [x] `copilot_agents/ingest_flow_diagram.py` (new) — `render_ingest_flow_html()`, same visual language as the query-flow diagram (solid/colored "REAL" stages, dashed/grey "NOT IMPLEMENTED LOCALLY" placeholders for Entra ID/RBAC/Azure Monitor/AI Foundry): File Upload → Parse Document → Chunk Text → Version Check (color-coded new/new-version/no-op outcome) → Generate Embeddings → Store in ChromaDB → Ingestion Complete, each populated with real data from the actual `IngestStep` sequence. Handles early-exit rendering for the no-op and error paths distinctly.
- [x] `streamlit_app.py` — new **Knowledge Base** tab (5th tab) with Search / Upload / Browse-Manage sub-tabs, plus a shared document viewer (version dropdown, soft-delete action) opened from either Search results or the Browse table. Upload drives `ingest_document()`'s generator through a live `st.status()` block. Flow tab extended with a second sidebar section ("Ingestion runs") alongside the existing "Query runs," backed by new `ingest_history`/`selected_flow_kind`/`selected_ingest_index` session state, so both event types are viewable from the same tab without conflating them.
- [x] **Verified end-to-end** (full suite matching the plan's 8 verification steps, run as one script against the live Postgres/Chroma containers):
  - New document upload → appears in browse table as v1/active, retrievable via the exact same `mcp_servers.common.search_documents()` agents use, ingestion diagram renders with real data
  - Re-upload with different content under the same `doc_id` → v1 correctly flips to `superseded`, v2 becomes `active`; search returns only the new content; **version-history viewer correctly shows v1's original content and v2's revised content as genuinely different** (confirms the file-path bug fix holds)
  - Re-upload byte-identical content → correctly detected as a no-op, no duplicate version row created
  - `kb_actions.search_kb()` results match raw `mcp_servers.common.search_documents()` results exactly (same underlying call)
  - `.md` document renders as clean HTML in the viewer (frontmatter stripped, `<h1>` etc. present)
  - Soft delete → excluded from search and the browse table, file remains on disk, both version rows remain queryable in Postgres (`superseded`, `deleted`) for audit purposes
  - Regression check: `scripts/ingest.py` (CLI bulk path) and `scripts/ask.py` (full agent orchestration) both still run correctly, unaffected by the refactor
  - Full app launched 3 times across this session (varying ports) — clean startup, HTTP 200, `/_stcore/health` → `ok`, no import/runtime errors each time
- [x] **Real transient failure encountered and handled correctly, not papered over:** one verification run hit an `OpenAI APITimeoutError` mid-pipeline (network blip during the embedding call, after the Postgres version row had already committed) — left a genuine partial-failure state (Postgres row + file on disk, but no Chroma embedding yet). Diagnosed as a one-off connectivity issue (confirmed via a direct API reachability check), not a code bug; deliberately did **not** add speculative retry/transaction-spanning logic for a failure mode that self-resolved, since over-engineering error handling for a local demo's one-off network blip isn't the goal — cleaned up the partial state and re-verified successfully.

## Phase 9 — Production-Grade Retrieval, Typed/Cached Boundaries, Critic Review & Retry ✅ Complete

**Goal:** Harden the system to match how a regulated pharmaceutical company would actually build it: explainable/auditable hybrid retrieval (BM25 + reranking, not pure vector search), validated + cached data flowing through typed boundaries (Pydantic replacing plain dicts), and a self-checking critic review loop before an answer is considered done — sitting in front of the existing human-review queue, not replacing it.

**Survey before building:** confirmed via full-codebase investigation that retrieval was pure ChromaDB dense vector search (no BM25, no reranking), every MCP tool returned untyped `dict`/`list[dict]`, no `output_type` was set on any of the 5 agents, `Runner.run()` was called exactly once with no retry/guardrails, and there was no caching anywhere — a clean greenfield baseline. Also confirmed `openai-agents==0.19.2` already ships ready-to-use `InputGuardrail`/`OutputGuardrail` primitives, unused until this phase.

- [x] `requirements.txt` — added `rank-bm25`, `sentence-transformers`, `diskcache`; promoted `pydantic`/`tenacity` from transitive to explicit dependencies.
- [x] `mcp_servers/hybrid_search.py` (new) — 3-stage pipeline: BM25 keyword search (`rank_bm25.BM25Okapi`, in-memory index built from the full Chroma corpus) + dense vector search run in parallel, fused via Reciprocal Rank Fusion (chosen over a weighted blend specifically because RRF's ranking is easy to explain to an auditor), then reranked with a local cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`, CPU-only, no GPU/API dependency). Every result carries `bm25_score`, `vector_score`, `fusion_rank`, and `rerank_score` as separate fields — never collapsed into one number — so the retrieval justification stays auditable. `mcp_servers/common.py::search_documents()` now delegates here; call signature unchanged so none of the 4 MCP servers' call sites needed touching for retrieval logic itself.
- [x] `copilot_agents/cache.py` (new) — `diskcache`-backed, two namespaces: an embedding cache (keyed on `hash(text, model)`, no expiry — embeddings are deterministic) wrapping the OpenAI embedding function via a `CachedEmbeddingFunction` proxy, and a retrieval-result cache (keyed on `hash(query, doc_type, n_results)`, 5-minute TTL). Deliberately does **not** cache LLM final answers, per confirmed scope — a cached compliance answer going stale against updated source documents was called out as a real regulatory risk, not just a technical one.
- [x] **Real bug caught and fixed during build:** the first version of `CachedEmbeddingFunction` only implemented `__call__`, but Chroma's `EmbeddingFunction` protocol requires `.name()`/`.get_config()`/`.is_legacy()` etc. for its persisted-config validation — caused an `AttributeError` the moment a collection was reopened. Fixed with `__getattr__` transparently proxying everything except `__call__` to the wrapped real embedding function, confirmed via a full round-trip test (first call embeds + caches, second identical call returns in 0.00s).
- [x] `copilot_agents/schemas.py` (new) — Pydantic models for every MCP tool's return shape (`SearchResult`, `BatchMetadata`, `DeviationRef`, `CapaStatus`, `CapaDraft`, `SopDocument`, `ToolError` for the not-found branch) and the agent-output boundary (`GroundedAnswer`: answer, citations, confidence, requires_human_review; `CriticResult`: passed, feedback, layer). All 4 MCP servers (`quality_docs_server.py`, `sop_repository_server.py`, `batch_records_server.py`, `capa_server.py`) updated to return these instead of plain dicts — verified over the real stdio transport via `scripts/test_mcp_server.py` that FastMCP correctly serializes Pydantic models (including union return types like `BatchMetadata | ToolError`) to JSON with no changes needed to the test harness itself.
- [x] `copilot_agents/critic.py` (new) — layered critic: deterministic checks first (answer non-empty; every citation must match an identifier the agent actually saw this run — the single highest-value check for a grounded-answer system, catches hallucinated citations for free with no LLM call), then an LLM critic agent judging whether the draft's claims are actually supported by the retrieved source text. Implemented as a **genuine SDK `output_guardrail`** (not a bolted-on manual check) per explicit direction, which required real architecture work to satisfy correctly:
  - Investigated and confirmed `output_guardrail` functions only receive `(context, agent, agent_output)` — no direct handle on the run's tool-call history — and that `OutputGuardrailTripwireTriggered`'s carried `OutputGuardrailResult` doesn't include `new_items` either.
  - Confirmed empirically (not just from source reading) that MCP tools are internally converted to SDK `FunctionTool`s, so they flow through `RunHooks.on_tool_end` like any native tool — this became the channel: a `RunContext` dataclass threaded via `Runner.run(context=...)`, populated by a `RecordingHooks(RunHooks)` subclass that parses each tool's raw JSON result and records both full `SearchResult` objects and every ID-shaped field (including nested ones, e.g. `BatchMetadata.deviations[].deviation_id`) into a `seen_record_ids` set — giving the guardrail everything it needs by the time it fires, with zero plumbing inside the MCP servers themselves.
  - Confirmed empirically that the guardrail fires correctly on the **handed-off-to specialist** (not the Supervisor), matching how `agent.output_guardrails` is read for whichever agent actually produces the run's final output.
- [x] **Two real false-positives caught and fixed via live testing, not just unit tests:**
  1. The deterministic check initially validated citations only against `SearchResult.doc_id`s, so a citation to a `deviation_id` learned from `get_batch_metadata` (a structured lookup, not a search hit) was flagged as fabricated when it wasn't. Fixed by broadening `RecordingHooks` to recursively collect every ID-shaped field from *any* tool result, not just search results.
  2. The LLM critic's source-text context was built only from `SearchResult` excerpts, so it had no visibility into structured-lookup facts (disposition status, CAPA monitoring window, etc.) and would fail correctly-grounded answers for exactly the questions those tools exist to answer. Fixed by also capturing full structured-lookup JSON payloads (`structured_lookups`) and including them in the critic's source text. Re-verified the same test case passed cleanly after both fixes.
- [x] `copilot_agents/specialists.py` — all 4 agents gained `output_type=GroundedAnswer` and `output_guardrails=[llm_critic_guardrail]`; citation instructions tightened to require exact `doc_id`/`batch_id`/etc. values from tool calls.
- [x] `copilot_agents/ask_flow.py::run_question()` — wrapped in a bounded retry loop (`MAX_ATTEMPTS = 3`): catches `OutputGuardrailTripwireTriggered`, appends the critic's feedback to the next attempt's input, retries. New `critic_check` `TraceStep` type records pass/fail/layer/feedback per attempt so a failed-then-retried-then-passed run is fully visible, not hidden. If every attempt is exhausted, the last draft is still returned (never silently dropped) with `requires_human_review` forced `True` — the existing human review queue remains the final backstop.
  - **Second real bug caught via adversarial testing:** a deliberately tricky question (asking the agent to cite a nonexistent document) caused the SDK's own internal turn cap to trip (`MaxTurnsExceeded`) *before* any guardrail even ran — an exception type the retry loop didn't originally catch, which crashed `run_question()` entirely instead of returning any answer. Fixed by adding a catch for `MaxTurnsExceeded`/`ModelBehaviorError` that records a failed `critic_check` and returns a safe `requires_human_review=True` fallback instead of propagating the crash.
  - **Third real gap caught:** the guardrail-trip exception path had no way to rebuild an accurate tool-call trace (see above — the SDK doesn't expose `new_items` there), so the original code silently produced an empty trace for failed attempts. Fixed with `_build_trace_steps_from_context()`, reconstructing an approximate (if less precise) trace from what `RecordingHooks` already captured, so failed attempts still show real data in the Flow tab instead of nothing.
- [x] `copilot_agents/diagram_common.py` / `copilot_agents/flow_diagram.py` — extended with a per-document score-breakdown table (BM25/vector/fusion-rank/rerank columns) on search tool-call stages, a cache hit/miss badge (sourced from a new `SearchResult.cache_hit` field — the only viable channel given MCP servers run as isolated per-question subprocesses, confirmed via the same `RunHooks` investigation above), and a pass/fail critic-review stage. The diagram now renders **per attempt** (grouped under an "Attempt N of M" label when a run took more than one try) instead of a single flat sequence, so multi-attempt runs are fully visible.
- [x] **Verified end-to-end:** hybrid search tested with both a keyword-heavy query (BM25 dominant) and a paraphrased query (vector-driven, reranker correctly reordering results) against the real corpus, confirming all 4 score fields populate and the reranker demonstrably changes the final order; caching verified with a real hit/miss round trip and cross-process persistence check (`diskcache` genuinely shared across separate Python processes, unlike the intentionally per-process BM25 index); all 4 MCP servers re-verified over real stdio transport with the new Pydantic types, including the `BatchMetadata | ToolError` union path; a full multi-attempt retry cycle was observed live (not simulated) on a genuinely hard question, producing 3 real attempts with real tool calls and critic feedback at each step; full regression pass confirmed `scripts/ask.py`, `scripts/ingest.py`, all 4 MCP servers, and the full Streamlit app (3 separate launches) all still work correctly, unaffected.

---

## Verification Summary

Each phase has its own local verification step (listed above); the overall end-to-end test after Phase 4 is:

1. `docker compose up -d` (Postgres, RabbitMQ)
2. Run ingestion script once (Phase 1) to populate Chroma + Postgres with synthetic docs
3. Start the 4 MCP servers
4. Run `scripts/ask.py "Does deviation DEV-2201 meet SOP-114 escalation criteria?"` — confirm Supervisor routes correctly, grounded cited answer is produced, and the item appears in the review queue
5. Run `scripts/review.py`, approve the item, confirm audit log entry and hash-chain integrity
6. Check LangSmith dashboard for the full trace of the run (Supervisor → specialist → MCP tool calls → LLM generation)

This reproduces the original architecture's full request lifecycle (Section 1's sequence diagram in the Deep Dive doc) end-to-end on local/free infrastructure, with the agent orchestration layer (Phase 3) as the earliest fully-working, most heavily verified piece.

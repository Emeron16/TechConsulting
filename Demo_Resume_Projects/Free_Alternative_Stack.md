# Free / Open-Source Alternative Stack for the Multi-Agent CMC Quality Copilot Architecture

**Purpose:** A layer-by-layer substitution for [Novartis_Architecture_Deep_Dive copy.md](Novartis_Architecture_Deep_Dive%20copy.md) that preserves the same architectural *shape* (agent orchestration → MCP governance → retrieval → human-in-the-loop → audit) using entirely free or free-tier tools, so the full pattern can be demoed locally or on a laptop without an Azure subscription.

---

## Layer-by-Layer Substitution

| Layer | Azure Original | Free Alternative | Notes |
|---|---|---|---|
| **Reasoning (LLM)** | Azure OpenAI GPT-4o | **OpenAI API directly, `gpt-4o-mini`** (using your existing key) | No Azure wrapper needed — same OpenAI SDK, just point at `api.openai.com` instead of an Azure endpoint. Cheapest capable OpenAI model, good fit for a demo budget |
| **Agent Orchestration** | OpenAI Agents SDK | **OpenAI Agents SDK itself** (it's free/open-source — works with any OpenAI-compatible endpoint) | Since you're using a real OpenAI key, this layer needs **zero substitution** — it's identical to the original architecture |
| **MCP Servers** | Custom MCP servers on AKS | **MCP Python SDK** (free, open-source) running as local processes or Docker containers | MCP protocol itself is free/open — no Azure dependency at all |
| **Vector/Hybrid Search** | Azure AI Search | **Qdrant** (free, self-hosted, generous free cloud tier) or **ChromaDB** (fully local, embedded) | Chroma is easiest for a laptop demo; Qdrant is closer to "production-grade" if you want to show scaling story. Embeddings via `text-embedding-3-small` (OpenAI, cheap) |
| **OCR / Document Intelligence** | Azure AI Document Intelligence | **Tesseract OCR** (free/open-source) or **unstructured.io** (open-source library, table/layout aware) | Unstructured is the closer analog — handles layout/table extraction like Doc Intelligence |
| **Blob Storage** | Azure Blob Storage | **MinIO** (free, self-hosted, S3-compatible) or local filesystem, or **Supabase Storage** (bundled free with the Supabase project below) | MinIO is a drop-in for demoing "object storage" without cloud cost; Supabase Storage keeps everything in one hosted project if you'd rather not self-host |
| **Relational DB** | Azure SQL Database | **Supabase (hosted Postgres, free tier)** | Free tier includes a full Postgres instance, auto-generated REST/GraphQL API, row-level security, and a dashboard — closer to a managed cloud DB experience than self-hosted Postgres, and no Docker/infra to maintain. Note: free projects pause after 7 days of inactivity and need a manual restore |
| **Async Messaging** | Azure Service Bus | **RabbitMQ** (free, self-hosted) or **Redis Streams** (free), or **Supabase Realtime** (Postgres-native pub/sub, bundled free) | RabbitMQ maps well to Service Bus's queue/dead-letter semantics; Supabase Realtime is simpler if you want to avoid standing up a separate broker, at the cost of weaker delivery guarantees |
| **Identity/SSO** | Microsoft Entra ID | **Keycloak** (free, open-source, full OIDC/SAML SSO + RBAC), or **Supabase Auth** (bundled free, built-in RBAC via row-level security) | Keycloak is the closer enterprise-SSO analog; Supabase Auth is less setup if you're already using Supabase for the DB |
| **Secrets Management** | Azure Key Vault | **HashiCorp Vault** (free OSS edition) or `.env` + Docker secrets for a demo | Vault OSS is the real analog if you want to show the pattern |
| **Container Orchestration** | AKS | **Docker Compose** (single-machine) or **k3s/kind** (free, lightweight local Kubernetes) | k3s/kind lets you say "yes, this runs on real Kubernetes," just not managed/cloud |
| **Container Registry** | ACR | **Docker Hub free tier** or local registry via `registry:2` image | |
| **CI/CD** | GitHub Actions | **GitHub Actions** (already free for public repos, generous free minutes for private) | No substitution needed |
| **Observability** | Azure Monitor + App Insights | **LangSmith (free tier)** for LLM/agent-level tracing, plus **Grafana + Prometheus + Loki** for infra-level metrics/logs if you want that layer too | LangSmith is purpose-built for exactly this — per-run traces of every agent step, tool call, and token cost, which is arguably a better interview story than generic APM for an *agent* system specifically |
| **Prompt/Agent Governance** | Azure AI Foundry | **LangSmith (free tier)** — covers prompt versioning, dataset-based evals, and run comparison, so it does double duty with the observability row above | Since LangSmith already covers tracing, it's reasonable to use it for both rows and skip Langfuse entirely |
| **Audit Log / Immutability** | Immutable Audit Log Store | **Supabase Postgres, append-only table + hash chaining** (e.g., a `previous_hash`/`record_hash` column pair, enforced via a trigger that rejects UPDATE/DELETE) | Supabase's row-level security can enforce "insert-only" at the database level, which is a clean way to demonstrate tamper-evidence without a separate immutability product |
| **E-Signature (21 CFR Part 11)** | Custom + Part 11 validation | Mocked/simulated for demo purposes — no free tool truly satisfies Part 11 | Worth being explicit that this piece is compliance-gated and can only be *simulated*, not genuinely certified, without enterprise tooling |

---

## The Practical Path

With an OpenAI key and Supabase in the mix, the stack splits cleanly into **hosted free-tier services** (no local infra to run) and a **thin local/Docker layer** for the pieces that don't have a good hosted-free option:

**Hosted (free tier, no Docker needed):**
- **LLM + embeddings:** OpenAI API (`gpt-4o-mini`, `text-embedding-3-small`)
- **Database + Storage + Auth + Realtime:** Supabase (one project covers all four)
- **Observability + prompt/agent governance:** LangSmith

**Local / Docker Compose (no free hosted equivalent, or better demoed self-hosted):**
- **Orchestration:** OpenAI Agents SDK (runs as your application code, not a service)
- **Tool governance:** MCP servers as local Python processes
- **Retrieval:** ChromaDB (or Qdrant if you want a separate service)
- **Identity/SSO:** Keycloak — *only if* you want to demo enterprise SSO/RBAC distinct from Supabase Auth's row-level security model
- **Secrets:** `.env` locally, or HashiCorp Vault if you want to show the pattern explicitly

This reproduces every architectural layer and every design *decision* in the original document (why MCP, why async, why RBAC, why human-in-the-loop) — just on free infrastructure instead of Azure, with less to self-host than the original all-open-source version since Supabase and LangSmith absorb several rows at once.

---

## Open Question

Which pieces are most important to actually demo end-to-end versus which are fine to just diagram/describe in an interview setting? Worth deciding before scaffolding the project, since that determines how much of the Docker Compose stack is worth building out fully.

# Free / Open-Source Alternative Stack for the NRG Energy Knowledge Copilot Architecture

**Purpose:** A layer-by-layer substitution for [NRG_Energy_Architecture_Deep_Dive.md](NRG_Energy_Architecture_Deep_Dive.md) that preserves the same architectural *shape* (LangChain orchestration → hybrid retrieval → caching → human feedback → evaluation/audit) using entirely free or free-tier tools, so the full pattern can be demoed locally or on a laptop without an AWS subscription.

---

## Layer-by-Layer Substitution

| Layer | AWS Original | Free Alternative | Notes |
|---|---|---|---|
| **Reasoning (LLM)** | Amazon Bedrock (Claude / Titan / Llama family) | **OpenAI API directly, `gpt-4o-mini`** (using your existing key), or **Claude API directly** if you'd rather stay closer to the original model family | No Bedrock wrapper needed — call the model API directly. `gpt-4o-mini` is the cheapest capable option for a demo budget; using the Claude API directly is the closer analog since Bedrock's model roster included Claude |
| **Agent/Chain Orchestration** | LangChain (on ECS Fargate) | **LangChain itself** (free, open-source) | LangChain works identically outside Bedrock — point it at `api.openai.com` or `api.anthropic.com` instead of a Bedrock endpoint. Zero substitution needed for this layer |
| **Vector/Hybrid Search** | OpenSearch Serverless (BM25 + Titan vector search) | **Qdrant** (free, self-hosted, generous free cloud tier — supports hybrid dense+sparse search natively) or **ChromaDB** (fully local, embedded, pair with a BM25 library like `rank_bm25` for the keyword half) | Qdrant's built-in hybrid search (dense + sparse vectors) is the closer analog to OpenSearch's BM25+vector combination; Chroma is simpler for a laptop demo but needs a bolted-on keyword search library to fully replicate hybrid retrieval |
| **Embeddings** | Titan Embeddings (via Bedrock) | **`text-embedding-3-small`** (OpenAI, cheap) or a free local model via **`sentence-transformers`** (e.g. `all-MiniLM-L6-v2`) | OpenAI embeddings are simplest if you're already using the OpenAI API for the LLM; sentence-transformers is fully free/local if you want zero API cost |
| **Knowledge Base / Ingestion Orchestration** | Bedrock Knowledge Bases (managed chunking + embedding pipeline) | **LlamaIndex** or **Haystack** (both free, open-source) — handles chunking, embedding generation, and indexing hand-off | These are the direct open-source analogs to a managed "ingest documents → chunk → embed → index" pipeline |
| **OCR / Document Intelligence** | Amazon Textract | **Tesseract OCR** (free/open-source) or **unstructured.io** (open-source library, layout/table aware) | Unstructured is the closer analog — handles multi-column layout and table extraction the way Textract does for plan/billing PDFs |
| **Object Storage** | Amazon S3 | **MinIO** (free, self-hosted, S3-compatible — even reuses the S3 SDK/API) or **Supabase Storage** (bundled free with the Supabase project below) | MinIO is the most drop-in replacement since it speaks the actual S3 API; Supabase Storage is simpler if you want one hosted project to cover storage, DB, and auth |
| **Async Messaging** | Amazon SNS + SQS (Textract job-completion events) | **RabbitMQ** (free, self-hosted) or **Redis Streams** (free), or **Supabase Realtime** (Postgres-native pub/sub, bundled free) | RabbitMQ maps well to SNS/SQS's pub/sub + queue semantics for "OCR job finished, trigger re-indexing"; Supabase Realtime avoids standing up a separate broker if you're already on Supabase |
| **Identity/Auth** | AWS IAM | **Supabase Auth** (bundled free, RBAC via row-level security) or **Keycloak** (free, open-source, full OIDC/RBAC) | Supabase Auth is the lighter-weight choice if you're already using Supabase for storage/DB; Keycloak is the closer enterprise-IAM analog if you want to demo fine-grained service-to-service policies |
| **Secrets Management** | AWS Secrets Manager | **HashiCorp Vault** (free OSS edition) or `.env` + Docker secrets for a demo | Vault OSS is the real analog if you want to show key rotation/centralized secrets as a distinct pattern |
| **Encryption Key Management** | AWS KMS | **HashiCorp Vault's Transit engine** (free OSS) or provider-managed encryption-at-rest (e.g. Supabase/MinIO's built-in encryption) | Vault Transit is the closest open-source analog to "centralized key management with rotation"; for a laptop demo, relying on the storage layer's built-in at-rest encryption is enough to make the point |
| **Caching** | Redis (already open-source/free) | **Redis itself** (free, self-hosted or free-tier hosted via Upstash/Redis Cloud) | No substitution needed — Redis was already the free/open-source choice in the original architecture |
| **Container Orchestration** | Amazon ECS Fargate | **Docker Compose** (single-machine) or **k3s/kind** (free, lightweight local Kubernetes) | k3s/kind lets you say "this runs on real Kubernetes," just not managed/cloud; Compose is simplest for a laptop demo |
| **Container Registry** | Amazon ECR | **Docker Hub free tier** or a local registry via the `registry:2` image | |
| **CI/CD** | GitHub Actions | **GitHub Actions** (already free for public repos, generous free minutes for private) | No substitution needed |
| **Observability (logs/metrics/alarms)** | Amazon CloudWatch | **Grafana + Prometheus + Loki** (all free, self-hosted) | Standard free OSS observability stack — Prometheus for metrics, Loki for logs, Grafana for dashboards/alarms, roughly mirroring CloudWatch's combined role |
| **Audit Log (API/account activity)** | AWS CloudTrail | **Supabase Postgres, append-only table + hash chaining** (`previous_hash`/`record_hash` columns, enforced via an insert-only trigger/RLS policy), or self-hosted **OpenTelemetry Collector** logging all service-to-service calls | Supabase's row-level security can enforce "insert-only" at the database level for tamper-evidence; OpenTelemetry is the better fit if you want to capture cross-service call activity specifically, not just DB writes |
| **Offline Evaluation (RAGAS + G-Eval + LLM-as-Judge)** | Same tools — already free/open-source | **RAGAS, G-Eval, and LLM-as-Judge unchanged**, run against the OpenAI/Claude API instead of Bedrock | No substitution needed — this layer was already free/open-source in the original; only the underlying LLM call target changes |

---

## The Practical Path

With an OpenAI (or Claude) key and Supabase in the mix, the stack splits cleanly into **hosted free-tier services** (no local infra to run) and a **thin local/Docker layer** for the pieces that don't have a good hosted-free option:

**Hosted (free tier, no Docker needed):**
- **LLM + embeddings:** OpenAI API (`gpt-4o-mini`, `text-embedding-3-small`) or Claude API
- **Storage + Auth + Realtime + Audit table:** Supabase (one project covers all four)
- **Vector search (optional hosted route):** Qdrant Cloud free tier, instead of self-hosting

**Local / Docker Compose (no free hosted equivalent, or better demoed self-hosted):**
- **Orchestration:** LangChain (runs as your application code, not a service)
- **Retrieval:** Qdrant or ChromaDB, self-hosted
- **Document ingestion pipeline:** LlamaIndex/Haystack + unstructured.io
- **Caching:** Redis
- **Messaging:** RabbitMQ (or skip in favor of Supabase Realtime)
- **Observability:** Grafana + Prometheus + Loki
- **Identity/SSO:** Keycloak — *only if* you want to demo IAM-style service-to-service policies distinct from Supabase Auth's row-level security model
- **Secrets/Key management:** `.env` locally, or HashiCorp Vault (+ Transit engine) if you want to show the pattern explicitly

This reproduces every architectural layer and every design *decision* in the original document (why hybrid retrieval, why async ingestion, why caching, why statistical sampling over per-answer sign-off) — just on free infrastructure instead of AWS, with less to self-host than the original all-open-source version since Supabase absorbs several rows at once.

---

## Open Question

Which pieces are most important to actually demo end-to-end versus which are fine to just diagram/describe in an interview setting? The hybrid-retrieval layer (Qdrant/Chroma + BM25) and the evaluation framework (RAGAS/G-Eval) are likely the highest-value pieces to actually run, since they're the parts most likely to come up as follow-up questions — worth deciding before scaffolding the project.

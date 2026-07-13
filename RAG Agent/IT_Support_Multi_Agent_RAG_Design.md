# Multi-Agent RAG IT Support SLM — Design Draft

**Scope:** Sample/demo project, 3-day build. Fabricated internal IT knowledge base. Real local script execution, restricted to a small allow-list of safe, non-admin actions. Some actions additionally require a permissions check against a PostgreSQL directory table before they can run.

## 1. Core design principle

The riskiest part of this system is "agent writes and runs a script." Rather than letting the LLM generate arbitrary code and then trying to sandbox or filter it after the fact, the Action Agent never writes free-form scripts. It only does two things: classify which of a small, pre-approved set of actions the user needs, and extract the parameters for that action (a drive letter, a UNC path, a printer name, an app name). The actual script is a static, hand-audited template with parameters substituted safely via argument lists, never string-concatenated shell commands. This turns "can the agent be tricked into running something dangerous" into a much smaller problem — there are only 4 templates, and none of them touch anything requiring elevation. This is the main simplification that keeps the architecture buildable in 3 days.

A second layer, separate from "is this script safe to run at all," is "is this specific user allowed to run it." Some actions (e.g., mapping a shared drive) are gated by department or role — only Finance should get the Finance drive, only IT should get the driver install, etc. That's an authorization question, not a safety question, so it's handled by its own step: a Permissions Agent that queries a PostgreSQL directory table for the user's department/role and checks it against the action's required entitlement, before parameters are even extracted. For this demo, the user's department is taken as a claim typed in chat (e.g., "I'm in Finance") rather than pulled from an authenticated session — it's checked against Postgres, but the identity itself is self-reported and therefore spoofable by design. That's an acceptable simplification for a 3-day sample; a real deployment would resolve identity from SSO/session context, not chat text.

## 2. Architecture diagram

```mermaid
flowchart TD
    U[User - Streamlit chat UI] --> O[Orchestrator<br/>LangGraph supervisor]

    O --> C{Intent Classifier<br/>gpt-4o-mini}
    C -->|informational| R[Retrieval Agent]
    C -->|action needed| R
    C -->|action needed, no info needed| A[Action Agent]

    R --> VDB[(ChromaDB<br/>local vector store)]
    VDB --> R
    R --> SUM[Summarize + cite KB article<br/>gpt-4o-mini]
    SUM --> O

    R -.->|if resolution requires an action| A
    A --> MATCH{Matches an<br/>allow-listed action?}
    MATCH -->|no| DECLINE[Explain KB steps,<br/>tell user to contact IT]
    MATCH -->|yes| PCHECK{Action requires<br/>entitlement?}
    PCHECK -->|no| EXTRACT
    PCHECK -->|yes| PERM[Permissions Agent<br/>looks up user dept/role]
    PERM --> PG[(PostgreSQL<br/>directory / entitlements table)]
    PG --> PERM
    PERM --> AUTH{User's dept/role<br/>entitled for this action?}
    AUTH -->|no| DECLINE
    AUTH -->|yes| EXTRACT[Extract parameters<br/>via structured output]
    EXTRACT --> GUARD[Guardrail Validator<br/>allow-list + blocklist check]
    GUARD -->|blocked| DECLINE
    GUARD -->|passed| CONFIRM[Show exact script to user<br/>require explicit confirm click]
    CONFIRM --> EXEC[Execute via subprocess<br/>non-admin, arg-list only]
    EXEC --> LOG[(Local audit log<br/>JSONL)]
    EXEC --> O
    DECLINE --> O
    O --> U

    KB[Fabricated KB<br/>~12-15 markdown articles] -.ingested at setup.-> VDB
```

## 3. Component breakdown and recommended tools

| Phase | Recommended tool | Why it fits a 3-day build |
|---|---|---|
| Orchestration / multi-agent routing | LangGraph, supervisor pattern (1 router + 2 worker agents) | Minimal boilerplate for routing between a retrieval agent and an action agent; avoids building your own state machine |
| LLM | OpenAI `gpt-4o-mini` for classification, summarization, and parameter extraction | Fast and cheap enough to call multiple times per turn; upgrade to `gpt-4o` only if answer quality on demo day needs it |
| Embeddings | OpenAI `text-embedding-3-small` | Cheap, good enough for a 15-document corpus |
| Vector store | ChromaDB, local persistent mode | Zero infrastructure — no server to stand up, runs from a Python process, fine for a fabricated 15-article KB |
| Knowledge base format | Markdown files with YAML frontmatter (`title`, `category`, `tags`) | Easy to fabricate quickly, easy to chunk, easy to cite back to the user |
| UI | Streamlit chat app | Fastest way to get a working chat + "confirm before running" button interaction |
| Permissions check | Permissions Agent — parameterized SQL query (`psycopg`) against a PostgreSQL `user_entitlements` table, keyed by department/role and action ID | Authorization lives outside the LLM's judgment — it's a deterministic DB lookup, not a model decision, so it can't be prompted around |
| Action parameter extraction | OpenAI function calling / structured output (Pydantic schema per template) | Forces the LLM's output into a fixed shape instead of freeform text, which is what makes the guardrail simple |
| Script templates | 4 static PowerShell templates (see §5), rendered with Python f-strings/Jinja2 | No codegen risk — the LLM never writes the script body, only fills typed fields |
| Execution | `subprocess.run([...])` with an argument list, never `shell=True` | Avoids shell injection entirely; runs as the logged-in user, no elevation |
| Guardrail validator | Keyword blocklist + strict allow-list of the 4 template IDs | Second layer of defense in case parameter extraction produces something unexpected |
| Audit logging | Append-only local `audit_log.jsonl` (timestamp, user, action, params, output, success/fail) | Simple, demonstrable "we log every action taken" story for the write-up |

## 4. Flow walkthrough

1. User asks a question in the Streamlit chat.
2. The Orchestrator's classifier node tags the turn as informational, action-needed, or both.
3. For informational turns, the Retrieval Agent embeds the query, pulls the top-k chunks from ChromaDB, and asks `gpt-4o-mini` to summarize the answer with a citation back to the source KB article title.
4. If the retrieved article implies a fixable action (e.g., "Fix: map the shared drive using the steps below"), the Action Agent checks whether that action matches one of the 4 allow-listed templates.
5. If the matched action is entitlement-gated (see §5.1 — currently only the drive-mapping template), the Permissions Agent takes over before any parameters are extracted. It asks the user which department they're in (if not already stated), runs a parameterized lookup against the PostgreSQL `user_entitlements` table for that department + action ID, and gets back allowed/denied. If denied, or the stated department doesn't resolve to a known row, the agent declines and explains what's missing rather than proceeding.
6. If not entitlement-gated, or the permissions check passed, the agent uses structured output to extract the needed parameters from the user's message and the KB article (e.g., drive letter, UNC path). If a required parameter is missing, it asks the user a follow-up question instead of guessing.
7. The filled-in script is passed through the Guardrail Validator, which checks it against the blocklist and confirms it's one of the 4 approved template IDs and nothing else.
8. The exact script text and a plain-English description are shown to the user in the UI. Execution only happens after the user clicks an explicit "Run" confirmation — this human-in-the-loop step is not optional.
9. The script runs locally via `subprocess.run` with an argument list, output is captured, and the result (success/failure + output) is shown to the user and appended to the audit log.
10. If the action doesn't match any allow-listed template, the KB article indicates the fix requires admin rights, or the permissions check fails, the agent gives the user the KB steps and tells them to contact IT rather than attempting anything.

## 5. Allow-listed actions (the only 4 scripts the Action Agent can ever run)

| Action | Template (Windows/PowerShell) | Required parameters | Entitlement-gated? |
|---|---|---|---|
| Map a network/shared drive | `New-PSDrive -Name X -PSProvider FileSystem -Root "\\server\share" -Persist` | drive letter, UNC path | Yes — see §5.1 |
| Install a printer driver | `Add-PrinterDriver -Name "<driver>"` (from a pre-approved local driver store, no downloads) | driver name | No |
| Map a network printer | `Add-Printer -ConnectionName "\\printserver\printername"` | print server, printer name | No |
| Install an approved app | `winget install --id <approved-app-id> --silent` (id restricted to a pre-approved app list) | app id (validated against allow-list, not free text) | No |

None of these require `-Verb RunAs`, admin group membership, or registry/user-account changes. Anything outside this list (installing unapproved software, editing the registry, creating users, changing execution policy, deleting files, disabling security features) is explicitly out of scope and the agent declines and defers to human IT staff.

### 5.1 Entitlement check for drive mapping

Different shared drives belong to different departments (e.g., only Finance should get `\\fileserver\finance`), so drive mapping is the one template in this demo that requires a permissions check before it can proceed, on top of the guardrail validator.

**Table (fabricated for the demo):**

```sql
CREATE TABLE user_entitlements (
    department   TEXT NOT NULL,
    action_id    TEXT NOT NULL,   -- e.g. 'map_shared_drive'
    resource     TEXT NOT NULL,   -- e.g. UNC path or share name this department may map
    PRIMARY KEY (department, action_id, resource)
);
```

**Lookup, always parameterized — never string-formatted into SQL:**

```python
cur.execute(
    "SELECT 1 FROM user_entitlements WHERE department = %s AND action_id = %s AND resource = %s",
    (department, action_id, resource),
)
entitled = cur.fetchone() is not None
```

**Flow specifics:**
- The user's department is a claim typed in chat (e.g., "I'm in Finance, map the shared drive"). The Permissions Agent extracts it via structured output alongside the action match, the same way parameters are extracted later — it is not authenticated identity, just a value checked against the table.
- If the stated department has no matching row for the requested share, the agent declines with the KB's normal "request access" guidance (pointing to the existing `10-requesting-admin-access.md` pattern) rather than mapping the drive.
- The Permissions Agent's query and result (department, action, resource, allowed/denied) are appended to the audit log regardless of outcome, so denied attempts are traceable too.
- This is explicitly a demo-grade simplification: production use would resolve department/role from an authenticated session (SSO claims, directory lookup) rather than trusting a chat-stated claim, since a self-reported department can't be trusted for real authorization decisions.

Guardrail blocklist (reject immediately if any of these appear anywhere in a proposed action, even though the LLM should never produce them): `Start-Process -Verb RunAs`, `sudo`, `Set-ExecutionPolicy`, `New-LocalUser`, `Remove-Item -Recurse -Force`, `reg delete`, `reg add`, `net user /add`, `diskpart`, `format`, `icacls`, `Disable-*` (any Defender/Firewall cmdlet).

## 6. Fabricated knowledge base

Since this is a sample project, the KB is a folder of ~12–15 markdown articles you write by hand (or generate once with an LLM and lightly edit), covering a realistic IT-helpdesk spread, for example: VPN connection issues, mapping a shared drive, installing a printer driver, connecting to a network printer, installing approved software via the app catalog, password reset policy, Wi-Fi connection troubleshooting, email client setup, two-factor authentication enrollment, disk space cleanup, VPN split-tunneling policy, and requesting admin access (this one should exist specifically so the agent can demonstrate declining to act and pointing to a human process). Each article gets a short frontmatter block (title, category, last-updated date, tags) so retrieval can cite "Source: Mapping a Shared Drive, updated 2026-06-02."

## 7. Three-day build plan

| Day | Focus |
|---|---|
| Day 1 | Write the 12–15 fabricated KB articles. Stand up ChromaDB, chunk + embed the KB. Build and test the Retrieval Agent in isolation (query in, cited summary out). Stand up local PostgreSQL, create and seed the `user_entitlements` table with fabricated department/resource rows. |
| Day 2 | Build the LangGraph orchestrator (classifier + supervisor routing). Build the Action Agent: the 4 script templates, structured-output parameter extraction, and the guardrail validator. Build the Permissions Agent (department extraction + parameterized Postgres lookup) and wire it in ahead of parameter extraction for the drive-mapping template. Wire up the Streamlit UI with the confirm-before-run step. |
| Day 3 | Integration testing end-to-end (informational-only, action-only, mixed, and entitlement-denied queries). Add audit logging, including denied permission checks. Test guardrail rejection paths (ask for something out of scope, confirm it declines correctly) and entitlement rejection paths (wrong department for a drive). Polish UI, prepare a short demo script with 4–5 sample queries, write up the README. |

## 8. Explicitly out of scope for this 3-day version

Multi-turn memory across sessions, support for non-Windows targets, a real ticketing-system integration, dynamic/user-editable action templates, authenticated identity resolution (SSO/session-based department lookup, as opposed to a chat-stated claim), entitlement gating on templates other than drive mapping, and any script that touches user accounts, security settings, or requires elevation. These are reasonable "next steps" to mention in a demo but would blow the timeline if attempted now.

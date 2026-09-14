-- kb_documents: version history / source of truth for what's active.
-- Qdrant remains the search index (chunked text + embeddings); this table
-- answers "what versions of a doc_id exist and which one is currently
-- active." Uploading a file whose doc_id already has an active row creates
-- a new version and marks the prior one 'superseded' rather than
-- overwriting it, so there's always an audit trail of what content an
-- answer's citation was actually grounded in at the time.
CREATE TABLE IF NOT EXISTS kb_documents (
    id                BIGSERIAL PRIMARY KEY,
    doc_id            TEXT NOT NULL,
    version           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    doc_type          TEXT NOT NULL CHECK (doc_type IN
                        ('plan_rate', 'billing_policy', 'outage_procedure',
                         'escalation_playbook', 'compliance_disclosure')),
    plan_type         TEXT,
    file_path         TEXT NOT NULL,
    file_format       TEXT NOT NULL CHECK (file_format IN ('md', 'pdf', 'html')),
    content_hash      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'superseded', 'deleted')),
    effective_date    DATE,
    uploaded_by       TEXT NOT NULL,
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, version)
);

CREATE INDEX IF NOT EXISTS idx_kb_documents_doc_id ON kb_documents (doc_id);

-- At most one active row per doc_id -- enforced at the DB level so a bug in
-- the versioning logic can't silently leave two "active" versions of the
-- same doc_id both retrievable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_documents_one_active_per_doc
    ON kb_documents (doc_id)
    WHERE status = 'active';

-- ingestion_events: durable record of the async RabbitMQ "document
-- processed" event (the SNS+SQS analog -- see NRG_Energy_Architecture_Deep_Dive.md
-- §2.6). RabbitMQ is the transport; this table is the query-of-record so
-- the Flow/Audit tabs can show ingestion status without re-draining the
-- queue. status flips published -> consumed (or -> failed after DLQ
-- routing) once scripts/consume_ingestion_events.py processes the message.
CREATE TABLE IF NOT EXISTS ingestion_events (
    id                BIGSERIAL PRIMARY KEY,
    doc_id            TEXT NOT NULL,
    version           INTEGER NOT NULL,
    event_type        TEXT NOT NULL DEFAULT 'document_processed',
    status            TEXT NOT NULL DEFAULT 'published'
                      CHECK (status IN ('published', 'consumed', 'failed')),
    chunk_count       INTEGER,
    payload           JSONB NOT NULL,
    published_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingestion_events_doc_id ON ingestion_events (doc_id);

-- sampled_answers: EVERY answer is logged here immediately and shown to the
-- user right away -- nothing here ever blocks or gates a response. This is
-- the deliberate architectural contrast with a mandatory pre-publish review
-- queue: NRG_Energy_Architecture_Deep_Dive.md §2.1 and §3 describe periodic
-- statistical sampling by Compliance/Legal instead of per-answer sign-off,
-- since the regulatory stakes here are lower and query volume far higher
-- than a GxP-style system. The reviewed_* columns are populated only if and
-- when a reviewer happens to sample this particular row -- there is no
-- "pending" gating state, unlike a review_queue table.
CREATE TABLE IF NOT EXISTS sampled_answers (
    id                    BIGSERIAL PRIMARY KEY,
    question              TEXT NOT NULL,
    answer                TEXT NOT NULL,
    doc_type_classified   TEXT,
    citations             JSONB NOT NULL DEFAULT '[]',
    confidence            TEXT CHECK (confidence IN ('high', 'medium', 'low') OR confidence IS NULL),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed              BOOLEAN NOT NULL DEFAULT false,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    review_verdict        TEXT CHECK (review_verdict IN ('accurate', 'inaccurate') OR review_verdict IS NULL),
    review_notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_sampled_answers_created_at ON sampled_answers (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sampled_answers_reviewed ON sampled_answers (reviewed);

-- Immutable, hash-chained audit log -- same design as copilot-demo's
-- (SNS/SQS analog for CloudTrail-style traceability per the deep-dive's
-- §2.11 CloudTrail node and §3's "not GxP but still a regulated consumer-
-- facing industry" framing). Written on document_ingested and
-- answer_sampled_reviewed events.
CREATE TABLE IF NOT EXISTS audit_log (
    id                   BIGSERIAL PRIMARY KEY,
    event_type           TEXT NOT NULL,
    payload              JSONB NOT NULL,
    actor                TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    record_hash          TEXT NOT NULL,
    previous_hash        TEXT NOT NULL
);

-- Enforce insert-only (no UPDATE/DELETE) on the audit log at the DB level.
CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is insert-only: % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

-- Knowledge base document version history. Chroma remains the search
-- index (chunked text + embeddings); this table is the source of truth
-- for "what versions of a doc_id exist and which one is currently active."
-- Uploading a file whose doc_id already has an active row creates a new
-- version and marks the prior one 'superseded' rather than overwriting it,
-- so there's always an audit trail of what content an agent's citation
-- was actually grounded in at the time.

CREATE TABLE IF NOT EXISTS kb_documents (
    id                BIGSERIAL PRIMARY KEY,
    doc_id            TEXT NOT NULL,
    version           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    doc_type          TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    file_format       TEXT NOT NULL CHECK (file_format IN ('md', 'html')),
    content_hash      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'superseded', 'deleted')),
    effective_date    DATE,
    uploaded_by       TEXT NOT NULL,
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, version)
);

CREATE INDEX IF NOT EXISTS idx_kb_documents_doc_id ON kb_documents (doc_id);

-- At most one active row per doc_id -- enforced at the DB level so a bug
-- in the versioning logic can't silently leave two "active" versions of
-- the same doc_id both retrievable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_documents_one_active_per_doc
    ON kb_documents (doc_id)
    WHERE status = 'active';

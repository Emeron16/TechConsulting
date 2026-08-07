-- Structured/relational data: batch metadata, deviation status, CAPA status.
-- Document content itself (SOPs, deviation narrative, CAPA narrative) lives in Chroma;
-- this is the "SQL-vs-search split" from the original architecture.

CREATE TABLE batches (
    batch_id            TEXT PRIMARY KEY,
    product_name        TEXT NOT NULL,
    manufacturing_line  TEXT NOT NULL,
    manufacturing_date  DATE NOT NULL,
    disposition_status  TEXT NOT NULL DEFAULT 'pending'
                         CHECK (disposition_status IN ('pending', 'released', 'rejected', 'rework')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE deviations (
    deviation_id        TEXT PRIMARY KEY,
    batch_id            TEXT REFERENCES batches(batch_id),
    date_identified      DATE NOT NULL,
    classification       TEXT CHECK (classification IN ('critical', 'major', 'minor', 'pending')),
    root_cause_category   TEXT,
    investigation_status TEXT NOT NULL DEFAULT 'open'
                         CHECK (investigation_status IN ('open', 'closed')),
    related_deviation_id TEXT REFERENCES deviations(deviation_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE capas (
    capa_id              TEXT PRIMARY KEY,
    related_deviation_id TEXT REFERENCES deviations(deviation_id),
    status               TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'effective', 'ineffective', 'closed')),
    monitoring_start     DATE,
    monitoring_end       DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human-in-the-loop review queue (Phase 4)
CREATE TABLE review_queue (
    id                   BIGSERIAL PRIMARY KEY,
    question             TEXT NOT NULL,
    draft_answer         TEXT NOT NULL,
    citations            JSONB NOT NULL DEFAULT '[]',
    agent_name           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at          TIMESTAMPTZ,
    reviewed_by          TEXT
);

-- Immutable, hash-chained audit log (Phase 4)
CREATE TABLE audit_log (
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

-- Seed data matching the synthetic documents in data/synthetic_docs/
INSERT INTO batches (batch_id, product_name, manufacturing_line, manufacturing_date, disposition_status) VALUES
    ('BATCH-4471', 'Drug Product (lyophilized)', 'Line 3', '2026-06-12', 'pending'),
    ('BATCH-4108', 'Drug Product (lyophilized)', 'Line 3', '2026-02-18', 'released');

INSERT INTO deviations (deviation_id, batch_id, date_identified, classification, root_cause_category, investigation_status, related_deviation_id) VALUES
    ('DEV-2144', 'BATCH-4108', '2026-02-18', 'major', 'equipment_failure', 'closed', NULL),
    ('DEV-2201', 'BATCH-4471', '2026-06-12', 'pending', NULL, 'open', 'DEV-2144');

INSERT INTO capas (capa_id, related_deviation_id, status, monitoring_start, monitoring_end) VALUES
    ('CAPA-3390', 'DEV-2144', 'open', '2026-03-25', '2026-09-21');

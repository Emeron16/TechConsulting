-- warranty_cases: one row per submitted case (new or bulk-seeded
-- historical). OpenSearch is the search/lookup index (structured filters +
-- full-text + vector); this table is the durable source of truth a case's
-- classification/entity/escalation rows join back to.
CREATE TABLE IF NOT EXISTS warranty_cases (
    id                BIGSERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL UNIQUE,
    vin               TEXT NOT NULL,
    narrative_text    TEXT NOT NULL,
    dealer_location   TEXT,
    mileage           INTEGER,
    vehicle_model     TEXT,
    model_year        INTEGER,
    status            TEXT NOT NULL DEFAULT 'indexed'
                      CHECK (status IN ('indexed', 'escalated', 'escalation_resolved')),
    submitted_by      TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_warranty_cases_vin ON warranty_cases (vin);

-- case_classifications: a JOIN table, not a single doc_type-style enum
-- column, because the BERT/DistilBERT classifier is multi-label -- a case
-- can legitimately carry more than one category at once (see
-- Volvo_Architecture_Deep_Dive.md §2.4's infotainment+electrical example).
-- Per-category confidence stays individually queryable this way, which a
-- JSONB array would not give for free.
CREATE TABLE IF NOT EXISTS case_classifications (
    id                BIGSERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES warranty_cases(case_id),
    category          TEXT NOT NULL CHECK (category IN
                        ('powertrain', 'infotainment', 'electrical', 'braking',
                         'software_update', 'safety_concern', 'parts_delay',
                         'dealer_escalation')),
    confidence        REAL NOT NULL,
    UNIQUE (case_id, category)
);

CREATE INDEX IF NOT EXISTS idx_case_classifications_case_id ON case_classifications (case_id);
CREATE INDEX IF NOT EXISTS idx_case_classifications_category ON case_classifications (category);

-- extracted_entities: spaCy NER output. Kept as JSONB rather than a join
-- table since entity types are heterogeneous and open-ended (VIN, DTC,
-- COMPONENT, SYMPTOM, ...) unlike the fixed 8-category classification
-- vocabulary above.
CREATE TABLE IF NOT EXISTS extracted_entities (
    id                BIGSERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES warranty_cases(case_id) UNIQUE,
    entities          JSONB NOT NULL DEFAULT '[]'
);

-- safety_escalations: the THIRD distinct human-in-the-loop pattern across
-- the three demos in this repo -- not Novartis's mandatory pre-publish
-- gate, not NRG's after-the-fact statistical sampling. A row here is
-- created only when (a) a case is directly classified safety_concern
-- above threshold, or (b) similarity search surfaces a recurring pattern
-- across multiple already-flagged similar cases. Per
-- Volvo_Architecture_Deep_Dive.md §2.1/§3, this is a real routing decision
-- with TREAD Act / recall-determination consequences, not a passive
-- annotation -- routine (non-safety) classifications never produce a row
-- here at all.
CREATE TABLE IF NOT EXISTS safety_escalations (
    id                BIGSERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES warranty_cases(case_id),
    trigger_reason    TEXT NOT NULL CHECK (trigger_reason IN
                        ('direct_classification', 'recurring_pattern')),
    related_case_ids  JSONB NOT NULL DEFAULT '[]',
    status            TEXT NOT NULL DEFAULT 'pending_review'
                      CHECK (status IN ('pending_review', 'field_action_recommended',
                                        'no_action_needed')),
    raised_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMPTZ,
    review_notes      TEXT
);

CREATE INDEX IF NOT EXISTS idx_safety_escalations_status ON safety_escalations (status);

-- airflow_dag_runs: the thin join key between a submitted case_id and the
-- Airflow dag_run_id processing it. This does NOT duplicate Airflow's own
-- metadata DB (which separately tracks full task-instance history in its
-- own Postgres, stood up in Phase 7) -- it exists only so the UI can look
-- up which dag_run_id to poll for a given case_id.
--
-- Deliberately NOT a foreign key to warranty_cases: this row is written
-- the moment a DAG run is TRIGGERED, which is before the case exists in
-- warranty_cases at all (that insert only happens later, inside the DAG's
-- index_and_check_escalation task calling /index-case). A DAG run can also
-- fail before ever reaching that task, in which case case_id here
-- legitimately never appears in warranty_cases -- an FK would make that
-- normal, expected outcome impossible to record. Caught during Phase 9's
-- Submit New Case testing: a first version with `REFERENCES
-- warranty_cases(case_id)` raised a foreign-key violation on every
-- submission, since the insert always happens before the case exists.
CREATE TABLE IF NOT EXISTS airflow_dag_runs (
    id                  BIGSERIAL PRIMARY KEY,
    case_id             TEXT NOT NULL,
    dag_run_id          TEXT NOT NULL UNIQUE,
    triggered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_polled_state   TEXT,
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_airflow_dag_runs_case_id ON airflow_dag_runs (case_id);

-- Immutable, hash-chained audit log -- identical design to
-- nrg-demo/db/init/01_schema.sql's audit_log (the chaining logic is
-- domain-agnostic; see volvo_retrieval/audit.py, ported near-verbatim from
-- nrg_retrieval/audit.py).
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

-- Minimal credential store backing real 21 CFR Part 11-style e-signature
-- re-authentication at approve/reject time (mcp_servers/auth.py). Previously
-- reviewer_name was free text with no verification -- this table is what a
-- password re-entry at signing time is actually checked against, so
-- "who signed" in the audit log is a verified identity, not a typed string.
--
-- NOTE: docker-compose.yml only auto-runs files in db/init/ against a
-- FRESH postgres data volume (docker-entrypoint-initdb.d semantics). On an
-- already-initialized demo DB, apply manually:
--   docker compose exec -T postgres psql -U copilot -d copilot < db/init/04_qp_users.sql

CREATE TABLE qp_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'QP' CHECK (role IN ('QP', 'reviewer')),
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Demo accounts only -- password is the literal string shown, bcrypt-hashed.
-- qp_jane   / qp-jane-demo-pw
-- qp_marcus / qp-marcus-demo-pw
-- prince    / password
INSERT INTO qp_users (username, password_hash, display_name, role) VALUES
    ('qp_jane', '$2b$12$rum10ud8Cg56UpeKrBw5Fen5Zuu1CUKgBZHROyOtZ4vVdf1/WaI1S', 'Jane QP Reviewer', 'QP'),
    ('qp_marcus', '$2b$12$HtKSWXq0Xz65uDTD6LWtkOvNt4QCExdEPHOD2qa7lbIdiERdvr/ay', 'Marcus QP Reviewer', 'QP'),
    ('prince', '$2b$12$4fyvRNtwaLdKd1kLmlYg2uVAMnKHny4mofnyhr7D8J3IqlyycqLuO', 'Prince QP Reviewer', 'QP');

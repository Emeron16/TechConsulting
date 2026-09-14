-- Adds structured promotion linkage from review_queue to the capas/
-- deviations records it can create/update, and the narrative columns a
-- promoted record needs to be self-contained (matches real eQMS systems
-- storing the full CAPA/disposition record in one row rather than
-- splitting narrative into a separate document store).
--
-- NOTE: docker-compose.yml only auto-runs files in db/init/ against a
-- FRESH postgres data volume (docker-entrypoint-initdb.d semantics). On an
-- already-initialized demo DB, apply manually:
--   docker compose exec -T postgres psql -U copilot -d copilot < db/init/03_review_promotion.sql

ALTER TABLE review_queue
    ADD COLUMN linked_record_type TEXT CHECK (linked_record_type IN ('capa', 'deviation')),
    ADD COLUMN linked_record_id   TEXT,
    ADD COLUMN structured_payload JSONB;

ALTER TABLE capas
    ADD COLUMN root_cause_summary TEXT,
    ADD COLUMN proposed_action    TEXT;

ALTER TABLE deviations
    ADD COLUMN investigation_summary TEXT;

ALTER TABLE system_initialization_state
    ADD COLUMN last_known_good_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN last_known_good_readiness jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE system_initialization_state
SET last_known_good_metadata = candidate_metadata,
    last_known_good_readiness = readiness_summary
WHERE last_known_good_revision IS NOT NULL;

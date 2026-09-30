BEGIN;

ALTER TABLE identity_sync_runs
    ADD COLUMN queued_at timestamptz,
    ADD COLUMN heartbeat_at timestamptz,
    ADD COLUMN lease_token uuid;

UPDATE identity_sync_runs run
SET queued_at = coalesce(
    (
        SELECT min(event.created_at)
        FROM outbox_events event
        WHERE event.topic = 'identity.sync.requested'
          AND event.aggregate_id = run.id
    ),
    run.started_at,
    run.completed_at,
    now()
);

UPDATE identity_sync_runs
SET status = 'failed',
    completed_at = now(),
    error_code = CASE
        WHEN status = 'running' THEN 'identity_sync_heartbeat_timeout'
        ELSE 'identity_sync_queue_timeout'
    END,
    error_message = 'Identity synchronization did not complete before upgrade'
WHERE status IN ('queued', 'running')
  AND coalesce(heartbeat_at, started_at, queued_at) < now() - interval '5 minutes';

WITH active_ranked AS (
    SELECT id, row_number() OVER (ORDER BY queued_at DESC, id DESC) AS active_rank
    FROM identity_sync_runs
    WHERE status IN ('queued', 'running')
)
UPDATE identity_sync_runs run
SET status = 'failed',
    completed_at = now(),
    error_code = 'identity_sync_duplicate_active',
    error_message = 'Duplicate active identity synchronization was retired during upgrade'
FROM active_ranked ranked
WHERE run.id = ranked.id
  AND ranked.active_rank > 1;

UPDATE identity_sync_runs
SET lease_token = gen_random_uuid()
WHERE status IN ('queued', 'running')
  AND lease_token IS NULL;

ALTER TABLE identity_sync_runs
    ALTER COLUMN queued_at SET DEFAULT now(),
    ALTER COLUMN queued_at SET NOT NULL;

CREATE UNIQUE INDEX uq_identity_sync_runs_single_active
    ON identity_sync_runs ((true))
    WHERE status IN ('queued', 'running');

CREATE INDEX ix_identity_sync_runs_status_queued_at
    ON identity_sync_runs (status, queued_at DESC);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg234.identity_sync_recovery',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-234'),
    now()
);

COMMIT;

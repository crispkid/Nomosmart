BEGIN;

ALTER TABLE identity_sync_runs
    ADD COLUMN requested_scope varchar(32),
    ADD COLUMN phase varchar(32);

UPDATE identity_sync_runs
SET requested_scope = 'people_and_groups',
    phase = CASE
        WHEN status = 'succeeded' THEN 'completed'
        WHEN status = 'failed' THEN 'failed'
        WHEN status = 'queued' THEN 'queued'
        ELSE 'provider_discovery'
    END;

ALTER TABLE identity_sync_runs
    ALTER COLUMN requested_scope SET DEFAULT 'people_and_groups',
    ALTER COLUMN requested_scope SET NOT NULL,
    ALTER COLUMN phase SET DEFAULT 'queued',
    ALTER COLUMN phase SET NOT NULL,
    ADD CONSTRAINT identity_sync_runs_requested_scope_check
        CHECK (requested_scope IN ('people', 'groups', 'people_and_groups')),
    ADD CONSTRAINT identity_sync_runs_phase_check
        CHECK (phase IN (
            'queued',
            'provider_discovery',
            'provider_user_sync',
            'provider_group_sync',
            'snapshot_fetch',
            'reconciliation',
            'completed',
            'failed'
        ));

CREATE TABLE identity_sync_provider_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES identity_sync_runs(id) ON DELETE CASCADE,
    provider_id varchar(255) NOT NULL,
    provider_name varchar(255) NOT NULL,
    provider_vendor varchar(64) NOT NULL,
    requested_scope varchar(32) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending',
    user_sync_status varchar(32) NOT NULL DEFAULT 'not_requested',
    group_sync_status varchar(32) NOT NULL DEFAULT 'not_requested',
    users_added integer NOT NULL DEFAULT 0,
    users_updated integer NOT NULL DEFAULT 0,
    users_removed integer NOT NULL DEFAULT 0,
    users_failed integer NOT NULL DEFAULT 0,
    users_ignored integer NOT NULL DEFAULT 0,
    error_code varchar(100),
    started_at timestamptz,
    heartbeat_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_identity_sync_provider_results_run_provider
        UNIQUE (run_id, provider_id),
    CONSTRAINT identity_sync_provider_results_scope_check
        CHECK (requested_scope IN ('people', 'groups', 'people_and_groups')),
    CONSTRAINT identity_sync_provider_results_status_check
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    CONSTRAINT identity_sync_provider_results_user_status_check
        CHECK (user_sync_status IN ('not_requested', 'pending', 'running', 'succeeded', 'failed', 'skipped')),
    CONSTRAINT identity_sync_provider_results_group_status_check
        CHECK (group_sync_status IN ('not_requested', 'pending', 'running', 'succeeded', 'failed', 'skipped')),
    CONSTRAINT identity_sync_provider_results_counters_check
        CHECK (
            users_added >= 0
            AND users_updated >= 0
            AND users_removed >= 0
            AND users_failed >= 0
            AND users_ignored >= 0
        )
);

CREATE INDEX ix_identity_sync_provider_results_run_created
    ON identity_sync_provider_results (run_id, created_at, provider_id);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg255.keycloak_cascaded_identity_sync',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-255'),
    now()
);

COMMIT;

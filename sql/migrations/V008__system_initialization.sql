CREATE TABLE system_initialization_state (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_mode varchar(32) NOT NULL DEFAULT 'appliance',
    status varchar(64) NOT NULL DEFAULT 'not_started',
    lock_state varchar(64) NOT NULL DEFAULT 'first_run_open',
    current_revision integer NOT NULL DEFAULT 0,
    last_known_good_revision integer,
    candidate_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    readiness_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    completed_at timestamptz,
    locked_at timestamptz,
    unlocked_by uuid REFERENCES users(id),
    unlock_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_system_initialization_singleton
    ON system_initialization_state ((true));

CREATE TABLE system_initialization_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    initialization_state_id uuid NOT NULL REFERENCES system_initialization_state(id) ON DELETE CASCADE,
    step_key varchar(100) NOT NULL,
    status varchar(32) NOT NULL,
    detail_code varchar(100) NOT NULL,
    safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    audit_log_id uuid REFERENCES audit_logs(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_system_initialization_steps_state_created
    ON system_initialization_steps(initialization_state_id, created_at);

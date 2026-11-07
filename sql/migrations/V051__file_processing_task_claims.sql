BEGIN;

-- CHG-305 R11 additive task journal. No backfill, policy initialization or down migration.
CREATE TABLE file_processing_tasks (
    id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES file_processing_executions(id),
    generation uuid NOT NULL REFERENCES file_processing_executions(generation),
    broker_task_id uuid NOT NULL UNIQUE,
    claim_token uuid,
    state varchar(24) NOT NULL CHECK (state IN ('prepared','claimed','quiescent','finalized','recovery_required')),
    disposition varchar(16) CHECK (disposition IN ('completed','failed','cancelled','yield')),
    worker_identity varchar(255),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    heartbeat_at timestamptz,
    finished_at timestamptz,
    completion_receipt jsonb,
    CONSTRAINT ck_file_task_claim CHECK (state = 'prepared' OR claim_token IS NOT NULL),
    CONSTRAINT ck_file_task_final CHECK ((state = 'finalized') = (finished_at IS NOT NULL)),
    CONSTRAINT ck_file_task_completion CHECK (
        state NOT IN ('quiescent','finalized') OR (disposition IS NOT NULL AND completion_receipt IS NOT NULL))
);
CREATE UNIQUE INDEX uq_file_task_active ON file_processing_tasks(execution_id) WHERE finished_at IS NULL;
CREATE INDEX ix_file_task_state ON file_processing_tasks(state, updated_at);
COMMENT ON TABLE file_processing_tasks IS
    'CHG-305 task-specific completion; an expired heartbeat is never authority to recycle a document slot.';

COMMIT;

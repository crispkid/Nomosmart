BEGIN;

ALTER TABLE roles
    ADD COLUMN deleted_at timestamptz,
    ADD COLUMN deleted_by uuid REFERENCES users(id);

ALTER TABLE roles
    DROP CONSTRAINT roles_name_key;

ALTER TABLE roles
    ADD CONSTRAINT roles_deleted_inactive_check
    CHECK (deleted_at IS NULL OR is_active = false);

CREATE UNIQUE INDEX uq_roles_undeleted_name
    ON roles (name)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_roles_undeleted_name_id
    ON roles (name, id)
    WHERE deleted_at IS NULL;

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg237.local_role_lifecycle',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-237'),
    now()
);

COMMIT;

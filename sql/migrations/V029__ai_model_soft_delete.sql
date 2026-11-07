BEGIN;

ALTER TABLE ai_models
    ADD COLUMN deleted_at timestamptz,
    ADD COLUMN deleted_by uuid REFERENCES users(id);

ALTER TABLE ai_models
    DROP CONSTRAINT ai_models_name_model_type_key;

DROP INDEX uq_ai_models_default_type;

CREATE UNIQUE INDEX uq_ai_models_active_name_type
    ON ai_models (name, model_type)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX uq_ai_models_default_type
    ON ai_models (model_type)
    WHERE is_active AND is_default AND deleted_at IS NULL;

CREATE INDEX ix_ai_models_live_type_name
    ON ai_models (model_type, name, id)
    WHERE deleted_at IS NULL;

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg235.ai_model_soft_delete',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-235'),
    now()
);

COMMIT;

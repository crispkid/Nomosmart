CREATE TABLE IF NOT EXISTS system_prompts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_scope varchar(16) NOT NULL,
    model_type varchar(32) NOT NULL,
    model_id uuid NULL REFERENCES ai_models(id),
    is_active boolean NOT NULL DEFAULT false,
    current_version_id uuid NULL,
    lock_version integer NOT NULL DEFAULT 1,
    created_by uuid NULL REFERENCES users(id),
    updated_by uuid NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT system_prompts_scope_check CHECK (prompt_scope IN ('global', 'model')),
    CONSTRAINT system_prompts_model_type_check CHECK (model_type IN ('Chat', 'Judge')),
    CONSTRAINT system_prompts_scope_model_check CHECK (
        (prompt_scope = 'global' AND model_id IS NULL)
        OR (prompt_scope = 'model' AND model_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_system_prompts_global_type
    ON system_prompts(model_type)
    WHERE prompt_scope = 'global';

CREATE UNIQUE INDEX IF NOT EXISTS uq_system_prompts_model_id
    ON system_prompts(model_id)
    WHERE prompt_scope = 'model';

CREATE TABLE IF NOT EXISTS system_prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id uuid NOT NULL REFERENCES system_prompts(id) ON DELETE CASCADE,
    version_number integer NOT NULL,
    content text NOT NULL DEFAULT '',
    content_hash varchar(64) NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    change_reason text NULL,
    created_by uuid NULL REFERENCES users(id),
    request_id varchar(255),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_system_prompt_versions_number UNIQUE (prompt_id, version_number),
    CONSTRAINT system_prompt_versions_content_length_check CHECK (char_length(content) <= 8000)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_system_prompts_current_version'
            AND conrelid = 'system_prompts'::regclass
    ) THEN
        ALTER TABLE system_prompts
            ADD CONSTRAINT fk_system_prompts_current_version
            FOREIGN KEY (current_version_id) REFERENCES system_prompt_versions(id);
    END IF;
END $$;

ALTER TABLE chat_records
    ADD COLUMN IF NOT EXISTS system_prompt_source varchar(32),
    ADD COLUMN IF NOT EXISTS system_prompt_version_id uuid NULL REFERENCES system_prompt_versions(id),
    ADD COLUMN IF NOT EXISTS system_prompt_content_hash varchar(64),
    ADD COLUMN IF NOT EXISTS system_prompt_layers jsonb;

ALTER TABLE validation_run_items
    ADD COLUMN IF NOT EXISTS system_prompt_source varchar(32),
    ADD COLUMN IF NOT EXISTS system_prompt_version_id uuid NULL REFERENCES system_prompt_versions(id),
    ADD COLUMN IF NOT EXISTS system_prompt_content_hash varchar(64),
    ADD COLUMN IF NOT EXISTS system_prompt_layers jsonb;

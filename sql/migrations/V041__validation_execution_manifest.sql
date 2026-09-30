ALTER TABLE validation_runs
    ADD COLUMN IF NOT EXISTS execution_manifest jsonb,
    ADD COLUMN IF NOT EXISTS execution_manifest_hash varchar(64),
    ADD COLUMN IF NOT EXISTS max_attempts integer;

UPDATE validation_runs
SET execution_manifest = jsonb_build_object(
        'manifest_version', 'legacy-unavailable',
        'state', 'legacy_manifest_unavailable'
    )
WHERE execution_manifest IS NULL;

UPDATE validation_runs
SET max_attempts = 1
WHERE max_attempts IS NULL;

UPDATE validation_runs
SET execution_manifest_hash = encode(
        digest(convert_to(execution_manifest::text, 'UTF8'), 'sha256'),
        'hex'
    )
WHERE execution_manifest_hash IS NULL;

ALTER TABLE validation_runs
    ALTER COLUMN execution_manifest SET NOT NULL,
    ALTER COLUMN execution_manifest_hash SET NOT NULL,
    ALTER COLUMN max_attempts SET NOT NULL,
    ALTER COLUMN max_attempts SET DEFAULT 3;

ALTER TABLE validation_runs
    DROP CONSTRAINT IF EXISTS validation_runs_max_attempts_check;

ALTER TABLE validation_runs
    ADD CONSTRAINT validation_runs_max_attempts_check
    CHECK (max_attempts BETWEEN 1 AND 10);

ALTER TABLE validation_run_items
    ADD COLUMN IF NOT EXISTS input_item_id uuid,
    ADD COLUMN IF NOT EXISTS input_ordinal integer,
    ADD COLUMN IF NOT EXISTS input_content_hash varchar(64);

WITH input_roots AS (
    SELECT DISTINCT
        run_id,
        COALESCE(parent_item_id, id) AS root_item_id
    FROM validation_run_items
),
ordered_items AS (
    SELECT
        run_id,
        root_item_id,
        row_number() OVER (
            PARTITION BY run_id
            ORDER BY root_item_id
        )::integer AS ordinal
    FROM input_roots
)
UPDATE validation_run_items AS item
SET input_item_id = COALESCE(item.input_item_id, item.parent_item_id, item.id),
    input_ordinal = COALESCE(item.input_ordinal, ordered_items.ordinal),
    input_content_hash = COALESCE(
        item.input_content_hash,
        encode(
            digest(
                convert_to(
                    concat_ws(
                        E'\x1f',
                        item.question,
                        COALESCE(item.expected_answer, ''),
                        COALESCE(item.expected_keywords::text, '[]'),
                        COALESCE(item.selected_document_ids::text, '[]'),
                        COALESCE(item.category, ''),
                        COALESCE(item.priority, '')
                    ),
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    )
FROM ordered_items
WHERE ordered_items.run_id = item.run_id
  AND ordered_items.root_item_id = COALESCE(item.parent_item_id, item.id);

ALTER TABLE validation_run_items
    ALTER COLUMN input_item_id SET NOT NULL,
    ALTER COLUMN input_ordinal SET NOT NULL,
    ALTER COLUMN input_content_hash SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_validation_items_run_input_attempt
    ON validation_run_items(run_id, input_item_id, attempt);

CREATE UNIQUE INDEX IF NOT EXISTS uq_validation_items_run_ordinal_attempt
    ON validation_run_items(run_id, input_ordinal, attempt);

CREATE INDEX IF NOT EXISTS ix_validation_items_run_ordinal
    ON validation_run_items(run_id, input_ordinal, attempt, id);

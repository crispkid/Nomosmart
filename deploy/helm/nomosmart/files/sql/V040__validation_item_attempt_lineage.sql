ALTER TABLE validation_run_items
    ADD COLUMN IF NOT EXISTS parent_item_id uuid REFERENCES validation_run_items(id),
    ADD COLUMN IF NOT EXISTS attempt integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_current boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS error_code varchar(100);

CREATE INDEX IF NOT EXISTS ix_validation_items_run_current_created
    ON validation_run_items(run_id, is_current, created_at, id);

CREATE INDEX IF NOT EXISTS ix_validation_items_parent_attempt
    ON validation_run_items(parent_item_id, attempt);

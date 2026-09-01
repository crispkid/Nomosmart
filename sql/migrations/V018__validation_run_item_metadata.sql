ALTER TABLE validation_run_items
    ADD COLUMN IF NOT EXISTS category varchar(100),
    ADD COLUMN IF NOT EXISTS priority varchar(32);

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS ocr_model_id uuid REFERENCES ai_models(id);

CREATE INDEX IF NOT EXISTS ix_projects_ocr_model_id ON projects(ocr_model_id);

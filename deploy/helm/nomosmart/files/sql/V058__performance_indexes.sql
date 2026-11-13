-- CHG-424 OPT424-013: indexes for identity resolution, notifications, reports
-- and document pipeline lookups. Index-only; no data or contract change.
-- Runs inside the upgrade window like earlier migrations (writes to these
-- tables wait for each index build). Rollback: DROP INDEX IF EXISTS <name>.
CREATE INDEX IF NOT EXISTS ix_role_users_user ON public.role_users USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_project_owners_user ON public.project_owners USING btree (user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_read_created ON public.notifications USING btree (recipient_user_id, is_read, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_chat_records_project_created ON public.chat_records USING btree (project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_project_created ON public.pipeline_runs USING btree (project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_version_created ON public.pipeline_runs USING btree (document_version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_validation_runs_project_created ON public.validation_runs USING btree (project_id, created_at);

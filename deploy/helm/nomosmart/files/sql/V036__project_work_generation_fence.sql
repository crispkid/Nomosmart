BEGIN;

ALTER TABLE projects
    ADD COLUMN work_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE project_archive_runs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE outbox_events
    ADD COLUMN project_id uuid REFERENCES projects(id),
    ADD COLUMN project_generation bigint;

ALTER TABLE file_scan_runs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE data_sync_runs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE pipeline_runs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE validation_runs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

ALTER TABLE graph_sync_jobs
    ADD COLUMN project_generation bigint NOT NULL DEFAULT 1;

UPDATE document_versions AS version
SET chunk_strategy = jsonb_set(
    version.chunk_strategy,
    '{chunk_artifacts,project_generation}',
    to_jsonb(project.work_generation),
    true
)
FROM projects AS project
WHERE project.id = version.project_id
  AND version.chunk_strategy ? 'chunk_artifacts';

UPDATE outbox_events AS event
SET project_id = pipeline.project_id,
    project_generation = pipeline.project_generation
FROM pipeline_runs AS pipeline
WHERE event.aggregate_type = 'pipeline_run'
  AND event.aggregate_id = pipeline.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = version.project_id,
    project_generation = scan.project_generation
FROM file_scan_runs AS scan
JOIN document_versions AS version ON version.id = scan.document_version_id
WHERE event.aggregate_type = 'file_scan_run'
  AND event.aggregate_id = scan.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = connection.project_id,
    project_generation = sync_run.project_generation
FROM data_sync_runs AS sync_run
JOIN data_connections AS connection ON connection.id = sync_run.data_connection_id
WHERE event.aggregate_type = 'data_sync_run'
  AND event.aggregate_id = sync_run.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = run.project_id,
    project_generation = run.project_generation
FROM validation_runs AS run
WHERE event.aggregate_type = 'validation_run'
  AND event.aggregate_id = run.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = job.project_id,
    project_generation = job.project_generation
FROM graph_sync_jobs AS job
WHERE event.aggregate_type = 'graph_sync_job'
  AND event.aggregate_id = job.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = version.project_id,
    project_generation = project.work_generation
FROM document_versions AS version
JOIN projects AS project ON project.id = version.project_id
WHERE event.aggregate_type = 'document_version'
  AND event.aggregate_id = version.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET project_id = archive_run.project_id,
    project_generation = archive_run.project_generation
FROM project_archive_runs AS archive_run
WHERE event.aggregate_type = 'project_archive_run'
  AND event.aggregate_id = archive_run.id
  AND event.project_id IS NULL;

UPDATE outbox_events AS event
SET status = 'cancelled',
    processed_at = now(),
    last_error = 'project_generation_stale'
FROM projects AS project
WHERE event.project_id = project.id
  AND event.topic <> 'project.archive.cleanup.requested'
  AND (project.status = 'archived' OR event.project_generation IS DISTINCT FROM project.work_generation)
  AND event.status IN ('pending', 'dispatching');

CREATE INDEX ix_outbox_events_project_generation_status
    ON outbox_events (project_id, project_generation, status, available_at, id);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg247.project_work_generation_fence',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-247', 'requirement_id', 'PROJECT-006'),
    now()
);

COMMIT;

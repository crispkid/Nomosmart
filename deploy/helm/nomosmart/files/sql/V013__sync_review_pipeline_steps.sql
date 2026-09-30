BEGIN;

UPDATE pipeline_run_steps step
SET
    status = 'completed',
    progress_percent = 100,
    completed_at = COALESCE(step.completed_at, CURRENT_TIMESTAMP),
    progress_message = 'Manager review approved',
    error_message = NULL
FROM pipeline_runs run
JOIN document_versions version ON version.id = run.document_version_id
WHERE step.run_id = run.id
  AND step.step_name = 'manager_review'
  AND step.status = 'waiting_action'
  AND version.status IN ('pending_owner_review', 'approved', 'active');

UPDATE pipeline_run_steps step
SET
    status = 'waiting_action',
    progress_percent = 0,
    started_at = NULL,
    completed_at = NULL,
    progress_message = 'Waiting for project_owner',
    error_message = NULL
FROM pipeline_runs run
JOIN document_versions version ON version.id = run.document_version_id
WHERE step.run_id = run.id
  AND step.step_name = 'owner_review'
  AND version.status = 'pending_owner_review';

UPDATE pipeline_runs run
SET
    status = 'waiting_action',
    current_step_name = 'owner_review',
    current_waiting_role = 'project_owner',
    current_action_url = '/approve/' || run.id::text
FROM document_versions version
WHERE version.id = run.document_version_id
  AND version.status = 'pending_owner_review';

UPDATE pipeline_run_steps step
SET
    status = 'completed',
    progress_percent = 100,
    completed_at = COALESCE(step.completed_at, CURRENT_TIMESTAMP),
    progress_message = 'Project Owner review approved',
    error_message = NULL
FROM pipeline_runs run
JOIN document_versions version ON version.id = run.document_version_id
WHERE step.run_id = run.id
  AND step.step_name = 'owner_review'
  AND step.status = 'waiting_action'
  AND version.status IN ('approved', 'active');

UPDATE pipeline_run_steps step
SET
    status = 'waiting_action',
    progress_percent = 0,
    started_at = NULL,
    completed_at = NULL,
    progress_message = 'Waiting for publisher',
    error_message = NULL
FROM pipeline_runs run
JOIN document_versions version ON version.id = run.document_version_id
WHERE step.run_id = run.id
  AND step.step_name = 'publish'
  AND version.status = 'approved';

UPDATE pipeline_runs run
SET
    status = 'waiting_action',
    current_step_name = 'publish',
    current_waiting_role = 'publisher',
    current_action_url = NULL
FROM document_versions version
WHERE version.id = run.document_version_id
  AND version.status = 'approved';

UPDATE pipeline_run_steps step
SET
    status = 'completed',
    progress_percent = 100,
    completed_at = COALESCE(step.completed_at, CURRENT_TIMESTAMP),
    error_message = NULL
FROM pipeline_runs run
JOIN document_versions version ON version.id = run.document_version_id
WHERE step.run_id = run.id
  AND step.step_name IN ('publish', 'production_index', 'graph_sync')
  AND version.status = 'active';

UPDATE pipeline_runs run
SET
    status = 'completed',
    progress_percent = 100,
    current_step_name = 'graph_sync',
    current_waiting_role = NULL,
    current_action_url = NULL,
    completed_at = COALESCE(run.completed_at, CURRENT_TIMESTAMP)
FROM document_versions version
WHERE version.id = run.document_version_id
  AND version.status = 'active';

COMMIT;

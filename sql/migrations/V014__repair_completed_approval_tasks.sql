-- Repair approval tasks that were left pending after a completed decision.
-- The repair is intentionally conservative and idempotent:
-- it only updates pending tasks whose approval request / document version are
-- already in a terminal state and whose matching review record proves the
-- decision was recorded.

WITH latest_review AS (
    SELECT
        task.id AS task_id,
        record.status AS repaired_status,
        max(record.created_at) AS repaired_at
    FROM approval_tasks task
    JOIN approval_requests request ON request.id = task.approval_request_id
    JOIN document_versions version ON version.id = task.document_version_id
    JOIN review_records record
        ON record.project_id = task.project_id
        AND record.document_id = task.document_id
        AND record.document_version_id = task.document_version_id
        AND record.review_stage = task.review_stage
    WHERE task.status = 'pending'
      AND (
          (
              record.status = 'approved'
              AND (
                  (task.review_stage = 'manager_review' AND request.status IN ('pending_owner_review', 'approved', 'published') AND version.status IN ('pending_owner_review', 'approved', 'active', 'inactive'))
                  OR (task.review_stage = 'owner_review' AND request.status IN ('approved', 'published') AND version.status IN ('approved', 'active', 'inactive'))
              )
          )
          OR (
              record.status = 'rejected'
              AND request.status = 'rejected'
              AND version.status = 'review_rejected'
          )
      )
    GROUP BY task.id, record.status
)
UPDATE approval_tasks task
SET status = latest_review.repaired_status,
    completed_at = COALESCE(task.completed_at, latest_review.repaired_at),
    lock_version = GREATEST(task.lock_version + 1, 2)
FROM latest_review
WHERE task.id = latest_review.task_id
  AND task.status = 'pending';

UPDATE idempotency_keys key
SET response_summary = jsonb_set(
        jsonb_set(
            jsonb_set(key.response_summary, '{status}', to_jsonb(task.status), false),
            '{lock_version}',
            to_jsonb(task.lock_version),
            false
        ),
        '{completed_at}',
        to_jsonb(task.completed_at),
        false
    )
FROM approval_tasks task
WHERE key.status = 'completed'
  AND key.scope LIKE ('approval.%:' || task.id::text || ':%')
  AND key.response_summary IS NOT NULL
  AND key.response_summary->>'id' = task.id::text
  AND key.response_summary->>'status' = 'pending'
  AND task.status IN ('approved', 'rejected');

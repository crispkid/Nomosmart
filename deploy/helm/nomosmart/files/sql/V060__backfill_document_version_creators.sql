-- CHG-424 D424-11 / OPT424-016: record the creator of every document version
-- that has none, so the document summary no longer derives it from audit_logs.
-- Uses the same rules the summary applied at read time:
--   1. version 1, extraction revision 0, created together with its document:
--      the document's created_by;
--   2. otherwise the actor of the earliest successful creation audit bound to
--      exactly this version (retry/extract actors are excluded).
-- Only versions without a recorded creator (missing, null or empty) are
-- written; each written value is marked version_created_by_source = 'V060'.
-- Rollback:
--   UPDATE public.document_versions
--      SET chunk_strategy = chunk_strategy - 'version_created_by' - 'version_created_by_source'
--    WHERE chunk_strategy->>'version_created_by_source' = 'V060';
--   A version that held an empty string before V060 loses the key on rollback;
--   both states read as "no recorded creator".
UPDATE public.document_versions AS v
   SET chunk_strategy = COALESCE(v.chunk_strategy, '{}'::jsonb)
       || jsonb_build_object('version_created_by', d.created_by::text, 'version_created_by_source', 'V060')
  FROM public.documents AS d
 WHERE d.id = v.document_id
   AND COALESCE(v.chunk_strategy->'version_created_by', 'null'::jsonb) IN ('null'::jsonb, '""'::jsonb)
   AND v.version_major = 1
   AND v.extraction_revision = 0
   AND v.created_at = d.created_at
   AND d.created_by IS NOT NULL;

WITH unrecorded AS (
    SELECT v.id
      FROM public.document_versions AS v
     WHERE COALESCE(v.chunk_strategy->'version_created_by', 'null'::jsonb) IN ('null'::jsonb, '""'::jsonb)
), creation_audits AS (
    SELECT a.id,
           a.created_at,
           a.actor_user_id,
           COALESCE(NULLIF(a.summary->>'version_id', ''),
                    NULLIF(a.summary->>'target_version_id', ''),
                    CASE WHEN a.action = 'document.reextract.queued' THEN a.resource_id::text END) AS version_key
      FROM public.audit_logs AS a
     WHERE a.result = 'success'
       AND a.actor_user_id IS NOT NULL
       AND a.action IN ('document.version.update_file', 'document.reextract.queued', 'document_reference.create',
                        'document_reference.import.copy', 'document_reference.import.reference', 'document_reference.update_version')
       AND (a.summary->>'version_id' IN (SELECT id::text FROM unrecorded)
            OR a.summary->>'target_version_id' IN (SELECT id::text FROM unrecorded)
            OR (a.action = 'document.reextract.queued' AND a.resource_type = 'document_version'
                AND a.resource_id IN (SELECT id FROM unrecorded)))
), earliest AS (
    SELECT DISTINCT ON (u.id) u.id AS version_id, c.actor_user_id
      FROM unrecorded AS u
      JOIN creation_audits AS c ON c.version_key = u.id::text
     ORDER BY u.id, c.created_at, c.id
)
UPDATE public.document_versions AS v
   SET chunk_strategy = COALESCE(v.chunk_strategy, '{}'::jsonb)
       || jsonb_build_object('version_created_by', e.actor_user_id::text, 'version_created_by_source', 'V060')
  FROM earliest AS e
 WHERE v.id = e.version_id;

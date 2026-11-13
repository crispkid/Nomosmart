BEGIN;
-- CHG-412: retain immutable paid-call identity while detachable content is purged.
ALTER TABLE ocr_document_receipts
    ADD COLUMN original_document_id uuid,
    ADD COLUMN original_document_version_id uuid,
    ADD COLUMN original_run_id uuid,
    ADD COLUMN original_step_id uuid,
    ADD COLUMN content_removed_at timestamptz,
    ADD COLUMN content_cleanup_run_id uuid REFERENCES project_archive_runs(id);
UPDATE ocr_document_receipts SET original_document_id = document_id,
    original_document_version_id = document_version_id,
    original_run_id = run_id, original_step_id = step_id;
ALTER TABLE ocr_document_receipts
    ALTER COLUMN original_document_id SET NOT NULL,
    ALTER COLUMN original_document_version_id SET NOT NULL,
    ALTER COLUMN original_run_id SET NOT NULL,
    ALTER COLUMN original_step_id SET NOT NULL,
    ALTER COLUMN document_id DROP NOT NULL,
    ALTER COLUMN document_version_id DROP NOT NULL,
    ALTER COLUMN run_id DROP NOT NULL,
    ALTER COLUMN step_id DROP NOT NULL,
    DROP CONSTRAINT uq_ocr_document_step_attempt,
    DROP CONSTRAINT uq_ocr_document_step_retry,
    ADD CONSTRAINT uq_ocr_document_step_attempt UNIQUE(original_step_id, attempt_id),
    ADD CONSTRAINT uq_ocr_document_step_retry UNIQUE(original_step_id, retry_count),
    ADD CONSTRAINT ck_ocr_document_receipts_ocr_document_live_identity CHECK (
      (document_id IS NULL OR document_id = original_document_id) AND
      (document_version_id IS NULL OR document_version_id = original_document_version_id) AND
      (run_id IS NULL OR run_id = original_run_id) AND
      (step_id IS NULL OR step_id = original_step_id)),
    ADD CONSTRAINT ck_ocr_document_receipts_ocr_document_content_removal CHECK (
      (num_nonnulls(document_id, document_version_id, run_id, step_id) = 4 AND
       content_removed_at IS NULL AND content_cleanup_run_id IS NULL) OR
      (num_nonnulls(document_id, document_version_id, run_id, step_id) = 0 AND
       content_removed_at IS NOT NULL AND content_cleanup_run_id IS NOT NULL AND
       status NOT IN ('intent', 'unknown')));
DROP INDEX uq_ocr_document_active_version;
CREATE UNIQUE INDEX uq_ocr_document_active_version
    ON ocr_document_receipts(original_document_version_id) WHERE status IN ('intent','unknown');
DROP INDEX ix_ocr_document_version_created;
CREATE INDEX ix_ocr_document_version_created ON ocr_document_receipts(original_document_version_id, created_at);

CREATE FUNCTION preserve_ocr_document_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.original_document_id := COALESCE(NEW.original_document_id, NEW.document_id);
        NEW.original_document_version_id := COALESCE(NEW.original_document_version_id, NEW.document_version_id);
        NEW.original_run_id := COALESCE(NEW.original_run_id, NEW.run_id);
        NEW.original_step_id := COALESCE(NEW.original_step_id, NEW.step_id);
    ELSIF ROW(NEW.project_id, NEW.model_id, NEW.original_document_id,
              NEW.original_document_version_id, NEW.original_run_id, NEW.original_step_id,
              NEW.attempt_id, NEW.retry_count, NEW.source_sha256, NEW.request_sha256,
              NEW.snapshot_sha256, NEW.binding_sha256, NEW.dispatch_binding,
              NEW.model_snapshot, NEW.policy_snapshot, NEW.counted_input_tokens, NEW.request_output_limit)
          IS DISTINCT FROM
          ROW(OLD.project_id, OLD.model_id, OLD.original_document_id,
              OLD.original_document_version_id, OLD.original_run_id, OLD.original_step_id,
              OLD.attempt_id, OLD.retry_count, OLD.source_sha256, OLD.request_sha256,
              OLD.snapshot_sha256, OLD.binding_sha256, OLD.dispatch_binding,
              OLD.model_snapshot, OLD.policy_snapshot, OLD.counted_input_tokens, OLD.request_output_limit) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ocr_document_identity_immutable';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.content_removed_at IS NOT NULL AND
       ROW(NEW.document_id,NEW.document_version_id,NEW.run_id,NEW.step_id,
           NEW.content_removed_at,NEW.content_cleanup_run_id)
       IS DISTINCT FROM ROW(OLD.document_id,OLD.document_version_id,OLD.run_id,OLD.step_id,
                            OLD.content_removed_at,OLD.content_cleanup_run_id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ocr_document_content_removal_immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ocr_document_identity_guard BEFORE INSERT OR UPDATE ON ocr_document_receipts
    FOR EACH ROW EXECUTE FUNCTION preserve_ocr_document_identity();

ALTER TABLE file_processing_policies ADD COLUMN schema_version integer NOT NULL DEFAULT 1
    CHECK(schema_version IN (1,2));
ALTER TABLE file_processing_policy_revisions ADD COLUMN schema_version integer NOT NULL DEFAULT 1
    CHECK(schema_version IN (1,2));

-- Local migration helpers match Python's compact, sorted JSON for the strictly
-- validated integer/enum-array policy. They never rewrite historical snapshots.
CREATE FUNCTION pg_temp.nms412_policy_hash(v jsonb) RETURNS text LANGUAGE sql AS $$
 SELECT encode(sha256(convert_to('{' || COALESCE(string_agg(to_json(e.key)::text || ':' ||
   CASE WHEN jsonb_typeof(e.value) = 'array' THEN
     (SELECT '[' || COALESCE(string_agg(a.value::text, ',' ORDER BY a.ordinality), '') || ']'
      FROM jsonb_array_elements(e.value) WITH ORDINALITY a(value, ordinality))
   ELSE e.value::text END, ',' ORDER BY e.key COLLATE "C"), '') || '}', 'UTF8')), 'hex')
 FROM jsonb_each(v) e
$$;
DO $$
DECLARE p record; h record; current_values jsonb; new_values jsonb; new_hash text;
        k text; minimum integer; maximum integer; new_key text; old_key text;
BEGIN
    SELECT * INTO p FROM file_processing_policies WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF; -- No implicit initialization/readiness.
    SELECT * INTO h FROM file_processing_policy_revisions WHERE revision = p.revision;
    IF NOT FOUND OR h.schema_version <> 1 OR p.schema_version <> 1 OR
       jsonb_typeof(h.snapshot) <> 'object' THEN
        RAISE EXCEPTION 'file_processing_policy_revision_mismatch';
    END IF;
    SELECT jsonb_object_agg(key, value) INTO current_values FROM system_parameters WHERE key IN (
        'document_processing_max_concurrent','pdf_parser_max_concurrent','pdf_parser_cpu_millicores',
        'pdf_parser_memory_mib','pdf_parser_scratch_mib','pdf_parser_timeout_seconds','pdf_parser_max_pages',
        'pdf_parser_max_output_mib','pdf_parser_retry_max_attempts','pdf_parser_retry_delay_seconds',
        'pdf_parser_retryable_error_codes','file_processing_progress_interval_seconds',
        'file_processing_background_poll_interval_seconds');
    IF current_values IS DISTINCT FROM h.snapshot OR
       (SELECT count(*) FROM jsonb_object_keys(h.snapshot)) <> 13 OR
       h.content_hash <> p.content_hash OR h.content_hash <> pg_temp.nms412_policy_hash(h.snapshot) THEN
        RAISE EXCEPTION 'file_processing_policy_revision_mismatch';
    END IF;
    FOR k, minimum, maximum IN SELECT * FROM (VALUES
       ('document_processing_max_concurrent',1,10000),('pdf_parser_max_concurrent',1,10000),
       ('pdf_parser_cpu_millicores',100,64000),('pdf_parser_memory_mib',128,262144),
       ('pdf_parser_scratch_mib',16,262144),('pdf_parser_timeout_seconds',10,1800),
       ('pdf_parser_max_pages',1,2000),('pdf_parser_max_output_mib',1,40960),
       ('pdf_parser_retry_max_attempts',1,5),('pdf_parser_retry_delay_seconds',1,3600),
       ('file_processing_progress_interval_seconds',1,60),('file_processing_background_poll_interval_seconds',1,300)
    ) AS bounds(key,minval,maxval) LOOP
        IF jsonb_typeof(h.snapshot->k) <> 'number' OR (h.snapshot->>k) !~ '^[0-9]+$' OR
           (h.snapshot->>k)::numeric NOT BETWEEN minimum AND maximum THEN
            RAISE EXCEPTION 'file_processing_policy_invalid';
        END IF;
    END LOOP;
    IF jsonb_typeof(h.snapshot->'pdf_parser_retryable_error_codes') <> 'array' OR
       EXISTS (SELECT 1 FROM jsonb_array_elements(h.snapshot->'pdf_parser_retryable_error_codes') v
               WHERE v NOT IN ('"parser_capacity_unavailable"'::jsonb,'"parser_start_failed_confirmed_stopped"'::jsonb)) OR
       (h.snapshot->>'file_processing_background_poll_interval_seconds')::int <
       (h.snapshot->>'file_processing_progress_interval_seconds')::int THEN
        RAISE EXCEPTION 'file_processing_policy_invalid';
    END IF;
    -- Match the existing metadata contract before importing any live values.
    IF EXISTS (SELECT 1 FROM system_parameters s JOIN (VALUES
        ('document_processing_max_concurrent','documents'),('pdf_parser_max_concurrent','workloads'),
        ('pdf_parser_cpu_millicores','millicores'),('pdf_parser_memory_mib','MiB'),
        ('pdf_parser_scratch_mib','MiB'),('pdf_parser_timeout_seconds','seconds'),('pdf_parser_max_pages','pages'),
        ('pdf_parser_max_output_mib','MiB'),('pdf_parser_retry_max_attempts','attempts'),
        ('pdf_parser_retry_delay_seconds','seconds'),('pdf_parser_retryable_error_codes',NULL),
        ('file_processing_progress_interval_seconds','seconds'),('file_processing_background_poll_interval_seconds','seconds')
      ) AS metadata(key,unit) ON s.key=metadata.key
      WHERE s.unit IS DISTINCT FROM metadata.unit OR s.value_type IS DISTINCT FROM
        CASE WHEN s.key='pdf_parser_retryable_error_codes' THEN 'array' ELSE 'integer' END) THEN
        RAISE EXCEPTION 'file_processing_parameter_metadata_invalid';
    END IF;
    new_values := jsonb_build_object('document_processing_max_concurrent',h.snapshot->'document_processing_max_concurrent',
        'document_processing_timeout_seconds',h.snapshot->'pdf_parser_timeout_seconds',
        'document_dispatch_yield_delay_seconds',h.snapshot->'pdf_parser_retry_delay_seconds',
        'file_processing_progress_interval_seconds',h.snapshot->'file_processing_progress_interval_seconds',
        'file_processing_background_poll_interval_seconds',h.snapshot->'file_processing_background_poll_interval_seconds');
    FOR new_key, old_key IN SELECT * FROM (VALUES
       ('document_processing_timeout_seconds','pdf_parser_timeout_seconds'),
       ('document_dispatch_yield_delay_seconds','pdf_parser_retry_delay_seconds')) AS aliases(new_key,old_key) LOOP
        IF EXISTS (SELECT 1 FROM system_parameters WHERE key=new_key AND
             (value IS DISTINCT FROM new_values->new_key OR value_type<>'integer' OR unit<>'seconds')) THEN
            RAISE EXCEPTION 'file_processing_alias_conflict';
        END IF;
        INSERT INTO system_parameters(key,value,default_value,value_type,unit,description,updated_by)
          SELECT new_key,new_values->new_key,default_value,'integer','seconds',
                 'CHG-412 document policy; imported existing effective value',updated_by
          FROM system_parameters WHERE key=old_key ON CONFLICT(key) DO NOTHING;
    END LOOP;
    new_hash := pg_temp.nms412_policy_hash(new_values);
    INSERT INTO file_processing_policy_revisions(revision,schema_version,snapshot,content_hash,provenance,created_by,created_at)
      VALUES(p.revision+1,2,new_values,new_hash,jsonb_build_object('operation','V056_import_existing_v1',
          'previous_revision',p.revision,'previous_hash',p.content_hash,'actor_source','previous_revision_owner'),h.created_by,now());
    UPDATE file_processing_policies SET revision=p.revision+1,schema_version=2,content_hash=new_hash,updated_at=now()
      WHERE id=1;
END $$;
COMMIT;

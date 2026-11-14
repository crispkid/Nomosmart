-- CHG-425 FIX425-006: OpenAI Chat and Judge models only use the Responses API.
-- Every non-deleted OpenAI Chat/Judge model whose config.api_mode is not
-- 'responses' (missing, 'chat_completions' or anything else) is switched to
-- 'responses':
--   * config.api_mode_migrated_from keeps the previous value ('unset' when missing);
--   * config_version is incremented and the saved connection-test evidence is
--     cleared, so administrators must test the model again (CONNTEST-001);
--   * one audit_logs row per model (action ai_model.api_mode_migrated) records the
--     previous value and whether base_url/endpoint is the official api.openai.com
--     host. No credential is read or written.
-- Re-running changes nothing: models already on 'responses' are skipped.
-- A NOTICE lists every migrated model and flags non-official hosts, which may be
-- proxies that only speak Chat Completions and must move to the vLLM or Custom provider.
-- Rollback: not required. v0.2.4 also supports api_mode = 'responses'. To restore the
-- previous mode for a specific model:
--   UPDATE public.ai_models
--      SET config = CASE WHEN config->>'api_mode_migrated_from' = 'unset'
--                        THEN config - 'api_mode' - 'api_mode_migrated_from'
--                        ELSE (config - 'api_mode_migrated_from')
--                             || jsonb_build_object('api_mode', config->>'api_mode_migrated_from') END
--    WHERE config ? 'api_mode_migrated_from';
CREATE TEMPORARY TABLE v061_migrated ON COMMIT DROP AS
SELECT m.id,
       m.name,
       COALESCE(NULLIF(m.config->>'api_mode', ''), 'unset') AS previous_mode,
       COALESCE(substring(lower(COALESCE(NULLIF(m.config->>'base_url', ''), m.endpoint, 'https://api.openai.com/v1'))
                          FROM '^https?://([^/:]+)') = 'api.openai.com', false) AS official_host
  FROM public.ai_models AS m
 WHERE m.deleted_at IS NULL
   AND lower(m.provider) = 'openai'
   AND m.model_type IN ('Chat', 'Judge')
   AND COALESCE(m.config->>'api_mode', '') <> 'responses';

UPDATE public.ai_models AS m
   SET config = COALESCE(m.config, '{}'::jsonb)
       || jsonb_build_object('api_mode', 'responses', 'api_mode_migrated_from', v.previous_mode),
       config_version = m.config_version + 1,
       last_test_status = NULL,
       last_tested_at = NULL,
       last_test_fingerprint = NULL,
       last_test_latency_ms = NULL,
       last_test_detail_code = NULL,
       last_test_actor_id = NULL,
       updated_at = now()
  FROM v061_migrated AS v
 WHERE m.id = v.id;

INSERT INTO public.audit_logs (actor_user_id, action, resource_type, resource_id, result, request_id, summary)
SELECT NULL, 'ai_model.api_mode_migrated', 'ai_model', v.id, 'success', NULL,
       jsonb_build_object('migration', 'V061', 'previous_api_mode', v.previous_mode,
                          'api_mode', 'responses', 'official_openai_host', v.official_host,
                          'connection_test_evidence_cleared', true)
  FROM v061_migrated AS v;

DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT id, name, previous_mode, official_host FROM v061_migrated ORDER BY name, id LOOP
        RAISE NOTICE 'V061 migrated OpenAI model % (%) from % to responses%', item.name, item.id, item.previous_mode,
            CASE WHEN item.official_host THEN '' ELSE '; base URL is not api.openai.com, confirm it supports the Responses API or switch to vLLM/Custom' END;
    END LOOP;
END
$$;

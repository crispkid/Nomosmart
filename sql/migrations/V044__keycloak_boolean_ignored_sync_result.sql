BEGIN;

ALTER TABLE identity_sync_provider_results
    ADD COLUMN user_sync_ignored boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN identity_sync_provider_results.user_sync_ignored IS
    'Keycloak 26 SynchronizationResultRepresentation ignored boolean.';

COMMENT ON COLUMN identity_sync_provider_results.users_ignored IS
    'Deprecated compatibility counter; always zero. Use user_sync_ignored.';

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg266.keycloak_boolean_ignored_sync_result',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-266'),
    now()
);

COMMIT;

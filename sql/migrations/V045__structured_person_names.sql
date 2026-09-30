BEGIN;

ALTER TABLE users
    ADD COLUMN given_name varchar(255),
    ADD COLUMN family_name varchar(255);

COMMENT ON COLUMN users.given_name IS
    'Keycloak firstName synchronized as the locale-neutral given name.';

COMMENT ON COLUMN users.family_name IS
    'Keycloak lastName synchronized as the locale-neutral family name.';

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg267.structured_person_names',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-267'),
    now()
);

COMMIT;

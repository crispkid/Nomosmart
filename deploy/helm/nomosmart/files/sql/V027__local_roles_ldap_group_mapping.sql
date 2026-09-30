BEGIN;

ALTER TABLE external_groups
    ADD COLUMN identity_origin varchar(32) NOT NULL DEFAULT 'keycloak_local';

ALTER TABLE external_groups
    ADD CONSTRAINT external_groups_identity_origin_check
    CHECK (identity_origin IN ('ldap', 'ad', 'keycloak_local'));

UPDATE external_groups
SET identity_origin = 'ldap'
WHERE path LIKE '/ldap/%';

ALTER TABLE role_users DROP CONSTRAINT role_users_source_check;
ALTER TABLE role_users ADD CONSTRAINT role_users_source_check
    CHECK (source IN ('manual', 'external_sync', 'break_glass'));

UPDATE roles
SET is_system = (name = 'system-admin'),
    updated_at = now()
WHERE is_system IS DISTINCT FROM (name = 'system-admin');

DO $$
DECLARE
    pristine_install boolean;
BEGIN
    SELECT
        NOT EXISTS (SELECT 1 FROM users)
        AND NOT EXISTS (SELECT 1 FROM projects)
        AND NOT EXISTS (SELECT 1 FROM audit_logs)
        AND NOT EXISTS (SELECT 1 FROM deployment_bootstrap_evidence)
    INTO pristine_install;

    IF pristine_install THEN
        DELETE FROM roles
        WHERE name IN ('project-owner', 'knowledge-editor', 'reviewer');
    END IF;
END $$;

DELETE FROM external_group_role_mappings broad
USING roles role, external_groups broad_group
WHERE broad.role_id = role.id
  AND broad.external_group_id = broad_group.id
  AND role.name = 'system-admin'
  AND lower(broad_group.group_name) = 'users'
  AND coalesce(broad_group.path, '') IN ('/users', 'users', '/ldap/users')
  AND EXISTS (
      SELECT 1
      FROM external_group_role_mappings retained
      JOIN external_groups retained_group ON retained_group.id = retained.external_group_id
      WHERE retained.role_id = role.id
        AND lower(retained_group.group_name) = 'systemadmin'
        AND coalesce(retained_group.path, '') IN ('/systemadmin', 'systemadmin', '/ldap/systemadmin')
  );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM external_group_role_mappings
        GROUP BY role_id
        HAVING count(*) > 1
    ) OR EXISTS (
        SELECT 1
        FROM external_group_role_mappings
        GROUP BY external_group_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'CHG-233 cannot choose among ambiguous external group role mappings';
    END IF;
END $$;

ALTER TABLE external_group_role_mappings
    DROP CONSTRAINT external_group_role_mappings_external_group_id_role_id_key;
ALTER TABLE external_group_role_mappings
    ADD CONSTRAINT uq_external_group_role_mappings_external_group UNIQUE (external_group_id);
ALTER TABLE external_group_role_mappings
    ADD CONSTRAINT uq_external_group_role_mappings_role UNIQUE (role_id);

DELETE FROM role_users WHERE source = 'external_sync';

INSERT INTO role_users (role_id, user_id, source, created_at, updated_at)
SELECT DISTINCT mapping.role_id, membership.user_id, 'external_sync', now(), now()
FROM external_group_role_mappings mapping
JOIN external_groups external_group ON external_group.id = mapping.external_group_id
JOIN roles role ON role.id = mapping.role_id
JOIN external_group_users membership ON membership.external_group_id = mapping.external_group_id
WHERE external_group.is_active = true
  AND external_group.identity_origin = 'ldap'
  AND role.is_active = true
ON CONFLICT (role_id, user_id, source) DO NOTHING;

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg233.local_roles_ldap_mapping',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-233'),
    now()
);

COMMIT;

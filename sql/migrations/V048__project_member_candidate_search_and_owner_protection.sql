BEGIN;

INSERT INTO roles (
    name,
    description,
    is_active,
    is_system,
    lock_version,
    created_at,
    updated_at
)
SELECT
    'knowledge-project-user',
    'View knowledge projects and receive project-scoped roles',
    true,
    false,
    1,
    now(),
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM roles
    WHERE name = 'knowledge-project-user'
      AND deleted_at IS NULL
);

INSERT INTO role_permissions (
    role_id,
    module_name,
    function_name,
    can_view,
    can_create,
    can_edit,
    can_delete,
    can_execute,
    created_at,
    updated_at
)
SELECT
    role.id,
    'Menu',
    'KnowledgeProjects',
    true,
    false,
    false,
    false,
    false,
    now(),
    now()
FROM roles AS role
WHERE role.name = 'knowledge-project-user'
  AND role.is_active = true
  AND role.deleted_at IS NULL
ON CONFLICT (role_id, module_name, function_name)
DO NOTHING;

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
SELECT
    'migration.chg288.project_member_candidate_search_owner_protection',
    'system',
    'success',
    jsonb_build_object(
        'change_id', 'CHG-288',
        'migration', 'V048',
        'base_role', 'knowledge-project-user',
        'users_assigned', 0,
        'groups_mapped', 0
    ),
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_logs
    WHERE action = 'migration.chg288.project_member_candidate_search_owner_protection'
      AND summary ->> 'migration' = 'V048'
);

COMMIT;

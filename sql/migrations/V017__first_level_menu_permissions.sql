BEGIN;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role_id, 'Menu', 'KnowledgeProjects', bool_or(can_view), bool_or(can_create), false, false
FROM role_permissions
WHERE module_name = 'Project' AND function_name = 'ProjectList'
GROUP BY role_id
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = false,
    can_delete = false,
    updated_at = now();

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role_id, 'Menu', 'Reports', bool_or(can_view), false, false, false
FROM role_permissions
WHERE module_name = 'Report' AND function_name = 'Statistics'
GROUP BY role_id
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = EXCLUDED.can_view,
    can_create = false,
    can_edit = false,
    can_delete = false,
    updated_at = now();

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role_id, 'Menu', 'SystemManagement', bool_or(can_view), bool_or(can_create), bool_or(can_edit), bool_or(can_delete)
FROM role_permissions
WHERE module_name = 'System'
GROUP BY role_id
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = EXCLUDED.can_edit,
    can_delete = EXCLUDED.can_delete,
    updated_at = now();

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, permission.can_view, permission.can_create, permission.can_edit, permission.can_delete
FROM roles role
CROSS JOIN (VALUES
    ('Menu', 'KnowledgeProjects', true, true, false, false),
    ('Menu', 'Reports', true, false, false, false),
    ('Menu', 'SystemManagement', true, true, true, true)
) AS permission(module_name, function_name, can_view, can_create, can_edit, can_delete)
WHERE role.name = 'system-admin'
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = EXCLUDED.can_edit,
    can_delete = EXCLUDED.can_delete,
    updated_at = now();

COMMIT;

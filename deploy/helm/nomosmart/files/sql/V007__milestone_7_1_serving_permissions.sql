BEGIN;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, true, true, true, true
FROM roles role
CROSS JOIN (VALUES
    ('Chat', 'ChatVerification'),
    ('Chat', 'ValidationQuestion'),
    ('Chat', 'ValidationRun'),
    ('Notification', 'NotificationCenter')
) AS permission(module_name, function_name)
WHERE role.name = 'system-admin'
ON CONFLICT (role_id, module_name, function_name) DO UPDATE
SET can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = EXCLUDED.can_edit,
    can_delete = EXCLUDED.can_delete;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, permission.can_view, permission.can_create, permission.can_edit, permission.can_delete
FROM roles role
CROSS JOIN (VALUES
    ('Knowledge', 'KnowledgeGraph', true, false, false, false),
    ('Chat', 'ChatVerification', true, false, false, false),
    ('Notification', 'NotificationCenter', true, false, true, false)
) AS permission(module_name, function_name, can_view, can_create, can_edit, can_delete)
WHERE role.name = 'project-owner'
ON CONFLICT (role_id, module_name, function_name) DO UPDATE
SET can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = EXCLUDED.can_edit,
    can_delete = EXCLUDED.can_delete;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, permission.can_view, permission.can_create, permission.can_edit, permission.can_delete
FROM roles role
CROSS JOIN (VALUES
    ('Knowledge', 'KnowledgeGraph', true, false, false, false),
    ('Chat', 'ChatVerification', true, false, false, false),
    ('Notification', 'NotificationCenter', true, false, true, false)
) AS permission(module_name, function_name, can_view, can_create, can_edit, can_delete)
WHERE role.name IN ('knowledge-editor', 'reviewer')
ON CONFLICT (role_id, module_name, function_name) DO UPDATE
SET can_view = EXCLUDED.can_view,
    can_create = EXCLUDED.can_create,
    can_edit = EXCLUDED.can_edit,
    can_delete = EXCLUDED.can_delete;

COMMIT;

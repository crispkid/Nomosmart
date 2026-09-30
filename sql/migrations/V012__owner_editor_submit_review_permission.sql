BEGIN;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, 'Document', 'DocumentReview', true, true, true, false
FROM roles role
WHERE role.name = 'project-owner'
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = true,
    can_create = true,
    can_edit = true,
    can_delete = false;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, 'Document', 'DocumentReview', true, true, true, false
FROM roles role
WHERE role.name = 'knowledge-editor'
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = true,
    can_create = true,
    can_edit = true,
    can_delete = false;

COMMIT;

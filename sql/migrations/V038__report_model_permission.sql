INSERT INTO role_permissions (
    role_id,
    module_name,
    function_name,
    can_view,
    can_create,
    can_edit,
    can_delete,
    can_execute
)
SELECT
    role.id,
    'Report',
    'ModelReport',
    role.name = 'system-admin',
    false,
    false,
    false,
    false
FROM roles AS role
WHERE role.deleted_at IS NULL
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_view = EXCLUDED.can_view,
    can_create = false,
    can_edit = false,
    can_delete = false,
    can_execute = false,
    updated_at = now();

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg247.report_model_permission',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-247', 'default_role', 'system-admin'),
    now()
);

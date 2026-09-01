BEGIN;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, true, true, true, true
FROM roles role
CROSS JOIN (VALUES
    ('System', 'UserManagement'), ('System', 'RoleManagement'), ('System', 'PermissionSettings'), ('System', 'AIModelSettings'), ('System', 'SystemLogs'),
    ('Project', 'ProjectList'), ('Project', 'ProjectSettings'), ('Project', 'ProjectMembers'), ('Project', 'EmbeddingSettings'),
    ('Document', 'DocumentImport'), ('Document', 'DocumentVersion'), ('Document', 'DocumentActivation'), ('Document', 'DocumentReview'),
    ('Knowledge', 'KnowledgeExtraction'), ('Knowledge', 'ChunkEditing'), ('Knowledge', 'TagManagement'), ('Knowledge', 'KnowledgeGraph'),
    ('Review', 'ApprovalWorkspace'), ('Review', 'ApprovalDetail')
) AS permission(module_name, function_name)
WHERE role.name = 'system-admin'
ON CONFLICT (role_id, module_name, function_name) DO NOTHING;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, permission.can_view, permission.can_create, permission.can_edit, permission.can_delete
FROM roles role
CROSS JOIN (VALUES
    ('Project', 'ProjectList', true, false, true, false),
    ('Project', 'ProjectSettings', true, false, true, false),
    ('Project', 'ProjectMembers', true, true, true, true),
    ('Document', 'DocumentReview', true, false, true, false),
    ('Review', 'ApprovalWorkspace', true, false, true, false),
    ('Review', 'ApprovalDetail', true, false, true, false)
) AS permission(module_name, function_name, can_view, can_create, can_edit, can_delete)
WHERE role.name = 'project-owner'
ON CONFLICT (role_id, module_name, function_name) DO NOTHING;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, true, true, true, false
FROM roles role
CROSS JOIN (VALUES
    ('Project', 'ProjectList'), ('Document', 'DocumentImport'), ('Document', 'DocumentVersion'),
    ('Knowledge', 'KnowledgeExtraction'), ('Knowledge', 'ChunkEditing'), ('Knowledge', 'TagManagement')
) AS permission(module_name, function_name)
WHERE role.name = 'knowledge-editor'
ON CONFLICT (role_id, module_name, function_name) DO NOTHING;

INSERT INTO role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete)
SELECT role.id, permission.module_name, permission.function_name, true, false, true, false
FROM roles role
CROSS JOIN (VALUES ('Review', 'ApprovalWorkspace'), ('Review', 'ApprovalDetail')) AS permission(module_name, function_name)
WHERE role.name = 'reviewer'
ON CONFLICT (role_id, module_name, function_name) DO NOTHING;

COMMIT;

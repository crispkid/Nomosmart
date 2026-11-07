BEGIN;

ALTER TABLE role_permissions
    ADD COLUMN can_execute boolean NOT NULL DEFAULT false;

CREATE INDEX ix_projects_status_updated
    ON projects (status, updated_at DESC, id);

CREATE INDEX ix_project_members_user_role_project
    ON project_members (user_id, project_role, project_id);

CREATE INDEX ix_documents_project_visible
    ON documents (project_id, updated_at DESC, id)
    WHERE is_deleted = false;

CREATE INDEX ix_document_versions_project_published
    ON document_versions (project_id, updated_at DESC, id)
    WHERE published_at IS NOT NULL;

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
SELECT role.id, 'Project', 'ProjectArchive', false, false, false, false, true
FROM roles AS role
WHERE role.name = 'system-admin'
  AND role.is_active = true
  AND role.deleted_at IS NULL
ON CONFLICT (role_id, module_name, function_name)
DO UPDATE SET
    can_execute = true,
    updated_at = now();

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg241.project_archive_execute_permission',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-241'),
    now()
);

COMMIT;

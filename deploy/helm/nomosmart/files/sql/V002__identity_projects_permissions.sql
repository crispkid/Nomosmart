BEGIN;

ALTER TABLE users
    ADD COLUMN knowledge_owner boolean NOT NULL DEFAULT false,
    ADD COLUMN system_notes text;

ALTER TABLE roles
    ADD COLUMN lock_version integer NOT NULL DEFAULT 1;

ALTER TABLE role_users DROP CONSTRAINT role_users_pkey;
ALTER TABLE role_users ADD PRIMARY KEY (role_id, user_id, source);
ALTER TABLE role_users ADD CONSTRAINT role_users_source_check
    CHECK (source IN ('manual', 'external_sync'));

CREATE TABLE external_group_users (
    external_group_id uuid NOT NULL REFERENCES external_groups(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (external_group_id, user_id)
);

ALTER TABLE identity_sync_runs
    ADD COLUMN trigger_type varchar(32) NOT NULL DEFAULT 'manual',
    ADD COLUMN error_code varchar(100),
    ADD COLUMN attempt integer NOT NULL DEFAULT 0;

DELETE FROM project_members contributor
USING project_members maintainer
WHERE contributor.project_id = maintainer.project_id
  AND contributor.user_id = maintainer.user_id
  AND contributor.project_role = 'contributor'
  AND maintainer.project_role = 'maintainer';

ALTER TABLE project_members DROP CONSTRAINT project_members_project_role_check;
UPDATE project_members SET project_role = 'editor'
WHERE project_role IN ('maintainer', 'contributor');
ALTER TABLE project_members ADD CONSTRAINT project_members_project_role_check
    CHECK (project_role IN ('owner', 'editor', 'viewer'));

COMMIT;

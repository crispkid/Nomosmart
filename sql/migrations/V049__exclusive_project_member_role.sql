BEGIN;

-- CHG-291 precedence: owner > editor > viewer.
-- Lock all membership/governance writers while the invariant is normalized.
LOCK TABLE projects, project_members, project_owners IN SHARE ROW EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM projects AS project
        WHERE NOT EXISTS (
            SELECT 1
            FROM project_owners AS owner_row
            WHERE owner_row.project_id = project.id
        )
          AND NOT EXISTS (
            SELECT 1
            FROM project_members AS member
            WHERE member.project_id = project.id
              AND member.project_role = 'owner'
        )
    ) THEN
        RAISE EXCEPTION 'project_without_owner: every project must retain a provable Owner before CHG-291 normalization';
    END IF;
END
$$;

-- Either existing side is sufficient evidence to repair the already-required
-- bidirectional Owner relationship; no unrelated user is promoted.
INSERT INTO project_members (project_id, user_id, project_role, created_at)
SELECT owner_row.project_id, owner_row.user_id, 'owner', owner_row.created_at
FROM project_owners AS owner_row
WHERE NOT EXISTS (
    SELECT 1
    FROM project_members AS member
    WHERE member.project_id = owner_row.project_id
      AND member.user_id = owner_row.user_id
      AND member.project_role = 'owner'
)
ON CONFLICT (project_id, user_id, project_role) DO NOTHING;

INSERT INTO project_owners (project_id, user_id, created_at)
SELECT member.project_id, member.user_id, member.created_at
FROM project_members AS member
WHERE member.project_role = 'owner'
ON CONFLICT (project_id, user_id) DO NOTHING;

DELETE FROM project_members AS lower_role
USING project_members AS higher_role
WHERE lower_role.project_id = higher_role.project_id
  AND lower_role.user_id = higher_role.user_id
  AND (
      (higher_role.project_role = 'owner' AND lower_role.project_role IN ('editor', 'viewer'))
      OR (higher_role.project_role = 'editor' AND lower_role.project_role = 'viewer')
  );

DO $$
BEGIN
    IF EXISTS (
        SELECT project_id, user_id
        FROM project_members
        GROUP BY project_id, user_id
        HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION 'project_member_role_cardinality: CHG-291 normalization did not produce exactly one role';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM project_owners AS owner_row
        WHERE NOT EXISTS (
            SELECT 1
            FROM project_members AS member
            WHERE member.project_id = owner_row.project_id
              AND member.user_id = owner_row.user_id
              AND member.project_role = 'owner'
        )
    ) OR EXISTS (
        SELECT 1
        FROM project_members AS member
        WHERE member.project_role = 'owner'
          AND NOT EXISTS (
              SELECT 1
              FROM project_owners AS owner_row
              WHERE owner_row.project_id = member.project_id
                AND owner_row.user_id = member.user_id
          )
    ) THEN
        RAISE EXCEPTION 'project_owner_membership_mismatch: CHG-291 Owner parity check failed';
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_project_members_project_user'
          AND conrelid = 'project_members'::regclass
    ) THEN
        ALTER TABLE project_members
            ADD CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id);
    END IF;
END
$$;

COMMENT ON CONSTRAINT uq_project_members_project_user ON project_members IS
    'CHG-291: a user has exactly one Owner, Editor, or Viewer role per project';

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
SELECT
    'migration.chg291.exclusive_project_member_role',
    'system',
    'success',
    jsonb_build_object(
        'change_id', 'CHG-291',
        'migration', 'V049',
        'precedence', 'owner > editor > viewer'
    ),
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_logs
    WHERE action = 'migration.chg291.exclusive_project_member_role'
      AND summary ->> 'migration' = 'V049'
);

COMMIT;

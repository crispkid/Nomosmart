-- Discussion inventory only: SELECT under a READ ONLY transaction.
-- No migration, data repair, backup, temp table, explicit table lock or DDL.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

WITH pairs AS (
    SELECT project_id, user_id FROM project_members
    UNION
    SELECT project_id, user_id FROM project_owners
), members AS (
    SELECT p.id AS project_id, p.name AS project_name, p.status AS project_status,
           u.id AS user_id, u.display_name, u.email, u.is_active AS user_active,
           ARRAY(SELECT m.project_role FROM project_members m
                 WHERE m.project_id = pair.project_id AND m.user_id = pair.user_id
                 ORDER BY m.project_role) AS current_roles,
           EXISTS (SELECT 1 FROM project_owners o WHERE o.project_id = pair.project_id
                   AND o.user_id = pair.user_id) AS owner_governance,
           EXISTS (SELECT 1 FROM project_members m WHERE m.project_id = pair.project_id
                   AND m.user_id = pair.user_id AND m.project_role = 'owner') AS owner_membership
    FROM pairs pair
    JOIN projects p ON p.id = pair.project_id
    JOIN users u ON u.id = pair.user_id
), proposed AS (
    SELECT *, CASE WHEN owner_governance OR owner_membership THEN 'owner'
                   WHEN 'editor' = ANY(current_roles) THEN 'editor'
                   WHEN 'viewer' = ANY(current_roles) THEN 'viewer'
                   ELSE NULL END AS proposed_role
    FROM members
)
SELECT jsonb_build_object(
    'capturedAt', statement_timestamp(),
    'database', current_database(),
    'transactionReadOnly', current_setting('transaction_read_only'),
    'transactionIsolation', current_setting('transaction_isolation'),
    'flywayLatest', (SELECT jsonb_build_object('version', version, 'success', success)
                     FROM flyway_schema_history WHERE version IS NOT NULL
                     ORDER BY installed_rank DESC LIMIT 1),
    'v049HistoryCount', (SELECT count(*) FROM flyway_schema_history WHERE version IN ('049', '49')),
    'v049AuditCount', (SELECT count(*) FROM audit_logs
                       WHERE action = 'migration.chg291.exclusive_project_member_role'
                         AND summary ->> 'migration' = 'V049'),
    'memberConstraints', (SELECT coalesce(jsonb_agg(jsonb_build_object('name', conname,
                            'definition', pg_get_constraintdef(oid)) ORDER BY conname), '[]'::jsonb)
                          FROM pg_constraint WHERE conrelid = 'project_members'::regclass),
    'projectCount', (SELECT count(*) FROM projects),
    'membershipRows', (SELECT count(*) FROM project_members),
    'ownerRows', (SELECT count(*) FROM project_owners),
    'duplicatePairs', (SELECT count(*) FROM (SELECT project_id, user_id FROM project_members
                       GROUP BY project_id, user_id HAVING count(*) > 1) d),
    'ownerMismatchPairs', (SELECT count(*) FROM proposed WHERE owner_governance <> owner_membership),
    'projectsWithoutProvableOwner', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', p.id,
                                        'name', p.name, 'status', p.status) ORDER BY p.id), '[]'::jsonb)
        FROM projects p WHERE NOT EXISTS (SELECT 1 FROM proposed r
                          WHERE r.project_id = p.id AND r.proposed_role = 'owner')),
    'inactiveOwnerPairs', (SELECT count(*) FROM proposed WHERE proposed_role = 'owner' AND NOT user_active),
    'invalidRoleRows', (SELECT count(*) FROM project_members WHERE project_role NOT IN ('owner', 'editor', 'viewer')),
    'proposedOwnerMembershipInserts', (SELECT count(*) FROM proposed WHERE owner_governance AND NOT owner_membership),
    'proposedOwnerGovernanceInserts', (SELECT count(*) FROM proposed WHERE owner_membership AND NOT owner_governance),
    'proposedLowerRoleDeletes', (SELECT count(*) FROM project_members m JOIN proposed p
        ON p.project_id = m.project_id AND p.user_id = m.user_id
        WHERE (p.proposed_role = 'owner' AND m.project_role IN ('editor', 'viewer'))
           OR (p.proposed_role = 'editor' AND m.project_role = 'viewer')),
    'memberPairCount', (SELECT count(*) FROM proposed),
    'members', (SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.project_name, p.email, p.user_id), '[]'::jsonb)
                FROM (SELECT * FROM proposed ORDER BY project_name, email, user_id LIMIT 200) p)
);
COMMIT;

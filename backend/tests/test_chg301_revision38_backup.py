"""CHG-301 diagnostic qualification using real isolated PostgreSQL only.

No current Kubernetes/DB, old archive, fake services or credentials are used.
The original suite owns the shared fixture and full-tool qualification gates.
"""
from __future__ import annotations

import json
import secrets

import pytest

from test_chg291_v049_live_backup import (  # shared real owned service, not a double
    artifacts, backup, populated, private_test_directory, r5_source,
)


@pytest.fixture(scope="module")
def pg(artifacts):
    lab = backup.MemoryPostgres(private_test_directory(artifacts, "chg301_shared"))
    try:
        lab.start()
        yield lab
    finally:
        lab.cleanup()


def evidence(pg, db):
    command = lambda tool, *args: pg.command(tool, db, *args)
    with backup.Snapshot(command("psql", *backup.PSQL)) as snapshot:
        state = backup.DatabaseState.collect(snapshot, command)
        catalog = backup.SchemaEvidence.collect(snapshot)
    return state, catalog


@pytest.mark.parametrize("category,sql", [
    ("schema", "COMMENT ON TABLE test.items IS 'sensitive diagnostic marker'"),
    ("rows", "UPDATE test.items SET body='sensitive diagnostic marker' WHERE id=1"),
    ("sequences", "SELECT nextval('test.items_id_seq')"),
    ("properties", "REVOKE TEMPORARY ON DATABASE {db} FROM PUBLIC"),
    ("owner_acl", "REVOKE SELECT ON test.items FROM {reader}"),
    ("large_objects", "SELECT lo_put(123456,0,convert_to('sensitive diagnostic marker','UTF8'))"),
])
def test_six_real_difference_categories(pg, category, sql):
    db = populated(pg)
    reader = "diagnostic_reader_" + secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {reader} NOLOGIN; GRANT SELECT ON test.items TO {reader}")
    before, original = evidence(pg, db)
    equal = backup.state_diagnostics(before, before, original, original)
    assert equal["full_comparison_pass"]
    assert all(value["equal"] for value in equal["categories"].values())
    pg.sql(db, sql.format(db=db, reader=reader))
    after, current = evidence(pg, db)
    report = backup.state_diagnostics(before, after, original, current)
    assert not report["full_comparison_pass"]
    assert not report["categories"][category]["equal"]
    assert set(report["categories"]) == {"schema", "rows", "sequences", "properties", "owner_acl", "large_objects"}
    encoded = json.dumps(report)
    assert "sensitive diagnostic marker" not in encoded
    assert "test.items" not in encoded and reader not in encoded
    for entry in report["categories"].values():
        assert len(entry["expected_sha256"]) == len(entry["actual_sha256"]) == 64
    with pytest.raises(backup.BackupError, match="member_comments_state_differs"):
        backup.ExtensionMemberComments.precheck({}, {}, original, current, before, after)


def test_category_shape_is_fail_closed():
    with pytest.raises(backup.BackupError, match="snapshot_categories_invalid"):
        backup.state_diagnostics({}, {}, {}, {})


@pytest.mark.parametrize("variant", ["foreign_keys", "dropped_columns", "default_acl"])
def test_mixed_owner_structures_fresh_roundtrip(artifacts, pg, variant):
    pg.cleanup()  # Retire this module's own synthetic source before fresh pairs.
    directory = private_test_directory(artifacts, "chg301_" + variant)
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="chg301_initial")
    archive = None
    try:
        source.start()
        db, owner = r5_source(source, populated_data=True)
        source.sql(db, "COMMENT ON FUNCTION digest(text,text) IS 'synthetic extension comment'")
        if variant == "foreign_keys":
            source.sql(db, "CREATE TABLE test.children(id int PRIMARY KEY, parent bigint REFERENCES test.items(id)); "
                "INSERT INTO test.children VALUES (1,1); CREATE INDEX child_parent_idx ON test.children(parent); "
                "ALTER TABLE test.children ADD CONSTRAINT unique_parent UNIQUE(parent)")
        elif variant == "dropped_columns":
            source.sql(db, "ALTER TABLE test.items ADD COLUMN abandoned text; "
                "ALTER TABLE test.items ADD COLUMN retained text; ALTER TABLE test.items DROP COLUMN abandoned; "
                "UPDATE test.items SET retained='synthetic retained'")
        else:
            source.sql(db, f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT ON TABLES TO PUBLIC")
        archive, state = backup.export_synthetic_database(source, db, directory,
            mixed_identity=True, member_comments=True)
    finally:
        source.cleanup()
    try:
        result = backup.restore_isolated(archive, state, private_test_directory(directory, "restore"),
            mixed_identity=True, member_comments=True)
        assert result["full_comparison"]
        report = backup.read_private_json(next(directory.glob("member-comments-replay-*.json")))
        assert "state_diagnostics" in report and report["status"] == "PASS"
    finally:
        if archive:
            archive.close()

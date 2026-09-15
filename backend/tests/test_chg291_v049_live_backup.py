"""Real process/PostgreSQL tests; human GPG cases require an actual Terminal.

No fake database, forged migration history, mock process or precomputed success.
Use --self-test for complete interactive qualification. The automated subset is
not a completed encrypted backup or whole application coverage result.
"""
from __future__ import annotations

import hashlib
import difflib
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import runpy
import secrets
import subprocess
import ssl
import sys
import tempfile
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/chg291_v049_live_backup.py"
spec = importlib.util.spec_from_file_location("chg291_v049_live_backup", SCRIPT)
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


@pytest.fixture(scope="module")
def artifacts():
    configured = os.environ.get("V49_BACKUP_ARTIFACTS")
    path = Path(configured) if configured else Path(tempfile.mkdtemp(prefix="v049-backup-test-", dir="/private/tmp"))
    backup.require(path.parent == Path("/private/tmp") and path.name.startswith("v049-backup-"), "artifact_path_invalid")
    backup.secure_directory(path)
    print("Backup qualification artifacts:", path)
    return path


@pytest.fixture(scope="module")
def pg(artifacts):
    lab = backup.MemoryPostgres(artifacts)
    source_hash = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    try:
        lab.start()
        yield lab
    finally:
        if (artifacts / "container-receipt.json").exists():
            backup.recover_test_resources(artifacts)
        else:
            lab.cleanup()
        assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == source_hash
        backup.private_json(artifacts / "cleanup.json", {"cleanup_ok": True, "baseline_equal": True,
            "image": backup.PG_IMAGE, "source_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            "kubernetes_access": False, "provider_calls": 0, "live_data": False})


def database(pg, suffix):
    name = "v49b_" + suffix + "_" + secrets.token_hex(4)
    pg.create_db(name)
    return name


def populated(pg):
    name = database(pg, "source")
    pg.sql(name, """
        CREATE SCHEMA test;
        CREATE TABLE test.items(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            body text NOT NULL, metadata jsonb, raw bytea);
        INSERT INTO test.items(body,metadata,raw) VALUES
            ('合成資料，不是使用者文件','{"x":[1,2],"q":"測試"}',decode('0001ff','hex')),
            ('a quoted '' value',NULL,NULL);
        COMMENT ON TABLE test.items IS 'backup qualification only';
        CREATE INDEX body_idx ON test.items(body);
        CREATE VIEW test.item_names AS SELECT body FROM test.items;
        SELECT lo_from_bytea(123456,convert_to('synthetic large object','UTF8'));
    """)
    return name


def content(pg, db):
    # Canonical server-side evidence; no sensitive rows are logged.
    sql = """SELECT json_build_object(
        'data',(SELECT md5(string_agg(to_jsonb(t)::text,'' ORDER BY id)) FROM test.items t),
        'rows',(SELECT count(*) FROM test.items),
        'comment',obj_description('test.items'::regclass),
        'sequence',(SELECT row_to_json(s) FROM (SELECT last_value,is_called FROM test.items_id_seq) s),
        'blob',encode(sha256(lo_get(123456)),'hex'),
        'constraints',(SELECT json_agg(pg_get_constraintdef(oid) ORDER BY conname)
            FROM pg_constraint WHERE conrelid='test.items'::regclass))"""
    # This helper only queries the fixed synthetic test.items schema, never live
    # content; expose its SQL diagnostic so qualification defects are actionable.
    result = subprocess.run(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"),
        input=sql.encode(), capture_output=True, env=backup.clean_env(), timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def test_network_none_tmpfs_and_resource_limits(pg):
    pg.guard()
    info = pg.inspect()
    assert all(m["Type"] == "tmpfs" for m in info["Mounts"])
    assert info["HostConfig"]["LogConfig"]["Type"] == "none"


def test_private_paths_reject_symlinks_and_overwrite(artifacts):
    child = artifacts / "private"
    child.mkdir(mode=0o700)
    assert backup.secure_directory(child) == child
    link = artifacts / "linked"
    link.symlink_to(child)
    with pytest.raises(backup.BackupError, match="symlink"):
        backup.secure_directory(link)
    link.unlink()
    target = child / "receipt.json"
    backup.private_json(target, {"synthetic": True})
    with pytest.raises(FileExistsError):
        backup.private_json(target, {"synthetic": False})
    assert json.loads(target.read_text()) == {"synthetic": True}
    child.chmod(0o755)
    with pytest.raises(backup.BackupError, match="private"):
        backup.secure_directory(child)
    child.chmod(0o700)


def test_snapshot_is_readonly_and_consistent(pg):
    db = populated(pg)
    with backup.Snapshot(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1")) as snap:
        assert snap.query("SHOW transaction_read_only") == ["on"]
        assert snap.value("SELECT count(*) FROM test.items") == 2
        pg.sql(db, "INSERT INTO test.items(body) VALUES('concurrent synthetic write')")
        assert snap.value("SELECT count(*) FROM test.items") == 2
        with backup.Snapshot(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1")) as second:
            assert second.value("SELECT count(*) FROM test.items") == 3
    with backup.Snapshot(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1")) as snap:
        with pytest.raises(backup.BackupError, match="snapshot_query_failed"):
            snap.query("DELETE FROM test.items")
    assert pg.sql(db, "SELECT count(*) FROM test.items").strip() == b"3"


def test_real_dump_restore_snapshot_and_full_synthetic_objects(pg):
    db = populated(pg)
    target = database(pg, "restore")
    with backup.Snapshot(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1")) as snap:
        before = content(pg, db)
        pg.sql(db, "INSERT INTO test.items(body) VALUES('not in exported snapshot')")
        outcome = backup.pipeline(pg.command("pg_dump", db, "--format=custom", "--lock-wait-timeout=2s",
            "--snapshot="+snap.snapshot), pg.empty_restore(target))
        assert outcome["all_exits_zero"] and outcome["bytes"] > 0
    # The non-transactional sequence advanced despite the exported snapshot.
    actual = json.loads(content(pg, target))
    expected = json.loads(before)
    assert actual["sequence"]["last_value"] != expected["sequence"]["last_value"]
    actual.pop("sequence"); expected.pop("sequence")
    assert actual == expected
    assert pg.sql(db, "SELECT count(*) FROM test.items").strip() == b"3"
    with pytest.raises(backup.BackupError, match="restore_target_not_empty"):
        pg.empty_restore(target)


@pytest.mark.parametrize("side", ["producer", "consumer"])
def test_pipeline_checks_both_exit_codes(side):
    source = [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*10000);sys.exit("+ ("3" if side=="producer" else "0")+")"]
    target = [sys.executable, "-c", "import sys;sys.stdin.buffer.read();sys.exit("+("4" if side=="consumer" else "0")+")"]
    with pytest.raises(backup.BackupError):
        backup.pipeline(source, target, seconds=3)


def test_pipeline_limits_and_timeout():
    sink = [sys.executable, "-c", "import sys;sys.stdin.buffer.read()"]
    with pytest.raises(backup.BackupError, match="stream_too_large"):
        backup.pipeline([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'a'*4096)"], sink, limit=128)
    started = time.monotonic()
    with pytest.raises(backup.BackupError, match="pipeline_timeout"):
        backup.pipeline([sys.executable, "-c", "import time;time.sleep(60)"], sink, seconds=0.5)
    assert time.monotonic() - started < 8
    with pytest.raises(backup.BackupError, match="empty_stream"):
        backup.pipeline([sys.executable, "-c", "pass"], sink)
    with pytest.raises(backup.BackupError, match="invalid_pipeline_limit"):
        backup.pipeline(sink, sink, limit=backup.MAX_STREAM+1)


def test_child_timeout_and_identifier_validation():
    with pytest.raises(backup.BackupError, match="child_timeout"):
        backup.run([sys.executable, "-c", "import time;time.sleep(60)"], timeout=0.2)
    assert backup.quote_ident('a"b') == '"a""b"'
    with pytest.raises(backup.BackupError, match="invalid_identifier"):
        backup.quote_ident("bad\x00identifier")


def test_pipeline_cleans_sigterm_resistant_child():
    source = [sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"]
    sink = [sys.executable, "-c", "import sys;sys.stdin.buffer.read()"]
    started = time.monotonic()
    with pytest.raises(backup.BackupError, match="pipeline_timeout"):
        backup.pipeline(source, sink, seconds=0.5)
    assert time.monotonic() - started < 9


def test_snapshot_handles_actual_psql_failure(pg):
    db = database(pg, "bad_psql")
    with pytest.raises(backup.BackupError, match="snapshot_query_failed"):
        backup.Snapshot(pg.command("psql", db, "--invalid-qualification-option"))


def test_snapshot_rejects_bad_shapes_and_sql(pg):
    db = database(pg, "shape")
    with backup.Snapshot(pg.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1")) as snap:
        with pytest.raises(backup.BackupError, match="metadata_shape_invalid"):
            snap.value("SELECT generate_series(1,2)")
        assert snap.value("SELECT 1") == 1
    with pytest.raises(backup.BackupError, match="unsupported_pg_tool"):
        pg.command("arbitrary", db)


def test_cleanup_rejects_forged_receipt(artifacts):
    folder = artifacts / "bad_receipt"
    folder.mkdir(mode=0o700)
    backup.private_json(folder / "container-receipt.json", {"label": "wrong", "image": "wrong"})
    with pytest.raises(backup.BackupError, match="receipt_invalid"):
        backup.recover_test_resources(folder)


@pytest.mark.parametrize("name", ["nomosmart", "postgres", "v49b_x;DROP DATABASE x", "../v49b_x"])
def test_reject_unowned_database(pg, name):
    with pytest.raises(backup.BackupError, match="database_not_owned"):
        pg.command("pg_restore", name)


def test_sql_error_does_not_expose_source_text(pg):
    db = database(pg, "error")
    with pytest.raises(backup.BackupError) as failure:
        pg.sql(db, "SELECT 'synthetic-sensitive-marker'::integer")
    assert "synthetic-sensitive-marker" not in str(failure.value)


def test_human_gpg_roundtrip_truncation_and_cancellation(pg, artifacts):
    # Missing human TTY is a genuine blocker, not skip/xfail or fake encryption.
    gpg = backup.HumanGPG(artifacts)
    db = populated(pg)
    encrypted = artifacts / "synthetic.partial.gpg"
    try:
        print("\n[1/4] 請在 Pinentry 設定本次合成資料測試密碼。", flush=True)
        backup.pipeline(pg.command("pg_dump", db, "--format=custom"), gpg.encrypt(encrypted), interactive=True)
        encrypted.chmod(0o600)
        before = content(pg, db)
        target = database(pg, "crypto")
        print("\n[2/4] 請再次輸入相同測試密碼，驗證解密還原。", flush=True)
        backup.pipeline(gpg.decrypt(encrypted), pg.empty_restore(target), interactive=True)
        assert content(pg, target) == before
        broken = artifacts / "synthetic-truncated.partial.gpg"
        with broken.open("xb") as stream:
            broken.chmod(0o600)
            stream.write(encrypted.read_bytes()[:-32])
        target2 = database(pg, "broken")
        print("\n[3/4] 請輸入相同測試密碼；這次密文故意截斷，必須被判定失敗。", flush=True)
        with pytest.raises(backup.BackupError):
            backup.pipeline(gpg.decrypt(broken), pg.empty_restore(target2), interactive=True)
        print("\n[4/4] 下一個 Pinentry 請按「取消」，測試取消是否正確停止。", flush=True)
        with pytest.raises(backup.BackupError):
            backup.pipeline(pg.command("pg_dump", db, "--format=custom"),
                gpg.encrypt(artifacts / "synthetic-cancelled.partial.gpg"), interactive=True)
        backup.private_json(artifacts / "human-gpg.json", {"roundtrip": True, "truncation_rejected": True,
            "cancellation_rejected": True, "ciphertext_sha256": hashlib.sha256(encrypted.read_bytes()).hexdigest(),
            "live_data": False, "no_password_in_agent": True})
    finally:
        gpg.close()


def private_test_directory(artifacts, name):
    path = artifacts / (name + "_" + secrets.token_hex(4))
    path.mkdir(mode=0o700)
    return path


def test_plain_full_database_roundtrip(pg, artifacts):
    db = populated(pg)
    role = "owner_" + secrets.token_hex(4)
    reader = "reader_" + secrets.token_hex(4)
    # Genuine additional objects and privileges, not a forged success snapshot.
    pg.sql(db, f"CREATE ROLE {role} NOLOGIN; CREATE ROLE {reader} NOLOGIN; "
        f"ALTER DATABASE {db} OWNER TO {role}; ALTER TABLE test.items OWNER TO {role}; "
        f"GRANT SELECT ON test.items TO {reader}; GRANT CONNECT ON DATABASE {db} TO {reader}; "
        "CREATE TABLE test.parent (id int, body text); CREATE TABLE test.child () INHERITS (test.parent); "
        "INSERT INTO test.parent VALUES (1,'parent'); INSERT INTO test.child VALUES (2,'child'); "
        "CREATE TABLE test.parts (id int, body text) PARTITION BY RANGE(id); "
        "CREATE TABLE test.part1 PARTITION OF test.parts FOR VALUES FROM (0) TO (10); "
        "INSERT INTO test.parts VALUES (1,'partition'); "
        "CREATE MATERIALIZED VIEW test.material AS SELECT * FROM test.items; "
        "CREATE TYPE test.status AS ENUM ('one','two'); "
        "CREATE TABLE test.special (s test.status, j json, n numeric, a text[]); "
        "INSERT INTO test.special VALUES ('one','{ \"x\" : 2 }',1.001,ARRAY['a','b']); "
        "CREATE FUNCTION test.answer() RETURNS integer LANGUAGE sql AS $$ SELECT 42 $$; "
        "COMMENT ON FUNCTION test.answer() IS 'synthetic function'; "
        "COMMENT ON LARGE OBJECT 123456 IS 'synthetic object'; "
        f"GRANT SELECT ON LARGE OBJECT 123456 TO {reader}")
    command = lambda tool, *args: pg.command(tool, db, *args)
    directory = private_test_directory(artifacts, "plain_roundtrip")
    archive = backup.PlainArchive(directory)
    try:
        with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
            state = backup.DatabaseState.collect(snap, command)
            initial = archive.export(command("pg_dump", "--format=custom", "--lock-wait-timeout=2s",
                "--snapshot="+snap.snapshot), snap.deadline)
        with backup.Snapshot(command("psql", *backup.PSQL)) as post:
            backup.DatabaseState.assert_stable(state, post, command)
        target = database(pg, "plain_restore")
        # Roles already exist in this one isolated cluster; new live restore has
        # a fresh cluster. Marking an existing non-bootstrap role is refused.
        with pytest.raises(backup.BackupError, match="restore_role_collision"):
            backup.DatabaseState.provision_restore(pg, target, state)
        # Remove only this test's source DB/roles after capturing its archive,
        # then exercise genuine role recreation, not hand-made restore state.
        assert db.startswith("v49b_") and pg.guard() is None
        pg.sql(target, f"DROP DATABASE {backup.quote_ident(db)}; DROP ROLE {role}; DROP ROLE {reader}")
        backup.DatabaseState.provision_restore(pg, target, state)
        assert pg.sql(target, f"SELECT rolcanlogin OR rolsuper FROM pg_roles WHERE rolname='{role}'").strip() == b"f"
        archive.restore(pg.empty_restore(target), time.monotonic()+120)
        restored = lambda tool, *args: pg.command(tool, target, *args)
        with backup.Snapshot(restored("psql", *backup.PSQL)) as snap:
            actual = backup.DatabaseState.collect(snap, restored)
        assert actual == state
        assert initial == archive.calculate()
        with pytest.raises(backup.BackupError, match="verification_incomplete"):
            archive.finalize(accepted=False)
        final = archive.finalize(accepted=True)
        assert final.name == "database.dump" and final.stat().st_mode & 0o777 == 0o600
        assert not (directory / "database.partial.dump").exists()
        archive.verify()
    finally:
        archive.close()


def test_plain_role_provision_and_same_schema(pg, artifacts):
    db = populated(pg)
    command = lambda tool, *args: pg.command(tool, db, *args)
    archive = backup.PlainArchive(private_test_directory(artifacts, "provision"))
    try:
        with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
            state = backup.DatabaseState.collect(snap, command)
            archive.export(command("pg_dump", "--format=custom", "--snapshot="+snap.snapshot), snap.deadline)
        target = database(pg, "provision")
        backup.DatabaseState.provision_restore(pg, target, state)
        archive.restore(pg.empty_restore(target), time.monotonic()+60)
        with backup.Snapshot(pg.command("psql", target, *backup.PSQL)) as snap:
            assert backup.DatabaseState.collect(snap, lambda tool, *args: pg.command(tool, target, *args)) == state
    finally:
        archive.close()


def test_plain_source_ddl_and_sequence_drift(pg):
    db = populated(pg)
    command = lambda tool, *args: pg.command(tool, db, *args)
    with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
        state = backup.DatabaseState.collect(snap, command)
    pg.sql(db, "SELECT nextval('test.items_id_seq')")
    with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
        with pytest.raises(backup.BackupError, match="drift"):
            backup.DatabaseState.assert_stable(state, snap, command)
        state = backup.DatabaseState.collect(snap, command)
    pg.sql(db, "COMMENT ON TABLE test.items IS 'changed in synthetic concurrent DDL'")
    with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
        with pytest.raises(backup.BackupError, match="drift"):
            backup.DatabaseState.assert_stable(state, snap, command)


@pytest.mark.parametrize("change,code", [
    ("COMMENT ON DATABASE {db} IS 'synthetic'", "unsupported_database_properties"),
    ("ALTER DATABASE {db} SET work_mem='8MB'", "unsupported_database_properties"),
    ("CREATE EXTENSION file_fdw", "unsupported_extension"),
    ("CREATE PUBLICATION backup_negative", "unsupported_external_or_tablespace"),
])
def test_plain_unsupported_properties_are_not_omitted(pg, change, code):
    db = database(pg, "unsupported")
    pg.sql(db, change.format(db=db))
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        with pytest.raises(backup.BackupError, match=code):
            backup.DatabaseState.collect(snap, lambda tool, *args: pg.command(tool, db, *args))


def archive_command(body=b"PGDMPsynthetic-negative-test-only"):
    return [sys.executable, "-c", "import sys;sys.stdout.buffer.write("+repr(body)+")"]


def test_plain_file_private_integrity_and_no_overwrite(artifacts):
    directory = private_test_directory(artifacts, "file_integrity")
    archive = backup.PlainArchive(directory)
    try:
        with pytest.raises(FileExistsError):
            backup.PlainArchive(directory)
        archive.export(archive_command(), time.monotonic()+10)
        with pytest.raises(backup.BackupError, match="already_written"):
            archive.export(archive_command(), time.monotonic()+10)
        archive.path.chmod(0o644)
        with pytest.raises(backup.BackupError, match="private"):
            archive.verify()
        archive.path.chmod(0o600)
        link = directory / "hardlink"
        os.link(archive.path, link)
        with pytest.raises(backup.BackupError, match="private"):
            archive.verify()
        link.unlink()
        final = directory / "database.dump"
        with final.open("xb") as f:
            f.write(b"existing synthetic file")
        with pytest.raises(backup.BackupError, match="finalize_exists"):
            archive.finalize(accepted=True)
        assert final.read_bytes() == b"existing synthetic file"
        # Corruption of our own synthetic data is detected by content hash.
        os.pwrite(archive.fd, b"X", 7)
        with pytest.raises(backup.BackupError, match="integrity"):
            archive.verify()
        archive.path.rename(directory / "retained_original")
        with archive.path.open("xb") as f:
            f.write(b"PGDMPanother synthetic inode")
        archive.path.chmod(0o600)
        with pytest.raises(backup.BackupError, match="replaced"):
            archive.verify()
    finally:
        archive.close()


def test_plain_acl_and_space_guards(artifacts):
    directory = private_test_directory(artifacts, "acl_space")
    with pytest.raises(backup.BackupError, match="insufficient_space"):
        backup.PlainArchive(directory, minimum_free=2**63)
    if sys.platform == "darwin":
        subprocess.run(["chmod", "+a", "everyone allow read,search", str(directory)], check=True)
        try:
            with pytest.raises(backup.BackupError, match="acl_grants_access"):
                backup.PlainArchive(directory)
        finally:
            subprocess.run(["chmod", "-a", "everyone allow read,search", str(directory)], check=True)
    other = private_test_directory(artifacts, "linked_custody")
    link = directory / "linked"
    link.symlink_to(other)
    with pytest.raises(backup.BackupError, match="symlink"):
        backup.PlainArchive(link)


@pytest.mark.parametrize("body", [b"", b"not-a-postgresql-archive"])
def test_plain_empty_and_bad_format(artifacts, body):
    archive = backup.PlainArchive(private_test_directory(artifacts, "bad_format"))
    try:
        with pytest.raises(backup.BackupError):
            archive.export(archive_command(body), time.monotonic()+10)
        assert archive.path.name == "database.partial.dump"
    finally:
        archive.close()


def test_plain_real_restore_rejects_truncated_dump(pg, artifacts):
    db = populated(pg)
    archive = backup.PlainArchive(private_test_directory(artifacts, "truncated"))
    try:
        archive.export(pg.command("pg_dump", db, "--format=custom"), time.monotonic()+60)
        os.ftruncate(archive.fd, archive.expected["bytes"]//2)
        with pytest.raises(backup.BackupError, match="integrity"):
            archive.restore(pg.empty_restore(database(pg, "truncated")), time.monotonic()+20)
        # The actual PostgreSQL parser must also reject a truncated archive even
        # if its externally supplied expected hash were updated by an attacker.
        archive.expected = archive.calculate()
        with pytest.raises(backup.BackupError, match="restore_failed"):
            archive.restore(pg.empty_restore(database(pg, "parser_reject")), time.monotonic()+20)
    finally:
        archive.close()


def test_plain_process_stream_limits_and_errors(artifacts):
    sink = hashlib.sha256()
    assert backup.read_process(archive_command(b"hello"), sink.update, deadline=time.monotonic()+10) == 5
    assert sink.hexdigest() == hashlib.sha256(b"hello").hexdigest()
    with pytest.raises(backup.BackupError, match="invalid_stream_limit"):
        backup.read_process(archive_command(), sink.update, limit=0)
    with pytest.raises(backup.BackupError, match="stream_too_large"):
        backup.read_process(archive_command(), sink.update, limit=3)
    with pytest.raises(backup.BackupError, match="stream_failed"):
        backup.read_process([sys.executable, "-c", "import sys;sys.stdout.write('x');sys.exit(3)"], sink.update)
    with pytest.raises(backup.BackupError, match="stream_timeout"):
        backup.read_process([sys.executable, "-c", "import time;time.sleep(60)"], sink.update,
            deadline=time.monotonic()+0.2)
    archive = backup.PlainArchive(private_test_directory(artifacts, "restore_timeout"))
    try:
        archive.export(archive_command(), time.monotonic()+10)
        with pytest.raises(backup.BackupError, match="restore_timeout"):
            archive.restore([sys.executable, "-c", "import time;time.sleep(60)"], time.monotonic()+0.2)
    finally:
        archive.close()
    assert backup.literal("a'\\b") == "E'a''\\\\b'"
    with pytest.raises(backup.BackupError, match="invalid_literal"):
        backup.literal("x\x00")


def test_plain_complete_export_and_restore_orchestration(pg, artifacts):
    db = populated(pg)
    command = lambda tool, *args: pg.command(tool, db, *args)
    directory = private_test_directory(artifacts, "orchestration")
    archive, state = backup.export_database(command, directory)
    try:
        assert json.loads((directory / "snapshot.json").read_text()) == state
        result = backup.verify_restore(archive, state, pg)
        assert result["full_comparison"] and result["rows"] == 2 and result["large_objects"] == 1
        incorrect = {**state, "schema": "changed-expected-schema-negative-test"}
        # R3 rejects a changed expected snapshot BEFORE starting a restore.
        with pytest.raises(backup.BackupError, match="schema_evidence_binding"):
            backup.verify_restore(archive, incorrect, pg)
    finally:
        archive.close()
    pg.sql(db, f"COMMENT ON DATABASE {db} IS 'synthetic unsupported source'")
    failed = private_test_directory(artifacts, "failed_export")
    with pytest.raises(backup.BackupError, match="unsupported_database_properties"):
        backup.export_database(command, failed)
    assert (failed / "database.partial.dump").stat().st_mode & 0o777 == 0o600
    assert not (failed / "database.dump").exists()


def test_snapshot_json_and_deadline_guards(pg):
    db = database(pg, "json_guard")
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        with pytest.raises(backup.BackupError, match="metadata_json_invalid"):
            snap.value("SELECT true")
        snap.deadline = time.monotonic()-1
        with pytest.raises(backup.BackupError, match="snapshot_expired"):
            snap.value("SELECT 1")


def test_plain_cli_refuses_unapproved_export_without_kubernetes(artifacts):
    for argv in (["--prepare-source"], ["--backup-unencrypted"],
                 ["--backup-unencrypted", "--qualification", str(artifacts)],
                 ["--prepare-source", "--qualification", str(artifacts), "--accept-unencrypted"],
                 ["--self-test-unencrypted", "--accept-unencrypted"],
                 ["--self-test", "--accept-unencrypted"]):
        with pytest.raises(backup.BackupError):
            backup.main(argv)
    with pytest.raises(SystemExit) as done:
        backup.main(["--help"])
    assert done.value.code == 0
    with pytest.raises(SystemExit) as bad:
        backup.main(["--backup-unencrypted", "--self-test-unencrypted"])
    assert bad.value.code == 2
    with pytest.raises(backup.BackupError, match="live_tool_not_readonly"):
        backup.LiveSource.command("pg_restore")
    argv = backup.LiveSource.command("psql", *backup.PSQL)
    assert argv[:5] == ["kubectl", "--context", "docker-desktop", "-n", "nomosmart"]
    assert "--no-password" in argv[argv.index("-c")+5] or "--no-password" in " ".join(argv)
    with pytest.raises(backup.BackupError, match="plaintext_opt_in_required"):
        backup.live_backup(artifacts, "not-a-binding", False)


def test_plain_missing_or_changed_qualification_is_not_accepted(artifacts):
    directory = private_test_directory(artifacts, "unqualified")
    with pytest.raises(backup.BackupError, match="qualification_path_invalid"):
        backup.require_qualification(directory)
    # Genuine old failure reports are not replaced with fabricated PASS JSON.
    with pytest.raises(backup.BackupError, match="qualification_failed"):
        backup.qualification_reports(directory, 1, backup.tool_sources())
    with pytest.raises(backup.BackupError, match="qualification_failed"):
        backup.qualification_reports(directory, 0, {})
    with pytest.raises(backup.BackupError, match="qualification_missing"):
        backup.require_qualification(artifacts)


def test_plain_source_diagnostic_is_bounded_and_not_raw(artifacts):
    sink = hashlib.sha256()
    with pytest.raises(backup.BackupError, match="stream_failed_or_empty") as error:
        backup.read_process([sys.executable, "-c",
            "import sys;sys.stderr.write('synthetic-private-diagnostic');sys.exit(9)"], sink.update)
    assert "synthetic-private-diagnostic" not in str(error.value)
    with pytest.raises(backup.BackupError, match="stream_timeout"):
        backup.read_process([sys.executable, "-c", "import sys,time;sys.stdout.close();time.sleep(60)"],
            sink.update, deadline=time.monotonic()+0.2)


def test_plain_real_file_write_failure_retains_private_partial(artifacts):
    directory = private_test_directory(artifacts, "file_failure")
    script = ("import sys,resource,signal,time;sys.path.insert(0,sys.argv[1]);"
        "import chg291_v049_live_backup as b;"
        "a=b.PlainArchive(sys.argv[2]);"
        "signal.signal(signal.SIGXFSZ,signal.SIG_IGN);resource.setrlimit(resource.RLIMIT_FSIZE,(1,1));"
        "a.export([sys.executable,'-c',\"import sys;sys.stdout.buffer.write(b'PGDMPtest')\"],time.monotonic()+10)")
    result = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPT.parent), str(directory)],
        capture_output=True, env=backup.clean_env(), timeout=20)
    assert result.returncode != 0
    assert (directory / "database.partial.dump").stat().st_size <= 1
    assert (directory / "database.partial.dump").stat().st_mode & 0o777 == 0o600
    assert not (directory / "database.dump").exists()


def test_private_proofs_reject_unsafe_files(artifacts):
    directory = private_test_directory(artifacts, "proof_io")
    path = directory / "proof.json"
    backup.private_json(path, {"synthetic": True})
    assert backup.read_private_json(path) == {"synthetic": True}
    path.chmod(0o644)
    with pytest.raises(backup.BackupError, match="metadata_file_not_private"):
        backup.read_private_json(path)
    path.chmod(0o600)
    link = directory / "alias.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        backup.read_private_json(link)
    for data, error in ((b"not json", "metadata_json_invalid"), (b"[]", "metadata_not_object")):
        bad = directory / (error+".json")
        with bad.open("xb") as stream:
            stream.write(data)
        bad.chmod(0o600)
        with pytest.raises(backup.BackupError, match=error):
            backup.read_private_json(bad)
    oversized = directory / "oversized.json"
    with oversized.open("xb") as stream:
        stream.truncate(4*1024**2+1)
    oversized.chmod(0o600)
    with pytest.raises(backup.BackupError, match="metadata_file_not_private"):
        backup.read_private_json(oversized)


def test_human_mode_still_refuses_automated_password_entry(artifacts):
    # No fake TTY, no attempted prompt and no password. Negative guard only.
    if not sys.stdin.isatty():
        with pytest.raises(backup.BackupError, match="human_terminal_required"):
            backup.HumanGPG(artifacts)
        with pytest.raises(backup.BackupError, match="human_terminal_required"):
            backup.main(["--self-test"])
    with pytest.raises(backup.BackupError, match="cleanup_path_invalid"):
        backup.main(["--cleanup-test", str(artifacts.parent)])


def test_intent_and_registry_refuse_unowned_targets(pg, artifacts):
    db = database(pg, "registry_guard")
    bad = private_test_directory(artifacts, "bad_intent")
    backup.private_json(bad / "container-intent.json", {"label": "wrong", "image": backup.PG_IMAGE, "run": "wrong"})
    with pytest.raises(backup.BackupError, match="intent_invalid"):
        backup.recover_test_resources(bad)
    token = "v49b-"+secrets.token_hex(8)
    index = artifacts / ("owned-receipt-"+token+".json")
    backup.private_json(index, {"run": token, "relative_directory": "../unowned"})
    try:
        with pytest.raises(backup.BackupError, match="registry_outside_run"):
            backup.recover_qualification(artifacts)
        # Invalid registry input must leave even this run's real PG untouched.
        pg.guard()
        assert pg.sql(db, "SELECT 1").strip() == b"1"
    finally:
        index.unlink()  # Exact synthetic invalid metadata; not a backup/real receipt.


def test_snapshot_and_stream_interrupt_real_processes(pg):
    db = database(pg, "close_interrupt")
    snap = backup.Snapshot(pg.command("psql", db, *backup.PSQL))
    snap.child.stdin.write(b"SELECT pg_sleep(10);\n")
    snap.child.stdin.flush()
    time.sleep(0.2)
    snap.close()
    assert snap.child.poll() is not None
    with pytest.raises(backup.BackupError, match="stream_timeout"):
        backup.read_process([sys.executable, "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"],
            hashlib.sha256().update, deadline=time.monotonic()+0.5)


def test_large_pipe_backpressure_preserves_all_bytes():
    payload = b"synthetic-stream-block\n" * 65536
    expected = hashlib.sha256(payload).hexdigest()
    source = [sys.executable, "-c",
        "import sys;sys.stdout.buffer.write(b'synthetic-stream-block\\n'*65536)"]
    # A genuinely slow consumer forces bounded buffering and pause/resume.
    target = [sys.executable, "-c",
        "import sys,time,hashlib;time.sleep(.3);h=hashlib.sha256();"
        "exec('while block := sys.stdin.buffer.read(4096):\\n h.update(block);time.sleep(.001)');"
        "sys.exit(0 if h.hexdigest()==sys.argv[1] else 9)", expected]
    result = backup.pipeline(source, target, seconds=10)
    assert result["bytes"] == len(payload) and result["all_exits_zero"]


@pytest.mark.parametrize("blocked", ["source", "consumer"])
def test_pipe_eof_does_not_hide_running_child(blocked):
    source = [sys.executable, "-c", "import os,time;os.write(1,b'x');os.close(1);" +
              ("time.sleep(60)" if blocked == "source" else "pass")]
    target = [sys.executable, "-c", "import sys,time;sys.stdin.buffer.read();" +
              ("time.sleep(60)" if blocked == "consumer" else "pass")]
    with pytest.raises(backup.BackupError, match="pipeline_timeout"):
        backup.pipeline(source, target, seconds=0.4)


def test_stream_eof_does_not_hide_running_child():
    with pytest.raises(backup.BackupError, match="stream_timeout"):
        backup.read_process([sys.executable, "-c",
            "import os,time;os.write(1,b'x');os.close(1);time.sleep(60)"],
            hashlib.sha256().update, deadline=time.monotonic()+0.4)


def test_snapshot_metadata_limit_timeout_and_broken_pipe(pg):
    db = database(pg, "bounded_metadata")
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        with pytest.raises(backup.BackupError, match="metadata_too_large"):
            snap.query("SELECT repeat('synthetic',600000)")
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        snap.deadline = time.monotonic()+0.2
        with pytest.raises(backup.BackupError, match="snapshot_query_timeout"):
            snap.query("SELECT pg_sleep(0.5)")
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        backup.stop_process(snap.child)
        with pytest.raises(backup.BackupError, match="snapshot_query_failed"):
            snap.query("SELECT 1")
    assert snap.child.stdin.closed and snap.child.stdout.closed


def test_archive_constructor_closes_fd_on_real_permission_failure(artifacts):
    directory = private_test_directory(artifacts, "umask_failure")
    before = len(os.listdir("/dev/fd"))
    previous = os.umask(0o777)
    try:
        with pytest.raises(backup.BackupError, match="archive_not_private"):
            backup.PlainArchive(directory)
    finally:
        os.umask(previous)
    assert len(os.listdir("/dev/fd")) == before
    assert (directory / "database.partial.dump").stat().st_mode & 0o777 == 0
    assert not (directory / "database.dump").exists()


def test_plain_full_cli_arguments_still_reject_unqualified_run(artifacts):
    for args in (["--prepare-source", "--qualification", str(artifacts)],
                 ["--backup-unencrypted", "--qualification", str(artifacts),
                  "--binding-sha256", "not-an-approved-binding", "--accept-unencrypted"]):
        with pytest.raises(backup.BackupError, match="qualification_missing"):
            backup.main(args)


def test_real_program_entry_refuses_missing_qualification(artifacts, capsys):
    # Execute the real __main__ boundary, not an adapter or a successful fixture.
    # Only caller arguments change; every custody/CLI guard remains real.
    previous = sys.argv
    try:
        for arguments, expected, message in (
            (["--help"], 0, None),
            (["--prepare-source", "--qualification", str(artifacts)], 1, "qualification_missing"),
            (["--prepare-source", "--qualification", str(artifacts / "missing")], 1,
             "backup_operation_failed_details_withheld"),
        ):
            sys.argv = [str(SCRIPT), *arguments]
            with pytest.raises(SystemExit) as outcome:
                runpy.run_path(str(SCRIPT), run_name="__main__")
            assert outcome.value.code == expected
            output = capsys.readouterr()
            if message:
                assert output.err.strip() == message
    finally:
        sys.argv = previous


def test_readonly_cli_never_uses_intermediate_proof_for_export(artifacts):
    for args in (["--qualify-source-readonly"],
        ["--qualify-source-readonly", "--qualification", str(artifacts)],
        ["--qualify-source-readonly", "--qualification", str(artifacts), "--accept-source-readonly",
         "--accept-unencrypted"], ["--self-test-unencrypted", "--accept-source-readonly"]):
        with pytest.raises(backup.BackupError):
            backup.main(args)
    with pytest.raises(backup.BackupError, match="source_readonly_opt_in_required"):
        backup.qualify_source_readonly(artifacts, False)
    with pytest.raises(backup.BackupError, match="synthetic_proof_missing"):
        backup.main(["--qualify-source-readonly", "--qualification", str(artifacts), "--accept-source-readonly"])
    # A real invalid local proof is not a fabricated test/service PASS. Neither
    # readonly nor export can accept its status, even with both explicit flags.
    invalid = artifacts / "synthetic-proof.json"
    backup.private_json(invalid, {"status": "NOT_QUALIFIED"})
    try:
        with pytest.raises(backup.BackupError, match="synthetic_proof_invalid"):
            backup.require_synthetic(artifacts)
        with pytest.raises(backup.BackupError, match="qualification_missing"):
            backup.main(["--backup-unencrypted", "--qualification", str(artifacts),
                "--binding-sha256", "not-qualified", "--accept-unencrypted"])
        assert not (artifacts / "readonly-claimed.json").exists()
        assert not (artifacts / "database.partial.dump").exists()
    finally:
        invalid.unlink()  # Only this test's deliberately invalid input, not evidence.


def test_metadata_response_refuses_secret_body_or_wrong_scope():
    # Pure negative parser inputs only; no Kubernetes response is simulated as a
    # successful integration check. Positive negotiation is verified on source.
    for value in ({"kind": "SecretList", "apiVersion": "v1", "items": []},
        {"kind": "PartialObjectMetadataList", "apiVersion": "meta.k8s.io/v1", "metadata": {"continue": "next"}},
        {"kind": "PartialObjectMetadataList", "apiVersion": "meta.k8s.io/v1", "items": [
            {"metadata": {}, "data": {}}]},
        {"kind": "PartialObjectMetadataList", "apiVersion": "meta.k8s.io/v1", "items": [
            {"metadata": {"namespace": "unapproved"}}]},
        {"kind": "PartialObjectMetadataList", "apiVersion": "meta.k8s.io/v1", "items": []}):
        with pytest.raises(backup.BackupError):
            backup.secret_metadata_digest(value)


def test_existing_mtls_can_load_real_certificates_without_files():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic qualification only")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
        .not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    before = len(os.listdir("/dev/fd"))
    context = backup.memory_tls_context(cert, cert, pem)
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(OSError):
        backup.memory_tls_context(cert, cert, b"deliberately-invalid-synthetic-key")
    with pytest.raises(backup.BackupError, match="configured_certificate_too_large"):
        backup.memory_tls_context(cert, cert * 100, pem)
    assert len(os.listdir("/dev/fd")) == before


def test_bounded_json_uses_real_process_and_preserves_invalid_exit():
    result = backup.process_json([sys.executable, "-c", "print('{\"synthetic\":true}')"], time.monotonic()+10)
    assert result == {"synthetic": True}
    with pytest.raises(backup.BackupError, match="stream_failed_or_empty"):
        backup.process_json([sys.executable, "-c", "import sys;sys.exit(2)"], time.monotonic()+10)
    with pytest.raises(backup.BackupError, match="stream_too_large"):
        backup.process_json([sys.executable, "-c", "import sys;sys.stdout.write('x'*5000000)"], time.monotonic()+10)


def test_report_integrity_requires_private_existing_file(artifacts):
    path = artifacts / "report-guard.txt"
    path.write_bytes(b"actual guard input, not a test report")
    path.chmod(0o600)
    assert backup.report_hashes(artifacts, (path.name,))[path.name] == hashlib.sha256(path.read_bytes()).hexdigest()
    path.chmod(0o644)
    with pytest.raises(backup.BackupError, match="qualification_report_not_private"):
        backup.report_hashes(artifacts, (path.name,))
    with pytest.raises(backup.BackupError, match="qualification_report_missing"):
        backup.report_hashes(artifacts, ("missing-report",))
    path.chmod(0o600)


def test_cleanup_before_start_and_repeated_archive_close_are_safe(pg, artifacts):
    # Actual interrupted lifecycle: no container was created by this object, and
    # closing its archive twice must neither delete another resource nor reuse an
    # already closed descriptor. Compare the genuine existing Docker inventory.
    directory = private_test_directory(artifacts, "interrupted_before_start")
    before = pg.inventory()
    pending = backup.MemoryPostgres(directory)
    pending.cleanup()
    pending.cleanup()
    with pytest.raises(backup.BackupError, match="missing_owned_container"):
        pending.inspect()
    archive = backup.PlainArchive(directory)
    descriptor = archive.fd
    archive.close()
    archive.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert archive.fd is None and archive.path.exists()
    assert archive.path.stat().st_mode & 0o777 == 0o600
    assert pg.inventory() == before


def schema_evidence(pg, db):
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        return backup.SchemaEvidence.collect(snap)


def test_r3_real_catalog_inventory_definitions_and_stable_keys(pg, artifacts):
    db = populated(pg)
    pg.sql(db, """
      CREATE TYPE test.mood AS ENUM ('calm','busy');
      CREATE DOMAIN test.positive AS integer CHECK (VALUE>0);
      CREATE TABLE test.part(id integer) PARTITION BY RANGE(id);
      CREATE TABLE test.part_one PARTITION OF test.part FOR VALUES FROM(0) TO(10);
      CREATE MATERIALIZED VIEW test.materialized AS SELECT body FROM test.items;
      CREATE FUNCTION test.echo_text(text) RETURNS text LANGUAGE sql IMMUTABLE AS 'SELECT $1';
      CREATE FUNCTION test.touch() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END';
      CREATE TRIGGER touch BEFORE UPDATE ON test.items FOR EACH ROW EXECUTE FUNCTION test.touch();
      ALTER TABLE test.items ENABLE ROW LEVEL SECURITY;
      CREATE POLICY allow_items ON test.items USING(id>0);
      ALTER DEFAULT PRIVILEGES IN SCHEMA test GRANT SELECT ON TABLES TO PUBLIC;
    """)
    initial = schema_evidence(pg, db)
    again = schema_evidence(pg, db)
    assert initial == again and initial["complete"]
    assert all(initial["coverage"][kind] > 0 for kind in backup.SchemaEvidence.KINDS)
    pg.sql(db, """
      ALTER TABLE test.items ADD COLUMN added integer DEFAULT 4;
      ALTER TABLE test.items ALTER COLUMN body SET DEFAULT 'unchanged original words';
      ALTER TABLE test.items ADD CONSTRAINT positive_id CHECK(id>0);
      CREATE INDEX extra_body_idx ON test.items(body,id);
      CREATE OR REPLACE FUNCTION test.echo_text(text) RETURNS text LANGUAGE sql IMMUTABLE AS 'SELECT upper($1)';
      ALTER POLICY allow_items ON test.items USING(id>1);
      ALTER TABLE test.items FORCE ROW LEVEL SECURITY;
    """)
    changed = schema_evidence(pg, db)
    difference = backup.SchemaEvidence.diff(initial, changed)
    assert difference["status"] == "DIFFERENT"
    assert {"column", "constraint", "relation", "routine", "policy"} <= {x["kind"] for x in difference["changes"]}
    assert any(x["change"] == "added" for x in difference["changes"])
    assert any("definition" in x["fields"] for x in difference["changes"])
    assert backup.SchemaEvidence.diff(changed, initial)["changes"] != difference["changes"]
    assert any(x["change"] == "missing" for x in backup.SchemaEvidence.diff(changed, initial)["changes"])
    backup.private_json(private_test_directory(artifacts, "r3_inventory") / "difference.json", difference)


@pytest.mark.parametrize("object_sql,kind", [
    ("SCHEMA test", "schema"), ("TABLE test.items", "relation"),
    ("COLUMN test.items.body", "column"), ("EXTENSION plpgsql", "extension")])
def test_r3_real_comment_states_and_no_plaintext(pg, object_sql, kind, capsys):
    db = populated(pg)
    secret = "synthetic-only-secret-comment-'-$()-\\echo-never-execute"
    pg.sql(db, "COMMENT ON "+object_sql+" IS "+backup.literal(secret))
    present = schema_evidence(pg, db)
    assert secret not in json.dumps(present)
    pg.sql(db, "COMMENT ON "+object_sql+" IS NULL")
    absent = schema_evidence(pg, db)
    difference = backup.SchemaEvidence.diff(present, absent)
    assert any(x["kind"] == kind and x["fields"] == ["comment"] for x in difference["changes"])
    pg.sql(db, "COMMENT ON "+object_sql+" IS ''")
    empty = schema_evidence(pg, db)
    # PostgreSQL treats COMMENT '' as removal, not a fabricated empty comment.
    assert empty == absent
    assert secret not in json.dumps(difference) and secret not in capsys.readouterr().out


def test_r3_real_owners_grantors_options_default_acls_and_database(pg):
    db = populated(pg)
    owner = "r3_owner_"+secrets.token_hex(4)
    reader = "r3_reader_"+secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {owner} NOLOGIN; CREATE ROLE {reader} NOLOGIN")
    initial = schema_evidence(pg, db)
    pg.sql(db, f"ALTER TABLE test.items OWNER TO {owner}; GRANT SELECT ON test.items TO {reader} WITH GRANT OPTION; "
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA test GRANT SELECT ON TABLES TO {reader}; "
        f"ALTER DATABASE {db} OWNER TO {owner}")
    actual = schema_evidence(pg, db)
    changes = backup.SchemaEvidence.diff(initial, actual)["changes"]
    assert any(x["kind"] == "relation" and {"owner", "acl"} <= set(x["fields"]) for x in changes)
    assert any(x["kind"] == "default_acl" and x["change"] == "added" for x in changes)
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        assert backup.DatabaseState.properties(snap)["owner"] == owner
    fields = [x["fields"] for x in actual["objects"].values() if x["kind"] == "relation"]
    assert any(any(row[1] == reader and row[3] for row in x["acl"]["grants"]) for x in fields)


@pytest.mark.parametrize("damage,code", [
    ("missing", "unavailable"), ("version", "version"), ("collector", "version"),
    ("sources", "binding"), ("image", "binding"), ("snapshot_sha256", "binding"),
    ("archive", "binding"), ("digest", "integrity"), ("complete", "incomplete"),
    ("unsupported", "incomplete"), ("coverage", "inventory"), ("unknown_kind", "object_invalid"),
    ("object_key", "object_invalid"), ("fields", "object_invalid"), ("server_version", "incomplete"),
    ("null_evidence", "incomplete"), ("null_coverage", "incomplete"), ("boolean_version", "version"),
    ("replacement", "changed"), ("rehashed_object", "changed")])
def test_r3_sidecar_real_export_fail_closed_binding(pg, artifacts, damage, code):
    db = database(pg, "r3_binding")
    directory = private_test_directory(artifacts, "r3_binding")
    archive, state = backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory)
    path = directory / backup.SchemaEvidence.FILE
    try:
        original = backup.SchemaEvidence.read(archive, state)
        snapshot_bytes = (directory / "snapshot.json").read_bytes()
        value = json.loads(path.read_text())
        if damage == "missing":
            path.rename(directory / "retained-evidence.json")
        elif damage == "replacement":
            path.rename(directory / "retained-evidence.json")
            backup.private_json(path, value)
        else:
            if damage in ("version", "collector", "sources", "image", "snapshot_sha256", "archive"):
                value[damage] = "negative-test"
            elif damage == "boolean_version":
                value["version"] = True
            elif damage == "digest":
                value["evidence_sha256"] = "0"*64
            elif damage == "null_evidence":
                value["evidence"] = None
                value["evidence_sha256"] = backup.canonical_hash(None)
            else:
                e = value["evidence"]
                if damage == "complete":
                    e["complete"] = False
                elif damage == "unsupported":
                    e["unsupported"] = ["0"*64]
                elif damage == "coverage":
                    e["coverage"]["schema"] += 1
                elif damage == "null_coverage":
                    e["coverage"] = None
                elif damage == "server_version":
                    e["server_version_num"] = 170000
                else:
                    key = next(iter(e["objects"]))
                    if damage == "unknown_kind":
                        e["objects"][key]["kind"] = "unknown"
                    elif damage == "object_key":
                        e["objects"]["0"*64] = e["objects"].pop(key)
                    elif damage == "rehashed_object":
                        e["objects"][key]["fields"]["owner"] = "synthetic-negative-rehashed-owner"
                    else:
                        e["objects"][key]["fields"].pop("comment")
                value["evidence_sha256"] = backup.canonical_hash(e)
            path.write_text(json.dumps(value))
        with pytest.raises(backup.BackupError, match="schema_evidence_"+code):
            backup.verify_restore(archive, state, pg)
        assert (directory / "snapshot.json").read_bytes() == snapshot_bytes
        assert not list(directory.glob("schema-comparison-*.json"))  # Before any restore.
        assert original["evidence"]["complete"] and not (directory / "database.dump").exists()
    finally:
        archive.close()


def test_r3_real_unknown_objects_and_source_metadata_drift(pg, artifacts):
    db = populated(pg)
    initial = schema_evidence(pg, db)
    pg.sql(db, "CREATE COLLATION test.unsupported (provider=builtin,locale='C')")
    unsupported = schema_evidence(pg, db)
    assert not unsupported["complete"] and unsupported["unsupported"]
    assert backup.SchemaEvidence.diff(initial, unsupported)["status"] == "UNAVAILABLE"
    with pytest.raises(backup.BackupError, match="schema_evidence_incomplete"):
        backup.export_database(lambda tool, *args: pg.command(tool, db, *args),
            private_test_directory(artifacts, "r3_unsupported"))
    pg.sql(db, "DROP COLLATION test.unsupported")
    # Actual comment DDL changes metadata between snapshots; it is not repaired.
    pg.sql(db, "COMMENT ON SCHEMA test IS 'actual post-snapshot mutation'")
    assert schema_evidence(pg, db) != initial


def test_r3_malicious_identifiers_are_data_and_safe_diff(pg, capsys):
    db = database(pg, "r3_names")
    name = 'sensitive-name-"; SELECT pg_sleep(60); -- $(touch forbidden)'
    ident = backup.quote_ident(name)
    pg.sql(db, f"CREATE TABLE {ident}(body text); COMMENT ON TABLE {ident} IS 'secret-comment'; "
        "CREATE FUNCTION private_function() RETURNS text LANGUAGE sql AS 'SELECT ''secret-body''' ")
    before = schema_evidence(pg, db)
    pg.sql(db, f"COMMENT ON TABLE {ident} IS 'changed-secret'")
    difference = backup.SchemaEvidence.diff(before, schema_evidence(pg, db))
    rendered = json.dumps(difference)
    assert difference["status"] == "DIFFERENT"
    for value in (name, "secret-comment", "secret-body", "changed-secret", "private_function"):
        assert value not in rendered and value not in capsys.readouterr().out
    assert "secret-body" not in json.dumps(before)


def test_r3_post_snapshot_catalog_only_owner_drift_rejects_export(pg, artifacts):
    db = database(pg, "r3_drift")
    role = "r3_language_owner_"+secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {role} NOLOGIN")
    calls = 0
    def command(tool, *args):
        nonlocal calls
        if tool == "psql":
            calls += 1
            if calls == 2:
                # Actual concurrent-state transition after dump, before the
                # post-snapshot transaction. No fake SQL response or catalog edit.
                pg.sql(db, f"ALTER LANGUAGE plpgsql OWNER TO {role}")
        return pg.command(tool, db, *args)
    directory = private_test_directory(artifacts, "r3_drift")
    with pytest.raises(backup.BackupError, match="source_schema_evidence_drift"):
        backup.export_database(command, directory)
    assert not (directory / backup.SchemaEvidence.FILE).exists()
    assert not (directory / "database.dump").exists()


def test_r3_sidecar_custody_and_restore_error_evidence(pg, artifacts):
    db = populated(pg)
    directory = private_test_directory(artifacts, "r3_custody")
    archive, state = backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory)
    path = directory / backup.SchemaEvidence.FILE
    try:
        path.chmod(0o644)
        with pytest.raises(backup.BackupError, match="metadata_file_not_private"):
            backup.SchemaEvidence.read(archive, state)
        path.chmod(0o600)
        moved = directory / "retained-evidence.json"
        path.rename(moved)
        path.symlink_to(moved)
        with pytest.raises((backup.BackupError, OSError)):
            backup.SchemaEvidence.read(archive, state)
        path.unlink()
        moved.rename(path)
        path.rename(moved)
        os.mkfifo(path, 0o600)
        with pytest.raises(backup.BackupError, match="metadata_file_not_private"):
            backup.SchemaEvidence.read(archive, state)
        path.unlink()
        moved.rename(path)
        # Genuine corrupt pg_restore input, deliberately re-bound only in this
        # negative synthetic case so verification reaches the real restore error.
        os.ftruncate(archive.fd, 64)
        archive.expected = archive.calculate()
        value = backup.read_private_json(path)
        value["archive"] = archive.expected
        path.write_text(json.dumps(value))
        # Deliberately damage the in-memory negative fixture as well; this case
        # tests real pg_restore ERROR persistence, never successful qualification.
        info = path.lstat()
        archive.schema_evidence_binding = (info.st_dev, info.st_ino, backup.canonical_hash(value))
        with pytest.raises(backup.BackupError, match="restore_failed"):
            backup.verify_restore(archive, state, pg)
        report = backup.read_private_json(next(directory.glob("schema-comparison-*.json")))
        assert report["catalog"]["status"] == "ERROR" and report["full_comparison"] is False
    finally:
        archive.close()


def test_r3_real_representation_difference_never_becomes_pass(pg, artifacts):
    db = populated(pg)
    directory = private_test_directory(artifacts, "r3_representation")
    def command(tool, *args):
        # Two REAL pg_dump representations of the same catalog. The custom
        # archive is unchanged; do not fabricate a successful expected schema.
        if tool == "pg_dump" and "--schema-only" in args:
            args = (*args, "--no-comments")
        return pg.command(tool, db, *args)
    archive, state = backup.export_database(command, directory)
    try:
        with pytest.raises(backup.BackupError, match="restored_state_differs"):
            backup.verify_restore(archive, state, pg)
        report = backup.read_private_json(next(directory.glob("schema-comparison-*.json")))
        assert report["catalog"]["status"] == "EQUAL" and report["representation_difference_candidate"]
        assert report["categories"]["schema"] is False
        assert all(value for key, value in report["categories"].items() if key != "schema")
        assert not (directory / "database.dump").exists()
    finally:
        archive.close()


@pytest.mark.parametrize("damage", ["version", "catalog_hash", "server_version", "missing_extensions",
    "unknown_extension", "missing_version", "unknown_version", "missing_schema", "missing_owner",
    "missing_member", "unknown_member", "mixed_member", "incomplete", "inventory", "initial_acl"])
def test_r4_profile_validation_against_real_catalog(pg, damage):
    db = database(pg, "r4_profile")
    if damage == "initial_acl":
        pg.sql(db, "ALTER EXTENSION plpgsql DROP FUNCTION plpgsql_call_handler(); "
            "REVOKE ALL ON FUNCTION plpgsql_call_handler() FROM PUBLIC; "
            "ALTER EXTENSION plpgsql ADD FUNCTION plpgsql_call_handler()")
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        catalog = backup.SchemaEvidence.collect(snap)
        profile = backup.RestoreIdentityProfile.collect(snap, catalog)
    assert backup.RestoreIdentityProfile.select(profile, catalog) == pg.bootstrap
    if damage == "version":
        profile["version"] = True
    elif damage == "catalog_hash":
        profile["catalog_sha256"] = "0"*64
    elif damage == "server_version":
        profile["server_version_num"] = 170000
    elif damage == "missing_extensions":
        profile["extensions"] = []
    elif damage == "unknown_extension":
        profile["extensions"][0]["name"] = "unknown"
    elif damage in ("missing_version", "unknown_version", "missing_schema", "missing_owner"):
        key = {"missing_version": "version", "unknown_version": "version",
               "missing_schema": "schema", "missing_owner": "owner"}[damage]
        profile["extensions"][0][key] = "9999" if damage == "unknown_version" else None
    else:
        members = [v for v in catalog["objects"].values() if ["e", "extension", "plpgsql"] in v["fields"]["dependencies"]]
        if damage == "missing_member":
            for row in members:
                row["fields"]["dependencies"] = []
        elif damage == "unknown_member":
            members[0]["kind"] = "unsupported"
        elif damage == "mixed_member":
            members[0]["fields"]["owner"] = "different_synthetic_owner"
        elif damage == "initial_acl":
            member = next(row for row in catalog["objects"].values() if row["fields"]["initial_acl"])
            member["fields"]["initial_acl"]["type"] = "unknown"
        elif damage == "incomplete":
            catalog["complete"] = False
        else:
            row = next(v for v in catalog["objects"].values() if v["kind"] == "extension")
            catalog["objects"]["negative-inventory"] = {**row, "identity": "extra"}
        profile["catalog_sha256"] = backup.canonical_hash(catalog)
    # Deliberately damaged genuine collector output is negative input, never a
    # fabricated passing service/catalog response.
    with pytest.raises(backup.BackupError, match="restore_"):
        backup.RestoreIdentityProfile.select(profile, catalog)


@pytest.mark.parametrize("damage", ["replacement", "rehashed_profile", "mode", "symlink", "missing", "legacy"])
def test_r4_profile_custody_before_target_actions(pg, artifacts, damage):
    db = database(pg, "r4_custody")
    directory = private_test_directory(artifacts, "r4_custody")
    archive, state = backup.export_synthetic_database(pg, db, directory)
    try:
        path = directory / backup.RestoreIdentityProfile.FILE
        value, bootstrap = backup.RestoreIdentityProfile.read(archive, state)
        assert bootstrap == pg.bootstrap and value["source_kind"] == "r4-owned-synthetic"
        baseline = pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database")
        retained = directory / "retained-profile.json"
        if damage in ("replacement", "missing", "symlink"):
            path.rename(retained)
            if damage == "replacement":
                backup.private_json(path, value)
            elif damage == "symlink":
                path.symlink_to(retained)
        elif damage == "mode":
            path.chmod(0o644)
        elif damage == "legacy":
            archive.restore_identity_binding = None
        else:
            value["profile"]["extensions"][0]["owner"] = "changed"
            path.write_text(json.dumps(value))
        with pytest.raises((backup.BackupError, OSError)):
            backup.verify_restore(archive, state, pg, synthetic_identity=True)
        assert pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database") == baseline
        assert not list(directory.glob("schema-comparison-*.json"))
    finally:
        archive.close()


@pytest.mark.parametrize("scenario", ["trusted_owner", "language_owner"])
def test_r4_real_mixed_owners_reject_without_archive_export(pg, artifacts, scenario):
    db = database(pg, "r4_mixed")
    owner = "mixed_owner_"+secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {owner} NOLOGIN; ALTER DATABASE {db} OWNER TO {owner}")
    if scenario == "trusted_owner":
        pg.sql(db, f"SET ROLE {owner}; CREATE EXTENSION pgcrypto; RESET ROLE")
    else:
        pg.sql(db, f"ALTER LANGUAGE plpgsql OWNER TO {owner}")
    directory = private_test_directory(artifacts, "r4_mixed")
    with pytest.raises(backup.BackupError, match="restore_profile_mixed_owners"):
        backup.export_synthetic_database(pg, db, directory)
    assert (directory / "database.partial.dump").stat().st_size == 0
    assert not (directory / backup.RestoreIdentityProfile.FILE).exists()


@pytest.mark.parametrize("name", ["", "pg_reserved", "PUBLIC", "current_user", "a\nuser", "a\x00user", "a"*64, "用"*22,
    'r4_"; $(touch forbidden) --', "r4 space", "123name"])
def test_r4_unsafe_bootstrap_rejected_before_container(artifacts, name):
    directory = private_test_directory(artifacts, "r4_identifier")
    with pytest.raises(backup.BackupError, match="restore_identity_invalid"):
        backup.MemoryPostgres(directory, bootstrap=name)
    assert not (directory / "container-intent.json").exists()


def test_r4_runtime_identity_and_explicit_source_guards(pg, artifacts):
    db = database(pg, "r4_identity")
    directory = private_test_directory(artifacts, "r4_identity")
    with pytest.raises(backup.BackupError, match="synthetic_source_required"):
        backup.export_synthetic_database(backup.LiveSource, db, directory)
    original = pg.bootstrap
    try:
        pg.bootstrap = "not_the_actual_bootstrap"
        with pytest.raises(backup.BackupError, match="container_bootstrap_changed"):
            pg.command("psql", db, *backup.PSQL)
    finally:
        pg.bootstrap = original
    assert pg.sql(db, "SELECT current_user").strip().decode() == original
    second_dir = private_test_directory(artifacts, "r4_second_refused")
    second = backup.MemoryPostgres(second_dir)
    try:
        with pytest.raises(backup.BackupError, match="owned_postgres_already_active"):
            second.start()
        assert second.cid is None and not (second_dir / "container-intent.json").exists()
    finally:
        second.cleanup()
    archive, state = backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory)
    try:
        with pytest.raises(backup.BackupError, match="synthetic_restore_profile_required"):
            backup.restore_isolated(archive, state, directory, synthetic_identity=True)
        assert not (directory / "container-intent.json").exists()
    finally:
        archive.close()


def test_r4_restrict_preserves_unexpected_language_dependencies(pg, artifacts):
    db = database(pg, "r4_restrict_source")
    pg.sql(db, "DROP EXTENSION plpgsql; CREATE EXTENSION plpgsql")
    directory = private_test_directory(artifacts, "r4_restrict")
    archive, state = backup.export_synthetic_database(pg, db, directory)
    try:
        target = database(pg, "r4_restrict_target")
        pg.sql(target, "CREATE FUNCTION synthetic_dependency() RETURNS int LANGUAGE plpgsql AS 'BEGIN RETURN 1; END'")
        with pytest.raises(backup.BackupError, match="child_failed"):
            backup.RestoreIdentityProfile.prepare(archive, state, pg, target, time.monotonic()+60)
        assert pg.sql(target, "SELECT synthetic_dependency()").strip() == b"1"
        assert pg.sql(target, "SELECT count(*) FROM pg_extension WHERE extname='plpgsql'").strip() == b"1"
        assert not list(directory.glob("restore-preparation-*.json"))
        archive.verify()
    finally:
        archive.close()


def r5_source(pg, *, populated_data=False, recreate_language=False):
    db = populated(pg) if populated_data else database(pg, "r5_source")
    owner = "r5_owner_"+secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {owner} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; "
        f"ALTER DATABASE {db} OWNER TO {owner}")
    if recreate_language:
        pg.sql(db, "DROP EXTENSION plpgsql RESTRICT; CREATE EXTENSION plpgsql")
    pg.sql(db, f"SET ROLE {owner}; CREATE EXTENSION pgcrypto WITH SCHEMA public VERSION '1.4'; RESET ROLE")
    return db, owner


@pytest.mark.parametrize("damage", ["none", "version", "catalog", "controls", "requires", "roles", "create",
    "database_owner", "extension_version", "extension_schema", "missing_extension", "unknown_member",
    "third_owner", "initial_acl", "incomplete"])
def test_r5_real_profile_and_failclosed_validation(pg, damage):
    db, owner = r5_source(pg)
    if damage == "initial_acl":
        pg.sql(db, "ALTER EXTENSION pgcrypto DROP FUNCTION digest(text,text); "
            "REVOKE ALL ON FUNCTION digest(text,text) FROM PUBLIC; ALTER EXTENSION pgcrypto ADD FUNCTION digest(text,text)")
        with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
            catalog = backup.SchemaEvidence.collect(snap)
            assert any(row["fields"]["initial_acl"] for row in catalog["objects"].values())
            with pytest.raises(backup.BackupError, match="mixed_profile_member_ownership"):
                backup.MixedRestoreIdentityProfile.collect(snap, catalog)
        return
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        catalog = backup.SchemaEvidence.collect(snap)
        profile = backup.MixedRestoreIdentityProfile.collect(snap, catalog)
    assert backup.MixedRestoreIdentityProfile.select(profile, catalog) == pg.bootstrap
    assert profile["database_owner"] == owner and profile["roles"][owner]["superuser"] is False
    with pytest.raises(backup.BackupError, match="restore_profile_version_binding"):
        backup.RestoreIdentityProfile.select(profile, catalog)
    if damage == "none":
        return
    if damage == "version":
        profile["version"] = True
    elif damage == "catalog":
        profile["catalog_sha256"] = "0"*64
    elif damage == "controls":
        profile["controls"][0]["trusted"] = False
    elif damage == "requires":
        profile["controls"][0]["requires"] = ["unknown"]
    elif damage == "roles":
        profile["roles"][owner]["superuser"] = True
    elif damage == "create":
        profile["owner_create"] = False
    elif damage == "database_owner":
        profile["database_owner"] = pg.bootstrap
    elif damage == "extension_version":
        profile["extensions"][0]["version"] = "unsupported"
    elif damage == "extension_schema":
        profile["extensions"][0]["schema"] = "unknown"
    elif damage == "missing_extension":
        profile["extensions"].pop()
    else:
        member = next(row for row in catalog["objects"].values()
                      if ["e", "extension", "pgcrypto"] in row["fields"]["dependencies"])
        if damage == "unknown_member":
            member["identity"] = "unknown_function()"
        elif damage == "third_owner":
            member["fields"]["owner"] = "unrelated_role"
        else:
            catalog["complete"] = False
        profile["catalog_sha256"] = backup.canonical_hash(catalog)
    with pytest.raises(backup.BackupError, match="mixed_"):
        backup.MixedRestoreIdentityProfile.select(profile, catalog)


@pytest.mark.parametrize("damage", ["replacement", "mode", "missing_binding", "v1_reader", "both_modes", "source_kind"])
def test_r5_private_profile_custody_before_restore(pg, artifacts, damage):
    db, _ = r5_source(pg)
    directory = private_test_directory(artifacts, "r5_custody")
    archive, state = backup.export_synthetic_database(pg, db, directory, mixed_identity=True)
    try:
        value, _ = backup.MixedRestoreIdentityProfile.read(archive, state)
        assert value["source_kind"] == "r5-owned-synthetic"
        path = directory / backup.MixedRestoreIdentityProfile.FILE
        if damage == "replacement":
            path.rename(directory / "original-profile.json")
            backup.private_json(path, value)
        elif damage == "mode":
            path.chmod(0o644)
        elif damage == "missing_binding":
            archive.restore_identity_binding = None
        elif damage == "source_kind":
            value["source_kind"] = "current-source"
            path.write_text(json.dumps(value))
        before = pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database")
        with pytest.raises((backup.BackupError, OSError)):
            if damage == "v1_reader":
                backup.RestoreIdentityProfile.read(archive, state)
            else:
                backup.verify_restore(archive, state, pg, mixed_identity=True, synthetic_identity=damage == "both_modes")
        assert pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database") == before
        assert not list(directory.glob("schema-comparison-*.json"))
    finally:
        archive.close()


@pytest.mark.parametrize("damage,code", [("extension", "mixed_target_not_pristine"),
    ("function", "mixed_target_not_pristine"), ("public_create", "mixed_target_schema_unsafe"),
    ("installer_login", "mixed_target_installer_privileges"), ("no_create", "mixed_target_create_required"),
    ("consumed", "mixed_profile_target_identity"), ("timeout", "snapshot_expired")])
def test_r5_real_target_guards(pg, artifacts, damage, code):
    db, owner = r5_source(pg)
    directory = private_test_directory(artifacts, "r5_target_guard")
    archive, state = backup.export_synthetic_database(pg, db, directory, mixed_identity=True)
    target = database(pg, "r5_target_guard")
    pg.sql(target, f"ALTER DATABASE {target} OWNER TO {owner}")
    try:
        if damage == "extension":
            pg.sql(target, f"SET ROLE {owner}; CREATE EXTENSION pgcrypto; RESET ROLE")
        elif damage == "function":
            pg.sql(target, "CREATE FUNCTION unexpected() RETURNS int LANGUAGE SQL AS 'SELECT 1'")
        elif damage == "public_create":
            pg.sql(target, "GRANT CREATE ON SCHEMA public TO PUBLIC")
        elif damage == "installer_login":
            pg.sql(target, f"ALTER ROLE {owner} LOGIN")
        elif damage == "no_create":
            pg.sql(target, f"ALTER DATABASE {target} OWNER TO {pg.bootstrap}; REVOKE CREATE ON DATABASE {target} FROM {owner}")
        elif damage == "consumed":
            pg.fresh_targets.remove(target)
        deadline = time.monotonic()-1 if damage == "timeout" else time.monotonic()+60
        before = pg.sql(target, "SELECT json_agg(extname ORDER BY extname) FROM pg_extension")
        with pytest.raises(backup.BackupError, match=code):
            backup.MixedRestoreIdentityProfile.prepare(archive, state, pg, target, deadline)
        assert pg.sql(target, "SELECT json_agg(extname ORDER BY extname) FROM pg_extension") == before
        assert pg.sql(target, "SELECT current_user").strip().decode() == pg.bootstrap
        assert not list(directory.glob("restore-preparation-*.json"))
        archive.verify()
    finally:
        if damage == "installer_login":
            pg.sql(target, f"ALTER ROLE {owner} NOLOGIN")
        archive.close()


def test_r5_default_privileges_make_target_nonpristine(pg, artifacts):
    db, owner = r5_source(pg)
    directory = private_test_directory(artifacts, "r5_sql_failure")
    archive, state = backup.export_synthetic_database(pg, db, directory, mixed_identity=True)
    target = database(pg, "r5_sql_failure")
    pg.sql(target, f"ALTER DATABASE {target} OWNER TO {owner}")
    # Real unexpected default privileges must reject before any installation.
    try:
        pg.sql(target, "CREATE ROLE r5_dead_acl NOLOGIN; "
            "ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO r5_dead_acl")
        with pytest.raises(backup.BackupError, match="mixed_target_not_pristine"):
            backup.MixedRestoreIdentityProfile.prepare(archive, state, pg, target, time.monotonic()+60)
        assert pg.sql(target, "SELECT count(*) FROM pg_extension WHERE extname='pgcrypto'").strip() == b"0"
        assert pg.sql(target, "SELECT current_user").strip().decode() == pg.bootstrap
        archive.verify()
    finally:
        archive.close()


def test_r5_real_source_profile_drift_rejects_export(pg, artifacts):
    db, _ = r5_source(pg)
    directory = private_test_directory(artifacts, "r5_drift")
    def command(tool, *args):
        if tool == "pg_dump" and "--format=custom" in args:
            pg.sql(db, f"ALTER DATABASE {db} OWNER TO {pg.bootstrap}")
        return pg.command(tool, db, *args)
    with pytest.raises(backup.BackupError, match="source_ddl_or_sequence_drift"):
        backup.export_database(command, directory, _synthetic_source={"container": pg.cid, "database": db}, _mixed_identity=True)
    assert not (directory / backup.MixedRestoreIdentityProfile.FILE).exists()


def test_r5_explicit_export_and_legacy_guards(pg, artifacts):
    db = database(pg, "r5_legacy")
    directory = private_test_directory(artifacts, "r5_legacy")
    with pytest.raises(backup.BackupError, match="synthetic_source_required"):
        backup.export_synthetic_database(backup.LiveSource, db, directory, mixed_identity=True)
    with pytest.raises(backup.BackupError, match="synthetic_source_required"):
        backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory, _mixed_identity=True)
    with pytest.raises(backup.BackupError, match="synthetic_mode_invalid"):
        backup.export_synthetic_database(pg, db, directory, mixed_identity=1)
    archive, state = backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory)
    try:
        with pytest.raises(backup.BackupError, match="synthetic_restore_profile_required"):
            backup.restore_isolated(archive, state, directory, mixed_identity=True)
        assert not (directory / "container-intent.json").exists()
    finally:
        archive.close()


def r6_catalog(pg, db):
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        catalog = backup.SchemaEvidence.collect(snap)
        rows = backup.ExtensionMemberComments.collect(snap, catalog)
        state = backup.DatabaseState.collect(snap, lambda tool, *args: pg.command(tool, db, *args))
    return catalog, rows, state


@pytest.mark.parametrize("case", ["default", "unicode", "removed", "single_limit", "single_over", "total_over"])
def test_r6_real_member_collection_and_limits(pg, case):
    db, _ = r5_source(pg)
    if case == "unicode":
        pg.sql(db, "COMMENT ON FUNCTION digest(text,text) IS "+backup.literal("合成註解\n'quoted' \\ path ; SELECT 1;"))
    elif case == "removed":
        pg.sql(db, "COMMENT ON LANGUAGE plpgsql IS ''; COMMENT ON FUNCTION digest(text,text) IS NULL")
    elif case in ("single_limit", "single_over"):
        body = "測" * 21845 + ("x" if case == "single_limit" else "xy")
        pg.sql(db, "COMMENT ON FUNCTION digest(text,text) IS "+backup.literal(body))
    elif case == "total_over":
        _, rows, _ = r6_catalog(pg, db)
        pg.sql(db, "; ".join("COMMENT ON "+backup.ExtensionMemberComments.target_sql(r["target"])+" IS "+
            backup.literal("s"*32768) for r in rows.values()))
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        catalog = backup.SchemaEvidence.collect(snap)
        if case in ("single_over", "total_over"):
            with pytest.raises(backup.BackupError, match="member_comments_too_large"):
                backup.ExtensionMemberComments.collect(snap, catalog)
            return
        rows = backup.ExtensionMemberComments.collect(snap, catalog)
    assert len(rows) == 41 and sum(r["kind"] == "routine" for r in rows.values()) == 40
    assert all(r["comment"] == catalog["objects"][k]["fields"]["comment"] for k, r in rows.items())
    if case == "removed":
        language = next(r for r in rows.values() if r["kind"] == "language")
        assert language["body"] is None and language["comment"]["state"] == "absent"
    if case == "single_limit":
        assert max(r["bytes"] for r in rows.values()) == 65536


@pytest.mark.parametrize("damage", ["missing", "replacement", "mode", "hardlink", "symlink", "body", "version",
                                    "source", "identity", "binding", "unbound", "both_modes"])
def test_r6_real_private_comment_custody_rejects_before_target(pg, artifacts, damage):
    db, _ = r5_source(pg)
    directory = private_test_directory(artifacts, "r6_custody")
    archive, state = backup.export_synthetic_database(pg, db, directory, mixed_identity=True, member_comments=True)
    try:
        value = backup.ExtensionMemberComments.read(archive, state)
        path = directory / backup.ExtensionMemberComments.FILE
        before = pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database")
        if damage == "missing":
            path.rename(directory / "retained-comments.json")
        elif damage in ("replacement", "symlink"):
            original = directory / "retained-comments.json"
            path.rename(original)
            if damage == "symlink":
                path.symlink_to(original)
            else:
                backup.private_json(path, value)
        elif damage == "mode":
            path.chmod(0o644)
        elif damage == "hardlink":
            os.link(path, directory / "second-link.json")
        elif damage == "unbound":
            archive.member_comments_binding = None
        elif damage != "both_modes":
            if damage == "body":
                next(iter(value["members"].values()))["body"] = "tampered actual file"
                value["members_sha256"] = backup.canonical_hash(value["members"])
            elif damage == "version":
                value["version"] = 2
            elif damage == "source":
                value["source_kind"] = "current-source"
            elif damage == "identity":
                next(iter(value["members"].values()))["target"]["name"] = "other_function"
            else:
                value["profile_sha256"] = "0"*64
            path.write_text(json.dumps(value))  # Real untrusted artifact mutation, never a passing fixture.
        with pytest.raises((backup.BackupError, OSError)):
            backup.verify_restore(archive, state, pg, mixed_identity=True, member_comments=True,
                                  synthetic_identity=damage == "both_modes")
        assert pg.sql(db, "SELECT json_agg(datname ORDER BY datname) FROM pg_database") == before
        assert not list(directory.glob("schema-comparison-*.json"))
        archive.verify()
    finally:
        archive.close()


@pytest.mark.parametrize("damage", ["body", "bytes", "state", "shape", "duplicate", "target_kind", "target_args",
                                    "empty_identifier", "version", "inventory", "unsupported_body"])
def test_r6_comment_validator_rejects_untrusted_changes(pg, damage):
    db, _ = r5_source(pg)
    catalog, rows, _ = r6_catalog(pg, db)
    r = next(r for r in rows.values() if r["kind"] == "routine")
    if damage == "body":
        r["body"] = "changed body"
    elif damage == "bytes":
        r["bytes"] = True
    elif damage == "state":
        r["comment"]["state"] = "empty"
    elif damage == "shape":
        r["unexpected"] = 1
    elif damage == "duplicate":
        other = next(v for v in rows.values() if v is not r and v["kind"] == "routine")
        r["target"] = other["target"]
    elif damage == "target_kind":
        r["target"]["kind"] = "procedure"
    elif damage == "target_args":
        r["target"]["args"] = [["pg_catalog"]]
    elif damage == "empty_identifier":
        r["target"]["name"] = ""
    elif damage == "version":
        r["version"] = "unsupported"
    elif damage == "inventory":
        rows.pop(next(iter(rows)))
    else:
        r["body"] = ""
    with pytest.raises(backup.BackupError, match="member_"):
        backup.ExtensionMemberComments.validate(rows, catalog)


@pytest.mark.parametrize("change", ["member_comment", "outer_comment", "acl", "definition", "table", "owner", "typed"])
def test_r6_real_noncomment_differences_remain_rejected(pg, change):
    db, owner = r5_source(pg)
    original, expected, state = r6_catalog(pg, db)
    sql = {"member_comment": "COMMENT ON FUNCTION digest(text,text) IS 'actual new synthetic comment'",
        "outer_comment": "COMMENT ON EXTENSION pgcrypto IS 'must not repair outer comment'",
        "acl": "REVOKE EXECUTE ON FUNCTION digest(text,text) FROM PUBLIC",
        "definition": "ALTER FUNCTION digest(text,text) VOLATILE",
        "table": "CREATE TABLE extra(id int)",
        "owner": "ALTER FUNCTION digest(text,text) OWNER TO "+owner,
        "typed": "ALTER FUNCTION digest(text,text) RENAME TO renamed_digest"}[change]
    pg.sql(db, sql)
    if change == "typed":
        with pytest.raises(backup.BackupError, match="member_comments_inventory"):
            r6_catalog(pg, db)
        return
    current, actual, actual_state = r6_catalog(pg, db)
    if change == "member_comment":
        assert len(backup.ExtensionMemberComments.precheck(expected, actual, original, current, state, actual_state)) == 1
    else:
        with pytest.raises(backup.BackupError, match="member_comments_(state_differs|noncomment_difference)"):
            backup.ExtensionMemberComments.precheck(expected, actual, original, current, state, actual_state)
    # A well-formed but misdirected typed payload also cannot identify the target.
    if change == "member_comment":
        next(r for r in actual.values() if r["kind"] == "routine")["target"]["name"] = "not_same_target"
        with pytest.raises(backup.BackupError, match="member_comments_target_identity"):
            backup.ExtensionMemberComments.precheck(expected, actual, original, current, state, actual_state)


def test_r6_explicit_mode_and_consumed_target_guards(pg, artifacts):
    db, _ = r5_source(pg)
    directory = private_test_directory(artifacts, "r6_modes")
    for options in ({"member_comments": True}, {"member_comments": 1, "mixed_identity": True}):
        with pytest.raises(backup.BackupError, match="member_comments_mode"):
            backup.export_synthetic_database(pg, db, directory, **options)
    with pytest.raises(backup.BackupError, match="member_comments_mode"):
        backup.export_database(lambda *args: pg.command(*args), directory, _member_comments=True)
    archive, state = backup.export_synthetic_database(pg, db, directory, mixed_identity=True, member_comments=True)
    try:
        with pytest.raises(backup.BackupError, match="member_comments_target_not_owned"):
            backup.ExtensionMemberComments.replay(archive, state, pg, db, time.monotonic()+30)
        for function in (backup.verify_restore, backup.restore_isolated):
            with pytest.raises(backup.BackupError, match="member_comments_mode"):
                function(archive, state, pg, member_comments=True)
        assert not list(directory.glob("member-comments-replay-*.json"))
    finally:
        archive.close()


@pytest.mark.parametrize("failure", ["sql_error", "statement_timeout", "lock_timeout"])
def test_r6_real_comment_transaction_primitives_rollback(pg, failure):
    # Exercise the exact production begin/apply primitives using genuine PG;
    # the following deliberately failing SQL is test-only, never replay input.
    db, _ = r5_source(pg)
    original, rows, _ = r6_catalog(pg, db)
    first = next(r for r in rows.values() if r["target"].get("name") == "digest"
                 and r["target"].get("args") == [["pg_catalog", "text"], ["pg_catalog", "text"]])
    first = {**first, "body": "synthetic uncommitted first write"}
    blocker = None
    try:
        with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as tx:
            backup.ExtensionMemberComments.begin_write(tx)
            backup.ExtensionMemberComments.apply_rows(tx, [first])
            assert tx.query("SHOW transaction_read_only") == ["off"]
            with pytest.raises(backup.BackupError, match="snapshot_query_failed"):
                if failure == "sql_error":
                    tx.query("SELECT 1/0")
                elif failure == "statement_timeout":
                    tx.query("SELECT pg_sleep(11)")
                else:
                    blocker = backup.Snapshot(pg.command("psql", db, *backup.PSQL))
                    backup.ExtensionMemberComments.begin_write(blocker)
                    second = next(r for r in rows.values() if r["kind"] == "language")
                    backup.ExtensionMemberComments.apply_rows(blocker, [{**second, "body": "uncommitted blocker"}])
                    backup.ExtensionMemberComments.apply_rows(tx, [{**second, "body": "blocked write"}])
    finally:
        if blocker:
            blocker.close()
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        assert backup.SchemaEvidence.collect(snap) == original


@pytest.fixture
def r7_owned_database(pg):
    # The original suite retains its own sources until the final shared-lab
    # cleanup. New cases must not accumulate another twenty databases in the
    # same bounded 2GiB tmpfs. Remove ONLY this fixture's freshly created pair.
    db, owner = r5_source(pg)
    try:
        yield db, owner
    finally:
        pg.guard()
        assert db in pg.fresh_targets and db.startswith("v49b_r5_source_")
        assert owner.startswith("r5_owner_") and owner != pg.bootstrap
        backup.run(pg.docker("exec", pg.cid, "dropdb", "--no-password", "-U", pg.bootstrap, db))
        backup.run(pg.docker("exec", "-i", pg.cid, "psql", "--no-password", "-U", pg.bootstrap,
                            "-d", "postgres", *backup.PSQL), data=("DROP ROLE "+backup.quote_ident(owner)).encode())
        pg.fresh_targets.remove(db)


@pytest.mark.parametrize("damage", ["none", "uniform", "third_owner", "extra_member", "oversized"])
def test_r7_entry_compatibility(pg, r7_owned_database, damage):
    db, owner = r7_owned_database
    if damage == "uniform":
        pg.sql(db, "DROP EXTENSION pgcrypto; CREATE EXTENSION pgcrypto")
    elif damage == "third_owner":
        pg.sql(db, "ALTER FUNCTION digest(text,text) OWNER TO "+owner)
    elif damage == "extra_member":
        pg.sql(db, "CREATE FUNCTION r7_extra() RETURNS int LANGUAGE SQL AS 'SELECT 1'; "
                   "ALTER EXTENSION pgcrypto ADD FUNCTION r7_extra()")
    elif damage == "oversized":
        pg.sql(db, "COMMENT ON FUNCTION digest(text,text) IS "+backup.literal("a"*65537))
    with backup.Snapshot(pg.command("psql", db, *backup.PSQL)) as snap:
        if damage != "none":
            with pytest.raises(backup.BackupError, match="entry_compatibility"):
                backup.entry_compatibility(snap)
        else:
            before = backup.entry_compatibility(snap)
            assert before["contract"] == "r7" and before["server_version_num"] == 180004
            assert set(before) == {"contract", "server_version_num", "facts_sha256", "members_sha256", "controls_sha256", "bounds"}
            assert snap.value("SELECT to_json(current_setting('transaction_read_only'))") == "on"
            assert before == backup.entry_compatibility(snap)


@pytest.mark.parametrize("damage", ["none", "source", "profile", "comments", "claim", "missing", "replacement",
    "mode", "legacy", "callback", "repeat", "identity", "scope", "constructor", "live_missing_qualification"])
def test_r7_entry_custody_and_scope(pg, r7_owned_database, artifacts, damage):
    db, _ = r7_owned_database
    directory = private_test_directory(artifacts, "r7_entry_guard")
    if damage == "scope":
        with pytest.raises(backup.BackupError, match="entry_source_not_owned"):
            backup.BackupSourceEvidence.owned(pg, "nomosmart", directory)
        return
    if damage == "constructor":
        with pytest.raises(backup.BackupError, match="entry_factory_required"):
            backup.BackupSourceEvidence()
        with pytest.raises(backup.BackupError, match="entry_owned_source_required"):
            backup.BackupSourceEvidence.owned(backup.LiveSource, db, directory)
        return
    if damage == "live_missing_qualification":
        with pytest.raises(backup.BackupError, match="qualification_missing"):
            backup.BackupSourceEvidence.live(artifacts, "0"*64, True)
        with pytest.raises(backup.BackupError, match="plaintext_opt_in_required"):
            backup.BackupSourceEvidence.live(artifacts, "0"*64, False)
        return
    entry = backup.BackupSourceEvidence.owned(pg, db, directory)
    if damage == "callback":
        with pytest.raises(backup.BackupError, match="entry_export_arguments"):
            backup.export_database(backup.LiveSource.command, directory, _entry=entry)
        assert not (directory / "database.partial.dump").exists()
        return
    archive, state = backup.export_database(entry.command, directory, _entry=entry)
    try:
        assert backup.BoundRestoreIdentityProfile.read(archive, state)[1] == pg.bootstrap
        assert len(backup.BoundMemberComments.read(archive, state)["members"]) == 41
        assert not (directory / backup.MixedRestoreIdentityProfile.FILE).exists()
        if damage == "none":
            with pytest.raises(backup.BackupError, match="entry_binding_duplicate"):
                entry.bind_file("../escape.json", {})
            with pytest.raises(backup.BackupError, match="entry_binding_duplicate"):
                entry.bind_file("entry-claim.json", {})
            with pytest.raises(backup.BackupError, match="entry_tool_not_readonly"):
                entry.command("pg_restore")
            with pytest.raises(backup.BackupError, match="entry_source_cleanup_required"):
                backup.restore_isolated(archive, state, directory, _entry=entry)
            return
        if damage in ("source", "profile", "comments", "claim", "missing", "replacement"):
            name = {"source": entry.FILE, "profile": backup.BoundRestoreIdentityProfile.FILE,
                "comments": backup.BoundMemberComments.FILE, "claim": "entry-claim.json"}.get(damage, entry.FILE)
            path = directory / name
            value = backup.read_private_json(path)
            if damage in ("missing", "replacement"):
                path.rename(directory / ("original-"+name))
                if damage == "replacement":
                    backup.private_json(path, value)
            else:
                value["tampered"] = True
                path.write_text(json.dumps(value))
        elif damage == "identity":
            entry.identity["database"] = "nomosmart"
        elif damage == "repeat":
            with pytest.raises(backup.BackupError, match="entry_export_consumed"):
                backup.export_database(entry.command, directory, _entry=entry)
            return
        elif damage == "mode":
            with pytest.raises(backup.BackupError, match="entry_restore_arguments"):
                backup.verify_restore(archive, state, pg, mixed_identity=True, _entry=entry)
            return
        elif damage == "legacy":
            with pytest.raises(backup.BackupError, match="entry_explicit_restore_required"):
                backup.verify_restore(archive, state, pg)
            with pytest.raises(backup.BackupError, match="entry_explicit_finalization_required"):
                backup.finish_backup(archive, {}, directory, {}, backup.tool_sources())
            return
        with pytest.raises((backup.BackupError, FileNotFoundError)):
            backup.BoundMemberComments.read(archive, state)
    finally:
        archive.close()


def test_plain_final_fresh_cluster_roundtrip_and_cleanup(pg, artifacts):
    # Keep last among tests using pg: export our own synthetic source, remove
    # it, then restore in a NEW cluster. At most one PG exists at any instant.
    db = populated(pg)
    role = "fresh_owner_"+secrets.token_hex(4)
    reader = "fresh_reader_"+secrets.token_hex(4)
    pg.sql(db, f"CREATE ROLE {role} NOLOGIN; CREATE ROLE {reader} NOLOGIN; "
        f"ALTER DATABASE {db} OWNER TO {role}; ALTER TABLE test.items OWNER TO {role}; "
        f"GRANT SELECT ON test.items TO {reader}; GRANT CONNECT ON DATABASE {db} TO {reader}; "
        f"GRANT SELECT ON LARGE OBJECT 123456 TO {reader}")
    identity = {"kind": "isolated-synthetic-postgresql", "container_id": pg.cid,
                "database": db, "image": backup.PG_IMAGE}
    directory = private_test_directory(artifacts, "fresh_cluster")
    archive, state = backup.export_database(lambda tool, *args: pg.command(tool, db, *args), directory)
    try:
        # Simulate interruption in the window before the final receipt exists:
        # recover the actual owned source via its pre-create intent, not a mock.
        (artifacts / "container-receipt.json").rename(artifacts / "retained-container-receipt.json")
        backup.recover_test_resources(artifacts)
        pg.cid = None  # Actual container was removed by intent-bound recovery.
        assert pg.inventory() == pg.baseline
        outcome = backup.restore_isolated(archive, state, directory)
        assert backup.read_private_json(directory / "restore-proof.json")["cleanup_ok"]
        with pytest.raises(backup.BackupError, match="source_changed"):
            backup.finish_backup(archive, outcome, directory, identity, {})
        with pytest.raises(backup.BackupError, match="restore_proof_mismatch"):
            backup.finish_backup(archive, {**outcome, "full_comparison": False}, directory, identity, backup.tool_sources())
        result = backup.finish_backup(archive, outcome, directory, identity, backup.tool_sources())
        assert result["status"] == "PASS" and result["encrypted"] is False
        assert result["source"] == identity and result["verification"]["full_comparison"]
        assert (directory / "database.dump").exists()
        assert backup.read_private_json(directory / "result.json") == result
        backup.main(["--cleanup-test", str(artifacts)])
        assert pg.inventory() == pg.baseline
    finally:
        archive.close()


def test_extension_owner_is_preserved_by_full_restore(artifacts):
    # Original T15 scenario and success assertion retained. Source is removed
    # BEFORE the fresh restore cluster: never two owned PostgreSQL containers.
    directory = private_test_directory(artifacts, "extension_owner")
    source_dir = private_test_directory(directory, "source")
    pg = backup.MemoryPostgres(source_dir)
    archive = None
    schema_args = ("--schema-only", "--quote-all-identifiers", "--encoding=UTF8",
                   "--restrict-key="+backup.RESTRICT_KEY)
    try:
        pg.start()
        db = database(pg, "extension_owner")
        owner = "extension_owner_"+secrets.token_hex(4)
        pg.sql(db, f"CREATE ROLE {owner} SUPERUSER NOLOGIN; ALTER DATABASE {db} OWNER TO {owner}; "
            "DROP EXTENSION plpgsql; "
            f"SET ROLE {owner}; CREATE EXTENSION plpgsql; CREATE EXTENSION pgcrypto; "
            "CREATE TABLE synthetic_items(id integer PRIMARY KEY, body text); "
            "INSERT INTO synthetic_items VALUES (1,'synthetic extension ownership'); RESET ROLE")
        source_schema = backup.run(pg.command("pg_dump", db, *schema_args)).decode()
        archive, state = backup.export_synthetic_database(pg, db, directory)
    finally:
        pg.cleanup()
    try:
        profile, bootstrap = backup.RestoreIdentityProfile.read(archive, state)
        assert bootstrap == owner and bootstrap != pg.bootstrap
        target_dir = private_test_directory(directory, "restore")
        restored = backup.MemoryPostgres(target_dir, bootstrap=bootstrap)
        try:
            restored.start()
            target = database(restored, "extension_restore")
            backup.DatabaseState.provision_restore(restored, target, state)
            backup.RestoreIdentityProfile.prepare(archive, state, restored, target, time.monotonic()+600)
            archive.restore(restored.empty_restore(target), time.monotonic()+600)
            command = lambda tool, *args: restored.command(tool, target, *args)
            with backup.Snapshot(command("psql", *backup.PSQL)) as snap:
                actual = backup.DatabaseState.collect(snap, command)
                actual_objects = backup.SchemaEvidence.collect(snap)
            original = backup.SchemaEvidence.read(archive, state)
            comparison = backup.SchemaEvidence.diff(original["evidence"], actual_objects)
            backup.private_json(directory / "object-comparison.json", comparison)
            restored_schema = backup.run(command("pg_dump", *schema_args)).decode()
            backup.private_json(directory / "comparison-diagnostic.json", {
                "source_kind": "synthetic", "equal_categories": {key: actual[key] == state[key] for key in state},
                "synthetic_schema_diff": list(difflib.unified_diff(source_schema.splitlines(), restored_schema.splitlines()))})
            assert actual == state
            assert comparison["status"] == "EQUAL"
            assert restored.sql(target, "SELECT count(*) FROM pg_roles WHERE rolsuper").strip() == b"1"
            assert backup.read_private_json(next(directory.glob("restore-preparation-*.json")))["plpgsql_recreated"]
        finally:
            restored.cleanup()
        assert pg.inventory() == pg.baseline
        backup.private_json(directory / "cleanup.json", {"cleanup_ok": True, "baseline_equal": True,
            "profile_sha256": backup.canonical_hash(profile), "sources": backup.tool_sources()})
    finally:
        if archive:
            archive.close()


@pytest.mark.parametrize("bootstrap", ["backup_verify", "r4_named_bootstrap"])
def test_r4_default_and_named_identity_fresh_restore(artifacts, bootstrap):
    directory = private_test_directory(artifacts, "r4_default")
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap=bootstrap)
    archive = None
    try:
        source.start()
        db = populated(source)
        reader = "limited_reader_"+secrets.token_hex(4)
        source.sql(db, f"CREATE ROLE {reader} NOLOGIN; GRANT SELECT ON test.items TO {reader}")
        archive, state = backup.export_synthetic_database(source, db, directory)
    finally:
        source.cleanup()
    try:
        target_dir = private_test_directory(directory, "restore")
        result = backup.restore_isolated(archive, state, target_dir, synthetic_identity=True)
        assert result["full_comparison"] is True
        comparison = backup.read_private_json(next(directory.glob("schema-comparison-*.json")))
        assert all(comparison["categories"].values()) and comparison["catalog"]["status"] == "EQUAL"
        preparation = backup.read_private_json(next(directory.glob("restore-preparation-*.json")))
        assert preparation["plpgsql_recreated"] is False and preparation["archive_filtered"] is False
        assert backup.read_private_json(target_dir / "container-receipt.json")["bootstrap"] == bootstrap
        assert backup.read_private_json(target_dir / "restore-proof.json")["cleanup_ok"] is True
        assert not (directory / "forbidden").exists() and not (backup.ROOT / "forbidden").exists()
        assert source.inventory() == source.baseline
    finally:
        archive.close()


def test_r4_named_bootstrap_interrupt_recovery_and_limited_roles(artifacts):
    directory = private_test_directory(artifacts, "r4_interrupt")
    lab = backup.MemoryPostgres(directory, bootstrap="r4_initial_"+secrets.token_hex(4))
    try:
        lab.start()
        db = database(lab, "r4_roles")
        reader = "r4_limited_"+secrets.token_hex(4)
        # Capture a genuine DB state referencing a role, drop the source objects
        # and role, then provision in a fresh empty DB with only limited grants.
        lab.sql(db, f"CREATE ROLE {reader} NOLOGIN; CREATE TABLE items(id int); GRANT SELECT ON items TO {reader}")
        with backup.Snapshot(lab.command("psql", db, *backup.PSQL)) as snap:
            state = backup.DatabaseState.collect(snap, lambda tool, *args: lab.command(tool, db, *args))
        target = database(lab, "r4_roles_target")
        with pytest.raises(backup.BackupError, match="restore_role_collision"):
            backup.DatabaseState.provision_restore(lab, target, state)
        lab.sql(target, f"DROP DATABASE {db}; DROP ROLE {reader}")
        backup.DatabaseState.provision_restore(lab, target, state)
        assert lab.sql(target, "SELECT count(*) FROM pg_roles WHERE rolsuper").strip() == b"1"
        assert lab.sql(target, f"SELECT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
            f"FROM pg_roles WHERE rolname='{reader}'").strip() == b"f"
        (directory / "container-receipt.json").rename(directory / "retained-receipt.json")
        backup.recover_test_resources(directory)  # Actual interruption before receipt.
        lab.cid = None
        assert lab.inventory() == lab.baseline
        backup.private_json(directory / "cleanup.json", {"cleanup_ok": True, "baseline_equal": True,
            "sources": backup.tool_sources(), "bootstrap_sha256": backup.canonical_hash(lab.bootstrap)})
    finally:
        lab.cleanup()


@pytest.mark.parametrize("recreate_language", [False, True])
def test_r5_trusted_mixed_owner_fresh_roundtrip(artifacts, recreate_language):
    directory = private_test_directory(artifacts, "r5_roundtrip")
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="r5_bootstrap")
    archive = None
    try:
        source.start()
        db, owner = r5_source(source, populated_data=True, recreate_language=recreate_language)
        reader = "r5_reader_"+secrets.token_hex(4)
        source.sql(db, f"CREATE ROLE {reader} NOLOGIN; ALTER TABLE test.items OWNER TO {owner}; "
            f"GRANT CONNECT ON DATABASE {db} TO {reader}; GRANT SELECT ON test.items TO {reader}; "
            f"GRANT SELECT ON LARGE OBJECT 123456 TO {reader}; "
            "COMMENT ON EXTENSION pgcrypto IS 'synthetic trusted A/B extension'; "
            "COMMENT ON FUNCTION digest(text,text) IS 'synthetic member comment'; "
            "REVOKE EXECUTE ON FUNCTION digest(text,text) FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION digest(text,text) TO {reader}")
        archive, state = backup.export_synthetic_database(source, db, directory, mixed_identity=True, member_comments=True)
    finally:
        source.cleanup()
    try:
        result = backup.restore_isolated(archive, state, private_test_directory(directory, "restore"),
                                        mixed_identity=True, member_comments=True)
        assert result["full_comparison"] and result["large_objects"] == 1 and result["rows"] == 2
        report = backup.read_private_json(next(directory.glob("schema-comparison-*.json")))
        assert all(report["categories"].values()) and report["catalog"]["status"] == "EQUAL"
        preparation = backup.read_private_json(next(directory.glob("restore-preparation-*.json")))
        assert preparation["pgcrypto_precreated"] and preparation["role_reset"]
        assert preparation["plpgsql_recreated"] == recreate_language and not preparation["archive_filtered"]
        assert source.inventory() == source.baseline
        assert not (directory / "qualified.json").exists()
    finally:
        if archive:
            archive.close()


@pytest.mark.parametrize("recreate_language", [False, True])
def test_r5_mixed_owner_baseline_without_member_customization(artifacts, recreate_language):
    # Additional baseline, not a replacement for the two failing custom-member
    # comment cases above. Their original strict success assertions remain.
    directory = private_test_directory(artifacts, "r5_baseline")
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="r5_baseline_bootstrap")
    archive = None
    try:
        source.start()
        db, owner = r5_source(source, populated_data=True, recreate_language=recreate_language)
        reader = "r5_baseline_reader_"+secrets.token_hex(4)
        source.sql(db, f"CREATE ROLE {reader} NOLOGIN; ALTER TABLE test.items OWNER TO {owner}; "
            f"GRANT SELECT ON test.items TO {reader}; GRANT SELECT ON LARGE OBJECT 123456 TO {reader}; "
            "COMMENT ON EXTENSION pgcrypto IS 'synthetic outer extension comment'; "
            "REVOKE EXECUTE ON FUNCTION digest(text,text) FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION digest(text,text) TO {reader}")
        archive, state = backup.export_synthetic_database(source, db, directory, mixed_identity=True)
    finally:
        source.cleanup()
    try:
        result = backup.restore_isolated(archive, state, private_test_directory(directory, "restore"), mixed_identity=True)
        assert result["full_comparison"] and result["rows"] == 2 and result["large_objects"] == 1
        report = backup.read_private_json(next(directory.glob("schema-comparison-*.json")))
        assert all(report["categories"].values()) and report["catalog"]["status"] == "EQUAL"
        preparation = backup.read_private_json(next(directory.glob("restore-preparation-*.json")))
        assert preparation["plpgsql_recreated"] == recreate_language
        assert preparation["pgcrypto_precreated"] and preparation["role_reset"] and not preparation["archive_filtered"]
        assert source.inventory() == source.baseline
    finally:
        if archive:
            archive.close()


@pytest.mark.parametrize("remove_language", [False, True])
def test_r6_special_comment_fresh_roundtrip_and_legacy_rejection(artifacts, remove_language):
    directory = private_test_directory(artifacts, "r6_special")
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="r6_initial")
    archive = None
    try:
        source.start()
        db, _ = r5_source(source, populated_data=True, recreate_language=remove_language)
        body = "合成註解\n''quoted'' \\path \\n ; COMMIT; DROP TABLE test.items; -- 文字不是SQL"
        source.sql(db, "COMMENT ON FUNCTION digest(text,text) IS "+backup.literal(body)+"; "
            "COMMENT ON FUNCTION digest(bytea,text) IS "+backup.literal("不同overload\n"+body)+"; "
            "COMMENT ON FUNCTION plpgsql_call_handler() IS NULL; "
            "COMMENT ON LANGUAGE plpgsql IS "+("NULL" if remove_language else backup.literal("language "+body)))
        archive, state = backup.export_synthetic_database(source, db, directory, mixed_identity=True, member_comments=True)
    finally:
        source.cleanup()
    try:
        # Same genuine archive: the legacy mode must NOT silently use the new
        # sidecar; its separate fresh target is discarded before the R6 target.
        with pytest.raises(backup.BackupError, match="restored_schema_evidence_differs"):
            backup.restore_isolated(archive, state, private_test_directory(directory, "legacy_restore"), mixed_identity=True)
        outcome = backup.restore_isolated(archive, state, private_test_directory(directory, "r6_restore"),
                                         mixed_identity=True, member_comments=True)
        assert outcome["full_comparison"] and outcome["rows"] == 2 and outcome["large_objects"] == 1
        replay = backup.read_private_json(next(directory.glob("member-comments-replay-*.json")))
        assert replay["status"] == "PASS" and replay["changed"] >= 3 and replay["members"] == 41
        assert source.inventory() == source.baseline
    finally:
        if archive:
            archive.close()


@pytest.mark.parametrize("phase", ["install", "comments"])
def test_r6_real_midtransaction_cancellation_and_target_consumption(artifacts, phase):
    real_midtransaction_cancellation(artifacts, phase, entry_mode=False)


@pytest.mark.parametrize("phase", ["install", "comments"])
def test_r7_entry_cancellation(artifacts, phase):
    real_midtransaction_cancellation(artifacts, phase, entry_mode=True)


def real_midtransaction_cancellation(artifacts, phase, *, entry_mode):
    directory = private_test_directory(artifacts, ("r7" if entry_mode else "r6")+"_cancel_"+phase)
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="r6_cancel_initial")
    archive = None
    try:
        source.start()
        db, _ = r5_source(source)
        _, rows, _ = r6_catalog(source, db)
        source.sql(db, "; ".join("COMMENT ON "+backup.ExtensionMemberComments.target_sql(r["target"])+" IS "+
            backup.literal("synthetic transaction cancellation "+str(i)) for i, r in enumerate(rows.values())))
        if entry_mode:
            entry = backup.BackupSourceEvidence.owned(source, db, directory)
            archive, state = backup.export_database(entry.command, directory, _entry=entry)
        else:
            archive, state = backup.export_synthetic_database(source, db, directory, mixed_identity=True, member_comments=True)
    finally:
        source.cleanup()
    lab = backup.MemoryPostgres(private_test_directory(directory, "restore"), bootstrap="r6_cancel_initial")
    watcher = None
    try:
        lab.start()
        control_db = database(lab, "cancellation_control")
        lab.sql(control_db, "CREATE TABLE observed(pid int,dbname text,write_xid bool,cancelled bool)")
        application = "v49b-trusted-install" if phase == "install" else "v49b-member-comments"
        # A real observer in ANOTHER owned database (not an unexpected target
        # client). It cancels only this run's named operation AFTER a write XID
        # exists, proving this is not a synthetic precheck/deadline failure.
        sql = """SET statement_timeout='25s'; DO $watch$ DECLARE v record; selected_pid int;
            finish timestamptz := clock_timestamp()+interval '20 seconds'; BEGIN
            WHILE clock_timestamp()<finish LOOP
              PERFORM pg_stat_clear_snapshot();
              SELECT pid,datname,backend_xid FROM pg_stat_activity WHERE application_name="""+backup.literal(application)+"""
                AND datname LIKE 'v49b_restored_%' AND backend_type='client backend'
                AND backend_xid IS NOT NULL AND state='active' AND pid<>pg_backend_pid()
                AND (selected_pid IS NULL OR pid=selected_pid) LIMIT 1 INTO v;
              IF FOUND THEN
                selected_pid := v.pid;
                INSERT INTO observed SELECT v.pid,v.datname,v.backend_xid IS NOT NULL,pg_cancel_backend(v.pid);
              ELSIF selected_pid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM pg_stat_activity
                  WHERE pid=selected_pid AND backend_xid IS NOT NULL) THEN EXIT;
              END IF;
              PERFORM pg_sleep(0.0001);
            END LOOP; END $watch$;
            SELECT coalesce(jsonb_agg(to_jsonb(observed)),'[]') FROM observed;"""
        watcher = subprocess.Popen(lab.command("psql", control_db, *backup.PSQL), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=backup.clean_env(), start_new_session=True)
        watcher.stdin.write(sql.encode()); watcher.stdin.close()
        # Wait for actual server observation to be armed, not an assumed sleep.
        until = time.monotonic()+5
        while time.monotonic() < until:
            if lab.sql(control_db, "SELECT count(*) FROM pg_stat_activity WHERE datname="+backup.literal(control_db)+
                       " AND query LIKE '%$watch$%' AND state='active' AND pid<>pg_backend_pid()").strip() == b"1":
                break
        else:
            pytest.fail("real cancellation observer did not become active")
        with pytest.raises(backup.BackupError, match="child_failed|snapshot_query_failed"):
            backup.verify_restore(archive, state, lab, **({"_entry": entry} if entry_mode else
                                  {"mixed_identity": True, "member_comments": True}))
        watcher.wait(timeout=25)
        assert watcher.returncode == 0
        observed = json.loads(watcher.stdout.read())
        assert observed and all(o["write_xid"] and o["cancelled"] for o in observed)
        assert len({o["pid"] for o in observed}) == 1
        target = observed[0]["dbname"]
        assert target not in lab.fresh_targets and target not in lab.comment_targets
        assert lab.sql(target, "SELECT current_user").strip().decode() == lab.bootstrap
        if phase == "install":
            assert lab.sql(target, "SELECT count(*) FROM pg_extension WHERE extname='pgcrypto'").strip() == b"0"
            with pytest.raises(backup.BackupError, match="mixed_profile_target_identity"):
                profile_type = backup.BoundRestoreIdentityProfile if entry_mode else backup.MixedRestoreIdentityProfile
                profile_type.prepare(archive, state, lab, target, time.monotonic()+30)
        else:
            # Every custom body was absent from dump. After a real mid-write
            # cancel, none may remain committed. This query returns only count.
            assert lab.sql(target, "SELECT count(*) FROM pg_description WHERE description LIKE 'synthetic transaction cancellation %'").strip() == b"0"
            with pytest.raises(backup.BackupError, match="member_comments_target_not_owned"):
                comment_type = backup.BoundMemberComments if entry_mode else backup.ExtensionMemberComments
                comment_type.replay(archive, state, lab, target, time.monotonic()+30)
            report = backup.read_private_json(next(directory.glob("member-comments-replay-*.json")))
            assert report["status"] == "ERROR" and report["phase"] == "comment"
        archive.verify()
        backup.private_json(directory / "cancellation-evidence.json", {"phase": phase,
            "observed_write_transaction": True, "cancelled": True, "rollback_verified": True,
            "target_consumed": True, "sources": backup.tool_sources()})
    finally:
        if watcher:
            backup.stop_process(watcher)
            watcher.stdout.close()
        lab.cleanup()
        if archive:
            archive.close()
    assert source.inventory() == source.baseline


def r7_roundtrip_evidence(artifacts, mode):
    directory = private_test_directory(artifacts, "r7_roundtrip_"+mode)
    source = backup.MemoryPostgres(private_test_directory(directory, "source"), bootstrap="r7_roundtrip_bootstrap")
    archive = None
    try:
        try:
            source.start()
            db, owner = r5_source(source, populated_data=True, recreate_language=mode == "removed")
            source.sql(db, "ALTER TABLE test.items OWNER TO "+owner)
            if mode == "custom":
                source.sql(db, "COMMENT ON FUNCTION digest(text,text) IS "+backup.literal("真實合成\n'quoted' \\path; --")+"; "
                    "COMMENT ON FUNCTION digest(bytea,text) IS 'overloaded function'; "
                    "REVOKE EXECUTE ON FUNCTION digest(text,text) FROM PUBLIC")
            elif mode == "removed":
                source.sql(db, "COMMENT ON LANGUAGE plpgsql IS NULL; COMMENT ON FUNCTION plpgsql_call_handler() IS NULL")
            entry = backup.BackupSourceEvidence.owned(source, db, directory)
            archive, state = backup.export_database(entry.command, directory, _entry=entry)
        finally:
            source.cleanup()
        outcome = backup.restore_isolated(archive, state, private_test_directory(directory, "restore"), _entry=entry)
        entry.postflight()
        assert source.inventory() == source.baseline
        return entry, archive, state, outcome
    except BaseException:
        if archive:
            archive.close()
        raise


@pytest.mark.parametrize("mode", ["default", "custom", "removed"])
def test_r7_entry_roundtrip(artifacts, mode):
    entry, archive, state, outcome = r7_roundtrip_evidence(artifacts, mode)
    try:
        assert outcome["rows"] == 2 and outcome["large_objects"] == 1
        result = backup.finish_bound_backup(entry, archive, state, outcome)
        assert result["status"] == "ENTRY_REHEARSAL_PASS_NOT_QUALIFIED"
        assert result["usable_backup"] is False and result["current_data_export"] is False
        assert result["protected_resources_unchanged"] is None and result["cleanup_ok"]
        assert result["verification"]["full_comparison"] is True
        assert not (entry.directory / "result.json").exists()
        assert not (entry.directory / "qualified.json").exists()
        assert archive.path.name == "database.partial.dump"
        with pytest.raises(backup.BackupError, match="entry_finalization_scope"):
            backup.finish_bound_backup(entry, archive, state, outcome)
        with pytest.raises(backup.BackupError, match="entry_restore_arguments"):
            backup.restore_isolated(archive, state, entry.directory, _entry=entry)
    finally:
        archive.close()


@pytest.fixture(scope="module")
def r7_finalization_evidence(artifacts):
    entry, archive, state, outcome = r7_roundtrip_evidence(artifacts, "custom")
    try:
        yield entry, archive, state, outcome
        result = backup.finish_bound_backup(entry, archive, state, outcome)
        assert result["status"] == "ENTRY_REHEARSAL_PASS_NOT_QUALIFIED"
    finally:
        archive.close()


@pytest.mark.parametrize("damage", ["snapshot", "comparison", "profile", "comments", "postflight", "claim",
    "proof", "missing", "outcome", "state", "wrong_entry"])
def test_r7_entry_finalization_guards(r7_finalization_evidence, damage):
    entry, archive, state, outcome = r7_finalization_evidence
    if damage in ("outcome", "state", "wrong_entry"):
        bad_outcome = {**outcome, "full_comparison": False} if damage == "outcome" else outcome
        bad_state = {**state, "tables": []} if damage == "state" else state
        with pytest.raises(backup.BackupError):
            backup.finish_bound_backup(None if damage == "wrong_entry" else entry, archive, bad_state, bad_outcome)
        assert not entry.finished
        return
    names = {"snapshot": "snapshot.json", "profile": backup.BoundRestoreIdentityProfile.FILE,
        "comments": backup.BoundMemberComments.FILE, "postflight": "entry-postflight.json",
        "claim": "entry-claim.json", "proof": "entry-restore-proof.json", "missing": "entry-restore-proof.json"}
    path = next(entry.directory.glob("schema-comparison-*.json")) if damage == "comparison" else entry.directory / names[damage]
    before = path.read_bytes()
    preserved = entry.directory / ("negative-preserved-"+path.name)
    try:
        if damage == "missing":
            path.rename(preserved)
        else:
            value = json.loads(before)
            value["negative_tamper"] = True
            path.write_text(json.dumps(value))
        with pytest.raises((backup.BackupError, FileNotFoundError)):
            backup.finish_bound_backup(entry, archive, state, outcome)
        assert not entry.finished
        assert not (entry.directory / "entry-rehearsal-result.json").exists()
    finally:
        if damage == "missing":
            preserved.rename(path)
        else:
            path.write_bytes(before)  # Restore only this newly generated test proof, same inode.


@pytest.mark.parametrize("arguments", [[], ["--accept-unencrypted"], ["--accept-source-readonly"],
    ["--accept-retained-diagnostic"], ["--qualification", "/private/tmp"], ["--binding-sha256", "0"*64]])
def test_r7_entry_cli(artifacts, arguments):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--rehearse-backup-entry", *arguments],
        capture_output=True, env={**backup.clean_env(), "V49_BACKUP_ARTIFACTS": str(artifacts)}, timeout=120)
    if arguments:
        assert result.returncode == 1 and result.stderr.strip() == b"entry_arguments_invalid"
        return
    assert result.returncode == 0, result.stderr.decode()
    value = json.loads(result.stdout)
    assert value["status"] == "ENTRY_REHEARSAL_PASS_NOT_QUALIFIED" and value["cleanup_ok"]
    directory = Path(value["directory"])
    assert directory.parent == artifacts and directory.name.startswith("r7-entry-")
    proof = backup.read_private_json(directory / "entry-rehearsal-result.json")
    assert proof["usable_backup"] is False and proof["current_data_export"] is False
    assert proof["verification"]["rows"] == 2
    assert not (directory / "qualified.json").exists()


def file_binding(path):
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_r2_bound_reader_is_readonly_and_detects_mutation(artifacts):
    directory = private_test_directory(artifacts, "r2_reader")
    path = directory / "input.json"
    backup.private_json(path, {"synthetic_negative_guard_input": True})
    binding = file_binding(path)
    reader = backup.BoundInput(path, binding)
    try:
        assert reader.json() == {"synthetic_negative_guard_input": True}
        assert not hasattr(reader, "export") and not hasattr(reader, "finalize")
        with pytest.raises(OSError):
            os.write(reader.fd, b"not writable")
        path.write_bytes(b"a different actual file")
        with pytest.raises(backup.BackupError, match="identity_changed"):
            reader.verify()
    finally:
        reader.close()
        reader.close()
    with pytest.raises(backup.BackupError, match="digest_changed"):
        backup.BoundInput(path, {"bytes": path.stat().st_size, "sha256": "0"*64})
    with pytest.raises(backup.BackupError, match="size_changed"):
        backup.BoundInput(path, {"bytes": 1, "sha256": "0"*64})
    with pytest.raises(backup.BackupError, match="invalid_input_binding"):
        backup.BoundInput(path, {"bytes": 0, "sha256": "bad"})


def test_r2_custody_rejects_links_modes_acl_and_replaced_inode(artifacts):
    directory = private_test_directory(artifacts, "r2_custody")
    path = directory / "input.json"
    backup.private_json(path, {"test": "negative integrity case"})
    binding = file_binding(path)
    path.chmod(0o644)
    with pytest.raises(backup.BackupError, match="input_not_private"):
        backup.BoundInput(path, binding)
    path.chmod(0o600)
    link = directory / "hardlink"
    os.link(path, link)
    with pytest.raises(backup.BackupError, match="input_not_private"):
        backup.BoundInput(path, binding)
    link.unlink()
    link.symlink_to(path)
    with pytest.raises(OSError):
        backup.BoundInput(link, binding)
    link.unlink()
    if sys.platform == "darwin":
        backup.run(["chmod", "+a", "everyone allow read", str(path)])
        try:
            with pytest.raises(backup.BackupError, match="acl_grants_access"):
                backup.BoundInput(path, binding)
        finally:
            backup.run(["chmod", "-N", str(path)])
    reader = backup.BoundInput(path, binding)
    try:
        path.rename(directory / "preserved-input.json")
        backup.private_json(path, {"test": "negative integrity case"})
        with pytest.raises(backup.BackupError, match="identity_changed"):
            reader.verify()
    finally:
        reader.close()
    fifo = directory / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(backup.BackupError, match="input_not_private"):
        backup.BoundInput(fifo, binding)


def test_r2_json_guards_and_fixed_cli_arguments(artifacts):
    directory = private_test_directory(artifacts, "r2_json")
    path = directory / "bad.json"
    path.write_bytes(b"[]")
    path.chmod(0o600)
    reader = backup.BoundInput(path, file_binding(path))
    try:
        with pytest.raises(backup.BackupError, match="metadata_not_object"):
            reader.json()
    finally:
        reader.close()
    with pytest.raises(backup.BackupError, match="retained_input_names_invalid"):
        backup.RetainedInputs(directory, {})
    for args in (["--diagnose-retained-archive"],
                 ["--diagnose-retained-archive", "--accept-retained-diagnostic", "--qualification", str(directory)],
                 ["--cleanup-test", str(directory), "--accept-retained-diagnostic"]):
        with pytest.raises(backup.BackupError):
            backup.main(args)
    # Real CLI: no input path override, no combined modes, no test-registry reuse.
    for args in (["--diagnose-retained-archive", "--input", str(directory)],
                 ["--diagnose-retained-archive", "--backup-unencrypted"],
                 ["--diagnose-retained-archive", "--accept-retained-diagnostic"]):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True,
            env={**backup.clean_env(), "V49_BACKUP_ARTIFACTS": str(artifacts)}, timeout=10)
        assert result.returncode != 0
    with pytest.raises(backup.BackupError, match="test_registry_not_allowed"):
        backup.main(["--diagnose-retained-archive", "--accept-retained-diagnostic"])


def synthetic_retained_export(artifacts, variant):
    """Genuine fresh source, exported then removed BEFORE another PG is started."""
    directory = private_test_directory(artifacts, "r2_"+variant)
    source_dir = directory / "source"
    source_dir.mkdir(mode=0o700)
    lab = backup.MemoryPostgres(source_dir)
    archive = None
    try:
        lab.start()
        db = populated(lab)
        if variant == "different":
            owner = "diagnostic_owner_"+secrets.token_hex(4)
            lab.sql(db, f"CREATE ROLE {owner} SUPERUSER NOLOGIN; ALTER DATABASE {db} OWNER TO {owner}; "
                f"DROP EXTENSION plpgsql; SET ROLE {owner}; CREATE EXTENSION plpgsql; RESET ROLE")
        archive, state = backup.export_database(lambda tool, *args: lab.command(tool, db, *args), directory)
        backup.private_json(directory / "source-binding.json", {"kind": "synthetic", "container": lab.cid})
    finally:
        if archive is not None:
            archive.close()
        lab.cleanup()
    # A malformed genuine archive tests actual pg_restore failure, not a fake DB.
    if variant == "error":
        with (directory / "database.partial.dump").open("r+b") as stream:
            stream.truncate(64)
    backup.private_json(directory / "failed.json", {"status": "FAILED", "encrypted": False,
        "usable_backup": False, "partial_retained": True, "migration_applied": False})
    return directory, {name: file_binding(directory / name) for name in backup.RETAINED_INPUTS}


def test_r2_malformed_inputs_never_claim_and_schema_text_never_leaks(artifacts):
    directory = private_test_directory(artifacts, "r2_invalid")
    for name in backup.RETAINED_INPUTS:
        path = directory / name
        path.write_bytes(b"not an archive")
        path.chmod(0o600)
    bindings = {name: file_binding(directory / name) for name in backup.RETAINED_INPUTS}
    with pytest.raises(backup.BackupError, match="invalid_archive_format"):
        backup.RetainedInputs(directory, bindings)
    path = directory / "database.partial.dump"
    path.write_bytes(b"PGDMPnegative input guard only")
    bindings[path.name] = file_binding(path)
    path = directory / "snapshot.json"
    path.write_bytes(b"{}")
    bindings[path.name] = file_binding(path)
    with pytest.raises(backup.BackupError, match="snapshot_categories_invalid"):
        backup.RetainedInputs(directory, bindings)
    assert not (directory / "r2-diagnostic").exists()
    poison = b"-- Name: irrelevant; Type: PRIVATE SECRET TEXT; Schema: secret; Owner: secret\n"
    summary = backup.schema_representation_summary(poison, poison)
    assert summary["archive_reconstructed"]["object_type_counts"] == {"OTHER": 1}
    assert "SECRET" not in json.dumps(summary)


@pytest.mark.parametrize("variant,expected_status", [("match", "MATCH"), ("different", "DIFFERENT"), ("error", "ERROR")])
def test_r2_real_once_only_diagnostic_and_cleanup(artifacts, variant, expected_status):
    directory, bindings = synthetic_retained_export(artifacts, variant)
    baseline = backup.MemoryPostgres(directory).inventory()
    inputs = backup.RetainedInputs(directory, bindings)
    original_ids = {name: value.identity for name, value in inputs.files.items()}
    try:
        report = backup.diagnose_retained(inputs)
        assert report["status"] == expected_status
        assert report["cleanup_ok"] and report["inputs_unchanged"]
        assert report["backup_qualified"] is False and report["deployment"] is False
        assert backup.MemoryPostgres(directory).inventory() == baseline
        assert {name: value.identity for name, value in inputs.files.items()} == original_ids
        assert {name: file_binding(directory / name) for name in bindings} == bindings
        with pytest.raises(backup.BackupError, match="already_claimed"):
            backup.diagnose_retained(inputs)
        assert backup.MemoryPostgres(directory).inventory() == baseline
        result = backup.read_private_json(directory / "r2-diagnostic" / "diagnostic.json")
        assert result == report
        assert set(result["equal_categories"]) == set(backup.DIAGNOSTIC_CATEGORIES)
        if variant == "different":
            assert result["equal_categories"]["schema"] is False
            assert all(value for key, value in result["equal_categories"].items() if key != "schema")
            assert result["schema_diagnostic"]["archive_reconstructed"]["create_extension_names"] == ["plpgsql"]
            assert result["schema_diagnostic"]["restored_pg_dump"]["create_extension_names"] == []
        if variant == "error":
            assert result["error_code"] == "restore_failed"
        encoded = json.dumps(report)
        assert "合成資料" not in encoded and "CREATE TABLE" not in encoded and "synthetic large object" not in encoded
        for name in ("qualified.json", "restore-proof.json", "result.json", "database.dump"):
            assert not (directory / name).exists() and not (directory / "r2-diagnostic" / name).exists()
    finally:
        inputs.close()

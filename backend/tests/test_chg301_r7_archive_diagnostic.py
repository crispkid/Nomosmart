"""Real owned PostgreSQL diagnostics. Never opens the historical R7 files."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

import pytest

from test_chg291_v049_live_backup import artifacts, backup, private_test_directory, r5_source

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import chg301_r7_archive_diagnostic as d


@pytest.fixture(scope="module")
def real_source(artifacts):
    directory = private_test_directory(artifacts, "r7_diagnostic_source")
    lab = backup.MemoryPostgres(private_test_directory(directory, "pg"), bootstrap="diagnostic_initial")
    archive = None
    try:
        lab.start()
        db, _ = r5_source(lab, populated_data=True)
        entry = backup.BackupSourceEvidence.owned(lab, db, directory)
        archive, _ = backup.export_database(entry.command, directory, _entry=entry)
        with pytest.raises(backup.BackupError, match="diagnostic_owned_source"):
            d.Inputs.owned(entry)
    finally:
        lab.cleanup()
    try:
        yield entry
    finally:
        if archive:
            archive.close()


def test_fresh_archive_diagnostic_and_once_only(real_source, artifacts):
    inputs = d.Inputs.owned(real_source)
    root = private_test_directory(artifacts, "r7_full")
    try:
        directory, report = d.diagnose(inputs, root)
        assert report["status"] == "MATCH", report.get("error_code")
        assert report["cleanup_ok"] and report["inputs_unchanged"]
        assert report["comparison"]["full_comparison_pass"]
        assert not report["usable_backup"] and not report["comment_repair"]
        assert (directory/"comparison.json").is_file()
        assert not list(real_source.directory.glob("member-comments-replay*"))
        encoded = json.dumps(report)
        assert "合成資料" not in encoded and "test.items" not in encoded
        with pytest.raises(FileExistsError):
            d.diagnose(inputs, root)
        assert len(list(root.glob("r7-diagnostic-*"))) == 2
        inputs.verify()
    finally:
        inputs.close()


@pytest.mark.parametrize("variant", ["comment", "recreated_language"])
def test_other_real_source_structures(variant, artifacts):
    directory = private_test_directory(artifacts, "r7_"+variant)
    source = backup.MemoryPostgres(private_test_directory(directory, "pg"), bootstrap="diagnostic_initial")
    archive = inputs = None
    try:
        source.start()
        db, _ = r5_source(source, populated_data=True, recreate_language=variant == "recreated_language")
        if variant == "comment":
            source.sql(db, "COMMENT ON FUNCTION digest(text,text) IS 'private synthetic comment'")
        entry = backup.BackupSourceEvidence.owned(source, db, directory)
        archive, _ = backup.export_database(entry.command, directory, _entry=entry)
    finally:
        source.cleanup()
    try:
        inputs = d.Inputs.owned(entry)
        _, report = d.diagnose(inputs, private_test_directory(directory, "output"))
        assert report["status"] == ("DIFFERENT" if variant == "comment" else "MATCH"), report.get("error_code")
        assert report["cleanup_ok"] and report["inputs_unchanged"]
        assert report["preparation"]["plpgsql_recreated"] == (variant == "recreated_language")
        assert "private synthetic comment" not in json.dumps(report)
        if variant == "comment":
            assert not report["comparison"]["categories"]["schema"]["equal"]
            assert all(c["equal"] for key, c in report["comparison"]["categories"].items() if key != "schema")
            assert all(c["fields"] == ["comment"] for c in report["comparison"]["catalog"]["changes"])
    finally:
        if inputs:
            inputs.close()
        if archive:
            archive.close()


@pytest.mark.parametrize("file,field", [
    ("snapshot.json", "properties"), ("schema-evidence-v1.json", "sources"),
    ("backup-source-v1.json", "archive"), ("restore-identity-v3.json", "source_sha256"),
    ("extension-member-comments-v2.json", "members_sha256"),
])
def test_actual_evidence_rejects_changed_values(real_source, file, field):
    inputs = d.Inputs.owned(real_source)
    try:
        del inputs.values[file][field]
        with pytest.raises(backup.BackupError):
            inputs.validate()
    finally:
        inputs.close()


@pytest.mark.parametrize("damage", ["kind", "historical_scope", "names", "json_limit", "digest"])
def test_constructor_guards(real_source, damage):
    inputs = d.Inputs.owned(real_source)
    bindings = {name: dict(value.expected) for name, value in inputs.files.items()}
    inputs.close()
    kind = real_source.kind
    if damage == "kind":
        kind = "unknown"
    elif damage == "historical_scope":
        kind = backup.BackupSourceEvidence.LIVE
    elif damage == "names":
        bindings["../outside"] = bindings.pop("snapshot.json")
    elif damage == "json_limit":
        bindings["snapshot.json"]["bytes"] = 5*1024**2
    else:
        bindings["snapshot.json"]["sha256"] = "0"*64
    with pytest.raises(backup.BackupError):
        d.Inputs(real_source.directory, bindings, real_source.sources, kind)


def test_real_deadline_consumes_claim_and_cleans(real_source, artifacts):
    inputs = d.Inputs.owned(real_source)
    root = private_test_directory(artifacts, "r7_timeout")
    try:
        _, report = d.diagnose(inputs, root, seconds=.001)
        assert report["status"] == "ERROR" and report["cleanup_ok"] and report["inputs_unchanged"]
        with pytest.raises(FileExistsError):
            d.diagnose(inputs, root)
        with pytest.raises(backup.BackupError, match="diagnostic_deadline"):
            d.diagnose(inputs, root, seconds=601)
    finally:
        inputs.close()


def test_real_cancel_preserves_claim_and_cleans(real_source, artifacts):
    inputs = d.Inputs.owned(real_source)
    root = private_test_directory(artifacts, "r7_cancel")
    timer = threading.Timer(1, lambda: os.kill(os.getpid(), signal.SIGINT))
    try:
        timer.start()
        with pytest.raises(KeyboardInterrupt):
            d.diagnose(inputs, root)
        report = backup.read_private_json(next(root.glob("r7-diagnostic-*/diagnostic-result.json")))
        assert report["status"] == "ERROR" and report["cleanup_ok"]
        with pytest.raises(FileExistsError):
            d.diagnose(inputs, root)
    finally:
        timer.cancel()
        timer.join()
        inputs.close()


def test_real_corrupt_archive_restore_fails_and_target_cleanup(real_source, artifacts):
    directory = private_test_directory(artifacts, "r7_corrupt")
    path = directory/"truncated.dump"
    # Deliberately truncate only this freshly exported synthetic test input.
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write((real_source.directory/"database.partial.dump").read_bytes()[:80])
    archive = backup.BoundInput(path, {"bytes": path.stat().st_size, "sha256": d.sha(path)})
    lab = backup.MemoryPostgres(private_test_directory(directory, "pg"))
    try:
        lab.start()
        target = lab.next_database() if lab.current_scope else "v49b_corrupt"
        lab.create_db(target)
        with pytest.raises(backup.BackupError):
            archive.restore(lab.empty_restore(target), time.monotonic()+30)
        archive.verify()
    finally:
        archive.close()
        lab.cleanup()
    assert lab.inventory() == lab.baseline


def test_local_qualification_and_cli_guards(artifacts):
    directory = private_test_directory(artifacts, "r7_unqualified")
    with pytest.raises((FileNotFoundError, backup.BackupError)):
        d.historical(directory)  # Stops at local proof, before historical I/O.
    with pytest.raises(backup.BackupError, match="historical_explicit_approval_required"):
        d.main(["--diagnose-r7"])
    with pytest.raises(backup.BackupError, match="qualification_arguments"):
        d.main(["--qualify", "--qualification", str(directory)])
    with pytest.raises(SystemExit):
        d.main([])
    with pytest.raises(backup.BackupError, match="diagnostic_run_expired"):
        d.disk_guard(directory, time.time()-21601)
    d.disk_guard(directory, time.time())
    backup.private_json(directory/"diagnostic-qualified.json", {"status": "UNQUALIFIED"})
    with pytest.raises(backup.BackupError, match="diagnostic_qualification_invalid"):
        d.require_qualification(directory)
    assert d.output_root(directory/"new") == directory/"new"
    assert d.output_root(directory/"new") == directory/"new"
    proof = directory/"diagnostic-qualified.json"
    d.verify_report_files(directory, {proof.name: d.sha(proof)})
    with pytest.raises(backup.BackupError, match="diagnostic_report_changed"):
        d.verify_report_files(directory, {proof.name: "0"*64})
    with pytest.raises(backup.BackupError, match="diagnostic_report_changed"):
        d.verify_report_files(directory, {"../outside": "0"*64})

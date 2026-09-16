"""Real files/artifacts and pure guards; never emulate registry/runtime success."""
from datetime import UTC, datetime
import importlib.util
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
spec = importlib.util.spec_from_file_location("node_qualification", ROOT / "backend/scripts/chg301_r2_node_qualification.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
RUN = Path(os.environ["CHG301_R2_NODE_QUAL_EVIDENCE"]).resolve(strict=True)
RECORD = json.loads((RUN / "manifest.json").read_bytes())


def real_json(name):
    path = RUN / name
    assert path.is_file() and not path.is_symlink()
    return json.loads(path.read_bytes())


def recorded_plan():
    active = (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    section = next(x for x in active.split("\n## ") if x.splitlines()[0] == q.SECTION)
    return "# Historical static qualification evidence\n\n## " + section


def test_current_approved_real_plan():
    # Original name retained for continuity; only the recorded scope/time was authorized.
    q.approval_guard(q.PLAN.read_bytes(), recorded_plan(), datetime.fromisoformat(RECORD["started_at"]))


def test_retired_static_runner_refuses_current_repair_plan():
    with pytest.raises(ValueError, match="historical_plan_not_active"):
        q.Qualification()


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "a/../../b", "a\\b", "a\x00b"])
def test_reject_archive_escape(path):
    with pytest.raises(ValueError, match="archive_path"):
        q.safe_name(path)


@pytest.mark.parametrize("path", ["usr/bin/kubelet", "./kind/images", "var/lib/dpkg/status"])
def test_safe_archive_name(path):
    assert ".." not in q.safe_name(path)
    assert not q.safe_name(path).startswith("/")


def test_expired_original_batch():
    with pytest.raises(ValueError, match="time_exhausted"):
        q.approval_guard(q.PLAN.read_bytes(), recorded_plan(), q.STOP_WORK)


def test_changed_plan_digest():
    with pytest.raises(ValueError, match="plan_hash"):
        q.approval_guard(q.PLAN.read_bytes() + b" ", (ROOT / "DEVELOPMENT_PLAN.md").read_text(), datetime.now(UTC))


def test_historical_approval_not_current():
    active = "## CHG-OTHER\nnot approved\n" + (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    with pytest.raises(ValueError, match="not_active"):
        q.approval_guard(q.PLAN.read_bytes(), active, datetime.now(UTC))


def test_pending_cannot_use_previous_approval():
    active = recorded_plan().replace("Gate 4 approval: APPROVED.", "Gate 4 approval: PENDING.", 1)
    with pytest.raises(ValueError, match="approval_required"):
        q.approval_guard(q.PLAN.read_bytes(), active, datetime.now(UTC))


def test_whiteouts_only_remove_lower_layer():
    lower = {"a/old": {"type": "file"}, "b": {"type": "file"}}
    layer = {"a/.wh..wh..opq": {"type": "file"}, "a/new": {"type": "file"}, ".wh.b": {"type": "file"}}
    assert q.apply_layer(lower, layer) == {"a/new": {"type": "file"}}


def test_file_replaces_lower_directory():
    assert q.apply_layer({"a/b": {"type": "file"}}, {"a": {"type": "symlink", "link": "/tmp"}}) == {"a": {"type": "symlink", "link": "/tmp"}}


@pytest.mark.parametrize("url", ["http://registry-1.docker.io/", "https://localhost/", "https://user:secret@registry-1.docker.io/", "https://registry-1.docker.io:444/", "https://registry-1.docker.io/#fragment"])
def test_out_of_scope_url_no_network(url):
    with pytest.raises(ValueError, match="url_scope"):
        q.validate_url(url, {"registry-1.docker.io"})


@pytest.mark.parametrize("command", [["docker", "run", "x"], [*q.DOCKER, "run", "x"], [*q.DOCKER, "pull", "x"], [*q.DOCKER, "build", "."], ["kubectl", "get", "pods"], ["helm", "upgrade", "x"], ["go", "install", "x"], ["go", "test", "./..."]])
def test_forbidden_tool_dispatch_without_execution(command):
    # Constructor is deliberately unnecessary: forbidden commands must be
    # rejected by pure dispatch before any resource, filesystem or tool action.
    run = object.__new__(q.Qualification)
    with pytest.raises(ValueError, match="command_scope"):
        run.command(command)


def test_true_cli_refuses_without_opt_in(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "backend/scripts/chg301_r2_node_qualification.py"), "--phase", "preflight"], cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True)
    assert proc.returncode != 0
    assert b"explicit isolated opt-in" in proc.stderr
    assert list(tmp_path.iterdir()) == []


def test_real_research_raw_bindings():
    ledger = json.loads((ROOT / "docs/CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json").read_bytes())
    root = Path(ledger["artifacts"]["root"])
    for name in ("result.json", "all-severity.sarif.json", "sbom.spdx.json", "index.json"):
        assert q.file_sha(root / name) == ledger["artifacts"][name]
    assert len(ledger["candidate"]["findings"]) == 59
    assert ledger["candidate"]["arm64_digest"] == q.NODE_ARM64
    assert not ledger["mutation_summary"]["waivers_applied"]


def test_official_node_artifact_platform():
    root = Path("/private/tmp/chg301-r2-node-research-pkn1sbr_")
    index = json.loads((root / "index.json").read_bytes())
    assert index["digest"] == q.NODE_INDEX
    arm64 = [x for x in index["manifests"] if x.get("platform", {}).get("architecture") == "arm64"]
    assert len(arm64) == 1 and arm64[0]["digest"] == q.NODE_ARM64


def test_real_node_manifest_and_config_chain():
    assert q.file_sha(RUN / "blobs/node-index.json") == q.NODE_INDEX.split(":")[1]
    assert q.file_sha(RUN / "blobs/node-manifest.json") == q.NODE_ARM64.split(":")[1]
    manifest = real_json("blobs/node-manifest.json")
    config = real_json("blobs/node-config.json")
    assert q.file_sha(RUN / "blobs/node-config.json") == manifest["config"]["digest"].split(":")[1]
    assert config["architecture"] == "arm64" and config["os"] == "linux"
    assert len(manifest["layers"]) == len(config["rootfs"]["diff_ids"]) == 2


@pytest.mark.parametrize("ordinal", [0, 1])
def test_real_compressed_and_uncompressed_digest(ordinal):
    manifest = real_json("blobs/node-manifest.json")
    config = real_json("blobs/node-config.json")
    assert q.file_sha(RUN / f"blobs/layer-{ordinal:02d}.blob") == manifest["layers"][ordinal]["digest"].split(":")[1]
    assert q.file_sha(RUN / f"blobs/layer-{ordinal:02d}.tar") == config["rootfs"]["diff_ids"][ordinal].split(":")[1]


def test_actual_effective_rootfs_overlay_and_links_not_materialized():
    effective = q.apply_layer(q.apply_layer({}, real_json("analysis/layer-00.json")), real_json("analysis/layer-01.json"))
    assert effective == real_json("analysis/node-files.json")
    assert len(effective) == RECORD["node"]["effective_files"]
    links = [v for v in effective.values() if v["type"] in {"symlink", "hardlink"}]
    assert links and all(not x.get("payload") for x in links)
    assert not any(p.is_symlink() for p in (RUN / "payload").iterdir())


def test_all_actual_nested_descriptors_and_oci_dirs():
    enabled = [x for x in RECORD["scan_inventory"] if x["enabled"] and x["scan_reference"].startswith("oci-dir://")]
    assert len(enabled) == 9
    for item in enabled:
        root = Path(item["scan_reference"].removeprefix("oci-dir://"))
        index = json.loads((root / "index.json").read_bytes())
        assert index["manifests"][0]["digest"] == item["manifest_digest"]
        for digest in (item["manifest_digest"], item["config_digest"]):
            assert q.file_sha(root / "blobs/sha256" / digest.split(":")[1]) == digest.split(":")[1]
    excluded = [x for x in RECORD["scan_inventory"] if not x["enabled"]]
    assert len(excluded) == 1 and excluded[0]["manifest_digest"].startswith("sha256:aa67f22ca961")


def test_cilium_every_actual_rendered_image_and_disabled_hubble():
    import yaml
    content = (RUN / "analysis/cilium-render.yaml").read_bytes()
    assert q.sha(content) == RECORD["cilium"]["render_sha256"]
    found = [r for doc in yaml.safe_load_all(content) if isinstance(doc, dict) for r in q.image_fields(doc)]
    assert len(found) == 9
    assert {r["reference"] for r in found} == {r["reference"] for r in RECORD["cilium"]["images"]}
    assert len({r["reference"] for r in found}) == 3
    values = yaml.safe_load((RUN / "analysis/cilium-values.yaml").read_bytes())
    assert values["hubble"]["enabled"] is False
    assert values["kubeProxyReplacement"] is False
    assert all("--dry-run=server" not in x["argv"] for x in RECORD["commands"])


@pytest.mark.parametrize("name", [x["name"] for x in RECORD["scan_inventory"] if x["enabled"]])
def test_actual_all_severity_scan_spdx_and_digest(name):
    item = next(x for x in RECORD["scan_inventory"] if x["name"] == name)
    assert item["scan_status"] == "RAW_SCAN_COMPLETE" and item["spdx_image_bound"]
    for fmt in ("sarif", "spdx"):
        assert q.file_sha(RUN / "analysis" / f"{name}.{fmt}.json") == item[fmt + "_sha256"]
    parsed = q.assess_sarif(real_json(f"analysis/{name}.sarif.json"))
    assert parsed == item["assessment"]
    assert not parsed["waivers_applied"] and parsed["runtime_exploitability_verified"] is False


@pytest.mark.parametrize("mutation", ["suppressed", "tool", "failed"])
def test_real_raw_negative_cannot_be_clean(mutation):
    raw = real_json("analysis/cilium.sarif.json")
    run = raw["runs"][0]
    if mutation == "suppressed":
        run["results"][0]["suppressions"] = [{"kind": "external"}]
    elif mutation == "tool":
        run["tool"]["driver"]["name"] = "not docker scout"
    else:
        run["invocations"] = [{"executionSuccessful": False}]
    with pytest.raises(ValueError):
        q.assess_sarif(raw)


def test_all_59_original_ids_and_every_instance_retained():
    initial = real_json("analysis/node-assessment-ledger.json")
    final = real_json("analysis/node-assessment-final.json")
    assert len(initial) == len(final) == 59
    assert {x["id"] for x in initial} == {x["id"] for x in final}
    for a, b in zip(initial, final):
        assert a["raw_instances"] == b["raw_instances"] and a["purls"] == b["purls"]
        assert b["official_advisories"] and b["assessment_basis"]
        assert b["accepted"] is False and b["assessment"] != "FIXED"


def test_zero_symbol_module_presence_not_not_affected():
    caps = real_json("analysis/binary-analysis-capability.json")
    assert len(caps) == 7 and all(x["symbols_count"] == 0 for x in caps)
    assert all(x["source_closure_verified"] is False for x in caps)
    final = real_json("analysis/node-assessment-final.json")
    go_rows = [x for x in final if any(p.startswith("pkg:golang/") for p in x["purls"])]
    assert len(go_rows) == 27 and all(x["assessment"] == "INDETERMINATE" for x in go_rows)


def test_exact_perl_architecture_proposal_is_not_accepted():
    row = next(x for x in real_json("analysis/node-assessment-final.json") if x["id"] == "CVE-2026-8376")
    assert row["assessment"] == "PROPOSED_NOT_AFFECTED" and row["accepted"] is False
    assert row["architecture_evidence"]["elf"]["class_bits"] == 64
    assert all(v == ["8"] for v in row["architecture_evidence"]["sizes"].values())


def test_perl_source_qualified_fix_not_socket_version():
    row = next(x for x in real_json("analysis/node-assessment-ledger.json") if x["id"] == "CVE-2026-12087")
    assert q.debian_fixed_versions(row["official_advisories"][0]["tables"], "perl") == ["5.40.1-6+deb13u1"]
    assert q.debian_fixed_versions(row["official_advisories"][0]["tables"], "libsocket-perl") == ["2.038-1+deb13u1"]


@pytest.mark.parametrize("suite", ["trixie", "trixie-security"])
def test_actual_official_signature_and_index_binding(suite):
    cmd = next(i for i in reversed(range(len(RECORD["commands"]))) if RECORD["commands"][i]["exit_code"] == 0
               and RECORD["commands"][i]["argv"][0] == "gpgv" and RECORD["commands"][i]["argv"][-1].endswith("/" + suite + ".InRelease"))
    stdout = (RUN / "raw" / f"{cmd:03d}.stdout").read_text()
    digest, size, name = q.signed_release_index((RUN / "raw" / (suite + ".InRelease")).read_text(), stdout, suite, datetime(2026, 9, 15, 18, 0, tzinfo=UTC))
    assert q.file_sha(RUN / "raw" / (suite + ".Packages.xz")) == digest
    assert (RUN / "raw" / (suite + ".Packages.xz")).stat().st_size == size
    assert name == "main/binary-arm64/Packages.xz"
    with pytest.raises(ValueError, match="signature"):
        q.signed_release_index((RUN / "raw" / (suite + ".InRelease")).read_text(), stdout + "\nBADSIG", suite, datetime.now(UTC))


def test_materials_not_an_executable_lock():
    rows = real_json("analysis/debian-material-candidates.json")
    assert len(rows) == 17 and {x["source"] for x in rows} == {"glibc", "gzip", "libevent", "libssh2", "openssl", "pcre2", "perl", "sqlite3", "zlib"}
    assert all(x["dependency_closure"] == "UNRESOLVED_NOT_AN_EXECUTABLE_LOCK" and not x["payload_downloaded"] for x in rows)
    assert all(len(x["sha256"]) == 64 and x["bytes"] > 0 for x in rows)


@pytest.mark.parametrize("command", [[*q.DOCKER, "inspect", "--format", "{{json .Config.Env}}", "0"*64],
    [*q.DOCKER, "buildx", "imagetools", "inspect", "localhost/private:latest", "--raw"],
    [*q.DOCKER, "ps", "-aq", "--host", "tcp://localhost:9999"], ["helm", "version", "--kubeconfig", "/tmp/external"],
    ["go", "generate", "./..."], ["go", "build", "./..."]])
def test_additional_precise_cli_rejections(command):
    run = object.__new__(q.Qualification)
    run.work, run.record = RUN, RECORD
    with pytest.raises(ValueError, match="command_scope"):
        run.command(command)


def test_real_baseline_unchanged_and_no_runtime_operations():
    assert RECORD["baseline_before"] == RECORD["baseline_after"] and RECORD["baseline_unchanged"]
    assert RECORD["runtime_operations"] == RECORD["provider_calls"] == RECORD["pr_writes"] == 0
    assert not RECORD["waivers_applied"]
    assert RECORD["plan_sha256"] == q.PLAN_SHA


def test_exact_owned_cleanup_preserves_foreign_file(tmp_path):
    root = tmp_path / "owned"
    root.mkdir()
    owned = root / "owned.txt"
    owned.write_text("pure cleanup policy test")
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("must remain")
    identity = q.exact_owned_file(root, "owned.txt")
    assert q.exact_owned_file(root, "owned.txt", identity) == identity
    with pytest.raises(ValueError):
        q.exact_owned_file(root, "../foreign.txt")
    (root / "link").symlink_to(foreign)
    with pytest.raises(ValueError, match="cleanup_link"):
        q.exact_owned_file(root, "link")
    owned.write_text("changed")
    with pytest.raises(ValueError, match="identity_drift"):
        q.exact_owned_file(root, "owned.txt", identity)
    current = q.exact_owned_file(root, "owned.txt")
    assert q.exact_owned_file(root, "owned.txt", current) == current
    owned.unlink()
    assert foreign.read_text() == "must remain"


@pytest.mark.parametrize("case", ["path", "duplicate", "claimed_size", "wrong_diff"])
def test_real_static_archive_rejects_malformed_local_input(tmp_path, case):
    # Policy inputs only; not a mock image/registry or a product acceptance test.
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        member = tarfile.TarInfo("../escape" if case == "path" else "entry")
        if case == "claimed_size":
            member.size = q.MAX_LAYER + 1
        archive.addfile(member)
        if case == "duplicate":
            archive.addfile(member)
    data = stream.getvalue()
    blob = tmp_path / "input.blob"
    blob.write_bytes(gzip.compress(data))
    expected = "sha256:" + ("0" * 64 if case == "wrong_diff" else q.sha(data))
    reason = {"path": "archive_path", "duplicate": "archive_duplicate", "claimed_size": "archive_entry_bound", "wrong_diff": "layer_diff_id"}[case]
    with pytest.raises(ValueError, match=reason):
        actual = gzip.decompress(blob.read_bytes())
        q.validate_layer_digest(q.sha(actual), expected)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(actual), mode="r:") as archive:
            for n, member in enumerate(archive):
                seen.add(q.validate_archive_member(member, n, seen))
    assert not (tmp_path.parent / "escape").exists()


def test_old_acceptance_is_historical_and_cannot_unlock_new_scope():
    import chg301_r2_ingress as ingress
    approval = ingress.ACCEPTANCE_PATH.read_bytes()
    active = (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    raw = (ingress.ACCEPTED_BUILD / "all-severity.sarif.json").read_bytes()
    recorded = datetime.fromisoformat(json.loads(approval)["recordedAt"])
    with pytest.raises(ValueError, match="applicability_active_plan"):
        ingress.applicability_guard(approval, active, raw, recorded)
    actual_section = next(x for x in active.split("\n## ") if x.splitlines()[0] == ingress.SMOKE_SECTION)
    historical = "# Historical real approved plan\n\n## " + actual_section
    result = ingress.applicability_guard(approval, historical, raw, recorded)
    assert result["status"] == "PASS_WITH_ACCEPTED_NOT_AFFECTED"
    assert result["raw"]["severity_counts"] == {"HIGH": 1, "UNSPECIFIED": 1}
    assert result["raw"]["waivers_applied"] == []


@pytest.mark.parametrize("change", ["expired", "suite", "duplicate", "oversize", "no_signature"])
def test_real_signed_index_negative_policies(change):
    suite = "trixie-security"
    release = (RUN / "raw/trixie-security.InRelease").read_text()
    cmd = next(i for i in reversed(range(len(RECORD["commands"]))) if RECORD["commands"][i]["exit_code"] == 0
               and RECORD["commands"][i]["argv"][0] == "gpgv" and RECORD["commands"][i]["argv"][-1].endswith("/trixie-security.InRelease"))
    status = (RUN / "raw" / f"{cmd:03d}.stdout").read_text()
    now = datetime(2026, 9, 15, 18, tzinfo=UTC)
    if change == "expired":
        now = datetime(2030, 1, 1, tzinfo=UTC)
    elif change == "suite":
        suite = "other-suite"
    elif change == "no_signature":
        status = ""
    else:
        import re
        line = next(x for x in release.split("\nSHA256:\n")[1].splitlines() if re.fullmatch(r"\s*[0-9a-f]{64}\s+\d+\s+main/binary-arm64/Packages.xz", x))
        parts = line.split()
        replacement = line + "\n" + line if change == "duplicate" else " " + parts[0] + " 999999999 main/binary-arm64/Packages.xz"
        release = release.replace(line, replacement)
    with pytest.raises(ValueError):
        q.signed_release_index(release, status, suite, now)

"""CMPING-T02 local guards against real downloaded/scanned artifacts.

Not ingress runtime acceptance. No application import, network, mock subprocess,
forged clean scanner result or changed production configuration. Provide the
exact private scan root via CHG301_R2_CANDIDATE_EVIDENCE; absence is an error.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend/scripts/chg301_r2_ingress.py"
SPEC = importlib.util.spec_from_file_location("chg301_r2_ingress", SCRIPT)
INGRESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INGRESS)
SCAN = Path(os.environ["CHG301_R2_CANDIDATE_EVIDENCE"]).resolve(strict=True)
EVIDENCE = json.loads((SCAN / "result.json").read_bytes())


def artifact(name):
    path = SCAN / name
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EVIDENCE["artifacts"][name]["sha256"]
    return data


INDEX = artifact("chart-index.yaml")
CHART = artifact("traefik-41.5.0.tgz")
IMAGE = json.loads(artifact("image-index.json"))
SARIF = json.loads(artifact("all-severity.sarif.json"))
SBOM = json.loads(artifact("sbom.spdx.json"))


def test_real_chart_archive_and_index_bind_exact_candidate():
    result, members = INGRESS.validate_chart(INDEX, CHART)
    assert result["version"] == "41.5.0"
    assert result["app_version"] == "v3.7.13"
    assert result["compatible_provider_present"]
    values = yaml.safe_load(members["traefik/values.yaml"])
    assert "kubernetesIngressNGINX" in values["providers"]
    # This test validates public defaults, not secure installed configuration.
    assert values["providers"]["kubernetesIngressNGINX"]["enabled"] is False


@pytest.mark.parametrize("field,value", [
    ("appVersion", "v3.7.12"), ("digest", "0" * 64),
    ("urls", ["https://example.invalid/unapproved.tgz"]),
])
def test_changed_official_index_binding_rejected(field, value):
    index = yaml.safe_load(INDEX)
    entry = next(x for x in index["entries"]["traefik"] if x["version"] == "41.5.0")
    entry[field] = value
    with pytest.raises(ValueError, match="chart_binding"):
        INGRESS.validate_chart(yaml.safe_dump(index).encode(), CHART)


def test_corrupt_real_archive_rejected_before_tar_read():
    with pytest.raises(ValueError, match="chart_binding"):
        INGRESS.validate_chart(INDEX, CHART[:-1])


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_ambiguous_chart_version_rejected(duplicate):
    index = yaml.safe_load(INDEX)
    entries = index["entries"]["traefik"]
    selected = next(x for x in entries if x["version"] == "41.5.0")
    index["entries"]["traefik"] = entries + [selected] if duplicate else [x for x in entries if x is not selected]
    with pytest.raises(ValueError, match="chart_version"):
        INGRESS.validate_chart(yaml.safe_dump(index).encode(), CHART)


def test_real_arm64_manifest_and_sbom_same_identity():
    identity = INGRESS.validate_image(IMAGE)
    assert identity["arm64_digest"] == EVIDENCE["image"]["arm64_digest"]
    locators = [r.get("referenceLocator", "") for p in SBOM["packages"] for r in p.get("externalRefs", [])]
    assert any(v.startswith("pkg:oci/") and identity["arm64_digest"] in v for v in locators)
    assert SBOM["creationInfo"]["creators"] == ["Organization: Docker, Inc", "Tool: docker-scout-1.24.0"]


@pytest.mark.parametrize("mutation", ["index", "child", "duplicate", "missing", "version"])
def test_image_drift_or_wrong_architecture_rejected(mutation):
    image = copy.deepcopy(IMAGE)
    arm = next(m for m in image["manifests"] if m["platform"].get("architecture") == "arm64")
    if mutation == "index":
        image["digest"] = "sha256:" + "0" * 64
    elif mutation == "child":
        arm["digest"] = "sha256:" + "0" * 64
    elif mutation == "duplicate":
        image["manifests"].append(copy.deepcopy(arm))
    elif mutation == "missing":
        image["manifests"].remove(arm)
    else:
        arm["annotations"]["org.opencontainers.image.version"] = "v3.7.12"
    with pytest.raises(ValueError, match="image_identity|image_version"):
        INGRESS.validate_image(image)


def test_actual_scan_blocks_without_inheriting_any_waiver():
    result = INGRESS.assess_sarif(SARIF)
    assert result["status"] == "BLOCKED_FINDINGS"
    assert result["unique_advisories"] == 12
    assert result["unique_cves"] == 11  # One additional advisory has only a GO ID.
    assert result["severity_counts"] == EVIDENCE["assessment"]["severity_counts"]
    assert result["unaccepted_high_critical"] == 10
    assert result["unclassified"] == 1
    assert result["waivers_applied"] == []
    assert result["runtime_exploitability_verified"] is False


@pytest.mark.parametrize("mutation", ["format", "runs", "driver", "results", "execution", "suppression", "unmatched", "duplicate", "unknown"])
def test_incomplete_or_waived_scan_cannot_pass(mutation):
    report = copy.deepcopy(SARIF)
    run = report["runs"][0]
    if mutation == "format":
        report["version"] = "unknown"
    elif mutation == "runs":
        report["runs"].append(copy.deepcopy(run))
    elif mutation == "driver":
        run["tool"]["driver"]["name"] = "unapproved"
    elif mutation == "results":
        del run["results"]
    elif mutation == "execution":
        run["invocations"] = [{"executionSuccessful": False}]
    elif mutation == "suppression":
        run["results"][0]["suppressions"] = [{"kind": "external"}]
    elif mutation == "unmatched":
        run["results"].pop()
    elif mutation == "duplicate":
        run["tool"]["driver"]["rules"].append(copy.deepcopy(run["tool"]["driver"]["rules"][0]))
    else:
        run["results"][0]["ruleId"] = "unknown"
    with pytest.raises(ValueError):
        INGRESS.assess_sarif(report)


def test_unknown_severity_stays_blocked_without_crashing():
    report = copy.deepcopy(SARIF)
    for rule in report["runs"][0]["tool"]["driver"]["rules"]:
        rule["properties"]["cvssV3_severity"] = "FUTURE_SCALE"
    result = INGRESS.assess_sarif(report)
    assert result["status"] == "BLOCKED_FINDINGS"
    assert result["unclassified"] == 12


def test_private_evidence_file_never_overwrites_existing(tmp_path):
    target = tmp_path / "evidence.json"
    INGRESS.save(target, {"test": True})
    before = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        INGRESS.save(target, b"changed")
    assert target.read_bytes() == before


@pytest.mark.parametrize("args,expected", [
    (["--phase", "candidate"], b"explicit isolated opt-in required"),
    (["--phase", "install"], b"invalid choice"),
])
def test_real_cli_refuses_unapproved_optin_or_unimplemented_phase(tmp_path, args, expected):
    process = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=tmp_path,
                             env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=10)
    assert process.returncode != 0
    assert expected in process.stderr
    assert list(tmp_path.iterdir()) == []


def test_unapproved_public_url_rejected_without_network():
    with pytest.raises(ValueError, match="unapproved_public_url"):
        INGRESS.fetch("https://example.invalid/other")


# CMPPATCH guards use real pinned OCI/APK/tool artifacts, never a fabricated
# clean scan or signature. Build/runtime cases remain NOT RUN at the scope gate.
REPAIR = Path(os.environ["CHG301_R2_REPAIR_EVIDENCE"]).resolve(strict=True)
REPAIR_INSPECT = json.loads((REPAIR / "inspect-result.json").read_bytes())
REPAIR_ANALYSIS = json.loads((REPAIR / "analysis-result.json").read_bytes())
REPAIR_ASSESSMENT = json.loads((REPAIR / "assessment-result.json").read_bytes())


def repair_artifact(name):
    path = REPAIR / name
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    if name in REPAIR_INSPECT["artifacts"]:
        expected = REPAIR_INSPECT["artifacts"][name]["sha256"]
    else:
        expected = REPAIR_ASSESSMENT["artifacts"][name]
    assert hashlib.sha256(data).hexdigest() == expected
    return data


KEY = (REPAIR / "alpine-signing-key.pem").read_bytes()
assert hashlib.sha256(KEY).hexdigest() == REPAIR_ANALYSIS["signing_key_sha256"]


@pytest.mark.parametrize("name", list(INGRESS.REPAIR_DOWNLOADS))
def test_cmppatch_real_pinned_apk_signature_datahash_and_metadata(name):
    data = repair_artifact(name)
    assert INGRESS.digest(data) == INGRESS.REPAIR_DOWNLOADS[name]
    metadata, files = INGRESS.verify_apk(data, KEY, name.removesuffix("-3.5.8-r0.apk"))
    assert metadata["pkgver"] == ["3.5.8-r0"]
    assert metadata["arch"] == ["aarch64"]
    assert files


def test_cmppatch_real_official_index_signature():
    index = INGRESS.verify_apk(repair_artifact("APKINDEX.tar.gz"), KEY)
    assert "APKINDEX" in index
    assert all(REPAIR_ASSESSMENT["signed_index_package_bindings"].values())


def test_cmppatch_real_apk_wrong_signing_key_rejected():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    # Real newly generated unrelated key, not a mocked signature verifier.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(InvalidSignature):
        INGRESS.verify_apk(repair_artifact("libssl3-3.5.8-r0.apk"), pem, "libssl3")


def test_cmppatch_truncated_signed_apk_rejected():
    with pytest.raises(ValueError, match="gzip_size_limit"):
        INGRESS.verify_apk(repair_artifact("libssl3-3.5.8-r0.apk")[:-1], KEY, "libssl3")


@pytest.mark.parametrize("field,value", [
    ("pkgver", ["3.5.9-r0"]), ("arch", ["x86_64"]), ("pkgname", ["unexpected"]),
    ("depend", ["fourth-package=1.0"]), ("datahash", ["0" * 64]),
])
def test_cmppatch_metadata_drift_or_additional_dependency_rejected(field, value):
    metadata, _ = INGRESS.verify_apk(repair_artifact("libssl3-3.5.8-r0.apk"), KEY, "libssl3")
    expected = metadata["datahash"][0]
    metadata[field] = value
    with pytest.raises(ValueError):
        INGRESS.validate_apk_metadata(metadata, "libssl3", expected)


@pytest.mark.parametrize("name", ["../../etc/passwd", "/usr/bin/x", "a/../b", "a\\b", "a\x00b"])
def test_cmppatch_unsafe_archive_paths_fail_closed(name):
    with pytest.raises(ValueError, match="unsafe_archive_path"):
        INGRESS.safe_tar_name(name)


def test_cmppatch_real_oci_blobs_config_and_effective_rootfs():
    repair_artifact("original-image.tar")
    config, fs = INGRESS.image_rootfs(REPAIR / "original-image.tar", INGRESS.ARM64_DIGEST)
    assert config["os"] == "linux" and config["architecture"] == "arm64"
    assert fs["usr/local/bin/traefik"]["sha256"] == REPAIR_ANALYSIS["binary_sha256"]
    assert fs["entrypoint.sh"]["sha256"] == REPAIR_ANALYSIS["entrypoint_sha256"]
    assert "usr/bin/openssl" not in fs
    assert fs["lib/apk/db/installed"]["data"] == repair_artifact("lib-apk-db-installed.bin")


def test_cmppatch_wrong_original_manifest_cannot_bind_real_archive():
    with pytest.raises(ValueError, match="image_blob_member"):
        INGRESS.image_rootfs(REPAIR / "original-image.tar", "sha256:" + "0" * 64)


def test_cmppatch_actual_inventory_blocks_adding_absent_openssl():
    packages = INGRESS.installed_packages(repair_artifact("lib-apk-db-installed.bin"))
    assert len(packages) == 18
    assert packages["libcrypto3"]["V"] == packages["libssl3"]["V"] == "3.5.7-r0"
    assert "openssl" not in packages
    # Revised, explicitly approved scope upgrades only the actual two libraries.
    INGRESS.validate_repair_scope(packages)
    packages["openssl"] = {"P": "openssl", "V": "3.5.7-r0", "A": "aarch64"}
    with pytest.raises(ValueError, match="approved_upgrade_baseline_drift"):
        INGRESS.validate_repair_scope(packages)


def test_cmppatch_actual_stripped_analysis_not_misrepresented_as_symbols():
    extracted = INGRESS.json_messages(repair_artifact("govulncheck-extract.json"))
    report = INGRESS.json_messages(repair_artifact("govulncheck.json"))
    capability = INGRESS.analysis_capability(extracted, report)
    assert capability["symbols_count"] == 0
    assert capability["precision"] == "module_only_stripped_fallback"
    assert capability["openpgp"] == "INDETERMINATE"
    assert capability["vex_applied"] == []
    assert {x["osv"] for x in capability["findings"]} == {"GO-2026-5932"}


@pytest.mark.parametrize("field,value", [("goos", "windows"), ("goarch", "amd64")])
def test_cmppatch_wrong_binary_platform_rejected(field, value):
    extracted = INGRESS.json_messages(repair_artifact("govulncheck-extract.json"))
    extracted[1][field] = value
    with pytest.raises(ValueError, match="analysis_build_platform"):
        INGRESS.analysis_capability(extracted, INGRESS.json_messages(repair_artifact("govulncheck.json")))


def test_cmppatch_json_exit_zero_without_scanner_config_cannot_pass():
    extracted = INGRESS.json_messages(repair_artifact("govulncheck-extract.json"))
    report = [x for x in INGRESS.json_messages(repair_artifact("govulncheck.json")) if "config" not in x]
    with pytest.raises(ValueError, match="analysis_scanner_identity"):
        INGRESS.analysis_capability(extracted, report)


def test_cmppatch_only_active_bound_approval_is_valid():
    real = (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    # Historical repair authorization is no longer the active scope. Exercise
    # its genuine recorded section without allowing history to unlock the CLI.
    historical = "\n## " + next(s for s in real.split("\n## ") if s.split("\n", 1)[0] == INGRESS.REPAIR_SECTION)
    INGRESS.repair_approval(historical)
    for changed in [real, historical.replace(INGRESS.REPAIR_APPROVAL, "0" * 64),
                    historical.replace("Gate 4 approval: APPROVED.", "Gate 4 approval: PENDING.", 1)]:
        with pytest.raises(ValueError, match="repair_approval_missing"):
            INGRESS.repair_approval(changed)


@pytest.mark.parametrize("phase", ["inspect", "analyze", "assess", "repair", "smoke", "cleanup"])
def test_cmppatch_real_cli_no_implicit_phase_execution(tmp_path, phase):
    proc = subprocess.run([sys.executable, "-B", str(SCRIPT), "--phase", phase], cwd=tmp_path,
                          env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=10)
    assert proc.returncode != 0
    assert b"explicit isolated opt-in required" in proc.stderr or b"invalid choice" in proc.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mutation", ["missing", "version", "architecture", "unrelated_version"])
def test_cmppatch_two_library_baseline_drift_rejected(mutation):
    packages = INGRESS.installed_packages(repair_artifact("lib-apk-db-installed.bin"))
    if mutation == "missing":
        del packages["libssl3"]
    elif mutation == "version":
        packages["libssl3"]["V"] = "3.5.6-r0"
    elif mutation == "architecture":
        packages["libcrypto3"]["A"] = "x86_64"
    else:
        packages["musl"]["V"] = "unexpected"
    with pytest.raises(ValueError, match="approved_upgrade"):
        INGRESS.validate_repair_scope(packages)


def test_cmppatch_historical_approved_cannot_unlock_first_pending_plan():
    real = (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    assert INGRESS.HISTORICAL_REPAIR_APPROVAL in real
    for prefix in ["## Another Active Scope\nGate 4 approval: APPROVED.\n",
                   "## " + INGRESS.REPAIR_SECTION + "\nGate 4 approval: PENDING.\n"]:
        with pytest.raises(ValueError, match="repair_approval_missing"):
            INGRESS.repair_approval(real.split("\n## ", 1)[0] + "\n" + prefix + "\n" + real)


def accepted_inputs():
    approval = INGRESS.ACCEPTANCE_PATH.read_bytes()
    active = (ROOT / "DEVELOPMENT_PLAN.md").read_text()
    section = next(x for x in active.split("\n## ") if x.splitlines()[0] == INGRESS.SMOKE_SECTION)
    # Validate the actual historical acceptance at its recorded time, not runtime authority.
    plan = "# Historical acceptance evidence\n\n## " + section
    raw = (INGRESS.ACCEPTED_BUILD / "all-severity.sarif.json").read_bytes()
    recorded = INGRESS.datetime.fromisoformat(json.loads(approval)["recordedAt"])
    return approval, plan, raw, recorded


def test_cmppatch_real_human_acceptance_preserves_raw_findings():
    result = INGRESS.applicability_guard(*accepted_inputs())
    assert result["status"] == "PASS_WITH_ACCEPTED_NOT_AFFECTED"
    assert result["raw"]["status"] == "BLOCKED_FINDINGS"
    assert result["raw"]["severity_counts"] == {"HIGH": 1, "UNSPECIFIED": 1}
    assert result["raw"]["waivers_applied"] == []
    assert result["plugins_allowed"] is False


def test_cmppatch_historical_acceptance_cannot_authorize_current_plan():
    approval, _, raw, recorded = accepted_inputs()
    with pytest.raises(ValueError, match="applicability_active_plan"):
        INGRESS.applicability_guard(approval, (ROOT / "DEVELOPMENT_PLAN.md").read_text(), raw, recorded)


@pytest.mark.parametrize("field,value", [
    ("imageId", "sha256:" + "0" * 64), ("pluginsAllowed", True),
    ("otherFindingsAccepted", True), ("currentDeploymentAuthorized", True),
    ("providerCallsAuthorized", True), ("expiresAt", "2099-01-01T00:00:00Z"),
])
def test_cmppatch_approval_cannot_expand_scope(field, value):
    approval, plan, raw, now = accepted_inputs()
    changed = json.loads(approval)
    changed[field] = value
    with pytest.raises(ValueError, match="applicability_approval_digest"):
        INGRESS.applicability_guard(json.dumps(changed).encode(), plan, raw, now)


@pytest.mark.parametrize("case", ["expired", "preapproval", "pending", "other_active", "report"])
def test_cmppatch_acceptance_time_plan_and_report_guard(case):
    approval, plan, raw, now = accepted_inputs()
    if case == "expired":
        now = INGRESS.datetime.fromisoformat(INGRESS.BATCH_DEADLINE)
    elif case == "preapproval":
        now = INGRESS.datetime.fromisoformat(INGRESS.BATCH_STARTED)
    elif case == "pending":
        plan = plan.replace("Plan Approval: APPROVED original R2 scope plus Peter", "Plan Approval: PENDING", 1)
    elif case == "other_active":
        plan = "\n## Unapproved\n" + plan
    else:
        raw += b" "
    with pytest.raises(ValueError, match="applicability_"):
        INGRESS.applicability_guard(approval, plan, raw, now)


def real_smoke_container():
    path = Path(os.environ["CHG301_R2_SMOKE_EVIDENCE"]).resolve(strict=True)
    data = (path / "result.json").read_bytes()
    assert INGRESS.digest(data) == "2cfece07e6f37a25bbfc4a1679feccf05c2624a330f843033f7737d8dc11e926"
    result = json.loads(data)
    assert result["status"] == "PASS_NETWORK_NONE_CLI_SMOKE"
    assert result["protected_baseline_unchanged"] and result["owned_containers_removed"]
    assert len(result["containers"]) == 2
    raw = (path / "container-0.json").read_bytes()
    assert INGRESS.digest(raw) == result["artifacts"]["container-0.json"]
    return json.loads(raw), path.name


def test_cmppatch_real_nonroot_network_none_runtime_smoke():
    row, name = real_smoke_container()
    INGRESS.validate_smoke_container(row, name, "version")


@pytest.mark.parametrize("field,value", [
    ("NetworkMode", "host"), ("Privileged", True), ("ReadonlyRootfs", False),
    ("CapAdd", ["SYS_ADMIN"]), ("CapDrop", []), ("SecurityOpt", []),
    ("Memory", 0), ("MemorySwap", -1), ("NanoCpus", 0), ("PidsLimit", -1),
    ("PortBindings", {"80/tcp": []}), ("Binds", ["/tmp:/tmp"]),
    ("Devices", [{"PathOnHost": "/dev/kmsg"}]), ("RestartPolicy", {"Name": "always"}),
])
def test_cmppatch_runtime_guard_rejects_weakened_isolation(field, value):
    row, name = real_smoke_container()
    row["HostConfig"][field] = value
    with pytest.raises(ValueError, match="smoke_container_isolation"):
        INGRESS.validate_smoke_container(row, name, "version")


@pytest.mark.parametrize("case", ["root", "image", "entrypoint", "serve", "owner", "mount"])
def test_cmppatch_runtime_guard_rejects_execution_scope_change(case):
    row, name = real_smoke_container()
    if case == "root":
        row["Config"]["User"] = "0"
    elif case == "image":
        row["Image"] = "sha256:" + "0" * 64
    elif case == "entrypoint":
        row["Config"]["Entrypoint"] = ["/bin/sh"]
    elif case == "serve":
        row["Config"]["Cmd"] = ["--providers.docker"]
    elif case == "owner":
        name = "not-owned"
    else:
        row["Mounts"] = [{"Type": "bind", "Source": "/tmp"}]
    with pytest.raises(ValueError, match="smoke_container_isolation"):
        INGRESS.validate_smoke_container(row, name, "version")


def node_artifacts():
    sys.modules.setdefault("chg301_r2_ingress", INGRESS)
    spec = importlib.util.spec_from_file_location("chg301_r2_node_candidate", SCRIPT.with_name("chg301_r2_node_candidate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = Path(os.environ["CHG301_R2_NODE_EVIDENCE"]).resolve(strict=True)
    raw = (path / "result.json").read_bytes()
    assert INGRESS.digest(raw) == "2373b58f6ccc4676fe79fad1fbf97b1abb53a05fce715998be63930829a94313"
    result = json.loads(raw)
    manifest = (path / "image-index.json").read_bytes()
    assert INGRESS.digest(manifest) == result["artifacts"]["image-index.json"]
    return module, json.loads(manifest), result


def test_cmpverify_real_node_security_does_not_inherit_traefik_acceptance():
    module, manifest, result = node_artifacts()
    assert module.node_identity(manifest) == result["arm64_digest"]
    assert result["assessment"]["severity_counts"] == {"CRITICAL": 18, "HIGH": 57, "MEDIUM": 59, "LOW": 80, "UNSPECIFIED": 16}
    assert result["status"] == "BLOCKED_FINDINGS"
    assert result["accepted_findings"] == []
    assert result["container_executions"] == result["kubernetes_operations"] == 0
    assert result["protected_baseline_unchanged"] and result["source_unchanged"]


@pytest.mark.parametrize("case", ["index", "missing", "duplicate", "architecture", "os"])
def test_cmpverify_node_wrong_or_ambiguous_platform_rejected(case):
    module, manifest, _ = node_artifacts()
    row = next(v for v in manifest["manifests"] if v["platform"] == {"architecture": "arm64", "os": "linux"})
    if case == "index":
        manifest["digest"] = "sha256:" + "0" * 64
    elif case == "missing":
        manifest["manifests"].remove(row)
    elif case == "duplicate":
        manifest["manifests"].append(copy.deepcopy(row))
    elif case == "architecture":
        row["platform"]["architecture"] = "amd64"
    else:
        row["platform"]["os"] = "windows"
    with pytest.raises(ValueError, match="official_node_identity"):
        module.node_identity(manifest)


def test_cmpverify_real_node_cli_rejects_without_optin(tmp_path):
    proc = subprocess.run([sys.executable, "-B", str(SCRIPT.with_name("chg301_r2_node_candidate.py"))],
                          cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=10)
    assert proc.returncode != 0 and b"explicit isolated opt-in required" in proc.stderr
    assert list(tmp_path.iterdir()) == []


def make_real_context(tmp_path):
    expected = {"Dockerfile": INGRESS.RECIPE.read_bytes(),
                "APKINDEX.tar.gz": repair_artifact("APKINDEX.tar.gz"),
                **{n + "-3.5.8-r0.apk": repair_artifact(n + "-3.5.8-r0.apk") for n in INGRESS.REPAIR_TARGETS}}
    for n, data in expected.items():
        INGRESS.save(tmp_path / n, data)
    return INGRESS.digest(expected["Dockerfile"])


def test_cmppatch_exact_two_signed_apks_index_and_recipe_context(tmp_path):
    recipe_sha = make_real_context(tmp_path)
    lock = INGRESS.validate_context(tmp_path, recipe_sha)
    assert len(lock) == 4 and lock["APKINDEX.tar.gz"] == INGRESS.SIGNED_INDEX_SHA
    assert "openssl-3.5.8-r0.apk" not in lock


@pytest.mark.parametrize("mutation", ["third_apk", "new_index", "missing", "symlink", "recipe"])
def test_cmppatch_context_extra_or_tampered_material_rejected(tmp_path, mutation):
    recipe_sha = make_real_context(tmp_path)
    if mutation == "third_apk":
        INGRESS.save(tmp_path / "openssl-3.5.8-r0.apk", repair_artifact("openssl-3.5.8-r0.apk"))
    else:
        name = "Dockerfile" if mutation == "recipe" else "APKINDEX.tar.gz"
        (tmp_path / name).unlink()
        if mutation == "symlink":
            (tmp_path / name).symlink_to(REPAIR / "APKINDEX.tar.gz")
        elif mutation != "missing":
            INGRESS.save(tmp_path / name, b"unapproved replacement")
    with pytest.raises(ValueError, match="repair_context_"):
        INGRESS.validate_context(tmp_path, recipe_sha)


def test_cmppatch_signed_index_binds_only_two_payloads():
    _, original = INGRESS.image_rootfs(REPAIR / "original-image.tar", INGRESS.ARM64_DIGEST)
    payload, bindings = INGRESS.signed_repair_inputs(REPAIR, original)
    assert set(bindings) == {"libssl3", "libcrypto3"}
    assert "usr/bin/openssl" not in payload
    assert all(row["metadata"]["pkgver"] == ["3.5.8-r0"] for row in bindings.values())


def test_cmppatch_changed_signed_index_hash_rejected_before_parsing(tmp_path):
    _, original = INGRESS.image_rootfs(REPAIR / "original-image.tar", INGRESS.ARM64_DIGEST)
    INGRESS.save(tmp_path / "APKINDEX.tar.gz", repair_artifact("APKINDEX.tar.gz")[:-1])
    with pytest.raises(ValueError, match="signed_index_digest"):
        INGRESS.signed_repair_inputs(tmp_path, original)


def test_cmppatch_real_cli_retires_old_inspect_with_isolated_optin(tmp_path):
    proc = subprocess.run([sys.executable, "-B", str(SCRIPT), "--phase", "inspect"], cwd=tmp_path,
                          env={"PATH": "/usr/bin:/bin", "CHG301_R2_ISOLATED": "1"}, capture_output=True, timeout=10)
    assert proc.returncode != 0 and b"historical phase retired" in proc.stderr
    assert list(tmp_path.iterdir()) == []


def actual_build():
    path = Path(os.environ["CHG301_R2_TWO_LIBRARY_EVIDENCE"]).resolve(strict=True)
    result = json.loads((path / "verification-result.json").read_bytes())
    for name in ("repaired-image.tar", "simulation.txt", "all-severity.sarif.json", "sbom.spdx.json"):
        assert INGRESS.digest((path / name).read_bytes()) == result["artifacts"][name]["sha256"]
    return path, result


def test_cmppatch_real_built_solver_rootfs_and_complete_scan():
    path, result = actual_build()
    original_config, original = INGRESS.image_rootfs(REPAIR / "original-image.tar", INGRESS.ARM64_DIGEST)
    config, final = INGRESS.image_rootfs(path / "repaired-image.tar", result["manifest_digest"])
    payload, _ = INGRESS.signed_repair_inputs(REPAIR, original)
    comparison = INGRESS.validate_final_image(original_config, original, config, final, payload)
    assert comparison["package_count"] == 18 and comparison["controller_binary_unchanged"]
    assert INGRESS.validate_simulation((path / "simulation.txt").read_text()) == result["solver_changes"]
    scan = INGRESS.assess_sarif(json.loads((path / "all-severity.sarif.json").read_bytes()))
    assert scan == result["scan"]
    assert result["openpgp"] == "INDETERMINATE" and result["controller_executions"] == 0
    assert result["source_unchanged"] and result["container_baseline_unchanged"]
    assert result["network_baseline_unchanged"] and result["context_removed"]


@pytest.mark.parametrize("mutation", ["extra", "missing", "version", "unrecognized"])
def test_cmppatch_real_built_solver_modified_plan_rejected(mutation):
    path, _ = actual_build()
    raw = (path / "simulation.txt").read_text()
    if mutation == "extra":
        raw += "\n(3/3) Installing openssl (3.5.8-r0)"
    elif mutation == "missing":
        raw = "\n".join(raw.splitlines()[1:])
    elif mutation == "version":
        raw = raw.replace("3.5.8-r0", "3.5.9-r0")
    else:
        raw += "\nUnrecognized action"
    with pytest.raises(ValueError, match="solver_unapproved_changes"):
        INGRESS.validate_simulation(raw)


@pytest.mark.parametrize("mutation", ["world", "binary", "entrypoint", "config", "extra_file", "ca"])
def test_cmppatch_real_built_protected_files_and_config_reject_mutation(mutation):
    path, result = actual_build()
    original_config, original = INGRESS.image_rootfs(REPAIR / "original-image.tar", INGRESS.ARM64_DIGEST)
    config, final = INGRESS.image_rootfs(path / "repaired-image.tar", result["manifest_digest"])
    payload, _ = INGRESS.signed_repair_inputs(REPAIR, original)
    if mutation == "config":
        config["config"]["Cmd"] = ["unexpected"]
    elif mutation == "extra_file":
        final["unapproved-file"] = final["etc/apk/world"].copy()
    else:
        name = {"world": "etc/apk/world", "binary": "usr/local/bin/traefik",
                "entrypoint": "entrypoint.sh", "ca": "etc/ssl/certs/ca-certificates.crt"}[mutation]
        final[name]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        INGRESS.validate_final_image(original_config, original, config, final, payload)


def real_build_metadata():
    path, result = actual_build()
    data = (path / "build-metadata.json").read_bytes()
    assert INGRESS.digest(data) == result["artifacts"]["build-metadata.json"]["sha256"]
    return json.loads(data), (path / "image-id.txt").read_text().strip()


def test_cmppatch_real_built_optional_config_digest_and_manifest_binding():
    metadata, iid = real_build_metadata()
    assert "containerimage.config.digest" not in metadata  # Actual exporter contract.
    assert INGRESS.validate_build_metadata(metadata, iid) == iid


@pytest.mark.parametrize("mutation", ["digest", "descriptor", "platform", "config", "iid"])
def test_cmppatch_real_built_metadata_drift_fails_closed(mutation):
    metadata, iid = real_build_metadata()
    if mutation == "digest":
        metadata["containerimage.digest"] = "sha256:" + "0" * 64
    elif mutation == "descriptor":
        metadata["containerimage.descriptor"]["digest"] = "sha256:" + "0" * 64
    elif mutation == "platform":
        metadata["containerimage.descriptor"]["platform"]["architecture"] = "amd64"
    elif mutation == "config":
        metadata["containerimage.config.digest"] = "not a digest"
    else:
        iid = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="built_image_identity"):
        INGRESS.validate_build_metadata(metadata, iid)


def test_cmppatch_real_built_scan_resolves_ten_openssl_advisories_without_waivers():
    _, result = actual_build()
    original = INGRESS.assess_sarif(SARIF)
    retained = {f["id"] for f in result["scan"]["findings"]}
    assert retained == {"CVE-2025-15558", "GO-2026-5932"}
    assert len({f["id"] for f in original["findings"]} - retained) == 10
    assert result["scan"]["waivers_applied"] == []
    assert result["status"] == "LIBRARIES_REPAIRED_SECURITY_BLOCKED"
    assert result["lower_layers_retained"]


def test_cmppatch_real_built_network_and_context_evidence():
    path, result = actual_build()
    data = (path / "build-network.txt").read_bytes()
    assert INGRESS.digest(data) == result["artifacts"]["build-network.txt"]["sha256"]
    for line in data.decode().splitlines():
        if line.startswith("1:"):
            assert line.split()[1].rstrip(":") == "lo"
        else:
            assert " dev lo " in line
    lock = json.loads((path / "context-lock.json").read_bytes())
    assert set(lock) == {"Dockerfile", "APKINDEX.tar.gz", "libssl3-3.5.8-r0.apk", "libcrypto3-3.5.8-r0.apk"}
    assert lock["APKINDEX.tar.gz"] == INGRESS.SIGNED_INDEX_SHA
    assert not (path / "context").exists() and result["context_removed"]


def test_cmppatch_real_signed_index_wrong_key_rejected():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    unrelated = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem = unrelated.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(InvalidSignature):
        INGRESS.verify_apk(repair_artifact("APKINDEX.tar.gz"), pem)


@pytest.mark.parametrize("filename", ["libcrypto3-3.5.8-r0.apk", "libssl3-3.5.8-r0.apk"])
def test_cmppatch_q1_formatting_requires_independent_full_sha256(filename):
    data = repair_artifact(filename)
    actual = INGRESS.apk_index_checksum(data, filename)
    name = filename.removesuffix("-3.5.8-r0.apk")
    assert actual == REPAIR_ASSESSMENT["signed_index_package_bindings"][name]
    # A corrupt APK cannot even reach the weaker, compatibility-only Q1 hash.
    with pytest.raises(ValueError, match="apk_index_requires_pinned_sha256"):
        INGRESS.apk_index_checksum(data[:-1], filename)
    with pytest.raises(ValueError, match="apk_index_requires_pinned_sha256"):
        INGRESS.apk_index_checksum(data, "unapproved.apk")

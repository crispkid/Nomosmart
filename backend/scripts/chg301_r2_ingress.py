"""CHG-301 R2 exact-image gate and bounded, network-none CLI smoke.

Candidate and repair-inspect phases collect real public artifacts, never execute
the controller. Smoke requires the separate exact applicability approval. Never
reads operator env files or accepts command/image overrides.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import ssl
import shutil
import signal
import subprocess
import tarfile
import tempfile
import urllib.request
import zlib

import yaml
import certifi

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ("docker", "--context", "desktop-linux")
VERSION = "v3.7.13"
CHART_VERSION = "41.5.0"
CHART_SHA = "30f8db73182019b2764179d7fc0a7efc9505670204f847ffc3a779bacaae3a1a"
INDEX_URL = "https://traefik.github.io/charts/index.yaml"
CHART_URL = "https://traefik.github.io/charts/traefik/traefik-41.5.0.tgz"
IMAGE = "docker.io/library/traefik:v3.7.13"
INDEX_DIGEST = "sha256:f86a2cab1b5c649070c49f883c743dd32d8485a56e3368c5f93b9e91f1e91259"
ARM64_DIGEST = "sha256:444bb54c1f7ebe5fac94d1c40f02b48c08dc005a92fc65ca29c1c75991d16baa"
REFERENCE = IMAGE + "@" + INDEX_DIGEST
GIT_BASE = ["c261a494283835af57c0e0678afc7ee7e2c0dcc8", "5f1a0a2505dee9c85ee621bd2c8680b92d397a45"]
HISTORICAL_REPAIR_APPROVAL = "3ed18f43106e87adce5e4da3bd9c997deff8374ca654cf91b58ad2b30e1aea54"
REPAIR_APPROVAL = "c0a4b2348abe9fd4b5472b172629629c5e147191fec5f38a81f09e0d7d7cbfab"
REPAIR_SECTION = "CHG-301 R2 Signed Index Material Supplement"
SIGNED_INDEX_SHA = "f0ee7c9c6bb43109521715530f6c1922bd486207ae63e598557ce2900e5a1a49"
BATCH_STARTED = "2026-09-15T14:17:52.088462+00:00"
BATCH_DEADLINE = "2026-09-15T20:17:52.088462+00:00"
SMOKE_SECTION = "CHG-301 R2 Accepted Applicability And Isolated Verification Continuation"
ACCEPTANCE_SHA = "87c5c7b4e26e363a51a8328780955b93d57855d40821e51f2e883807b10a7110"
ACCEPTANCE_PATH = ROOT / "docs/CHG-301-R2-APPLICABILITY-ACCEPTANCE.json"
ACCEPTED_IMAGE = "sha256:5043ce31721c19e4a3a18afd60f449a7c842d46a52ec1ed6d7fdfb84a68cf7cd"
ACCEPTED_TAG = "nomosmart-test/traefik:3.7.13-chg301-r2-say0hh9k"
ACCEPTED_BUILD = Path("/private/tmp/chg301-r2-two-lib-say0hh9k")
# Build-time snapshots predate these reviewed post-build documentation updates
# (00:12/00:17 local). Product bytes must still match the build snapshot exactly.
POST_BUILD_DOCS = {
    "docs/CHG-301-R2-SIGNED-INDEX-PLAN.md": "f83aaa340909a51a82e739956ca64659e5124f1462b76bc1b18ce7d274c30941",
    "docs/CHG-301-R2-TWO-LIBRARY-PLAN.md": "a5c1362fbaef72de89eebdb16a064e5f5359cf8fd7c589a32bd4ba2cf5ddad08",
}
RECIPE = ROOT / "deploy/test/chg301-r2-traefik/Dockerfile"
APK_BASE = "https://dl-cdn.alpinelinux.org/alpine/v3.24/main/aarch64/"
REPAIR_DOWNLOADS = {
    "openssl-3.5.8-r0.apk": "0d12f4f145ec045dd19e8465bd3cb07b08197f96a3776641511dc2bec53cc0b7",
    "libssl3-3.5.8-r0.apk": "d6ec970cc10e01539e41626f720c4e0ac69016eaa2079a10ef776ffd3243db5b",
    "libcrypto3-3.5.8-r0.apk": "35b892813c23664a3592e4fc8c12a03538a22c579057655361c7043305272a9a",
}
# Historical artifact inventory above is intentionally not the install allowlist.
REPAIR_TARGETS = ("libcrypto3", "libssl3")
BASELINE_VERSIONS = {
    "alpine-baselayout": "3.7.2-r1", "alpine-baselayout-data": "3.7.2-r1",
    "alpine-keys": "2.6-r0", "alpine-release": "3.24.1-r0", "apk-tools": "3.0.6-r0",
    "busybox": "1.37.0-r31", "busybox-binsh": "1.37.0-r31",
    "ca-certificates": "20260611-r0", "ca-certificates-bundle": "20260611-r0",
    "libapk": "3.0.6-r0", "libcrypto3": "3.5.7-r0", "libssl3": "3.5.7-r0",
    "musl": "1.2.6-r2", "musl-utils": "1.2.6-r2", "scanelf": "1.3.9-r1",
    "ssl_client": "1.37.0-r31", "tzdata": "2026c-r0", "zlib": "1.3.2-r0",
}
TOOL_MOD_URL = "https://proxy.golang.org/golang.org/x/vuln/@v/v1.8.0.mod"
TOOL_MOD_SHA = "db905ebdb09329cf41098ae5553f4869428615173ac6f767d82176093887d3a2"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apk_index_checksum(data, filename):
    # Security rests on the complete, explicitly approved SHA256 bytes. Q1 is
    # only the legacy APK v2 index identifier, never an acceptance mechanism.
    if filename not in REPAIR_DOWNLOADS or digest(data) != REPAIR_DOWNLOADS[filename]:
        raise ValueError("apk_index_requires_pinned_sha256")
    control = gzip_segments(data)[1][0]
    return "Q1" + base64.b64encode(hashlib.sha1(control, usedforsecurity=False).digest()).decode()


def save(path, value):
    data = value if isinstance(value, bytes) else json.dumps(value, indent=2, ensure_ascii=False).encode()
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write(data)


def source_snapshot():
    paths = {Path("backend/pyproject.toml"), Path("backend/uv.lock"),
             Path("frontend/package.json"), Path("frontend/package-lock.json"),
             Path("docker-compose.yml"), Path("backend/scripts/chg301_r2_ingress.py"),
             Path("backend/tests/test_chg301_r2_ingress.py"),
             Path("docs/CHG-301-R2-TRAEFIK-PLAN.md"),
             Path("docs/CHG-301-R2-TRAEFIK-REMEDIATION-PLAN.md"),
             Path("docs/CHG-301-R2-TWO-LIBRARY-PLAN.md"),
             Path("docs/CHG-301-R2-SIGNED-INDEX-PLAN.md"),
             RECIPE.relative_to(ROOT)}
    for directory in ("backend/app", "frontend/src", "deploy/helm/nomosmart", "sql"):
        paths.update(p.relative_to(ROOT) for p in (ROOT / directory).rglob("*")
                     if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".json", ".yaml", ".yml", ".tpl", ".sql", ".css"}
                     and not any(v in {"__pycache__", "node_modules", ".venv", ".git"} for v in p.parts))
    output = {}
    for rel in sorted(paths):
        path = ROOT / rel
        if not path.is_file() or path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError("source_identity")
        output[str(rel)] = digest(path.read_bytes())
    return output


def fetch(url):
    if url not in {INDEX_URL, CHART_URL, TOOL_MOD_URL, APK_BASE + "APKINDEX.tar.gz",
                   *(APK_BASE + name for name in REPAIR_DOWNLOADS)}:
        raise ValueError("unapproved_public_url")
    # No auth, operator proxy settings, redirects or application endpoints.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    # This host's Python has no default CA file. Use the already-installed
    # Mozilla CA bundle explicitly; certificate/hostname verification stays on.
    tls = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=tls))
    with opener.open(url, timeout=30) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("public_download_response")
        data = response.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("public_download_size")
        return data


def validate_chart(index_bytes, archive):
    index = yaml.safe_load(index_bytes)
    choices = [v for v in index["entries"]["traefik"] if v["version"] == CHART_VERSION]
    if len(choices) != 1:
        raise ValueError("chart_version")
    entry = choices[0]
    if (entry["appVersion"] != VERSION or entry["digest"] != CHART_SHA
            or entry["urls"] != [CHART_URL] or digest(archive) != CHART_SHA):
        raise ValueError("chart_binding")
    # Read exact regular members in memory; never extract paths or execute hooks.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        selected = {}
        for name in ("traefik/Chart.yaml", "traefik/values.yaml"):
            members = [m for m in tar.getmembers() if m.name == name]
            if len(members) != 1 or not members[0].isfile() or members[0].size > 2 * 1024 * 1024:
                raise ValueError("chart_member")
            selected[name] = tar.extractfile(members[0]).read()
    meta = yaml.safe_load(selected["traefik/Chart.yaml"])
    values = yaml.safe_load(selected["traefik/values.yaml"])
    if meta["name"] != "traefik" or meta["version"] != CHART_VERSION or meta["appVersion"] != VERSION:
        raise ValueError("chart_metadata")
    if "kubernetesIngressNGINX" not in values.get("providers", {}):
        raise ValueError("chart_provider_missing")
    return {"version": CHART_VERSION, "app_version": VERSION, "sha256": CHART_SHA,
            "url": CHART_URL, "kube_version": meta.get("kubeVersion"),
            "compatible_provider_present": True}, selected


def validate_image(value):
    platforms = [m for m in value.get("manifests", [])
                 if m.get("platform", {}).get("os") == "linux"
                 and m.get("platform", {}).get("architecture") == "arm64"]
    if value.get("digest") != INDEX_DIGEST or len(platforms) != 1 or platforms[0]["digest"] != ARM64_DIGEST:
        raise ValueError("image_identity")
    if platforms[0].get("annotations", {}).get("org.opencontainers.image.version") != VERSION:
        raise ValueError("image_version")
    return {"reference": REFERENCE, "index_digest": INDEX_DIGEST,
            "arm64_digest": ARM64_DIGEST, "platform": "linux/arm64"}


def assess_sarif(report):
    if report.get("version") != "2.1.0" or len(report.get("runs", [])) != 1:
        raise ValueError("sarif_structure")
    run = report["runs"][0]
    if run["tool"]["driver"].get("name") != "docker scout":
        raise ValueError("scanner_identity")
    rules = run["tool"]["driver"].get("rules", [])
    results = run.get("results")
    if not isinstance(results, list):
        raise ValueError("sarif_results")
    if any(i.get("executionSuccessful") is False for i in run.get("invocations", [])):
        raise ValueError("scanner_execution")
    by_id = {}
    for rule in rules:
        if rule["id"] in by_id:
            raise ValueError("duplicate_sarif_rule")
        by_id[rule["id"]] = rule
    found = {}
    for result in results:
        ident = result.get("ruleId")
        if ident not in by_id or result.get("suppressions"):
            raise ValueError("unresolved_or_suppressed_result")
        rule = by_id[ident]
        severity = rule.get("properties", {}).get("cvssV3_severity", "UNSPECIFIED").upper()
        if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNSPECIFIED"}:
            severity = "UNSPECIFIED"
        found[ident] = {"id": ident, "severity": severity, "properties": rule.get("properties", {}),
                        "upstream_description": rule.get("help", {}).get("text", ""),
                        "scanner_url": rule.get("helpUri")}
    if set(by_id) != set(found):
        raise ValueError("unmatched_sarif_rules")
    counts = Counter(row["severity"] for row in found.values())
    blocked = sum(counts[v] for v in ("HIGH", "CRITICAL", "UNSPECIFIED"))
    return {"status": "BLOCKED_FINDINGS" if blocked else "CANDIDATE_SCAN_ONLY_PASS",
            "unique_advisories": len(found),
            "unique_cves": sum(ident.startswith("CVE-") for ident in found),
            "result_instances": len(results),
            "severity_counts": dict(counts), "unaccepted_high_critical": counts["HIGH"] + counts["CRITICAL"],
            "unclassified": counts["UNSPECIFIED"], "findings": list(found.values()),
            "waivers_applied": [], "runtime_exploitability_verified": False}


def candidate():
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-traefik-", dir="/private/tmp"))
    work.chmod(0o700)
    evidence = {"scope": "CHG-301 R2 Traefik candidate registry-only", "phase": "candidate",
                "started_at": datetime.now(UTC).isoformat(), "status": "BLOCKED_ERROR",
                "kubernetes_operations": 0, "provider_calls": 0, "container_execution": 0,
                "commands": [], "database_version": "not exposed by Scout SARIF; no independent freshness assertion"}
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["DOCKER_CLI_HINTS"] = "false"
    def command(args, timeout=60, retain_stdout=True):
        result = subprocess.run(args, cwd=work, env=env, capture_output=True, timeout=timeout)
        ordinal = len(evidence["commands"])
        if retain_stdout:
            save(work / f"command-{ordinal:02d}.stdout", result.stdout)
        save(work / f"command-{ordinal:02d}.stderr", result.stderr)
        evidence["commands"].append({"argv": list(args), "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError("tool_exit_" + str(result.returncode))
        return result.stdout
    source = None
    try:
        approval = (ROOT / "DEVELOPMENT_PLAN.md").read_text().split("\n## CHG-301 R2 Full Coverage", 1)[0]
        if "Gate 4 approval: APPROVED." not in approval or "11a36a1c5ee3e5ec664cb628b2d088d69ce072b47aadec0de155e791d18733aa" not in approval:
            raise ValueError("approval_missing")
        git = command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split()
        if git != GIT_BASE:
            raise ValueError("source_baseline_drift")
        evidence["git"] = git
        # Diff output may include private user edits; never persist its content.
        evidence["dirty_diff_sha256"] = digest(command(
            ["git", "-C", str(ROOT), "diff", "HEAD", "--binary"], retain_stdout=False))
        source = source_snapshot()
        save(work / "source-manifest.json", source)
        evidence["source_manifest_sha256"] = digest((work / "source-manifest.json").read_bytes())
        evidence["source_file_count"] = len(source)
        evidence["download_ca_bundle_sha256"] = digest(Path(certifi.where()).read_bytes())
        index, chart = fetch(INDEX_URL), fetch(CHART_URL)
        save(work / "chart-index.yaml", index)
        save(work / "traefik-41.5.0.tgz", chart)
        evidence["chart"], members = validate_chart(index, chart)
        for name, data in members.items():
            save(work / Path(name).name, data)
        value = json.loads(command([*DOCKER, "buildx", "imagetools", "inspect", IMAGE, "--format", "{{json .Manifest}}"], 120))
        save(work / "image-index.json", value)
        evidence["image"] = validate_image(value)
        command([*DOCKER, "scout", "version"])
        registry = "registry://" + REFERENCE
        command([*DOCKER, "scout", "cves", "--platform", "linux/arm64", "--format", "sarif",
                 "--output", str(work / "all-severity.sarif.json"), registry], 1200)
        command([*DOCKER, "scout", "sbom", "--platform", "linux/arm64", "--format", "spdx",
                 "--output", str(work / "sbom.spdx.json"), registry], 1200)
        sbom = json.loads((work / "sbom.spdx.json").read_bytes())
        purls = [ref.get("referenceLocator", "") for p in sbom.get("packages", []) for ref in p.get("externalRefs", [])]
        image_purls = [p for p in purls if p.startswith("pkg:oci/") and ARM64_DIGEST in p]
        if not image_purls or not sbom.get("spdxVersion", "").startswith("SPDX-"):
            raise ValueError("sbom_image_binding")
        evidence["sbom"] = {"packages_including_image": len(sbom["packages"]),
                            "image_purls": image_purls, "creation_info": sbom.get("creationInfo")}
        evidence["assessment"] = assess_sarif(json.loads((work / "all-severity.sarif.json").read_bytes()))
        evidence["status"] = evidence["assessment"]["status"]
        # Re-read tag metadata; do not reuse results after registry drift.
        validate_image(json.loads(command([*DOCKER, "buildx", "imagetools", "inspect", IMAGE,
                                           "--format", "{{json .Manifest}}"], 120)))
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        # Only our fixed diagnostic identifiers are safe for public evidence.
        if type(exc) is ValueError and len(exc.args) == 1 and isinstance(exc.args[0], str):
            ident = exc.args[0]
            if ident.isascii() and ident.replace("_", "").isalpha() and len(ident) < 60:
                evidence["error_code"] = ident
        # Deliberately do not publish raw exception text/credentials.
        evidence["status"] = "BLOCKED_ERROR"
    finally:
        if source is not None:
            try:
                evidence["source_unchanged"] = source == source_snapshot()
            except Exception:
                evidence["source_unchanged"] = False
            if not evidence["source_unchanged"]:
                evidence["status"] = "BLOCKED_SOURCE_DRIFT"
        evidence["artifacts"] = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                                 for p in sorted(work.iterdir()) if p.is_file()}
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        save(work / "result.json", evidence)
        print(json.dumps({"status": evidence["status"], "evidence": str(work / "result.json"),
                          "scan": {k: v for k, v in evidence.get("assessment", {}).items() if k != "findings"}}, indent=2))
    return 0 if evidence["status"] == "CANDIDATE_SCAN_ONLY_PASS" else 1


def repair_approval(text):
    sections = text.split("\n## ")
    if len(sections) < 2 or sections[1].split("\n", 1)[0] != REPAIR_SECTION:
        raise ValueError("repair_approval_missing")
    section = sections[1]
    if ("Gate 4 approval: APPROVED." not in section or REPAIR_APPROVAL not in section
        or "Plan Approval: APPROVED explicitly by Peter" not in section
        or "Gate 4 approval: PENDING" in section):
        raise ValueError("repair_approval_missing")


def safe_tar_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\x00" in name or "\\" in name:
        raise ValueError("unsafe_archive_path")
    return str(path)


def tar_records(data):
    """Bounded, in-memory only; no extractall, links or executable writes."""
    records = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        total = 0
        for ordinal, member in enumerate(archive):
            name = safe_tar_name(member.name)
            total += member.size
            if ordinal > 50000 or total > 512 * 1024**2 or member.size > 256 * 1024**2:
                raise ValueError("archive_size_limit")
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError("archive_special_file")
            if name in records:
                raise ValueError("archive_duplicate_path")
            raw = archive.extractfile(member).read() if member.isfile() else None
            records[name] = {"type": member.type.decode(), "mode": member.mode,
                             "uid": member.uid, "gid": member.gid, "link": member.linkname,
                             "sha256": digest(raw) if raw is not None else None, "data": raw}
    return records


def gzip_segments(data, limit=256 * 1024**2):
    parts = []
    while data:
        if len(parts) >= 4:
            raise ValueError("gzip_segment_count")
        decoder = zlib.decompressobj(31)
        plain = decoder.decompress(data, limit + 1)
        if len(plain) > limit or not decoder.eof:
            raise ValueError("gzip_size_limit")
        consumed = len(data) - len(decoder.unused_data)
        parts.append((data[:consumed], plain))
        data = decoder.unused_data
    return parts


def image_rootfs(path, expected_manifest=None):
    """Validate OCI blobs/diff IDs and reconstruct effective entries in memory."""
    if path.stat().st_size > 1024**3 or path.is_symlink():
        raise ValueError("image_archive_bound")
    with tarfile.open(path, mode="r:") as archive:
        members = {}
        for ordinal, member in enumerate(archive):
            name = safe_tar_name(member.name)
            if ordinal > 10000 or name in members or not (member.isdir() or member.isfile()):
                raise ValueError("image_archive_member")
            members[name] = member
        def read(name, maximum=256 * 1024**2):
            member = members.get(name)
            if member is None or not member.isfile() or member.size > maximum:
                raise ValueError("image_blob_member")
            data = archive.extractfile(member).read()
            if name.startswith("blobs/sha256/") and digest(data) != name.rsplit("/", 1)[1]:
                raise ValueError("image_blob_digest")
            return data
        manifests = json.loads(read("manifest.json", 1024**2))
        if len(manifests) != 1:
            raise ValueError("image_manifest_count")
        manifest = manifests[0]
        config = json.loads(read(manifest["Config"], 1024**2))
        if config.get("os") != "linux" or config.get("architecture") != "arm64":
            raise ValueError("image_platform")
        if expected_manifest:
            bound = json.loads(read("blobs/sha256/" + expected_manifest.removeprefix("sha256:"), 1024**2))
            if ("blobs/sha256/" + bound["config"]["digest"].removeprefix("sha256:") != manifest["Config"]
                or ["blobs/sha256/" + x["digest"].removeprefix("sha256:") for x in bound["layers"]] != manifest["Layers"]):
                raise ValueError("image_manifest_binding")
        diffs = config["rootfs"]["diff_ids"]
        if len(diffs) != len(manifest["Layers"]) or len(diffs) > 20:
            raise ValueError("image_layer_count")
        effective = {}
        for name, expected in zip(manifest["Layers"], diffs):
            raw = read(name)
            if raw.startswith(b"\x1f\x8b"):
                segments = gzip_segments(raw)
                if len(segments) != 1:
                    raise ValueError("image_layer_gzip_segments")
                plain = segments[0][1]
            else:
                plain = raw
            if "sha256:" + digest(plain) != expected:
                raise ValueError("image_layer_diffid")
            layer = tar_records(plain)
            # Whiteouts affect only lower layers, never later entries in this layer.
            for key in layer:
                p = PurePosixPath(key)
                if p.name == ".wh..wh..opq":
                    prefix = str(p.parent) + "/"
                    effective = {k: v for k, v in effective.items() if not k.startswith(prefix)}
                elif p.name.startswith(".wh."):
                    target = str(p.with_name(p.name[4:]))
                    effective = {k: v for k, v in effective.items() if k != target and not k.startswith(target + "/")}
            for key, value in layer.items():
                if PurePosixPath(key).name.startswith(".wh."):
                    continue
                for parent in PurePosixPath(key).parents:
                    if str(parent) in effective and effective[str(parent)]["type"] != "5":
                        raise ValueError("image_symlink_parent")
                if value["type"] == "1":
                    target = safe_tar_name(value["link"])
                    linked = layer.get(target, effective.get(target))
                    if linked is None or linked["type"] != "0":
                        raise ValueError("image_hardlink_target")
                    value = {**value, "type": "0", "link": "", "data": linked["data"], "sha256": linked["sha256"]}
                effective[key] = value
        return config, effective


def verify_apk(data, key, expected_name=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    parts = gzip_segments(data, 32 * 1024**2)
    if len(parts) != (3 if expected_name else 2):
        raise ValueError("apk_segments")
    signed = tar_records(parts[0][1])
    key_name = ".SIGN.RSA.alpine-devel@lists.alpinelinux.org-616ae350.rsa.pub"
    if set(signed) != {key_name} or signed[key_name]["data"] is None:
        raise ValueError("apk_signature_identity")
    serialization.load_pem_public_key(key).verify(signed[key_name]["data"], parts[1][0], padding.PKCS1v15(), hashes.SHA1())
    control = tar_records(parts[1][1])
    if not expected_name:
        return control
    if set(control) != {".PKGINFO"}:
        raise ValueError("apk_unreviewed_script")
    metadata = {}
    for line in control[".PKGINFO"]["data"].decode().splitlines():
        if " = " in line and not line.startswith("#"):
            k, v = line.split(" = ", 1)
            metadata.setdefault(k, []).append(v)
    validate_apk_metadata(metadata, expected_name, digest(parts[2][0]))
    return metadata, tar_records(parts[2][1])


def validate_apk_metadata(metadata, expected_name, data_hash):
    if (expected_name + "-3.5.8-r0.apk" not in REPAIR_DOWNLOADS
        or metadata.get("pkgname") != [expected_name] or metadata.get("pkgver") != ["3.5.8-r0"]
        or metadata.get("arch") != ["aarch64"] or metadata.get("datahash") != [data_hash]):
        raise ValueError("apk_metadata_or_datahash")
    allowed = {"so:libc.musl-aarch64.so.1", "so:libcrypto.so.3", "so:libssl.so.3",
               "libcrypto3=3.5.8-r0", "libssl3=3.5.8-r0"}
    if not set(metadata.get("depend", [])).issubset(allowed):
        raise ValueError("apk_extra_dependency")


def installed_packages(data):
    result = {}
    for block in data.decode().strip().split("\n\n"):
        row = {}
        for line in block.splitlines():
            if line[:2] in {"P:", "V:", "A:", "p:", "D:"}:
                if line[:1] in row:
                    raise ValueError("package_database_duplicate")
                row[line[:1]] = line[2:]
        if "P" not in row or "V" not in row or "A" not in row or row["P"] in result:
            raise ValueError("package_database_identity")
        result[row["P"]] = row
    return result


def validate_repair_scope(installed):
    """Approval is an upgrade, not permission to install an absent executable."""
    for name in REPAIR_TARGETS:
        if name not in installed:
            raise ValueError("approved_upgrade_package_absent")
    if set(installed) != set(BASELINE_VERSIONS) or any(
        row["V"] != BASELINE_VERSIONS[name] or row["A"] != "aarch64"
        for name, row in installed.items()
    ):
        raise ValueError("approved_upgrade_baseline_drift")


def json_messages(raw):
    text = raw.decode()
    decoder = json.JSONDecoder()
    messages = []
    while text.strip():
        text = text.lstrip()
        value, end = decoder.raw_decode(text)
        if not isinstance(value, dict):
            raise ValueError("analysis_message_shape")
        messages.append(value)
        text = text[end:]
    return messages


def analysis_capability(extracted, report):
    if len(extracted) != 2 or extracted[0] != {"name": "govulncheck-extract", "version": "0.1.0"}:
        raise ValueError("analysis_extract_protocol")
    binary = extracted[1]
    if binary.get("goos") != "linux" or binary.get("goarch") != "arm64":
        raise ValueError("analysis_build_platform")
    config = [x["config"] for x in report if "config" in x]
    if len(config) != 1 or config[0].get("scanner_version") != "v1.8.0" or config[0].get("scan_mode") != "binary":
        raise ValueError("analysis_scanner_identity")
    symbols = binary.get("pkgSymbols") or []
    return {"symbols_count": len(symbols), "symbols_available": bool(symbols),
            "precision": "symbol_inventory_not_call_graph" if symbols else "module_only_stripped_fallback",
            "openpgp": "INDETERMINATE", "database": config[0].get("db"),
            "database_last_modified": config[0].get("db_last_modified"),
            "findings": [x["finding"] for x in report if "finding" in x], "vex_applied": []}


def repair_assess():
    work = repair_work()
    previous = json.loads((work / "analysis-result.json").read_bytes())
    if digest((work / "traefik.elf").read_bytes()) != previous["binary_sha256"]:
        raise ValueError("analysis_binary_digest")
    env = {"PATH": os.environ["PATH"], "HOME": str(work), "GOENV": "off", "GOTOOLCHAIN": "local", "GOTELEMETRY": "off"}
    proc = subprocess.run([str(work / "tools/govulncheck"), "-mode=extract", str(work / "traefik.elf")],
                          env=env, cwd=work, capture_output=True, timeout=120)
    save(work / "govulncheck-extract.json", proc.stdout)
    save(work / "govulncheck-extract.stderr", proc.stderr)
    if proc.returncode:
        raise ValueError("analysis_extract_failed")
    capability = analysis_capability(json_messages(proc.stdout), json_messages((work / "govulncheck.json").read_bytes()))
    config, fs = image_rootfs(work / "original-image.tar", ARM64_DIGEST)
    installed = installed_packages(fs["lib/apk/db/installed"]["data"])
    evidence = {"status": "BLOCKED_SCOPE_AND_ANALYSIS", "approval_sha256": REPAIR_APPROVAL,
                "binary_sha256": previous["binary_sha256"], "image_manifest": ARM64_DIGEST,
                "capability": capability, "installed_packages": installed,
                "openssl_executable_present": "usr/bin/openssl" in fs,
                "controller_executions": 0, "image_builds": 0, "provider_calls": 0, "kubernetes_operations": 0}
    try:
        validate_repair_scope(installed)
    except ValueError as exc:
        evidence["scope_blocker"] = str(exc)
    # Bind signatures to signed index's control checksum and exact file length,
    # not just an identical package name/version text entry.
    key = fs["etc/apk/keys/alpine-devel@lists.alpinelinux.org-616ae350.rsa.pub"]["data"]
    index = verify_apk((work / "APKINDEX.tar.gz").read_bytes(), key)["APKINDEX"]["data"].decode()
    evidence["signed_index_package_bindings"] = {}
    for filename in REPAIR_DOWNLOADS:
        name = filename.removesuffix("-3.5.8-r0.apk")
        data = (work / filename).read_bytes()
        parts = gzip_segments(data)
        checksum = apk_index_checksum(data, filename)
        rows = [r for r in index.split("\n\n") if f"P:{name}\n" in r and "V:3.5.8-r0\n" in r]
        if len(rows) != 1 or f"C:{checksum}\n" not in rows[0] or f"S:{len(data)}\n" not in rows[0] or "A:aarch64\n" not in rows[0]:
            raise ValueError("apk_index_checksum_binding")
        evidence["signed_index_package_bindings"][name] = checksum
    modules = json_messages(proc.stdout)[1].get("modules", [])
    cli = [m for m in modules if m.get("Path") == "github.com/docker/cli"]
    if len(cli) != 1 or cli[0].get("Version") != "v29.7.2+incompatible" or cli[0].get("Replace"):
        raise ValueError("docker_cli_module_identity")
    evidence["docker_cli"] = {"modules": cli, "os": config["os"],
        "assessment": "PROPOSED_NOT_AFFECTED", "basis": "Linux/arm64 and actual module version >= upstream fixed 29.2.0; no waiver applied"}
    scripts = fs["lib/apk/db/scripts.tar.gz"]["data"]
    save(work / "original-apk-scripts.tar.gz", scripts)
    evidence["script_inventory"] = list(tar_records(gzip_segments(scripts)[0][1]))
    evidence["source_manifest"] = source_snapshot()
    evidence["artifacts"] = {n: digest((work / n).read_bytes()) for n in (
        "original-image.tar", "analysis-result.json", "govulncheck.json", "govulncheck-extract.json",
        "traefik-build-info.txt", "lib-apk-db-installed.bin", "original-apk-scripts.tar.gz")}
    save(work / "assessment-result.json", evidence)
    print(json.dumps({"status": evidence["status"], "scope_blocker": evidence.get("scope_blocker"),
                      "capability": {k: v for k, v in capability.items() if k != "findings"},
                      "evidence": str(work / "assessment-result.json")}, indent=2))
    return 1


def repair_work():
    repair_approval((ROOT / "DEVELOPMENT_PLAN.md").read_text())
    given = Path(os.environ.get("CHG301_R2_REPAIR_EVIDENCE", ""))
    path = given.resolve(strict=True)
    if (path != given or path.parent != Path("/private/tmp") or not path.name.startswith("chg301-r2-repair-")
        or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid()):
        raise ValueError("repair_work_identity")
    evidence = json.loads((path / "inspect-result.json").read_bytes())
    if evidence.get("status") != "ARTIFACTS_COLLECTED_NOT_SIGNATURE_OR_BUILD_PASS" or evidence.get("approval_sha256") != HISTORICAL_REPAIR_APPROVAL:
        raise ValueError("repair_inspect_required")
    for name in (*REPAIR_DOWNLOADS, "original-image.tar", "APKINDEX.tar.gz"):
        if (path / name).is_symlink() or digest((path / name).read_bytes()) != evidence["artifacts"][name]["sha256"]:
            raise ValueError("repair_artifact_digest")
    if digest((path / "tools/govulncheck").read_bytes()) != evidence["govulncheck_sha256"]:
        raise ValueError("repair_tool_digest")
    return path


def repair_analyze():
    work = repair_work()
    config, fs = image_rootfs(work / "original-image.tar", ARM64_DIGEST)
    save(work / "original-config.json", config)
    save(work / "original-rootfs.json", {k: {n: v for n, v in row.items() if n != "data"} for k, row in fs.items()})
    key = fs["etc/apk/keys/alpine-devel@lists.alpinelinux.org-616ae350.rsa.pub"]["data"]
    save(work / "alpine-signing-key.pem", key)
    index = verify_apk((work / "APKINDEX.tar.gz").read_bytes(), key)
    packages = {}
    for filename in REPAIR_DOWNLOADS:
        name = filename.removesuffix("-3.5.8-r0.apk")
        meta, files = verify_apk((work / filename).read_bytes(), key, name)
        matching = [row for row in index["APKINDEX"]["data"].decode().split("\n\n") if f"P:{name}\n" in row and "V:3.5.8-r0\n" in row]
        if len(matching) != 1:
            raise ValueError("apk_index_version")
        packages[name] = {"metadata": meta, "signature_verified": True,
                          "files": {k: {n: v for n, v in row.items() if n != "data"} for k, row in files.items()}}
    binary = fs["usr/local/bin/traefik"]["data"]
    if binary[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", binary, 18)[0] != 183:
        raise ValueError("binary_architecture")
    phoff = struct.unpack_from("<Q", binary, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", binary, 54)
    if phentsize != 56 or phnum > 1024 or phoff + phentsize * phnum > len(binary):
        raise ValueError("binary_program_headers")
    types = [struct.unpack_from("<I", binary, phoff + n * phentsize)[0] for n in range(phnum)]
    save(work / "traefik.elf", binary)  # 0600, never executable.
    save(work / "entrypoint.txt", fs["entrypoint.sh"]["data"])
    for name in ("lib/apk/db/installed", "lib/apk/db/triggers", "lib/apk/db/scripts.tar", "etc/apk/world"):
        if name in fs:
            save(work / (name.replace("/", "-") + ".bin"), fs[name]["data"])
    evidence = {"binary_sha256": digest(binary), "entrypoint_sha256": fs["entrypoint.sh"]["sha256"],
                "elf": {"architecture": "aarch64", "dynamic_segment": 2 in types, "interpreter_segment": 3 in types},
                "signing_key_sha256": digest(key), "index_signature_verified": True, "packages": packages,
                "controller_executions": 0, "vex_applied": [], "status": "STATIC_ANALYSIS_ONLY"}
    env = {"PATH": os.environ["PATH"], "HOME": str(work), "GOENV": "off", "GOTOOLCHAIN": "local",
           "GOTELEMETRY": "off", "SSL_CERT_FILE": certifi.where(), "GOCACHE": str(work / "gocache")}
    commands = [(["go", "version", "-m", str(work / "traefik.elf")], "traefik-build-info.txt"),
                ([str(work / "tools/govulncheck"), "-mode=binary", "-json", str(work / "traefik.elf")], "govulncheck.json")]
    for args, filename in commands:
        process = subprocess.run(args, cwd=work, env=env, capture_output=True, timeout=600)
        save(work / filename, process.stdout)
        save(work / (filename + ".stderr"), process.stderr)
        evidence[filename] = {"sha256": digest(process.stdout), "exit_code": process.returncode}
        if process.returncode:
            evidence["status"] = "INDETERMINATE_TOOL_FAILURE"
    evidence["source_manifest"] = source_snapshot()
    save(work / "analysis-result.json", evidence)
    print(json.dumps({"status": evidence["status"], "evidence": str(work / "analysis-result.json"),
                      "elf": evidence["elf"], "signed_packages": list(packages)}, indent=2))
    return 0 if evidence["status"] == "STATIC_ANALYSIS_ONLY" else 1


def repair_cleanup():
    """Remove only the newly pulled reference and this run's disposable Go cache."""
    work = repair_work()
    before = json.loads((work / "baseline-before.json").read_bytes())
    if any(INDEX_DIGEST in item for item in before["images"]):
        raise ValueError("cleanup_preexisting_image")
    preflight_path = Path(os.environ.get("CHG301_R2_PREFLIGHT_EVIDENCE", "")).resolve(strict=True)
    if not preflight_path.parent.name.startswith("chg301-r2-preflight-") or preflight_path.parent.parent != Path("/private/tmp"):
        raise ValueError("cleanup_preflight_identity")
    preflight = json.loads(preflight_path.read_bytes())
    if preflight.get("status") != "MEASURED_NOT_CLUSTER_APPROVAL" or not preflight.get("probe_removed") or not preflight.get("baseline_unchanged"):
        raise ValueError("cleanup_preflight_state")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    def command(args):
        proc = subprocess.run([*DOCKER, *args], env=env, cwd=work, capture_output=True, timeout=60)
        if proc.returncode:
            raise RuntimeError("cleanup_tool_failed")
        return proc.stdout
    image = json.loads(command(["image", "inspect", "--format", '{{json .Id}}', REFERENCE]))
    if image != INDEX_DIGEST or command(["ps", "-aq", "--filter", "ancestor=" + REFERENCE]).strip():
        raise ValueError("cleanup_image_identity_or_in_use")
    cache = work / "gocache"
    if cache.is_symlink() or not cache.is_dir() or cache.stat().st_uid != os.getuid():
        raise ValueError("cleanup_cache_owner")
    proof = work / "go/pkg/mod/golang.org/x/vuln@v1.8.0/internal/vulncheck/binary.go"
    save(work / "govulncheck-binary-analysis-source.go", proof.read_bytes())
    manifest = {"run": work.name, "image_reference": REFERENCE, "image_id": image,
                "directory": str(cache), "force_image_removal": False, "prune": False}
    save(work / "cleanup-owned.json", manifest)
    save(work / "cleanup-image.stdout", command(["image", "rm", "--no-prune", REFERENCE]))
    shutil.rmtree(cache)
    networks = sorted(command(["network", "ls", "--no-trunc", "--format", '{{.ID}} {{.Name}}']).decode().splitlines())
    images = sorted(command(["image", "ls", "--no-trunc", "--format", '{{.Repository}}:{{.Tag}} {{.ID}}']).decode().splitlines())
    ids = sorted(command(["ps", "-aq", "--no-trunc"]).decode().split())
    containers = [json.loads(command(["inspect", "--format",
        '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', ident])) for ident in ids]
    evidence = {"status": "CLEANED_OWNED_RESOURCES", "network_baseline_unchanged": networks == before["networks"],
                "image_baseline_unchanged": images == before["images"],
                "container_baseline_unchanged": containers == preflight["baseline"],
                "containers": containers, "source_manifest": source_snapshot(),
                "preflight_sha256": digest(preflight_path.read_bytes()),
                "removed": manifest, "retained": ["signed public APK/index", "original OCI archive and 0600 binary",
                "fixed govulncheck tool/public module provenance", "raw analysis/evidence/test reports"],
                "controller_executions": 0, "image_builds": 0, "kubernetes_operations": 0, "provider_calls": 0}
    if not all(evidence[k] for k in ("network_baseline_unchanged", "image_baseline_unchanged", "container_baseline_unchanged")):
        evidence["status"] = "EXTERNAL_BASELINE_DRIFT"
    save(work / "cleanup-result.json", evidence)
    print(json.dumps({k: v for k, v in evidence.items() if k not in {"containers", "source_manifest"}}, indent=2))
    return 0 if evidence["status"] == "CLEANED_OWNED_RESOURCES" else 1


def repair_inspect():
    """Collect pinned inputs and static-analysis tools; no build or image startup."""
    repair_approval((ROOT / "DEVELOPMENT_PLAN.md").read_text())
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-repair-", dir="/private/tmp"))
    work.chmod(0o700)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["DOCKER_CLI_HINTS"] = "false"
    result = {"scope": "CHG-301 R2 repair inspect only", "approval_sha256": REPAIR_APPROVAL,
              "started_at": datetime.now(UTC).isoformat(), "commands": [],
              "controller_executions": 0, "kubernetes_operations": 0, "provider_calls": 0,
              "status": "BLOCKED_ERROR", "downloads": {}}
    def command(args, timeout=120, custom_env=None, retain_stdout=True):
        proc = subprocess.run(args, env=custom_env or env, cwd=work,
                              capture_output=True, timeout=timeout)
        ordinal = len(result["commands"])
        if retain_stdout:
            save(work / f"inspect-{ordinal:02d}.stdout", proc.stdout)
        save(work / f"inspect-{ordinal:02d}.stderr", proc.stderr)
        result["commands"].append({"argv": list(args), "exit_code": proc.returncode})
        if proc.returncode:
            raise RuntimeError("tool_exit")
        return proc.stdout
    def baseline():
        return {"containers": command([*DOCKER, "ps", "-a", "--no-trunc", "--format",
                '{{.ID}} {{.Status}} {{.Names}}']).decode().splitlines(),
                "networks": sorted(command([*DOCKER, "network", "ls", "--no-trunc", "--format",
                '{{.ID}} {{.Name}}']).decode().splitlines()),
                "images": sorted(command([*DOCKER, "image", "ls", "--no-trunc", "--format",
                '{{.Repository}}:{{.Tag}} {{.ID}}']).decode().splitlines())}
    source = None
    before = None
    try:
        git = command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split()
        if git != GIT_BASE:
            raise ValueError("source_baseline_drift")
        result["git"] = git
        source = source_snapshot()
        save(work / "source-manifest.json", source)
        before = baseline()
        save(work / "baseline-before.json", before)
        # Buildx supports JSON, not Driver as a template field. Never persist
        # its unfiltered Files/config/certificates: retain nonsecret identity only.
        raw_builders = command([*DOCKER, "buildx", "ls", "--format", '{{json .}}'], retain_stdout=False)
        builders = []
        for line in raw_builders.splitlines():
            value = json.loads(line)
            builders.append({k: value.get(k) for k in ("Name", "Driver", "Current")})
            builders[-1]["nodes"] = [{k: n.get(k) for k in ("Name", "Endpoint", "Status", "Version", "IDs")}
                                      for n in value.get("Nodes", [])]
        save(work / "builders.json", builders)
        if not any(v["Name"] == "desktop-linux" and v["Driver"] == "docker" for v in builders):
            raise ValueError("builder_identity")
        for name, expected in {**REPAIR_DOWNLOADS, "govulncheck-v1.8.0.mod": TOOL_MOD_SHA}.items():
            url = TOOL_MOD_URL if name.endswith(".mod") else APK_BASE + name
            data = fetch(url)
            if digest(data) != expected:
                raise ValueError("repair_artifact_digest")
            save(work / name, data)
            result["downloads"][name] = {"url": url, "sha256": expected, "bytes": len(data)}
        index = fetch(APK_BASE + "APKINDEX.tar.gz")
        save(work / "APKINDEX.tar.gz", index)
        result["downloads"]["APKINDEX.tar.gz"] = {"url": APK_BASE + "APKINDEX.tar.gz",
                                                       "sha256": digest(index), "bytes": len(index)}
        result["image"] = validate_image(json.loads(command([*DOCKER, "buildx", "imagetools", "inspect",
                                   IMAGE, "--format", "{{json .Manifest}}"])))
        command([*DOCKER, "pull", "--platform", "linux/arm64", REFERENCE], 600)
        result["image_config"] = json.loads(command([*DOCKER, "image", "inspect", "--format",
            '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},"layers":{{json .RootFS.Layers}}}', REFERENCE]))
        if result["image_config"]["os"] != "linux" or result["image_config"]["architecture"] != "arm64":
            raise ValueError("image_platform")
        command([*DOCKER, "image", "save", "--output", str(work / "original-image.tar"), REFERENCE], 300)
        tool_env = {"PATH": env["PATH"], "HOME": str(work), "TMPDIR": str(work),
                    "GOENV": "off", "GOTOOLCHAIN": "local", "GOTELEMETRY": "off",
                    "GOPATH": str(work / "go"), "GOCACHE": str(work / "gocache"),
                    "GOBIN": str(work / "tools"), "GOPROXY": "https://proxy.golang.org",
                    "GOSUMDB": "sum.golang.org", "SSL_CERT_FILE": certifi.where()}
        result["go_version"] = command(["go", "version"], custom_env=tool_env).decode().strip()
        command(["go", "install", "golang.org/x/vuln/cmd/govulncheck@v1.8.0"], 600, tool_env)
        result["govulncheck_sha256"] = digest((work / "tools/govulncheck").read_bytes())
        command(["go", "version", "-m", str(work / "tools/govulncheck")], custom_env=tool_env)
        result["status"] = "ARTIFACTS_COLLECTED_NOT_SIGNATURE_OR_BUILD_PASS"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if isinstance(exc, urllib.error.HTTPError):
            result["http_status"] = exc.code
    finally:
        if source is not None:
            result["source_unchanged"] = source == source_snapshot()
            if not result["source_unchanged"]:
                result["status"] = "BLOCKED_SOURCE_DRIFT"
        if before is not None:
            after = baseline()
            save(work / "baseline-after.json", after)
            result["network_baseline_unchanged"] = before["networks"] == after["networks"]
            result["added_image_inventory"] = sorted(set(after["images"]) - set(before["images"]))
            result["removed_image_inventory"] = sorted(set(before["images"]) - set(after["images"]))
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["artifacts"] = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                               for p in work.iterdir() if p.is_file() and p.stat().st_size < 1024**3}
        save(work / "inspect-result.json", result)
        print(json.dumps({"status": result["status"], "evidence": str(work / "inspect-result.json"),
                          "error_type": result.get("error_type")}, indent=2))
    return 0 if result["status"] == "ARTIFACTS_COLLECTED_NOT_SIGNATURE_OR_BUILD_PASS" else 1


def validate_context(path, recipe_sha):
    expected = {"Dockerfile": recipe_sha, "APKINDEX.tar.gz": SIGNED_INDEX_SHA,
                **{n + "-3.5.8-r0.apk": REPAIR_DOWNLOADS[n + "-3.5.8-r0.apk"] for n in REPAIR_TARGETS}}
    if path.is_symlink() or not path.is_dir() or set(p.name for p in path.iterdir()) != set(expected):
        raise ValueError("repair_context_inventory")
    for name, sha in expected.items():
        p = path / name
        if p.is_symlink() or not p.is_file() or digest(p.read_bytes()) != sha:
            raise ValueError("repair_context_digest")
    return expected


def signed_repair_inputs(work, fs):
    """Only two APK payloads; retain the signed full index without trusting all candidates."""
    key = fs["etc/apk/keys/alpine-devel@lists.alpinelinux.org-616ae350.rsa.pub"]["data"]
    data = (work / "APKINDEX.tar.gz").read_bytes()
    if digest(data) != SIGNED_INDEX_SHA:
        raise ValueError("signed_index_digest")
    index = verify_apk(data, key)["APKINDEX"]["data"].decode()
    files, bindings = {}, {}
    for name in REPAIR_TARGETS:
        filename = name + "-3.5.8-r0.apk"
        data = (work / filename).read_bytes()
        if digest(data) != REPAIR_DOWNLOADS[filename]:
            raise ValueError("repair_artifact_digest")
        meta, payload = verify_apk(data, key, name)
        checksum = apk_index_checksum(data, filename)
        rows = [r + "\n" for r in index.strip().split("\n\n") if f"P:{name}\n" in r + "\n"]
        if len(rows) != 1 or any(v not in rows[0] for v in (
            f"C:{checksum}\n", f"S:{len(data)}\n", "V:3.5.8-r0\n", "A:aarch64\n")):
            raise ValueError("apk_index_checksum_binding")
        bindings[name] = {"sha256": digest(data), "index_checksum": checksum, "metadata": meta}
        for filename, row in payload.items():
            if filename in files and row != files[filename]:
                raise ValueError("repair_payload_overlap")
            files[filename] = row
    return files, bindings


def validate_simulation(text):
    lines = text.strip().splitlines()
    actions = ["(1/2) Upgrading libcrypto3 (3.5.7-r0 -> 3.5.8-r0)",
               "(2/2) Upgrading libssl3 (3.5.7-r0 -> 3.5.8-r0)"]
    if len(lines) != 3 or lines[:2] != actions or not re.fullmatch(r"OK: .+ in 18 packages", lines[2]):
        raise ValueError("solver_unapproved_changes")
    return actions


def record_metadata(row):
    return {k: v for k, v in row.items() if k != "data"} if row else None


def validate_build_metadata(metadata, iid):
    manifest = metadata.get("containerimage.digest", "")
    descriptor = metadata.get("containerimage.descriptor", {})
    config_digest = metadata.get("containerimage.config.digest")
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest)
        or descriptor.get("digest") != manifest
        or descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        or descriptor.get("platform") != {"architecture": "arm64", "os": "linux"}
        or (config_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest))
        or iid not in {manifest, config_digest}):
        raise ValueError("built_image_identity")
    # Config digest is optional in this Buildx exporter. The saved OCI manifest
    # independently binds and verifies the config blob via image_rootfs.
    return manifest


def emitted_build_text(log, name):
    clean = "\n".join(re.sub(r"^#\d+ [0-9.]+ ", "", v) for v in log.splitlines())
    matches = re.findall(r"^CHG301_" + name + r"_BEGIN\n(.*?)^CHG301_" + name + r"_END$", clean, re.S | re.M)
    if len(matches) != 1:
        raise ValueError("build_emitted_evidence_missing")
    return matches[0].strip()


def package_blocks(data):
    blocks = {}
    for block in data.decode().strip().split("\n\n"):
        names = [v[2:] for v in block.splitlines() if v.startswith("P:")]
        if len(names) != 1 or names[0] in blocks:
            raise ValueError("package_database_identity")
        blocks[names[0]] = block
    return blocks


def validate_final_image(original_config, original, final_config, final, payload):
    if final_config["config"] != original_config["config"]:
        raise ValueError("runtime_config_changed")
    before = installed_packages(original["lib/apk/db/installed"]["data"])
    validate_repair_scope(before)
    after = installed_packages(final["lib/apk/db/installed"]["data"])
    if set(after) != set(before) or "usr/bin/openssl" in final:
        raise ValueError("installed_package_set_changed")
    old_blocks = package_blocks(original["lib/apk/db/installed"]["data"])
    new_blocks = package_blocks(final["lib/apk/db/installed"]["data"])
    for name, row in after.items():
        if row["A"] != "aarch64" or row["V"] != ("3.5.8-r0" if name in REPAIR_TARGETS else before[name]["V"]):
            raise ValueError("installed_package_version_changed")
        if name not in REPAIR_TARGETS and old_blocks[name] != new_blocks[name]:
            raise ValueError("unrelated_package_metadata_changed")
    for name in ("etc/apk/world", "entrypoint.sh", "usr/local/bin/traefik"):
        if record_metadata(final.get(name)) != record_metadata(original.get(name)):
            raise ValueError("protected_file_changed")
    # Every package payload entry must match its verified signed APK, not a
    # generated expected image. Existing CA files/directories stay identical.
    for name, row in payload.items():
        actual = record_metadata(final.get(name))
        if row["type"] == "5" and name in original and actual == record_metadata(original[name]):
            continue  # Shared directory ACL may remain owned by another package.
        if actual != record_metadata(row):
            raise ValueError("signed_payload_file_mismatch")
    diff = {}
    for name in sorted(set(original) | set(final)):
        old, new = original.get(name), final.get(name)
        if record_metadata(old) == record_metadata(new):
            continue
        if name in payload:
            category = "signed_library_payload"
        elif name == "lib/apk/db/installed":
            if any(old[k] != new[k] for k in ("type", "mode", "uid", "gid", "link")):
                raise ValueError("package_database_permissions_changed")
            category = "two_package_install_metadata"
        elif name == "lib/apk/db/scripts.tar.gz" and old and new:
            if (any(old[k] != new[k] for k in ("type", "mode", "uid", "gid", "link"))
                or tar_records(gzip_segments(old["data"])[0][1]) != tar_records(gzip_segments(new["data"])[0][1])):
                raise ValueError("package_scripts_changed")
            category = "identical_scripts_recompressed"
        else:
            raise ValueError("unapproved_rootfs_difference")
        diff[name] = {"category": category, "before": record_metadata(old), "after": record_metadata(new)}
    return {"installed_packages": after, "diff": diff, "package_count": len(after),
            "runtime_config_unchanged": True, "world_unchanged": True,
            "controller_binary_unchanged": True, "ca_trust_unchanged": True}


def repair():
    """Bounded approved two-library build; never run Traefik or contact Kubernetes."""
    repair_approval((ROOT / "DEVELOPMENT_PLAN.md").read_text())
    # The old fixed artifacts remain under their historical approval/digests.
    artifacts = repair_work()
    if datetime.now(UTC) >= datetime.fromisoformat(BATCH_DEADLINE):
        raise ValueError("original_batch_deadline_exceeded")
    attempts = list(Path("/private/tmp").glob("chg301-r2-two-lib-*/owned.json"))
    if len(attempts) >= 3:
        raise ValueError("bounded_build_attempts_exhausted")
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-two-lib-", dir="/private/tmp"))
    work.chmod(0o700)
    context = work / "context"
    tag = "nomosmart-test/traefik:3.7.13-chg301-r2-" + work.name.removeprefix("chg301-r2-two-lib-")
    result = {"scope": "CHG-301 R2 signed-index two-library build and rescan only",
              "approval_sha256": REPAIR_APPROVAL, "batch_started_at": BATCH_STARTED,
              "batch_deadline": BATCH_DEADLINE, "attempt": len(attempts) + 1,
              "started_at": datetime.now(UTC).isoformat(), "commands": [], "status": "BLOCKED_ERROR",
              "controller_executions": 0, "kubernetes_operations": 0, "provider_calls": 0,
              "tag": tag, "source_artifacts": str(artifacts), "vex_applied": []}
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["DOCKER_CLI_HINTS"] = "false"
    source, before = None, None
    context_lock = None

    def command(args, timeout=60, retain=True):
        remaining = (datetime.fromisoformat(BATCH_DEADLINE) - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ValueError("original_batch_deadline_exceeded")
        proc = subprocess.Popen(args, env=env, cwd=work, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=min(timeout, remaining))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = proc.communicate()
        ordinal = len(result["commands"])
        if retain:
            save(work / f"repair-{ordinal:02d}.stdout", stdout)
        save(work / f"repair-{ordinal:02d}.stderr", stderr)
        result["commands"].append({"argv": list(args), "exit_code": proc.returncode,
                                   "pid": proc.pid, "timeout": timed_out})
        if timed_out or proc.returncode:
            raise RuntimeError("bounded_tool_failure")
        return stdout

    def baseline():
        ids = sorted(command([*DOCKER, "ps", "-aq", "--no-trunc"]).decode().split())
        return {"containers": [json.loads(command([*DOCKER, "inspect", "--format",
            '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', v])) for v in ids],
            "networks": sorted(command([*DOCKER, "network", "ls", "--no-trunc", "--format", '{{.ID}} {{.Name}}']).decode().splitlines()),
            "images": sorted(command([*DOCKER, "image", "ls", "--no-trunc", "--format", '{{.Repository}}:{{.Tag}} {{.ID}}']).decode().splitlines())}
    try:
        git = command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split()
        if git != GIT_BASE:
            raise ValueError("source_baseline_drift")
        source = source_snapshot()
        result["git"] = git
        save(work / "source-manifest.json", source)
        before = baseline()
        save(work / "baseline-before.json", before)
        if any(line.startswith(tag + " ") for line in before["images"]):
            raise ValueError("test_tag_already_exists")
        preflight_path = Path(os.environ.get("CHG301_R2_PREFLIGHT_EVIDENCE", "")).resolve(strict=True)
        if preflight_path.parent.parent != Path("/private/tmp") or not preflight_path.parent.name.startswith("chg301-r2-preflight-"):
            raise ValueError("preflight_path_identity")
        preflight = json.loads(preflight_path.read_bytes())
        capacity = preflight["capacity"]
        if (preflight.get("status") != "MEASURED_NOT_CLUSTER_APPROVAL" or not preflight.get("probe_removed")
            or not preflight.get("baseline_unchanged") or before["containers"] != preflight["baseline"]
            or (datetime.now(UTC) - datetime.fromisoformat(preflight["finished_at"])).total_seconds() > 300
            or capacity["remaining_test_cpu_ceiling"] < 1 or capacity["remaining_test_memory_ceiling_bytes"] < 2 * 1024**3
            or not capacity["disk_100gib_precondition"]):
            raise ValueError("capacity_or_baseline_guard")
        result["preflight"] = {"path": str(preflight_path), "sha256": digest(preflight_path.read_bytes()), "capacity": capacity}
        raw = command([*DOCKER, "buildx", "ls", "--format", '{{json .}}'], retain=False)
        builders = [json.loads(v) for v in raw.splitlines()]
        # Buildx 0.32 emits identical rows twice on this host. Collapse only
        # byte-equivalent structured rows, never conflicting identities/config.
        chosen = list({json.dumps(b, sort_keys=True): b for b in builders
                       if b.get("Name") == "desktop-linux"}.values())
        if len(chosen) != 1 or chosen[0].get("Driver") != "docker":
            raise ValueError("builder_identity")
        nodes = chosen[0].get("Nodes", [])
        if len(nodes) != 1 or any(nodes[0].get(k) != v for k, v in {
            "Endpoint": "desktop-linux", "Status": "running", "Version": "v0.32.2",
            "IDs": ["tvkkrw7huygx9h4q03ebtohad"]}.items()):
            raise ValueError("builder_worker_identity")
        result["builder"] = {"name": "desktop-linux", "driver": "docker",
            "nodes": [{k: n.get(k) for k in ("Name", "Endpoint", "Status", "Version", "IDs")} for n in chosen[0].get("Nodes", [])]}
        original_config, original_fs = image_rootfs(artifacts / "original-image.tar", ARM64_DIGEST)
        validate_repair_scope(installed_packages(original_fs["lib/apk/db/installed"]["data"]))
        payload, bindings = signed_repair_inputs(artifacts, original_fs)
        result["input_bindings"] = bindings
        # The fixed source archive binds the reviewed busybox/CA triggers and
        # their tool binaries. These libraries have no new package scripts.
        hooks = [n for n in original_fs if n.startswith(("etc/apk/commit_hooks.d/", "lib/apk/commit_hooks.d/"))]
        if hooks:
            raise ValueError("unreviewed_commit_hook")
        result["reviewed_script_artifacts"] = {n: original_fs[n]["sha256"] for n in (
            "lib/apk/db/scripts.tar.gz", "lib/apk/db/triggers", "usr/sbin/update-ca-certificates",
            "usr/bin/c_rehash", "etc/ca-certificates/update.d/certhash")}
        context.mkdir(mode=0o700)
        save(context / "Dockerfile", RECIPE.read_bytes())
        for name in ["APKINDEX.tar.gz", *(n + "-3.5.8-r0.apk" for n in REPAIR_TARGETS)]:
            save(context / name, (artifacts / name).read_bytes())
        context_lock = validate_context(context, digest(RECIPE.read_bytes()))
        save(work / "context-lock.json", context_lock)
        save(work / "owned.json", {"run": work.name, "tag": tag, "context": str(context),
                                   "context_lock": context_lock, "original_batch": BATCH_STARTED})
        result["build_started"] = True
        args = [*DOCKER, "buildx", "build", "--builder", "desktop-linux", "--platform", "linux/arm64",
                "--network", "none", "--resource", "memory=2g", "--resource", "cpu-quota=100000",
                "--resource", "cpu-period=100000", "--no-cache", "--provenance=false", "--load",
                "--progress", "plain", "--tag", tag, "--iidfile", str(work / "image-id.txt"),
                "--metadata-file", str(work / "build-metadata.json"), str(context)]
        command(args, 1800)
        build_iid = (work / "image-id.txt").read_text().strip()
        build_metadata = json.loads((work / "build-metadata.json").read_bytes())
        manifest_digest = validate_build_metadata(build_metadata, build_iid)
        config_digest = build_metadata.get("containerimage.config.digest", "")
        image_id = json.loads(command([*DOCKER, "image", "inspect", "--format", '{{json .Id}}', tag]))
        if image_id not in {manifest_digest, config_digest}:
            raise ValueError("built_tag_drift")
        result.update(image_id=image_id, build_iid=build_iid, manifest_digest=manifest_digest, config_digest=config_digest)
        build_log = (work / f"repair-{len(result['commands']) - 2:02d}.stderr").read_text()
        # BuildKit prefixes each line with a vertex/time; extract the emitted
        # simulation between unambiguous markers, never infer success from exit0.
        if "CHG301_SANDBOX network=none cpu=1 memory=2147483648" not in build_log:
            raise ValueError("build_sandbox_or_solver_evidence_missing")
        simulation = emitted_build_text(build_log, "SIMULATION")
        result["solver_changes"] = validate_simulation(simulation)
        save(work / "simulation.txt", simulation.encode())
        command([*DOCKER, "image", "save", "--output", str(work / "repaired-image.tar"), tag], 300)
        final_config, final_fs = image_rootfs(work / "repaired-image.tar", manifest_digest)
        result["comparison"] = validate_final_image(original_config, original_fs, final_config, final_fs, payload)
        result["lower_layers_retained"] = final_config["rootfs"]["diff_ids"][:len(original_config["rootfs"]["diff_ids"])] == original_config["rootfs"]["diff_ids"]
        if not result["lower_layers_retained"]:
            raise ValueError("base_layers_changed")
        save(work / "final-config.json", final_config)
        save(work / "final-rootfs.json", {n: record_metadata(r) for n, r in final_fs.items()})
        command([*DOCKER, "scout", "version"])
        for mode, fmt, filename in [("cves", "sarif", "all-severity.sarif.json"), ("sbom", "spdx", "sbom.spdx.json")]:
            command([*DOCKER, "scout", mode, "--platform", "linux/arm64", "--format", fmt,
                     "--output", str(work / filename), "local://" + image_id], 1200)
        result["scan"] = assess_sarif(json.loads((work / "all-severity.sarif.json").read_bytes()))
        sbom = json.loads((work / "sbom.spdx.json").read_bytes())
        purls = [r.get("referenceLocator", "") for p in sbom.get("packages", []) for r in p.get("externalRefs", [])]
        if not any(v.startswith("pkg:oci/") and image_id in v for v in purls):
            raise ValueError("repaired_sbom_image_binding")
        result["sbom_image_purls"] = [v for v in purls if v.startswith("pkg:oci/")]
        result["openpgp"] = "INDETERMINATE"
        result["status"] = "LIBRARIES_REPAIRED_SECURITY_BLOCKED"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]{1,70}", str(exc)):
            result["error_code"] = str(exc)
    finally:
        if context_lock is not None:
            validate_context(context, context_lock["Dockerfile"])
            save(work / "cleanup-owned.json", {"removed_context": str(context), "lock": context_lock,
                                              "retained_test_tag": tag, "prune": False})
            for name in context_lock:
                (context / name).unlink()
            context.rmdir()
            result["context_removed"] = True
        if before is not None:
            after = baseline()
            save(work / "baseline-after.json", after)
            result["container_baseline_unchanged"] = before["containers"] == after["containers"]
            result["network_baseline_unchanged"] = before["networks"] == after["networks"]
            result["added_image_inventory"] = sorted(set(after["images"]) - set(before["images"]))
            result["removed_image_inventory"] = sorted(set(before["images"]) - set(after["images"]))
        if source is not None:
            result["source_unchanged"] = source == source_snapshot()
        result["finished_at"] = datetime.now(UTC).isoformat()
        if before is not None and (not result.get("container_baseline_unchanged")
            or not result.get("network_baseline_unchanged") or result.get("removed_image_inventory")):
            result["status"] = "BLOCKED_EXTERNAL_BASELINE_DRIFT"
        if source is not None and not result.get("source_unchanged"):
            result["status"] = "BLOCKED_SOURCE_DRIFT"
        if any(not row.startswith(tag + " ") for row in result.get("added_image_inventory", [])):
            result["status"] = "BLOCKED_EXTERNAL_IMAGE_DRIFT"
        result["artifacts"] = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                               for p in work.iterdir() if p.is_file()}
        save(work / "result.json", result)
        print(json.dumps({k: result.get(k) for k in ("status", "error_type", "error_code", "tag", "image_id",
                        "container_baseline_unchanged", "network_baseline_unchanged", "context_removed")}
                         | {"evidence": str(work / "result.json")}, indent=2))
    return 0 if result["status"] == "LIBRARIES_REPAIRED_SECURITY_BLOCKED" else 1


def verify_built():
    """Resume static verification of the exact owned successful build, no rebuild."""
    repair_approval((ROOT / "DEVELOPMENT_PLAN.md").read_text())
    original_work = repair_work()
    given = Path(os.environ.get("CHG301_R2_TWO_LIBRARY_EVIDENCE", ""))
    work = given.resolve(strict=True)
    if (work != given or work.parent != Path("/private/tmp") or not work.name.startswith("chg301-r2-two-lib-")
        or work.is_symlink() or work.stat().st_mode & 0o077 or work.stat().st_uid != os.getuid()):
        raise ValueError("owned_build_path_identity")
    prior = json.loads((work / "result.json").read_bytes())
    owned = json.loads((work / "owned.json").read_bytes())
    if (prior.get("approval_sha256") != REPAIR_APPROVAL or not prior.get("context_removed")
        or not prior.get("container_baseline_unchanged") or not prior.get("network_baseline_unchanged")
        or not prior.get("source_unchanged") or owned.get("run") != work.name or owned.get("tag") != prior.get("tag")
        or prior.get("error_code") != "built_image_identity"):
        raise ValueError("owned_build_resume_state")
    for name, row in prior["artifacts"].items():
        path = work / name
        if path.is_symlink() or digest(path.read_bytes()) != row["sha256"]:
            raise ValueError("owned_build_evidence_drift")
    builds = [(i, c) for i, c in enumerate(prior["commands"]) if "buildx" in c["argv"] and "build" in c["argv"]]
    if len(builds) != 1 or builds[0][1]["exit_code"] != 0 or builds[0][1].get("timeout"):
        raise ValueError("successful_build_required")
    old_source = json.loads((work / "source-manifest.json").read_bytes())
    source = source_snapshot()
    allowed = {"backend/scripts/chg301_r2_ingress.py", "backend/tests/test_chg301_r2_ingress.py"}
    if set(source) != set(old_source) or any(source[n] != old_source[n] for n in source if n not in allowed):
        raise ValueError("built_product_or_recipe_source_drift")
    result = {"status": "BLOCKED_VERIFICATION", "started_at": datetime.now(UTC).isoformat(),
              "approval_sha256": REPAIR_APPROVAL, "batch_deadline": BATCH_DEADLINE,
              "prior_result_sha256": digest((work / "result.json").read_bytes()),
              "tag": prior["tag"], "commands": [], "image_builds": 0,
              "controller_executions": 0, "kubernetes_operations": 0, "provider_calls": 0,
              "vex_applied": [], "context_removed": True}
    save(work / "verify-source-manifest.json", source)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["DOCKER_CLI_HINTS"] = "false"

    def command(args, timeout=60):
        remaining = (datetime.fromisoformat(BATCH_DEADLINE) - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ValueError("original_batch_deadline_exceeded")
        proc = subprocess.run([*DOCKER, *args], env=env, cwd=work, capture_output=True, timeout=min(timeout, remaining))
        ordinal = len(result["commands"])
        save(work / f"verify-{ordinal:02d}.stdout", proc.stdout)
        save(work / f"verify-{ordinal:02d}.stderr", proc.stderr)
        result["commands"].append({"argv": [*DOCKER, *args], "exit_code": proc.returncode})
        if proc.returncode:
            raise RuntimeError("verification_tool_failed")
        return proc.stdout

    def baseline():
        ids = sorted(command(["ps", "-aq", "--no-trunc"]).decode().split())
        return {"containers": [json.loads(command(["inspect", "--format",
            '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', v])) for v in ids],
                "networks": sorted(command(["network", "ls", "--no-trunc", "--format", '{{.ID}} {{.Name}}']).decode().splitlines()),
                "images": sorted(command(["image", "ls", "--no-trunc", "--format", '{{.Repository}}:{{.Tag}} {{.ID}}']).decode().splitlines())}
    before = None
    try:
        before = baseline()
        if before != json.loads((work / "baseline-after.json").read_bytes()):
            raise ValueError("post_build_baseline_drift")
        manifest = validate_build_metadata(json.loads((work / "build-metadata.json").read_bytes()),
                                           (work / "image-id.txt").read_text().strip())
        actual = json.loads(command(["image", "inspect", "--format", '{{json .Id}}', prior["tag"]]))
        if actual != manifest:
            raise ValueError("built_tag_drift")
        result.update(image_id=actual, manifest_digest=manifest)
        build_log = (work / f"repair-{builds[0][0]:02d}.stderr").read_text()
        simulation = emitted_build_text(build_log, "SIMULATION")
        result["solver_changes"] = validate_simulation(simulation)
        save(work / "simulation.txt", simulation.encode())
        network = emitted_build_text(build_log, "NETWORK")
        save(work / "build-network.txt", network.encode())
        if ("CHG301_SANDBOX network=none cpu=1 memory=2147483648" not in build_log
            or "CHG301_APPLIED_WITH_UNCHANGED_WORLD" not in build_log):
            raise ValueError("build_sandbox_evidence_missing")
        command(["image", "save", "--output", str(work / "repaired-image.tar"), prior["tag"]], 300)
        original_config, original = image_rootfs(original_work / "original-image.tar", ARM64_DIGEST)
        config, final = image_rootfs(work / "repaired-image.tar", manifest)
        payload, bindings = signed_repair_inputs(original_work, original)
        result["input_bindings"] = bindings
        result["comparison"] = validate_final_image(original_config, original, config, final, payload)
        result["lower_layers_retained"] = config["rootfs"]["diff_ids"][:len(original_config["rootfs"]["diff_ids"])] == original_config["rootfs"]["diff_ids"]
        if not result["lower_layers_retained"]:
            raise ValueError("base_layers_changed")
        save(work / "final-config.json", config)
        save(work / "final-rootfs.json", {n: record_metadata(r) for n, r in final.items()})
        command(["scout", "version"])
        for mode, fmt, filename in [("cves", "sarif", "all-severity.sarif.json"), ("sbom", "spdx", "sbom.spdx.json")]:
            command(["scout", mode, "--platform", "linux/arm64", "--format", fmt,
                     "--output", str(work / filename), "local://" + actual], 1200)
        result["scan"] = assess_sarif(json.loads((work / "all-severity.sarif.json").read_bytes()))
        sbom = json.loads((work / "sbom.spdx.json").read_bytes())
        purls = [r.get("referenceLocator", "") for p in sbom.get("packages", []) for r in p.get("externalRefs", [])]
        if not any(v.startswith("pkg:oci/") and actual in v for v in purls):
            raise ValueError("repaired_sbom_image_binding")
        result["sbom_image_purls"] = [v for v in purls if v.startswith("pkg:oci/")]
        result["openpgp"] = "INDETERMINATE"
        result["status"] = "LIBRARIES_REPAIRED_SECURITY_BLOCKED"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]{1,70}", str(exc)):
            result["error_code"] = str(exc)
    finally:
        if before is not None:
            after = baseline()
            save(work / "verify-baseline-after.json", after)
            result["container_baseline_unchanged"] = before["containers"] == after["containers"]
            result["network_baseline_unchanged"] = before["networks"] == after["networks"]
            result["image_baseline_unchanged"] = before["images"] == after["images"]
        result["source_unchanged"] = source == source_snapshot()
        if not all(result.get(k) for k in ("source_unchanged", "container_baseline_unchanged",
                                          "network_baseline_unchanged", "image_baseline_unchanged")):
            result["status"] = "BLOCKED_VERIFICATION_DRIFT"
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["artifacts"] = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                               for p in work.iterdir() if p.is_file()}
        save(work / "verification-result.json", result)
        print(json.dumps({k: result.get(k) for k in ("status", "error_type", "error_code", "tag", "image_id")}
                         | {"evidence": str(work / "verification-result.json")}, indent=2))
    return 0 if result["status"] == "LIBRARIES_REPAIRED_SECURITY_BLOCKED" else 1


def applicability_guard(approval_bytes, plan, sarif_bytes, now):
    """Exact reviewed bytes; never generalize exclusions or alter raw findings."""
    if digest(approval_bytes) != ACCEPTANCE_SHA:
        raise ValueError("applicability_approval_digest")
    approval = json.loads(approval_bytes)
    sections = plan.split("\n## ")
    if (len(sections) < 2 or sections[1].split("\n", 1)[0] != SMOKE_SECTION
        or "Plan Approval: APPROVED original R2 scope plus Peter" not in sections[1]
        or "PENDING" in sections[1]):
        raise ValueError("applicability_active_plan")
    if now >= datetime.fromisoformat(approval["expiresAt"]) or now < datetime.fromisoformat(approval["recordedAt"]):
        raise ValueError("applicability_time_window")
    if digest(sarif_bytes) != approval["rawSarifSha256"]:
        raise ValueError("applicability_raw_report_digest")
    raw = assess_sarif(json.loads(sarif_bytes))
    accepted = {v["id"]: v["rawSeverity"] for v in approval["findings"]}
    if (accepted != {v["id"]: v["severity"] for v in raw["findings"]}
        or raw["unique_advisories"] != 2
        or approval["pluginsAllowed"] is not False
        or approval["imageId"] != ACCEPTED_IMAGE):
        raise ValueError("applicability_scope")
    return {"status": "PASS_WITH_ACCEPTED_NOT_AFFECTED", "approval_sha256": ACCEPTANCE_SHA,
            "raw": raw, "accepted": approval["findings"], "plugins_allowed": False}


def validate_smoke_container(row, label, action):
    host, config = row["HostConfig"], row["Config"]
    if (row["Image"] != ACCEPTED_IMAGE or config["User"] != "10001:10001"
        or config["Entrypoint"] != ["/usr/local/bin/traefik"] or config["Cmd"] != [action]
        or config["Labels"].get("nomosmart.chg301-r2.run") != label
        or row.get("Mounts") or host["NetworkMode"] != "none" or not host["ReadonlyRootfs"]
        or host["Privileged"] or host.get("CapAdd") or host["CapDrop"] != ["ALL"]
        or host["SecurityOpt"] != ["no-new-privileges"]
        or host["Memory"] != 128 * 1024**2 or host["MemorySwap"] != 128 * 1024**2
        or host["NanoCpus"] != 500000000 or host["PidsLimit"] != 64
        or host.get("PortBindings") or host.get("Binds") or host.get("Devices")
        or host["RestartPolicy"]["Name"] != "no"):
        raise ValueError("smoke_container_isolation")


def smoke():
    approval = json.loads(ACCEPTANCE_PATH.read_bytes())
    assessment = applicability_guard(ACCEPTANCE_PATH.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text(),
                                    (ACCEPTED_BUILD / "all-severity.sarif.json").read_bytes(), datetime.now(UTC))
    for key in ("assessmentDocument", "assessmentEvidence"):
        if digest((ROOT / approval[key]).read_bytes()) != approval[key + "Sha256"]:
            raise ValueError("accepted_evidence_drift")
    evidence = json.loads((ROOT / approval["assessmentEvidence"]).read_bytes())
    for name, sha in {"verification-result.json": evidence["priorImageVerificationSha256"],
                      "sbom.spdx.json": approval["rawSpdxSha256"]}.items():
        if digest((ACCEPTED_BUILD / name).read_bytes()) != sha:
            raise ValueError("accepted_build_evidence_drift")
    source = source_snapshot()
    prior_source = json.loads((ACCEPTED_BUILD / "verify-source-manifest.json").read_bytes())
    allowed = {"backend/scripts/chg301_r2_ingress.py", "backend/tests/test_chg301_r2_ingress.py"}
    for name, sha in POST_BUILD_DOCS.items():
        if source.get(name) != sha:
            raise ValueError("accepted_governance_source_drift")
        prior_source[name] = sha
    if set(source) != set(prior_source) or any(source[k] != prior_source[k] for k in source if k not in allowed):
        raise ValueError("accepted_product_source_drift")
    _, rootfs = image_rootfs(ACCEPTED_BUILD / "repaired-image.tar", ACCEPTED_IMAGE)
    if digest(rootfs["usr/local/bin/traefik"]["data"]) != approval["binarySha256"]:
        raise ValueError("accepted_binary_drift")
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-smoke-", dir="/private/tmp"))
    result = {"status": "BLOCKED_SMOKE", "started_at": datetime.now(UTC).isoformat(),
              "assessment": assessment, "image_id": ACCEPTED_IMAGE, "commands": [],
              "containers": [], "kubernetes_operations": 0, "provider_calls": 0,
              "pr_operations": 0, "batch_deadline": BATCH_DEADLINE}
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}

    def command(args, cleanup=False):
        remaining = (datetime.fromisoformat(BATCH_DEADLINE) - datetime.now(UTC)).total_seconds()
        if remaining <= 0 and not cleanup:
            raise ValueError("original_batch_deadline_exceeded")
        proc = subprocess.run([*DOCKER, *args], env=env, cwd=work, capture_output=True,
                              timeout=30 if cleanup else min(30, remaining))
        ordinal = len(result["commands"])
        save(work / f"{ordinal:03d}.stdout", proc.stdout)
        save(work / f"{ordinal:03d}.stderr", proc.stderr)
        result["commands"].append({"argv": [*DOCKER, *args], "exit_code": proc.returncode})
        if proc.returncode:
            raise RuntimeError("smoke_command_failed")
        return proc.stdout

    def baseline(cleanup=False):
        ids = sorted(command(["ps", "-aq", "--no-trunc"], cleanup).decode().split())
        return {"containers": [json.loads(command(["inspect", "--format",
                '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', v], cleanup)) for v in ids],
                "networks": sorted(command(["network", "ls", "--no-trunc", "--format", '{{.ID}} {{.Name}}'], cleanup).decode().splitlines()),
                "images": sorted(command(["image", "ls", "--no-trunc", "--format", '{{.Repository}}:{{.Tag}} {{.ID}}'], cleanup).decode().splitlines())}

    before, owned = None, []
    try:
        actual = json.loads(command(["image", "inspect", "--format",
            '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}', ACCEPTED_TAG]))
        if actual != {"id": ACCEPTED_IMAGE, "os": "linux", "architecture": "arm64"}:
            raise ValueError("accepted_image_drift")
        before = baseline()
        save(work / "baseline-before.json", before)
        if before != json.loads((ACCEPTED_BUILD / "verify-baseline-after.json").read_bytes()):
            raise ValueError("accepted_baseline_drift")
        for ordinal, action in enumerate(("version", "--help")):
            name = f"{work.name}-{ordinal}"
            cid = command(["create", "--pull=never", "--platform", "linux/arm64", "--name", name,
                "--label", f"nomosmart.chg301-r2.run={work.name}", "--user", "10001:10001",
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.5", "--pids-limit", "64",
                "--entrypoint", "/usr/local/bin/traefik", ACCEPTED_IMAGE, action]).decode().strip()
            if not re.fullmatch(r"[0-9a-f]{64}", cid) or cid in {v["id"] for v in before["containers"]}:
                raise ValueError("smoke_owned_id")
            owned.append(cid)
            row = json.loads(command(["inspect", cid]))[0]
            validate_smoke_container(row, work.name, action)
            save(work / f"container-{ordinal}.json", row)
            output = command(["start", "--attach", cid]).decode()
            state = json.loads(command(["inspect", "--format", '{{json .State}}', cid]))
            if state["ExitCode"] != 0 or state["Running"] or state["OOMKilled"]:
                raise ValueError("smoke_exit_state")
            if (action == "version" and ("3.7.13" not in output or "linux/arm64" not in output)) or not output.strip():
                raise ValueError("smoke_output")
            result["containers"].append({"id": cid, "action": action, "state": state, "output_sha256": digest(output.encode())})
        result["status"] = "PASS_NETWORK_NONE_CLI_SMOKE"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if isinstance(exc, ValueError):
            result["error_code"] = str(exc)
    finally:
        try:
            for cid in owned:
                row = json.loads(command(["inspect", cid], cleanup=True))[0]
                if row["Id"] != cid or row["Config"]["Labels"].get("nomosmart.chg301-r2.run") != work.name:
                    raise ValueError("cleanup_ownership")
                command(["rm", "-f", cid], cleanup=True)
            result["owned_containers_removed"] = True
            after = baseline(cleanup=True)
            save(work / "baseline-after.json", after)
            result["protected_baseline_unchanged"] = before is not None and before == after
            result["source_unchanged"] = source == source_snapshot()
            if not result["protected_baseline_unchanged"] or not result["source_unchanged"]:
                result["status"] = "BLOCKED_SMOKE_DRIFT"
        except Exception as exc:
            result.update(status="BLOCKED_SMOKE_CLEANUP", cleanup_error=type(exc).__name__)
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["artifacts"] = {p.name: digest(p.read_bytes()) for p in work.iterdir() if p.is_file()}
        save(work / "result.json", result)
        print(json.dumps({k: result.get(k) for k in ("status", "error_type", "error_code", "protected_baseline_unchanged", "owned_containers_removed")}
                         | {"evidence": str(work / "result.json")}, indent=2))
    return 0 if result["status"] == "PASS_NETWORK_NONE_CLI_SMOKE" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["candidate", "inspect", "analyze", "assess", "cleanup", "repair", "verify-built", "smoke"])
    args = parser.parse_args()
    if os.environ.get("CHG301_R2_ISOLATED") != "1":
        raise SystemExit("explicit isolated opt-in required")
    if args.phase == "smoke":
        return smoke()
    if args.phase not in {"repair", "verify-built"}:
        raise SystemExit("historical phase retired; current approval only permits repair")
    return repair() if args.phase == "repair" else verify_built()


if __name__ == "__main__":
    raise SystemExit(main())

"""Approved CHG-300 two-image build/scan, no deployment or live-data commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from chg291_integrated_preparation import allowed, put, sha

REPO = Path(__file__).resolve().parents[2]
TAGS = {"migrations": "nomosmart/migrations:0.1.0-chg300", "backend": "nomosmart/backend:0.1.0-chg300"}
DOCKER = ["docker", "--context", "desktop-linux"]


def env():
    return {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}


def docker(*args):
    return subprocess.run([*DOCKER, *args], env=env(), capture_output=True, timeout=120)


def inventory():
    result = docker("image", "ls", "--no-trunc", "--format", "{{json .}}")
    assert result.returncode == 0, "Docker image inventory unavailable"
    return {r["Repository"] + ":" + r["Tag"]: r["ID"] for r in
            (json.loads(line) for line in result.stdout.decode().splitlines()) if r["Tag"] != "<none>"}


def snapshot():
    evidence = json.loads((REPO / "docs/CHG-300-VERIFICATION-EVIDENCE.json").read_text())
    for name, expected in evidence["sources"].items():
        assert sha(REPO / name) == expected, "Previous verified source drift: " + name
    names = {"backend/" + n for n in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock",
        "main.py", "migrate.py", "models.py", "connection.py")}
    names.update(str(p.relative_to(REPO)) for p in (REPO / "backend/app").rglob("*") if p.is_file())
    names.update(str(p.relative_to(REPO)) for p in (REPO / "sql/migrations").glob("*.sql"))
    names.update((".dockerignore", "deploy/migrations/Dockerfile", "deploy/docker/secret-env-entrypoint.sh"))
    root = Path(tempfile.mkdtemp(prefix="chg300-images-", dir="/private/tmp")); root.chmod(0o700)
    files = {}
    for name in sorted(names):
        if not allowed(name):
            continue
        source = REPO / name
        assert source.is_file() and not source.is_symlink() and source.resolve().is_relative_to(REPO)
        target = root / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(source); shutil.copy2(source, target)
        assert before == sha(source) == sha(target)
        files[name] = before
    assert files["sql/migrations/V049__exclusive_project_member_role.sql"] == evidence["sources"]["sql/migrations/V049__exclusive_project_member_role.sql"]
    manifest = {"scope": "CHG-300 Backend/Migration image preparation only", "root": str(root), "files": files,
                "sourceSha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
                "toolSha256": sha(Path(__file__)), "tags": TAGS}
    put(root / "manifest.json", manifest)
    (root / "images").mkdir(mode=0o700)
    print(json.dumps({"root": str(root), "sourceSha256": manifest["sourceSha256"], "files": len(files)}))


def guard(root):
    root = root.resolve(strict=True)
    assert re.fullmatch(r"/private/tmp/chg300-images-[a-z0-9_]+", str(root)) and root.stat().st_mode & 0o077 == 0
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["root"] == str(root) and manifest["tags"] == TAGS and manifest["toolSha256"] == sha(Path(__file__))
    for name, expected in manifest["files"].items():
        assert sha(root / "source" / name) == expected and sha(REPO / name) == expected, "Build input drift: " + name
    return manifest


def run_logged(root, label, command, timeout):
    log = root / "images" / (label + ".log")
    started = time.time()
    with log.open("x") as stream:
        log.chmod(0o600)
        try:
            result = subprocess.run(command, env=env(), stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    return {"command": command, "exitCode": code, "elapsedSeconds": round(time.time() - started, 2),
            "log": str(log), "logSha256": sha(log)}


def build(root):
    manifest = guard(root)
    baseline = inventory()
    for tag in TAGS.values():
        result = docker("image", "inspect", tag)
        assert result.returncode != 0 and b"No such image" in result.stderr, "Tag exists or Docker unavailable"
    put(root / "images/baseline.json", baseline)
    for name, tag in TAGS.items():
        guard(root)
        context = root / "source" if name == "migrations" else root / "source/backend"
        recipe = root / "source/deploy/migrations/Dockerfile" if name == "migrations" else context / "Dockerfile"
        iidfile = root / "images" / (name + ".iid")
        print(json.dumps({"phase": "build", "tag": tag}), flush=True)
        result = run_logged(root, name + "-build", [*DOCKER, "build", "--platform=linux/arm64",
            "--progress=plain", "--iidfile", str(iidfile), "-f", str(recipe), "-t", tag, str(context)], 1800)
        result.update(tag=tag, sourceSha256=manifest["sourceSha256"])
        if result["exitCode"] == 0:
            info = json.loads(docker("image", "inspect", tag).stdout)[0]
            assert info["Id"] == iidfile.read_text().strip() and info["Architecture"] == "arm64" and info["Os"] == "linux"
            result.update(imageId=info["Id"], user=info["Config"]["User"], architecture=info["Architecture"])
        put(root / "images" / (name + "-build.json"), result)
        print(json.dumps(result), flush=True)
        guard(root)
        after = inventory()
        assert all(after.get(tag) == value for tag, value in baseline.items()), "Preexisting image tags changed"
        if result["exitCode"]:
            raise SystemExit("Build failed; preserve log and stop")


def scan(root):
    guard(root)
    for name, tag in TAGS.items():
        build = json.loads((root / "images" / (name + "-build.json")).read_text())
        assert build["exitCode"] == 0
        ident = build["imageId"]
        assert json.loads(docker("image", "inspect", tag).stdout)[0]["Id"] == ident
        for label, args, extension in (
            ("sbom", ["sbom", "--format=spdx"], "json"),
            ("all-severity", ["cves", "--format=sarif"], "sarif"),
            ("high-critical", ["cves", "--exit-code", "--only-severity=critical,high", "--format=sarif"], "sarif"),
        ):
            guard(root)
            output = root / "images" / (name + "-" + label + "." + extension)
            assert not output.exists(), "Evidence already exists"
            print(json.dumps({"phase": "scan", "image": name, "kind": label, "imageId": ident}), flush=True)
            result = run_logged(root, name + "-" + label, [*DOCKER, "scout", *args, "--output", str(output), "local://" + ident], 600)
            result.update(imageId=ident, tag=tag, sourceSha256=build["sourceSha256"])
            if output.exists():
                result.update(artifact=str(output), artifactSha256=sha(output))
            put(root / "images" / (name + "-" + label + "-result.json"), result)
            print(json.dumps(result), flush=True)
            if result["exitCode"] not in (0, 2):
                raise SystemExit("Scanner unavailable/failed; do not treat as security PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "build", "scan"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.action == "snapshot":
        snapshot()
    else:
        assert args.root
        (build if args.action == "build" else scan)(args.root)

"""Source-bound, dependency/static-only CHG-301 R2 security verification.

Copies an explicit code/lock allowlist into a private directory. No application
imports, Docker/Kubernetes, operator settings, Provider, audit-fix or PR writes.
Scanner dependencies are resolved once with hashes and installed only in this
run's venv. A finding/error is evidence, never permission to upgrade a product.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ("backend/app", "deploy/installer/nomosmart_installer",
             "deploy/release/nomosmart_release", "deploy/package")
LOCKS = ("frontend/package.json", "frontend/package-lock.json",
         "backend/pyproject.toml", "backend/uv.lock")
SCANNERS = "pip-audit==2.10.1\nbandit==1.9.4\n"
RISK_PATH = "docs/CHG-301-R2-FTP-RISK-ACCEPTANCE.json"
RISK_SHA256 = "e0ef6fb654acc49093f5c3cbc50f3449f527fd3e135d66cda6a7f1e5a6b969e5"
FINDING_KEY = ("filename", "line_number", "test_id", "issue_severity", "issue_confidence")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(value, stream, indent=2, ensure_ascii=False)


def assess_static_risk(findings, source_hashes, approval_bytes):
    """Pure assessment of actual scanner records; never remove raw findings.

    Only the exact human-approved ledger is trusted, with matching source bytes
    and finding identity. Missing/tampered acceptance cannot authorize a waiver.
    """
    approved = set()
    approval_id = None
    if hashlib.sha256(approval_bytes).hexdigest() == RISK_SHA256:
        ledger = json.loads(approval_bytes)
        if all(source_hashes.get(path) == digest for path, digest in ledger["source_sha256"].items()):
            approved = {tuple(row[k] for k in FINDING_KEY) for row in ledger["findings"]}
            approval_id = ledger["id"]
    accepted, blocked = [], []
    for row in findings:
        if row.get("issue_severity") not in {"HIGH", "CRITICAL"}:
            continue
        if tuple(row.get(k) for k in FINDING_KEY) in approved:
            accepted.append(row)
        else:
            blocked.append(row)
    return {"status": "FAIL" if blocked else "ACCEPTED_RISK" if accepted else "PASS",
            "approval_id": approval_id, "accepted_findings": accepted,
            "unaccepted_high_critical": blocked}


def sources():
    files = set(LOCKS + (RISK_PATH,))
    for directory in CODE_DIRS:
        files.update(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob("*.py")
                     if not any(part in {"__pycache__", ".venv", "venv"} for part in p.parts))
    for name in files:
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or ROOT not in path.resolve().parents:
            raise RuntimeError("source allowlist identity failure")
    return sorted(files)


def main():
    if os.environ.get("CHG301_R2_ISOLATED") != "1" or len(sys.argv) != 1:
        raise SystemExit("explicit isolated R2 opt-in required; no command overrides")
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-security-", dir="/private/tmp"))
    snapshot = work / "source"
    snapshot.mkdir(mode=0o700)
    # npm rejects loading the same empty file as both user and global config.
    npm_global = work / "npm-global-empty.conf"
    npm_global.touch(mode=0o600)
    environment = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    environment.update(UV_NO_CONFIG="1", UV_CACHE_DIR=str(work / "uv-cache"),
        UV_PYTHON_DOWNLOADS="never", PIP_CONFIG_FILE=os.devnull, PYTHONNOUSERSITE="1",
        PYTHONPYCACHEPREFIX=str(work / "pycache"), npm_config_userconfig=os.devnull,
        npm_config_globalconfig=str(npm_global), npm_config_cache=str(work / "npm-cache"),
        npm_config_registry="https://registry.npmjs.org", npm_config_ignore_scripts="true",
        npm_config_update_notifier="false", CI="1")
    evidence = {"scope": "CHG-301 R2 dependency and static analysis only",
        "started_at": datetime.now(UTC).isoformat(), "status": "BLOCKED",
        "commands": [], "checks": {}, "provider_calls": 0,
        "kubernetes_operations": 0, "docker_operations": 0,
        "scanner_pins": SCANNERS.splitlines(), "tool_sha256": sha(Path(__file__))}

    def run(name, args, *, cwd=snapshot, allowed=(0,), timeout=1200):
        entry = {"name": name, "argv": [str(a) for a in args],
                 "started_at": datetime.now(UTC).isoformat()}
        evidence["commands"].append(entry)
        try:
            result = subprocess.run(args, cwd=cwd, env=environment, text=True,
                                    capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            entry.update(status="BLOCKED", reason="timeout")
            raise RuntimeError(name + " timeout") from None
        entry.update(exit_code=result.returncode, finished_at=datetime.now(UTC).isoformat())
        # Private diagnostics only: do not echo scanner code snippets or tokens.
        save(work / (name + "-command.json"), {"stdout": result.stdout, "stderr": result.stderr})
        if result.returncode not in allowed:
            entry["status"] = "BLOCKED"
            raise RuntimeError(name + " scanner/tool error")
        entry["status"] = "COMPLETED"
        return result

    before = {}
    try:
        before = {name: sha(ROOT / name) for name in sources()}
        evidence["source_sha256"] = before
        for name in before:
            dest = snapshot / name
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(ROOT / name, dest)
            dest.chmod(0o600)
        if before != {name: sha(snapshot / name) for name in before}:
            raise RuntimeError("snapshot mismatch")
        npm_lock = json.loads((snapshot / "frontend/package-lock.json").read_text())
        public_npm = [v for k, v in npm_lock["packages"].items() if k]
        for package in public_npm:
            url = urlsplit(package.get("resolved", ""))
            if (url.scheme != "https" or url.hostname != "registry.npmjs.org"
                    or url.username or url.password or package.get("link")):
                raise RuntimeError("non-public npm dependency: no transmission allowed")
        python_lock = tomllib.loads((snapshot / "backend/uv.lock").read_text())
        public_python = [p for p in python_lock["package"] if p["name"] != "nomosmart-backend"]
        if any(p["source"] != {"registry": "https://pypi.org/simple"} for p in public_python):
            raise RuntimeError("non-public Python dependency: no transmission allowed")
        evidence["transmission_scope"] = {"npm_registry": "https://registry.npmjs.org",
            "python_registry_and_advisories": "https://pypi.org", "python_distribution_files": "https://files.pythonhosted.org",
            "npm_public_lock_entries": len(public_npm), "python_public_packages": len(public_python),
            "private_packages": 0, "root_project_excluded": True,
            "payload": "public dependency names/versions only; no source, environment, credentials or private project metadata"}
        evidence["git_parents"] = run("git-parents", ["git", "rev-parse", "HEAD", "MERGE_HEAD"], cwd=ROOT).stdout.split()
        evidence["versions"] = {}
        for name, args in {"npm": ["npm", "--version"], "node": ["node", "--version"],
                           "uv": ["uv", "--version"], "python": [sys.executable, "--version"]}.items():
            evidence["versions"][name] = run(name + "-version", args).stdout.strip()

        for name, flags in (("npm-production", ["--omit=dev"]), ("npm-full", [])):
            result = run(name, ["npm", "audit", "--json", *flags], cwd=snapshot / "frontend", allowed=(0, 1))
            data = json.loads(result.stdout)
            if "error" in data or "vulnerabilities" not in data or "metadata" not in data:
                raise RuntimeError(name + " incomplete audit")
            counts = data["metadata"]["vulnerabilities"]
            evidence["checks"][name] = {"status": "FAIL" if counts.get("high", 0) + counts.get("critical", 0) else "PASS",
                "counts": counts, "dependencies": data["metadata"].get("dependencies"),
                "findings": data["vulnerabilities"]}
            save(work / (name + ".json"), data)
            print(json.dumps({"check": name, "counts": counts}), flush=True)

        reqin = work / "scanner-requirements.in"
        reqin.write_text(SCANNERS)
        lock = work / "scanner-requirements.txt"
        run("scanner-lock", ["uv", "pip", "compile", str(reqin), "--python", sys.executable,
            "--generate-hashes", "--no-build", "--default-index", "https://pypi.org/simple",
            "--output-file", str(lock)])
        evidence["scanner_lock_sha256"] = sha(lock)
        venv = work / "scanner-venv"
        run("scanner-venv", ["uv", "venv", "--python", sys.executable, str(venv)])
        python = venv / "bin/python"
        run("scanner-install", ["uv", "pip", "install", "--python", str(python),
            "--require-hashes", "--no-build", "--default-index", "https://pypi.org/simple", "-r", str(lock)])
        for tool in ("pip-audit", "bandit"):
            evidence["versions"][tool] = run(tool + "-version", [str(venv / "bin" / tool), "--version"]).stdout.strip()

        for name, flags in (("pip-production", ["--no-dev"]), ("pip-full", [])):
            requirements = work / (name + "-requirements.txt")
            run(name + "-export", ["uv", "export", "--quiet", "--project", str(snapshot / "backend"),
                "--frozen", "--no-emit-project", *flags, "--format", "requirements-txt", "--output-file", str(requirements)])
            output = work / (name + ".json")
            result = run(name, [str(venv / "bin/pip-audit"), "-r", str(requirements), "--disable-pip",
                "--require-hashes", "--vulnerability-service", "pypi", "--format", "json", "--output", str(output), "--progress-spinner", "off"], allowed=(0, 1))
            data = json.loads(output.read_text())
            deps = data.get("dependencies", [])
            if not deps or any("skip_reason" in item for item in deps):
                raise RuntimeError(name + " incomplete audit")
            findings = [{"name": d["name"], "version": d["version"], "vulns": d["vulns"]} for d in deps if d.get("vulns")]
            evidence["checks"][name] = {"status": "FAIL" if findings else "PASS",
                "dependencies": len(deps), "findings": findings, "requirements_sha256": sha(requirements),
                "severity_note": "pip-audit does not classify severity; any finding requires review"}
            if (result.returncode == 0) != (not findings):
                raise RuntimeError(name + " exit/result inconsistency")
            print(json.dumps({"check": name, "dependencies": len(deps), "affected_packages": len(findings)}), flush=True)

        bandit = work / "bandit.json"
        # R2 forbids silently inheriting previous risk waivers (# nosec).
        run("bandit", [str(venv / "bin/bandit"), "-r", *CODE_DIRS,
            "--ignore-nosec", "-f", "json", "-o", str(bandit)], allowed=(0, 1))
        data = json.loads(bandit.read_text())
        if data.get("errors") or not data.get("metrics", {}).get("_totals", {}).get("loc"):
            raise RuntimeError("bandit incomplete scan")
        findings = [{k: row[k] for k in ("filename", "line_number", "test_id", "issue_severity", "issue_confidence", "issue_text")}
                    for row in data["results"]]
        for row in findings:
            row["filename"] = row["filename"].removeprefix(str(snapshot) + "/")
        high = [row for row in findings if row["issue_severity"] == "HIGH" and row["issue_confidence"] == "HIGH"]
        assessment = assess_static_risk(findings, before, (snapshot / RISK_PATH).read_bytes())
        evidence["checks"]["bandit"] = {**assessment, "high_confidence_high_severity": len(high),
            "findings": findings, "metrics": data["metrics"]["_totals"], "raw_scanner_status": "FINDINGS" if findings else "CLEAN"}
        print(json.dumps({"check": "bandit", "high_confidence_high_severity": len(high)}), flush=True)
        states = {v["status"] for v in evidence["checks"].values()}
        evidence["status"] = ("FAIL" if "FAIL" in states else "PASS_WITH_ACCEPTED_RISK_SCOPED"
                              if "ACCEPTED_RISK" in states else "PASS_SCOPED")
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = str(exc) if isinstance(exc, RuntimeError) else "private command evidence requires inspection"
    finally:
        evidence["source_unchanged"] = bool(before) and before == {name: sha(ROOT / name) for name in before}
        if not evidence["source_unchanged"]:
            evidence["status"] = "SOURCE_DRIFT"
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        save(work / "result.json", evidence)
        print(json.dumps({"status": evidence["status"], "checks": {k: v["status"] for k, v in evidence["checks"].items()},
                          "evidence": str(work / "result.json")}), flush=True)
    return 0 if evidence["status"] in {"PASS_SCOPED", "PASS_WITH_ACCEPTED_RISK_SCOPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

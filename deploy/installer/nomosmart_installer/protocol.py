"""Protocol contract installer. No IdP administration or secret-value reads."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import tomllib
from uuid import UUID

from .core import ActionRequired, PreconditionError, Redactor, Runner
from .chart_digest import chart_digest
from .protocol_inputs import regular_bytes, target_digest


@dataclass(frozen=True)
class ProtocolRelease:
    package_dir: Path
    trusted_signer_fingerprint: str
    purpose: str

    @classmethod
    def load(cls, raw: dict, root: Path):
        if (not isinstance(raw, dict) or set(raw) != {"package_dir", "trusted_signer_fingerprint", "purpose", "isolated_environment_acknowledged"}
                or raw["purpose"] not in {"local-verified-release", "local-risk-reviewed-release"} or raw["isolated_environment_acknowledged"] is not True):
            raise ValueError("local release requires explicit isolated scope and signer trust")
        fingerprint = re.sub(r"\s+", "", raw["trusted_signer_fingerprint"]).upper()
        if not re.fullmatch(r"(?:[0-9A-F]{40}|[0-9A-F]{64})", fingerprint):
            raise ValueError("independent signer fingerprint required")
        directory = root / raw["package_dir"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("regular release package directory required")
        return cls(directory.resolve(strict=True), fingerprint, raw["purpose"])


@dataclass(frozen=True)
class ProtocolTarget:
    context: str
    namespace: str
    release: str
    installation_id: str
    values_file: Path
    chart: Path
    release_package: ProtocolRelease | None = None
    test_candidate: dict | None = None

    @classmethod
    def load(cls, path: Path, *, allow_test_candidate=False):
        try:
            raw = tomllib.loads(regular_bytes(path).decode("utf-8"))
            allowed = [{"api_version", "target"}, {"api_version", "target", "release"}]
            if allow_test_candidate:
                allowed.append({"api_version", "target", "test_candidate"})
            if set(raw) not in allowed or raw["api_version"] != "install.nomosmart.io/protocol-v2":
                raise ValueError("unsupported configuration")
            target = raw["target"]
            if set(target) != {"context", "namespace", "release", "installation_id", "values_file", "chart"}:
                raise ValueError("unknown target field")
            if not isinstance(target["context"], str) or not target["context"].strip():
                raise ValueError("missing context")
            for key in ("namespace", "release"):
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,51}[a-z0-9])?", target[key]):
                    raise ValueError("invalid target name")
            root = path.resolve().parent
            values_path, chart_path = root / target["values_file"], root / target["chart"]
            regular_bytes(values_path)
            if chart_path.is_symlink():
                raise ValueError("chart must not be a symlink")
            test = None
            if "test_candidate" in raw:
                value = raw["test_candidate"]
                if set(value) != {"package_dir", "archive", "platform"} or value["platform"] not in {"linux/amd64", "linux/arm64"}:
                    raise ValueError("explicit test candidate configuration required")
                package, archive = root / value["package_dir"], root / value["archive"]
                if package.is_symlink() or archive.is_symlink() or not package.is_dir() or not archive.is_file():
                    raise ValueError("regular test candidate materials required")
                if chart_path.resolve(strict=True) != package.resolve(strict=True) / "deploy/helm/nomosmart":
                    raise ValueError("test candidate must use its packaged chart")
                test = {"package_dir": package.resolve(strict=True), "archive": archive.resolve(strict=True),
                        "platform": value["platform"], "chart_sha256": chart_digest(chart_path)}
            return cls(target["context"], target["namespace"], target["release"], str(UUID(target["installation_id"])), values_path.resolve(strict=True), chart_path.resolve(strict=True), ProtocolRelease.load(raw["release"], root) if "release" in raw else None, test)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PreconditionError("Invalid protocol installer configuration") from exc


class ProtocolInstaller:
    def __init__(self, path: Path, *, test_candidate_scope: Path | None = None):
        self.configuration_path = path.expanduser().absolute()
        self.target = ProtocolTarget.load(self.configuration_path, allow_test_candidate=test_candidate_scope is not None)
        if (self.target.test_candidate is not None) != (test_candidate_scope is not None):
            raise PreconditionError("Test candidate requires its explicit configuration and --test-candidate-scope together")
        self._input_digest = target_digest(self.configuration_path, self.target)
        self.runner = Runner(Redactor(), cwd=path.resolve().parent)
        self.test_scope = None
        if test_candidate_scope is not None:
            from .test_candidate_scope import TestCandidateScope
            self.test_scope = TestCandidateScope(test_candidate_scope, self.target, self._input_digest)
            self._guard_test_scope()
        try:
            self.values = json.loads(regular_bytes(self.target.values_file))
            auth = self.values["authentication"]
            mode = auth["bootstrapConfiguration"]["configuration"]["auth_mode"]
            if auth.get("contractRevision", 2) != 2 or mode not in {"ldap", "oidc"}:
                raise ValueError("unsupported authentication contract")
            if not self.values.get("secrets", {}).get("existingSecret") or self.values["secrets"].get("data"):
                raise ValueError("external runtime Secret is required")
            if "keycloak" in self.values:
                raise ValueError("IdP software is managed separately")
            if self.values.get("deploymentProfile") != "external-services":
                raise ValueError("protocol installer expects operator-managed infrastructure")
            self._reject_credentials(self.values)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PreconditionError("Protocol values require auth contract 2, operator-managed services and an existing runtime Secret; credential values are forbidden") from exc
        self.mode = mode
        self.release_verification = self._verify_release()
        self.evidence_release = self.target.release + "-" + self.target.installation_id[:8]
        self.values.setdefault("bootstrap", {})["evidenceRelease"] = self.evidence_release

    def _verify_release(self):
        if self.test_scope is not None:
            result = self.test_scope.result
            for name in ("frontend", "backend"):
                image = self.values.get("image", {}).get(name, {})
                tag = image.get("tag", "")
                if not isinstance(tag, str) or not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", tag):
                    raise PreconditionError("Test candidate application image must be digest-pinned")
                reference = image.get("repository", "") + "@" + tag.split("@", 1)[1]
                key = name + ":" + self.target.test_candidate["platform"]
                if result["image_digests"].get(key) != reference:
                    raise PreconditionError("Test candidate application image differs from its exact platform material")
            migration = self.values.get("image", {}).get("migration", {})
            if migration.get("repository", "") + ":" + migration.get("tag", "") != result["migration_reference"]:
                raise PreconditionError("Test candidate migration image differs from its dependency lock")
            return result
        release = self.target.release_package
        if release is None:
            # An unsigned schema5 chart cannot silently become an engineering-source install.
            marker = self.target.chart.parents[2] / "release-manifest.json"
            if marker.exists() or marker.is_symlink():
                try:
                    if json.loads(regular_bytes(marker)).get("schema_version") == 5:
                        raise PreconditionError("Schema5 package requires an explicit signed release or test-candidate scope")
                except (ValueError, OSError) as exc:
                    raise PreconditionError("Package identity is invalid") from exc
            return {"status": "engineering-source", "production_ready": False}
        from .release import verify_release_package, ReleaseContractError
        try:
            result = verify_release_package(release.package_dir,
                trusted_fingerprint=release.trusted_signer_fingerprint,
                expected_chart_sha256=chart_digest(self.target.chart), purpose=release.purpose)
            for name in ("frontend", "backend", "migration"):
                image = self.values.get("image", {}).get(name, {})
                if not isinstance(image, dict):
                    raise ReleaseContractError("protocol release image configuration is invalid")
                reference = image.get("repository", "") + ":" + image.get("tag", "")
                if result["image_digests"].get(name) != reference:
                    raise ReleaseContractError("protocol image differs from the signed release: " + name)
            return result
        except (ReleaseContractError, ValueError) as exc:
            raise PreconditionError("Protocol release verification failed") from exc

    @staticmethod
    def _reject_credentials(value):
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in {"password", "bind_password", "client_secret", "app_encryption_key", "auth_encryption_key", "directory_bind_password", "oidc_client_secret", "stringdata"}:
                    raise ValueError("credential value is forbidden")
                ProtocolInstaller._reject_credentials(child)
        elif isinstance(value, list):
            for child in value:
                ProtocolInstaller._reject_credentials(child)

    def _assert_inputs_unchanged(self):
        current = ProtocolTarget.load(self.configuration_path, allow_test_candidate=self.test_scope is not None)
        if target_digest(self.configuration_path, current) != self._input_digest:
            raise PreconditionError("Protocol target/values/chart changed; obtain a new read-only plan")
        self._guard_test_scope()

    def _guard_test_scope(self, *, mutation=False):
        if self.test_scope is None:
            return
        current = ProtocolTarget.load(self.configuration_path, allow_test_candidate=True)
        if target_digest(self.configuration_path, current) != self._input_digest:
            raise PreconditionError("Test candidate configuration changed")
        self.test_scope.check(mutation=mutation)
        result = self.runner.run(["kubectl", "--context", self.target.context, "get", "namespace",
                                  self.target.namespace, "-o", "json"], timeout=180)
        self.test_scope.check_namespace(json.loads(result.stdout))

    def _kubectl(self, *args, accepted=frozenset({0})):
        self._guard_test_scope(mutation=any(arg in {"exec", "create", "apply", "delete", "patch"} for arg in args))
        return self.runner.run(["kubectl", "--context", self.target.context, *args], accepted=accepted, timeout=180)

    def _namespace(self, *, create=False):
        result = self._kubectl("get", "namespace", self.target.namespace, "--ignore-not-found", "-o", "json")
        if not result.stdout.strip():
            if self.test_scope is not None:
                raise PreconditionError("Test candidate requires its existing UID-bound namespace")
            if not create:
                return None
            self._assert_inputs_unchanged()
            manifest = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.target.namespace, "labels": {"nomosmart.io/protocol-installation": self.target.installation_id}}}
            self.runner.run(["kubectl", "--context", self.target.context, "create", "-f", "-"], input_text=json.dumps(manifest))
            return self._namespace()
        record = json.loads(result.stdout)
        if record.get("metadata", {}).get("labels", {}).get("nomosmart.io/protocol-installation") != self.target.installation_id:
            raise PreconditionError("Namespace is not owned by this protocol installation")
        return record["metadata"]["uid"]

    def _values(self, *, finalize=False, operational=False):
        values = json.loads(json.dumps(self.values))
        values.setdefault("installer", {})["deploymentStage"] = "operational" if operational else "application"
        values.setdefault("bootstrap", {})["deploymentPhase"] = "operational" if operational else "onboarding"
        values["bootstrap"]["finalize"] = {"enabled": finalize}
        return values

    def _helm(self, operation, *, finalize=False, operational=False):
        self._assert_inputs_unchanged()
        self._guard_test_scope(mutation=operation != "template")
        with tempfile.TemporaryDirectory(prefix="nomosmart-protocol-") as directory:
            path = Path(directory) / "values.json"
            path.write_text(json.dumps(self._values(finalize=finalize, operational=operational)));path.chmod(0o600)
            args = ["helm", operation]
            if operation == "upgrade": args += ["--install"]
            args += [self.target.release, str(self.target.chart), "--kube-context", self.target.context, "--namespace", self.target.namespace, "--values", str(path)]
            if operation == "upgrade": args += ["--wait", "--wait-for-jobs", "--timeout", "20m", "--history-max", "20"]
            return self.runner.run(args, timeout=1250 if operation == "upgrade" else 180)

    def plan(self):
        self._assert_inputs_unchanged()
        uid = self._namespace()
        rendered = self._helm("template").stdout
        if "app.kubernetes.io/component: keycloak" in rendered:
            raise PreconditionError("Rendered application must not require a bundled IdP")
        return {"status": "ready", "read_only": True, "context": self.target.context, "installation_id": self.target.installation_id, "config_digest": self._input_digest, "namespace_uid": uid, "namespace": self.target.namespace, "release": self.target.release, "authentication_mode": self.mode, "auth_contract_revision": 2, "release_verification": self.release_verification, "values_sha256": hashlib.sha256(self.target.values_file.read_bytes()).hexdigest(), "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(), "steps": ["bootstrap existing services and directory", "normal administrator sign-in and verification", "finalize onboarding", "verify operational readiness"], "secret_values_read": False}

    def install(self, *, expected_digest=None):
        if expected_digest is not None and expected_digest != self._input_digest:
            raise PreconditionError("Confirmation digest does not match this protocol target")
        self.plan()
        self._assert_inputs_unchanged()
        self._namespace(create=True)
        self._helm("upgrade")
        return {"status": "action-required", "next_command": "finalize", "action": "Sign in as a synchronized normal administrator at the configured HTTPS login page. For OIDC, also reauthenticate to unlock identity settings.", "auth_contract_revision": 2}

    resume = install

    def _backend_exec(self, script):
        pods = json.loads(self._kubectl("-n", self.target.namespace, "get", "pods", "-l", f"app.kubernetes.io/instance={self.target.release},app.kubernetes.io/component=backend", "-o", "json").stdout)["items"]
        ready = [pod for pod in pods if pod.get("status", {}).get("phase") == "Running" and any(c.get("type") == "Ready" and c.get("status") == "True" for c in pod.get("status", {}).get("conditions", []))]
        if not ready: raise ActionRequired("A ready application backend is required")
        return self._kubectl("-n", self.target.namespace, "exec", ready[0]["metadata"]["name"], "-c", "backend", "--", "python", "-c", script)

    def finalize(self):
        self._namespace()
        self._backend_exec("from app.db.session import get_session_factory; from app.deployment.protocol_status import normal_admin_evidence\nwith get_session_factory()() as s: normal_admin_evidence(s)\nprint('normal_admin_verified')")
        self._helm("upgrade", finalize=True)
        self._helm("upgrade", operational=True)
        return self.verify()

    def status(self):
        uid = self._namespace()
        if uid is None: return {"status": "not-installed", "next_command": "install"}
        result = self.runner.run(["helm", "status", self.target.release, "--kube-context", self.target.context, "--namespace", self.target.namespace, "-o", "json"])
        data = json.loads(result.stdout)
        return {"status": data["info"]["status"], "revision": data["version"], "namespace_uid": uid, "auth_contract_revision": 2}

    doctor = status

    def verify(self):
        self._namespace()
        self._backend_exec("from app.deployment.bootstrap import _protocol_onboarding_check; from app.core.config import get_settings\n_protocol_onboarding_check(get_settings())\nprint('onboarding_verified')")
        return {**self.status(), "onboarding": "normal_administrator_verified", "secret_values_read": False}

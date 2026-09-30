from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .barman_cloud import BarmanCloud
from .config import InstallConfig
from .cloudnativepg import CloudNativePG
from .core import (
    ActionRequired,
    DriftError,
    InstallerError,
    PreconditionError,
    Redactor,
    Runner,
    atomic_private_json,
    local_lock,
    sha256_file,
)
from .directory import KeycloakDirectoryInstaller
from .diagnostics import InstallerDiagnostics
from .factory import FactoryReinstall
from .helm import Helm
from .kube import Kubernetes
from .package import PackageManager
from .preflight import build_plan
from .release import InstallerReleaseVerifier
from .state import STAGES, InstallerState, Lease, StateStore
from .verify import Verifier


def recoverable_finalization_helm_status(
    state: InstallerState,
    status: dict[str, Any],
) -> bool:
    return (
        status.get("status") == "failed"
        and state.current_stage == "operational-finalization"
        and "identity-checkpoint" in state.completed_stages
        and "operational-finalization" not in state.completed_stages
    )


class Installer:
    def __init__(self, config: InstallConfig) -> None:
        self.config = config
        self.repository = Path(__file__).resolve().parents[3]
        self.redactor = Redactor()
        self.runner = Runner(self.redactor, cwd=self.repository)
        self.kube = Kubernetes(config, self.runner)
        self.cloudnativepg = CloudNativePG(config, self.kube)
        self.barman_cloud = BarmanCloud(config, self.kube)
        self.helm = Helm(config, self.runner, self.kube)
        self.package = PackageManager(
            config, self.runner, self.kube, self.repository
        )
        self.directory = KeycloakDirectoryInstaller(
            config, self.kube, self.redactor
        )
        self.store = StateStore(config, self.kube, __version__)
        self.release = InstallerReleaseVerifier(config)
        self.diagnostics = InstallerDiagnostics(
            config,
            self.kube,
            self.helm,
            self.store,
        )
        self.factory = FactoryReinstall(
            config,
            self.kube,
            self.helm,
            self.store,
        )
        self.verifier = Verifier(
            config,
            self.kube,
            self.helm,
            self.directory,
        )

    def plan(self) -> dict[str, Any]:
        try:
            release = self.release.verify()
            plan = build_plan(self.config, self.runner, self.kube)
            if release.get("required") or release.get("status") == "verified":
                plan["release_package"] = release
            return plan
        except (PreconditionError, DriftError):
            raise
        except InstallerError as exc:
            raise PreconditionError(
                f"read-only preflight failed: {exc}"
            ) from exc

    def status(self) -> dict[str, Any]:
        target = self.kube.validate_identity()
        state = self.store.load(allow_missing=True)
        if state is None:
            return {
                "status": "not-installed",
                "target": target,
                "config_digest": self.config.digest,
                "next_command": "plan",
            }
        pending = [stage for stage in STAGES if stage not in state.completed_stages]
        helm: dict[str, Any] | None = None
        try:
            helm = self.helm.status()
        except InstallerError:
            helm = None
        return {
            "status": "complete" if not pending else "in-progress",
            "target": target,
            "current_stage": state.current_stage,
            "completed_stages": state.completed_stages,
            "pending_stages": pending,
            "last_error": state.last_error,
            "helm": helm,
            "next_command": "verify" if not pending else "resume",
        }

    def verify(self) -> dict[str, Any]:
        state = self.store.load(allow_missing=False)
        if "operational-finalization" not in state.completed_stages:
            raise PreconditionError(
                "deployment is not operational; resume/finalize checkpoints first"
            )
        self._revalidate_completed(state)
        return self.verifier.verify()

    def doctor(self) -> dict[str, Any]:
        return self.diagnostics.doctor()

    def reset_plan(self, output: Path) -> dict[str, Any]:
        return self.diagnostics.reset_plan(output)

    def reset_apply(
        self, plan: Path, *, confirmation: str
    ) -> dict[str, Any]:
        return self.diagnostics.reset_apply(
            plan, confirmation=confirmation
        )

    def factory_plan(self, output: Path) -> dict[str, Any]:
        return self.factory.plan(output)

    def factory_apply(
        self,
        plan: Path,
        *,
        confirmation: str,
        approval: str,
    ) -> dict[str, Any]:
        return self.factory.apply(
            plan,
            confirmation=confirmation,
            approval=approval,
        )

    def install(self) -> dict[str, Any]:
        return self._run(fresh=True)

    def resume(self) -> dict[str, Any]:
        return self._run(fresh=False)

    def finalize(self) -> dict[str, Any]:
        return self._run(fresh=False)

    def _run(self, *, fresh: bool) -> dict[str, Any]:
        with local_lock(self.config.application.state_dir):
            plan = self.plan()
            if plan["config_digest"] != self.config.digest:
                raise DriftError(
                    "installer source artifacts changed during preflight"
                )
            existing = self.store.load(allow_missing=True)
            if fresh and existing is not None:
                raise PreconditionError(
                    "installer state already exists; use resume for this release"
                )
            if not fresh and existing is None:
                raise PreconditionError(
                    "installer state is unavailable; use install after a successful plan"
                )
            self.kube.ensure_namespace()
            lease = Lease(self.config, self.kube)
            lease.acquire()
            lease.start_heartbeat()
            state = existing
            try:
                if state is None:
                    state = self.store.fresh()
                elif "preflight" in state.completed_stages:
                    previous_preflight = state.postconditions.get(
                        "preflight", {}
                    )
                    for key, current in (
                        (
                            "referenced_secret_fingerprints",
                            plan.get(
                                "referenced_secret_fingerprints", {}
                            ),
                        ),
                        (
                            "release_package",
                            plan.get("release_package"),
                        ),
                    ):
                        previous_value = previous_preflight.get(key)
                        if (
                            key == "referenced_secret_fingerprints"
                            and self.config.deployment_profile
                            == "external-services"
                            and self.package.break_glass_retired()
                        ):
                            # The external runtime Secret is operator-owned.
                            # Once finalization retired the local bootstrap
                            # package, the operator may remove that one key;
                            # do not turn this documented cleanup into input
                            # drift on a later resume.
                            retired_key = (
                                f"{self.config.application.runtime_secret}:"
                                "BREAK_GLASS_INITIAL_PASSWORD"
                            )
                            previous_value = dict(previous_value or {})
                            current = dict(current or {})
                            previous_value.pop(retired_key, None)
                            current.pop(retired_key, None)
                        if previous_value != current:
                            raise DriftError(
                                f"completed preflight input differs: {key}"
                            )
                self._revalidate_completed(state)
                handlers: dict[str, Callable[[], dict[str, Any]]] = {
                    "preflight": lambda: {
                        "config_digest": plan["config_digest"],
                        "target": plan["target"],
                        "ready_schedulable_nodes": plan[
                            "ready_schedulable_nodes"
                        ],
                        "referenced_secret_fingerprints": plan.get(
                            "referenced_secret_fingerprints", {}
                        ),
                        "release_package": plan.get("release_package"),
                    },
                    "package-and-secrets": self._package_and_secrets,
                    "cloudnativepg-operator": self._cloudnativepg_stage,
                    "barman-cloud-plugin": self._barman_cloud_stage,
                    "foundation": self._foundation,
                    "migration-bootstrap-and-app": self._application,
                    "directory-integration": self._directory,
                    "identity-checkpoint": self._identity_checkpoint,
                    "operational-finalization": lambda: self._finalize(
                        state.helm_revision
                    ),
                    "verification-receipt": self._receipt,
                }
                for stage in STAGES:
                    if stage in state.completed_stages:
                        continue
                    state.begin(stage)
                    self.store.save(state)
                    lease.check_heartbeat()
                    lease.renew()
                    evidence = handlers[stage]()
                    lease.check_heartbeat()
                    if stage == "package-and-secrets":
                        state.resource_fingerprints["secrets"] = evidence.get(
                            "secret_fingerprints", {}
                        )
                        state.resource_fingerprints["package_manifest"] = (
                            evidence.get("manifest_sha256", "")
                        )
                    elif stage == "migration-bootstrap-and-app":
                        state.resource_fingerprints["workloads"] = evidence.get(
                            "resource_fingerprint", ""
                        )
                    elif stage == "verification-receipt":
                        state.resource_fingerprints["receipt"] = evidence.get(
                            "sha256", ""
                        )
                    elif stage == "operational-finalization":
                        runtime_fingerprints = (
                            evidence.get("package", {}).get(
                                "runtime_secret_fingerprints", {}
                            )
                        )
                        runtime_name = (
                            self.config.application.runtime_secret
                        )
                        package_evidence = state.postconditions.get(
                            "package-and-secrets", {}
                        )
                        package_fingerprints = package_evidence.get(
                            "secret_fingerprints", {}
                        )
                        if runtime_fingerprints:
                            package_fingerprints[runtime_name] = (
                                runtime_fingerprints
                            )
                            state.resource_fingerprints.setdefault(
                                "secrets", {}
                            )[runtime_name] = runtime_fingerprints
                        for key in (
                            "generation_id",
                            "deployment_state",
                            "manifest_sha256",
                            "credential_inventory_sha256",
                        ):
                            if key in evidence.get("package", {}):
                                package_evidence[key] = evidence[
                                    "package"
                                ][key]
                        state.resource_fingerprints[
                            "package_manifest"
                        ] = package_evidence.get("manifest_sha256", "")
                    if stage in {
                        "foundation",
                        "migration-bootstrap-and-app",
                        "operational-finalization",
                    }:
                        state.helm_revision = self.helm.revision()
                    state.complete(stage, evidence)
                    self.store.save(state)
                    lease.renew()
                return {
                    "status": "complete",
                    "release": self.config.target.release,
                    "namespace": self.config.target.namespace,
                    "completed_stages": state.completed_stages,
                    "receipt": str(self.store.receipt_path),
                    "services_left_running": True,
                }
            except KeyboardInterrupt:
                if state is not None:
                    state.fail("Interrupted")
                    self.store.save(state)
                raise
            except InstallerError as exc:
                if state is not None:
                    state.fail(type(exc).__name__)
                    self.store.save(state)
                raise
            except Exception:
                if state is not None:
                    state.fail("UnexpectedInstallerFailure")
                    try:
                        self.store.save(state)
                    except Exception:
                        pass
                raise
            finally:
                lease.release()

    def _package_and_secrets(self) -> dict[str, Any]:
        self.package.initialize()
        return self.package.create_secrets()

    def _cloudnativepg_stage(self) -> dict[str, Any]:
        if self.config.deployment_profile == "external-services":
            return {
                "status": "skipped",
                "reason": "external-services profile owns PostgreSQL",
            }
        return self.cloudnativepg.ensure()

    def _barman_cloud_stage(self) -> dict[str, Any]:
        if self.config.deployment_profile == "external-services":
            return {
                "status": "skipped",
                "reason": "external-services profile owns backup storage",
            }
        return self.barman_cloud.ensure()

    def _foundation(self) -> dict[str, Any]:
        current = self._release_config()
        revision = (
            int(current["revision"])
            if current is not None
            and current["status"] == "deployed"
            and current["stage"] == "foundation"
            else self.helm.upgrade("foundation")
        )
        backup_bucket: dict[str, Any] = {
            "status": "not-managed",
            "reason": "external-services profile owns PostgreSQL backup storage",
        }
        if self.config.deployment_profile != "external-services":
            backup_bucket_job = (
                f"{self._fullname()}-postgresql-backup-bucket-{revision}"
            )
            backup_bucket = self.kube.wait_job_terminal(
                backup_bucket_job, timeout=1800
            )
        return {
            "helm_revision": revision,
            "postgresql_backup_bucket": backup_bucket,
        }

    def _application(self) -> dict[str, Any]:
        if self.config.deployment_profile == "external-services":
            postgresql: dict[str, Any] = {
                "mode": "external",
                "status": "operator-owned",
                "configured_host": "external",
            }
        else:
            postgresql = self.kube.wait_cloudnativepg_cluster(
                self.config.helm_fullname,
                instances=3,
            )
        current = self._release_config()
        if (
            current is not None
            and current["status"] == "deployed"
            and current["stage"] == "application"
            and not current["finalization"]
            and self._application_jobs_succeeded(int(current["revision"]))
        ):
            revision = int(current["revision"])
        else:
            revision = self.helm.upgrade("application")
        status = self.helm.status()
        if status["status"] != "deployed":
            raise InstallerError("application Helm revision is not deployed")
        if self.config.deployment_profile == "external-services":
            postgresql_backup: dict[str, Any] = {
                "status": "operator-owned",
            }
        else:
            postgresql_backup = self.kube.wait_cloudnativepg_backup(
                self.config.helm_fullname,
                timeout=1800,
            )
        workload = self.verifier.workloads()
        return {
            "helm_revision": revision,
            "helm_status": status["status"],
            "postgresql": postgresql,
            "postgresql_backup": postgresql_backup,
            "resource_fingerprint": workload["fingerprint"],
        }

    def _directory(self) -> dict[str, Any]:
        provider = self.directory.configure()
        mapping = self.directory.reconcile_application_mapping()
        return {"provider": provider, "application_mapping": mapping}

    def _identity_checkpoint(self) -> dict[str, Any]:
        try:
            return {
                "federated_administrator": (
                    self.directory.verify_identity_checkpoint()
                ),
                "break_glass": (
                    self.directory.verify_break_glass_checkpoint()
                ),
                "application": (
                    self.directory.verify_application_onboarding()
                ),
            }
        except PreconditionError as exc:
            raise ActionRequired(
                "complete the designated federated administrator and break-glass "
                "first login and password change at "
                f"https://{self.config.application.public_host}/login, "
                "then rerun resume"
            ) from exc

    def _finalize(
        self,
        application_revision: int | None,
    ) -> dict[str, Any]:
        if (
            application_revision is None
            or application_revision < 1
            or not self._job_succeeded(
                f"{self._fullname()}-bootstrap-{application_revision}"
            )
        ):
            raise PreconditionError(
                "successful application bootstrap evidence revision is unavailable"
            )
        bootstrap_release = (
            f"{self.config.target.release}-{application_revision}"
        )
        current = self._release_config()
        finalize_revision: int
        if (
            current is not None
            and current["status"] == "deployed"
            and current["stage"] == "operational"
        ):
            finalize_revision = int(current["revision"]) - 1
            if not self._job_succeeded(
                f"{self._fullname()}-finalize-{finalize_revision}"
            ):
                raise PreconditionError(
                    "operational Helm stage lacks successful finalization Job evidence"
                )
            operational_revision = int(current["revision"])
        elif (
            current is not None
            and current["status"] == "deployed"
            and current["stage"] == "application"
            and current["finalization"]
            and self._job_succeeded(
                f"{self._fullname()}-finalize-{int(current['revision'])}"
            )
        ):
            finalize_revision = int(current["revision"])
            operational_revision = self.helm.upgrade(
                "operational",
                bootstrap_release=bootstrap_release,
            )
        else:
            finalize_revision = self.helm.upgrade(
                "application",
                finalize=True,
                bootstrap_release=bootstrap_release,
            )
            operational_revision = self.helm.upgrade(
                "operational",
                bootstrap_release=bootstrap_release,
            )
        package = self.package.mark_finalized()
        return {
            "finalization_revision": finalize_revision,
            "operational_revision": operational_revision,
            "package": package,
        }

    def _receipt(self) -> dict[str, Any]:
        receipt = self.verifier.verify()
        atomic_private_json(self.store.receipt_path, receipt)
        return {
            "path": str(self.store.receipt_path),
            "sha256": sha256_file(self.store.receipt_path),
            "status": receipt["status"],
        }

    def _fullname(self) -> str:
        release = self.config.target.release
        return (release if "nomosmart" in release else f"{release}-nomosmart")[
            :63
        ].rstrip("-")

    def _release_config(self) -> dict[str, Any] | None:
        try:
            status = self.helm.status()
        except InstallerError:
            return None
        if status["status"] not in {"deployed", "failed"}:
            raise PreconditionError(
                f"Helm release is {status['status']}; operator recovery is required"
            )
        config_name = f"{self._fullname()}-config"
        if not self.kube.exists("configmap", config_name):
            if status["status"] == "failed":
                return {
                    "revision": status["revision"],
                    "status": "failed",
                    "stage": "",
                    "finalization": False,
                }
            raise PreconditionError(
                "deployed Helm release is missing its configuration evidence"
            )
        configmap = self.kube.json(
            "get", "configmap", config_name, namespace=True
        )
        data = configmap.get("data") or {}
        return {
            "revision": status["revision"],
            "status": status["status"],
            "stage": str(data.get("INSTALLER_DEPLOYMENT_STAGE") or ""),
            "finalization": str(
                data.get("INSTALLER_FINALIZATION_ENABLED") or ""
            ).lower()
            == "true",
        }

    def _job_succeeded(self, name: str) -> bool:
        if not self.kube.exists("job", name):
            return False
        payload = self.kube.json("get", "job", name, namespace=True)
        return int((payload.get("status") or {}).get("succeeded") or 0) == 1

    def _application_jobs_succeeded(self, revision: int) -> bool:
        fullname = self._fullname()
        return self._job_succeeded(
            f"{fullname}-migration-{revision}"
        ) and self._job_succeeded(f"{fullname}-bootstrap-{revision}")

    def _revalidate_completed(self, state: InstallerState) -> None:
        if "package-and-secrets" in state.completed_stages:
            package_evidence = state.postconditions.get(
                "package-and-secrets", {}
            )
            pending_finalization = (
                state.current_stage == "operational-finalization"
                and "operational-finalization"
                not in state.completed_stages
                and self.package.break_glass_retired()
            )
            self.package.verify_evidence(
                package_evidence,
                allow_pending_finalization=pending_finalization,
            )
            expected = package_evidence.get("secret_fingerprints", {})
            for name, fingerprints in expected.items():
                actual = self.kube.secret_fingerprints(name)
                if (
                    name == self.config.application.runtime_secret
                    and self.package.break_glass_retired()
                ):
                    retired_fingerprints = {
                        key: value
                        for key, value in fingerprints.items()
                        if key != "BREAK_GLASS_INITIAL_PASSWORD"
                    }
                    matches = actual in (
                        fingerprints,
                        retired_fingerprints,
                    )
                else:
                    matches = actual == fingerprints
                if not matches:
                    raise PreconditionError(
                        f"completed secret/{name} fingerprint differs"
                    )
        if "foundation" in state.completed_stages:
            status = self.helm.status()
            if (
                status["status"] != "deployed"
                and not recoverable_finalization_helm_status(state, status)
            ):
                raise PreconditionError(
                    "completed foundation Helm release is not deployed"
                )
            if (
                state.helm_revision is not None
                and state.current_stage
                not in {
                    "migration-bootstrap-and-app",
                    "operational-finalization",
                }
                and status["revision"] != state.helm_revision
            ):
                raise PreconditionError(
                    "Helm revision differs from completed installer state"
                )
        if "migration-bootstrap-and-app" in state.completed_stages:
            status = self.helm.status()
            if (
                status["status"] != "deployed"
                and not recoverable_finalization_helm_status(state, status)
            ):
                raise PreconditionError(
                    "completed application Helm release is not deployed"
                )
        if "directory-integration" in state.completed_stages:
            self.directory.verify_provider()
            self.directory.verify_application_mapping()
        if "identity-checkpoint" in state.completed_stages:
            allow_disabled_break_glass = (
                state.current_stage == "operational-finalization"
                or "operational-finalization" in state.completed_stages
            )
            self.directory.verify_identity_checkpoint()
            self.directory.verify_break_glass_checkpoint(
                allow_disabled=allow_disabled_break_glass
            )
            self.directory.verify_application_onboarding(
                allow_disabled_break_glass=allow_disabled_break_glass
            )
        if "operational-finalization" in state.completed_stages:
            configmap = self.kube.json(
                "get",
                "configmap",
                f"{self._fullname()}-config",
                namespace=True,
            )
            if (
                str((configmap.get("data") or {}).get("DEPLOYMENT_PHASE") or "")
                != "operational"
            ):
                raise PreconditionError(
                    "completed finalization is no longer operational"
                )
        if "verification-receipt" in state.completed_stages:
            evidence = state.postconditions.get("verification-receipt", {})
            if (
                not self.store.receipt_path.is_file()
                or sha256_file(self.store.receipt_path) != evidence.get("sha256")
            ):
                raise PreconditionError(
                    "completed verification receipt fingerprint differs"
                )

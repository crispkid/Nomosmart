from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote, urlencode

from .config import InstallConfig
from .core import DriftError, InstallerError, PreconditionError, Redactor
from .kube import CONFIG_ANNOTATION, OWNER_LABEL, Kubernetes
from .tls_client import TLSClient, TLSClientError


COMPONENT_TYPE = "org.keycloak.storage.UserStorageProvider"
MAPPER_TYPE = "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"


def onboarding_status_probe_script(
    *,
    allow_disabled_break_glass: bool = False,
) -> str:
    allow_disabled = (
        "True" if allow_disabled_break_glass else "False"
    )
    return f"""
import json
import sys

from app.core.config import Settings
from app.deployment.bootstrap import (
    BootstrapFailure,
    _realm_name,
    _verify_finalization_database_evidence,
)
from app.integrations.keycloak import KeycloakAdminClient

try:
    from app.deployment.onboarding_status import OnboardingStatusSettings
except ImportError:
    class OnboardingStatusSettings(Settings):
        deployment_finalization_admin_username: str = ""
        deployment_finalization_admin_group: str = ""

try:
    settings = OnboardingStatusSettings()
    client = KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    break_glass_id = client.verify_break_glass_onboarding_complete(
        settings.break_glass_username,
        system_admin_group=settings.break_glass_system_admin_group,
        allow_disabled={allow_disabled},
    )
    federated_id = client.verify_federated_admin_onboarding_complete(
        settings.deployment_finalization_admin_username,
        external_group=settings.deployment_finalization_admin_group,
    )
    _verify_finalization_database_evidence(
        settings,
        break_glass_keycloak_user_id=break_glass_id,
        federated_admin_keycloak_user_id=federated_id,
    )
    payload = {{
        "status": "ready",
        "break_glass": "first_use_complete",
        "federated_administrator": "oidc_password_role_ready",
    }}
except BootstrapFailure as exc:
    print(
        json.dumps({{"status": "action-required", "code": exc.code}}),
        file=sys.stderr,
    )
    raise SystemExit(1)
except Exception:
    print(
        json.dumps(
            {{
                "status": "action-required",
                "code": "onboarding_evidence_incomplete",
            }}
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)
print(json.dumps(payload, sort_keys=True))
""".strip()


class KeycloakDirectoryInstaller:
    def __init__(
        self,
        config: InstallConfig,
        kube: Kubernetes,
        redactor: Redactor,
    ) -> None:
        self.config = config
        self.identity = config.identity
        self.kube = kube
        self.redactor = redactor
        self.base_url = f"https://{config.application.public_host}/identity"
        self._token = ""
        self._realm_component_parent = ""

    @property
    def evidence_name(self) -> str:
        return f"{self.config.helm_fullname}-directory-evidence"

    def _tls_client(self) -> TLSClient:
        ca_file = (
            self.config.application.package_dir
            / "current/tls/active/edge-ca.crt"
        )
        if not ca_file.is_file():
            raise PreconditionError("generated edge CA is unavailable")
        return TLSClient(
            ca_file=str(ca_file),
            timeout=30,
            max_body=1024 * 1024,
            max_redirects=0,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        accepted_errors: frozenset[int] = frozenset(),
    ) -> tuple[int, Any, dict[str, str]]:
        body: bytes | None = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if form is not None:
            body = urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._tls_client().request(
                method,
                f"{self.base_url}{path}",
                body=body,
                headers=headers,
                accepted_statuses=(
                    frozenset({200, 201, 204}) | accepted_errors
                ),
                content_types=(),
            )
            raw = response.body.decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                if response.status in accepted_errors:
                    parsed = None
                else:
                    raise
            return response.status, parsed, dict(response.headers)
        except TLSClientError as exc:
            raise InstallerError("Keycloak Admin API is unavailable") from exc
        except json.JSONDecodeError as exc:
            raise InstallerError("Keycloak Admin API returned invalid JSON") from exc

    def wait_ready(self, attempts: int = 60) -> None:
        for _ in range(attempts):
            try:
                self._request("GET", f"/realms/{self.identity.realm}")
                return
            except InstallerError:
                time.sleep(5)
        raise InstallerError("Keycloak did not become ready before the installer timeout")

    def authenticate(self) -> None:
        client_secret = self.kube.get_secret_value(
            self.config.application.runtime_secret,
            "KEYCLOAK_SYNC_CLIENT_SECRET",
        ).strip()
        self.redactor.register(client_secret)
        _, payload, _ = self._request(
            "POST",
            f"/realms/{self.identity.realm}/protocol/openid-connect/token",
            form={
                "grant_type": "client_credentials",
                "client_id": "nomosmart-sync",
                "client_secret": client_secret,
            },
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise InstallerError("Keycloak service-account token response is invalid")
        self.redactor.register(token)
        self._token = token
        _, realm, _ = self._request(
            "GET", f"/admin/realms/{self.identity.realm}"
        )
        realm_id = realm.get("id") if isinstance(realm, dict) else None
        if not isinstance(realm_id, str) or not realm_id:
            raise InstallerError("Keycloak realm identity is invalid")
        self._realm_component_parent = realm_id

    def _components(self, component_type: str, *, parent: str | None = None) -> list[dict[str, Any]]:
        query = {"type": component_type}
        if parent:
            query["parent"] = parent
        _, payload, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/components?{urlencode(query)}",
        )
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise InstallerError("Keycloak component inventory is invalid")
        return payload

    @staticmethod
    def _value(config: dict[str, Any], key: str) -> str:
        value = config.get(key)
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value or "")

    @staticmethod
    def _vendor(mode: str) -> str:
        return {"freeipa": "rhds", "active-directory": "ad", "ldap": "other"}[mode]

    def _provider_payload(self, bind_credential: str) -> dict[str, Any]:
        item = self.identity
        if not self._realm_component_parent:
            raise InstallerError("Keycloak realm component identity is unavailable")
        return {
            "name": item.provider_name,
            "providerId": "ldap",
            "providerType": COMPONENT_TYPE,
            "parentId": self._realm_component_parent,
            "config": {
                "enabled": ["true"],
                "vendor": [self._vendor(item.mode)],
                "connectionUrl": [item.server_url],
                "usersDn": [item.users_dn],
                "bindDn": [item.bind_dn],
                "bindCredential": [bind_credential],
                "editMode": ["READ_ONLY"],
                "importEnabled": ["true"],
                "syncRegistrations": ["false"],
                "usernameLDAPAttribute": [item.username_attribute],
                "rdnLDAPAttribute": [item.rdn_attribute],
                "uuidLDAPAttribute": [item.uuid_attribute],
                "userObjectClasses": [",".join(item.user_object_classes)],
                "customUserSearchFilter": [item.custom_user_filter],
                "searchScope": [
                    "1" if item.user_search_scope == "one-level" else "2"
                ],
                "pagination": ["true"],
                "connectionPooling": ["true"],
                "useTruststoreSpi": ["ldapsOnly"],
                "batchSizeForSync": ["1000"],
                "fullSyncPeriod": ["-1"],
                "changedSyncPeriod": ["-1"],
            },
        }

    def _mapper_payload(self, provider_id: str) -> dict[str, Any]:
        item = self.identity
        return {
            "name": item.mapper_name,
            "providerId": "group-ldap-mapper",
            "providerType": MAPPER_TYPE,
            "parentId": provider_id,
            "config": {
                "groups.dn": [item.groups_dn],
                "group.name.ldap.attribute": [item.group_name_attribute],
                "group.object.classes": [",".join(item.group_object_classes)],
                "membership.ldap.attribute": [item.membership_attribute],
                "membership.attribute.type": [item.membership_attribute_type],
                "membership.user.ldap.attribute": [item.membership_user_attribute],
                "mode": ["READ_ONLY"],
                "groups.path": [item.group_path],
                "preserve.group.inheritance": [
                    str(item.preserve_group_inheritance).lower()
                ],
                "drop.non.existing.groups.during.sync": ["true"],
            },
        }

    def _directory_evidence(
        self, provider_id: str, mapper_id: str
    ) -> dict[str, str]:
        expected = {
            "identity_digest": self.config.identity_digest,
            "provider_id": provider_id,
            "provider_name": self.identity.provider_name,
            "mapper_id": mapper_id,
            "mapper_name": self.identity.mapper_name,
        }
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": self.evidence_name,
                "namespace": self.config.target.namespace,
                "labels": {OWNER_LABEL: self.config.target.release},
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
            "data": expected,
        }
        if self.kube.exists("configmap", self.evidence_name):
            existing = self.kube.json(
                "get",
                "configmap",
                self.evidence_name,
                namespace=True,
            )
            metadata = existing.get("metadata") or {}
            if (
                (metadata.get("labels") or {}).get(OWNER_LABEL)
                != self.config.target.release
                or (metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                != self.config.digest
                or existing.get("data") != expected
            ):
                raise DriftError(
                    "directory ownership evidence differs"
                )
            return expected
        self.kube.apply_object(manifest)
        return expected

    def _directory_data_quality(self) -> dict[str, Any]:
        if self.identity.mode != "ldap":
            return {
                "checked": False,
                "multi_valued_cn_count": 0,
                "warnings": [],
            }
        _, users, _ = self._request(
            "GET",
            (
                f"/admin/realms/{self.identity.realm}/users"
                "?briefRepresentation=false&first=0&max=1000"
            ),
        )
        if not isinstance(users, list):
            raise InstallerError(
                "Keycloak directory user inventory is invalid"
            )
        count = 0
        for user in users:
            attributes = (
                user.get("attributes")
                if isinstance(user, dict)
                else None
            )
            if not isinstance(attributes, dict):
                continue
            values: list[Any] = []
            for key, value in attributes.items():
                if str(key).casefold() == "cn" and isinstance(value, list):
                    values.extend(value)
            if len({str(value) for value in values if str(value)}) > 1:
                count += 1
        return {
            "checked": True,
            "visibility": "keycloak-imported-attributes",
            "multi_valued_cn_count": count,
            "warnings": (
                ["openldap-multi-valued-cn-detected"]
                if count
                else []
            ),
            "rule": {
                "login": "uid",
                "canonical_name": "single-cn",
                "display": "displayName",
            },
            "directory_write_performed": False,
        }

    def _verify_component(
        self,
        existing: dict[str, Any],
        expected: dict[str, Any],
        *,
        ignore_keys: frozenset[str] = frozenset(),
    ) -> None:
        if (
            existing.get("name") != expected["name"]
            or existing.get("providerId") != expected["providerId"]
            or existing.get("providerType") != expected["providerType"]
        ):
            raise DriftError("Keycloak directory component identity differs")
        actual_config = existing.get("config")
        if not isinstance(actual_config, dict):
            raise DriftError("Keycloak directory component config is invalid")
        expected_config = expected["config"]
        mismatches = [
            key
            for key in expected_config
            if key not in ignore_keys
            and self._value(actual_config, key) != self._value(expected_config, key)
        ]
        if mismatches:
            raise DriftError(
                "Keycloak directory component differs: " + ", ".join(sorted(mismatches))
            )

    def _create_component(self, payload: dict[str, Any]) -> None:
        self._request(
            "POST",
            f"/admin/realms/{self.identity.realm}/components",
            payload=payload,
        )

    def _ensure_group_path(self) -> dict[str, str]:
        segments = [
            segment
            for segment in self.identity.group_path.split("/")
            if segment
        ]
        if not segments:
            raise PreconditionError(
                "directory group path must contain a group name"
            )
        parent_id = ""
        current: list[str] = []
        for segment in segments:
            current.append(segment)
            encoded_path = "/".join(
                quote(item, safe="") for item in current
            )
            status, group, _ = self._request(
                "GET",
                (
                    f"/admin/realms/{self.identity.realm}/"
                    f"group-by-path/{encoded_path}"
                ),
                accepted_errors=frozenset({404}),
            )
            if status == 404:
                endpoint = (
                    f"/admin/realms/{self.identity.realm}/groups"
                    if not parent_id
                    else (
                        f"/admin/realms/{self.identity.realm}/groups/"
                        f"{parent_id}/children"
                    )
                )
                self._request(
                    "POST",
                    endpoint,
                    payload={"name": segment},
                )
                _, group, _ = self._request(
                    "GET",
                    (
                        f"/admin/realms/{self.identity.realm}/"
                        f"group-by-path/{encoded_path}"
                    ),
                )
            group_id = (
                str(group.get("id") or "")
                if isinstance(group, dict)
                else ""
            )
            if not group_id:
                raise InstallerError(
                    "Keycloak directory group path has no stable id"
                )
            parent_id = group_id
        return {
            "path": "/" + "/".join(segments),
            "group_id": parent_id,
        }

    def _update_component(
        self, component_id: str, payload: dict[str, Any]
    ) -> None:
        representation = dict(payload)
        representation["id"] = component_id
        self._request(
            "PUT",
            (
                f"/admin/realms/{self.identity.realm}/components/"
                f"{component_id}"
            ),
            payload=representation,
        )

    def _ensure_admin_password_only(self) -> dict[str, Any]:
        query = urlencode(
            {
                "username": self.identity.admin_username,
                "exact": "true",
            }
        )
        _, users, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/users?{query}",
        )
        if not isinstance(users, list) or len(users) != 1:
            raise PreconditionError(
                "designated federated administrator is unavailable after sync"
            )
        user = users[0]
        user_id = str(user.get("id") or "")
        if (
            not user_id
            or not user.get("federationLink")
            or not bool(user.get("enabled", False))
        ):
            raise PreconditionError(
                "designated administrator is not an active federated user"
            )
        original_actions = [str(item) for item in (user.get("requiredActions") or []) if item]
        actions = [item for item in original_actions if item != "CONFIGURE_TOTP"]
        needs_update = actions != original_actions
        if needs_update:
            representation = dict(user)
            representation["requiredActions"] = actions
            self._request(
                "PUT",
                (
                    f"/admin/realms/{self.identity.realm}/users/"
                    f"{user_id}"
                ),
                payload=representation,
            )
        return {
            "username": self.identity.admin_username,
            "federated": True,
            "authentication": "password_only",
            "updated": needs_update,
        }

    def configure(self) -> dict[str, Any]:
        self.wait_ready()
        self.authenticate()
        provider_rows = [
            row
            for row in self._components(COMPONENT_TYPE)
            if row.get("providerId") == "ldap"
        ]
        bind_credential = ""
        if self.identity.mode != "preconfigured":
            bind_credential = self.kube.get_secret_value(
                self.identity.bind_secret_name,
                self.identity.bind_secret_key,
            ).strip()
            if not bind_credential:
                raise PreconditionError("directory bind credential is empty")
            self.redactor.register(bind_credential)
        if not provider_rows:
            if self.identity.mode == "preconfigured":
                raise PreconditionError("preconfigured identity mode requires one LDAP provider")
            self._create_component(self._provider_payload(bind_credential))
            provider_rows = [
                row
                for row in self._components(COMPONENT_TYPE)
                if row.get("providerId") == "ldap"
            ]
        if len(provider_rows) != 1:
            raise DriftError("exactly one Keycloak LDAP provider is required")
        provider = provider_rows[0]
        if str(provider.get("name") or "") != self.identity.provider_name:
            raise DriftError("Keycloak LDAP provider name differs")
        provider_id = str(provider.get("id") or "")
        if not provider_id:
            raise InstallerError("Keycloak LDAP provider has no id")
        if self.identity.mode != "preconfigured":
            provider_payload = self._provider_payload(bind_credential)
            self._verify_component(
                provider,
                provider_payload,
                ignore_keys=frozenset({"bindCredential"}),
            )
            self._update_component(provider_id, provider_payload)
            refreshed = [
                row
                for row in self._components(COMPONENT_TYPE)
                if row.get("id") == provider_id
            ]
            if len(refreshed) != 1:
                raise InstallerError(
                    "updated Keycloak LDAP provider cannot be verified"
                )
            self._verify_component(
                refreshed[0],
                provider_payload,
                ignore_keys=frozenset({"bindCredential"}),
            )
        group_path_evidence = self._ensure_group_path()
        mapper_rows = [
            row
            for row in self._components(MAPPER_TYPE, parent=provider_id)
            if row.get("providerId") == "group-ldap-mapper"
        ]
        if not mapper_rows:
            if self.identity.mode == "preconfigured":
                raise PreconditionError(
                    "preconfigured identity mode requires one LDAP group mapper"
                )
            self._create_component(self._mapper_payload(provider_id))
            mapper_rows = [
                row
                for row in self._components(MAPPER_TYPE, parent=provider_id)
                if row.get("providerId") == "group-ldap-mapper"
            ]
        if len(mapper_rows) != 1:
            raise DriftError("exactly one Keycloak LDAP group mapper is required")
        if self.identity.mode == "preconfigured":
            mapper = mapper_rows[0]
            config = mapper.get("config")
            if (
                mapper.get("name") != self.identity.mapper_name
                or not isinstance(config, dict)
                or self._value(config, "groups.path").rstrip("/")
                != self.identity.group_path.rstrip("/")
            ):
                raise DriftError(
                    "preconfigured Keycloak LDAP group mapper differs"
                )
        else:
            self._verify_component(
                mapper_rows[0], self._mapper_payload(provider_id)
            )
        _, sync, _ = self._request(
            "POST",
            f"/admin/realms/{self.identity.realm}/user-storage/{provider_id}/sync?action=triggerFullSync",
        )
        sync_summary = {
            key: int(value)
            for key, value in (sync.items() if isinstance(sync, dict) else ())
            if key in {"added", "updated", "removed", "failed"} and str(value).isdigit()
        }
        if sync_summary.get("failed", 0) != 0:
            raise InstallerError("Keycloak directory full sync reported failures")
        data_quality = self._directory_data_quality()
        admin_password_only = self._ensure_admin_password_only()
        mapper_id = str(mapper_rows[0].get("id") or "")
        if not mapper_id:
            raise InstallerError("Keycloak LDAP group mapper has no id")
        self._directory_evidence(provider_id, mapper_id)
        return {
            "provider_id": provider_id,
            "provider_name": self.identity.provider_name,
            "mapper_id": mapper_id,
            "group_path": self.identity.group_path,
            "group_path_id": group_path_evidence["group_id"],
            "full_sync": sync_summary,
            "data_quality": data_quality,
            "admin_authentication": admin_password_only,
        }

    def verify_provider(self) -> dict[str, Any]:
        self.wait_ready()
        self.authenticate()
        providers = [
            row
            for row in self._components(COMPONENT_TYPE)
            if row.get("providerId") == "ldap"
        ]
        if len(providers) != 1:
            raise DriftError("exactly one Keycloak LDAP provider is required")
        if str(providers[0].get("name") or "") != self.identity.provider_name:
            raise DriftError("Keycloak LDAP provider name differs")
        provider_id = str(providers[0].get("id") or "")
        mappers = [
            row
            for row in self._components(MAPPER_TYPE, parent=provider_id)
            if row.get("providerId") == "group-ldap-mapper"
        ]
        if len(mappers) != 1:
            raise DriftError("exactly one Keycloak LDAP group mapper is required")
        if str(mappers[0].get("name") or "") != self.identity.mapper_name:
            raise DriftError("Keycloak LDAP group mapper name differs")
        mapper_config = mappers[0].get("config")
        actual_path = (
            self._value(mapper_config, "groups.path")
            if isinstance(mapper_config, dict)
            else ""
        )
        if actual_path.rstrip("/") != self.identity.group_path.rstrip("/"):
            raise DriftError("Keycloak LDAP group mapper path differs")
        mapper_id = str(mappers[0].get("id") or "")
        self._directory_evidence(provider_id, mapper_id)
        return {
            "provider_id": provider_id,
            "provider_name": str(providers[0].get("name") or ""),
            "mapper_id": mapper_id,
            "group_path": actual_path,
        }

    def verify_identity_checkpoint(self) -> dict[str, Any]:
        self.wait_ready()
        self.authenticate()
        query = urlencode(
            {"username": self.identity.admin_username, "exact": "true"}
        )
        _, users, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/users?{query}",
        )
        if not isinstance(users, list) or len(users) != 1:
            raise PreconditionError(
                "designated federated administrator has not completed directory login"
            )
        user = users[0]
        user_id = str(user.get("id") or "")
        if (
            not user_id
            or not user.get("federationLink")
            or not bool(user.get("enabled", False))
            or user.get("requiredActions")
        ):
            raise PreconditionError(
                "designated federated administrator onboarding is incomplete"
            )
        _, groups, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/users/{user_id}/groups",
        )
        if not isinstance(groups, list) or not any(
            str(group.get("name") or "").casefold()
            == self.identity.external_group_name.casefold()
            or str(group.get("path") or "").rstrip("/").casefold().endswith(
                f"/{self.identity.external_group_name}".casefold()
            )
            for group in groups
            if isinstance(group, dict)
        ):
            raise PreconditionError(
                "designated federated administrator group evidence is incomplete"
            )
        return {
            "admin_username": self.identity.admin_username,
            "federated": True,
            "required_actions_complete": True,
            "authentication": "password_only",
            "external_group": self.identity.external_group_name,
        }

    def verify_break_glass_checkpoint(
        self,
        *,
        allow_disabled: bool = False,
    ) -> dict[str, Any]:
        self.wait_ready()
        self.authenticate()
        query = urlencode({"username": "nomosmart", "exact": "true"})
        _, users, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/users?{query}",
        )
        if not isinstance(users, list) or len(users) != 1:
            raise PreconditionError("break-glass account is unavailable")
        user = users[0]
        user_id = str(user.get("id") or "")
        if (
            not user_id
            or user.get("federationLink")
            or (
                not bool(user.get("enabled", False))
                and not allow_disabled
            )
            or user.get("requiredActions")
        ):
            raise PreconditionError("break-glass first-use actions are incomplete")
        _, groups, _ = self._request(
            "GET",
            f"/admin/realms/{self.identity.realm}/users/{user_id}/groups",
        )
        if not isinstance(groups, list) or not any(
            isinstance(group, dict)
            and str(group.get("name") or "") == "system-admin"
            for group in groups
        ):
            raise PreconditionError("break-glass System Admin mapping is incomplete")
        return {
            "username": "nomosmart",
            "local_account": True,
            "enabled": bool(user.get("enabled", False)),
            "required_actions_complete": True,
            "authentication": "password_only",
            "system_admin_group": True,
        }

    def verify_application_onboarding(
        self,
        *,
        allow_disabled_break_glass: bool = False,
    ) -> dict[str, Any]:
        selector = (
            f"app.kubernetes.io/instance={self.config.target.release},"
            "app.kubernetes.io/component=backend"
        )
        pods = self.kube.json(
            "get", "pods", "-l", selector, namespace=True
        ).get("items") or []
        ready = [
            row
            for row in pods
            if str((row.get("status") or {}).get("phase") or "") == "Running"
            and any(
                condition.get("type") == "Ready"
                and condition.get("status") == "True"
                for condition in (row.get("status") or {}).get("conditions") or []
            )
        ]
        if not ready:
            raise PreconditionError(
                "no Ready Backend Pod is available for onboarding evidence"
            )
        pod_name = str((ready[0].get("metadata") or {}).get("name") or "")
        result = self.kube.run(
            "exec",
            pod_name,
            "--",
            "python",
            "-c",
            onboarding_status_probe_script(
                allow_disabled_break_glass=(
                    allow_disabled_break_glass
                )
            ),
            namespace=True,
            accepted=frozenset({0, 1}),
        )
        if result.returncode != 0:
            safe_code = "onboarding_evidence_incomplete"
            try:
                error_payload = json.loads(result.stderr)
                candidate = str(error_payload.get("code") or "")
                if (
                    candidate
                    and len(candidate) <= 100
                    and all(
                        character.islower()
                        or character.isdigit()
                        or character == "_"
                        for character in candidate
                    )
                ):
                    safe_code = candidate
            except (AttributeError, json.JSONDecodeError):
                pass
            raise PreconditionError(
                "NomoSmart OIDC password login and role evidence is incomplete: "
                f"{safe_code}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InstallerError(
                "NomoSmart onboarding status returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "ready":
            raise PreconditionError(
                "NomoSmart onboarding status is not ready"
            )
        return payload

    def reconcile_application_mapping(self) -> dict[str, Any]:
        base_name = self._mapping_base_name()
        fullname = (
            self.config.target.release
            if "nomosmart" in self.config.target.release
            else f"{self.config.target.release}-nomosmart"
        )[:63].rstrip("-")
        jobs = self._mapping_jobs()
        for existing in jobs:
            name = str((existing.get("metadata") or {}).get("name") or "")
            self._validate_mapping_job(name, existing)
        completed = [
            row
            for row in jobs
            if int((row.get("status") or {}).get("succeeded") or 0) == 1
        ]
        if completed:
            if len(completed) != 1:
                raise DriftError(
                    "multiple successful directory reconciliation Jobs exist"
                )
            return self.verify_application_mapping()
        pending = [
            row
            for row in jobs
            if int((row.get("status") or {}).get("succeeded") or 0) == 0
            and int((row.get("status") or {}).get("failed") or 0) == 0
        ]
        if len(pending) > 1:
            raise DriftError(
                "multiple pending directory reconciliation Jobs exist"
            )
        if pending:
            name = str((pending[0].get("metadata") or {}).get("name") or "")
        else:
            attempt = len(jobs) + 1
            if attempt == 1:
                name = base_name[:63].rstrip("-")
            else:
                suffix = f"-r{attempt}"
                name = (
                    f"{base_name[:63 - len(suffix)].rstrip('-')}{suffix}"
                )
            manifest = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "name": name,
                    "namespace": self.config.target.namespace,
                    "labels": {
                        OWNER_LABEL: self.config.target.release,
                        "app.kubernetes.io/name": "nomosmart",
                        "app.kubernetes.io/instance": self.config.target.release,
                        "app.kubernetes.io/component": "deployment-bootstrap",
                        "nomosmart.io/installer-action": "directory-reconcile",
                    },
                    "annotations": {CONFIG_ANNOTATION: self.config.digest},
                },
                "spec": {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 900,
                    "template": {
                        "metadata": {
                            "labels": {
                                "app.kubernetes.io/name": "nomosmart",
                                "app.kubernetes.io/instance": self.config.target.release,
                                "app.kubernetes.io/component": "deployment-bootstrap",
                                "nomosmart.io/installer-action": "directory-reconcile",
                            }
                        },
                        "spec": {
                            "restartPolicy": "Never",
                            "serviceAccountName": fullname,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "runAsGroup": 10001,
                                "fsGroup": 10001,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": "directory-reconcile",
                                    "image": self.config.images.backend,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": [
                                        "python",
                                        "-m",
                                        "app.deployment.directory_reconcile",
                                    ],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "envFrom": [
                                        {"configMapRef": {"name": f"{fullname}-config"}},
                                        {
                                            "secretRef": {
                                                "name": self.config.application.runtime_secret
                                            }
                                        },
                                    ],
                                }
                            ],
                        },
                    },
                },
            }
            self.kube.apply_object(manifest)
        self.kube.wait_job_terminal(name, timeout=900)
        return self.verify_application_mapping()

    def _validate_mapping_job(
        self, name: str, payload: dict[str, Any]
    ) -> None:
        metadata = payload.get("metadata") or {}
        spec = payload.get("spec") or {}
        template = spec.get("template") or {}
        template_metadata = template.get("metadata") or {}
        template_spec = template.get("spec") or {}
        containers = template_spec.get("containers") or []
        fullname = (
            self.config.target.release
            if "nomosmart" in self.config.target.release
            else f"{self.config.target.release}-nomosmart"
        )[:63].rstrip("-")
        expected_env_from = [
            {"configMapRef": {"name": f"{fullname}-config"}},
            {
                "secretRef": {
                    "name": self.config.application.runtime_secret
                }
            },
        ]
        base_name = self._mapping_base_name()
        retry = name.removeprefix(f"{base_name}-r")
        if (
            not (
                name == base_name
                or (
                    retry != name
                    and retry.isdigit()
                    and int(retry) >= 2
                )
            )
            or (metadata.get("labels") or {}).get(OWNER_LABEL)
            != self.config.target.release
            or (metadata.get("labels") or {}).get(
                "nomosmart.io/installer-action"
            )
            != "directory-reconcile"
            or (metadata.get("annotations") or {}).get(CONFIG_ANNOTATION)
            != self.config.digest
            or len(containers) != 1
            or containers[0].get("image") != self.config.images.backend
            or containers[0].get("command")
            != ["python", "-m", "app.deployment.directory_reconcile"]
            or containers[0].get("envFrom") != expected_env_from
            or containers[0].get("securityContext")
            != {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
            }
            or spec.get("backoffLimit") != 0
            or spec.get("activeDeadlineSeconds") != 900
            or template_spec.get("restartPolicy") != "Never"
            or template_spec.get("serviceAccountName") != fullname
            or (
                template_metadata.get("labels") or {}
            ).get("nomosmart.io/installer-action")
            != "directory-reconcile"
        ):
            raise DriftError(
                f"job/{name} differs from the owned reconciliation definition"
            )

    def _mapping_base_name(self) -> str:
        release = self.config.target.release[:37].rstrip("-")
        return (
            f"{release}-directory-{self.config.identity_digest[:8]}"
        )

    def _mapping_jobs(self) -> list[dict[str, Any]]:
        selector = (
            f"app.kubernetes.io/instance={self.config.target.release},"
            "nomosmart.io/installer-action=directory-reconcile"
        )
        rows = self.kube.json(
            "get", "jobs", "-l", selector, namespace=True
        ).get("items") or []
        if not all(isinstance(row, dict) for row in rows):
            raise InstallerError(
                "directory reconciliation Job inventory is invalid"
            )
        return sorted(
            rows,
            key=lambda row: str(
                (row.get("metadata") or {}).get("creationTimestamp") or ""
            ),
        )

    def verify_application_mapping(self) -> dict[str, Any]:
        jobs = self._mapping_jobs()
        completed: list[dict[str, Any]] = []
        for payload in jobs:
            name = str((payload.get("metadata") or {}).get("name") or "")
            self._validate_mapping_job(name, payload)
            if int((payload.get("status") or {}).get("succeeded") or 0) == 1:
                completed.append(payload)
        if not completed:
            raise PreconditionError(
                "directory reconciliation Job evidence is missing"
            )
        if len(completed) != 1:
            raise DriftError(
                "multiple successful directory reconciliation Jobs exist"
            )
        payload = completed[0]
        name = str((payload.get("metadata") or {}).get("name") or "")
        succeeded = 1
        return {"job": name, "succeeded": succeeded}

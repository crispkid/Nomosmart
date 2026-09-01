from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import hmac
import json
from typing import Any
from urllib.parse import quote

import httpx

from app.core.errors import AppError


NOMOSMART_LOGIN_THEME = "nomosmart"
NOMOSMART_SUPPORTED_LOCALES = frozenset({"zh-TW", "en"})
NOMOSMART_DEFAULT_LOCALE = "zh-TW"
NOMOSMART_BROWSER_FLOW = "nomosmart-browser-password-only"
BREAK_GLASS_DEFAULT_EMAIL = "nomosmart@nomosmart.local"
BREAK_GLASS_DEFAULT_FIRST_NAME = "NomoSmart"
BREAK_GLASS_DEFAULT_LAST_NAME = "Administrator"


def nomosmart_realm_theme_settings() -> dict[str, object]:
    return {
        "loginTheme": NOMOSMART_LOGIN_THEME,
        "internationalizationEnabled": True,
        "supportedLocales": sorted(NOMOSMART_SUPPORTED_LOCALES),
        "defaultLocale": NOMOSMART_DEFAULT_LOCALE,
    }


def nomosmart_realm_theme_ready(payload: dict[str, Any]) -> bool:
    supported = payload.get("supportedLocales")
    return (
        payload.get("loginTheme") == NOMOSMART_LOGIN_THEME
        and payload.get("internationalizationEnabled") is True
        and isinstance(supported, list)
        and {str(locale) for locale in supported} == NOMOSMART_SUPPORTED_LOCALES
        and payload.get("defaultLocale") == NOMOSMART_DEFAULT_LOCALE
    )


@dataclass(frozen=True)
class KeycloakSnapshot:
    users: tuple[dict[str, Any], ...]
    groups: tuple[dict[str, Any], ...]
    user_group_ids: dict[str, frozenset[str]]


@dataclass(frozen=True)
class KeycloakBreakGlassStatus:
    username: str
    configured: bool
    status: str
    detail_code: str
    enabled: bool | None
    local_account: bool | None
    system_admin_mapped: bool | None
    credential_update_required: bool | None
    required_actions: tuple[str, ...]
    credential_source: str = "deployment_secret"


@dataclass(frozen=True)
class KeycloakDirectoryProvider:
    id: str
    name: str
    vendor: str
    enabled: bool
    custom_user_search_filter: str
    config_hash: str
    checked_at: datetime


@dataclass(frozen=True)
class KeycloakDirectoryMapper:
    id: str
    name: str
    groups_path: str


@dataclass(frozen=True)
class KeycloakDirectoryUserSyncResult:
    added: int
    updated: int
    removed: int
    failed: int
    ignored: bool


class KeycloakAdminClient:
    """Service-account client used by identity synchronization."""

    def __init__(self, *, base_url: str, realm: str, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def _access_token(self, client: httpx.Client) -> str:
        response = client.post(
            f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret},
        )
        if response.status_code >= 400:
            raise AppError("keycloak_auth_failed", "Keycloak service-account authentication failed", status_code=502, details={"status_code": response.status_code})
        try:
            token = response.json().get("access_token")
        except ValueError as exc:
            raise AppError("keycloak_invalid_response", "Keycloak token response was invalid", status_code=502) from exc
        if not isinstance(token, str) or not token:
            raise AppError("keycloak_invalid_response", "Keycloak token response was invalid", status_code=502)
        return token

    def _request_list(self, client: httpx.Client, token: str, resource: str, *, params: dict[str, int | str | bool] | None = None) -> list[dict[str, Any]]:
        response = client.get(f"{self.base_url}/admin/realms/{self.realm}/{resource}", headers={"Authorization": f"Bearer {token}"}, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise AppError("keycloak_invalid_response", "Keycloak Admin API response was invalid", status_code=502)
        return payload

    def _request_empty(self, client: httpx.Client, token: str, method: str, resource: str, *, json: dict[str, Any] | None = None) -> httpx.Response:
        response = client.request(method, f"{self.base_url}/admin/realms/{self.realm}/{resource}", headers={"Authorization": f"Bearer {token}"}, json=json)
        response.raise_for_status()
        return response

    def _request_object(self, client: httpx.Client, token: str, resource: str) -> dict[str, Any]:
        response = client.get(f"{self.base_url}/admin/realms/{self.realm}/{resource}", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AppError("keycloak_invalid_response", "Keycloak Admin API response was invalid", status_code=502)
        return payload

    @staticmethod
    def _config_value(config: dict[str, Any], key: str) -> str:
        value = config.get(key)
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value or "")

    @staticmethod
    def _component_hash(component: dict[str, Any], concurrency_key: bytes) -> str:
        canonical = json.dumps(component, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hmac.new(concurrency_key, canonical, sha256).hexdigest()

    def _directory_provider(self, component: dict[str, Any], concurrency_key: bytes) -> KeycloakDirectoryProvider:
        provider_id = component.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise AppError("keycloak_invalid_response", "Keycloak directory provider is missing an id", status_code=502)
        config = component.get("config") if isinstance(component.get("config"), dict) else {}
        return KeycloakDirectoryProvider(
            id=provider_id,
            name=str(component.get("name") or provider_id),
            vendor=self._config_value(config, "vendor") or "ldap",
            enabled=self._config_value(config, "enabled").lower() != "false",
            custom_user_search_filter=self._config_value(config, "customUserSearchFilter"),
            config_hash=self._component_hash(component, concurrency_key),
            checked_at=datetime.now(UTC),
        )

    def list_directory_providers(self, *, concurrency_key: bytes) -> list[KeycloakDirectoryProvider]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                rows = self._request_list(
                    client,
                    token,
                    "components",
                    params={"type": "org.keycloak.storage.UserStorageProvider"},
                )
                providers = [
                    self._directory_provider(row, concurrency_key)
                    for row in rows
                    if row.get("providerId") == "ldap"
                ]
                provider_ids = [provider.id for provider in providers]
                if len(provider_ids) != len(set(provider_ids)):
                    raise AppError("keycloak_invalid_response", "Keycloak returned duplicate directory providers", status_code=502)
                return sorted(providers, key=lambda provider: provider.name.lower())
        except AppError:
            raise
        except httpx.TimeoutException as exc:
            raise AppError("keycloak_provider_timeout", "Keycloak directory provider operation timed out", status_code=504) from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    @staticmethod
    def _safe_component_id(component_id: str) -> str:
        if not component_id or len(component_id) > 255:
            raise AppError("keycloak_invalid_response", "Keycloak component id was invalid", status_code=502)
        return quote(component_id, safe="")

    @staticmethod
    def _sync_counter(payload: dict[str, Any], key: str) -> int:
        raw = payload.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise AppError("keycloak_invalid_response", "Keycloak synchronization response was invalid", status_code=502)
        if raw < 0:
            raise AppError("keycloak_invalid_response", "Keycloak synchronization response was invalid", status_code=502)
        return raw

    @staticmethod
    def _sync_boolean(payload: dict[str, Any], key: str) -> bool:
        raw = payload.get(key)
        if not isinstance(raw, bool):
            raise AppError("keycloak_invalid_response", "Keycloak synchronization response was invalid", status_code=502)
        return raw

    @classmethod
    def _directory_user_sync_result(cls, payload: Any) -> KeycloakDirectoryUserSyncResult:
        if not isinstance(payload, dict):
            raise AppError("keycloak_invalid_response", "Keycloak synchronization response was invalid", status_code=502)
        return KeycloakDirectoryUserSyncResult(
            added=cls._sync_counter(payload, "added"),
            updated=cls._sync_counter(payload, "updated"),
            removed=cls._sync_counter(payload, "removed"),
            failed=cls._sync_counter(payload, "failed"),
            ignored=cls._sync_boolean(payload, "ignored"),
        )

    def list_directory_group_mappers(self, provider_id: str) -> list[KeycloakDirectoryMapper]:
        self._safe_component_id(provider_id)
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                rows = self._request_list(
                    client,
                    token,
                    "components",
                    params={
                        "parent": provider_id,
                        "type": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
                    },
                )
                mappers: list[KeycloakDirectoryMapper] = []
                for row in rows:
                    if row.get("providerId") != "group-ldap-mapper":
                        continue
                    mapper_id = row.get("id")
                    if not isinstance(mapper_id, str) or not mapper_id:
                        raise AppError("keycloak_invalid_response", "Keycloak directory mapper is missing an id", status_code=502)
                    config = row.get("config") if isinstance(row.get("config"), dict) else {}
                    groups_path = self._config_value(config, "groups.path").rstrip("/") or "/"
                    mappers.append(KeycloakDirectoryMapper(id=mapper_id, name=str(row.get("name") or mapper_id), groups_path=groups_path))
                return sorted(mappers, key=lambda mapper: mapper.id)
        except AppError:
            raise
        except httpx.TimeoutException as exc:
            raise AppError("keycloak_provider_timeout", "Keycloak directory provider operation timed out", status_code=504) from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def trigger_directory_user_sync(self, provider_id: str) -> KeycloakDirectoryUserSyncResult:
        safe_provider_id = self._safe_component_id(provider_id)
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                response = client.post(
                    f"{self.base_url}/admin/realms/{self.realm}/user-storage/{safe_provider_id}/sync",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"action": "triggerFullSync"},
                )
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise AppError("keycloak_invalid_response", "Keycloak synchronization response was invalid", status_code=502) from exc
                return self._directory_user_sync_result(payload)
        except AppError:
            raise
        except httpx.TimeoutException as exc:
            raise AppError("keycloak_provider_timeout", "Keycloak directory provider operation timed out", status_code=504) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError("keycloak_provider_sync_failed", "Keycloak directory user synchronization failed", status_code=502) from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def trigger_directory_group_sync(self, provider_id: str, mapper_id: str) -> None:
        safe_provider_id = self._safe_component_id(provider_id)
        safe_mapper_id = self._safe_component_id(mapper_id)
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                response = client.post(
                    f"{self.base_url}/admin/realms/{self.realm}/user-storage/{safe_provider_id}/mappers/{safe_mapper_id}/sync",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"direction": "fedToKeycloak"},
                )
                response.raise_for_status()
        except AppError:
            raise
        except httpx.TimeoutException as exc:
            raise AppError("keycloak_provider_timeout", "Keycloak directory provider operation timed out", status_code=504) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError("keycloak_group_mapper_sync_failed", "Keycloak directory group synchronization failed", status_code=502) from exc
        except httpx.HTTPError as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def update_directory_provider_filter(
        self,
        provider_id: str,
        *,
        custom_user_search_filter: str,
        expected_config_hash: str,
        concurrency_key: bytes,
    ) -> tuple[KeycloakDirectoryProvider, str]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                component = self._request_object(client, token, f"components/{provider_id}")
                if component.get("providerId") != "ldap":
                    raise AppError("directory_provider_not_found", "Directory provider was not found", status_code=404)
                current_hash = self._component_hash(component, concurrency_key)
                if not hmac.compare_digest(current_hash, expected_config_hash):
                    raise AppError(
                        "directory_provider_conflict",
                        "Directory provider changed; reload before saving",
                        status_code=409,
                        details={"provider_id": provider_id},
                    )
                config = dict(component.get("config") or {})
                old_filter = self._config_value(config, "customUserSearchFilter")
                config["customUserSearchFilter"] = [custom_user_search_filter]
                updated_component = dict(component)
                updated_component["config"] = config
                self._request_empty(client, token, "PUT", f"components/{provider_id}", json=updated_component)
                read_back = self._request_object(client, token, f"components/{provider_id}")
                provider = self._directory_provider(read_back, concurrency_key)
                if provider.custom_user_search_filter != custom_user_search_filter:
                    raise AppError("directory_provider_readback_failed", "Directory provider update could not be verified", status_code=502)
                return provider, old_filter
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def _find_user_by_username(self, client: httpx.Client, token: str, username: str) -> dict[str, Any] | None:
        rows = self._request_list(client, token, "users", params={"username": username, "exact": "true", "max": 2})
        matches = [row for row in rows if str(row.get("username") or "").lower() == username.lower()]
        if len(matches) > 1:
            raise AppError("keycloak_invalid_response", "Keycloak returned duplicate break-glass users", status_code=502)
        return matches[0] if matches else None

    def _find_group(self, groups: list[dict[str, Any]], group_name_or_path: str) -> dict[str, Any] | None:
        normalized = group_name_or_path.strip().lower()
        if not normalized:
            return None
        for group in groups:
            name = str(group.get("name") or "").lower()
            path = str(group.get("path") or "").lower().strip("/")
            if normalized.strip("/") in {name, path}:
                return group
        return None

    def _user_group_mapped(self, groups: list[dict[str, Any]], group_name_or_path: str) -> bool:
        return self._find_group(groups, group_name_or_path) is not None

    def _all_pages(self, client: httpx.Client, token: str, resource: str, *, page_size: int = 100) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        first = 0
        while True:
            page = self._request_list(client, token, resource, params={"first": first, "max": page_size})
            collected.extend(page)
            if len(page) < page_size:
                return collected
            first += len(page)

    def _flatten_groups(self, roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []

        def visit(group: dict[str, Any], parent_path: str = "") -> None:
            item = dict(group)
            children = item.pop("subGroups", []) or []
            name = str(item.get("name") or "")
            item["path"] = item.get("path") or f"{parent_path}/{name}"
            flattened.append(item)
            for child in children:
                if isinstance(child, dict):
                    visit(child, str(item["path"]))

        for root in roots:
            visit(root)
        return flattened

    def snapshot(self, *, page_size: int = 100) -> KeycloakSnapshot:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                users = self._all_pages(client, token, "users", page_size=page_size)
                groups = self._flatten_groups(self._all_pages(client, token, "groups", page_size=page_size))
                memberships: dict[str, frozenset[str]] = {}
                for user in users:
                    user_id = user.get("id")
                    if not isinstance(user_id, str) or not user_id:
                        raise AppError("keycloak_invalid_response", "Keycloak user is missing an id", status_code=502)
                    rows = self._request_list(client, token, f"users/{user_id}/groups")
                    memberships[user_id] = frozenset(str(row["id"]) for row in rows if row.get("id"))
                known_group_ids = {str(group.get("id")) for group in groups}
                referenced_group_ids = set().union(*memberships.values()) if memberships else set()
                for group_id in sorted(referenced_group_ids - known_group_ids):
                    groups.append(self._request_object(client, token, f"groups/{group_id}"))
                return KeycloakSnapshot(tuple(users), tuple(groups), memberships)
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def list_users(self) -> list[dict[str, Any]]:
        return list(self.snapshot().users)

    def list_groups(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                return self._flatten_groups(self._all_pages(client, self._access_token(client), "groups"))
        except AppError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def verify_ldap_group_mapper_path(self, expected_path: str) -> dict[str, str]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                providers = self._request_list(
                    client,
                    token,
                    "components",
                    params={"type": "org.keycloak.storage.UserStorageProvider"},
                )
                normalized_expected = expected_path.rstrip("/") or "/"
                enabled_providers = []
                for row in providers:
                    if row.get("providerId") != "ldap" or not row.get("id"):
                        continue
                    config = row.get("config") if isinstance(row.get("config"), dict) else {}
                    if self._config_value(config, "enabled").lower() == "false":
                        continue
                    enabled_providers.append(row)
                if not enabled_providers:
                    raise AppError("keycloak_ldap_provider_invalid", "At least one enabled LDAP user storage provider is required", status_code=422)
                mapper_ids: list[str] = []
                for provider in sorted(enabled_providers, key=lambda row: str(row["id"])):
                    rows = self._request_list(
                        client,
                        token,
                        "components",
                        params={
                            "parent": str(provider["id"]),
                            "type": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
                        },
                    )
                    group_mappers = [row for row in rows if row.get("providerId") == "group-ldap-mapper"]
                    if len(group_mappers) != 1:
                        raise AppError("keycloak_ldap_group_mapper_invalid", "Each enabled LDAP provider requires exactly one group mapper", status_code=422)
                    mapper = group_mappers[0]
                    config = mapper.get("config") if isinstance(mapper.get("config"), dict) else {}
                    actual_path = self._config_value(config, "groups.path").rstrip("/") or "/"
                    if actual_path != normalized_expected:
                        raise AppError("keycloak_ldap_group_path_mismatch", "Keycloak LDAP group mapper path does not match deployment configuration", status_code=422)
                    mapper_id = mapper.get("id")
                    if not isinstance(mapper_id, str) or not mapper_id:
                        raise AppError("keycloak_invalid_response", "Keycloak directory mapper is missing an id", status_code=502)
                    mapper_ids.append(mapper_id)
                return {
                    "mapper_id": mapper_ids[0],
                    "groups_path": normalized_expected,
                    "provider_count": str(len(enabled_providers)),
                }
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def verify_initialization_resources(
        self,
        *,
        frontend_client_id: str,
        confidential_client_ids: tuple[str, ...],
        audience: str,
        frontend_origin: str,
        system_admin_group: str,
    ) -> dict[str, object]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                realm_response = client.get(
                    f"{self.base_url}/admin/realms/{self.realm}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                realm_response.raise_for_status()
                realm_representation = realm_response.json()
                if not isinstance(realm_representation, dict):
                    raise AppError("keycloak_invalid_response", "Keycloak realm response was invalid", status_code=502)
                if not nomosmart_realm_theme_ready(realm_representation):
                    raise AppError(
                        "keycloak_realm_theme_incompatible",
                        "Required Keycloak realm Theme or locale settings are missing",
                        status_code=422,
                    )
                if realm_representation.get("browserFlow") != NOMOSMART_BROWSER_FLOW:
                    raise AppError(
                        "keycloak_password_only_flow_incompatible",
                        "Required Keycloak password-only Browser Flow is not active",
                        status_code=422,
                    )
                verified_clients: list[str] = [frontend_client_id]
                frontend_rows = self._request_list(client, token, "clients", params={"clientId": frontend_client_id, "max": 2})
                frontend_matches = [row for row in frontend_rows if str(row.get("clientId") or "") == frontend_client_id]
                if len(frontend_matches) != 1 or not isinstance(frontend_matches[0].get("id"), str):
                    raise AppError("keycloak_client_missing", "Required Keycloak frontend client is missing", status_code=422)
                frontend = frontend_matches[0]
                attributes = frontend.get("attributes") if isinstance(frontend.get("attributes"), dict) else {}
                redirect_uris = {str(value) for value in frontend.get("redirectUris", []) if value}
                web_origins = {str(value) for value in frontend.get("webOrigins", []) if value}
                origin = frontend_origin.rstrip("/")
                if (
                    not frontend.get("enabled")
                    or not frontend.get("publicClient")
                    or not frontend.get("standardFlowEnabled")
                    or frontend.get("directAccessGrantsEnabled")
                    or attributes.get("pkce.code.challenge.method") != "S256"
                    or f"{origin}/auth/callback" not in redirect_uris
                    or f"{origin}/api/backend/system/identity-settings/reauth/callback" not in redirect_uris
                    or origin not in web_origins
                ):
                    raise AppError("keycloak_client_incompatible", "Keycloak frontend client is incompatible", status_code=422)
                mappers = self._request_list(
                    client,
                    token,
                    f"clients/{frontend['id']}/protocol-mappers/models",
                )
                audience_ready = any(
                    row.get("protocolMapper") == "oidc-audience-mapper"
                    and isinstance(row.get("config"), dict)
                    and row["config"].get("included.client.audience") == audience
                    and row["config"].get("access.token.claim") == "true"
                    for row in mappers
                )
                if not audience_ready:
                    raise AppError("keycloak_mapper_incompatible", "Required Keycloak audience mapper is missing", status_code=422)
                for client_id in confidential_client_ids:
                    rows = self._request_list(client, token, "clients", params={"clientId": client_id, "max": 2})
                    matches = [row for row in rows if str(row.get("clientId") or "") == client_id]
                    if len(matches) != 1:
                        raise AppError("keycloak_client_missing", "Required Keycloak client is missing", status_code=422, details={"client_id": client_id})
                    representation = matches[0]
                    if (
                        not representation.get("enabled")
                        or representation.get("publicClient")
                        or representation.get("standardFlowEnabled")
                        or not representation.get("serviceAccountsEnabled")
                    ):
                        raise AppError("keycloak_client_incompatible", "Required Keycloak client is incompatible", status_code=422, details={"client_id": client_id})
                    verified_clients.append(client_id)
                groups = self._flatten_groups(self._all_pages(client, token, "groups"))
                if self._find_group(groups, system_admin_group) is None:
                    raise AppError("keycloak_system_admin_group_missing", "Required Keycloak System Admin group is missing", status_code=422)
                return {
                    "clients": verified_clients,
                    "system_admin_group": system_admin_group,
                    "login_theme": NOMOSMART_LOGIN_THEME,
                    "supported_locales": sorted(NOMOSMART_SUPPORTED_LOCALES),
                }
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def break_glass_status(self, username: str, *, system_admin_group: str = "system-admin") -> KeycloakBreakGlassStatus:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                user = self._find_user_by_username(client, token, username)
                if user is None:
                    return KeycloakBreakGlassStatus(
                        username=username,
                        configured=False,
                        status="not_configured",
                        detail_code="user_missing",
                        enabled=None,
                        local_account=None,
                        system_admin_mapped=False,
                        credential_update_required=None,
                        required_actions=(),
                    )
                user_id = user.get("id")
                if not isinstance(user_id, str) or not user_id:
                    raise AppError("keycloak_invalid_response", "Keycloak user is missing an id", status_code=502)
                groups = self._request_list(client, token, f"users/{user_id}/groups")
                required_actions = tuple(str(item) for item in user.get("requiredActions", []) if item)
                enabled = bool(user.get("enabled", False))
                local_account = not bool(user.get("federationLink"))
                system_admin_mapped = self._user_group_mapped(groups, system_admin_group)
                credential_update_required = "UPDATE_PASSWORD" in required_actions
                if not local_account:
                    status = "attention_required"
                    detail_code = "not_keycloak_local"
                elif enabled:
                    status = "attention_required"
                    detail_code = "account_enabled"
                elif not system_admin_mapped:
                    status = "attention_required"
                    detail_code = "system_admin_mapping_missing"
                else:
                    status = "configured_disabled"
                    detail_code = "configured_disabled"
                return KeycloakBreakGlassStatus(
                    username=username,
                    configured=True,
                    status=status,
                    detail_code=detail_code,
                    enabled=enabled,
                    local_account=local_account,
                    system_admin_mapped=system_admin_mapped,
                    credential_update_required=credential_update_required,
                    required_actions=required_actions,
                )
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def ensure_break_glass_user(
        self,
        *,
        username: str,
        initial_password: str | None = None,
        system_admin_group: str = "system-admin",
        enabled: bool = False,
    ) -> KeycloakBreakGlassStatus:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                user = self._find_user_by_username(client, token, username)
                required_actions = ["UPDATE_PASSWORD"]
                if user is None:
                    if not initial_password:
                        raise AppError("break_glass_initial_credential_required", "Break-glass initial credential must be provided by deployment Secret", status_code=422)
                    payload: dict[str, Any] = {
                        "username": username,
                        "email": BREAK_GLASS_DEFAULT_EMAIL,
                        "emailVerified": True,
                        "firstName": BREAK_GLASS_DEFAULT_FIRST_NAME,
                        "lastName": BREAK_GLASS_DEFAULT_LAST_NAME,
                        "enabled": enabled,
                        "requiredActions": required_actions,
                    }
                    payload["credentials"] = [{"type": "password", "value": initial_password, "temporary": True}]
                    self._request_empty(client, token, "POST", "users", json=payload)
                    user = self._find_user_by_username(client, token, username)
                if user is None:
                    raise AppError("keycloak_invalid_response", "Keycloak did not return the provisioned break-glass user", status_code=502)
                user_id = user.get("id")
                if not isinstance(user_id, str) or not user_id:
                    raise AppError("keycloak_invalid_response", "Keycloak user is missing an id", status_code=502)
                if user.get("federationLink"):
                    raise AppError("break_glass_not_keycloak_local", "Break-glass account must be Keycloak-local", status_code=422)
                update_payload = dict(user)
                update_payload["enabled"] = enabled
                update_payload["requiredActions"] = [
                    str(action)
                    for action in (update_payload.get("requiredActions") or [])
                    if action and str(action) != "CONFIGURE_TOTP"
                ]
                if not str(update_payload.get("email") or "").strip():
                    update_payload["email"] = BREAK_GLASS_DEFAULT_EMAIL
                    update_payload["emailVerified"] = True
                if not str(update_payload.get("firstName") or "").strip():
                    update_payload["firstName"] = BREAK_GLASS_DEFAULT_FIRST_NAME
                if not str(update_payload.get("lastName") or "").strip():
                    update_payload["lastName"] = BREAK_GLASS_DEFAULT_LAST_NAME
                # Required actions are set only when the account is created. Re-running
                # bootstrap after a completed first login must not force them again.
                self._request_empty(client, token, "PUT", f"users/{user_id}", json=update_payload)
                groups = self._flatten_groups(self._all_pages(client, token, "groups"))
                group = self._find_group(groups, system_admin_group)
                if group and group.get("id"):
                    self._request_empty(client, token, "PUT", f"users/{user_id}/groups/{group['id']}")
                return self.break_glass_status(username, system_admin_group=system_admin_group)
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def verify_break_glass_onboarding_complete(
        self,
        username: str,
        *,
        system_admin_group: str = "system-admin",
        allow_disabled: bool = False,
    ) -> str:
        """Verify password update, mapping and lifecycle controls without receiving the password."""
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                user = self._find_user_by_username(client, token, username)
                if user is None:
                    raise AppError("break_glass_user_missing", "Break-glass account is unavailable", status_code=422)
                user_id = user.get("id")
                if not isinstance(user_id, str) or not user_id:
                    raise AppError("keycloak_invalid_response", "Keycloak user is missing an id", status_code=502)
                if user.get("federationLink"):
                    raise AppError("break_glass_not_keycloak_local", "Break-glass account must be Keycloak-local", status_code=422)
                if not allow_disabled and not bool(user.get("enabled", False)):
                    raise AppError("break_glass_not_enabled", "Break-glass onboarding account is not enabled", status_code=422)
                required_actions = {str(item) for item in user.get("requiredActions", []) if item}
                if required_actions:
                    raise AppError("break_glass_required_actions_pending", "Break-glass first-use actions are incomplete", status_code=422)
                groups = self._request_list(client, token, f"users/{user_id}/groups")
                if not self._user_group_mapped(groups, system_admin_group):
                    raise AppError("break_glass_system_admin_missing", "Break-glass System Admin mapping is missing", status_code=422)
                return user_id
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def verify_federated_admin_onboarding_complete(
        self,
        username: str,
        *,
        external_group: str,
    ) -> str:
        """Verify the designated directory administrator and group evidence."""
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                user = self._find_user_by_username(client, token, username)
                if user is None:
                    raise AppError("federated_admin_missing", "Designated federated administrator is unavailable", status_code=422)
                user_id = user.get("id")
                if not isinstance(user_id, str) or not user_id:
                    raise AppError("keycloak_invalid_response", "Keycloak user is missing an id", status_code=502)
                if not user.get("federationLink"):
                    raise AppError("federated_admin_not_directory_user", "Designated administrator must be directory-federated", status_code=422)
                if not bool(user.get("enabled", False)):
                    raise AppError("federated_admin_disabled", "Designated federated administrator is disabled", status_code=422)
                required_actions = {str(item) for item in user.get("requiredActions", []) if item}
                if required_actions:
                    raise AppError("federated_admin_required_actions_pending", "Federated administrator first-use actions are incomplete", status_code=422)
                groups = self._request_list(client, token, f"users/{user_id}/groups")
                if not self._user_group_mapped(groups, external_group):
                    raise AppError("federated_admin_group_missing", "Federated administrator group mapping is missing", status_code=422)
                return user_id
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

    def disable_break_glass_user(self, username: str) -> None:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                token = self._access_token(client)
                user = self._find_user_by_username(client, token, username)
                if user is None or not isinstance(user.get("id"), str):
                    raise AppError("break_glass_user_missing", "Break-glass account is unavailable", status_code=422)
                user_id = str(user["id"])
                payload = dict(user)
                payload["enabled"] = False
                self._request_empty(client, token, "PUT", f"users/{user_id}", json=payload)
                self._request_empty(client, token, "POST", f"users/{user_id}/logout")
        except AppError:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError("keycloak_unavailable", "Keycloak Admin API is unavailable", status_code=502) from exc

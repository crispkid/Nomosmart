from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import stat
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AuthConnectionSecret, DirectorySource, IdentitySetting


class DirectoryConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    name: str = Field(min_length=1, max_length=255)
    schema_type: Literal["ldap", "ad"] = "ldap"
    endpoints: list[str] = Field(min_length=1, max_length=4)
    start_tls: bool = False
    ca_reference: str = ""
    users_dn: str = Field(min_length=1, max_length=2048)
    groups_dn: str = Field(min_length=1, max_length=2048)
    bind_dn: str = Field(min_length=1, max_length=2048)
    user_filter: str = "(objectClass=inetOrgPerson)"
    group_filter: str = "(objectClass=groupOfNames)"
    login_attribute: str = "uid"
    object_id_attribute: str = "entryUUID"
    group_id_attribute: str = "entryUUID"
    group_member_attribute: Literal["member", "uniqueMember", "memberUid"] = "member"
    employee_attribute: str = "employeeNumber"
    enabled_attribute: str = ""
    disabled_value: str = "TRUE"
    page_size: int = Field(default=200, ge=1, le=1000)
    maximum_entries: int = Field(default=100000, ge=1, le=1000000)

    @field_validator("login_attribute", "object_id_attribute", "group_id_attribute", "employee_attribute", "enabled_attribute")
    @classmethod
    def attribute_names(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9;-]*", value):
            raise ValueError("Invalid directory attribute")
        return value

    @model_validator(mode="after")
    def secure_transport(self):
        if any(not e.startswith("ldaps://") and not (e.startswith("ldap://") and self.start_tls) for e in self.endpoints):
            raise ValueError("Directory requires LDAPS or mandatory StartTLS")
        if self.schema_type == "ad" and (self.object_id_attribute != "objectGUID" or self.group_id_attribute != "objectGUID"):
            raise ValueError("AD identities require objectGUID")
        return self


class OidcConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(min_length=1, max_length=2048)
    client_id: str = Field(min_length=1, max_length=255)
    client_auth_method: Literal["none", "client_secret_basic", "client_secret_post"] = "none"
    scopes: str = "openid profile email"
    mapping_claim: str = "directory_id"
    mapping_attribute: Literal["object_id", "employee_id"] = "object_id"
    employee_id_immutable: bool = False
    discovery_url: str = ""
    token_url: str = ""
    jwks_url: str = ""
    ca_reference: str = ""

    @model_validator(mode="after")
    def openid_scope(self):
        if "openid" not in self.scopes.split() or not self.issuer.startswith("https://") or self.issuer.endswith("/"):
            raise ValueError("OIDC requires HTTPS issuer without a trailing slash and openid scope")
        if self.mapping_attribute == "employee_id" and not self.employee_id_immutable:
            raise ValueError("Employee mapping requires an explicit immutable unique identifier policy")
        return self


class ProtocolConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_mode: Literal["oidc", "ldap"]
    display_name: str = Field(default="Enterprise sign-in", min_length=1, max_length=255)
    directory: DirectoryConfiguration
    oidc: OidcConfiguration | None = None
    sync_enabled: bool = True
    sync_scope: Literal["people", "groups", "people_and_groups"] = "people_and_groups"
    sync_schedule: str = "0 2 * * *"
    timezone: str = "Asia/Taipei"
    auth_contract_revision: Literal[2] = 2

    @field_validator("sync_schedule")
    @classmethod
    def daily_schedule(cls, value: str) -> str:
        fields = value.split()
        if len(fields) != 5 or fields[2:] != ["*", "*", "*"] or not all(part.isascii() and part.isdecimal() for part in fields[:2]):
            raise ValueError("Choose a daily execution time")
        if not 0 <= int(fields[0]) <= 59 or not 0 <= int(fields[1]) <= 23:
            raise ValueError("Choose a valid hour and minute")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def mode_configuration(self):
        if self.auth_mode == "oidc" and self.oidc is None:
            raise ValueError("OIDC configuration is required")
        return self


def current_setting(session: Session) -> IdentitySetting:
    row = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    if row is None or row.configuration.get("auth_contract_revision") != 2:
        raise AppError("auth_configuration_required", "Protocol authentication must be initialized", status_code=503)
    return row


def configuration(row: IdentitySetting) -> ProtocolConfiguration:
    try:
        return ProtocolConfiguration.model_validate(row.configuration)
    except ValueError as exc:
        raise AppError("auth_configuration_invalid", "Authentication configuration is invalid", status_code=503) from exc


def keyring(settings: Settings) -> dict[str, bytes]:
    keys = {settings.auth_encryption_key_id: settings.auth_encryption_key_bytes}
    if settings.auth_encryption_previous_keys_file:
        path = Path(settings.auth_encryption_previous_keys_file)
        try:
            details = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
                raise ValueError("insecure keyring")
            old = json.loads(path.read_text())
            if not isinstance(old, dict) or settings.auth_encryption_key_id in old:
                raise ValueError("invalid keyring")
            for name, value in old.items():
                raw = bytes.fromhex(value)
                if len(raw) != 32:
                    raise ValueError("invalid key")
                keys[str(name)] = raw
        except (OSError, ValueError, TypeError) as exc:
            raise AppError("auth_key_unavailable", "Authentication encryption key is unavailable", status_code=503) from exc
    return keys


def seal(settings: Settings, value: str, *, context: str) -> tuple[str, str]:
    if settings.auth_encryption_key_bytes == bytes(32):
        raise AppError("auth_key_unavailable", "A non-default authentication encryption key is required", status_code=503)
    return settings.auth_encryption_key_id, EnvelopeCipher(settings.auth_encryption_key_bytes).encrypt(value, context=context)


def unseal(settings: Settings, key_id: str, envelope: str, *, context: str) -> str:
    key = keyring(settings).get(key_id)
    if key is None:
        raise AppError("auth_key_unavailable", "Authentication encryption key is unavailable", status_code=503)
    try:
        return EnvelopeCipher(key).decrypt(envelope, context=context)
    except AppError as exc:
        raise AppError("auth_secret_invalid", "Authentication credential could not be verified", status_code=503) from exc


def secret_context(setting: IdentitySetting, purpose: str) -> str:
    source_id = str(configuration(setting).directory.source_id)
    return f"auth-connection:{setting.id}:{source_id}:{setting.revision}:{purpose}"


def read_secret(session: Session, settings: Settings, setting: IdentitySetting, purpose: str) -> str:
    row = session.scalar(select(AuthConnectionSecret).where(AuthConnectionSecret.setting_id == setting.id, AuthConnectionSecret.purpose == purpose))
    if row is None:
        return ""
    if row.source_id != configuration(setting).directory.source_id or row.context_revision != setting.revision:
        raise AppError("auth_secret_invalid", "Authentication credential context is invalid", status_code=503)
    return unseal(settings, row.key_id, row.envelope, context=secret_context(setting, purpose))


def store_secret(session: Session, settings: Settings, setting: IdentitySetting, purpose: str, value: str) -> None:
    if purpose not in {"ldap_bind_password", "oidc_client_secret"}:
        raise ValueError("Unsupported connection secret purpose")
    row = session.scalar(select(AuthConnectionSecret).where(AuthConnectionSecret.setting_id == setting.id, AuthConnectionSecret.purpose == purpose))
    if not value:
        if row:
            session.delete(row)
        return
    key_id, envelope = seal(settings, value, context=secret_context(setting, purpose))
    if row is None:
        row = AuthConnectionSecret(id=uuid4(), setting_id=setting.id, source_id=configuration(setting).directory.source_id, purpose=purpose, context_revision=setting.revision, key_id=key_id, envelope=envelope, created_at=datetime.now(UTC))
        session.add(row)
    else:
        row.key_id, row.envelope = key_id, envelope


def stage_configuration(session: Session, settings: Settings, candidate: ProtocolConfiguration, secrets: dict[str, str], actor_id: UUID | None, *, previous: IdentitySetting | None = None) -> IdentitySetting:
    session.execute(text("SELECT pg_advisory_xact_lock(4873662102)"))
    source = session.get(DirectorySource, candidate.directory.source_id)
    if source is None:
        if session.scalar(select(func.count()).select_from(DirectorySource)):
            raise AppError("directory_source_conflict", "Only the configured directory source may be used", status_code=409)
        source = DirectorySource(id=candidate.directory.source_id, name=candidate.directory.name, schema=candidate.directory.schema_type)
        session.add(source)
        session.flush()
    elif source.schema != candidate.directory.schema_type:
        raise AppError("directory_source_conflict", "Directory schema cannot be changed for an existing source", status_code=409)
    revision = (session.scalar(select(func.max(IdentitySetting.revision))) or 0) + 1
    row = IdentitySetting(id=uuid4(), revision=revision, base_revision=previous.revision if previous else None, state="draft_unvalidated", configuration=candidate.model_dump(mode="json"), secret_configured=False, is_current=False, is_last_known_good=False, created_by=actor_id)
    session.add(row)
    session.flush()
    for purpose in ("ldap_bind_password", "oidc_client_secret"):
        value = secrets[purpose] if purpose in secrets else read_secret(session, settings, previous, purpose) if previous else ""
        store_secret(session, settings, row, purpose, value)
    session.flush()
    row.secret_configured = bool(read_secret(session, settings, row, "ldap_bind_password"))
    return row

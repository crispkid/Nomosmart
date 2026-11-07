"""CHG-305: database-owned file policy; caller owns the transaction.

No runtime defaults/fallback: initialization is a separate authenticated operation.
All writers and admission decisions serialize on the same singleton policy row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import FileProcessingPolicy, FileProcessingPolicyRevision, SystemParameter
from app.security.auth import IdentityPrincipal
from app.security.context import resolve_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


def policy_error(code: str, status: int = 409) -> AppError:
    return AppError(code, "File-processing policy could not be applied", status_code=status)


StrictInteger = Annotated[int, Field(strict=True)]
RetryCode = Literal["parser_capacity_unavailable", "parser_start_failed_confirmed_stopped"]


class LegacyFileProcessingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_processing_max_concurrent: StrictInteger = Field(ge=1, le=10000)
    pdf_parser_max_concurrent: StrictInteger = Field(ge=1, le=10000)
    pdf_parser_cpu_millicores: StrictInteger = Field(ge=100, le=64000)
    pdf_parser_memory_mib: StrictInteger = Field(ge=128, le=262144)
    pdf_parser_scratch_mib: StrictInteger = Field(ge=16, le=262144)
    pdf_parser_timeout_seconds: StrictInteger = Field(ge=10, le=1800)
    pdf_parser_max_pages: StrictInteger = Field(ge=1, le=2000)
    pdf_parser_max_output_mib: StrictInteger = Field(ge=1, le=40960)
    pdf_parser_retry_max_attempts: StrictInteger = Field(ge=1, le=5)
    pdf_parser_retry_delay_seconds: StrictInteger = Field(ge=1, le=3600)
    pdf_parser_retryable_error_codes: tuple[RetryCode, ...]
    file_processing_progress_interval_seconds: StrictInteger = Field(ge=1, le=60)
    file_processing_background_poll_interval_seconds: StrictInteger = Field(ge=1, le=300)

    @field_validator("pdf_parser_retryable_error_codes", mode="before")
    @classmethod
    def retry_codes(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (tuple, list)) or not all(isinstance(item, str) for item in value):
            raise ValueError("Retry codes must be a list of enum values")
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def related_limits(self) -> LegacyFileProcessingSettings:
        if self.file_processing_background_poll_interval_seconds < self.file_processing_progress_interval_seconds:
            raise ValueError("Background polling must not be faster than foreground polling")
        return self

    @property
    def content_hash(self) -> str:
        material = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return sha256(material.encode()).hexdigest()


class FileProcessingSettings(BaseModel):
    """Current document policy. Historical parser policy is decoded separately."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    document_processing_max_concurrent: StrictInteger = Field(ge=1, le=10000)
    document_processing_timeout_seconds: StrictInteger = Field(ge=10, le=1800)
    document_dispatch_yield_delay_seconds: StrictInteger = Field(ge=1, le=3600)
    file_processing_progress_interval_seconds: StrictInteger = Field(ge=1, le=60)
    file_processing_background_poll_interval_seconds: StrictInteger = Field(ge=1, le=300)

    @model_validator(mode="after")
    def related_limits(self):
        if self.file_processing_background_poll_interval_seconds < self.file_processing_progress_interval_seconds:
            raise ValueError("Background polling must not be faster than foreground polling")
        return self

    @property
    def content_hash(self) -> str:
        material = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return sha256(material.encode()).hexdigest()


LEGACY_UNITS = {
    "document_processing_max_concurrent": "documents", "pdf_parser_max_concurrent": "workloads",
    "pdf_parser_cpu_millicores": "millicores", "pdf_parser_memory_mib": "MiB",
    "pdf_parser_scratch_mib": "MiB", "pdf_parser_timeout_seconds": "seconds",
    "pdf_parser_max_pages": "pages", "pdf_parser_max_output_mib": "MiB",
    "pdf_parser_retry_max_attempts": "attempts", "pdf_parser_retry_delay_seconds": "seconds",
    "pdf_parser_retryable_error_codes": None, "file_processing_progress_interval_seconds": "seconds",
    "file_processing_background_poll_interval_seconds": "seconds",
}
UNITS = {"document_processing_max_concurrent": "documents", "document_processing_timeout_seconds": "seconds",
         "document_dispatch_yield_delay_seconds": "seconds", "file_processing_progress_interval_seconds": "seconds",
         "file_processing_background_poll_interval_seconds": "seconds"}
ACTIVE_KEYS = frozenset(UNITS)
DEPRECATED_KEYS = frozenset(LEGACY_UNITS) - ACTIVE_KEYS
CAPABILITY_KEYS = frozenset({"document_processing_max_concurrent", "document_processing_timeout_seconds"})
_LEGACY_CAPABILITY_KEYS = frozenset({"document_processing_max_concurrent", "pdf_parser_max_concurrent",
    "pdf_parser_cpu_millicores", "pdf_parser_memory_mib", "pdf_parser_scratch_mib", "pdf_parser_timeout_seconds",
    "pdf_parser_max_pages", "pdf_parser_max_output_mib"})


def _validated(values: dict, *, schema_version: int = 2):
    if type(schema_version) is not int or schema_version not in {1, 2}:
        raise policy_error("file_processing_policy_version_invalid", 422)
    try:
        return (LegacyFileProcessingSettings if schema_version == 1 else FileProcessingSettings).model_validate(values)
    except ValidationError as exc:
        raise policy_error("file_processing_policy_invalid", 422) from exc


def settings_from_snapshot(snapshot: dict):
    if type(snapshot) is not dict:
        raise policy_error("file_processing_policy_invalid", 422)
    version = snapshot.get("_schema_version", 1)
    return _validated({k: v for k, v in snapshot.items() if k != "_schema_version"}, schema_version=version)


def snapshot_setting(snapshot: dict, key: str) -> int:
    values = settings_from_snapshot(snapshot)
    alias = {"document_processing_timeout_seconds": "pdf_parser_timeout_seconds",
             "document_dispatch_yield_delay_seconds": "pdf_parser_retry_delay_seconds"}
    return getattr(values, alias.get(key, key) if isinstance(values, LegacyFileProcessingSettings) else key)


@dataclass(frozen=True)
class PlatformCapabilities:
    maxima: dict[str, int]

    def validate(self, values) -> None:
        keys = set(self.maxima)
        accepted = (set(), CAPABILITY_KEYS, _LEGACY_CAPABILITY_KEYS,
                    _LEGACY_CAPABILITY_KEYS - {"pdf_parser_cpu_millicores", "pdf_parser_memory_mib"},
                    {"document_processing_max_concurrent", "pdf_parser_timeout_seconds"})
        if keys not in accepted or any(type(v) is not int or v <= 0 for v in self.maxima.values()):
            raise policy_error("file_processing_capability_invalid")
        for key, maximum in self.maxima.items():
            effective = "document_processing_timeout_seconds" if key == "pdf_parser_timeout_seconds" else key
            if effective not in CAPABILITY_KEYS:
                continue  # Historical parser resource caps are not document runtime settings.
            name = "pdf_parser_timeout_seconds" if isinstance(values, LegacyFileProcessingSettings) and effective == "document_processing_timeout_seconds" else effective
            if getattr(values, name) > maximum:
                raise policy_error("file_processing_capability_exceeded", 422)


@dataclass(frozen=True)
class PolicySnapshot:
    deployment_id: UUID
    revision: int
    settings: FileProcessingSettings | LegacyFileProcessingSettings

    @property
    def schema_version(self) -> int:
        return 1 if isinstance(self.settings, LegacyFileProcessingSettings) else 2

    def execution_values(self) -> dict:
        values = self.settings.model_dump(mode="json")
        return values if self.schema_version == 1 else {**values, "_schema_version": 2}


def _parameter_rows(session: Session, *, schema_version: int = 2):
    units = LEGACY_UNITS if schema_version == 1 else UNITS
    return {r.key: r for r in session.scalars(select(SystemParameter).where(SystemParameter.key.in_(units))
            .execution_options(populate_existing=True))}


def _row_values(rows: dict, *, schema_version: int = 2) -> dict:
    units = LEGACY_UNITS if schema_version == 1 else UNITS
    for key, row in rows.items():
        expected_type = "array" if key == "pdf_parser_retryable_error_codes" else "integer"
        if key not in units or row.unit != units[key] or row.value_type != expected_type:
            raise policy_error("file_processing_parameter_metadata_invalid")
    return {k: r.value for k, r in rows.items()}


def validated_policy(session, row) -> PolicySnapshot:
    version = row.schema_version
    values = _validated(_row_values(_parameter_rows(session, schema_version=version), schema_version=version), schema_version=version)
    history = session.get(FileProcessingPolicyRevision, row.revision, populate_existing=True)
    if (history is None or history.schema_version != version or values.content_hash != row.content_hash
            or history.content_hash != row.content_hash or history.snapshot != values.model_dump(mode="json")):
        raise policy_error("file_processing_policy_revision_mismatch", 503)
    return PolicySnapshot(row.deployment_id, row.revision, values)


def load_policy(session: Session, *, lock: bool = False) -> PolicySnapshot:
    row = session.scalar(select(FileProcessingPolicy).where(FileProcessingPolicy.id == 1)
        .execution_options(populate_existing=True).with_for_update(read=not lock))
    if row is None:
        raise policy_error("file_processing_policy_missing", 503)
    return validated_policy(session, row)


def authorize_maintenance(session: Session, principal: IdentityPrincipal, *, write: bool) -> UUID:
    if principal.expires_at <= datetime.now(UTC):
        raise policy_error("token_expired", 401)
    context = resolve_identity_context(session, principal)
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    if write:
        require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    return context.user_id


def initialize_policy(session: Session, *, principal: IdentityPrincipal, deployment_id: UUID,
                      legacy_timeout_seconds: int, legacy_max_pages: int, legacy_upload_mib: int,
                      capabilities: PlatformCapabilities) -> PolicySnapshot:
    actor = authorize_maintenance(session, principal, write=True)
    session.execute(text("SELECT pg_advisory_xact_lock(305, 1)"))
    if session.get(FileProcessingPolicy, 1) is not None:
        existing = load_policy(session, lock=True)
        if existing.deployment_id != deployment_id:
            raise policy_error("file_processing_deployment_mismatch")
        capabilities.validate(existing.settings)
        return existing
    # Explicit operator initialization only; load_policy has no fallback defaults.
    defaults = {"document_processing_max_concurrent": 10, "document_processing_timeout_seconds": legacy_timeout_seconds,
                "document_dispatch_yield_delay_seconds": 5, "file_processing_progress_interval_seconds": 2,
                "file_processing_background_poll_interval_seconds": 15}
    rows = _parameter_rows(session)
    values = _validated(defaults | _row_values(rows))
    capabilities.validate(values)
    now = datetime.now(UTC)
    for key, value in values.model_dump(mode="json").items():
        if key not in rows:
            session.add(SystemParameter(key=key, value=value, default_value=defaults[key], unit=UNITS[key],
                value_type="integer", description=f"Document-processing policy: {key}", updated_by=actor))
    policy = FileProcessingPolicy(id=1, schema_version=2, deployment_id=deployment_id, revision=1,
                                 content_hash=values.content_hash, updated_at=now)
    session.add(policy)
    _record_revision(session, values, 1, actor, {"operation": "initialize_missing_only", "preserved_keys": sorted(rows)}, {}, now)
    session.flush()
    return PolicySnapshot(deployment_id, 1, values)


def _record_revision(session, settings, revision, actor, provenance, previous, now):
    snapshot = settings.model_dump(mode="json")
    version = 1 if isinstance(settings, LegacyFileProcessingSettings) else 2
    session.add(FileProcessingPolicyRevision(revision=revision, schema_version=version, snapshot=snapshot,
        content_hash=settings.content_hash, provenance=provenance, created_by=actor, created_at=now))
    add_audit(session, actor_user_id=actor, action="file_processing.policy.updated", resource_type="file_processing_policy",
        resource_id=None, result="success", request_id=None,
        summary={"schema_version": version, "revision": revision, "previous": previous, "current": snapshot, "provenance": provenance})


def update_policy(session: Session, *, principal: IdentityPrincipal, expected_revision: int,
                  changes: dict, capabilities: PlatformCapabilities) -> PolicySnapshot:
    actor = authorize_maintenance(session, principal, write=True)
    if type(expected_revision) is not int or type(changes) is not dict or not changes or set(changes) - (UNITS.keys() | LEGACY_UNITS.keys()):
        raise policy_error("file_processing_update_invalid", 422)
    current = load_policy(session, lock=True)
    if current.revision != expected_revision:
        raise policy_error("file_processing_policy_conflict")
    if current.schema_version != 2:
        raise policy_error("file_processing_policy_migration_required", 409)
    previous = current.settings.model_dump(mode="json")
    legacy = _parameter_rows(session, schema_version=1)
    aliases = {"pdf_parser_timeout_seconds": "document_processing_timeout_seconds",
               "pdf_parser_retry_delay_seconds": "document_dispatch_yield_delay_seconds"}
    for key in set(changes) & DEPRECATED_KEYS:
        if key in aliases and aliases[key] in changes and changes[key] != changes[aliases[key]]:
            raise policy_error("file_processing_alias_conflict", 422)
        if key not in legacy or changes[key] != legacy[key].value:
            raise policy_error("file_processing_parameter_deprecated", 422)
    updates = {k: v for k, v in changes.items() if k in ACTIVE_KEYS}
    values = _validated(previous | updates)
    capabilities.validate(values)
    if values == current.settings:
        return current
    now = datetime.now(UTC)
    rows = _parameter_rows(session)
    for key, value in values.model_dump(mode="json").items():
        if rows[key].value != value:
            rows[key].value, rows[key].updated_by, rows[key].updated_at = value, actor, now
    policy = session.get(FileProcessingPolicy, 1)
    policy.revision += 1
    policy.content_hash, policy.updated_at = values.content_hash, now
    _record_revision(session, values, policy.revision, actor, {"operation": "compare_and_swap"}, previous, now)
    session.flush()
    return PolicySnapshot(current.deployment_id, policy.revision, values)

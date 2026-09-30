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


class FileProcessingSettings(BaseModel):
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
    def related_limits(self) -> FileProcessingSettings:
        if self.file_processing_background_poll_interval_seconds < self.file_processing_progress_interval_seconds:
            raise ValueError("Background polling must not be faster than foreground polling")
        return self

    @property
    def content_hash(self) -> str:
        material = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return sha256(material.encode()).hexdigest()


# Metadata is part of the policy contract, not inferred from arbitrary stored JSON.
UNITS = {
    "document_processing_max_concurrent": "documents", "pdf_parser_max_concurrent": "workloads",
    "pdf_parser_cpu_millicores": "millicores", "pdf_parser_memory_mib": "MiB",
    "pdf_parser_scratch_mib": "MiB", "pdf_parser_timeout_seconds": "seconds",
    "pdf_parser_max_pages": "pages", "pdf_parser_max_output_mib": "MiB",
    "pdf_parser_retry_max_attempts": "attempts", "pdf_parser_retry_delay_seconds": "seconds",
    "pdf_parser_retryable_error_codes": None, "file_processing_progress_interval_seconds": "seconds",
    "file_processing_background_poll_interval_seconds": "seconds",
}
CAPABILITY_KEYS = frozenset({
    "document_processing_max_concurrent", "pdf_parser_max_concurrent", "pdf_parser_cpu_millicores",
    "pdf_parser_memory_mib", "pdf_parser_scratch_mib", "pdf_parser_timeout_seconds",
    "pdf_parser_max_pages", "pdf_parser_max_output_mib",
})
DEPRECATED_KEYS = frozenset({"pdf_parser_cpu_millicores", "pdf_parser_memory_mib"})
ACTIVE_KEYS = frozenset(UNITS) - DEPRECATED_KEYS


@dataclass(frozen=True)
class PlatformCapabilities:
    """Trusted deployment maximums, never DB overrides or silently clamped values."""
    maxima: dict[str, int]

    def validate(self, values: FileProcessingSettings) -> None:
        if (set(self.maxima) not in (set(), CAPABILITY_KEYS, CAPABILITY_KEYS - DEPRECATED_KEYS)
                or any(type(v) is not int or v <= 0 for v in self.maxima.values())):
            raise policy_error("file_processing_capability_invalid")
        if any(getattr(values, key) > maximum for key, maximum in self.maxima.items() if key not in DEPRECATED_KEYS):
            raise policy_error("file_processing_capability_exceeded", 422)


@dataclass(frozen=True)
class PolicySnapshot:
    deployment_id: UUID
    revision: int
    settings: FileProcessingSettings


def _validated(values: dict) -> FileProcessingSettings:
    try:
        return FileProcessingSettings.model_validate(values)
    except ValidationError as exc:
        # Do not echo arbitrary untrusted keys/values into logs or user errors.
        raise policy_error("file_processing_policy_invalid", 422) from exc


def _parameter_rows(session: Session) -> dict[str, SystemParameter]:
    return {row.key: row for row in session.scalars(
        select(SystemParameter).where(SystemParameter.key.in_(UNITS)).execution_options(populate_existing=True)
    )}


def _row_values(rows: dict[str, SystemParameter]) -> dict:
    for key, row in rows.items():
        expected_type = "array" if key == "pdf_parser_retryable_error_codes" else "integer"
        if row.unit != UNITS[key] or row.value_type != expected_type:
            raise policy_error("file_processing_parameter_metadata_invalid")
    return {key: row.value for key, row in rows.items()}


def load_policy(session: Session, *, lock: bool = False) -> PolicySnapshot:
    query = select(FileProcessingPolicy).where(FileProcessingPolicy.id == 1).execution_options(populate_existing=True)
    # Share lock protects a consistent policy+catalog read against approved writers.
    row = session.scalar(query.with_for_update(read=not lock))
    if row is None:
        raise policy_error("file_processing_policy_missing", 503)
    settings = _validated(_row_values(_parameter_rows(session)))
    history = session.get(FileProcessingPolicyRevision, row.revision, populate_existing=True)
    if (history is None or settings.content_hash != row.content_hash
            or history.content_hash != row.content_hash or history.snapshot != settings.model_dump(mode="json")):
        raise policy_error("file_processing_policy_revision_mismatch", 503)
    return PolicySnapshot(row.deployment_id, row.revision, settings)


def authorize_maintenance(session: Session, principal: IdentityPrincipal, *, write: bool) -> UUID:
    if principal.expires_at <= datetime.now(UTC):
        raise policy_error("token_expired", 401)
    context = resolve_identity_context(session, principal)
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    if write:
        require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    return context.user_id


def initialize_policy(
    session: Session, *, principal: IdentityPrincipal, deployment_id: UUID,
    legacy_timeout_seconds: int, legacy_max_pages: int, legacy_upload_mib: int,
    capabilities: PlatformCapabilities,
) -> PolicySnapshot:
    actor = authorize_maintenance(session, principal, write=True)
    # Serialize the absent-singleton case as well as repeat initialization.
    session.execute(text("SELECT pg_advisory_xact_lock(305, 1)"))
    if session.get(FileProcessingPolicy, 1) is not None:
        existing = load_policy(session, lock=True)
        if existing.deployment_id != deployment_id:
            raise policy_error("file_processing_deployment_mismatch")
        capabilities.validate(existing.settings)
        return existing
    if type(legacy_upload_mib) is not int or not 1 <= legacy_upload_mib <= 10240:
        raise policy_error("file_processing_legacy_source_invalid", 422)
    defaults = {
        "document_processing_max_concurrent": 10, "pdf_parser_max_concurrent": 10,
        "pdf_parser_cpu_millicores": 1000, "pdf_parser_memory_mib": 768, "pdf_parser_scratch_mib": 256,
        "pdf_parser_timeout_seconds": legacy_timeout_seconds, "pdf_parser_max_pages": legacy_max_pages,
        "pdf_parser_max_output_mib": legacy_upload_mib * 4, "pdf_parser_retry_max_attempts": 1,
        "pdf_parser_retry_delay_seconds": 5, "pdf_parser_retryable_error_codes": [],
        "file_processing_progress_interval_seconds": 2, "file_processing_background_poll_interval_seconds": 15,
    }
    _validated(defaults)  # Even pre-existing keys cannot hide an invalid legacy receipt.
    rows = _parameter_rows(session)
    values = _validated(defaults | _row_values(rows))
    capabilities.validate(values)
    now = datetime.now(UTC)
    for key, value in values.model_dump(mode="json").items():
        if key not in rows:
            session.add(SystemParameter(
                key=key, value=value, default_value=defaults[key], unit=UNITS[key],
                value_type="array" if key == "pdf_parser_retryable_error_codes" else "integer",
                description=f"CHG-305 file-processing policy: {key}", updated_by=actor,
            ))
    provenance = {"operation": "initialize_missing_only", "preserved_keys": sorted(rows),
                  "legacy_timeout_seconds": legacy_timeout_seconds, "legacy_max_pages": legacy_max_pages,
                  "legacy_upload_mib": legacy_upload_mib, "output_formula": "upload_mib * 4 * 1048576 bytes"}
    session.add(FileProcessingPolicy(id=1, deployment_id=deployment_id, revision=1, content_hash=values.content_hash, updated_at=now))
    _record_revision(session, values, 1, actor, provenance, {}, now)
    session.flush()
    return PolicySnapshot(deployment_id, 1, values)


def _record_revision(session, settings, revision, actor, provenance, previous, now) -> None:
    snapshot = settings.model_dump(mode="json")
    session.add(FileProcessingPolicyRevision(revision=revision, snapshot=snapshot,
        content_hash=settings.content_hash, provenance=provenance, created_by=actor, created_at=now))
    add_audit(session, actor_user_id=actor, action="file_processing.policy.updated", resource_type="file_processing_policy",
              resource_id=None, result="success", request_id=None,
              summary={"revision": revision, "previous": previous, "current": snapshot, "provenance": provenance})


def update_policy(
    session: Session, *, principal: IdentityPrincipal, expected_revision: int,
    changes: dict, capabilities: PlatformCapabilities,
) -> PolicySnapshot:
    actor = authorize_maintenance(session, principal, write=True)
    if type(expected_revision) is not int or type(changes) is not dict or not changes or set(changes) - UNITS.keys():
        raise policy_error("file_processing_update_invalid", 422)
    current = load_policy(session, lock=True)
    if current.revision != expected_revision:
        raise policy_error("file_processing_policy_conflict")
    previous = current.settings.model_dump(mode="json")
    if any(key in changes and (type(changes[key]) is not int or changes[key] != previous[key]) for key in DEPRECATED_KEYS):
        raise AppError("file_processing_parameter_deprecated",
                       "Per-parser CPU and memory settings are read-only; configure Worker deployment resources", status_code=422)
    values = _validated(previous | changes)
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

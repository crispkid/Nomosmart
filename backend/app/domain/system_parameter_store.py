"""Typed database-owned settings and atomic, section-scoped updates (CHG-389)."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uuid import UUID

from sqlalchemy import select, update

from app.core.errors import AppError
from app.db.models import AIModel, Project, SystemParameter, SystemParameterSectionRevision, User
from app.domain.ocr_token_settings import NativeOCRTokenSettings
from app.services.audit import add_audit

SECTIONS = {
    "general": ("default_timezone", "session_expired_form_draft_ttl_minutes"),
    "documents": ("max_upload_size_mb", "staging_index_ttl_days", "ocr_request_max_output_tokens", "ocr_document_max_tokens"),
    # CHG-445 ROUTE445-004: reference routing and reference expansion for published-scope answers.
    "question_answering": ("reference_routing_enabled", "reference_routing_max_documents",
                           "reference_expansion_enabled", "reference_expansion_max_chunks",
                           "subquestion_enabled", "subquestion_max",  # CHG-450 SUBQ450-004
                           # CHG-486 TOPKP486-001 / RERANK486-002
                           "retrieval_top_k", "retrieval_top_p", "retrieval_rerank_min_score",
                           "retrieval_rerank_enabled", "retrieval_rerank_model_id"),
    "approvals": ("approval_owner_fallback_enabled",),  # CHG-467 REVROUTE467-005
}
BOOLEAN_KEYS = ("reference_routing_enabled", "reference_expansion_enabled", "subquestion_enabled", "approval_owner_fallback_enabled",
                "retrieval_rerank_enabled")
# CHG-486 TOPKP486-001: decimal settings (JSON numbers, stored as floats) and their inclusive ranges.
NUMBER_LIMITS = {"retrieval_top_p": (0.1, 1.0), "retrieval_rerank_min_score": (0.0, 1.0)}
KEYS = tuple(key for keys in SECTIONS.values() for key in keys)


def unavailable():
    return AppError("system_parameters_unavailable", "System settings are unavailable", status_code=503)


def validate(values, *, deployment_limit=None):
    errors = {}
    limits = {"max_upload_size_mb": (1, 10240), "staging_index_ttl_days": (1, 3650),
              "ocr_request_max_output_tokens": (1, 2147483647), "ocr_document_max_tokens": (1, 2147483647),
              "reference_routing_max_documents": (1, 50), "reference_expansion_max_chunks": (0, 10),
              "subquestion_max": (1, 5), "retrieval_top_k": (1, 20)}
    for key, (low, high) in limits.items():
        if key in values and (type(values[key]) is not int or not low <= values[key] <= high):
            errors[key] = "integer_out_of_range"
    for key in BOOLEAN_KEYS:
        if key in values and type(values[key]) is not bool:
            errors[key] = "boolean_required"
    for key, (low, high) in NUMBER_LIMITS.items():
        if key in values and (type(values[key]) not in (int, float) or not low <= values[key] <= high):
            errors[key] = "number_out_of_range"
    if "retrieval_rerank_model_id" in values:
        model_id = values["retrieval_rerank_model_id"]
        if model_id is not None and not _is_uuid(model_id):
            errors["retrieval_rerank_model_id"] = "model_id_invalid"
        elif values.get("retrieval_rerank_enabled") is True and model_id is None:
            errors["retrieval_rerank_model_id"] = "rerank_model_required"  # RERANK486-002
    key = "session_expired_form_draft_ttl_minutes"
    if key in values and (type(values[key]) is not int or values[key] != 0 and not 5 <= values[key] <= 120):
        errors[key] = "integer_out_of_range"
    if "default_timezone" in values:
        try:
            if type(values["default_timezone"]) is not str or not values["default_timezone"]:
                raise ValueError()
            ZoneInfo(values["default_timezone"])
        except (ValueError, TypeError, OSError, ZoneInfoNotFoundError):
            errors["default_timezone"] = "invalid_timezone"
    request_budget, document = values.get("ocr_request_max_output_tokens"), values.get("ocr_document_max_tokens")
    if type(request_budget) is int and type(document) is int and document < request_budget:
        errors["ocr_document_max_tokens"] = "document_budget_below_request"
    if deployment_limit is not None and type(values.get("max_upload_size_mb")) is int and values["max_upload_size_mb"] > deployment_limit:
        errors["max_upload_size_mb"] = "deployment_capacity_exceeded"
    if errors:
        raise AppError("invalid_system_parameters", "System settings are invalid", status_code=422, details=errors)


def _is_uuid(value) -> bool:
    if type(value) is not str:
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def read_values(session, keys=KEYS, *, defaults=False):
    rows = list(session.scalars(select(SystemParameter).where(SystemParameter.key.in_(keys))
                               .order_by(SystemParameter.key).execution_options(populate_existing=True)))
    if {row.key for row in rows} != set(keys):
        raise unavailable()
    values = {row.key: getattr(row, "default_value" if defaults else "value") for row in rows}
    try:
        validate(values)
    except AppError as exc:
        raise unavailable() from exc
    return values


def _require_rerank_model(session, merged) -> None:
    """RERANK486-002: reranking can be turned on only with an active, undeleted rerank model selected."""
    if merged.get("retrieval_rerank_enabled") is not True:
        return
    model = session.get(AIModel, UUID(merged["retrieval_rerank_model_id"]))
    if model is None or model.deleted_at is not None or not model.is_active or model.model_type != "Reranker":
        raise AppError("invalid_system_parameters", "System settings are invalid", status_code=422,
                       details={"retrieval_rerank_model_id": "rerank_model_unavailable"})


def _reset_project_rerank(session, *, actor, request_id, now) -> None:
    """RERANK486-003: turning the system switch off turns every project's switch off in the same transaction."""
    project_ids = list(session.scalars(update(Project).where(Project.rerank_enabled.is_(True))
                                       .values(rerank_enabled=False, updated_at=now).returning(Project.id)))
    for project_id in project_ids:
        add_audit(session, actor_user_id=actor, action="project.rerank.update", resource_type="project",
                  resource_id=project_id, result="success", request_id=request_id,
                  summary={"rerank_enabled": False, "source": "system_rerank_disabled"})


def question_answering_settings(session) -> dict:
    """ROUTE445-004: current reference routing and expansion values; read per question so changes apply at once."""
    return read_values(session, SECTIONS["question_answering"])


def approval_owner_fallback_enabled(session) -> bool:
    """REVROUTE467-005: read at each submission so a change applies to the next submission only."""
    return bool(read_values(session, SECTIONS["approvals"])["approval_owner_fallback_enabled"])


def intake_settings(session, settings):
    """Immutable per-intake copy; deployment transport reservations stay unchanged."""
    value = read_values(session, ("max_upload_size_mb",))["max_upload_size_mb"]
    if value > settings.max_upload_size_mb:
        raise unavailable()
    return settings.model_copy(update={"max_upload_size_mb": value,
        "upload_request_max_size_mb": settings.upload_request_max_bytes // (1024 * 1024), "_intake_snapshot": True})


def revision(section, counter, values):
    body = {"contract": "system-section-v1", "section": section, "counter": counter,
            "values": {key: values[key] for key in SECTIONS[section]}}
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot(session, sections=None, *, write=False):
    sections = sorted(sections or SECTIONS)
    versions = list(session.scalars(select(SystemParameterSectionRevision)
        .where(SystemParameterSectionRevision.section.in_(sections)).order_by(SystemParameterSectionRevision.section)
        .with_for_update(read=not write).execution_options(populate_existing=True)))
    if {row.section for row in versions} != set(sections):
        raise unavailable()
    keys = [key for section in sections for key in SECTIONS[section]]
    query = select(SystemParameter).where(SystemParameter.key.in_(keys)).order_by(SystemParameter.key)
    if write:
        query = query.with_for_update()
    rows = list(session.scalars(query.execution_options(populate_existing=True)))
    if {row.key for row in rows} != set(keys):
        raise unavailable()
    values, defaults = ({row.key: getattr(row, field) for row in rows} for field in ("value", "default_value"))
    try:
        validate(values)
        validate(defaults)
    except AppError as exc:
        raise unavailable() from exc
    revisions = {row.section: revision(row.section, row.revision, values) for row in versions}
    # CHG-449 DISP449-002: names of the updaters already in this response only; users are never enumerated.
    updater_ids = {row.updated_by for row in rows if row.updated_by is not None}
    names = dict(session.execute(select(User.id, User.display_name).where(User.id.in_(updater_ids))).all()) if updater_ids else {}
    metadata = {row.key: {"updated_at": row.updated_at, "updated_by": row.updated_by, "updated_by_name": names.get(row.updated_by)}
                for row in rows}
    return values, defaults, revisions, metadata, rows, versions


def update_sections(session, *, changes, expected, actor, request_id, deployment_limit, ocr_hash=None):
    if set(expected) != set(changes) or any(not expected[key] for key in changes):
        raise AppError("system_parameters_revision_required", "Reload settings before saving", status_code=428)
    values, defaults, revisions, metadata, rows, versions = snapshot(session, changes, write=True)
    if any(expected[key] != revisions[key] for key in changes):
        raise AppError("system_parameters_conflict", "Settings changed; reload and compare", status_code=409)
    merged = dict(values)
    for section, patch in changes.items():
        if not patch or set(patch) - set(SECTIONS[section]):
            raise AppError("invalid_system_parameters", "Invalid section fields", status_code=422)
        merged.update(patch)
    for key in NUMBER_LIMITS:
        if type(merged.get(key)) is int:
            merged[key] = float(merged[key])  # TOPKP486-001: decimals are stored as JSON floats
    validate(merged, deployment_limit=deployment_limit)
    _require_rerank_model(session, merged)
    if ocr_hash is not None and ocr_hash != NativeOCRTokenSettings(values["ocr_request_max_output_tokens"], values["ocr_document_max_tokens"]).content_hash:
        raise AppError("ocr_token_settings_conflict", "OCR settings changed", status_code=409)
    changed = {key for key in values if values[key] != merged[key]}
    now = datetime.now(UTC)
    for row in rows:
        if row.key in changed:
            row.value, row.updated_by, row.updated_at = merged[row.key], actor, now
    for row in versions:
        if changed.intersection(SECTIONS[row.section]):
            row.revision += 1
            row.updated_at = now
    if values.get("retrieval_rerank_enabled") is True and merged.get("retrieval_rerank_enabled") is False:
        _reset_project_rerank(session, actor=actor, request_id=request_id, now=now)
    if changed:
        add_audit(session, actor_user_id=actor, action="system.parameters.update", resource_type="system_parameters",
                  resource_id=None, result="success", request_id=request_id,
                  summary={"sections": sorted(changes), "keys": sorted(changed),
                           "old": {key: values[key] for key in sorted(changed)},
                           "new": {key: merged[key] for key in sorted(changed)}})
    session.flush()
    return bool(changed)

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ProjectChatCitation
from app.core.errors import AppError
from app.db.models import AIModel, ChatRecord, Project, ValidationRun, ValidationRunItem
from app.domain.ai_provider import evaluate_rag_answer, generate_rag_answer
from app.domain.chat_citations import citation_persistence_payload, validate_citation_markers
from app.domain.chat_conversations import require_conversation_identity
from app.domain.model_usage import record_model_usage
from app.domain.system_prompts import (
    SystemPromptLayer,
    SystemPromptResolution,
    system_prompt_hash,
)

VALIDATION_PASS_THRESHOLD = 0.7


def execute_validation_run(session: Session, run_id: UUID, *, max_items: int | None = None) -> ValidationRun:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.status in {"completed", "cancelled"}:
        return run
    project = session.get(Project, run.project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status != "active":
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        session.commit()
        raise AppError("project_archived", "Archived projects cannot run chat validation", status_code=409)
    _validate_execution_manifest(session, run, project)
    pending_items = list(
        session.scalars(
            select(ValidationRunItem)
            .where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True), ValidationRunItem.status == "pending")
            .order_by(ValidationRunItem.input_ordinal, ValidationRunItem.id)
            .limit(max_items or run.total_count or 1000)
        )
    )
    now = datetime.now(UTC)
    run.status = "running"
    run.started_at = run.started_at or now
    session.commit()
    for item in pending_items:
        session.refresh(run)
        session.refresh(project)
        if project.status != "active":
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            session.commit()
            break
        if run.status == "cancelled":
            break
        _execute_item(session, run, project, item)
    session.refresh(run)
    if run.status == "cancelled":
        return run
    _refresh_run_counts(session, run)
    session.commit()
    session.refresh(run)
    return run


def _execute_item(session: Session, run: ValidationRun, project: Project, item: ValidationRunItem) -> None:
    from app.api.routes import serving

    item.status = "running"
    item.error_message = None
    item.error_code = None
    session.commit()
    started = perf_counter()
    asked_at = datetime.now(UTC)
    chat_model: AIModel | None = None
    provider_result = None
    try:
        _validate_input_item(item)
        retrieval_top_k = int(
            (run.execution_manifest or {})["retrieval_top_k"]
        )
        selected_ids = _uuid_set(item.selected_document_ids) or _uuid_set(run.selected_document_ids)
        conversation_id = uuid4()
        chat_scope_mode = "document_staging" if run.run_scope == "document_staging" else "published"
        require_conversation_identity(session, project_id=project.id, conversation_id=conversation_id,
            user_id=run.created_by, scope_mode=chat_scope_mode, requested_ids=selected_ids, unused_only=True)
        if run.run_scope == "document_staging":
            requested_ids = serving._resolve_document_staging_scope(session, project.id, list(selected_ids))
            citations = serving._search_document_staging_chunks(session, project.id, requested_ids, item.question, retrieval_top_k, source_channel="validation", actor_user_id=run.created_by)
            chat_scope_mode = "document_staging"
        else:
            _manifests, _manifest_ids, requested_ids = serving._resolve_retrieval_scope(session, project.id, list(selected_ids))
            citations = serving._search_published_chunks(session, project.id, requested_ids, item.question, retrieval_top_k, source_channel="validation", actor_user_id=run.created_by)
            chat_scope_mode = "published"
        chat_model = _manifest_model(session, run, "chat_model_id", "Chat") if citations else None
        chat_prompt = _manifest_prompt(run, "chat_prompt") if chat_model is not None else None
        provider_started = perf_counter()
        provider_result = generate_rag_answer(question=item.question, citations=citations, model=chat_model, system_prompt=chat_prompt)
        validate_citation_markers(provider_result.answer, len(citations))
        session.refresh(run)
        if run.status == "cancelled":
            item.status = "cancelled"
            item.error_message = None
            session.commit()
            return
        answered_at = datetime.now(UTC)
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        record = ChatRecord(
            id=uuid4(),
            project_id=project.id,
            document_version_id=next(iter(requested_ids)) if len(requested_ids) == 1 else None,
            scope_mode=chat_scope_mode,
            conversation_id=conversation_id,
            conversation_title=f"Validation: {item.question[:80]}",
            selected_document_version_ids=[str(value) for value in sorted(requested_ids, key=str)],
            question=item.question,
            answer=provider_result.answer,
            reference_docs=[citation_persistence_payload(citation) for citation in citations],
            evaluation="not_evaluated",
            llm_model_id=chat_model.id if chat_model else None,
            embedding_model_id=None,
            prompt_version=provider_result.prompt_version,
            system_prompt_source=provider_result.system_prompt_source,
            system_prompt_version_id=provider_result.system_prompt_version_id,
            system_prompt_content_hash=provider_result.system_prompt_content_hash,
            system_prompt_layers=provider_result.system_prompt_layers,
            token_usage=provider_result.token_usage,
            latency_ms=latency_ms,
            created_by=run.created_by,
            asked_at=asked_at,
            answered_at=answered_at,
            created_at=asked_at,
        )
        session.add(record)
        session.flush([record])
        if chat_model is not None:
            record_model_usage(
                session,
                model=chat_model,
                usage_purpose="validation_answer",
                source_channel="validation",
                status="success",
                token_usage=provider_result.token_usage,
                latency_ms=max(0, int((perf_counter() - provider_started) * 1000)),
                project_id=project.id,
                document_version_id=record.document_version_id,
                chat_record_id=record.id,
                validation_run_id=run.id,
                validation_run_item_id=item.id,
                actor_user_id=run.created_by,
                metadata={"run_scope": run.run_scope},
            )
        item.answer = provider_result.answer
        item.reference_docs = [citation_persistence_payload(citation) for citation in citations]
        item.chat_record_id = record.id
        score, reason, prompt_source, prompt_version_id, prompt_hash, prompt_layers = _score_answer(session, run, item, citations, provider_result.answer)
        item.score = score
        item.evaluation_reason = reason
        item.status = _validation_status(score=score, reason=reason)
        item.system_prompt_source = prompt_source
        item.system_prompt_version_id = prompt_version_id
        item.system_prompt_content_hash = prompt_hash
        item.system_prompt_layers = prompt_layers
        item.latency_ms = latency_ms
        item.token_usage = provider_result.token_usage
        session.commit()
    except AppError as exc:
        if chat_model is not None:
            record_model_usage(
                session,
                model=chat_model,
                usage_purpose="validation_answer",
                source_channel="validation",
                status="failed",
                token_usage=provider_result.token_usage if provider_result is not None else None,
                error_code=exc.code,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                project_id=project.id,
                validation_run_id=run.id,
                validation_run_item_id=item.id,
                actor_user_id=run.created_by,
            )
        item.status = "error"
        item.error_code = exc.code
        item.error_message = exc.message
        item.latency_ms = max(0, int((perf_counter() - started) * 1000))
        session.commit()
    except Exception:
        item.status = "error"
        item.error_code = "validation_item_failed"
        item.error_message = "validation_item_failed"
        item.latency_ms = max(0, int((perf_counter() - started) * 1000))
        session.commit()


def _score_answer(session: Session, run: ValidationRun, item: ValidationRunItem, citations: list[ProjectChatCitation], answer: str | None) -> tuple[float | None, str, str | None, UUID | None, str | None, list[dict] | None]:
    judge_model = _manifest_model(
        session,
        run,
        "judge_model_id",
        "Judge",
        required=False,
    )
    if judge_model is None:
        return None, "judge_not_configured", None, None, None, None
    started = perf_counter()
    try:
        judge_prompt = _manifest_prompt(run, "judge_prompt")
        judged = evaluate_rag_answer(question=item.question, answer=answer, expected_answer=item.expected_answer, expected_keywords=item.expected_keywords, citations=citations, model=judge_model, system_prompt=judge_prompt)
        record_model_usage(
            session,
            model=judge_model,
            usage_purpose="validation_judge",
            source_channel="validation",
            status="success",
            token_usage=judged.token_usage,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=run.project_id,
            validation_run_id=run.id,
            validation_run_item_id=item.id,
            actor_user_id=run.created_by,
        )
        return judged.score, f"judge_model:{judge_model.id}; {judged.reason}", judged.system_prompt_source, judged.system_prompt_version_id, judged.system_prompt_content_hash, judged.system_prompt_layers
    except AppError as exc:
        record_model_usage(
            session,
            model=judge_model,
            usage_purpose="validation_judge",
            source_channel="validation",
            status="failed",
            error_code=exc.code,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=run.project_id,
            validation_run_id=run.id,
            validation_run_item_id=item.id,
            actor_user_id=run.created_by,
        )
        return None, f"judge_failed:{exc.code}; unscored", None, None, None, None


def _canonical_hash(value: dict | list) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_execution_manifest(
    session: Session,
    run: ValidationRun,
    project: Project,
) -> None:
    manifest = run.execution_manifest or {}
    if (
        manifest.get("manifest_version") != "validation-v1"
        or manifest.get("state") != "available"
    ):
        raise AppError(
            "validation_manifest_unavailable",
            "Validation execution manifest is unavailable for this legacy run",
            status_code=409,
        )
    if _canonical_hash(manifest) != run.execution_manifest_hash:
        raise AppError(
            "validation_manifest_integrity_failed",
            "Validation execution manifest integrity check failed",
            status_code=409,
        )
    retrieval_top_k = manifest.get("retrieval_top_k")
    if (
        manifest.get("retrieval_strategy") != "hybrid"
        or not isinstance(retrieval_top_k, int)
        or isinstance(retrieval_top_k, bool)
        or not 1 <= retrieval_top_k <= 100
    ):
        raise AppError(
            "validation_retrieval_manifest_invalid",
            "Validation retrieval settings are invalid or unsupported",
            status_code=409,
        )
    expected_scope = (
        "document_staging" if run.run_scope == "document_staging" else "published"
    )
    selected_ids = sorted(str(value) for value in _uuid_set(run.selected_document_ids))
    if (
        manifest.get("project_id") != str(project.id)
        or manifest.get("project_generation") != project.work_generation
        or manifest.get("scope_mode") != expected_scope
        or sorted(manifest.get("selected_document_version_ids") or [])
        != selected_ids
        or manifest.get("max_attempts") != run.max_attempts
    ):
        raise AppError(
            "validation_manifest_scope_changed",
            "Validation execution scope no longer matches its immutable manifest",
            status_code=409,
        )
    embedding_model = _manifest_model(
        session,
        run,
        "embedding_model_id",
        "Embedding",
    )
    if project.embedding_model_id != embedding_model.id:
        raise AppError(
            "validation_execution_configuration_changed",
            "Project Embedding Model changed after the validation run was created",
            status_code=409,
        )
    chat_model = _manifest_model(
        session,
        run,
        "chat_model_id",
        "Chat",
    )
    if (
        project.llm_model_id is not None
        and project.llm_model_id != chat_model.id
    ):
        raise AppError(
            "validation_execution_configuration_changed",
            "Project Chat Model changed after the validation run was created",
            status_code=409,
        )


def _manifest_model(
    session: Session,
    run: ValidationRun,
    field: str,
    expected_type: str,
    *,
    required: bool = True,
) -> AIModel | None:
    raw_id = (run.execution_manifest or {}).get(field)
    if not raw_id:
        if required:
            raise AppError(
                "validation_model_manifest_invalid",
                "Validation execution manifest is missing a required model",
                status_code=409,
            )
        return None
    try:
        model_id = UUID(str(raw_id))
    except ValueError as exc:
        raise AppError(
            "validation_model_manifest_invalid",
            "Validation execution manifest contains an invalid model identity",
            status_code=409,
        ) from exc
    model = session.get(AIModel, model_id)
    if (
        model is None
        or model.model_type != expected_type
        or model.deleted_at is not None
        or not model.is_active
    ):
        raise AppError(
            "validation_model_unavailable",
            "A model fixed by the validation execution manifest is unavailable",
            status_code=409,
        )
    return model


def _manifest_prompt(run: ValidationRun, field: str) -> SystemPromptResolution:
    prompt = (run.execution_manifest or {}).get(field)
    if not isinstance(prompt, dict) or not isinstance(prompt.get("content"), str):
        raise AppError(
            "validation_prompt_manifest_invalid",
            "Validation execution manifest is missing a prompt snapshot",
            status_code=409,
        )
    if system_prompt_hash(prompt["content"]) != prompt.get("content_hash"):
        raise AppError(
            "validation_prompt_manifest_invalid",
            "Validation prompt snapshot integrity check failed",
            status_code=409,
        )
    layers: list[SystemPromptLayer] = []
    for layer in prompt.get("layers") or []:
        try:
            version_id = UUID(str(layer["version_id"])) if layer.get("version_id") else None
            layers.append(
                SystemPromptLayer(
                    source=str(layer["source"]),
                    version_id=version_id,
                    content_hash=str(layer["content_hash"]),
                    content_length=int(layer["content_length"]),
                    order=int(layer["order"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                "validation_prompt_manifest_invalid",
                "Validation prompt layer metadata is invalid",
                status_code=409,
            ) from exc
    return SystemPromptResolution(
        content=prompt["content"],
        source=str(prompt.get("source") or "backend_default"),
        version_id=UUID(str(prompt["version_id"])) if prompt.get("version_id") else None,
        content_hash=str(prompt["content_hash"]),
        layers=tuple(layers),
    )


def _validate_input_item(item: ValidationRunItem) -> None:
    input_payload = {
        "question": item.question,
        "expected_answer": item.expected_answer,
        "expected_keywords": item.expected_keywords or [],
        "selected_document_ids": item.selected_document_ids or [],
        "category": item.category,
        "priority": item.priority,
    }
    if _canonical_hash(input_payload) != item.input_content_hash:
        raise AppError(
            "validation_input_integrity_failed",
            "Validation input item no longer matches its immutable content hash",
            status_code=409,
        )


def _refresh_run_counts(session: Session, run: ValidationRun) -> None:
    items = list(session.scalars(select(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True))))
    completed = sum(1 for item in items if item.status in {"passed", "needs_review", "completed", "skipped"})
    failed = sum(1 for item in items if item.status in {"failed", "error"})
    run.completed_count = completed
    run.failed_count = failed
    if failed and completed:
        run.status = "partial_failed"
    elif failed and not completed:
        run.status = "failed"
    else:
        run.status = "completed"
    run.completed_at = datetime.now(UTC)


def _validation_status(*, score: float | None, reason: str) -> str:
    if score is None:
        return "needs_review"
    return "passed" if score >= VALIDATION_PASS_THRESHOLD else "failed"


def _uuid_set(values: list | None) -> set[UUID]:
    result: set[UUID] = set()
    for value in values or []:
        try:
            result.add(value if isinstance(value, UUID) else UUID(str(value)))
        except ValueError:
            continue
    return result

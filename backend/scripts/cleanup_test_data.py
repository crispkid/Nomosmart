from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings, neo4j_driver_options
from app.db.models import (
    AIModel,
    AIModelUsageEvent,
    ActiveVersionManifest,
    ApprovalRequest,
    ApprovalTask,
    AuditLog,
    ChatRecord,
    Chunk,
    ChunkTag,
    DataConnection,
    DataSyncRun,
    Document,
    DocumentReference,
    DocumentReferenceEvent,
    DocumentVersion,
    DocumentVersionTag,
    EmbeddingBuild,
    EmbeddingProfile,
    ExternalGroupRoleMapping,
    FileScanRun,
    GraphSyncJob,
    IdentitySetting,
    IdentityUnlockGrant,
    Notification,
    OutboxEvent,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectMember,
    ProjectOwner,
    ReviewRecord,
    Role,
    RolePermission,
    RoleUser,
    RevokedAuthToken,
    SessionExpiredFormDraft,
    SystemParameter,
    SystemPrompt,
    SystemPromptVersion,
    Tag,
    User,
    ValidationQuestion,
    ValidationRun,
    ValidationRunItem,
)
from app.db.session import get_engine

DEFAULT_PREFIXES = (
    "codex-live-",
    "milestone7-live-",
    "Milestone 7 Live ",
    "Milestone 7 Embedding ",
    "Milestone 8B ",
    "OCR Live Acceptance ",
)
DEFAULT_VALIDATION_FILES = ("milestone8b-live.csv",)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely remove NomoSmart automated test data.")
    parser.add_argument("--apply", action="store_true", help="Commit deletions. Without this flag the script is dry-run only.")
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Additional exact prefix to treat as test data. May be provided multiple times.",
    )
    parser.add_argument(
        "--older-than-hours",
        type=float,
        default=0,
        help="Only delete matched rows older than this many hours. Default 0 deletes all matched automated test data.",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Best-effort cleanup of matching OpenSearch indices and Neo4j graph nodes.",
    )
    args = parser.parse_args()

    prefixes = tuple(dict.fromkeys((*DEFAULT_PREFIXES, *[item for item in args.prefix if item.strip()])))
    cutoff = datetime.now(UTC) - timedelta(hours=args.older_than_hours) if args.older_than_hours > 0 else None
    settings = get_settings()
    engine = get_engine()

    with Session(engine, expire_on_commit=False) as session:
        scope = _collect_scope(session, prefixes=prefixes, cutoff=cutoff)
        counts = _count_scope(session, scope)
        summary: dict[str, object] = {
            "mode": "apply" if args.apply else "dry-run",
            "prefixes": prefixes,
            "older_than_hours": args.older_than_hours,
            "counts": counts,
        }

        if args.apply:
            deleted = _delete_scope(session, scope)
            session.commit()
            summary["deleted"] = deleted
        else:
            summary["deleted"] = {}
            session.rollback()

        if args.include_external:
            summary["external"] = _cleanup_external(scope, settings=settings, apply=args.apply)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _collect_scope(session: Session, *, prefixes: Sequence[str], cutoff: datetime | None) -> dict[str, list[UUID] | list[str]]:
    user_ids = _ids(
        session,
        select(User.id).where(
            _prefix_filter(User.keycloak_user_id, prefixes)
            | _prefix_filter(User.display_name, prefixes)
            | _prefix_filter(User.email, prefixes)
        ),
    )
    role_ids = _ids(session, select(Role.id).where(_prefix_filter(Role.name, prefixes)))
    model_ids = _ids(session, select(AIModel.id).where(_prefix_filter(AIModel.name, prefixes)))

    project_predicate = _prefix_filter(Project.name, prefixes)
    if user_ids:
        project_predicate = project_predicate | Project.created_by.in_(user_ids)
    if cutoff is not None:
        project_predicate = project_predicate & (Project.created_at < cutoff)
    project_ids = _ids(session, select(Project.id).where(project_predicate))

    document_predicate = _prefix_filter(Document.title, prefixes) | _prefix_filter(Document.document_code, prefixes)
    if project_ids:
        document_predicate = document_predicate | Document.project_id.in_(project_ids)
    if user_ids:
        document_predicate = document_predicate | Document.created_by.in_(user_ids)
    document_ids = _ids(session, select(Document.id).where(document_predicate))

    version_predicate = _prefix_filter(DocumentVersion.original_file_name, prefixes)
    if project_ids:
        version_predicate = version_predicate | DocumentVersion.project_id.in_(project_ids)
    if document_ids:
        version_predicate = version_predicate | DocumentVersion.document_id.in_(document_ids)
    version_ids = _ids(session, select(DocumentVersion.id).where(version_predicate))

    pipeline_predicate = PipelineRun.id.is_(None)
    if project_ids:
        pipeline_predicate = pipeline_predicate | PipelineRun.project_id.in_(project_ids)
    if document_ids:
        pipeline_predicate = pipeline_predicate | PipelineRun.document_id.in_(document_ids)
    if version_ids:
        pipeline_predicate = pipeline_predicate | PipelineRun.document_version_id.in_(version_ids)
    if user_ids:
        pipeline_predicate = pipeline_predicate | PipelineRun.triggered_by.in_(user_ids)
    pipeline_ids = _ids(session, select(PipelineRun.id).where(pipeline_predicate))

    validation_predicate = ValidationRun.uploaded_file_name.in_(DEFAULT_VALIDATION_FILES) | _prefix_filter(ValidationRun.uploaded_file_name, prefixes)
    if project_ids:
        validation_predicate = validation_predicate | ValidationRun.project_id.in_(project_ids)
    if version_ids:
        validation_predicate = validation_predicate | ValidationRun.document_version_id.in_(version_ids)
    if user_ids:
        validation_predicate = validation_predicate | ValidationRun.created_by.in_(user_ids)
    validation_run_ids = _ids(session, select(ValidationRun.id).where(validation_predicate))

    chat_predicate = _prefix_filter(ChatRecord.conversation_title, prefixes)
    if project_ids:
        chat_predicate = chat_predicate | ChatRecord.project_id.in_(project_ids)
    if version_ids:
        chat_predicate = chat_predicate | ChatRecord.document_version_id.in_(version_ids)
    if user_ids:
        chat_predicate = chat_predicate | ChatRecord.created_by.in_(user_ids)
    chat_record_ids = _ids(session, select(ChatRecord.id).where(chat_predicate))

    chunk_predicate = _prefix_filter(Chunk.title, prefixes)
    if project_ids:
        chunk_predicate = chunk_predicate | Chunk.project_id.in_(project_ids)
    if document_ids:
        chunk_predicate = chunk_predicate | Chunk.document_id.in_(document_ids)
    if version_ids:
        chunk_predicate = chunk_predicate | Chunk.document_version_id.in_(version_ids)
    chunk_ids = _ids(session, select(Chunk.id).where(chunk_predicate))

    tag_predicate = _prefix_filter(Tag.name, prefixes)
    if project_ids:
        tag_predicate = tag_predicate | Tag.project_id.in_(project_ids)
    tag_ids = _ids(session, select(Tag.id).where(tag_predicate))

    reference_predicate = DocumentReference.id.is_(None)
    if project_ids:
        reference_predicate = (
            reference_predicate
            | DocumentReference.target_project_id.in_(project_ids)
            | DocumentReference.source_project_id.in_(project_ids)
        )
    if document_ids:
        reference_predicate = (
            reference_predicate
            | DocumentReference.target_document_id.in_(document_ids)
            | DocumentReference.source_document_id.in_(document_ids)
        )
    document_reference_ids = _ids(session, select(DocumentReference.id).where(reference_predicate))

    data_connection_predicate = _prefix_filter(DataConnection.name, prefixes)
    if project_ids:
        data_connection_predicate = data_connection_predicate | DataConnection.project_id.in_(project_ids)
    if user_ids:
        data_connection_predicate = data_connection_predicate | DataConnection.created_by.in_(user_ids)
    data_connection_ids = _ids(session, select(DataConnection.id).where(data_connection_predicate))

    embedding_build_ids = _ids(
        session,
        select(EmbeddingBuild.id).where(
            _any_scope(
                (
                    EmbeddingBuild.project_id.in_(project_ids) if project_ids else None,
                    EmbeddingBuild.document_id.in_(document_ids) if document_ids else None,
                    EmbeddingBuild.document_version_id.in_(version_ids) if version_ids else None,
                )
            )
        ),
    )
    index_names = [
        value
        for value in session.scalars(select(EmbeddingBuild.index_name).where(EmbeddingBuild.id.in_(embedding_build_ids)))
        if value
    ]

    prompt_predicate = SystemPrompt.id.is_(None)
    if model_ids:
        prompt_predicate = prompt_predicate | SystemPrompt.model_id.in_(model_ids)
    if user_ids:
        prompt_predicate = prompt_predicate | SystemPrompt.created_by.in_(user_ids) | SystemPrompt.updated_by.in_(user_ids)
    prompt_ids = _ids(session, select(SystemPrompt.id).where(prompt_predicate))
    if user_ids:
        prompt_ids.extend(
            _ids(session, select(SystemPromptVersion.prompt_id).where(SystemPromptVersion.created_by.in_(user_ids)))
        )
    prompt_ids = sorted(set(prompt_ids))

    return {
        "user_ids": user_ids,
        "role_ids": role_ids,
        "model_ids": model_ids,
        "project_ids": project_ids,
        "document_ids": document_ids,
        "version_ids": version_ids,
        "pipeline_ids": pipeline_ids,
        "validation_run_ids": validation_run_ids,
        "chat_record_ids": chat_record_ids,
        "chunk_ids": chunk_ids,
        "tag_ids": tag_ids,
        "document_reference_ids": document_reference_ids,
        "data_connection_ids": data_connection_ids,
        "embedding_build_ids": embedding_build_ids,
        "prompt_ids": prompt_ids,
        "index_names": sorted(set(index_names)),
    }


def _count_scope(session: Session, scope: dict[str, list[UUID] | list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["users"] = len(scope["user_ids"])
    counts["roles"] = len(scope["role_ids"])
    counts["ai_models"] = len(scope["model_ids"])
    counts["projects"] = len(scope["project_ids"])
    counts["documents"] = len(scope["document_ids"])
    counts["document_versions"] = len(scope["version_ids"])
    counts["pipeline_runs"] = len(scope["pipeline_ids"])
    counts["validation_runs"] = len(scope["validation_run_ids"])
    counts["chat_records"] = len(scope["chat_record_ids"])
    counts["chunks"] = len(scope["chunk_ids"])
    counts["tags"] = len(scope["tag_ids"])
    counts["document_references"] = len(scope["document_reference_ids"])
    counts["data_connections"] = len(scope["data_connection_ids"])
    counts["embedding_builds"] = len(scope["embedding_build_ids"])
    counts["system_prompts"] = len(scope["prompt_ids"])
    counts["opensearch_indices"] = len(scope["index_names"])

    pipeline_ids = scope["pipeline_ids"]
    version_ids = scope["version_ids"]
    validation_run_ids = scope["validation_run_ids"]
    project_ids = scope["project_ids"]
    model_ids = scope["model_ids"]
    document_ids = scope["document_ids"]
    user_ids = scope["user_ids"]
    chat_record_ids = scope["chat_record_ids"]
    counts["ai_model_usage_events"] = _count(
        session,
        AIModelUsageEvent,
        _any_scope(
            (
                AIModelUsageEvent.model_id.in_(model_ids) if model_ids else None,
                AIModelUsageEvent.project_id.in_(project_ids) if project_ids else None,
                AIModelUsageEvent.document_id.in_(document_ids) if document_ids else None,
                AIModelUsageEvent.document_version_id.in_(version_ids) if version_ids else None,
                AIModelUsageEvent.pipeline_run_id.in_(pipeline_ids) if pipeline_ids else None,
                AIModelUsageEvent.chat_record_id.in_(chat_record_ids) if chat_record_ids else None,
                AIModelUsageEvent.validation_run_id.in_(validation_run_ids) if validation_run_ids else None,
                AIModelUsageEvent.actor_user_id.in_(user_ids) if user_ids else None,
            )
        ),
    )
    if pipeline_ids:
        counts["pipeline_run_steps"] = _count(session, PipelineRunStep, PipelineRunStep.run_id.in_(pipeline_ids))
    if version_ids:
        counts["file_scan_runs"] = _count(session, FileScanRun, FileScanRun.document_version_id.in_(version_ids))
        counts["approval_requests"] = _count(session, ApprovalRequest, ApprovalRequest.document_version_id.in_(version_ids))
        counts["approval_tasks"] = _count(session, ApprovalTask, ApprovalTask.document_version_id.in_(version_ids))
        counts["review_records"] = _count(session, ReviewRecord, ReviewRecord.document_version_id.in_(version_ids))
        counts["graph_sync_jobs"] = _count(session, GraphSyncJob, GraphSyncJob.document_version_id.in_(version_ids))
        counts["active_version_manifests"] = _count(session, ActiveVersionManifest, ActiveVersionManifest.document_version_id.in_(version_ids))
    if validation_run_ids:
        counts["validation_run_items"] = _count(session, ValidationRunItem, ValidationRunItem.run_id.in_(validation_run_ids))
    if project_ids:
        counts["notifications"] = _count(session, Notification, Notification.project_id.in_(project_ids))
        counts["validation_questions"] = _count(session, ValidationQuestion, ValidationQuestion.project_id.in_(project_ids))
    if user_ids:
        counts["audit_logs"] = _count(session, AuditLog, AuditLog.actor_user_id.in_(user_ids))
    return counts


def _delete_scope(session: Session, scope: dict[str, list[UUID] | list[str]]) -> dict[str, int]:
    deleted: dict[str, int] = {}
    user_ids = scope["user_ids"]
    role_ids = scope["role_ids"]
    model_ids = scope["model_ids"]
    project_ids = scope["project_ids"]
    document_ids = scope["document_ids"]
    version_ids = scope["version_ids"]
    pipeline_ids = scope["pipeline_ids"]
    validation_run_ids = scope["validation_run_ids"]
    chat_record_ids = scope["chat_record_ids"]
    chunk_ids = scope["chunk_ids"]
    tag_ids = scope["tag_ids"]
    reference_ids = scope["document_reference_ids"]
    data_connection_ids = scope["data_connection_ids"]
    embedding_build_ids = scope["embedding_build_ids"]
    prompt_ids = scope["prompt_ids"]

    _delete(
        deleted,
        session,
        AIModelUsageEvent,
        _any_scope(
            (
                AIModelUsageEvent.model_id.in_(model_ids) if model_ids else None,
                AIModelUsageEvent.project_id.in_(project_ids) if project_ids else None,
                AIModelUsageEvent.document_id.in_(document_ids) if document_ids else None,
                AIModelUsageEvent.document_version_id.in_(version_ids) if version_ids else None,
                AIModelUsageEvent.pipeline_run_id.in_(pipeline_ids) if pipeline_ids else None,
                AIModelUsageEvent.chat_record_id.in_(chat_record_ids) if chat_record_ids else None,
                AIModelUsageEvent.validation_run_id.in_(validation_run_ids) if validation_run_ids else None,
                AIModelUsageEvent.actor_user_id.in_(user_ids) if user_ids else None,
            )
        ),
    )

    _delete(deleted, session, DocumentReferenceEvent, DocumentReferenceEvent.reference_id.in_(reference_ids) if reference_ids else None)
    _delete(deleted, session, DocumentReference, DocumentReference.id.in_(reference_ids) if reference_ids else None)
    _delete(deleted, session, ValidationRunItem, ValidationRunItem.run_id.in_(validation_run_ids) if validation_run_ids else None)
    _delete(deleted, session, ValidationRun, ValidationRun.id.in_(validation_run_ids) if validation_run_ids else None)
    _delete(deleted, session, ChatRecord, ChatRecord.id.in_(chat_record_ids) if chat_record_ids else None)
    _delete(
        deleted,
        session,
        Notification,
        _any_scope(
            (
                Notification.project_id.in_(project_ids) if project_ids else None,
                Notification.recipient_user_id.in_(user_ids) if user_ids else None,
            )
        ),
    )
    _delete(deleted, session, ValidationQuestion, ValidationQuestion.project_id.in_(project_ids) if project_ids else None)
    _delete(deleted, session, OutboxEvent, OutboxEvent.aggregate_id.in_([*validation_run_ids, *pipeline_ids]) if validation_run_ids or pipeline_ids else None)

    if version_ids:
        session.execute(update(ApprovalRequest).where(ApprovalRequest.document_version_id.in_(version_ids)).values(current_task_id=None))
    _delete(deleted, session, ReviewRecord, ReviewRecord.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, ApprovalTask, ApprovalTask.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, ApprovalRequest, ApprovalRequest.document_version_id.in_(version_ids) if version_ids else None)

    _delete(deleted, session, PipelineRunStep, PipelineRunStep.run_id.in_(pipeline_ids) if pipeline_ids else None)
    _delete(deleted, session, PipelineRun, PipelineRun.id.in_(pipeline_ids) if pipeline_ids else None)
    _delete(deleted, session, FileScanRun, FileScanRun.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, ActiveVersionManifest, ActiveVersionManifest.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, GraphSyncJob, GraphSyncJob.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, EmbeddingBuild, EmbeddingBuild.id.in_(embedding_build_ids) if embedding_build_ids else None)
    _delete(deleted, session, ChunkTag, ChunkTag.chunk_id.in_(chunk_ids) if chunk_ids else None)
    _delete(deleted, session, DocumentVersionTag, DocumentVersionTag.document_version_id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, Chunk, Chunk.id.in_(chunk_ids) if chunk_ids else None)
    _delete(deleted, session, Tag, Tag.id.in_(tag_ids) if tag_ids else None)
    _delete(
        deleted,
        session,
        DataSyncRun,
        _any_scope(
            (
                DataSyncRun.document_version_id.in_(version_ids) if version_ids else None,
                DataSyncRun.data_connection_id.in_(data_connection_ids) if data_connection_ids else None,
            )
        ),
    )
    _delete(deleted, session, DataConnection, DataConnection.id.in_(data_connection_ids) if data_connection_ids else None)
    _delete(deleted, session, DocumentVersion, DocumentVersion.id.in_(version_ids) if version_ids else None)
    _delete(deleted, session, Document, Document.id.in_(document_ids) if document_ids else None)
    _delete(deleted, session, ProjectOwner, ProjectOwner.project_id.in_(project_ids) if project_ids else None)
    _delete(deleted, session, ProjectMember, ProjectMember.project_id.in_(project_ids) if project_ids else None)
    _delete(deleted, session, Project, Project.id.in_(project_ids) if project_ids else None)

    if prompt_ids:
        session.execute(update(SystemPrompt).where(SystemPrompt.id.in_(prompt_ids)).values(current_version_id=None))
    _delete(deleted, session, SystemPromptVersion, SystemPromptVersion.prompt_id.in_(prompt_ids) if prompt_ids else None)
    _delete(deleted, session, SystemPrompt, SystemPrompt.id.in_(prompt_ids) if prompt_ids else None)
    _delete(deleted, session, EmbeddingProfile, EmbeddingProfile.model_id.in_(model_ids) if model_ids else None)
    _delete(deleted, session, AIModel, AIModel.id.in_(model_ids) if model_ids else None)

    _delete(deleted, session, RolePermission, RolePermission.role_id.in_(role_ids) if role_ids else None)
    _delete(deleted, session, RoleUser, _any_scope((RoleUser.role_id.in_(role_ids) if role_ids else None, RoleUser.user_id.in_(user_ids) if user_ids else None)))
    _delete(deleted, session, Role, Role.id.in_(role_ids) if role_ids else None)
    if user_ids:
        session.execute(update(User).where(User.manager_user_id.in_(user_ids)).values(manager_user_id=None))
        session.execute(update(User).where(User.manager_delegate_user_id.in_(user_ids)).values(manager_delegate_user_id=None))
        session.execute(update(SystemParameter).where(SystemParameter.updated_by.in_(user_ids)).values(updated_by=None))
        session.execute(update(IdentitySetting).where(IdentitySetting.created_by.in_(user_ids)).values(created_by=None))
        session.execute(update(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.created_by.in_(user_ids)).values(created_by=None))
        session.execute(update(DocumentVersion).where(DocumentVersion.published_by.in_(user_ids)).values(published_by=None))
        session.execute(update(Chunk).where(Chunk.edited_by.in_(user_ids)).values(edited_by=None))
        session.execute(update(ChatRecord).where(ChatRecord.deleted_by.in_(user_ids)).values(deleted_by=None))
        session.execute(update(ValidationQuestion).where(ValidationQuestion.created_by.in_(user_ids)).values(created_by=None))
    _delete(deleted, session, IdentityUnlockGrant, IdentityUnlockGrant.user_id.in_(user_ids) if user_ids else None)
    _delete(deleted, session, SessionExpiredFormDraft, SessionExpiredFormDraft.user_id.in_(user_ids) if user_ids else None)
    _delete(deleted, session, RevokedAuthToken, RevokedAuthToken.revoked_by.in_(user_ids) if user_ids else None)
    _delete(deleted, session, AuditLog, AuditLog.actor_user_id.in_(user_ids) if user_ids else None)
    _delete(deleted, session, User, User.id.in_(user_ids) if user_ids else None)
    return deleted


def _cleanup_external(scope: dict[str, list[UUID] | list[str]], *, settings, apply: bool) -> dict[str, object]:
    result: dict[str, object] = {"opensearch": [], "neo4j": []}
    index_names = [name for name in scope["index_names"] if isinstance(name, str) and _is_safe_index_name(name, settings.opensearch_index_prefix)]
    if apply:
        deleted_indices = []
        for index_name in index_names:
            if _delete_opensearch_index(settings, index_name):
                deleted_indices.append(index_name)
        result["opensearch"] = deleted_indices
        if scope["project_ids"] or scope["document_ids"] or scope["version_ids"]:
            result["neo4j"] = _delete_neo4j_nodes(
                settings,
                project_ids=scope["project_ids"],
                document_ids=scope["document_ids"],
                version_ids=scope["version_ids"],
            )
    else:
        result["opensearch"] = index_names
        result["neo4j"] = {
            "project_ids": [str(value) for value in scope["project_ids"]],
            "document_ids": [str(value) for value in scope["document_ids"]],
            "version_ids": [str(value) for value in scope["version_ids"]],
        }
    return result


def _delete_opensearch_index(settings, index_name: str) -> bool:
    base = settings.opensearch_url.rstrip("/")
    request = urllib.request.Request(f"{base}/{index_name}", method="DELETE")
    username = settings.opensearch_username.get_secret_value()
    password = settings.opensearch_password.get_secret_value()
    if username or password:
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("authorization", f"Basic {token}")
    context = None if settings.opensearch_verify_tls else ssl._create_unverified_context()  # noqa: SLF001
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except Exception:
        return False


def _delete_neo4j_nodes(settings, *, project_ids: Iterable[UUID], document_ids: Iterable[UUID], version_ids: Iterable[UUID]) -> dict[str, int | str]:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username.get_secret_value(), settings.neo4j_password.get_secret_value()),
            **neo4j_driver_options(settings),
        )
        try:
            with driver.session(database=settings.neo4j_database) as session:
                result = session.execute_write(
                    lambda tx: tx.run(
                        """
                        MATCH (n)
                        WHERE n.id IN $ids
                        WITH collect(n) AS nodes, count(n) AS deleted
                        FOREACH (node IN nodes | DETACH DELETE node)
                        RETURN deleted
                        """,
                        ids=[str(value) for value in (*project_ids, *document_ids, *version_ids)],
                    ).single()
                )
            return {"deleted": int(result["deleted"] if result else 0)}
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001 - external cleanup is best effort
        return {"error": str(exc)}


def _prefix_filter(column, prefixes: Sequence[str]):
    return or_(*[column.ilike(f"{prefix}%") for prefix in prefixes])


def _any_scope(expressions: Iterable[object | None]):
    present = [expression for expression in expressions if expression is not None]
    if not present:
        return False
    return or_(*present)


def _ids(session: Session, statement) -> list[UUID]:
    return list(session.scalars(statement))


def _count(session: Session, model, predicate) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(predicate)) or 0)


def _delete(deleted: dict[str, int], session: Session, model, predicate) -> None:
    if predicate is None or predicate is False:
        deleted[model.__tablename__] = 0
        return
    result = session.execute(delete(model).where(predicate))
    deleted[model.__tablename__] = int(result.rowcount or 0)


def _is_safe_index_name(index_name: str, configured_prefix: str) -> bool:
    safe_fragments = ("-m7-", "codex-live", "milestone7", "milestone8b")
    return index_name.startswith(configured_prefix) and any(fragment in index_name.lower() for fragment in safe_fragments)


if __name__ == "__main__":
    raise SystemExit(main())

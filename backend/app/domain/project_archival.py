from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    AIModelUsageEvent,
    ActiveVersionManifest,
    ApprovalRequest,
    ApprovalTask,
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
    EmbeddingBuildVector,
    FileScanRun,
    GraphSyncJob,
    IntegrationClientProjectScope,
    OutboxEvent,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectArchiveRun,
    ReviewRecord,
    Tag,
    ValidationRun,
    ValidationRunItem,
)
from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter
from app.integrations.s3_storage import S3ObjectStorage
from app.services.audit import add_audit


ARCHIVE_CLEANUP_TOPIC = "project.archive.cleanup.requested"
COMPLETED_VERSION_STATUSES = ("active", "inactive")


def completed_version_clause():
    return DocumentVersion.published_at.is_not(None), DocumentVersion.status.in_(COMPLETED_VERSION_STATUSES)


def archive_impact(session: Session, project: Project) -> dict[str, int | str | UUID]:
    completed = list(session.scalars(select(DocumentVersion).where(DocumentVersion.project_id == project.id, *completed_version_clause())))
    unfinished = _unfinished_versions(session, project.id)
    unfinished_ids = [version.id for version in unfinished]
    retained = _retained_versions(session, unfinished)
    completed_document_ids = {version.document_id for version in completed}
    unfinished_document_ids = {version.document_id for version in unfinished}
    return {
        "project_id": project.id,
        "project_name": project.name,
        "lock_version": project.lock_version,
        "completed_document_count": len(completed_document_ids),
        "completed_version_count": len(completed),
        "unfinished_version_count": len(unfinished),
        "unfinished_document_count": len(unfinished_document_ids),
        "deleted_document_count": len(unfinished_document_ids - completed_document_ids),
        "unfinished_file_count": len(_object_references(session, unfinished) - _object_references(session, retained)),
        "unfinished_pipeline_count": len(_unfinished_pipeline_ids(session, project.id, unfinished_ids)),
        "unfinished_sync_count": len(_unfinished_sync_ids(session, project.id, unfinished_ids)),
        "unfinished_validation_count": len(_unfinished_validation_ids(session, project.id, unfinished_ids)),
        "unfinished_approval_count": _count_for_ids(session, ApprovalRequest, ApprovalRequest.document_version_id, unfinished_ids),
        "unfinished_staging_index_count": len({version.extraction_artifact_uri for version in unfinished if version.extraction_artifact_uri and version.extraction_artifact_uri.startswith("opensearch://")}),
        "unfinished_embedding_build_count": _count_for_ids(session, EmbeddingBuild, EmbeddingBuild.document_version_id, unfinished_ids),
        "unfinished_graph_count": _count_for_ids(session, GraphSyncJob, GraphSyncJob.document_version_id, unfinished_ids),
    }


def _count_for_ids(session: Session, model, column, ids: list[UUID]) -> int:
    if not ids:
        return 0
    return int(session.scalar(select(func.count()).select_from(model).where(column.in_(ids))) or 0)


def _unfinished_pipeline_ids(session: Session, project_id: UUID, version_ids: list[UUID]) -> list[UUID]:
    return list(
        session.scalars(
            select(PipelineRun.id).where(
                PipelineRun.project_id == project_id,
                or_(PipelineRun.document_version_id.in_(version_ids), PipelineRun.status != "completed"),
            )
        )
    )


def _unfinished_sync_ids(session: Session, project_id: UUID, version_ids: list[UUID]) -> list[UUID]:
    return list(
        session.scalars(
            select(DataSyncRun.id)
            .join(DataConnection, DataConnection.id == DataSyncRun.data_connection_id)
            .where(
                DataConnection.project_id == project_id,
                or_(DataSyncRun.document_version_id.in_(version_ids), DataSyncRun.status.not_in(("success", "unchanged"))),
            )
        )
    )


def _unfinished_validation_ids(session: Session, project_id: UUID, version_ids: list[UUID]) -> list[UUID]:
    return list(
        session.scalars(
            select(ValidationRun.id).where(
                ValidationRun.project_id == project_id,
                or_(ValidationRun.document_version_id.in_(version_ids), ValidationRun.status != "completed"),
            )
        )
    )


def begin_project_archive(
    session: Session,
    *,
    project_id: UUID,
    actor_user_id: UUID,
    lock_version: int,
    confirmation_name: str,
    request_id: str | None,
) -> Project:
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status == "archived":
        if confirmation_name != project.name:
            raise AppError("project_confirmation_mismatch", "Project name confirmation does not match", status_code=422)
        return project
    if project.lock_version != lock_version:
        raise AppError("stale_project_version", "Project was changed by another request", status_code=409)
    if confirmation_name != project.name:
        raise AppError("project_confirmation_mismatch", "Project name confirmation does not match", status_code=422)

    impact = archive_impact(session, project)
    now = datetime.now(UTC)
    project.status = "archived"
    project.work_generation += 1
    project.archived_at = now
    project.archived_by = actor_user_id
    project.lock_version += 1
    project.updated_at = now

    session.execute(
        update(DataConnection)
        .where(DataConnection.project_id == project.id)
        .values(enabled=False, next_run_at=None, credential_encrypted=None, credential_secret_ref=None, updated_at=now)
    )
    session.execute(delete(IntegrationClientProjectScope).where(IntegrationClientProjectScope.project_id == project.id))
    session.execute(update(DocumentReference).where(DocumentReference.source_project_id == project.id).values(status="source_archived", updated_at=now))

    run = ProjectArchiveRun(
        id=uuid4(),
        project_id=project.id,
        status="queued",
        requested_by=actor_user_id,
        project_generation=project.work_generation,
        queued_at=now,
        unfinished_version_count=int(impact["unfinished_version_count"]),
        checkpoint={"impact": {key: value for key, value in impact.items() if key not in {"project_id", "project_name"}}},
    )
    session.add(run)
    session.add(
        OutboxEvent(
            id=uuid4(),
            topic=ARCHIVE_CLEANUP_TOPIC,
            aggregate_type="project_archive_run",
            aggregate_id=run.id,
            project_id=project.id,
            project_generation=project.work_generation,
            payload={"run_id": str(run.id), "project_id": str(project.id), "project_generation": project.work_generation},
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
    )
    add_audit(
        session,
        actor_user_id=actor_user_id,
        action="project.archive.requested",
        resource_type="project",
        resource_id=project.id,
        result="success",
        request_id=request_id,
        summary={"archive_run_id": str(run.id), **{key: value for key, value in impact.items() if key not in {"project_id", "project_name"}}},
    )
    return project


def retry_project_archive_cleanup(session: Session, *, project: Project, actor_user_id: UUID, request_id: str | None) -> ProjectArchiveRun:
    run = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.project_id == project.id).order_by(ProjectArchiveRun.queued_at.desc(), ProjectArchiveRun.id.desc()).with_for_update().limit(1))
    if run is None or run.status != "failed":
        raise AppError("archive_cleanup_not_retryable", "Archive cleanup is not in a retryable state", status_code=409)
    now = datetime.now(UTC)
    run.status = "queued"
    run.queued_at = now
    run.completed_at = None
    run.error_code = None
    run.error_message = None
    session.add(OutboxEvent(id=uuid4(), topic=ARCHIVE_CLEANUP_TOPIC, aggregate_type="project_archive_run", aggregate_id=run.id, project_id=project.id, project_generation=run.project_generation, payload={"run_id": str(run.id), "project_id": str(project.id), "project_generation": run.project_generation}, status="pending", attempts=0, available_at=now, created_at=now))
    add_audit(session, actor_user_id=actor_user_id, action="project.archive.cleanup.retried", resource_type="project", resource_id=project.id, result="success", request_id=request_id, summary={"archive_run_id": str(run.id), "next_attempt": run.attempt + 1})
    return run


def execute_project_archive_cleanup(session: Session, *, settings: Settings, run_id: UUID) -> None:
    run = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.id == run_id).with_for_update())
    if run is None or run.status == "completed":
        return
    now = datetime.now(UTC)
    if run.status == "running" and run.lease_expires_at is not None and run.lease_expires_at > now:
        return
    project = session.get(Project, run.project_id)
    if project is None or project.status != "archived" or project.work_generation != run.project_generation:
        _fail_run(session, run, "archive_project_state_invalid")
        session.commit()
        return

    run.status = "running"
    run.started_at = run.started_at or now
    run.heartbeat_at = now
    run.lease_token = uuid4()
    run.lease_expires_at = now + timedelta(hours=1)
    run.attempt += 1
    run.error_code = None
    run.error_message = None
    session.commit()

    unfinished_versions = _unfinished_versions(session, project.id)
    retained_versions = _retained_versions(session, unfinished_versions)
    try:
        deleted_s3 = _delete_unfinished_s3_objects(settings, session, unfinished_versions, retained_versions)
        deleted_search = _delete_unfinished_search_artifacts(settings, unfinished_versions, retained_versions)
        deleted_graph = _delete_unfinished_graph_artifacts(settings, unfinished_versions)
        counts = _purge_unfinished_database_rows(session, project.id, unfinished_versions)
        run = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.id == run_id).with_for_update())
        if run is None:
            session.rollback()
            return
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.heartbeat_at = run.completed_at
        run.lease_token = None
        run.lease_expires_at = None
        run.deleted_version_count = counts["versions"]
        run.deleted_document_count = counts["documents"]
        run.deleted_s3_object_count = deleted_s3
        run.deleted_search_document_count = deleted_search
        run.deleted_graph_version_count = deleted_graph
        run.checkpoint = {**(run.checkpoint or {}), "completed": True}
        add_audit(session, actor_user_id=run.requested_by, action="project.archive.cleanup.completed", resource_type="project", resource_id=project.id, result="success", request_id=None, summary={"archive_run_id": str(run.id), **counts, "s3_objects": deleted_s3, "search_artifacts": deleted_search, "graph_versions": deleted_graph})
        session.commit()
    except Exception as exc:
        session.rollback()
        run = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.id == run_id).with_for_update())
        if run is not None:
            _fail_run(session, run, getattr(exc, "code", "project_archive_cleanup_failed"))
            add_audit(session, actor_user_id=run.requested_by, action="project.archive.cleanup.failed", resource_type="project", resource_id=run.project_id, result="failed", request_id=None, summary={"archive_run_id": str(run.id), "error_code": run.error_code, "attempt": run.attempt})
            session.commit()
        raise


def recover_stale_project_archive_runs(session: Session) -> int:
    now = datetime.now(UTC)
    stale_runs = list(session.scalars(select(ProjectArchiveRun).where(ProjectArchiveRun.status == "running", ProjectArchiveRun.lease_expires_at < now).with_for_update(skip_locked=True).limit(20)))
    for run in stale_runs:
        run.status = "queued"
        run.queued_at = now
        run.lease_token = None
        run.lease_expires_at = None
        run.error_code = "archive_cleanup_lease_expired"
        run.error_message = "Archive cleanup lease expired and was queued again"
        session.add(OutboxEvent(id=uuid4(), topic=ARCHIVE_CLEANUP_TOPIC, aggregate_type="project_archive_run", aggregate_id=run.id, project_id=run.project_id, project_generation=run.project_generation, payload={"run_id": str(run.id), "project_id": str(run.project_id), "project_generation": run.project_generation}, status="pending", attempts=0, available_at=now, created_at=now))
    return len(stale_runs)


def _retained_versions(session: Session, unfinished_versions: list[DocumentVersion]) -> list[DocumentVersion]:
    unfinished_ids = [version.id for version in unfinished_versions]
    query = select(DocumentVersion)
    if unfinished_ids:
        query = query.where(DocumentVersion.id.not_in(unfinished_ids))
    return list(session.scalars(query))


def _unfinished_versions(session: Session, project_id: UUID) -> list[DocumentVersion]:
    return list(session.scalars(select(DocumentVersion).where(DocumentVersion.project_id == project_id, or_(DocumentVersion.published_at.is_(None), DocumentVersion.status.not_in(COMPLETED_VERSION_STATUSES)))))


def _object_references(session: Session, versions: list[DocumentVersion]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    version_ids = [version.id for version in versions]
    for version in versions:
        if version.storage_bucket and version.storage_key:
            refs.add((version.storage_bucket, version.storage_key))
        for uri in (version.original_snapshot_uri, version.markdown_artifact_uri, version.extraction_artifact_uri):
            parsed = _s3_uri(uri)
            if parsed:
                refs.add(parsed)
    if not version_ids:
        return refs
    for scan in session.scalars(select(FileScanRun).where(FileScanRun.document_version_id.in_(version_ids))):
        if scan.quarantine_bucket and scan.quarantine_key:
            refs.add((scan.quarantine_bucket, scan.quarantine_key))
        if scan.accepted_bucket and scan.accepted_key:
            refs.add((scan.accepted_bucket, scan.accepted_key))
    pipeline_refs = session.execute(
        select(PipelineRunStep.input_artifact_ref, PipelineRunStep.output_artifact_ref)
        .join(PipelineRun, PipelineRun.id == PipelineRunStep.run_id)
        .where(PipelineRun.document_version_id.in_(version_ids))
    )
    for input_ref, output_ref in pipeline_refs:
        for uri in (input_ref, output_ref):
            parsed = _s3_uri(uri)
            if parsed:
                refs.add(parsed)
    return refs


def _s3_uri(uri: str | None) -> tuple[str, str] | None:
    if not uri or not uri.startswith("s3://"):
        return None
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    return (parsed.netloc, key) if parsed.netloc and key else None


def _delete_unfinished_s3_objects(settings: Settings, session: Session, unfinished: list[DocumentVersion], retained: list[DocumentVersion]) -> int:
    targets = _object_references(session, unfinished) - _object_references(session, retained)
    storage = S3ObjectStorage(settings)
    for bucket, key in sorted(targets):
        storage.delete_object(bucket=bucket, key=key)
        try:
            storage.object_status(bucket=bucket, key=key)
        except AppError as exc:
            if exc.code == "s3_object_missing":
                continue
            raise
        raise AppError("project_archive_s3_delete_unverified", "Archived project object still exists after deletion", status_code=503)
    return len(targets)


def _delete_unfinished_search_artifacts(settings: Settings, unfinished: list[DocumentVersion], retained: list[DocumentVersion]) -> int:
    retained_uris = {version.extraction_artifact_uri for version in retained if version.extraction_artifact_uri}
    targets = [version for version in unfinished if version.extraction_artifact_uri and version.extraction_artifact_uri.startswith("opensearch://") and version.extraction_artifact_uri not in retained_uris]
    adapter = LiveOpenSearchPublishedAdapter(settings)
    for version in targets:
        adapter.delete_staging_documents(version=version)
        if adapter.staging_index_exists(version=version):
            raise AppError("project_archive_index_delete_unverified", "Archived project staging index still exists after deletion", status_code=503)
    return len(targets)


def _delete_unfinished_graph_artifacts(settings: Settings, unfinished: list[DocumentVersion]) -> int:
    adapter = LiveNeo4jGraphSyncAdapter(settings)
    for version in unfinished:
        adapter.delete_version(version_id=version.id)
    return len(unfinished)


def _purge_unfinished_database_rows(session: Session, project_id: UUID, versions: list[DocumentVersion]) -> dict[str, int]:
    version_ids = [version.id for version in versions]
    document_ids = {version.document_id for version in versions}

    pipeline_ids = _unfinished_pipeline_ids(session, project_id, version_ids)
    pipeline_step_ids = list(session.scalars(select(PipelineRunStep.id).where(PipelineRunStep.run_id.in_(pipeline_ids)))) if pipeline_ids else []
    validation_ids = _unfinished_validation_ids(session, project_id, version_ids)
    validation_item_ids = list(session.scalars(select(ValidationRunItem.id).where(ValidationRunItem.run_id.in_(validation_ids)))) if validation_ids else []
    chat_ids = list(session.scalars(select(ChatRecord.id).where(ChatRecord.document_version_id.in_(version_ids))))
    scan_ids = list(session.scalars(select(FileScanRun.id).where(FileScanRun.document_version_id.in_(version_ids))))
    sync_ids = _unfinished_sync_ids(session, project_id, version_ids)
    _delete_unfinished_outbox_events(
        session,
        version_ids=version_ids,
        pipeline_ids=pipeline_ids,
        scan_ids=scan_ids,
        sync_ids=sync_ids,
        validation_ids=validation_ids,
    )
    usage_filter = or_(
        AIModelUsageEvent.document_version_id.in_(version_ids),
        AIModelUsageEvent.pipeline_run_id.in_(pipeline_ids) if pipeline_ids else False,
        AIModelUsageEvent.pipeline_step_id.in_(pipeline_step_ids) if pipeline_step_ids else False,
        AIModelUsageEvent.validation_run_id.in_(validation_ids) if validation_ids else False,
        AIModelUsageEvent.validation_run_item_id.in_(validation_item_ids) if validation_item_ids else False,
        AIModelUsageEvent.chat_record_id.in_(chat_ids) if chat_ids else False,
    )
    session.execute(update(AIModelUsageEvent).where(usage_filter).values(document_version_id=None, pipeline_run_id=None, pipeline_step_id=None, chat_record_id=None, validation_run_id=None, validation_run_item_id=None))
    if validation_ids:
        session.execute(delete(ValidationRun).where(ValidationRun.id.in_(validation_ids)))
    if chat_ids:
        session.execute(update(ValidationRunItem).where(ValidationRunItem.chat_record_id.in_(chat_ids)).values(chat_record_id=None))
    session.execute(delete(ChatRecord).where(ChatRecord.document_version_id.in_(version_ids)))
    session.execute(delete(DocumentReferenceEvent).where(or_(DocumentReferenceEvent.old_source_version_id.in_(version_ids), DocumentReferenceEvent.new_source_version_id.in_(version_ids))))
    source_reference_ids = list(session.scalars(select(DocumentReference.id).where(DocumentReference.source_version_id.in_(version_ids))))
    if source_reference_ids:
        session.execute(delete(DocumentReferenceEvent).where(DocumentReferenceEvent.reference_id.in_(source_reference_ids)))
        session.execute(delete(DocumentReference).where(DocumentReference.id.in_(source_reference_ids)))
    session.execute(delete(ReviewRecord).where(ReviewRecord.document_version_id.in_(version_ids)))
    session.execute(update(ApprovalRequest).where(ApprovalRequest.document_version_id.in_(version_ids)).values(current_task_id=None))
    session.execute(delete(ValidationRun).where(ValidationRun.approval_task_id.in_(select(ApprovalTask.id).where(ApprovalTask.document_version_id.in_(version_ids)))))
    session.execute(delete(ApprovalTask).where(ApprovalTask.document_version_id.in_(version_ids)))
    session.execute(delete(ApprovalRequest).where(ApprovalRequest.document_version_id.in_(version_ids)))
    session.execute(delete(GraphSyncJob).where(GraphSyncJob.document_version_id.in_(version_ids)))
    if pipeline_ids:
        session.execute(delete(PipelineRun).where(PipelineRun.id.in_(pipeline_ids)))
    if sync_ids:
        session.execute(delete(DataSyncRun).where(DataSyncRun.id.in_(sync_ids)))
    session.execute(delete(ActiveVersionManifest).where(ActiveVersionManifest.document_version_id.in_(version_ids)))
    build_ids = list(session.scalars(select(EmbeddingBuild.id).where(EmbeddingBuild.document_version_id.in_(version_ids))))
    if build_ids:
        session.execute(delete(EmbeddingBuildVector).where(EmbeddingBuildVector.embedding_build_id.in_(build_ids)))
    session.execute(delete(EmbeddingBuild).where(EmbeddingBuild.document_version_id.in_(version_ids)))
    session.execute(delete(Chunk).where(Chunk.document_version_id.in_(version_ids)))
    session.execute(update(DocumentVersion).where(DocumentVersion.source_version_id.in_(version_ids)).values(source_version_id=None))
    session.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))

    deleted_documents = 0
    for document_id in document_ids:
        remains = int(session.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == document_id)) or 0)
        if remains == 0:
            reference_ids = list(session.scalars(select(DocumentReference.id).where(or_(DocumentReference.target_document_id == document_id, DocumentReference.source_document_id == document_id))))
            if reference_ids:
                session.execute(delete(DocumentReferenceEvent).where(DocumentReferenceEvent.reference_id.in_(reference_ids)))
                session.execute(delete(DocumentReference).where(DocumentReference.id.in_(reference_ids)))
            document_pipeline_ids = list(session.scalars(select(PipelineRun.id).where(PipelineRun.document_id == document_id)))
            document_pipeline_step_ids = list(session.scalars(select(PipelineRunStep.id).where(PipelineRunStep.run_id.in_(document_pipeline_ids)))) if document_pipeline_ids else []
            document_sync_ids = list(session.scalars(select(DataSyncRun.id).where(DataSyncRun.document_id == document_id)))
            _delete_unfinished_outbox_events(session, pipeline_ids=document_pipeline_ids, sync_ids=document_sync_ids)
            session.execute(
                update(AIModelUsageEvent)
                .where(
                    or_(
                        AIModelUsageEvent.document_id == document_id,
                        AIModelUsageEvent.pipeline_run_id.in_(document_pipeline_ids) if document_pipeline_ids else False,
                        AIModelUsageEvent.pipeline_step_id.in_(document_pipeline_step_ids) if document_pipeline_step_ids else False,
                    )
                )
                .values(document_id=None, pipeline_run_id=None, pipeline_step_id=None)
            )
            session.execute(delete(DataSyncRun).where(DataSyncRun.document_id == document_id))
            session.execute(delete(PipelineRun).where(PipelineRun.document_id == document_id))
            session.execute(update(DocumentVersion).where(DocumentVersion.source_document_id == document_id).values(source_document_id=None))
            session.execute(delete(DocumentReferenceEvent).where(DocumentReferenceEvent.source_document_id == document_id))
            session.execute(delete(Document).where(Document.id == document_id))
            deleted_documents += 1
    used_tag_ids = select(ChunkTag.tag_id).union(select(DocumentVersionTag.tag_id))
    session.execute(delete(Tag).where(Tag.project_id == project_id, ~Tag.id.in_(used_tag_ids)))
    return {"versions": len(version_ids), "documents": deleted_documents}


def _delete_unfinished_outbox_events(
    session: Session,
    *,
    version_ids: list[UUID] | None = None,
    pipeline_ids: list[UUID] | None = None,
    scan_ids: list[UUID] | None = None,
    sync_ids: list[UUID] | None = None,
    validation_ids: list[UUID] | None = None,
) -> None:
    aggregate_filters = []
    for aggregate_type, aggregate_ids in (
        ("document_version", version_ids),
        ("pipeline_run", pipeline_ids),
        ("file_scan_run", scan_ids),
        ("data_sync_run", sync_ids),
        ("validation_run", validation_ids),
    ):
        if aggregate_ids:
            aggregate_filters.append(
                (OutboxEvent.aggregate_type == aggregate_type) & OutboxEvent.aggregate_id.in_(aggregate_ids)
            )
    if aggregate_filters:
        session.execute(delete(OutboxEvent).where(or_(*aggregate_filters)))


def _fail_run(session: Session, run: ProjectArchiveRun, error_code: str) -> None:
    run.status = "failed"
    run.completed_at = datetime.now(UTC)
    run.heartbeat_at = run.completed_at
    run.lease_token = None
    run.lease_expires_at = None
    run.error_code = error_code
    run.error_message = "Project archive cleanup failed and can be retried"

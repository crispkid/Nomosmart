"""Scoped canonical edits with durable receipts and revision-fenced promotion."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import desc, func, select, or_
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (ApprovalRequest, Chunk, ChunkTag, Document, DocumentContentState,
    DocumentContentUpdate, DocumentVersion, DocumentVersionTag, OutboxEvent, PipelineRun,
    PipelineRunStep, Project, ProjectMember, Role, RolePermission, RoleUser, User)
from app.domain.content_diff import equal_source_ranges, rebase_range, text_digest
from app.domain.markdown_artifacts import resolve_markdown_artifact
from app.domain.project_access import get_scoped_project
from app.security.project_roles import PROJECT_EDITOR_ROLES
from app.services.audit import add_audit

CONTENT_UPDATE_TOPIC = "document.content_update.requested"
ACTIVE_JOB_STATES = ("queued", "running", "failed", "blocked")
STEP_NAMES = ("generate_markdown", "parse_structure", "auto_tag", "embedding", "staging_index", "build_graph_preview", "cleanup_superseded")


def effective_pipeline(session, version_id):
    return session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id,
        ~((PipelineRun.run_type == "document_content_update") & (PipelineRun.status == "cancelled")))
        .order_by(desc(PipelineRun.created_at)).limit(1))


def recoverable_failed_update(session, project, version):
    from app.db.models import AIModelUsageEvent
    from app.domain.embedding_capacity import CHUNKING_ERROR_CODES
    from app.domain.content_update_cleanup import require_unprotected_version
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.document_version_id == version.id)
        .order_by(desc(DocumentContentUpdate.created_at)).limit(1))
    if (job is None or job.status != "failed" or job.error_code not in CHUNKING_ERROR_CODES
        or job.step_name not in {"generate_markdown", "parse_structure"} or job.claim_token is not None
        or job.lease_expires_at is not None or (job.checkpoint or {}).get("provider_inflight")
        or (job.checkpoint or {}).get("promoted") or not isinstance(job.pending_markdown, str)
        or text_digest(job.pending_markdown) != job.target_sha256
        or job.project_id != project.id or job.document_id != version.document_id
        or job.project_generation != project.work_generation or job.expected_lock != version.lock_version
        or session.scalar(select(AIModelUsageEvent.id).where(AIModelUsageEvent.pipeline_run_id == job.pipeline_run_id,
            AIModelUsageEvent.attempted.is_(True)).limit(1))):
        return None
    pipeline = effective_pipeline(session, version.id)
    if pipeline is None or pipeline.id != job.pipeline_run_id or pipeline.status != "failed":
        return None
    try:
        require_unprotected_version(session, version)
        _, revision, digest = current_content(session, version)
    except AppError:
        return None
    return job if (revision, digest) == (job.base_revision, job.base_sha256) else None


def can_edit_content(session, project_id, user_id):
    permission = select(RolePermission.role_id).join(RoleUser,RoleUser.role_id == RolePermission.role_id).join(Role,Role.id == RolePermission.role_id).where(
        RoleUser.user_id == user_id,Role.is_active.is_(True),Role.deleted_at.is_(None),
        RolePermission.module_name == "Menu",RolePermission.function_name == "KnowledgeProjects",RolePermission.can_view.is_(True)).exists()
    return session.scalar(select(ProjectMember.user_id).join(User,User.id == ProjectMember.user_id).where(
        ProjectMember.project_id == project_id,ProjectMember.user_id == user_id,
        ProjectMember.project_role.in_(PROJECT_EDITOR_ROLES),User.is_active.is_(True),permission).limit(1)) is not None


def scoped_content(session, project_id, document_id, version_id, context, *, write=False):
    project = get_scoped_project(session, project_id, context)
    if write:
        if not can_edit_content(session,project.id,context.user_id):
            raise AppError("project_editor_required","Editor permission is required",status_code=403)
        project = session.scalar(select(Project).where(Project.id == project.id).with_for_update().execution_options(populate_existing=True))
    document = session.scalar(select(Document).where(Document.id == document_id, Document.project_id == project.id))
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id,
        DocumentVersion.document_id == document_id, DocumentVersion.project_id == project.id))
    if document is None or document.is_deleted or version is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    if write:
        document = session.scalar(select(Document).where(Document.id == document.id).with_for_update().execution_options(populate_existing=True))
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version.id).with_for_update().execution_options(populate_existing=True))
    return project, document, version


def current_content(session: Session, version: DocumentVersion):
    state = session.get(DocumentContentState, version.id)
    artifact = resolve_markdown_artifact(session, version, require_fingerprint=True)
    if artifact.text is None:
        raise AppError("content_edit_source_unavailable", "Verified full source is unavailable", status_code=409)
    return artifact.text, state.content_revision if state else 1, text_digest(artifact.text)


def content_edit_mode(session, project, version, can_edit):
    if not can_edit or project.status != "active":
        return "readonly", "project_editor_required"
    if version.status in {"pending_manager_review", "pending_owner_review", "approved", "publishing", "production_indexing", "graph_syncing"}:
        return "readonly", "content_edit_review_locked"
    failed = recoverable_failed_update(session, project, version)
    if failed:
        return "overwrite_candidate", None
    if session.scalar(select(DocumentContentUpdate.id).where(DocumentContentUpdate.document_version_id == version.id,
                                                            DocumentContentUpdate.status.in_(ACTIVE_JOB_STATES)).limit(1)):
        return "readonly", "content_edit_in_progress"
    pipeline = effective_pipeline(session, version.id)
    # Automatic extraction finishes at submission_ready. The review/publish
    # lifecycle may subsequently finish at completed; both are actual terminal
    # extraction states, with the version/job/permission checks above retained.
    if pipeline is not None and pipeline.status == "failed" and version.status == "failed" and version.published_at is None:
        from app.domain.markdown_artifacts import resolve_chunking_failure_source
        if resolve_chunking_failure_source(session, version, pipeline).text is not None and not session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id).limit(1)):
            return "overwrite_candidate", None
    if pipeline is None or pipeline.status not in {"submission_ready", "completed"}:
        return "readonly", "content_edit_in_progress"
    if version.published_at is not None or version.status in {"active", "inactive", "review_rejected", "review_cancelled"}:
        return "create_revision", None
    reviewed = session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id).limit(1))
    if reviewed:
        return "create_revision", None
    return ("overwrite_candidate", None) if version.status == "submission_ready" else ("readonly", "content_edit_in_progress")


def editor_source(session, project, document, version, context, settings, chunk_id=None):
    text, revision, digest = current_content(session, version)
    can_edit = can_edit_content(session,project.id,context.user_id)
    mode, reason = content_edit_mode(session, project, version, can_edit)
    if len(text.encode("utf-8")) > settings.content_edit_max_utf8_bytes:
        mode, reason = "readonly", "content_edit_too_large"
    ranges = []
    if chunk_id:
        chunk = session.scalar(select(Chunk).where(Chunk.id == chunk_id, Chunk.project_id == project.id,
            Chunk.document_version_id == version.id, Chunk.document_id == document.id, Chunk.status == "active"))
        if chunk is None:
            raise AppError("chunk_not_found", "Chunk was not found", status_code=404)
        for mapping in chunk.source_mapping or []:
            start, end = mapping.get("markdown_start_offset"), mapping.get("markdown_end_offset")
            if (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and mapping.get("mapping_status") == "resolved"
                and text_digest(text[start:end]) == mapping.get("markdown_fragment_sha256")):
                ranges.append({"start":start, "end":end, "offset_unit":"unicode_code_point", "content_revision":revision})
    failed = recoverable_failed_update(session, project, version) if can_edit and mode != "readonly" else None
    return {"project_id":str(project.id), "document_id":str(document.id), "document_version_id":str(version.id),
        "document_title":document.title, "version_label":version.version_label, "document_lock_version":document.lock_version,
        "lock_version":version.lock_version, "content_revision":revision, "markdown":text, "canonical_sha256":digest,
        "original_source_sha256":version.content_sha256, "edit_mode":mode, "reason_code":reason,
        "max_utf8_bytes":settings.content_edit_max_utf8_bytes, "selection_ranges":ranges,
        "selection_reason":None if not chunk_id or ranges else "chunk_content_source_unresolved",
        "failed_update": {"update_id":str(failed.id), "target_sha256":failed.target_sha256,
            "reason_code":failed.error_code, "pending_markdown":failed.pending_markdown, "can_cancel":True} if failed else None}


def cancel_failed_update(session, project, document, version, job, payload, actor, request_id=None, *, recovering=False):
    from sqlalchemy import delete
    from app.domain.graph_projection import build_graph_projection, preview_artifact, digest as graph_digest
    if not can_edit_content(session, project.id, actor):
        raise AppError("project_editor_required", "Editor permission is required", status_code=403)
    # scoped_content(write=True) already holds parent locks. Lock the job last.
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == job.id).with_for_update().execution_options(populate_existing=True))
    _, revision, sha = current_content(session, version)
    eligible = recoverable_failed_update(session, project, version)
    if (eligible is None or eligible.id != job.id or project.status != "active"
        or payload.document_lock_version != document.lock_version or payload.lock_version != version.lock_version
        or payload.base_content_revision != revision or payload.base_canonical_sha256 != sha):
        raise AppError("content_edit_conflict", "Failed update is no longer recoverable", status_code=409)
    pending = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
        Chunk.status == "pending_content_update", Chunk.chunk_strategy["content_update_id"].astext == str(job.id))))
    for chunk in pending:
        if chunk.project_id != project.id or chunk.document_id != document.id:
            raise AppError("content_update_stale", "Pending chunk scope changed", status_code=409)
        if session.scalar(select(Chunk.id).where(or_(Chunk.parent_chunk_id == chunk.id, Chunk.superseded_by_id == chunk.id)).limit(1)):
            raise AppError("content_cleanup_protected", "Pending chunk is referenced", status_code=409)
        session.delete(chunk)
    # Preserve failure/hash/usage/audit facts; discard the abandoned full draft.
    job.status, job.pending_markdown, job.claim_token, job.lease_expires_at = "cancelled", None, None, None
    job.checkpoint = {"cancelled":True, "error_code":job.error_code,
        "canonical_sha256":job.target_sha256, "chunking_issue":(job.checkpoint or {}).get("chunking_issue")}
    job.updated_at = datetime.now(UTC)
    pipeline = session.get(PipelineRun, job.pipeline_run_id)
    pipeline.status, pipeline.completed_at = "cancelled", datetime.now(UTC)
    for step in session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)):
        if step.step_name == "generate_markdown":
            step.artifact_payload = {"source":"cancelled_content_update", "canonical_sha256":job.target_sha256}
            step.artifact_fingerprint = graph_digest(step.artifact_payload)
        if step.status in {"pending", "running", "queued"}:
            step.status = "cancelled"
    session.flush()  # Release the active-job unique slot inside this transaction.
    document.lock_version += 1
    version.lock_version += 1
    current_chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active")))
    previous = effective_pipeline(session, version.id)
    own_success = previous is not None and previous.status in {"completed", "submission_ready"}
    target = version
    if not own_success and version.id != job.source_version_id and not recovering:
        version.status = "review_cancelled"
        version.chunk_strategy = {"content_update_cancelled":True, "source_version_id":str(job.source_version_id)}
        session.execute(delete(DocumentContentState).where(DocumentContentState.document_version_id == version.id))
        target = session.get(DocumentVersion, job.source_version_id)
    else:
        # Restore only actual committed source/artifacts. Model compatibility is
        # still evaluated normally by chunk_artifact_state, never fabricated.
        version.status = "processing" if recovering else "submission_ready" if own_success else "failed"
        metadata = {**(version.chunk_strategy or {}).get("chunk_artifacts", {}),
            "revision":version.lock_version, "project_generation":project.work_generation,
            "status":"ready" if own_success and current_chunks else "chunks_required" if own_success else "failed"}
        version.chunk_strategy = {**(version.chunk_strategy or {}), "chunk_artifacts":metadata}
        version.chunk_strategy.pop("content_update_id", None)
        version.chunk_strategy = {**version.chunk_strategy, "graph_preview":preview_artifact(build_graph_projection(session, project, document, version, current_chunks))}
    add_audit(session, actor_user_id=actor, action="document.content_update.cancelled", resource_type="document_version",
        resource_id=version.id, result="success", request_id=request_id,
        summary={"update_id":str(job.id), "target_sha256":job.target_sha256, "recovering":recovering})
    return {"changed":False, "document_version_id":str(target.id), "version_label":target.version_label,
        "lock_version":target.lock_version, "content_revision":revision, "update_id":str(job.id),
        "status":"recovery_cancelled"}


def _new_revision(session, project, document, source, actor):
    working = session.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == document.id,
        DocumentVersion.id != source.id, DocumentVersion.status.in_(("ready_for_extraction","quarantine","queued","processing",
            "submission_ready","pending_manager_review","pending_owner_review","approved"))).limit(1))
    if working:
        raise AppError("content_edit_in_progress", "A working version already exists", status_code=409,
                       details={"document_version_id":str(working)})
    revision = (session.scalar(select(func.max(DocumentVersion.extraction_revision)).where(
        DocumentVersion.document_id == document.id, DocumentVersion.version_major == source.version_major)) or 0) + 1
    excluded = {"id","created_at","updated_at","version_major","extraction_revision","version_label","status",
                "published_at","published_by","inactive_reason","lock_version","chunk_strategy","markdown_artifact_uri","extraction_artifact_uri"}
    fields = {column.key:getattr(source,column.key) for column in DocumentVersion.__table__.columns if column.key not in excluded}
    now = datetime.now(UTC)
    version = DocumentVersion(**fields, id=uuid4(), version_major=source.version_major, extraction_revision=revision,
        version_label=f"v{source.version_major}.{revision}", status="processing", lock_version=1, created_at=now, updated_at=now,
        chunk_strategy={key:value for key,value in (source.chunk_strategy or {}).items() if key not in {"graph_preview","chunk_artifacts"}})
    version.source_version_id = source.id
    version.source_document_id = document.id
    version.source_snapshot_created_at = now
    session.add(version)
    session.flush()
    return version


def _preserve_legacy_corrections(session, source, old, new):
    equal = equal_source_ranges(old,new)
    replacements = []
    for chunk in session.scalars(select(Chunk).where(Chunk.document_version_id == source.id,Chunk.status == "active",Chunk.is_manual_edited.is_(True))):
        if chunk.markdown_content is None:
            raise AppError("content_edit_legacy_chunk_conflict","Legacy manual content has no verified full-source range",status_code=409)
        start,end = chunk.start_offset,chunk.end_offset
        if type(start) is int and type(end) is int and 0 <= start < end <= len(old) and old[start:end] == chunk.markdown_content:
            continue
        ancestor,seen,span = chunk,set(),None
        while ancestor and ancestor.id not in seen:
            seen.add(ancestor.id)
            if (ancestor.project_id != source.project_id or ancestor.document_id != source.document_id or ancestor.document_version_id != source.id):
                break
            start,end = ancestor.start_offset,ancestor.end_offset
            if type(start) is int and type(end) is int and 0 <= start < end <= len(old) and old[start:end] == ancestor.markdown_content:
                span=(start,end);break
            ancestor=session.get(Chunk,ancestor.parent_chunk_id) if ancestor.parent_chunk_id else None
        if span is None:
            raise AppError("content_edit_legacy_chunk_conflict","Legacy manual correction cannot be rebased safely",status_code=409)
        mapped=rebase_range(equal,*span)
        if mapped:
            replacements.append((*mapped,chunk))
    replacements.sort(key=lambda item:item[0])
    if any(a[1] > b[0] for a,b in zip(replacements,replacements[1:])):
        raise AppError("content_edit_legacy_chunk_conflict","Legacy manual corrections overlap",status_code=409)
    parts,cursor,preserved=[],0,[]
    for start,end,chunk in replacements:
        parts.append(new[cursor:start])
        target_start=sum(map(len,parts))
        parts.append(chunk.markdown_content)
        preserved.append({"chunk_id":str(chunk.id),"start":target_start,"end":target_start+len(chunk.markdown_content)})
        cursor=end
    parts.append(new[cursor:])
    return "".join(parts),preserved


def queue_content_update(session, project, document, source, payload, actor, settings, request_id=None):
    if not can_edit_content(session,project.id,actor):
        raise AppError("project_editor_required","Editor permission is required",status_code=403)
    text, revision, digest = current_content(session, source)
    if (document.lock_version != payload.document_lock_version or source.lock_version != payload.lock_version
        or revision != payload.base_content_revision or digest != payload.base_canonical_sha256):
        raise AppError("content_edit_conflict", "The document changed; reload before saving", status_code=409)
    mode, reason = content_edit_mode(session, project, source, True)
    if mode == "readonly":
        raise AppError(reason, "Content editing is unavailable in the current state", status_code=409)
    try:
        size = len(payload.markdown.encode("utf-8"))
    except UnicodeError as exc:
        raise AppError("content_edit_invalid", "Content contains invalid Unicode", status_code=422) from exc
    if size > settings.content_edit_max_utf8_bytes:
        raise AppError("content_edit_too_large", "Full content exceeds the configured limit", status_code=413)
    failed = recoverable_failed_update(session, project, source)
    recovery_id = getattr(payload, "recover_update_id", None)
    if failed:
        if recovery_id != failed.id:
            raise AppError("content_edit_conflict", "Recover the exact failed update", status_code=409)
        result = cancel_failed_update(session, project, document, source, failed, payload, actor, request_id, recovering=text != payload.markdown)
        if text == payload.markdown:
            return result
        if result["document_version_id"] != str(source.id):
            # Keep failed new-candidate recovery in the same candidate; source
            # evidence is still immutable and a fresh committed state is made below.
            source.status = "processing"
    elif recovery_id is not None:
        raise AppError("content_edit_conflict", "Failed update changed", status_code=409)
    if text == payload.markdown:
        return {"changed":False,"document_version_id":str(source.id),"version_label":source.version_label,
            "lock_version":source.lock_version,"content_revision":revision,"update_id":None,"status":"unchanged"}
    corrected,legacy_preserved = _preserve_legacy_corrections(session,source,text,payload.markdown)
    if len(corrected.encode("utf-8")) > settings.content_edit_max_utf8_bytes:
        raise AppError("content_edit_too_large","Content including preserved manual corrections exceeds the limit",status_code=413)
    target = _new_revision(session, project, document, source, actor) if mode == "create_revision" else source
    now = datetime.now(UTC)
    state = session.get(DocumentContentState, target.id)
    if state is None:
        source_state = session.get(DocumentContentState, source.id)
        original_pipeline = effective_pipeline(session, source.id)
        original_step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == original_pipeline.id,
            PipelineRunStep.step_name == "generate_markdown")) if original_pipeline else None
        state = DocumentContentState(document_version_id=target.id, project_id=project.id, document_id=document.id,
            current_markdown=text, current_sha256=digest, content_revision=revision,
            original_artifact=dict(source_state.original_artifact) if source_state else {
                "version_id":str(source.id),"pipeline_id":str(original_pipeline.id) if original_pipeline else None,
                "step_id":str(original_step.id) if original_step else None,"sha256":digest}, updated_by=actor, updated_at=now)
        session.add(state)
    if target.id == source.id:
        target.lock_version += 1
    target.status = "processing"
    target.updated_at = now
    document.lock_version += 1
    document.updated_at = now
    pipeline = PipelineRun(id=uuid4(), project_id=project.id, document_id=document.id, document_version_id=target.id,
        project_generation=project.work_generation, run_type="document_content_update", status="queued", progress_percent=0,
        triggered_by=actor, created_at=now)
    session.add(pipeline); session.flush()
    for name in STEP_NAMES:
        session.add(PipelineRunStep(id=uuid4(),run_id=pipeline.id,step_name=name,status="pending",progress_percent=0,retry_count=0))
    job = DocumentContentUpdate(id=uuid4(),project_id=project.id,document_id=document.id,document_version_id=target.id,
        source_version_id=source.id,pipeline_run_id=pipeline.id,actor_user_id=actor,request_id=request_id,
        base_revision=revision,target_revision=max(revision, session.scalar(select(func.max(DocumentContentUpdate.target_revision)).where(
            DocumentContentUpdate.document_version_id == target.id)) or 0)+1,base_sha256=digest,target_sha256=text_digest(payload.markdown),
        expected_lock=target.lock_version,project_generation=project.work_generation,pending_markdown=corrected,
        status="queued",step_name="generate_markdown",checkpoint={"legacy_preserved":legacy_preserved},created_at=now,updated_at=now)
    job.target_sha256 = text_digest(corrected)
    session.add(job); session.flush()
    target.chunk_strategy = {**(target.chunk_strategy or {}),"chunk_artifacts":{"status":"queued","revision":target.lock_version,
        "project_generation":project.work_generation,"content_update_id":str(job.id)},"content_update_id":str(job.id)}
    _enqueue(session, project, job)
    add_audit(session,actor_user_id=actor,action="document.content_update.queued",resource_type="document_version",resource_id=target.id,
        result="success",request_id=request_id,summary={"base_version_id":str(source.id),"update_id":str(job.id),
        "base_sha256":digest,"target_sha256":job.target_sha256,"revision":job.target_revision})
    return {"changed":True,"document_version_id":str(target.id),"version_label":target.version_label,
        "lock_version":target.lock_version,"base_content_revision":revision,"content_revision":job.target_revision,
        "canonical_sha256":job.target_sha256,"update_id":str(job.id),"pipeline_run_id":str(pipeline.id),"status":"queued"}


def _enqueue(session, project, job):
    session.add(OutboxEvent(id=uuid4(),topic=CONTENT_UPDATE_TOPIC,aggregate_type="document_content_update",aggregate_id=job.id,
        project_id=project.id,project_generation=project.work_generation,payload={"revision":job.target_revision},status="pending",
        attempts=0,available_at=datetime.now(UTC),created_at=datetime.now(UTC)))


def scoped_update(session, project, document, version, update_id):
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == update_id,
        DocumentContentUpdate.project_id == project.id,DocumentContentUpdate.document_id == document.id,
        DocumentContentUpdate.document_version_id == version.id))
    if job is None:
        raise AppError("content_update_not_found","Content update was not found",status_code=404)
    return job


def job_response(job):
    return {"update_id":str(job.id),"document_version_id":str(job.document_version_id),"status":job.status,
        "step_name":job.step_name,"content_revision":job.target_revision,"canonical_sha256":job.target_sha256,
        "error_code":job.error_code,"retry_allowed":job.status == "failed" and not (job.checkpoint or {}).get("provider_inflight"),
        "next_stage_allowed":job.status == "ready", "chunking_issue":(job.checkpoint or {}).get("chunking_issue"),
        "cleanup":(job.checkpoint or {}).get("cleanup"), "promoted":bool((job.checkpoint or {}).get("promoted"))}


def retry_content_update(session, project, version, job, lock_version):
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == job.id).with_for_update().execution_options(populate_existing=True))
    expected_lock = (job.checkpoint or {}).get("cleanup_expected_lock", job.expected_lock)
    if version.lock_version != lock_version or expected_lock != version.lock_version or project.work_generation != job.project_generation:
        raise AppError("content_update_stale","Content update is no longer current",status_code=409)
    if job.status == "blocked" or (job.checkpoint or {}).get("provider_inflight"):
        raise AppError("content_update_provider_result_unknown","A model result needs reconciliation before retry",status_code=409)
    if job.status != "failed":
        raise AppError("content_edit_in_progress","This update is not retryable",status_code=409)
    job.status, job.error_code, job.claim_token, job.lease_expires_at = "queued",None,None,None
    pipeline = session.get(PipelineRun,job.pipeline_run_id)
    pipeline.status, pipeline.error_message = "queued",None
    _enqueue(session,project,job)
    return job_response(job)


def _copy_entity(entity, *, overrides=None):
    fields = {column.key:getattr(entity,column.key) for column in entity.__table__.columns}
    fields.update(overrides or {})
    return type(entity)(**fields)


def _fence(session, job_id, token, settings):
    job = session.get(DocumentContentUpdate, job_id)
    project = session.scalar(select(Project).where(Project.id == job.project_id).with_for_update().execution_options(populate_existing=True))
    document = session.scalar(select(Document).where(Document.id == job.document_id).with_for_update().execution_options(populate_existing=True))
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == job.document_version_id).with_for_update().execution_options(populate_existing=True))
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == job_id).with_for_update().execution_options(populate_existing=True))
    actor = session.get(User,job.actor_user_id)
    promoted = bool((job.checkpoint or {}).get("promoted"))
    if (job.claim_token != token or job.status != "running" or project.status != "active"
        or project.work_generation != job.project_generation or document.is_deleted
        or version.lock_version != (job.checkpoint or {}).get("cleanup_expected_lock", job.expected_lock)
        or version.status != "processing" or (not promoted and (actor is None or not actor.is_active))
        or version.project_id != project.id or document.project_id != project.id or version.document_id != document.id
        or (not promoted and not can_edit_content(session,project.id,actor.id))):
        raise AppError("content_update_stale","Content update scope or authorization changed",status_code=409)
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.ingestion_worker_lease_seconds)
    if promoted:
        from app.domain.content_update_cleanup import require_unprotected_version
        require_unprotected_version(session, version)
        state = session.get(DocumentContentState, version.id)
        ids = [str(value) for value in session.scalars(select(Chunk.id).where(
            Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index))]
        if (state is None or state.current_sha256 != job.target_sha256 or state.content_revision != job.target_revision
            or text_digest(state.current_markdown) != job.target_sha256
            or text_digest("\n".join(ids)) != job.checkpoint.get("active_chunk_digest")
            or (version.extraction_artifact_uri or "").removeprefix("opensearch://") != (job.checkpoint.get("staging_index") or "")):
            raise AppError("content_update_stale", "Promoted cleanup binding changed", status_code=409)
    return job,project,document,version


def _checkpoint(session, job, **values):
    job.checkpoint = {**(job.checkpoint or {}),**values}
    job.updated_at = datetime.now(UTC)
    session.commit()


def _provider_start(session,job,scope,model,input_sha):
    _checkpoint(session,job,provider_inflight=scope,provider_context={"model_id":str(model.id),
        "config_version":model.config_version,"input_sha256":input_sha,"scope":scope})


def _record_unconfirmed_usage(session,job):
    from app.db.models import AIModel
    from app.domain.model_usage import record_model_usage
    context=(job.checkpoint or {}).get("provider_context") or {}
    if not context.get("model_id"):
        return
    model=session.get(AIModel,UUID(context["model_id"]))
    if model is not None:
        record_model_usage(session,model=model,usage_purpose="embedding_build" if context.get("scope")=="embedding" else "document_auto_tag" if context.get("scope")=="document_tags" else "chunk_auto_tag",
            source_channel="pipeline",status="failed",error_code="content_update_provider_result_unknown",
            project_id=job.project_id,document_id=job.document_id,document_version_id=job.document_version_id,
            pipeline_run_id=job.pipeline_run_id,actor_user_id=job.actor_user_id,
            metadata={"content_update_id":str(job.id),"provider_result_unconfirmed":True,
                "config_version":context.get("config_version"),"input_sha256":context.get("input_sha256")})


def _step(session, job, name):
    job.step_name = name
    pipeline = session.get(PipelineRun,job.pipeline_run_id)
    pipeline.current_step_name, pipeline.status = name,"running"
    pipeline.started_at = pipeline.started_at or datetime.now(UTC)
    pipeline.progress_percent = STEP_NAMES.index(name) * 100 / len(STEP_NAMES)
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,PipelineRunStep.step_name == name))
    if step is None and name == "cleanup_superseded":
        step = PipelineRunStep(id=uuid4(), run_id=pipeline.id, step_name=name, status="pending", progress_percent=0, retry_count=0)
        session.add(step)
    step.status, step.started_at = "running",step.started_at or datetime.now(UTC)
    session.commit()


def _complete_step(session, job, name, payload):
    from app.domain.graph_projection import digest
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == job.pipeline_run_id,PipelineRunStep.step_name == name))
    step.status,step.completed_at,step.progress_percent = "completed",datetime.now(UTC),100
    step.artifact_payload,step.artifact_fingerprint = payload,digest(payload)
    step.output_artifact_ref = f"artifact://document_versions/{job.document_version_id}/{name}"
    session.commit()


def _pending_chunks(session, job):
    rows = list(session.scalars(select(Chunk).where(Chunk.document_version_id == job.document_version_id,
        Chunk.status == "pending_content_update",Chunk.chunk_strategy["content_update_id"].astext == str(job.id)).order_by(Chunk.chunk_index)))
    expected = (job.checkpoint or {}).get("chunk_ids")
    if expected is not None and [str(row.id) for row in rows] != expected:
        raise AppError("content_update_stale","Prepared chunk identities changed",status_code=409)
    if any(row.project_id != job.project_id or row.document_id != job.document_id for row in rows):
        raise AppError("content_update_stale","Prepared chunk scope is invalid",status_code=409)
    return rows


def _prepare_chunks(session, settings, project, document, version, job):
    from app.domain.chunk_representations import build_manual_chunk_representation
    from app.domain.document_layout import build_document_layout, renderable_source_anchors
    from app.domain.extraction_pipeline import _create_structure_chunks
    from app.domain.markdown_structure import MarkdownStructureParser
    old = session.get(DocumentContentState,version.id).current_markdown
    new = job.pending_markdown
    source_chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == job.source_version_id,
                                                          Chunk.status == "active").order_by(Chunk.chunk_index)))
    equal = equal_source_ranges(old,new)
    shadow = _copy_entity(version)
    shadow.chunk_strategy = {**(version.chunk_strategy or {}),"page_ranges":[],
        "content_source":{"revision":job.target_revision,"canonical_sha256":job.target_sha256}}
    shadow.chunk_strategy.pop("embedding_input_contract", None)  # New explicit content operation gets a new contract.
    shadow.embedding_model_id = project.embedding_model_id or version.embedding_model_id
    try:
        chunks = _create_structure_chunks(session,settings,project,document,shadow,new,replace_existing=False,
            persist_status="pending_content_update",identity_namespace=job.id) if new.strip() else []
    except AppError as exc:
        if exc.code not in {"chunk_content_required","markdown_structure_empty"}:
            raise
        chunks = []
    structure = MarkdownStructureParser().parse(new)
    preserved = []
    legacy = {item["chunk_id"]:(item["start"],item["end"]) for item in (job.checkpoint or {}).get("legacy_preserved",[])}
    for original in source_chunks:
        mapped = legacy.get(str(original.id)) or rebase_range(equal,original.start_offset,original.end_offset)
        if original.is_manual_edited and mapped and new[mapped[0]:mapped[1]] == original.markdown_content:
            if not any(mapped[0] < end and start < mapped[1] for start,end,_ in preserved):
                preserved.append((*mapped,original))

    def fragment(start,end,reference,manual=None):
        raw = new[start:end]
        if not raw.strip():
            return None
        representation = build_manual_chunk_representation(raw_markdown=raw,document_title=document.title,
            inherited_heading_path=reference.heading_path,inherited_heading_level=reference.heading_level,
            config_snapshot=(shadow.chunk_strategy or {}).get("effective_chunk_config"),
            input_contract=(shadow.chunk_strategy or {}).get("embedding_input_contract"))
        values = {"id":uuid4(),"chunk_index":0,"sequence":0,"status":"pending_content_update",
            "start_offset":start,"end_offset":end,"content":representation.display_text,"markdown_content":raw,
            "display_markdown":representation.display_markdown,"retrieval_text":representation.retrieval_text,
            "embedding_content_hash":representation.embedding_content_hash,"content_hash":representation.content_hash,
            "stable_chunk_key":representation.stable_chunk_key,"token_count":representation.token_count,
            "embedding_vector_ref":None,"is_manual_edited":manual is not None,
            "chunk_strategy":{**(reference.chunk_strategy or {}),**representation.processing_metadata},
            "created_at":datetime.now(UTC),"updated_at":datetime.now(UTC)}
        result = _copy_entity(reference,overrides=values)
        result.document_version_id = version.id
        if manual:
            result.lineage_id,result.parent_chunk_id = manual.lineage_id,manual.id
        session.add(result)
        return result

    if preserved:
        split_chunks = []
        for chunk in chunks:
            pieces = [(chunk.start_offset,chunk.end_offset)]
            for start,end,_ in preserved:
                pieces = [(a,b) for left,right in pieces for a,b in
                          ((left,min(right,start)),(max(left,end),right)) if a < b] if any(left < end and start < right for left,right in pieces) else pieces
            if pieces == [(chunk.start_offset,chunk.end_offset)]:
                split_chunks.append(chunk)
            else:
                for start,end in pieces:
                    value = fragment(start,end,chunk)
                    if value:
                        split_chunks.append(value)
                session.delete(chunk)
        for start,end,original in preserved:
            reference = next((c for c in split_chunks if c.start_offset <= start < c.end_offset),None)
            # Resolve heading context from the full parsed source, not a new
            # fragment that forgets its ancestor headings.
            draft = next((n for n in structure.nodes if n.type != "document"
                and n.start_offset <= start < n.end_offset),None)
            reference = reference or original
            if draft:
                reference = _copy_entity(reference,overrides={"heading_path":list(draft.heading_path),"heading_level":draft.heading_level})
            value = fragment(start,end,reference,original)
            if value:
                split_chunks.append(value)
        chunks = sorted(split_chunks,key=lambda c:(c.start_offset,c.end_offset))
    for index,chunk in enumerate(chunks,1):
        chunk.chunk_index,chunk.sequence = index,index
        raw = new[chunk.start_offset:chunk.end_offset]
        anchors = renderable_source_anchors(structure,start_offset=chunk.start_offset,end_offset=chunk.end_offset)
        if not anchors:
            raise AppError("chunk_source_mapping_invalid","Edited chunk has no exact canonical anchor",status_code=422)
        original = next((c for c in source_chunks if (legacy.get(str(c.id)) or rebase_range(equal,c.start_offset,c.end_offset)) ==
                         (chunk.start_offset,chunk.end_offset) and c.markdown_content == raw and c.heading_path == chunk.heading_path),None)
        if original is None and chunk.is_manual_edited and chunk.parent_chunk_id:
            # Manual preservation is already bound to an exact source span.
            # Re-parsed heading context can change without invalidating the
            # human assignment; automatic tag/vector reuse has separate checks.
            parent = next((c for c in source_chunks if c.id == chunk.parent_chunk_id), None)
            if (parent is not None and parent.is_manual_edited and parent.project_id == project.id
                and parent.document_id == document.id and parent.document_version_id == job.source_version_id
                and (legacy.get(str(parent.id)) or rebase_range(equal,parent.start_offset,parent.end_offset)) ==
                    (chunk.start_offset,chunk.end_offset) and parent.markdown_content == raw):
                original = parent
        chunk.chunk_strategy = {**(chunk.chunk_strategy or {}),"content_update_id":str(job.id),
            "content_update_source_chunk_id":str(original.id) if original else None}
        chunk.page_start,chunk.page_end = (original.page_start,original.page_end) if original else (None,None)
        chunk.source_mapping = [{"source":"corrected-canonical-markdown","source_anchor":anchors[0]["source_anchor"],
            "source_anchors":[a["source_anchor"] for a in anchors],"source_anchor_ranges":anchors,
            "markdown_start_offset":chunk.start_offset,"markdown_end_offset":chunk.end_offset,
            "anchor_start_offset":anchors[0]["anchor_start_offset"],"anchor_end_offset":anchors[0]["anchor_end_offset"],
            "start_offset":chunk.start_offset,"end_offset":chunk.end_offset,"offset_scope":"canonical_markdown",
            "offset_unit":"unicode_code_point","mapping_status":"resolved","mapping_content":"markdown_fragment_v2",
            "markdown_fragment_sha256":text_digest(raw),"content_revision":job.target_revision,
            "original_provenance":original.source_mapping if original else None}]
    for index,chunk in enumerate(chunks):
        chunk.chunk_strategy = {**chunk.chunk_strategy,"previous_chunk_id":str(chunks[index-1].id) if index else None,
            "next_chunk_id":str(chunks[index+1].id) if index+1 < len(chunks) else None}
    layout = build_document_layout(structure)
    layout["source"] = "content-edit-layout"
    strategy = {**(shadow.chunk_strategy or {}),"document_layout":layout,"source_text":new,
                "content_source":{"revision":job.target_revision,"canonical_sha256":job.target_sha256}}
    session.flush()
    _checkpoint(session,job,structure_prepared=True,strategy=strategy,chunk_ids=[str(c.id) for c in chunks])


def _tag_chunks(session,settings,project,version,job,token):
    from app.domain.extraction_pipeline import (_resolve_chat_tag_model,_generate_pipeline_tags,_tag_metadata,_result_tags,_attach_chunk_tag)
    from app.domain.system_prompts import resolve_system_prompt
    if not job.pending_markdown.strip() or not _pending_chunks(session,job):
        _checkpoint(session,job,document_tags=[],tagging_done=True)
        return
    model = _resolve_chat_tag_model(session,project)
    prompt = resolve_system_prompt(session,model=model,model_type="Chat")
    pipeline = session.get(PipelineRun,job.pipeline_run_id)
    if "document_tags" not in (job.checkpoint or {}):
        _fence(session,job.id,token,settings)
        _provider_start(session,job,"document_tags",model,job.target_sha256)
        result = _generate_pipeline_tags(session=session,settings=settings,model=model,prompt=prompt,text=job.pending_markdown,
            max_tags=8,allow_empty=False,usage_purpose="document_auto_tag",project=project,version=version,pipeline=pipeline)
        _fence(session,job.id,token,settings)
        _checkpoint(session,job,provider_inflight=None,document_tags=_result_tags(result),
                    document_tag_metadata={**_tag_metadata(result,model=model,pipeline=pipeline,scope="document"),"llm_config_version":model.config_version})
    for chunk in _pending_chunks(session,job):
        done = list((job.checkpoint or {}).get("tagged_chunks") or [])
        if str(chunk.id) in done:
            continue
        original_id = (chunk.chunk_strategy or {}).get("content_update_source_chunk_id")
        original = session.get(Chunk,UUID(original_id)) if original_id else None
        links = list(session.scalars(select(ChunkTag).where(ChunkTag.chunk_id == original.id))) if original else []
        input_text = (chunk.retrieval_text or chunk.markdown_content).strip()
        input_sha = text_digest(input_text)
        receipt = (original.chunk_strategy or {}).get("tag_receipt",{}) if original else {}
        reusable = original is not None and receipt == {"model_id":str(model.id),"config_version":model.config_version,
            "prompt_sha256":prompt.content_hash,"input_sha256":input_sha} and all(link.source == "manual" or (
            link.source == "llm" and (link.metadata_ or {}).get("llm_model_id") == str(model.id)
            and (link.metadata_ or {}).get("llm_config_version") == model.config_version
            and (link.metadata_ or {}).get("system_prompt_content_hash") == prompt.content_hash) for link in links)
        _fence(session,job.id,token,settings)
        if original:
            for link in links:
                if link.source == "manual" or reusable:
                    session.add(ChunkTag(chunk_id=chunk.id,tag_id=link.tag_id,source=link.source,metadata_=dict(link.metadata_ or {}),
                        confidence_score=link.confidence_score,created_by=link.created_by,created_at=link.created_at))
        if not reusable:
            _provider_start(session,job,str(chunk.id),model,input_sha)
            result = _generate_pipeline_tags(session=session,settings=settings,model=model,prompt=prompt,
                text=input_text,max_tags=5,allow_empty=True,usage_purpose="chunk_auto_tag",project=project,
                version=version,pipeline=pipeline,chunk_id=chunk.id)
            _fence(session,job.id,token,settings)
            metadata = {**_tag_metadata(result,model=model,pipeline=pipeline,scope="chunk",chunk_id=chunk.id),"llm_config_version":model.config_version}
            metadata["tag_input_sha256"] = input_sha
            for value in _result_tags(result,allow_empty=True):
                _attach_chunk_tag(session,project.id,chunk.id,value,source="llm",actor_user_id=job.actor_user_id,metadata=metadata)
        chunk.chunk_strategy = {**(chunk.chunk_strategy or {}),"tag_receipt":{"model_id":str(model.id),
            "config_version":model.config_version,"prompt_sha256":prompt.content_hash,"input_sha256":input_sha}}
        _checkpoint(session,job,provider_inflight=None,tagged_chunks=done+[str(chunk.id)])
    _checkpoint(session,job,tagging_done=True,llm_model_id=str(model.id))


def execute_content_update(session: Session, update_id: UUID, settings: Settings):
    from app.domain.embeddings import (embed_content_chunks,embedding_reuse_key,load_canonical_embeddings,resolve_embedding_retrieval_text)
    from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter,staging_index_name,_attach_document_tag
    from app.domain.graph_projection import build_graph_projection,preview_artifact
    from app.db.models import EmbeddingBuild,ValidationRun
    job = session.get(DocumentContentUpdate, update_id)
    if job is not None:
        # Same parent-to-child lock order as save/cancel/retry.
        for model, identity in ((Project, job.project_id), (Document, job.document_id), (DocumentVersion, job.document_version_id)):
            session.scalar(select(model).where(model.id == identity).with_for_update().execution_options(populate_existing=True))
        job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == update_id).with_for_update().execution_options(populate_existing=True))
    if job is None or job.status not in ("queued","running"):
        session.rollback(); return
    now = datetime.now(UTC)
    if job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
        session.rollback(); return
    if (job.checkpoint or {}).get("provider_inflight"):
        job.status,job.error_code = "blocked","content_update_provider_result_unknown"
        _record_unconfirmed_usage(session,job)
        job.claim_token,job.lease_expires_at=None,None
        pipeline=session.get(PipelineRun,job.pipeline_run_id)
        pipeline.status,pipeline.error_message="failed",job.error_code
        step=session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id==pipeline.id,PipelineRunStep.step_name==job.step_name))
        if step:
            step.status,step.error_message="failed",job.error_code
        session.commit(); return
    token = uuid4()
    job.status,job.claim_token,job.lease_expires_at = "running",token,now+timedelta(seconds=settings.ingestion_worker_lease_seconds)
    session.commit()
    try:
        job,project,document,version = _fence(session,job.id,token,settings)
        if (job.checkpoint or {}).get("promoted"):
            _finish_cleanup(session, settings, job, project, document, version, token)
            return
        _step(session,job,"generate_markdown")
        _complete_step(session,job,"generate_markdown",{"markdown":job.pending_markdown,"source":"human_content_update","canonical_sha256":job.target_sha256})
        if not (job.checkpoint or {}).get("structure_prepared"):
            _step(session,job,"parse_structure")
            _fence(session,job.id,token,settings)
            _prepare_chunks(session,settings,project,document,version,job)
        _complete_step(session,job,"parse_structure",{"canonical_sha256":job.target_sha256,"chunk_ids":job.checkpoint["chunk_ids"]})
        shadow = _copy_entity(version,overrides={"chunk_strategy":job.checkpoint["strategy"]})
        shadow.embedding_model_id = project.embedding_model_id or version.embedding_model_id
        if not (job.checkpoint or {}).get("tagging_done"):
            _step(session,job,"auto_tag")
            _tag_chunks(session,settings,project,shadow,job,token)
        _complete_step(session,job,"auto_tag",{"document_tags":job.checkpoint.get("document_tags",[]),"tagged_chunks":job.checkpoint.get("tagged_chunks",[])})
        chunks = _pending_chunks(session,job)
        batch = None
        if chunks:
            _step(session,job,"embedding")
            if (job.checkpoint or {}).get("embedding_profile_id"):
                shadow.embedding_profile_id = UUID(job.checkpoint["embedding_profile_id"])
                shadow.embedding_model_id = UUID(job.checkpoint["embedding_model_id"])
                batch = load_canonical_embeddings(session,project=project,version=shadow,chunks=chunks)
            else:
                reuse = {}
                source = session.get(DocumentVersion,job.source_version_id)
                old_chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == source.id,Chunk.status == "active").order_by(Chunk.chunk_index)))
                try:
                    old_batch = load_canonical_embeddings(session,project=project,version=source,chunks=old_chunks)
                except AppError:
                    old_batch = None
                if old_batch and old_batch.model.id == shadow.embedding_model_id:
                    shadow.embedding_profile_id = old_batch.profile.id
                    for old_chunk,vector in zip(old_chunks,old_batch.vectors,strict=True):
                        retrieval = resolve_embedding_retrieval_text(old_chunk,model=old_batch.model,profile=old_batch.profile)
                        reuse[embedding_reuse_key(old_batch.model,old_chunk,retrieval,old_batch.profile)] = vector
                _fence(session,job.id,token,settings)
                # Receipt is durable before the adapter can charge. If the
                # process dies between response and commit, refuse blind replay.
                from app.domain.embeddings import _active_embedding_model
                from app.db.models import EmbeddingProfile
                model = _active_embedding_model(session,project,shadow)
                profile = session.get(EmbeddingProfile,shadow.embedding_profile_id) if shadow.embedding_profile_id else None
                needs_provider = any(embedding_reuse_key(model,chunk,resolve_embedding_retrieval_text(chunk,model=model,profile=profile),profile) not in reuse for chunk in chunks)
                if needs_provider:
                    _provider_start(session,job,"embedding",model,text_digest("\n".join(chunk.retrieval_text or "" for chunk in chunks)))
                else:
                    _checkpoint(session,job,provider_inflight=None)
                batch = embed_content_chunks(session,project=project,version=shadow,chunks=chunks,reusable=reuse,settings=settings)
                _fence(session,job.id,token,settings)
                _checkpoint(session,job,provider_inflight=None,embedding_profile_id=str(batch.profile.id),embedding_model_id=str(batch.model.id))
            _complete_step(session,job,"embedding",{"embedding_build_id":str(batch.build.id),"usage":batch.usage})
            _step(session,job,"staging_index")
            index = staging_index_name(settings.opensearch_index_prefix,project.id,version.id)+"-edit-"+job.id.hex
            from app.domain.index_residue import persist_index_intent
            _fence(session,job.id,token,settings)
            intent = persist_index_intent(session,job,project,version,index)
            adapter = LiveOpenSearchStagingIndexAdapter(settings,index_override=index,ownership=intent)
            if job.checkpoint.get("staging_index"):
                adapter.verify_existing_chunks(project=project,document=document,version=shadow,chunks=chunks,vectors=batch.vectors,profile=batch.profile)
            else:
                # The external write may have completed before its PG receipt.
                # Verify first; only absent or demonstrably owned partial data
                # may be replaced. Embedding has already been persisted.
                if adapter.has_owned_index(project=project, document=document, version=shadow):
                    try:
                        adapter.verify_existing_chunks(project=project,document=document,version=shadow,chunks=chunks,vectors=batch.vectors,profile=batch.profile)
                    except AppError as exc:
                        if exc.code != "vector_index_not_ready":
                            raise
                        adapter.write_chunks(project=project,document=document,version=shadow,chunks=chunks,vectors=batch.vectors,profile=batch.profile)
                else:
                    adapter.write_chunks(project=project,document=document,version=shadow,chunks=chunks,vectors=batch.vectors,profile=batch.profile)
                _fence(session,job.id,token,settings)
                _checkpoint(session,job,staging_index=index)
            _complete_step(session,job,"staging_index",{"index_name":index,"canonical_sha256":job.target_sha256})
        else:
            for name in ("embedding","staging_index"):
                _complete_step(session,job,name,{"skipped":"no_retrievable_chunks","canonical_sha256":job.target_sha256})
        _step(session,job,"build_graph_preview")
        job,project,document,version = _fence(session,job.id,token,settings)
        state = session.get(DocumentContentState,version.id)
        if state.current_sha256 != job.base_sha256 or state.content_revision != job.base_revision:
            raise AppError("content_update_stale","Canonical source changed during preparation",status_code=409)
        old_chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,Chunk.status == "active")))
        for old_chunk in old_chunks:
            old_chunk.status,old_chunk.superseded_at = "superseded",datetime.now(UTC)
        session.flush()
        for chunk in chunks:
            chunk.status = "active"
        # Keep manual document assignments and shared canonical Tags. Only the
        # target version's old automatic assignments are replaced.
        from sqlalchemy import delete
        session.execute(delete(DocumentVersionTag).where(DocumentVersionTag.document_version_id == version.id,DocumentVersionTag.source != "manual"))
        if job.source_version_id != version.id:
            for link in session.scalars(select(DocumentVersionTag).where(DocumentVersionTag.document_version_id == job.source_version_id,DocumentVersionTag.source == "manual")):
                session.add(DocumentVersionTag(document_version_id=version.id,tag_id=link.tag_id,source=link.source,
                    metadata_=dict(link.metadata_ or {}),confidence_score=link.confidence_score,created_by=link.created_by,created_at=link.created_at))
        for value in job.checkpoint.get("document_tags",[]):
            _attach_document_tag(session,project.id,version.id,value,source="llm",actor_user_id=job.actor_user_id,metadata=job.checkpoint["document_tag_metadata"])
        state.current_markdown,state.current_sha256,state.content_revision = job.pending_markdown,job.target_sha256,job.target_revision
        state.updated_by,state.updated_at = job.actor_user_id,datetime.now(UTC)
        version.chunk_strategy = {**job.checkpoint["strategy"],"content_update_id":str(job.id),
            "chunk_artifacts":{"revision":version.lock_version,"project_generation":project.work_generation,
                "status":"ready" if chunks else "chunks_required","content_update_id":str(job.id)}}
        if batch:
            version.embedding_model_id,version.embedding_profile_id = batch.model.id,batch.profile.id
            version.extraction_artifact_uri = "opensearch://"+job.checkpoint["staging_index"]
            batch.build.status,batch.build.index_name = "staged",job.checkpoint["staging_index"]
        else:
            version.extraction_artifact_uri = None
        version.llm_model_id = UUID(job.checkpoint["llm_model_id"]) if job.checkpoint.get("llm_model_id") else version.llm_model_id
        version.status,version.processed_at = "processing",datetime.now(UTC)
        projection = build_graph_projection(session,project,document,version,chunks)
        graph = preview_artifact(projection)
        version.chunk_strategy = {**version.chunk_strategy,"graph_preview":graph}
        session.flush()
        session.refresh(version,attribute_names=["chunk_strategy"])
        if version.chunk_strategy.get("graph_preview") != graph:
            raise AppError("graph_source_stale","Graph preview readback is inconsistent",status_code=409)
        if build_graph_projection(session,project,document,version,chunks).source_digest != projection.source_digest:
            raise AppError("graph_source_stale","Graph source changed during promotion",status_code=409)
        for validation in session.scalars(select(ValidationRun).where(ValidationRun.document_version_id == version.id,ValidationRun.status == "completed")):
            validation.status = "cancelled"
        pipeline = session.get(PipelineRun,job.pipeline_run_id)
        pipeline.status,pipeline.progress_percent = "running",85
        pipeline.error_message = None
        job.pending_markdown,job.error_code = None,None
        job.checkpoint = {"staging_index":job.checkpoint.get("staging_index"),
            **({"staging_index_intent": job.checkpoint["staging_index_intent"]} if job.checkpoint.get("staging_index_intent") else {}),
            "canonical_sha256":job.target_sha256,"chunk_count":len(chunks),"graph_source_digest":projection.source_digest,
            "active_chunk_digest":text_digest("\n".join(str(c.id) for c in chunks)),
            "promoted":True, "cleanup":{"status":"pending"}}
        version.chunk_strategy = {**version.chunk_strategy, "chunk_artifacts":{
            **version.chunk_strategy["chunk_artifacts"], "status":"running"}}
        # Clear temporary full text from the step payload as well; committed
        # canonical is resolved through DocumentContentState.
        markdown_step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,PipelineRunStep.step_name == "generate_markdown"))
        markdown_step.artifact_payload = {"source":"committed_content_state","canonical_sha256":job.target_sha256}
        from app.domain.graph_projection import digest
        markdown_step.artifact_fingerprint = digest(markdown_step.artifact_payload)
        graph_step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,PipelineRunStep.step_name == "build_graph_preview"))
        graph_step.status,graph_step.completed_at,graph_step.progress_percent = "completed",datetime.now(UTC),100
        graph_step.artifact_payload,graph_step.artifact_fingerprint = graph,projection.source_digest
        session.commit()
        _finish_cleanup(session, settings, job, project, document, version, token)
    except Exception as exc:
        session.rollback()
        current = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id == update_id).with_for_update().execution_options(populate_existing=True))
        if current is not None and current.claim_token == token and current.status == "running":
            unknown = bool((current.checkpoint or {}).get("provider_inflight"))
            if unknown:
                _record_unconfirmed_usage(session,current)
            current.status,current.error_code = ("blocked","content_update_provider_result_unknown") if unknown else ("failed",getattr(exc,"code","content_update_failed"))
            if isinstance(exc, AppError) and exc.details.get("chunking_issue"):
                current.checkpoint = {**(current.checkpoint or {}), "chunking_issue": exc.details["chunking_issue"]}
            current.claim_token,current.lease_expires_at = None,None
            pipeline = session.get(PipelineRun,current.pipeline_run_id)
            pipeline.status,pipeline.error_message = "failed",current.error_code
            step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,PipelineRunStep.step_name == current.step_name))
            step.status,step.error_message = "failed",current.error_code
            if (current.checkpoint or {}).get("chunking_issue"):
                step.artifact_payload = {**(step.artifact_payload or {}), "chunking_issue": current.checkpoint["chunking_issue"]}
            add_audit(session,actor_user_id=current.actor_user_id,action="document.content_update.failed",resource_type="document_version",resource_id=current.document_version_id,
                result="failed",request_id=current.request_id,summary={"update_id":str(current.id),"error_code":current.error_code})
            session.commit()
        raise


def _finish_cleanup(session, settings, job, project, document, version, token):
    from app.domain.content_update_cleanup import clean_obsolete_candidates
    _step(session, job, "cleanup_superseded")
    clean_obsolete_candidates(session, settings, project, document, version, job,
        lambda: _fence(session, job.id, token, settings))
    _fence(session, job.id, token, settings)
    _complete_step(session, job, "cleanup_superseded", {"cleanup":job.checkpoint["cleanup"]})
    _fence(session, job.id, token, settings)
    pipeline = session.get(PipelineRun, job.pipeline_run_id)
    pipeline.status, pipeline.progress_percent, pipeline.completed_at = "completed", 100, datetime.now(UTC)
    version.status = "submission_ready"
    status = "ready" if job.checkpoint["chunk_count"] else "chunks_required"
    version.chunk_strategy = {**version.chunk_strategy, "chunk_artifacts":{
        **version.chunk_strategy["chunk_artifacts"], "status":status}}
    job.status, job.error_code, job.claim_token, job.lease_expires_at = status, None, None, None
    add_audit(session, actor_user_id=job.actor_user_id, action="document.content_update.completed",
        resource_type="document_version", resource_id=version.id, result="success", request_id=job.request_id,
        summary={"update_id":str(job.id), "revision":job.target_revision, "canonical_sha256":job.target_sha256,
            "cleanup":job.checkpoint["cleanup"]})
    session.commit()


def queue_legacy_candidate_cleanup(session, project, document, version, actor, *, lock_version, revision, sha256):
    """Explicit, exact-bound repair using the same durable product cleanup path.

    Only the latest successful update matching current canonical can be resumed;
    original success/idempotency/expected-lock facts are kept unchanged.
    """
    from app.domain.content_update_cleanup import require_unprotected_version
    require_unprotected_version(session, version)
    if not can_edit_content(session, project.id, actor) or project.status != "active":
        raise AppError("project_editor_required", "Editor permission is required", status_code=403)
    if session.scalar(select(DocumentContentUpdate.id).where(DocumentContentUpdate.document_version_id == version.id,
        DocumentContentUpdate.status.in_(ACTIVE_JOB_STATES)).limit(1)):
        raise AppError("content_edit_in_progress", "Another content operation is active", status_code=409)
    text, current_revision, current_sha = current_content(session, version)
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.document_version_id == version.id,
        DocumentContentUpdate.status.in_(("ready", "chunks_required")), DocumentContentUpdate.target_revision == revision,
        DocumentContentUpdate.target_sha256 == sha256).order_by(desc(DocumentContentUpdate.created_at)).with_for_update().limit(1))
    if (job is None or version.lock_version != lock_version or (revision, sha256) != (current_revision, current_sha)
        or job.project_generation != project.work_generation or job.project_id != project.id or job.document_id != document.id):
        raise AppError("content_update_stale", "Legacy cleanup scope changed", status_code=409)
    chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
        Chunk.status == "active").order_by(Chunk.chunk_index)))
    job.checkpoint = {**(job.checkpoint or {}), "promoted":True, "cleanup_expected_lock":lock_version,
        "active_chunk_digest":text_digest("\n".join(str(c.id) for c in chunks)), "chunk_count":len(chunks),
        "staging_index":(version.extraction_artifact_uri or "").removeprefix("opensearch://") or None,
        "cleanup":{"status":"pending", "legacy_repair":True}}
    job.status, job.step_name, job.error_code = "queued", "cleanup_superseded", None
    version.status = "processing"
    version.chunk_strategy = {**version.chunk_strategy, "chunk_artifacts":{
        **version.chunk_strategy.get("chunk_artifacts", {}), "status":"queued"}}
    pipeline = session.get(PipelineRun, job.pipeline_run_id)
    pipeline.status, pipeline.current_step_name, pipeline.completed_at = "queued", "cleanup_superseded", None
    _enqueue(session, project, job)
    add_audit(session, actor_user_id=actor, action="document.content_update.cleanup_queued", resource_type="document_version",
        resource_id=version.id, result="success", request_id=None,
        summary={"update_id":str(job.id), "revision":revision, "canonical_sha256":sha256})
    return job_response(job)

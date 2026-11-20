"""CHG-442 STAGE442-001..004/010: four human-confirmed extraction stations.

A pipeline run executes the steps of one station, then pauses: the station row becomes `ready`, the run goes to
`waiting_action` with waiting role `station_editor`, and the worker task ends as completed. Confirming the
station (`confirm_station`) re-queues the same run; the document dispatcher accepts a new execution for it only
when a station confirmation is newer than the previous execution (`station_resume_authorized`). Station 4 has no
confirmation: it ends at `submission_ready` and submission is the confirmation.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.errors import AppError
from app.db.models import DocumentVersion, DocumentVersionStation, OutboxEvent, PipelineRun

STATION_STEPS: dict[int, tuple[str, ...]] = {
    1: ("upload_received", "parse_document", "ocr_extract", "generate_markdown"),
    2: ("split_paragraphs", "chunk_knowledge"),
    3: ("auto_tag", "extract_references"),
    4: ("build_embeddings", "build_staging_index", "build_graph_preview", "prepare_submission"),
}
STEP_STATION = {step: station for station, steps in STATION_STEPS.items() for step in steps}
STATION_WAIT_ROLE = "station_editor"
VERSION_STATION_STATUS = "awaiting_confirmation"
DOCUMENT_TOPIC = "document.extraction.requested"


def station_paused(run: PipelineRun | None) -> bool:
    return run is not None and run.status == "waiting_action" and run.current_waiting_role == STATION_WAIT_ROLE


def station_rows(session, version_id: UUID, *, lock: bool = False) -> dict[int, DocumentVersionStation]:
    query = select(DocumentVersionStation).where(DocumentVersionStation.document_version_id == version_id)
    if lock:
        query = query.with_for_update()
    return {row.station: row for row in session.scalars(query)}


def ensure_station_rows(session, version_id: UUID) -> dict[int, DocumentVersionStation]:
    rows = station_rows(session, version_id)
    now = datetime.now(UTC)
    for station in STATION_STEPS:
        if station not in rows:
            rows[station] = DocumentVersionStation(document_version_id=version_id, station=station, status="pending",
                                                   reused=False, created_at=now, updated_at=now)
            session.add(rows[station])
    session.flush()
    return rows


def station_confirmed(session, version_id: UUID, station: int) -> bool:
    row = session.get(DocumentVersionStation, (version_id, station))
    return row is not None and row.status == "confirmed"


def pause_at_station(session, project, document, version: DocumentVersion, pipeline: PipelineRun, station: int) -> None:
    """All steps of `station` are done and the next station needs a human confirmation."""
    rows = ensure_station_rows(session, version.id)
    now = datetime.now(UTC)
    row = rows[station]
    if row.status != "confirmed":
        row.status, row.updated_at = "ready", now
    pipeline.status = "waiting_action"
    pipeline.current_waiting_role = STATION_WAIT_ROLE
    pipeline.current_action_url = f"/project/{project.id}/knowledge/{document.id}?station={station}"
    pipeline.current_step_name = STATION_STEPS[station][-1]
    version.status, version.updated_at = VERSION_STATION_STATUS, now


def mark_station_ready(session, version_id: UUID, station: int) -> None:
    row = ensure_station_rows(session, version_id)[station]
    if row.status == "pending":
        row.status, row.updated_at = "ready", datetime.now(UTC)


def confirm_station(session, *, project, document, version: DocumentVersion, station: int, actor_user_id: UUID,
                    lock_version: int) -> PipelineRun:
    """STAGE442-002: confirm a ready station and queue the next one. Idempotent for an already confirmed station."""
    if station not in (1, 2, 3):
        raise AppError("station_not_confirmable", "Only stations 1 to 3 are confirmed; station 4 ends with submission", status_code=422)
    if version.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    rows = station_rows(session, version.id, lock=True)
    row = rows.get(station)
    if row is not None and row.status == "confirmed":
        return _current_run(session, version.id)
    if row is None or row.status != "ready" or any(rows.get(n) is None or rows[n].status != "confirmed" for n in range(1, station)):
        raise AppError("station_not_ready", "This station is not ready for confirmation", status_code=409,
                       details={"station": station})
    run = _current_run(session, version.id)
    if not station_paused(run):
        raise AppError("station_not_ready", "Extraction is not waiting for this station", status_code=409, details={"station": station})
    now = datetime.now(UTC)
    row.status, row.confirmed_by, row.confirmed_at, row.updated_at = "confirmed", actor_user_id, now, now
    run.status, run.current_waiting_role, run.current_action_url, run.error_message = "queued", None, None, None
    version.status, version.updated_at = "queued", now
    version.lock_version += 1
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == DOCUMENT_TOPIC, OutboxEvent.aggregate_id == run.id)
                           .with_for_update().limit(1))
    if event is None:
        session.add(OutboxEvent(id=uuid4(), topic=DOCUMENT_TOPIC, aggregate_type="pipeline_run", aggregate_id=run.id, project_id=project.id,
                                project_generation=project.work_generation,
                                payload={"pipeline_run_id": str(run.id), "project_id": str(project.id), "project_generation": project.work_generation},
                                status="pending", attempts=0, available_at=now, created_at=now))
    else:
        event.status, event.available_at, event.processed_at = "pending", now, None
        event.task_id = event.last_error = None
        event.claim_token = event.claimed_at = event.lease_expires_at = None
    return run


def station_resume_authorized(session, run: PipelineRun | None, previous) -> bool:
    """A completed (paused) execution may be followed by a new one after a station confirmation made after that
    execution started. Its release may come later than the confirmation (finalization is asynchronous)."""
    if run is None or previous is None or previous.state != "completed" or previous.released_at is None or run.status != "queued":
        return False
    latest = session.scalar(select(func.max(DocumentVersionStation.confirmed_at))
                            .where(DocumentVersionStation.document_version_id == run.document_version_id))
    return latest is not None and latest > previous.created_at


def paused_or_resumed(session, run: PipelineRun) -> bool:
    """For worker completion checks: the run paused at a station (it may already be re-queued by a confirmation)."""
    if station_paused(run):
        return True
    return run.status in {"queued", "running"} and session.scalar(select(DocumentVersionStation.station).where(
        DocumentVersionStation.document_version_id == run.document_version_id,
        DocumentVersionStation.status.in_(("ready", "confirmed"))).limit(1)) is not None


def _current_run(session, version_id: UUID) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id,
                                                    PipelineRun.run_type == "document_extraction")
                          .order_by(PipelineRun.created_at.desc()).limit(1).with_for_update())


def paused_station(session, version_id: UUID) -> int | None:
    """The station a person is working on now: the extraction run waits and that station is ready."""
    run = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id,
                                                    PipelineRun.run_type == "document_extraction")
                         .order_by(PipelineRun.created_at.desc()).limit(1))
    if not station_paused(run):
        return None
    ready = [row.station for row in station_rows(session, version_id).values() if row.status == "ready"]
    return min(ready) if ready else None


REOPENABLE_VERSION_STATUSES = {VERSION_STATION_STATUS, "submission_ready"}
# DD442-10: the versions the existing "create revision" rule applies to; with stations the revision starts at station 1.
REVISION_SOURCE_STATUSES = {"review_rejected", "review_cancelled", "active", "inactive"}


def uses_stations(session, version_id: UUID) -> bool:
    return session.scalar(select(DocumentVersionStation.station).where(DocumentVersionStation.document_version_id == version_id).limit(1)) is not None


def apply_station_content_edit(session, *, project, document, version: DocumentVersion, markdown: str, actor_user_id: UUID) -> dict:
    """STAGE442-005: at station 1 the full text is saved at once, without a model call. Chunking happens when the
    person confirms station 1; chunks whose text did not change then keep their tags, references and vectors."""
    from app.db.models import DocumentContentState, PipelineRunStep
    from app.domain.document_content_updates import current_content, text_digest
    from app.domain.extraction_pipeline import _artifact_ref
    text, revision, digest = current_content(session, version)
    if text == markdown:
        return {"changed": False, "document_version_id": str(version.id), "version_label": version.version_label,
                "lock_version": version.lock_version, "content_revision": revision, "update_id": None, "status": "unchanged"}
    now = datetime.now(UTC)
    new_digest = text_digest(markdown)
    state = session.get(DocumentContentState, version.id)
    if state is None:
        state = DocumentContentState(document_version_id=version.id, project_id=project.id, document_id=document.id,
                                     current_markdown=markdown, current_sha256=new_digest, content_revision=revision + 1,
                                     original_artifact={"version_id": str(version.id), "sha256": digest}, updated_by=actor_user_id, updated_at=now)
        session.add(state)
    else:
        state.current_markdown, state.current_sha256, state.content_revision = markdown, new_digest, revision + 1
        state.updated_by, state.updated_at = actor_user_id, now
    run = _current_run(session, version.id)
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == run.id, PipelineRunStep.step_name == "generate_markdown"))
    step.artifact_payload = {"markdown": markdown, "adapter_source": "station-1-content-edit", "canonical_sha256": new_digest}
    step.artifact_fingerprint = new_digest
    step.output_artifact_ref = version.markdown_artifact_uri = _artifact_ref(version, "generate_markdown")
    version.lock_version += 1
    version.updated_at = document.updated_at = now
    document.lock_version += 1
    return {"changed": True, "document_version_id": str(version.id), "version_label": version.version_label,
            "lock_version": version.lock_version, "base_content_revision": revision, "content_revision": revision + 1,
            "canonical_sha256": new_digest, "update_id": None, "status": "station_saved"}


def _reset_steps(session, run: PipelineRun, stations: range) -> None:
    from app.db.models import PipelineRunStep
    names = [name for station in stations for name in STATION_STEPS[station]]
    for step in session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == run.id, PipelineRunStep.step_name.in_(names))):
        step.status, step.progress_percent = "pending", 0
        step.started_at = step.completed_at = step.output_artifact_ref = None
        step.artifact_payload = step.artifact_fingerprint = None
        step.claim_token = step.claimed_at = step.lease_expires_at = step.error_message = None


def reopen_station(session, *, project, document, version: DocumentVersion, station: int, lock_version: int) -> dict:
    """STAGE442-009: go back to a finished station. That station waits for confirmation again and every later
    station returns to pending; nothing is recomputed until the person confirms. Unchanged chunks keep their work."""
    from app.db.models import ApprovalRequest, Chunk, ValidationRun
    if station not in (1, 2, 3):
        raise AppError("station_not_reopenable", "Only stations 1 to 3 can be reopened", status_code=422)
    if version.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    if version.status not in REOPENABLE_VERSION_STATUSES or session.scalar(
            select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id).limit(1)) is not None:
        raise AppError("station_reopen_unavailable", "This version can no longer return to an earlier station", status_code=409)
    run = _current_run(session, version.id)
    if run is None or not (station_paused(run) or run.status == "submission_ready"):
        raise AppError("station_reopen_unavailable", "Extraction is still running", status_code=409)
    rows = station_rows(session, version.id, lock=True)
    if rows.get(station) is None or rows[station].status not in {"ready", "confirmed"}:
        raise AppError("station_not_ready", "This station has not been reached yet", status_code=409, details={"station": station})
    now = datetime.now(UTC)
    redo = [n for n in STATION_STEPS if n > station]
    for n, row in rows.items():
        if n == station:
            row.status, row.confirmed_by, row.confirmed_at, row.reused, row.updated_at = "ready", None, None, False, now
        elif n > station:
            row.status, row.confirmed_by, row.confirmed_at, row.reused, row.updated_at = "pending", None, None, False, now
    _reset_steps(session, run, range(station + 1, 5))
    for validation in session.scalars(select(ValidationRun).where(ValidationRun.document_version_id == version.id,
                                                                  ValidationRun.status == "completed")):
        validation.status = "cancelled"
    run.completed_at = None
    pause_at_station(session, project, document, version, run, station)
    run.progress_percent = 0 if station == 1 else run.progress_percent
    version.lock_version += 1
    chunks = session.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active")) or 0
    return {"station": station, "redo_stations": redo, "active_chunks": int(chunks)}


def create_station_revision(session, *, project, document, source: DocumentVersion, actor_user_id: UUID, lock_version: int) -> DocumentVersion:
    """STAGE442-010: a rejected version stays locked; a new revision starts at station 1 with its content. Re-chunking
    at station 2 takes tags, references and vectors of unchanged chunks from the rejected version."""
    from app.db.models import DocumentContentState, DocumentVersionTag, PipelineRunStep
    from app.domain.document_content_updates import _new_revision, current_content, text_digest
    from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS, _artifact_ref, _step_message
    if source.status not in REVISION_SOURCE_STATUSES:
        raise AppError("station_revision_unavailable", "This version cannot start a station revision", status_code=409)
    if source.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    text, revision, digest = current_content(session, source)
    version = _new_revision(session, project, document, source, actor_user_id)
    now = datetime.now(UTC)
    version.status = VERSION_STATION_STATUS
    version.markdown_artifact_uri = _artifact_ref(version, "generate_markdown")
    version.chunk_strategy = {**(version.chunk_strategy or {}), "station_revision_of": str(source.id)}
    source_state = session.get(DocumentContentState, source.id)
    session.add(DocumentContentState(document_version_id=version.id, project_id=project.id, document_id=document.id,
                                     current_markdown=text, current_sha256=digest, content_revision=revision,
                                     original_artifact=dict(source_state.original_artifact) if source_state else {"version_id": str(source.id), "sha256": digest},
                                     updated_by=actor_user_id, updated_at=now))
    for link in session.scalars(select(DocumentVersionTag).where(DocumentVersionTag.document_version_id == source.id)).all():
        session.add(DocumentVersionTag(document_version_id=version.id, tag_id=link.tag_id, source=link.source, confidence_score=link.confidence_score,
                                       metadata_=dict(link.metadata_ or {}), created_by=link.created_by, created_at=link.created_at))
    source_run = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == source.id, PipelineRun.run_type == "document_extraction")
                                .order_by(PipelineRun.created_at.desc()).limit(1))
    old_steps = {step.step_name: step for step in session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == source_run.id))} if source_run else {}
    run = PipelineRun(id=uuid4(), project_id=project.id, document_id=document.id, document_version_id=version.id,
                      project_generation=project.work_generation, run_type="document_extraction", status="queued",
                      progress_percent=0, triggered_by=actor_user_id, created_at=now)
    session.add(run)
    session.flush()
    for name in AUTO_EXTRACTION_STEPS:
        old = old_steps.get(name)
        done = name in STATION_STEPS[1]
        payload = None
        if done:
            payload = dict(old.artifact_payload or {}) if old is not None else {}
            if name == "generate_markdown":
                payload = {"markdown": text, "adapter_source": "station-revision", "canonical_sha256": digest}
        session.add(PipelineRunStep(id=uuid4(), run_id=run.id, step_name=name, status="completed" if done else "pending",
                                    progress_percent=100 if done else 0, retry_count=0, progress_message=_step_message(name, "", False),
                                    started_at=now if done else None, completed_at=now if done else None,
                                    output_artifact_ref=_artifact_ref(version, name) if done else None,
                                    artifact_payload=payload, model_id=old.model_id if done and old is not None else None))
    session.flush()
    ensure_station_rows(session, version.id)
    pause_at_station(session, project, document, version, run, 1)
    return version


def reuse_summary(session, version_id: UUID) -> dict[str, int] | None:
    """STAGE442-009: kept vs redone chunks of the latest station work, for the confirmation and completion messages."""
    from app.db.models import PipelineRunStep
    run = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id, PipelineRun.run_type == "document_extraction")
                         .order_by(PipelineRun.created_at.desc()).limit(1))
    if run is None:
        return None
    steps = {step.step_name: step.artifact_payload or {} for step in session.scalars(select(PipelineRunStep).where(
        PipelineRunStep.run_id == run.id, PipelineRunStep.status == "completed",
        PipelineRunStep.step_name.in_(("chunk_knowledge", "auto_tag", "build_embeddings"))))}
    chunking = steps.get("chunk_knowledge", {}).get("station_reuse")
    tagging = steps.get("auto_tag", {})
    usage = steps.get("build_embeddings", {}).get("usage") or {}
    if not chunking and not tagging.get("reused_tag_chunks") and not usage.get("reused_vectors"):
        return None
    summary = {key: int(value) for key, value in (chunking or {}).items()}
    if "chunk_tags" in tagging:
        summary["reused_tag_chunks"] = int(tagging.get("reused_tag_chunks") or 0)
        summary["tagged_chunks"] = len(tagging["chunk_tags"]) - summary["reused_tag_chunks"]
    if "reused_vectors" in usage:
        summary["reused_vectors"], summary["new_vectors"] = int(usage["reused_vectors"]), int(usage.get("new_vectors") or 0)
    return summary

"""CHG-444 QUEUE444-001/002/004: queued extraction of a document that can no longer be processed.

A document extraction run that is `queued` and has no unreleased document execution has not started yet. When its
document is deleted (or the dispatcher finds its scope permanently gone), the run is taken out of the queue:

- a first run (or a retry) becomes `cancelled` and its version returns to `ready_for_extraction`, so a restored
  document can be started again;
- a run re-queued by a station confirmation (CHG-442) withdraws that confirmation: the station waits again and the
  run returns to `waiting_action`, so a restored document continues after one more confirmation.

Its pending outbox events are cancelled. Runs that already have a live execution are left to the worker, which
fails them on `file_processing_scope_stale` (existing behavior).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models import Document, DocumentVersion, FileProcessingExecution as Execution, FileProcessingTask as Task, OutboxEvent, PipelineRun, Project

DOCUMENT_TOPIC = "document.extraction.requested"
CANCEL_REASON = "document_deleted_before_processing"


def _had_execution(session, run_id: UUID) -> bool:
    return session.scalar(select(Execution.id).where(Execution.run_id == run_id, Execution.kind == "document").limit(1)) is not None


def take_run_out_of_queue(session, run: PipelineRun, *, event_error: str, reason: str = CANCEL_REASON) -> str | None:
    """Cancel or withdraw one queued, not-started run. Returns "cancelled", "withdrawn" or None (left alone).

    An execution whose task already finished its work (task `quiescent`, waiting for the dispatcher to release it)
    does not count as running for a station withdrawal; a plain cancel still waits for the release (existing
    finalization). Any other unreleased execution is running and is left to the worker."""
    from app.domain.stations import pause_at_station, station_rows, uses_stations
    if run.run_type != "document_extraction" or run.status != "queued":
        return None
    unreleased = list(session.scalars(select(Execution.id).where(Execution.run_id == run.id, Execution.kind == "document",
                                                                 Execution.released_at.is_(None))))
    for execution_id in unreleased:
        quiet = session.scalar(select(Task.id).where(Task.execution_id == execution_id, Task.state.in_(("quiescent", "finalized"))).limit(1))
        working = session.scalar(select(Task.id).where(Task.execution_id == execution_id, Task.state.not_in(("quiescent", "finalized"))).limit(1))
        if quiet is None or working is not None:
            return None
    now = datetime.now(UTC)
    version = session.get(DocumentVersion, run.document_version_id, with_for_update=True) if run.document_version_id else None
    outcome = None
    if version is not None and _had_execution(session, run.id) and uses_stations(session, version.id):
        rows = station_rows(session, version.id, lock=True)
        resumed = [n for n, row in rows.items() if n < 4 and row.status == "confirmed"
                   and (rows.get(n + 1) is None or rows[n + 1].status == "pending")]
        if resumed:
            station = max(resumed)
            row = rows[station]
            row.status, row.confirmed_by, row.confirmed_at, row.updated_at = "ready", None, None, now
            pause_at_station(session, session.get(Project, run.project_id), session.get(Document, run.document_id), version, run, station)
            version.lock_version += 1
            outcome = "withdrawn"
    if outcome is None:
        if unreleased:
            return None
        run.status, run.error_message, run.completed_at = "cancelled", reason, now
        run.current_waiting_role = run.current_action_url = None
        if version is not None and version.status == "queued":
            version.status, version.updated_at = "ready_for_extraction", now
            version.lock_version += 1
        outcome = "cancelled"
    for event in session.scalars(select(OutboxEvent).where(OutboxEvent.topic == DOCUMENT_TOPIC, OutboxEvent.aggregate_id == run.id,
                                                           OutboxEvent.status.in_(("pending", "dispatching"))).with_for_update()):
        event.status, event.processed_at, event.last_error = "cancelled", now, event_error
        event.claim_token = event.claimed_at = event.lease_expires_at = None
    return outcome


def cancel_queued_extractions(session, document: Document) -> int:
    """QUEUE444-001/002: on document deletion take every not-started extraction run of the document out of the queue."""
    runs = session.scalars(select(PipelineRun).where(PipelineRun.document_id == document.id, PipelineRun.run_type == "document_extraction",
                                                     PipelineRun.status == "queued").with_for_update()).all()
    return sum(1 for run in runs if take_run_out_of_queue(session, run, event_error="file_processing_document_deleted"))


def hidden_cancelled_run():
    """QUEUE444-003: runs that summaries treat as absent: cancelled content updates (existing rule) and extraction runs
    cancelled before they started (so a restored document shows "start extraction")."""
    return ((PipelineRun.status == "cancelled") & ((PipelineRun.run_type == "document_content_update")
            | ((PipelineRun.run_type == "document_extraction") & (PipelineRun.error_message == CANCEL_REASON))))

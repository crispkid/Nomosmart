"""Durable native-document calls; accounting survives revoked business claims."""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent, Document, DocumentVersion, OCRDocumentReceipt, PipelineRun, PipelineRunStep, Project
from app.domain.model_usage import record_model_usage

ACTIVE_STATES = ("intent", "unknown")
TERMINAL_STATES = ("confirmed_completed", "confirmed_rejected", "confirmed_incomplete", "unknown")


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def receipt_for_step(session: Session, step_id: UUID):
    return session.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.original_step_id == step_id)
                          .order_by(OCRDocumentReceipt.created_at.desc()).limit(1))


def require_no_unknown_call(session: Session, version_id: UUID) -> None:
    if session.scalar(select(OCRDocumentReceipt.id).where(OCRDocumentReceipt.original_document_version_id == version_id,
            OCRDocumentReceipt.status.in_(ACTIVE_STATES)).limit(1)) is not None:
        raise AppError("ocr_document_provider_result_unknown", "An earlier document call is unconfirmed; automatic replay is forbidden", status_code=409)
    from app.domain.ocr_image_receipts import checkpoint
    old_steps = session.scalars(select(PipelineRunStep).join(PipelineRun, PipelineRunStep.run_id == PipelineRun.id)
        .where(PipelineRun.document_version_id == version_id, PipelineRunStep.step_name == "ocr_extract"))
    for step in old_steps:
        old = checkpoint(step.artifact_payload)
        if old.get("intent") or (old and old.get("usage_confirmed") is False):
            raise AppError("ocr_image_provider_result_unknown", "A historical image OCR call is unconfirmed", status_code=409)


class DocumentOCRJournal:
    """Only reserve/promotion require a current claim. Completion is observation-only."""

    def __init__(self, *, session, settings, project, pipeline, execution_claim, model, version,
                 snapshot: dict, request_sha256: str, credential_fingerprint: str):
        self.session, self.settings = session, settings
        self.project_id, self.run_id, self.version_id = project.id, pipeline.id, version.id
        self.model, self.claim = model, execution_claim
        self.source_sha256, self.request_sha256 = version.content_sha256, request_sha256
        self.snapshot = snapshot
        self.snapshot_sha256 = digest(snapshot)
        self.expected_model_version = model.config_version
        self.expected_model_config = digest({"config": model.config, "endpoint": model.endpoint})
        self.source_locator = (version.storage_bucket, version.storage_key, version.file_size, version.mime_type)
        self.binding_sha256 = digest({"run": self.run_id, "version": self.version_id,
            "source": self.source_sha256, "source_locator": self.source_locator, "request": request_sha256, "snapshot": self.snapshot_sha256,
            "model": model.id, "config_version": model.config_version, "config": model.config,
            "endpoint": model.endpoint, "credential_fingerprint": credential_fingerprint})
        self.receipt_id = self.attempt_id = None

    def _scope(self):
        if self.claim is None or self.claim.run_id != self.run_id:
            raise AppError("file_processing_task_fenced", "A current document task claim is required", status_code=409)
        from app.domain.file_processing_dispatch import require_claim
        require_claim(self.session, self.claim)
        version = self.session.scalar(select(DocumentVersion).where(DocumentVersion.id == self.version_id)
            .with_for_update().execution_options(populate_existing=True))
        run = self.session.scalar(select(PipelineRun).where(PipelineRun.id == self.run_id)
            .with_for_update().execution_options(populate_existing=True))
        step = self.session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == self.run_id,
            PipelineRunStep.step_name == "ocr_extract").with_for_update().execution_options(populate_existing=True))
        project = self.session.get(Project, self.project_id, populate_existing=True)
        document = self.session.get(Document, run.document_id, populate_existing=True) if run else None
        if (version is None or run is None or step is None or project is None or document is None
                or run.project_id != self.project_id or run.document_version_id != version.id
                or version.project_id != self.project_id or version.document_id != document.id
                or document.is_deleted or project.status != "active" or run.status != "running"
                or project.work_generation != run.project_generation or step.status != "running"
                or step.claim_token is None or version.content_sha256 != self.source_sha256):
            raise AppError("file_processing_scope_stale", "Document OCR scope changed", status_code=409)
        live_model = self.session.get(AIModel, self.model.id, populate_existing=True)
        if (version.ocr_model_id != self.model.id or version.ocr_config_version != self.expected_model_version
                or self.snapshot.get("config_version") != self.expected_model_version
                or live_model is None or live_model.config_version != self.expected_model_version
                or not live_model.is_active or live_model.deleted_at is not None
                or digest({"config": live_model.config, "endpoint": live_model.endpoint}) != self.expected_model_config
                or digest((version.chunk_strategy or {}).get("ocr_snapshot")) != self.snapshot_sha256
                or (version.storage_bucket, version.storage_key, version.file_size, version.mime_type) != self.source_locator):
            raise AppError("ocr_model_snapshot_changed", "Native OCR model snapshot changed; create a new extraction revision", status_code=409)
        return version, run, step

    def _existing(self, step):
        row = self.session.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.original_step_id == step.id,
            OCRDocumentReceipt.retry_count == step.retry_count).with_for_update().execution_options(populate_existing=True))
        if row is None:
            return None
        if row.binding_sha256 != self.binding_sha256:
            raise AppError("ocr_document_receipt_conflict", "Document request identity changed", status_code=409)
        if row.status != "confirmed_completed":
            code = "ocr_document_provider_result_unknown" if row.status in ACTIVE_STATES else "ocr_document_recovery_required"
            raise AppError(code, "Existing document call cannot be replayed", status_code=409)
        ledger = self.session.get(AIModelUsageEvent, row.usage_event_id) if row.usage_event_id else None
        if (ledger is None or ledger.id != row.id or ledger.pipeline_step_id != row.step_id
                or ledger.correlation_id != str(row.attempt_id) or ledger.status != "success"
                or not row.output_artifact_uri or not row.output_sha256):
            raise AppError("ocr_document_receipt_conflict", "Completed document receipt is incomplete", status_code=409)
        self.receipt_id, self.attempt_id = row.id, row.attempt_id
        return row

    def inspect_existing(self):
        _, _, step = self._scope()
        row = self._existing(step)
        if row is None:
            require_no_unknown_call(self.session, self.version_id)
            if self.session.scalar(select(AIModelUsageEvent.id).where(
                    AIModelUsageEvent.document_version_id == self.version_id,
                    AIModelUsageEvent.usage_purpose == "ocr_extract", AIModelUsageEvent.attempted.is_(True)).limit(1)) is not None:
                raise AppError("ocr_document_recovery_required", "Previously attempted OCR requires explicit revision or recovery", status_code=409)
        self.session.commit()
        return row

    def reserve(self, *, input_tokens: int, output_limit: int, artifact_base: str):
        version, run, step = self._scope()
        existing = self._existing(step)
        if existing is not None:
            self.session.commit()
            return existing, False
        require_no_unknown_call(self.session, version.id)
        # Any previous attempted call on this version needs a separate explicit
        # revision/recovery, even if resetting the step or changing the run/model.
        if self.session.scalar(select(AIModelUsageEvent.id).where(
                AIModelUsageEvent.document_version_id == version.id,
                AIModelUsageEvent.usage_purpose == "ocr_extract",
                AIModelUsageEvent.attempted.is_(True)).limit(1)) is not None:
            raise AppError("ocr_document_recovery_required", "Previously attempted OCR cannot be replayed on this version", status_code=409)
        now, receipt_id, attempt_id = datetime.now(UTC), uuid4(), uuid4()
        row = OCRDocumentReceipt(id=receipt_id, project_id=run.project_id, document_id=run.document_id,
            document_version_id=version.id, run_id=run.id, step_id=step.id, model_id=self.model.id,
            original_document_id=version.document_id, original_document_version_id=version.id,
            original_run_id=run.id, original_step_id=step.id,
            attempt_id=attempt_id, retry_count=step.retry_count, source_sha256=self.source_sha256,
            request_sha256=self.request_sha256, snapshot_sha256=self.snapshot_sha256,
            binding_sha256=self.binding_sha256, status="intent", promotion_state="pending", attempted=None,
            dispatch_binding={"step_claim": str(step.claim_token), "task_id": str(self.claim.task_id),
                "task_claim": str(self.claim.claim_token), "execution_id": str(self.claim.execution_id),
                "generation": str(self.claim.generation), "project_generation": run.project_generation},
            model_snapshot={"name": self.model.name, "provider": self.model.provider,
                "model_type": self.model.model_type, "config_version": self.model.config_version,
                "config": self.model.config}, policy_snapshot=self.snapshot,
            counted_input_tokens=input_tokens, request_output_limit=output_limit, usage={},
            response_artifact_uri=f"{artifact_base}/{receipt_id}/response.json",
            output_artifact_uri=f"{artifact_base}/{receipt_id}/output.md",
            created_at=now, updated_at=now)
        self.session.add(row)
        self.session.flush()
        self.receipt_id, self.attempt_id = receipt_id, attempt_id
        self.session.commit()  # The single durable authorization precedes I/O.
        return row, True

    def assert_can_dispatch(self):
        _, _, step = self._scope()
        row = self.session.get(OCRDocumentReceipt, self.receipt_id)
        if (row is None or row.attempt_id != self.attempt_id or row.status != "intent"
                or row.dispatch_binding.get("step_claim") != str(step.claim_token)):
            raise AppError("ocr_document_receipt_conflict", "Document dispatch authorization changed", status_code=409)
        self.session.commit()

    def finalize(self, *, status: str, attempted: bool, usage: dict | None, error_code: str | None = None,
                 provider_response_id: str | None = None, output_sha256: str | None = None,
                 output_bytes: int | None = None, response_sha256: str | None = None,
                 latency_ms: int | None = None):
        if status not in TERMINAL_STATES or type(attempted) is not bool or self.receipt_id is None:
            raise AppError("ocr_document_receipt_conflict", "Document observation is invalid", status_code=409)
        observation = {"status": status, "attempted": attempted, "usage": usage or {}, "error_code": error_code,
            "provider_response_id": provider_response_id, "output_sha256": output_sha256,
            "output_bytes": output_bytes, "response_sha256": response_sha256}
        observed_hash = digest(observation)
        # This writer has no promotion capability. It can preserve observed cost
        # after the original task/version is revoked, without committing its work.
        with Session(bind=self.session.get_bind(), expire_on_commit=False) as writer:
            row = writer.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.id == self.receipt_id).with_for_update())
            if row is None or row.attempt_id != self.attempt_id or row.binding_sha256 != self.binding_sha256:
                raise AppError("ocr_document_receipt_conflict", "Document completion identity changed", status_code=409)
            if row.observation_sha256 is not None:
                if row.observation_sha256 != observed_hash or row.usage_event_id is None:
                    raise AppError("ocr_document_receipt_conflict", "Document completion conflicts with saved evidence", status_code=409)
                return row
            if row.status != "intent":
                raise AppError("ocr_document_receipt_conflict", "Document receipt is not awaiting observation", status_code=409)
            frozen = row.model_snapshot
            accounting_model = AIModel(id=row.model_id, name=frozen["name"], model_type=frozen["model_type"],
                provider=frozen["provider"], config=frozen["config"], config_version=frozen["config_version"])
            run = writer.get(PipelineRun, row.run_id)
            event = record_model_usage(writer, model=accounting_model, usage_purpose="ocr_extract", source_channel="pipeline",
                status="success" if status == "confirmed_completed" else "failed", attempted=attempted,
                error_code=error_code, token_usage=usage, latency_ms=latency_ms,
                correlation_id=str(row.attempt_id), event_id=row.id,
                project_id=row.project_id, document_id=row.document_id, document_version_id=row.document_version_id,
                pipeline_run_id=row.run_id, pipeline_step_id=row.step_id, actor_user_id=run.triggered_by if run else None,
                metadata={"input_mode": "native_pdf", "receipt_id": str(row.id), "source_sha256": row.source_sha256,
                    "request_sha256": row.request_sha256, "model_config_version": frozen["config_version"],
                    "provider_result_unconfirmed": status == "unknown", "physical_page_count": None})
            row.status, row.attempted, row.usage = status, attempted, usage or {}
            row.usage_event_id, row.observation_sha256 = event.id, observed_hash
            row.provider_response_id, row.output_sha256, row.output_bytes = provider_response_id, output_sha256, output_bytes
            row.response_sha256, row.error_code = response_sha256, error_code
            row.completed_at = row.updated_at = datetime.now(UTC)
            writer.commit()
            return row

    def assert_promotion(self):
        try:
            _, _, step = self._scope()
            row = self.session.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.id == self.receipt_id)
                .with_for_update().execution_options(populate_existing=True))
            if (row is None or row.status != "confirmed_completed" or row.binding_sha256 != self.binding_sha256
                    or row.attempt_id != self.attempt_id or row.usage_event_id is None
                    or row.promotion_state == "discarded" or row.dispatch_binding.get("step_claim") != str(step.claim_token)):
                raise AppError("ocr_document_receipt_conflict", "Document result cannot be promoted", status_code=409)
            row.promotion_state, row.promoted_at, row.updated_at = "promoted", datetime.now(UTC), datetime.now(UTC)
            # Caller commits this flag with the accepted step artifact.
            return row
        except AppError:
            self.session.rollback()
            with Session(bind=self.session.get_bind(), expire_on_commit=False) as writer:
                row = writer.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.id == self.receipt_id).with_for_update())
                if row is not None and row.attempt_id == self.attempt_id and row.promotion_state != "promoted":
                    row.promotion_state, row.updated_at = "discarded", datetime.now(UTC)
                    writer.commit()
            raise


def assert_receipt_promotion(session: Session, receipt_id, *, execution_claim):
    """Last promotion fence; caller commits with the actual OCR step artifact."""
    from app.domain.file_processing_dispatch import require_claim
    if execution_claim is None:
        raise AppError("file_processing_task_fenced", "A document claim is required", status_code=409)
    require_claim(session, execution_claim)
    try:
        receipt_id = UUID(str(receipt_id))
    except (ValueError, TypeError, AttributeError):
        raise AppError("ocr_document_receipt_conflict", "Document receipt identity is invalid", status_code=409) from None
    row = session.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.id == receipt_id)
        .with_for_update().execution_options(populate_existing=True))
    if row is None or row.run_id != execution_claim.run_id:
        raise AppError("ocr_document_receipt_conflict", "Document receipt is outside the current task", status_code=409)
    version = session.get(DocumentVersion, row.document_version_id, populate_existing=True)
    run = session.get(PipelineRun, row.run_id, populate_existing=True)
    step = session.get(PipelineRunStep, row.step_id, populate_existing=True)
    project = session.get(Project, row.project_id, populate_existing=True)
    document = session.get(Document, row.document_id, populate_existing=True)
    expected = {"step_claim": str(step.claim_token) if step else None, "task_id": str(execution_claim.task_id),
        "task_claim": str(execution_claim.claim_token), "execution_id": str(execution_claim.execution_id),
        "generation": str(execution_claim.generation), "project_generation": run.project_generation if run else None}
    if (row.status != "confirmed_completed" or row.usage_event_id is None or row.promotion_state == "discarded"
            or row.dispatch_binding != expected or version is None or run is None or step is None
            or project is None or document is None or document.is_deleted or project.status != "active"
            or version.content_sha256 != row.source_sha256 or version.ocr_model_id != row.model_id
            or version.ocr_config_version != row.model_snapshot.get("config_version")
            or project.work_generation != run.project_generation or run.status != "running" or step.status != "running"):
        raise AppError("file_processing_scope_stale", "Document result no longer belongs to the current scope", status_code=409)
    row.promotion_state, row.promoted_at, row.updated_at = "promoted", datetime.now(UTC), datetime.now(UTC)
    return row


def assert_no_unknown(session: Session, version_id: UUID) -> None:
    """Compatibility entry for the existing authenticated retry guard."""
    require_no_unknown_call(session, version_id)
    if session.scalar(select(OCRDocumentReceipt.id).where(OCRDocumentReceipt.original_document_version_id == version_id,
            OCRDocumentReceipt.attempted.is_(True)).limit(1)) is not None:
        raise AppError("ocr_document_recovery_required", "Attempted native OCR requires explicit revision or recovery", status_code=409)

"""Claim-bound Worker PDF processing with local owned tools (not a sandbox)."""
from contextvars import ContextVar
import hashlib
import os
import time

from app.core.errors import AppError
from app.db.models import FileProcessingExecution as Execution, DocumentVersion
from app.domain.document_execution import (begin_execution, bind_local_workload,
    claim_execution, record_progress, release_execution, transition_execution)
from app.domain.file_processing_dispatch import configured_capabilities, require_claim
from app.domain.local_pdf.errors import Rejected, need
from app.domain.local_pdf.runner import LocalPDF

_current = ContextVar("claimed_pdf_processing", default=None)
QUEUED = "file_processing_parser_queued"


def current_pdf_processing():
    value = _current.get()
    if value is None or value.claim is None:
        raise AppError("file_processing_claim_required", "PDF processing requires a current document task", status_code=409)
    return value


class PDFPages:
    def __init__(self, owner):
        self.owner = owner

    def __len__(self):
        return self.owner.result["pages"]

    def __iter__(self):
        for number in range(1, len(self)+1):
            self.owner.fence()
            body = self.owner.store.read(number)
            if self.owner.result["operation"] == "raster":
                from app.domain.local_pdf.png import validate_png
                validate_png(body, max_bytes=self.owner.settings.pdf_max_page_bytes, max_pixels=self.owner.settings.pdf_max_pixels)
                yield f"physical-{number}.png", "image/png", body
            else:
                yield f"physical-{number}.pdf", "application/pdf", body


class PDFProcessing:
    def __init__(self, *, session, settings, claim, program, language_resolver, raster_dpi=None):
        self.session, self.settings, self.claim = session, settings, claim
        self.program, self.language_resolver = program, language_resolver
        self.raster_dpi = raster_dpi
        self.local = self.store = self.result = self.admission = None
        self.released = False
        self.sequence = 0
        self.last_fence = 0

    def __enter__(self):
        need(_current.get() is None)
        self.token = _current.set(self)
        return self

    def __exit__(self, exc_type, exc, traceback):
        _current.reset(self.token)
        if self.local is not None:
            failed = False
            cleanups = [self.local.clean_parser] if not self.local.cleaned else []
            if self.local.store is not None:
                cleanups.append(self.local.store.close)
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    failed = True
            # prepare/fail_closed already retained recovery when needed. Preserve
            # its original safe error, while still attempting both cleanups.
            if failed and exc_type is None:
                raise AppError("file_processing_cleanup_failed", "PDF temporary cleanup is unconfirmed", status_code=503) from None

    def fence(self):
        if self.claim is None:
            raise AppError("file_processing_claim_required", "PDF processing requires a current document task", status_code=409)
        row = require_claim(self.session, self.claim)
        self.session.commit()
        self.last_fence = time.monotonic()
        return row

    def heartbeat(self):
        if time.monotonic()-self.last_fence >= self.local.policy["file_processing_progress_interval_seconds"]:
            self.fence()

    def progress(self, completed, total):
        require_claim(self.session, self.claim)
        self.sequence += 1
        record_progress(self.session, execution_id=self.admission.execution_id, generation=self.admission.generation,
                        sequence=self.sequence, phase="rendering_images" if self.local.operation == "raster" else "parsing", completed=completed, total=total, unit="pages")
        self.session.commit()

    def release(self, terminal, result=None):
        require_claim(self.session, self.claim, check_scope=terminal == "completed")
        self.local.clean_parser()
        if terminal != "completed" and self.local.store is not None:
            self.local.store.close()
        evidence = self.local.stop_evidence(self.admission.generation)
        transition_execution(self.session, execution_id=self.admission.execution_id,
                             generation=self.admission.generation, state="stopping")
        self.session.flush()
        release_execution(self.session, execution_id=self.admission.execution_id, generation=self.admission.generation,
            terminal=terminal, stop_evidence=evidence, output_evidence=None if result is None else {
                "input_hash": result["input_hash"], "generation": str(self.admission.generation),
                "complete": True, "output_hash": result["sha256"]})
        self.session.commit()
        self.released = True

    def fail_closed(self):
        self.session.rollback()
        if self.admission is None or self.released:
            return
        try:
            row = self.session.get(Execution, self.admission.execution_id)
            if row is not None and row.released_at is None:
                try:
                    self.release("failed")
                    return
                except Exception:
                    self.session.rollback()
                require_claim(self.session, self.claim, check_scope=False)
                row = self.session.get(Execution, self.admission.execution_id)
                if row.state != "recovery_required":
                    transition_execution(self.session, execution_id=row.id, generation=row.generation,
                                         state="recovery_required", error_code="parser_stop_unconfirmed")
                self.session.commit()
        except Exception:
            self.session.rollback()

    def prepare(self, body):
        parent = self.fence()
        need(type(body) is bytes and body.startswith(b"%PDF-")
             and len(body) <= self.settings.max_upload_size_mb*1024**2
             and hashlib.sha256(body).hexdigest() == parent.input_hash, "invalid_request")
        if self.result is not None:
            need(self.result["input_hash"] == parent.input_hash, "invalid_output")
            return
        need(self.admission is None)
        try:
            languages = self.language_resolver()
            if self.program in {"raster", "text_or_raster"}:
                version = self.session.get(DocumentVersion, parent.document_version_id)
                configured = dict((version.chunk_strategy or {}).get("ocr_snapshot") or {})
                from sqlalchemy import select
                from app.db.models import PipelineRunStep, AIModelUsageEvent
                from app.domain.ocr_image_receipts import checkpoint
                from app.domain.ocr_token_settings import from_snapshot, load_settings
                if from_snapshot(configured) is None:
                    step = self.session.scalar(select(PipelineRunStep).where(
                        PipelineRunStep.run_id == self.claim.run_id, PipelineRunStep.step_name == "ocr_extract"))
                    paid = step is not None and self.session.scalar(select(AIModelUsageEvent.id).where(
                        AIModelUsageEvent.pipeline_step_id == step.id, AIModelUsageEvent.attempted.is_(True)).limit(1))
                    if step is not None and not paid and not checkpoint(step.artifact_payload):
                        configured.update(load_settings(self.session).snapshot())
                        version.chunk_strategy = {**(version.chunk_strategy or {}), "ocr_snapshot": configured}
                mode = configured.get("pdf_input_mode", "page_images")
                dpi = configured.get("pdf_ocr_dpi", self.settings.pdf_ocr_dpi)
                need(mode == "page_images" and type(dpi) is int and 100 <= dpi <= 300, "invalid_request")
                self.raster_dpi = dpi
                if "pdf_input_mode" not in configured or "pdf_ocr_dpi" not in configured:
                    configured.update(pdf_input_mode=mode, pdf_ocr_dpi=dpi)
                    version.chunk_strategy = {**(version.chunk_strategy or {}), "ocr_snapshot": configured}
            admission = claim_execution(self.session, run_id=self.claim.run_id, kind="parser",
                capabilities=configured_capabilities(self.settings), parent_generation=self.claim.generation)
            if admission is None:
                self.session.commit()
                raise AppError(QUEUED, "Waiting for PDF parser capacity", status_code=409)
            if not admission.created:
                raise AppError("file_processing_parser_recovery_required", "An existing parser cannot be replayed", status_code=409)
            self.admission = admission
            row = self.session.get(Execution, admission.execution_id)
            self.local = LocalPDF(self.settings, row.policy_snapshot, heartbeat=self.heartbeat, progress=self.progress, raster_dpi=self.raster_dpi)
            need(begin_execution(self.session, execution_id=row.id, generation=row.generation))
            self.session.flush()
            bind_local_workload(self.session, execution_id=row.id, generation=row.generation,
                worker_identity=self.settings.file_processing_worker_runtime_id, worker_pid=os.getpid(),
                launch_uid=self.local.launch_uid)
            self.session.commit()
            self.local.setup()
            result = self.local.run(body, self.program, languages)
            self.store = self.local.store
            self.release("completed", result)
            self.result = result
        except BaseException as exc:
            self.fail_closed()
            if isinstance(exc, AppError) or not isinstance(exc, Exception):
                raise
            code = "pdf_parser_" + exc.code if isinstance(exc, Rejected) else "pdf_parser_unavailable"
            raise AppError(code, "PDF processing failed; output was not accepted", status_code=503) from None

    def text_pages(self, body, *, operation="text"):
        self.prepare(body)
        if operation == "text" and self.program.startswith("text_or_") and self.result["operation"] != "text":
            return [""] * self.result["pages"]
        need(self.result["operation"] == operation, "invalid_output")
        need(self.store.bytes <= self.settings.max_upload_size_mb*1024**2*4, "output_limit")
        return [self.store.read(number).decode("utf-8").strip() for number in range(1, self.result["pages"]+1)]

    def split_pages(self, body):
        self.prepare(body)
        need(self.result["operation"] == "split", "invalid_output")
        return PDFPages(self)

    def image_pages(self, body):
        self.prepare(body)
        need(self.result["operation"] == "raster", "invalid_output")
        return PDFPages(self)

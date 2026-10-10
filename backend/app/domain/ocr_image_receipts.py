"""Claim-bound page receipts; durable intent prevents replay of unknown calls."""
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import AIModelUsageEvent, PipelineRun, PipelineRunStep
from app.domain.model_usage import record_model_usage

KEY = "ocr_image_checkpoint"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def checkpoint(payload):
    if not isinstance(payload, dict):
        return {}
    value = payload.get(KEY) or (payload.get("execution_snapshot") or {}).get(KEY)
    return value if isinstance(value, dict) and value.get("version") == 1 else {}


class ImageOCRJournal:
    def __init__(self, owner, model, version, snapshot, pages, credential_fingerprint):
        self.owner, self.session, self.model = owner, owner.session, model
        self.run = self.session.get(PipelineRun, owner.claim.run_id)
        self.step = self.session.scalar(select(PipelineRunStep).where(
            PipelineRunStep.run_id == self.run.id, PipelineRunStep.step_name == "ocr_extract"))
        self.claim_token = self.step.claim_token
        if model.config_version != snapshot.get("config_version"):
            raise AppError("ocr_model_snapshot_changed", "OCR model configuration changed; create a new extraction revision", status_code=409)
        self.binding = digest({"run": self.run.id, "version": version.id, "source_sha256": version.content_sha256,
            "pages": pages, "snapshot": snapshot, "model": model.id, "config_version": model.config_version,
            "config": model.config, "endpoint": model.endpoint, "credential": model.api_key_encrypted,
            "credential_ref": model.api_key_secret_ref, "credential_fingerprint": credential_fingerprint})
        existing = checkpoint(self.step.artifact_payload)
        if existing and existing.get("binding") != self.binding:
            raise AppError("ocr_image_receipt_conflict", "PDF OCR receipt identity changed", status_code=409)
        if existing.get("intent"):
            raise AppError("ocr_image_provider_result_unknown", "PDF OCR provider result is unconfirmed", status_code=409)
        if not existing and self.session.scalar(select(AIModelUsageEvent.id).where(
                AIModelUsageEvent.pipeline_step_id == self.step.id, AIModelUsageEvent.attempted.is_(True)).limit(1)):
            raise AppError("ocr_partial_retry_requires_review", "Partially attempted PDF OCR requires scoped recovery", status_code=409)
        self.state = existing or {"version": 1, "binding": self.binding, "input_mode": "page_images",
            "dpi": snapshot["pdf_ocr_dpi"], "total_pages": pages, "pages": {}, "intent": None,
            "confirmed_output_tokens": 0, "usage_confirmed": True,
            **{key: snapshot[key] for key in ("ocr_page_max_output_tokens", "ocr_document_max_tokens", "ocr_token_budget_basis", "ocr_token_budget_policy", "ocr_token_settings_hash") if key in snapshot}}

    def _write(self):
        self.owner.fence()
        step = self.session.scalar(select(PipelineRunStep).where(PipelineRunStep.id == self.step.id)
            .with_for_update().execution_options(populate_existing=True))
        if step.status != "running" or step.claim_token != self.claim_token:
            raise AppError("file_processing_task_fenced", "OCR step claim changed", status_code=409)
        step.artifact_payload = {**(step.artifact_payload or {}), KEY: self.state}
        self.session.flush()
        return step

    def reuse(self, page, image_hash, body):
        row = self.state["pages"].get(str(page))
        if not row:
            return None
        if (row.get("image_sha256") != image_hash or row.get("request_sha256") != digest(body)
                or not isinstance(row.get("markdown"), str)
                or row.get("output_sha256") != hashlib.sha256(row["markdown"].encode()).hexdigest()):
            raise AppError("ocr_image_receipt_conflict", "PDF OCR page receipt is invalid", status_code=409)
        evidence = self.session.scalar(select(AIModelUsageEvent.id).where(
            AIModelUsageEvent.pipeline_step_id == self.step.id, AIModelUsageEvent.status == "success",
            AIModelUsageEvent.correlation_id == row["receipt_id"]).limit(1))
        if evidence is None:
            raise AppError("ocr_image_receipt_conflict", "PDF OCR page usage evidence is missing", status_code=409)
        return row

    def start(self, page, image_hash, body):
        self.state = {**self.state, "intent": {"receipt_id": str(uuid4()), "page": page,
            "image_sha256": image_hash, "request_sha256": digest(body),
            "request_max_output_tokens": body["max_output_tokens"], "usage_recorded": False}}
        self._write()
        self.session.commit()  # No database lock spans Provider I/O.

    def error(self, code):
        self.state = {**self.state, "error_code": code}
        self._write()
        self.session.commit()

    def finish(self, attempt, markdown=None):
        intent = self.state["intent"]
        attempt.update(usage_recorded=True, receipt_id=intent["receipt_id"], input_mode="page_images",
                       image_sha256=intent["image_sha256"])
        if markdown is not None:
            entry = {**intent, "markdown": markdown, "output_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                     "usage": attempt["usage"], "latency_ms": attempt["latency_ms"]}
            self.state = {**self.state, "pages": {**self.state["pages"], str(intent["page"]): entry},
                          "intent": None, "error_code": None}
        else:
            self.state = {**self.state, "error_code": attempt.get("error_code"),
                          "intent": intent if attempt["attempted"] else None}
        output = attempt.get("usage", {}).get("output_tokens")
        known = type(output) is int and output >= 0
        self.state = {**self.state,
            "confirmed_output_tokens": self.state.get("confirmed_output_tokens", 0) + (output if known else 0),
            "usage_confirmed": self.state.get("usage_confirmed", True) and (known or not attempt["attempted"])}
        if self.state.get("intent"):
            self.state = {**self.state, "intent": {**self.state["intent"], "usage_recorded": known}}
        self._write()
        record_model_usage(self.session, model=self.model, usage_purpose="ocr_extract", source_channel="pipeline",
            status=attempt["status"], error_code=attempt.get("error_code"), attempted=attempt["attempted"],
            token_usage=attempt["usage"], latency_ms=attempt["latency_ms"], correlation_id=intent["receipt_id"],
            project_id=self.run.project_id, document_id=self.run.document_id,
            document_version_id=self.run.document_version_id, pipeline_run_id=self.run.id,
            pipeline_step_id=self.step.id, actor_user_id=self.run.triggered_by,
            metadata={"physical_page": intent["page"], "input_mode": "page_images",
                      "image_sha256": intent["image_sha256"], "request_max_output_tokens": intent.get("request_max_output_tokens"),
                      "provider_result_unconfirmed": bool(self.state["intent"])})
        self.session.commit()  # Receipt and observed use are committed together.

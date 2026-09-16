"""Genuine processing in an explicitly authorized disposable environment.

The optional local endpoint is a bounded byte transport to the existing real
Provider, not a response adapter. Keys stay in the configured runtime. No input
completion status or vector substitutes for actual pipeline execution.
"""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.db.models import AIModel, ActiveVersionManifest, Chunk, Document, DocumentVersion, GraphSyncJob, PipelineRun, Project
from app.db.session import get_session_factory
from app.domain.extraction_pipeline import execute_auto_extraction, initialize_pipeline_steps
from app.domain.graph_sync_jobs import execute_graph_sync_job
from app.integrations.s3_storage import S3ObjectStorage


def _binding():
    assert os.environ.get("CHG298_ISOLATED") == "1", "BLOCKED: fresh authorized services required"
    path = os.environ.get("CHG298_MODEL_BINDING")
    assert path, "BLOCKED: current model transport and limits must be explicitly configured"
    assert "127.0.0.1" in get_settings().database_url.get_secret_value()
    data = json.loads(Path(path).read_text())
    assert data["project_models_verified"] and data["base_url"].startswith("http://127.0.0.1:")
    return data


def _models(session):
    binding = _binding()
    result = {}
    for source in binding["models"]:
        mid = UUID(source["id"])
        base = f"{binding['base_url']}/{mid}/v1"
        config = {**source["config"], "base_url": base}
        model = session.get(AIModel, mid)
        if model is None:
            model = AIModel(id=mid, name=source["name"], model_type=source["model_type"],
                provider=source["provider"], config_version=source["config_version"],
                endpoint=base, config=config, is_active=True, is_default=False)
            # This is only the newly generated local transport token, never a
            # Provider key. Use the application's real envelope cipher contract.
            model.api_key_encrypted = EnvelopeCipher(get_settings().encryption_key_bytes).encrypt(
                binding["transport_token"], context=f"ai-model:{mid}")
            session.add(model)
        assert model.config == config and model.is_active
        result[model.model_type] = model
    session.flush()
    return result


def candidate(project_id, actor_id, *, document_id=None, major=1):
    """Store a harmless raw source, then execute every real automatic step once."""
    _binding()
    source = f"# CHG298 acceptance\n\n版本 {major} 的驗收說明。申請人須年滿 **18 歲**，並提出身分證明。\n\n1. 提交申請。\n2. 管理人員確認文件。\n"
    raw = source.encode()
    settings = get_settings()
    project_id, actor_id = UUID(str(project_id)), UUID(str(actor_id))
    with get_session_factory()() as session:
        project = session.get(Project, project_id)
        assert project and project.name.startswith("codex-live-")
        models = _models(session)
        original = (project.llm_model_id, project.embedding_model_id, project.ocr_model_id)
        project.llm_model_id, project.embedding_model_id, project.ocr_model_id = models["Chat"].id, models["Embedding"].id, None
        if document_id is None:
            document = Document(project_id=project.id, document_code="CHG298-"+uuid4().hex,
                title="CHG298 acceptance", source_type="upload", status="inactive", created_by=actor_id)
            session.add(document); session.flush()
        else:
            document = session.get(Document, UUID(str(document_id)))
            assert document and document.project_id == project.id and document.document_code.startswith("CHG298-")
        vid = uuid4(); key = f"chg298/{document.id}/{vid}.md"
        storage = S3ObjectStorage(settings); storage.ensure_bucket(settings.s3_bucket)
        stored = storage.put_object(bucket=settings.s3_bucket, key=key, body=raw, content_type="text/markdown")
        loaded = storage.get_object(bucket=settings.s3_bucket, key=key)
        assert loaded.body == raw
        version = DocumentVersion(id=vid, project_id=project.id, document_id=document.id,
            version_major=major, extraction_revision=0, version_label=f"v{major}.0", status="processing",
            original_file_name="chg298.md", canonical_extension=".md", mime_type="text/markdown",
            file_size=len(raw), content_sha256=hashlib.sha256(raw).hexdigest(),
            storage_bucket=settings.s3_bucket, storage_key=key, storage_etag=stored.etag,
            original_snapshot_uri=f"s3://{settings.s3_bucket}/{key}",
            chunk_strategy={"source_text":loaded.body.decode(), "text_layer_status":"reliable", "force_ocr":False},
            embedding_model_id=models["Embedding"].id, llm_model_id=models["Chat"].id, lock_version=1)
        session.add(version); session.flush()
        pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=vid,
            project_generation=project.work_generation, run_type="document_extraction", status="queued",
            triggered_by=actor_id, created_at=datetime.now(UTC))
        session.add(pipeline); session.flush()
        initialize_pipeline_steps(session, pipeline, ocr_model_id=None, ocr_name="reliable text layer", force_ocr=False)
        session.commit()
        try:
            execute_auto_extraction(session=session, settings=settings, project=project,
                document=document, version=version, pipeline=pipeline, durable=True)
            assert pipeline.status == "submission_ready", (str(pipeline.id), pipeline.current_step_name, pipeline.error_message)
            chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == vid)))
            assert 1 <= len(chunks) <= 2 and all(c.retrieval_text and c.embedding_content_hash for c in chunks)
            return {"project_id":str(project.id), "document_id":str(document.id), "version_id":str(vid), "pipeline_id":str(pipeline.id)}
        finally:
            project.llm_model_id, project.embedding_model_id, project.ocr_model_id = original
            session.commit()


def approve_and_publish(client, headers, actor, data):
    """Actual authenticated evidence, approvals and publication; no state seeding."""
    def ok(response, status=200):
        assert response.status_code == status, response.text
        return response.json()
    pid, did, vid = data["project_id"], data["document_id"], data["version_id"]
    base = f"/api/v1/projects/{pid}/documents/{did}/versions/{vid}"
    evidence = ok(client.get(base+"/submission-evidence", headers=headers))
    request = ok(client.post(base+"/submit-review", headers={**headers,"Idempotency-Key":f"chg298-submit-{vid}"},
        json={"owner_user_id":str(actor),"evidence_revision":evidence["evidence_revision"],"lock_version":evidence["lock_version"]}),201)
    for stage in ("manager_review","owner_review"):
        tasks = ok(client.get("/api/v1/approvals/pending", headers=headers))["items"]
        task = next(t for t in tasks if t["approval_request_id"]==request["id"] and t["review_stage"]==stage)
        result = ok(client.post(f"/api/v1/approvals/{task['id']}/approve",
            headers={**headers,"Idempotency-Key":f"chg298-{stage}-{vid}"},json={"lock_version":task["lock_version"],"comment":"CHG298 real acceptance"}))
        assert result["status"]=="approved"
    with get_session_factory()() as session:
        version = session.get(DocumentVersion,UUID(vid)); assert version.status=="approved"
        lock_version = version.lock_version
    result = ok(client.post(f"/api/v1/document-versions/{vid}/publish",
        headers={**headers,"Idempotency-Key":f"chg298-publish-{vid}"},json={"lock_version":lock_version,"impact_confirmed":True}))
    with get_session_factory()() as session:
        execute_graph_sync_job(session,settings=get_settings(),job_id=UUID(result["graph_sync_job_id"]))
        job=session.get(GraphSyncJob,UUID(result["graph_sync_job_id"]))
        assert job.status=="completed", job.error_code
        manifest=session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_id==UUID(did)))
        assert str(manifest.document_version_id)==vid and manifest.index_ready
    return result

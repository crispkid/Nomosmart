from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep, time
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.api.routes.serving import (
    _canonical_json_hash,
    _validation_execution_manifest,
)
from app.db.models import (
    AIModel,
    ActiveVersionManifest,
    ApprovalRequest,
    ApprovalTask,
    AuditLog,
    ChatRecord,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingBuild,
    GraphSyncJob,
    Notification,
    OutboxEvent,
    PipelineRun,
    PipelineRunStep,
    Project,
    User,
    ValidationRun,
    ValidationRunItem,
)
from app.db.session import get_engine
from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter, publish_version
from app.worker import dispatch_outbox
from scripts.milestone7_live_acceptance import (
    _assert_env_file_ready,
    _delete_neo4j_fixture,
    _delete_opensearch_index,
    _seed_publish_fixture,
    _verify_opensearch_documents,
)


class AcceptanceProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        messages = payload.get("messages") or []
        system = str(messages[0].get("content", "")) if messages else ""
        if "strict validation judge" in system:
            content = json.dumps({"score": 1.0, "reason": "acceptance provider verified grounded answer"})
        else:
            content = "Milestone 8B live acceptance alpha content is available from the published source [1]."
        body = {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 10, "total_tokens": 22},
        }
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    run_id = uuid4()
    settings = None
    index_name: str | None = None
    graph_ids: dict[str, UUID] = {}
    db_ids: dict[str, object] = {}
    previous_default_judge_ids: list[UUID] = []
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    worker_process: subprocess.Popen[str] | None = None

    try:
        _assert_env_file_ready()
        from app.core.config import get_settings

        settings = get_settings()

        server = ThreadingHTTPServer(("127.0.0.1", 0), AcceptanceProviderHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        provider_endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        worker_process = _start_celery_worker()

        print("milestone8b-live: checking PostgreSQL and required schema", flush=True)
        engine = get_engine()
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text("select 1"))
            _assert_required_tables(session)
            _cleanup_stale_acceptance_rows(session)

            print("milestone8b-live: publishing controlled fixture through live adapters", flush=True)
            fixture = _seed_publish_fixture(session, run_id, settings=settings)
            actor: User = fixture["actor"]  # type: ignore[assignment]
            project: Project = fixture["project"]  # type: ignore[assignment]
            document: Document = fixture["document"]  # type: ignore[assignment]
            version: DocumentVersion = fixture["version"]  # type: ignore[assignment]
            pipeline: PipelineRun = fixture["pipeline"]  # type: ignore[assignment]

            previous_default_judge_ids = list(
                session.scalars(select(AIModel.id).where(AIModel.model_type == "Judge", AIModel.is_default.is_(True)))
            )
            for existing_default in session.scalars(select(AIModel).where(AIModel.id.in_(previous_default_judge_ids))):
                existing_default.is_default = False
            session.flush()

            chat_model = AIModel(
                name=f"Milestone 8B Chat {str(run_id)[:8]}",
                model_type="Chat",
                provider="vLLM",
                endpoint=provider_endpoint,
                is_active=True,
                is_default=False,
                config={"model_name": "acceptance-chat", "temperature": 0, "max_tokens": 256, "timeout_seconds": 5},
            )
            judge_model = AIModel(
                name=f"Milestone 8B Judge {str(run_id)[:8]}",
                model_type="Judge",
                provider="vLLM",
                endpoint=provider_endpoint,
                is_active=True,
                is_default=True,
                config={"model_name": "acceptance-judge", "temperature": 0, "max_tokens": 256, "timeout_seconds": 5},
            )
            session.add_all([chat_model, judge_model])
            session.flush()
            project.llm_model_id = chat_model.id

            manifest, index_result, graph_job = publish_version(
                session=session,
                actor_user_id=actor.id,
                document=document,
                version=version,
                lock_version=1,
                request_id=f"milestone8b-live-{run_id}",
                search_adapter=LiveOpenSearchPublishedAdapter(settings),
                graph_adapter=LiveNeo4jGraphSyncAdapter(settings),
            )
            index_name = index_result.index_name
            graph_ids = {"project_id": project.id, "document_id": document.id, "version_id": version.id}
            _verify_opensearch_documents(settings, index_name, index_result.document_ids)

            selected_validation_ids = {version.id}
            validation_max_attempts = 3
            validation_manifest = _validation_execution_manifest(
                session,
                project=project,
                scope_mode="published",
                selected_ids=selected_validation_ids,
                max_attempts=validation_max_attempts,
            )
            validation_run = ValidationRun(
                project_id=project.id,
                project_generation=project.work_generation,
                uploaded_file_name="milestone8b-live.csv",
                status="queued",
                run_scope="project_chat",
                selected_document_ids=[str(version.id)],
                execution_manifest=validation_manifest,
                execution_manifest_hash=_canonical_json_hash(validation_manifest),
                max_attempts=validation_max_attempts,
                total_count=1,
                completed_count=0,
                failed_count=0,
                created_by=actor.id,
                created_at=datetime.now(UTC),
            )
            session.add(validation_run)
            session.flush()
            validation_input = {
                "question": "Milestone 7 live acceptance alpha content",
                "expected_answer": "Milestone 8B live acceptance alpha content",
                "expected_keywords": ["Milestone 8B", "alpha content"],
                "selected_document_ids": [str(version.id)],
                "category": None,
                "priority": None,
            }
            item = ValidationRunItem(
                run_id=validation_run.id,
                input_item_id=uuid4(),
                input_ordinal=1,
                input_content_hash=_canonical_json_hash(validation_input),
                question=validation_input["question"],
                expected_answer=validation_input["expected_answer"],
                expected_keywords=validation_input["expected_keywords"],
                selected_document_ids=validation_input["selected_document_ids"],
                status="pending",
                created_at=datetime.now(UTC),
            )
            outbox = OutboxEvent(
                topic="validation.run.requested",
                aggregate_type="validation_run",
                aggregate_id=validation_run.id,
                payload={"run_id": str(validation_run.id), "project_id": str(project.id)},
                status="pending",
                attempts=0,
                available_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            session.add_all([item, outbox])
            session.commit()

            db_ids = {
                "actor_id": actor.id,
                "project_id": project.id,
                "document_id": document.id,
                "version_id": version.id,
                "pipeline_id": pipeline.id,
                "chat_model_id": chat_model.id,
                "judge_model_id": judge_model.id,
                "previous_default_judge_ids": previous_default_judge_ids,
                "validation_run_id": validation_run.id,
                "outbox_id": outbox.id,
            }

        print("milestone8b-live: dispatching validation outbox through Celery worker", flush=True)
        dispatch_outbox.run()
        _wait_for_validation_run(db_ids["validation_run_id"])

        with Session(engine, expire_on_commit=False) as session:
            completed_run = session.get(ValidationRun, db_ids["validation_run_id"])
            if completed_run is None:
                raise RuntimeError("validation run disappeared before verification")
            completed_items = list(session.scalars(select(ValidationRunItem).where(ValidationRunItem.run_id == completed_run.id)))
            if completed_run.status != "completed" or completed_run.completed_count != 1 or completed_run.failed_count != 0:
                raise RuntimeError(f"validation run did not complete successfully: {completed_run.status}")
            completed_item = completed_items[0]
            if completed_item.status not in {"passed", "completed"} or not completed_item.answer or not completed_item.chat_record_id:
                raise RuntimeError("validation item did not persist answer and chat record")
            if not completed_item.reference_docs:
                raise RuntimeError("validation item did not persist citations")
            chat_record = session.get(ChatRecord, completed_item.chat_record_id)
            if chat_record is None or chat_record.llm_model_id != db_ids["chat_model_id"] or not chat_record.token_usage:
                raise RuntimeError("chat record did not persist model metadata")
            if completed_item.score is None or float(completed_item.score) < 0.99:
                raise RuntimeError(f"judge score was not accepted: {completed_item.score}")

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "run_id": str(run_id),
                        "validation_run_id": str(completed_run.id),
                        "validation_status": completed_run.status,
                        "opensearch_index": index_name,
                        "citations": len(completed_item.reference_docs),
                        "chat_record_id": str(chat_record.id),
                        "judge_score": float(completed_item.score),
                        "provider_endpoint": "local-openai-compatible",
                    },
                    sort_keys=True,
                )
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - command must expose live acceptance failure
        print(f"milestone8b-live: failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        if worker_process is not None:
            _stop_celery_worker(worker_process)
        if settings is not None and index_name:
            _delete_opensearch_index(settings, index_name)
        if settings is not None and graph_ids:
            _delete_neo4j_fixture(settings, graph_ids)
        if db_ids:
            _cleanup_database(db_ids)
        elif previous_default_judge_ids:
            _restore_default_judges(previous_default_judge_ids)


def _assert_required_tables(session: Session) -> None:
    required = {
        "active_version_manifests",
        "ai_models",
        "chat_records",
        "validation_runs",
        "validation_run_items",
        "outbox_events",
    }
    rows = session.execute(
        text(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
              and table_name = any(:tables)
            """
        ),
        {"tables": list(required)},
    )
    found = {row[0] for row in rows}
    missing = sorted(required - found)
    if missing:
        raise RuntimeError(f"missing required Milestone 8B tables: {', '.join(missing)}")


def _cleanup_stale_acceptance_rows(session: Session) -> None:
    project_ids = list(session.scalars(select(Project.id).where(Project.name.like("Milestone 7 Live %"))))
    version_ids = list(session.scalars(select(DocumentVersion.id).where(DocumentVersion.project_id.in_(project_ids)))) if project_ids else []
    document_ids = list(session.scalars(select(Document.id).where(Document.project_id.in_(project_ids)))) if project_ids else []
    pipeline_ids = list(session.scalars(select(PipelineRun.id).where(PipelineRun.project_id.in_(project_ids)))) if project_ids else []
    validation_run_ids = list(session.scalars(select(ValidationRun.id).where(ValidationRun.uploaded_file_name == "milestone8b-live.csv")))
    actor_ids = list(session.scalars(select(User.id).where(User.keycloak_user_id.like("milestone7-live-%"))))
    acceptance_model_ids = list(session.scalars(select(AIModel.id).where(AIModel.name.like("Milestone 8B %"))))

    if not any((project_ids, validation_run_ids, actor_ids, acceptance_model_ids)):
        return

    if actor_ids:
        session.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(actor_ids)))
    if project_ids:
        session.execute(delete(Notification).where(Notification.project_id.in_(project_ids)))
    if validation_run_ids:
        session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(validation_run_ids)))
        session.execute(delete(ValidationRunItem).where(ValidationRunItem.run_id.in_(validation_run_ids)))
        session.execute(delete(ValidationRun).where(ValidationRun.id.in_(validation_run_ids)))
    if project_ids:
        session.execute(delete(ChatRecord).where(ChatRecord.project_id.in_(project_ids)))
    if pipeline_ids:
        session.execute(delete(PipelineRunStep).where(PipelineRunStep.run_id.in_(pipeline_ids)))
        session.execute(delete(PipelineRun).where(PipelineRun.id.in_(pipeline_ids)))
    if version_ids:
        session.execute(delete(ApprovalTask).where(ApprovalTask.document_version_id.in_(version_ids)))
        session.execute(delete(ApprovalRequest).where(ApprovalRequest.document_version_id.in_(version_ids)))
        session.execute(delete(ActiveVersionManifest).where(ActiveVersionManifest.document_version_id.in_(version_ids)))
        session.execute(delete(GraphSyncJob).where(GraphSyncJob.document_version_id.in_(version_ids)))
        session.execute(delete(EmbeddingBuild).where(EmbeddingBuild.document_version_id.in_(version_ids)))
        session.execute(delete(Chunk).where(Chunk.document_version_id.in_(version_ids)))
        session.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))
    if document_ids:
        session.execute(delete(Document).where(Document.id.in_(document_ids)))
    if project_ids:
        session.execute(delete(Project).where(Project.id.in_(project_ids)))
    if acceptance_model_ids:
        session.execute(delete(AIModel).where(AIModel.id.in_(acceptance_model_ids)))
    if actor_ids:
        session.execute(delete(User).where(User.id.in_(actor_ids)))
    session.flush()


def _start_celery_worker() -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.worker:celery_app",
        "worker",
        "--pool",
        "solo",
        "--concurrency",
        "1",
        "--loglevel",
        "WARNING",
        "--without-gossip",
        "--without-mingle",
        "--without-heartbeat",
    ]
    process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S603
    sleep(3)
    if process.poll() is not None:
        output = process.stdout.read() if process.stdout else ""
        raise RuntimeError(f"Celery worker exited before acceptance dispatch: {output[-1000:]}")
    return process


def _stop_celery_worker(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_validation_run(run_id: UUID, *, timeout_seconds: int = 30) -> None:
    deadline = time() + timeout_seconds
    engine = get_engine()
    last_status = None
    while time() < deadline:
        with Session(engine, expire_on_commit=False) as session:
            run = session.get(ValidationRun, run_id)
            if run is not None:
                last_status = run.status
                if run.status in {"completed", "partial_failed", "failed", "cancelled"}:
                    return
        sleep(1)
    raise RuntimeError(f"validation run did not finish before timeout; last_status={last_status}")


def _cleanup_database(ids: dict[str, object]) -> None:
    engine = get_engine()
    with Session(engine) as session:
        run_id = ids["validation_run_id"]
        project_id = ids["project_id"]
        document_id = ids["document_id"]
        version_id = ids["version_id"]
        pipeline_id = ids["pipeline_id"]
        actor_id = ids["actor_id"]
        session.execute(delete(AuditLog).where(AuditLog.actor_user_id == actor_id))
        session.execute(delete(Notification).where(Notification.project_id == project_id))
        session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == run_id))
        session.execute(delete(ValidationRunItem).where(ValidationRunItem.run_id == run_id))
        session.execute(delete(ValidationRun).where(ValidationRun.id == run_id))
        session.execute(delete(ChatRecord).where(ChatRecord.project_id == project_id))
        session.execute(delete(ApprovalTask).where(ApprovalTask.document_version_id == version_id))
        session.execute(delete(ApprovalRequest).where(ApprovalRequest.document_version_id == version_id))
        session.execute(delete(PipelineRunStep).where(PipelineRunStep.run_id == pipeline_id))
        session.execute(delete(PipelineRun).where(PipelineRun.id == pipeline_id))
        session.execute(delete(ActiveVersionManifest).where(ActiveVersionManifest.document_version_id == version_id))
        session.execute(delete(GraphSyncJob).where(GraphSyncJob.document_version_id == version_id))
        session.execute(delete(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version_id))
        session.execute(delete(Chunk).where(Chunk.document_version_id == version_id))
        session.execute(delete(DocumentVersion).where(DocumentVersion.id == version_id))
        session.execute(delete(Document).where(Document.id == document_id))
        session.execute(delete(Project).where(Project.id == project_id))
        session.execute(delete(AIModel).where(AIModel.id.in_([ids["chat_model_id"], ids["judge_model_id"]])))
        _restore_default_judges(ids.get("previous_default_judge_ids") or [], session=session)
        session.execute(delete(User).where(User.id == actor_id))
        session.commit()


def _restore_default_judges(model_ids: object, *, session: Session | None = None) -> None:
    if not model_ids:
        return
    if isinstance(model_ids, UUID):
        ids = [model_ids]
    elif isinstance(model_ids, (list, tuple, set)):
        ids = [value for value in model_ids if isinstance(value, UUID)]
    else:
        ids = []
    if not ids:
        return
    owns_session = session is None
    active_session = session or Session(get_engine())
    try:
        for model in active_session.scalars(select(AIModel).where(AIModel.id.in_(ids[:1]))):
            model.is_default = True
        if owns_session:
            active_session.commit()
    finally:
        if owns_session:
            active_session.close()


if __name__ == "__main__":
    raise SystemExit(main())

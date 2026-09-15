from __future__ import annotations

from pathlib import Path
import re

from sqlalchemy.dialects import postgresql

from app.api.routes import reports as report_routes
from app.api.routes import serving as serving_routes
from app.core.contracts import (
    IDEMPOTENCY_TRANSITIONS,
    PROJECT_CAPABILITY_KEYS,
    STABLE_ERROR_STATUS,
    AuditAction,
    IdempotencyState,
    ProjectCapability,
    StableErrorCode,
    empty_project_capabilities,
)
from app.core.errors import AppError
from app.security.secrets import parse_runtime_secret_reference
from app.domain.uploads import validate_source_extension


ROOT = Path(__file__).resolve().parents[2]


def test_stable_error_and_audit_identifiers_are_unique_and_machine_safe() -> None:
    identifier = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
    error_values = [item.value for item in StableErrorCode]
    audit_values = [item.value for item in AuditAction]
    assert len(error_values) == len(set(error_values))
    assert len(audit_values) == len(set(audit_values))
    assert all(identifier.fullmatch(value) for value in [*error_values, *audit_values])
    assert set(STABLE_ERROR_STATUS) == set(StableErrorCode)


def test_idempotency_terminal_states_do_not_reopen() -> None:
    assert IDEMPOTENCY_TRANSITIONS[IdempotencyState.SUCCEEDED] == frozenset()
    assert IDEMPOTENCY_TRANSITIONS[IdempotencyState.CANCELLED] == frozenset()
    assert IDEMPOTENCY_TRANSITIONS[IdempotencyState.EXPIRED] == frozenset()
    assert IdempotencyState.SUCCEEDED in IDEMPOTENCY_TRANSITIONS[IdempotencyState.PROCESSING]
    assert IdempotencyState.PROCESSING in IDEMPOTENCY_TRANSITIONS[IdempotencyState.FAILED]


def test_perm_005_capability_vocabulary_is_fixed_and_deny_by_default() -> None:
    assert PROJECT_CAPABILITY_KEYS == (
        "can_upload",
        "can_update_source",
        "can_start_extraction",
        "can_reextract",
        "can_edit_chunks",
        "can_create_reference",
        "can_sync_source",
        "can_view_graph",
        "can_submit_review",
        "can_manage_lifecycle",
        "can_archive_project",
        "can_retry_archive_cleanup",
    )
    assert len(PROJECT_CAPABILITY_KEYS) == len(ProjectCapability)
    assert empty_project_capabilities() == {key: False for key in PROJECT_CAPABILITY_KEYS}


def test_runtime_secret_parser_accepts_only_mounted_secret_identities() -> None:
    parsed = parse_runtime_secret_reference(
        "k8s-secret://nomosmart-runtime-secrets#openai-api-key"
    )
    assert parsed.provider == "kubernetes"
    assert parsed.name == "nomosmart-runtime-secrets"
    assert parsed.key == "openai-api-key"
    compose = parse_runtime_secret_reference("compose-secret://openai-api-key")
    assert compose.provider == "compose"
    assert compose.name == "openai-api-key"

    for invalid in (
        "k8s-secret://runtime",
        "k8s-secret://runtime#../api-key",
        "k8s-secret://runtime?version=1#api-key",
        "k8s-secret://user@runtime#api-key",
        "compose-secret://api-key#field",
    ):
        try:
            parse_runtime_secret_reference(invalid)
        except AppError as exc:
            assert exc.code == "runtime_secret_reference_invalid"
            assert invalid not in exc.message
        else:
            raise AssertionError(f"invalid runtime Secret reference was accepted: {invalid}")


def test_readiness_has_no_environment_shortcut_and_checks_live_dependencies() -> None:
    route_source = (ROOT / "backend/app/api/routes/health.py").read_text(encoding="utf-8")
    dependency_source = (ROOT / "backend/app/integrations/health.py").read_text(encoding="utf-8")
    assert 'settings.app_env == "test"' not in route_source
    assert "sentinel_primary_ready" in dependency_source
    assert "heartbeat_current" in dependency_source
    assert "_cluster/health" in dependency_source
    assert "required_bucket_ready" in dependency_source


def test_graph_retry_and_switch_active_use_durable_hashed_idempotent_commands() -> None:
    retry_source = (ROOT / "backend/app/api/routes/compatibility.py").read_text(encoding="utf-8")
    approval_source = (ROOT / "backend/app/api/routes/approvals.py").read_text(encoding="utf-8")
    worker_source = (ROOT / "backend/app/worker.py").read_text(encoding="utf-8")
    graph_source = (ROOT / "backend/app/domain/graph_sync_jobs.py").read_text(encoding="utf-8")
    migration_source = (ROOT / "sql/migrations/V033__graph_sync_durable_attempts.sql").read_text(encoding="utf-8")

    retry_body = retry_source.split("def retry_graph_sync_job(", 1)[1].split(
        "\ndef _embedding_settings_response", 1
    )[0]
    assert "Idempotency-Key" in retry_body
    assert "begin_idempotent_operation(" in retry_body
    assert "enqueue_graph_sync(" in retry_body
    assert "LiveNeo4jGraphSyncAdapter" not in retry_body
    assert "status_code=202" in retry_source

    switch_body = approval_source.split("def switch_document_version_active(", 1)[1].split(
        "\ndef _pending_query", 1
    )[0]
    assert "required=True" in switch_body
    assert "graph_adapter=" not in switch_body
    assert "canonical_request_hash" not in approval_source
    assert "IdempotencyKey.key == key" not in approval_source

    assert "GRAPH_SYNC_TOPIC: run_graph_sync" in worker_source
    assert "acks_late=True, reject_on_worker_lost=True" in worker_source
    assert 'status="queued"' in graph_source
    assert "claim_token" in graph_source
    assert "lease_expires_at" in graph_source
    assert "parent_job_id" in migration_source
    assert "requested_by_user_id" in migration_source


def test_scoped_graph_and_cursor_inventories_have_no_global_content_alias() -> None:
    serving = (ROOT / "backend/app/api/routes/serving.py").read_text(encoding="utf-8")
    compatibility = (ROOT / "backend/app/api/routes/compatibility.py").read_text(encoding="utf-8")
    identity = (ROOT / "backend/app/api/routes/identity.py").read_text(encoding="utf-8")
    schemas = (ROOT / "backend/app/api/schemas.py").read_text(encoding="utf-8")

    assert '@router.get("/projects/{project_id}/graph"' in serving
    assert '@router.get("/projects/{project_id}/graph/neighbors"' in serving
    assert '@router.get("/projects/{project_id}/graph/paths"' in serving
    assert '@router.get("/knowledge-graph' not in serving

    assert 'scope_mode: Literal["published", "document_staging"] = Query(...)' in serving
    assert 'namespace="chat-conversations"' in serving
    assert 'namespace="validation-run-inventory"' in serving
    assert 'namespace="validation-run-items"' in serving
    assert 'namespace="notifications"' in serving
    assert "class NotificationPage" in schemas
    assert "class IdentitySyncRunPage" in schemas
    assert 'namespace="identity-sync-runs"' in identity
    assert 'namespace="pipeline-runs"' in compatibility
    assert 'namespace="graph-sync-jobs"' in compatibility
    assert 'namespace="audit-logs"' in compatibility
    assert "_redact_audit_summary" in compatibility


def test_validation_attempt_lineage_is_immutable_and_exported() -> None:
    migration = (ROOT / "sql/migrations/V040__validation_item_attempt_lineage.sql").read_text(encoding="utf-8")
    manifest_migration = (ROOT / "sql/migrations/V041__validation_execution_manifest.sql").read_text(encoding="utf-8")
    serving = (ROOT / "backend/app/api/routes/serving.py").read_text(encoding="utf-8")
    runner = (ROOT / "backend/app/domain/validation_runner.py").read_text(encoding="utf-8")
    evidence = (ROOT / "backend/app/domain/submission_evidence.py").read_text(encoding="utf-8")

    for column in ("parent_item_id", "attempt", "is_current", "error_code"):
        assert column in migration
        assert f'"{column}"' in serving
        assert f'"{column}"' in evidence
    assert "ValidationRunItem.is_current.is_(True)" in runner
    assert "item.is_current = False" in serving
    assert "attempt=item.attempt + 1" in serving
    for column in (
        "execution_manifest",
        "execution_manifest_hash",
        "max_attempts",
        "input_item_id",
        "input_ordinal",
        "input_content_hash",
        "legacy_manifest_unavailable",
    ):
        assert column in manifest_migration
    assert "input_item_id=item.input_item_id" in serving
    assert "input_ordinal=item.input_ordinal" in serving
    assert "validation_retry_limit_reached" in serving
    assert "_validation_execution_manifest(" in serving
    assert "_public_validation_manifest(" in serving
    assert "_validate_execution_manifest(" in runner
    assert "_manifest_prompt(" in runner
    assert '(run.execution_manifest or {})["retrieval_top_k"]' in runner
    assert "validation_retrieval_manifest_invalid" in runner


def test_validation_manifest_public_projection_is_safe_and_hash_is_canonical() -> None:
    manifest = {
        "manifest_version": "validation-v1",
        "state": "available",
        "chat_prompt": {
            "content": "private chat instructions",
            "content_hash": "chat-hash",
            "layers": [],
        },
        "judge_prompt": {
            "content": "private judge instructions",
            "content_hash": "judge-hash",
            "layers": [],
        },
        "selected_document_version_ids": ["00000000-0000-0000-0000-000000000001"],
    }
    public_manifest = serving_routes._public_validation_manifest(manifest)

    assert "content" not in public_manifest["chat_prompt"]
    assert "content" not in public_manifest["judge_prompt"]
    assert manifest["chat_prompt"]["content"] == "private chat instructions"
    assert serving_routes._canonical_json_hash({"b": 2, "a": 1}) == (
        serving_routes._canonical_json_hash({"a": 1, "b": 2})
    )


def test_report_summary_and_export_are_datastore_bounded() -> None:
    reports = (ROOT / "backend/app/api/routes/reports.py").read_text(encoding="utf-8")
    config = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    assert "REPORT_ALL_ROWS_LIMIT" not in reports
    assert "_topic_page(" in reports
    assert ".offset(offset).limit(limit)" in reports
    assert "_iter_topic_batches(" in reports
    assert "stream_results=True" in reports
    assert "yield_per=batch_size" in reports
    assert "request.is_disconnected()" in reports
    assert "statement_timeout" in reports
    assert 'action="report.csv.export.started"' in reports
    assert 'action=f"report.csv.export.{result}"' in reports
    assert "report_export_batch_size" in config
    assert "report_export_timeout_seconds" in config


def test_report_group_adapters_compile_as_stable_postgresql_pages() -> None:
    statements = (
        report_routes._project_reference_group_statement(None, None, None),
        report_routes._document_reference_group_statement(None, None, None),
        report_routes._alert_group_statement(None, None, None),
        report_routes._model_usage_statement(None, None, None),
    )
    for statement in statements:
        sql = str(
            statement.offset(25)
            .limit(25)
            .compile(dialect=postgresql.dialect())
        ).upper()
        assert "GROUP BY" in sql
        assert "ORDER BY" in sql
        assert " LIMIT " in sql
        assert " OFFSET " in sql


def test_file_source_formats_and_ordered_upload_contract_are_canonical() -> None:
    for filename in ("policy.pdf", "policy.docx", "notes.txt", "readme.md"):
        assert validate_source_extension(filename)
        assert validate_source_extension(filename, http_response=True)
    for filename in ("table.csv", "payload.json"):
        try:
            validate_source_extension(filename)
        except ValueError:
            pass
        else:
            raise AssertionError(f"file source accepted HTTP-only format: {filename}")
        assert validate_source_extension(filename, http_response=True)

    source = (ROOT / "backend/app/api/routes/documents.py").read_text(encoding="utf-8")
    upload_body = source.split("async def upload_documents(", 1)[1].split(
        "\n\n@router.post", 1
    )[0]
    assert "status_code=200" in source
    assert "Idempotency-Key" in upload_body
    assert "get_session_factory()" in upload_body
    assert "_process_upload_item(" in upload_body
    assert "success_count=" in upload_body
    assert "failed_count=" in upload_body
    assert "start_extraction = len(payload.files) == 1" in source
    assert "storage.compensate()" in source

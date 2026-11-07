"""CHG-384: genuine retained SQL evidence, native refusals, no Provider replay."""
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent, Chunk, DocumentVersion, ValidationRun, ValidationRunItem
from app.db.session import get_session_factory
from app.domain.chunk_deletion import delete_candidate_chunk
from app.domain.validation_runner import _record_validation_usage, _validate_input_item
from current_live_support import load_current_context
from scripts.current_e2e_governance_fixture import read_private


@pytest.fixture(scope="module")
def retained_judge():
    context = load_current_context()
    source = Path(__file__).resolve().parents[2]
    approval = json.loads((source / "docs/CHG-384-APPROVAL.json").read_text())
    assert approval["gate_4"] == "APPROVED" and approval["approved_by"] == "Peter"
    assert sha256((source / approval["plan"]).read_bytes()).hexdigest() == approval["plan_sha256"]
    assert approval["original_run_uuid"] == context["run_id"]
    phase = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
    data = read_private(phase.parent / "remaining-deletion-real-input.json")
    assert data["run_uuid"] == context["run_id"]
    return context, data, phase


def snapshot(session):
    tables = ("document_versions", "chunks", "embedding_build_vectors", "chat_records",
        "validation_runs", "validation_run_items", "ai_model_usage_events", "outbox_events", "audit_logs")
    # Fixed identifiers only. Keep row contents private; compare complete values.
    value = {table: list(session.scalars(text(
        f"SELECT to_jsonb(r) FROM {table} r ORDER BY to_jsonb(r)::text"))) for table in tables}
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def actual_rows(session, data):
    version = session.get(DocumentVersion, UUID(data["version_id"]))
    item = session.get(ValidationRunItem, UUID(data["validation_item_id"]))
    assert version and item and version.published_at is None and version.status == "submission_ready"
    run = session.get(ValidationRun, item.run_id)
    judge = session.scalar(select(AIModelUsageEvent).where(
        AIModelUsageEvent.validation_run_item_id == item.id,
        AIModelUsageEvent.usage_purpose == "validation_judge"))
    assert run and run.document_version_id == version.id and run.status == "completed"
    assert judge and judge.validation_run_id == run.id and judge.document_version_id is None and judge.status == "failed"
    return version, run, item, judge


def write_proof(phase, name, value):
    with (phase / name).open("x") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)


def test_real_validation_refusal_usage_preserves_known_version_without_inference(retained_judge):
    context, data, phase = retained_judge
    source = Path(__file__).resolve().parents[1] / "app/domain/validation_runner.py"
    tree = ast.parse(source.read_text())
    connections = []
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in {"_execute_item", "_score_answer"}:
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_record_validation_usage":
                    assert len(call.args) == 3 and [a.id for a in call.args] == ["session", "run", "item"]
                    keywords = {k.arg: k.value for k in call.keywords}
                    connections.append((fn.name, ast.literal_eval(keywords["usage_purpose"]), ast.literal_eval(keywords["status"])))
    assert sorted(connections) == sorted([("_execute_item", "validation_answer", "failed"),
        ("_score_answer", "validation_judge", "success"), ("_score_answer", "validation_judge", "failed")])
    factory = get_session_factory()
    with factory() as session:
        before = snapshot(session)
        transaction = session.begin_nested()
        try:
            version, run, item, judge = actual_rows(session, data)
            item.input_content_hash = "0" * 64  # Native invalid input, never a fabricated model result.
            with pytest.raises(AppError) as refusal:
                _validate_input_item(item)
            assert refusal.value.code == "validation_input_integrity_failed"
            answer = session.scalar(select(AIModelUsageEvent).where(
                AIModelUsageEvent.validation_run_item_id == item.id,
                AIModelUsageEvent.usage_purpose == "validation_answer"))
            assert answer and answer.status == "success" and answer.document_version_id == version.id
            for original in (judge, answer):
                event = _record_validation_usage(session, run, item, model=session.get(AIModel, original.model_id),
                    usage_purpose=original.usage_purpose, status="failed", attempted=False, error_code=refusal.value.code)
                session.expire(event)
                assert event.document_version_id == version.id and event.project_id == run.project_id
                assert event.validation_run_id == run.id and event.validation_run_item_id == item.id
                assert not event.attempted and event.status == "failed" and event.error_code == refusal.value.code
                assert event.input_tokens is None and event.output_tokens is None
            for known_version, selection in ((None, run.selected_document_ids),
                    (version.id, [str(version.id), data["source_version_id"]])):
                run.document_version_id, run.selected_document_ids = known_version, selection
                event = _record_validation_usage(session, run, item, model=session.get(AIModel, judge.model_id),
                    usage_purpose="validation_judge", status="failed", attempted=False, error_code=refusal.value.code)
                session.expire(event)
                assert event.document_version_id is None and not event.attempted
        finally:
            transaction.rollback()
        assert snapshot(session) == before
    write_proof(phase, "chg384-native-context.json", {"run_uuid": context["run_id"],
        "known_version_for_judge_and_answer_verified_in_real_database": True,
        "unknown_or_ambiguous_version_not_guessed": True, "original_database_snapshot_restored": True,
        "native_refusal_code": refusal.value.code, "new_model_calls": 0,
        "success_branch_scope": "source_connection_only_not_provider_success_e2e",
        "validation_runner_sha256": sha256(source.read_bytes()).hexdigest()})


def test_real_legacy_judge_conflicts_refuse_atomically_without_model_replay(retained_judge):
    context, data, phase = retained_judge
    factory = get_session_factory()
    controls = []
    with factory() as session:
        before = snapshot(session)
        for kind in ("explicit_foreign_version", "missing_run", "run_item_mismatch",
                     "foreign_project", "protected_run", "multiple_versions"):
            transaction = session.begin_nested()
            try:
                version, run, item, judge = actual_rows(session, data)
                foreign_version = session.get(DocumentVersion, UUID(data["source_version_id"]))
                assert foreign_version and foreign_version.id != version.id
                if kind == "explicit_foreign_version":
                    judge.document_version_id = foreign_version.id
                elif kind == "missing_run":
                    judge.validation_run_id = None
                elif kind == "run_item_mismatch":
                    other_run = session.scalar(select(ValidationRun).where(ValidationRun.id != run.id))
                    assert other_run
                    judge.validation_run_id = other_run.id
                elif kind == "foreign_project":
                    assert foreign_version.project_id != version.project_id
                    judge.project_id = foreign_version.project_id
                elif kind == "protected_run":
                    run.run_scope = "published"
                else:
                    run.selected_document_ids = [str(version.id), str(foreign_version.id)]
                session.flush()
                with pytest.raises(AppError) as refused:
                    delete_candidate_chunk(session, version, session.get(Chunk, UUID(data["second_chunk_id"])),
                        actor_id=UUID(context["actors"]["project_owner"]["user_id"]),
                        request_id="chg384-native-refusal-" + kind)
                assert refused.value.code == "chunk_delete_reference_conflict" and refused.value.status_code == 409
            finally:
                transaction.rollback()
            assert snapshot(session) == before
            controls.append({"kind": kind, "code": refused.value.code, "complete_rollback_verified": True})
    write_proof(phase, "chg384-native-refusals.json", {"run_uuid": context["run_id"],
        "controls": controls, "new_model_calls": 0, "original_database_snapshot_restored": True})

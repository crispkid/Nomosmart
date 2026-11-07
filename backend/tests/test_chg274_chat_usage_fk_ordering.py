from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import AIModel, AIModelUsageEvent, ChatRecord, Project, User
from app.db.session import get_session_factory
from app.domain.model_usage import record_model_usage


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _function_calls(path: Path, function_name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    return sorted(
        (node for node in ast.walk(function) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    )


def _is_session_call(call: ast.Call, method: str, argument_name: str | None = None) -> bool:
    function = call.func
    if not (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "session"
        and function.attr == method
    ):
        return False
    if argument_name is None:
        return True
    if not call.args:
        return False
    argument = call.args[0]
    if method == "flush" and isinstance(argument, ast.List) and len(argument.elts) == 1:
        argument = argument.elts[0]
    return isinstance(argument, ast.Name) and argument.id == argument_name


def _is_linked_usage_call(call: ast.Call, parent_name: str, parent_attribute: str) -> bool:
    if not isinstance(call.func, ast.Name) or call.func.id != "record_model_usage":
        return False
    keyword = next((item for item in call.keywords if item.arg == "chat_record_id"), None)
    return bool(
        keyword
        and isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.value.id == parent_name
        and keyword.value.attr == parent_attribute
    )


def _assert_chat_parent_is_flushed_before_usage(path: Path, function_name: str) -> None:
    calls = _function_calls(path, function_name)
    add_index = next(index for index, call in enumerate(calls) if _is_session_call(call, "add", "record"))
    flush_index = next(index for index, call in enumerate(calls) if _is_session_call(call, "flush", "record"))
    usage_index = next(index for index, call in enumerate(calls) if _is_linked_usage_call(call, "record", "id"))

    assert add_index < flush_index < usage_index
    assert not any(_is_session_call(call, "commit") for call in calls[add_index + 1 : usage_index])


def test_document_chat_flushes_parent_before_linked_usage() -> None:
    _assert_chat_parent_is_flushed_before_usage(
        BACKEND_ROOT / "app/api/routes/serving.py",
        "query_project_chat",
    )


def test_csv_validation_flushes_parent_before_linked_usage() -> None:
    _assert_chat_parent_is_flushed_before_usage(
        BACKEND_ROOT / "app/domain/validation_runner.py",
        "_execute_item",
    )


def test_public_api_parent_first_ordering_remains_unchanged() -> None:
    calls = _function_calls(BACKEND_ROOT / "app/api/routes/public_api.py", "_create_public_log")
    add_index = next(index for index, call in enumerate(calls) if _is_session_call(call, "add", "log"))
    flush_index = next(index for index, call in enumerate(calls) if _is_session_call(call, "flush"))

    assert add_index < flush_index


def test_real_postgresql_accepts_parent_first_usage_and_rollback_is_atomic() -> None:
    session_factory = get_session_factory()
    user_id = uuid4()
    model_id = uuid4()
    project_id = uuid4()
    record_id = uuid4()
    event_id = uuid4()

    with session_factory() as session:
        user = User(
            id=user_id,
            employee_id=f"Z{user_id.hex[:9]}",
            keycloak_user_id=f"chg274-{user_id}",
            email=f"chg274-{user_id}@example.test",
            display_name="CHG-274 FK Tester",
            auth_source="keycloak",
            is_active=True,
        )
        session.add(user)
        session.flush([user])

        model = AIModel(
            id=model_id,
            name=f"chg274-{model_id.hex[:12]}",
            model_type="Chat",
            provider="Custom",
            endpoint="https://example.invalid/v1",
            is_active=True,
            is_default=False,
            config={"model_name": "chg274-transaction-probe"},
            config_version=1,
        )
        session.add(model)
        session.flush([model])

        project = Project(
            id=project_id,
            name=f"CHG-274 {project_id.hex[:12]}",
            description="Foreign-key ordering transaction probe",
            status="active",
            llm_model_id=model.id,
            created_by=user.id,
        )
        session.add(project)
        session.flush([project])

        record_created_at = datetime.now(UTC)
        record = ChatRecord(
            id=record_id,
            project_id=project.id,
            scope_mode="document_staging",
            conversation_id=uuid4(),
            conversation_title="CHG-274 transaction probe",
            selected_document_version_ids=[],
            question="CHG-274 transaction probe",
            answer="No provider call is made by this test.",
            reference_docs=[],
            evaluation="not_evaluated",
            llm_model_id=model.id,
            token_usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            latency_ms=0,
            created_by=user.id,
            asked_at=record_created_at,
            answered_at=record_created_at,
            created_at=record_created_at,
        )
        session.add(record)
        session.flush([record])
        event = record_model_usage(
            session,
            model=model,
            usage_purpose="chat_test",
            source_channel="chat_test",
            status="success",
            token_usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            latency_ms=0,
            project_id=project.id,
            chat_record_id=record.id,
            actor_user_id=user.id,
        )
        event_id = event.id

        assert session.get(ChatRecord, record_id) is not None
        assert session.get(AIModelUsageEvent, event_id) is not None
        invalid_record = ChatRecord(
            id=uuid4(),
            project_id=uuid4(),
            scope_mode="document_staging",
            conversation_id=uuid4(),
            conversation_title="CHG-274 forced rollback probe",
            selected_document_version_ids=[],
            question="Force a later project foreign-key failure.",
            answer=None,
            reference_docs=[],
            evaluation="not_evaluated",
            created_by=user.id,
            asked_at=record_created_at,
            created_at=record_created_at,
        )
        session.add(invalid_record)
        with pytest.raises(IntegrityError):
            session.flush([invalid_record])
        session.rollback()

    with session_factory() as session:
        assert session.get(ChatRecord, record_id) is None
        assert session.get(AIModelUsageEvent, event_id) is None
        assert session.get(Project, project_id) is None
        assert session.get(AIModel, model_id) is None
        assert session.get(User, user_id) is None

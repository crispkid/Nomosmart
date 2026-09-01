from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
SCRIPT_PATH = ROOT / "backend" / "scripts" / "backfill_chat_record_scope.py"
sys.path.insert(0, str(BACKEND_ROOT))
spec = importlib.util.spec_from_file_location("backfill_chat_record_scope", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
backfill = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backfill
spec.loader.exec_module(backfill)


def test_chat_scope_backfill_requires_bounded_selector() -> None:
    with pytest.raises(SystemExit):
        backfill.parse_args(["--scope-mode", "document_staging"])


def test_chat_scope_backfill_apply_requires_expected_count() -> None:
    with pytest.raises(SystemExit):
        backfill.parse_args(
            [
                "--scope-mode",
                "document_staging",
                "--document-version-id",
                "8922faee-d74d-4167-ae59-5ef07b14d821",
                "--apply",
            ]
        )


def test_chat_scope_backfill_builds_bounded_null_scope_where_clause() -> None:
    where_clause, params = backfill.build_where_clause(
        {
            "document_version_id": "8922faee-d74d-4167-ae59-5ef07b14d821",
            "created_by": "7d4250f0-7fe9-4432-8ab9-e34c70ee6126",
        }
    )

    assert "scope_mode IS NULL" in where_clause
    assert "document_version_id = :document_version_id" in where_clause
    assert "created_by = :created_by" in where_clause
    assert params == {
        "document_version_id": "8922faee-d74d-4167-ae59-5ef07b14d821",
        "created_by": "7d4250f0-7fe9-4432-8ab9-e34c70ee6126",
    }


def test_chat_scope_backfill_rejects_unknown_selectors() -> None:
    with pytest.raises(ValueError):
        backfill.build_where_clause({"document_id": "8922faee-d74d-4167-ae59-5ef07b14d821"})


def test_chat_scope_backfill_contract_is_schema_ready_and_guarded() -> None:
    source = (ROOT / "backend" / "scripts" / "backfill_chat_record_scope.py").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "V016__chat_record_scope_mode.sql").read_text(encoding="utf-8")
    serving = (ROOT / "backend" / "app" / "api" / "routes" / "serving.py").read_text(encoding="utf-8")

    assert "information_schema.columns" in source
    assert "chat_records.scope_mode is missing" in source
    assert "scope_mode IS NULL" in source
    assert "--expected-count is required with --apply" in source
    assert "candidate count" in source
    assert "UPDATE chat_records SET scope_mode = :scope_mode WHERE" in source
    assert "ADD COLUMN IF NOT EXISTS scope_mode" in migration
    assert "ChatRecord.scope_mode == scope_mode" in serving
    assert 'scope="published"' in serving

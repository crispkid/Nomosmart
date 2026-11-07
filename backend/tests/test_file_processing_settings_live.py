"""CHG-305 real-PostgreSQL policy tests; no OIDC login/CLI acceptance claim."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

# Import-only coverage is not OIDC/CLI acceptance; main() is not invoked.
# Keep all unexecuted new CLI paths in the measured product denominator.
import app.deployment.file_processing_policy

from app.core.errors import AppError
from app.db.models import AuditLog, FileProcessingPolicyRevision, RolePermission, SystemParameter, User
from app.domain.file_processing_settings import (FileProcessingSettings, PlatformCapabilities, UNITS,
    authorize_maintenance, initialize_policy, load_policy, update_policy)
from chg305_support import CAPS, initialize, live_db


def change(db, changes, revision=1, capabilities=CAPS):
    with db["factory"].begin() as session:
        return update_policy(session, principal=db["principal"], expected_revision=revision,
                             changes=changes, capabilities=capabilities)


def test_initialize_preserves_repeat_import_and_unrelated_settings(live_db):
    db = live_db
    with db["factory"].begin() as session:
        session.add(SystemParameter(key="pdf_parser_max_pages", value=333, default_value=222,
            value_type="integer", unit="pages", description="Existing controlled configuration"))
    first = initialize(db, timeout=180, pages=500, upload=20)
    assert first.schema_version == 2
    assert first.settings.document_processing_timeout_seconds == 180
    assert set(first.settings.model_dump()) == set(UNITS)
    second = initialize(db, timeout=120, pages=200, upload=100)
    assert second == first
    with db["factory"].begin() as session:
        assert load_policy(session) == first
        assert session.scalar(select(func.count()).select_from(FileProcessingPolicyRevision)) == 1
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "pdf_parser_max_pages"))
        assert row.default_value == 222
        assert session.scalar(select(SystemParameter).where(SystemParameter.key == "default_timezone")) is not None
        history = session.get(FileProcessingPolicyRevision, 1)
        assert history.provenance["preserved_keys"] == []
        assert row.value == 333  # Retained legacy input never becomes active runtime policy.


@pytest.mark.parametrize("changes", [
    {"pdf_parser_max_concurrent": 0}, {"pdf_parser_max_concurrent": -1}, {"pdf_parser_max_concurrent": True},
    {"pdf_parser_max_concurrent": "2"}, {"pdf_parser_max_concurrent": 2.5}, {"pdf_parser_max_pages": 2001},
    {"pdf_parser_memory_mib": 128}, {"file_processing_background_poll_interval_seconds": 1},
    {"pdf_parser_retryable_error_codes": ["encrypted_pdf"]}, {"pdf_parser_retryable_error_codes": "*"},
    {"pdf_parser_retryable_error_codes": [3]}, {"docker_socket": "/elsewhere"}, {},
    {"document_processing_max_concurrent": 0}, {"document_processing_max_concurrent": True},
    {"document_processing_max_concurrent": "2"}, {"document_processing_max_concurrent": 2.5},
    {"document_processing_max_concurrent": 10001}, {"document_processing_timeout_seconds": 0},
    {"file_processing_progress_interval_seconds": 301},
])
def test_invalid_policy_is_atomic(live_db, changes):
    original = initialize(live_db)
    with pytest.raises(AppError):
        change(live_db, changes)
    with live_db["factory"].begin() as session:
        assert load_policy(session) == original
        assert session.scalar(select(func.count()).select_from(FileProcessingPolicyRevision)) == 1


def test_retired_container_fields_read_only_and_active_scratch_independent(live_db):
    original = initialize(live_db)
    for key in ("pdf_parser_cpu_millicores", "pdf_parser_memory_mib"):
        with pytest.raises(AppError) as failure:
            change(live_db, {key: 1024})
        assert failure.value.code == "file_processing_parameter_deprecated"
        with live_db["factory"].begin() as session:
            assert load_policy(session) == original
    # Same legacy values in a full update remain legal, with unchanged hashes.
    assert change(live_db, original.settings.model_dump(mode="json")) == original
    with pytest.raises(AppError) as retired:
        change(live_db, {"pdf_parser_scratch_mib": 1024})
    assert retired.value.code == "file_processing_parameter_deprecated"
    updated = change(live_db, {"document_dispatch_yield_delay_seconds": 6})
    assert updated.settings.document_dispatch_yield_delay_seconds == 6
    assert updated.revision == original.revision + 1


def test_compare_and_swap_concurrent_writers_and_audit(live_db):
    db = live_db
    initialize(db)
    def writer(value):
        try:
            return change(db, {"document_processing_max_concurrent": value}).revision
        except AppError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(writer, (2, 3)))
    assert sorted(result, key=str) == [2, "file_processing_policy_conflict"]
    with db["factory"].begin() as session:
        current = load_policy(session)
        history = session.get(FileProcessingPolicyRevision, 2)
        audit = session.scalar(select(AuditLog).where(AuditLog.actor_user_id == db["actor"],
            AuditLog.action == "file_processing.policy.updated").order_by(AuditLog.created_at.desc()).limit(1))
        assert history.snapshot == current.settings.model_dump(mode="json")
        assert audit.summary["previous"]["document_processing_max_concurrent"] == 10
        assert audit.summary["current"] == history.snapshot
    assert change(db, {"document_processing_max_concurrent": current.settings.document_processing_max_concurrent}, revision=2) == current


def test_missing_policy_and_direct_sql_drift_fail_closed(live_db):
    db = live_db
    with db["factory"].begin() as session:
        with pytest.raises(AppError, match="File-processing") as failure:
            load_policy(session)
        assert failure.value.code == "file_processing_policy_missing"
    initialize(db)
    with db["factory"].begin() as session:
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "document_processing_max_concurrent"))
        row.value = 123
    with db["factory"].begin() as session:
        with pytest.raises(AppError) as failure:
            load_policy(session)
        assert failure.value.code == "file_processing_policy_revision_mismatch"


def test_metadata_capability_deployment_and_legacy_guards(live_db):
    db = live_db
    with pytest.raises(AppError):
        initialize(db, timeout=0)
    snapshot = initialize(db, upload=True)
    assert snapshot.schema_version == 2  # Retired upload hint cannot change document budgets.
    # R20 Worker-local processing permits an absent optional platform maximum;
    # it must still reject a malformed partial contract and an exceeded active cap.
    for caps in (PlatformCapabilities({"document_processing_timeout_seconds": 1000}), PlatformCapabilities(CAPS.maxima | {"document_processing_max_concurrent": 5})):
        with pytest.raises(AppError):
            change(db, {"document_processing_max_concurrent": 201}, capabilities=caps)
    assert change(db, snapshot.settings.model_dump(mode="json"), capabilities=PlatformCapabilities({})) == snapshot
    with db["factory"].begin() as session:
        with pytest.raises(AppError):
            initialize_policy(session, principal=db["principal"], deployment_id=db["actor"],
                legacy_timeout_seconds=120, legacy_max_pages=200, legacy_upload_mib=100, capabilities=CAPS)
        assert load_policy(session) == snapshot
    with db["factory"].begin() as session:
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "document_processing_timeout_seconds"))
        row.unit = "wrong"
    with db["factory"].begin() as session:
        with pytest.raises(AppError) as failure:
            load_policy(session)
        assert failure.value.code == "file_processing_parameter_metadata_invalid"


def test_domain_identity_active_permissions_and_expiry(live_db):
    db = live_db
    initialize(db)
    expired = replace(db["principal"], expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with db["factory"].begin() as session:
        with pytest.raises(AppError):
            authorize_maintenance(session, expired, write=True)
        permission = session.scalar(select(RolePermission).where(RolePermission.role_id == db["role"]))
        permission.can_edit = False
    with pytest.raises(AppError):
        change(db, {"document_processing_max_concurrent": 2})
    with db["factory"].begin() as session:
        assert authorize_maintenance(session, db["principal"], write=False) == db["actor"]
        session.get(User, db["actor"]).is_active = False
    with db["factory"].begin() as session:
        with pytest.raises(AppError):
            authorize_maintenance(session, db["principal"], write=False)


def test_retry_catalog_canonical_hash_and_no_extra_keys(live_db):
    from copy import deepcopy
    from pathlib import Path
    import json
    from scripts.chg413_runtime import Scope
    from app.domain.file_processing_settings import LegacyFileProcessingSettings

    first = initialize(live_db)
    result = change(live_db, {"document_dispatch_yield_delay_seconds": 6})
    assert result.settings.content_hash != first.settings.content_hash
    assert set(result.settings.model_dump()) == set(UNITS)
    assert FileProcessingSettings.model_validate(result.settings.model_dump(mode="json")) == result.settings
    # Actual retained v1 format is input to the native compatibility decoder;
    # this neither creates a historical row nor enables a parser/retry.
    authority = Scope()
    source = authority.parent.root / "cleanup412/recovery/before055.json"
    raw = source.read_bytes()
    history = json.loads(raw)["policy_history"][0]
    original = LegacyFileProcessingSettings.model_validate(history["snapshot"])
    assert original.content_hash == history["content_hash"]
    value = deepcopy(history["snapshot"])
    value["pdf_parser_retryable_error_codes"] *= 2
    decoded = LegacyFileProcessingSettings.model_validate(value)
    assert decoded.pdf_parser_retryable_error_codes == original.pdf_parser_retryable_error_codes
    assert decoded.content_hash == original.content_hash
    assert source.read_bytes() == raw

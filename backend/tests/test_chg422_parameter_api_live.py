"""REL422-003: real HTTPS/session/CAS tests in this run's disposable database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, text

GROUPS = {
    "general": ("default_timezone", "session_expired_form_draft_ttl_minutes"),
    "documents": ("max_upload_size_mb", "staging_index_ttl_days", "ocr_request_max_output_tokens", "ocr_document_max_tokens"),
}


@pytest.fixture(scope="module")
def live():
    path = Path(os.environ["CHG422_LIVE_API_CONTEXT"])
    assert path.is_absolute() and path.resolve() == path and not path.is_symlink()
    assert path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0
    context = json.loads(path.read_text())
    owner = json.loads((path.parent.parent / "owner.json").read_text())
    assert owner["change_id"] == "CHG-422" and not owner["execution_closed"]
    assert owner["run_uuid"] == context["run_uuid"]
    assert datetime.now(UTC) < datetime.fromisoformat(owner["deadline"])
    root = Path(__file__).resolve().parents[2]
    assert root == Path(context["source_root"])
    assert sha256((root / "docs/CHG-422-BASELINE-INTEGRATION-PLAN.md").read_bytes()).hexdigest() == owner["plan_sha256"]
    for name, digest in context["source"].items():
        assert (root / name).is_file() and sha256((root / name).read_bytes()).hexdigest() == digest
    assert {str(p.relative_to(root)) for p in (root / "backend/app").rglob("*.py")} <= set(context["source"])
    engine = create_engine(context["database_url"], hide_parameters=True)
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        assert connection.scalar(text("SELECT run_id FROM current_test_control.ownership")) == UUID(context["run_uuid"])
        assert connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")) is True
        assert connection.scalar(text("SELECT current_database()")) == "nomosmart422fresh"
    clients = {}
    for alias in ("owner", "viewer", "no_roles", "system_editor"):
        actor = context["actors"][alias]
        client = httpx.Client(base_url=context["origin"] + "/api/v1/", verify=context["ca_file"],
            trust_env=False, timeout=20, headers={"Origin": context["origin"]})
        response = client.post("auth/login", json={"username": actor["username"], "password": actor["password"]})
        assert response.status_code == 200
        session = client.get("auth/session")
        assert session.status_code == 200 and session.json()["authenticated"] is True
        client.headers["X-CSRF-Token"] = session.json()["csrf_token"]
        clients[alias] = client
    original = parameters(clients["owner"])
    try:
        yield clients, engine
    finally:
        for section, keys in GROUPS.items():
            current = parameters(clients["owner"])
            changes = {key: original[key] for key in keys if current[key] != original[key]}
            if changes:
                assert patch(clients["owner"], current, section, changes).status_code == 200
        for client in clients.values():
            client.close()
        engine.dispose()


def parameters(client):
    response = client.get("system/parameters")
    assert response.status_code == 200
    return response.json()


def patch(client, current, section, values):
    return client.patch("system/parameters", json={"section": section,
        "expected_revision": current["section_revisions"][section], "values": values})


def audits(engine):
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return connection.scalar(text("SELECT count(*) FROM audit_logs WHERE action='system.parameters.update'"))


def test_native_get_defaults_metadata_and_legacy_history(live):
    clients, _ = live
    value = parameters(clients["owner"])
    assert value["ocr_token_budget_policy"] == "output-document-v2"
    assert type(value["ocr_page_max_output_tokens"]) is int
    assert set(value["section_revisions"]) == set(GROUPS)
    assert set(value["parameter_defaults"]) == {key for keys in GROUPS.values() for key in keys}
    assert set(value["parameter_metadata"]) == set(value["parameter_defaults"])
    assert 0 < value["ocr_request_max_output_tokens"] <= value["ocr_document_max_tokens"]
    assert value["max_upload_size_mb"] <= value["deployment_max_upload_size_mb"]


def test_permissions_and_csrf_are_enforced_by_server(live):
    clients, engine = live
    before = parameters(clients["owner"])
    count = audits(engine)
    assert clients["viewer"].get("system/parameters").status_code == 200
    assert patch(clients["viewer"], before, "general", {"default_timezone": "UTC"}).status_code == 403
    assert clients["no_roles"].get("system/parameters").status_code == 403
    csrf = clients["owner"].headers.pop("X-CSRF-Token")
    try:
        assert patch(clients["owner"], before, "general", {"default_timezone": "UTC"}).status_code == 403
    finally:
        clients["owner"].headers["X-CSRF-Token"] = csrf
    # edit is sufficient without create/delete, which were removed by the genuine role API.
    saved = patch(clients["system_editor"], before, "general", {"default_timezone": before["default_timezone"]})
    assert saved.status_code == 200 and saved.json()["changed"] is False
    assert parameters(clients["owner"]) == before and audits(engine) == count


@pytest.mark.parametrize("values", [
    {}, {"default_timezone": None}, {"default_timezone": "invalid/not-a-zone"},
    {"default_timezone": "UTC", "max_upload_size_mb": 1},
    {"session_expired_form_draft_ttl_minutes": True},
    {"session_expired_form_draft_ttl_minutes": "5"},
    {"session_expired_form_draft_ttl_minutes": 4},
])
def test_invalid_general_updates_are_atomic(live, values):
    clients, engine = live
    before = parameters(clients["owner"])
    count = audits(engine)
    assert patch(clients["owner"], before, "general", values).status_code == 422
    assert parameters(clients["owner"]) == before and audits(engine) == count


def test_capacity_native_budget_and_retired_page_updates_are_atomic(live):
    clients, engine = live
    before = parameters(clients["owner"])
    count = audits(engine)
    invalid = [
        {"max_upload_size_mb": before["deployment_max_upload_size_mb"] + 1},
        {"max_upload_size_mb": 1, "ocr_request_max_output_tokens": before["ocr_document_max_tokens"] + 1},
        {"ocr_request_max_output_tokens": False}, {"ocr_request_max_output_tokens": None},
        {"ocr_page_max_output_tokens": before["ocr_page_max_output_tokens"] + 1},
    ]
    for values in invalid:
        assert patch(clients["owner"], before, "documents", values).status_code == 422
        assert parameters(clients["owner"]) == before and audits(engine) == count


def test_missing_revision_duplicate_keys_and_bounded_body(live):
    clients, engine = live
    before = parameters(clients["owner"])
    count = audits(engine)
    assert clients["owner"].patch("system/parameters", json={"section": "general", "values": {"default_timezone": "UTC"}}).status_code == 428
    raw = '{"section":"general","expected_revision":'+json.dumps(before["section_revisions"]["general"])+',"values":{"default_timezone":"UTC","default_timezone":"Asia/Tokyo"}}'
    assert clients["owner"].patch("system/parameters", content=raw, headers={"Content-Type": "application/json"}).status_code == 422
    assert clients["owner"].patch("system/parameters", content='{"padding":"'+'x'*16385+'"}', headers={"Content-Type": "application/json"}).status_code == 422
    assert parameters(clients["owner"]) == before and audits(engine) == count


def test_same_section_competition_and_aba_reject_stale_revisions(live):
    clients, engine = live
    owner = clients["owner"]
    before = parameters(owner)
    count = audits(engine)
    barrier = Barrier(2)
    options = [value for value in (5, 10, 15) if value != before["session_expired_form_draft_ttl_minutes"]][:2]
    def save(value):
        barrier.wait(timeout=5)
        return patch(owner, before, "general", {"session_expired_form_draft_ttl_minutes": value})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, value) for value in options]
        assert sorted(f.result().status_code for f in futures) == [200, 409]
    assert audits(engine) == count + 1
    current = parameters(owner)
    assert patch(owner, current, "general", {"session_expired_form_draft_ttl_minutes": before["session_expired_form_draft_ttl_minutes"]}).status_code == 200
    after = parameters(owner)
    assert after["session_expired_form_draft_ttl_minutes"] == before["session_expired_form_draft_ttl_minutes"]
    assert after["section_revisions"]["general"] != before["section_revisions"]["general"]
    assert patch(owner, before, "general", {"default_timezone": "UTC"}).status_code == 409


def test_cross_section_writes_preserve_both_changes(live):
    clients, _ = live
    owner = clients["owner"]
    before = parameters(owner)
    barrier = Barrier(2)
    zone = "UTC" if before["default_timezone"] != "UTC" else "Asia/Tokyo"
    upload = max(1, before["max_upload_size_mb"] - 1)
    def save(section, values):
        barrier.wait(timeout=5)
        return patch(owner, before, section, values)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(save, "general", {"default_timezone": zone})
        two = pool.submit(save, "documents", {"max_upload_size_mb": upload})
        assert one.result().status_code == two.result().status_code == 200
    after = parameters(owner)
    assert after["default_timezone"] == zone and after["max_upload_size_mb"] == upload
    assert owner.get("system/upload-config").json()["max_upload_size_mb"] == upload


def test_compatibility_put_preserves_native_hash_and_page_retirement(live):
    clients, engine = live
    owner = clients["owner"]
    before = parameters(owner)
    values = {key: before[key] for keys in GROUPS.values() for key in keys}
    assert owner.put("system/parameters", json=values).status_code == 428
    body = {**values, "expected_section_revisions": before["section_revisions"],
        "expected_ocr_token_settings_hash": before["ocr_token_settings_hash"],
        "ocr_page_max_output_tokens": before["ocr_page_max_output_tokens"]}
    count = audits(engine)
    same = owner.put("system/parameters", json=body)
    assert same.status_code == 200 and same.json() == before and audits(engine) == count
    denied = owner.put("system/parameters", json={**body, "ocr_page_max_output_tokens": before["ocr_page_max_output_tokens"] + 1})
    assert denied.status_code == 422 and denied.json()["code"] == "ocr_page_token_setting_retired"
    assert owner.put("system/parameters", json={**body, "expected_ocr_token_settings_hash": "0"*64}).status_code == 409
    assert parameters(owner) == before and audits(engine) == count


def test_draft_ttl_reader_disabled_sensitive_fields_and_single_restore(live):
    clients, _ = live
    owner = clients["owner"]
    before = parameters(owner)
    assert patch(owner, before, "general", {"session_expired_form_draft_ttl_minutes": 0}).status_code == 200
    payload = {"form_key": "system.parameters", "return_path": "/system?section=general", "nonce": "CHG422-genuine-draft-nonce-32characters", "payload": {"timezone": "UTC"}}
    denied = owner.post("auth/session-drafts", json=payload)
    assert denied.status_code == 422 and denied.json()["code"] == "session_draft_disabled"
    assert patch(owner, parameters(owner), "general", {"session_expired_form_draft_ttl_minutes": 5}).status_code == 200
    sensitive = owner.post("auth/session-drafts", json={**payload, "payload": {"api_key": "synthetic-refused-input"}})
    assert sensitive.status_code == 422 and sensitive.json()["code"] == "session_draft_sensitive_field"
    created = owner.post("auth/session-drafts", json=payload)
    assert created.status_code == 200
    draft = created.json()
    restore = {"return_path": payload["return_path"], "nonce": payload["nonce"]}
    saved = owner.post("auth/session-drafts/"+draft["draft_id"]+"/restore", json=restore)
    assert saved.status_code == 200 and saved.json()["payload"] == payload["payload"]
    assert owner.post("auth/session-drafts/"+draft["draft_id"]+"/restore", json=restore).status_code == 409

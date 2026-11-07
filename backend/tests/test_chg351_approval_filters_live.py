"""Read-only approval API contracts against the approved disposable TLS/OIDC run.

Authentication arrives through an anonymous inherited FD, never a stored token.
These query checks do not assert extraction, decisions or publication succeeded.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import ssl
from datetime import datetime

import httpx
import pytest


@pytest.fixture(scope="module")
def live():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_approval_filter_support import current_approval_query_case
        with current_approval_query_case() as value:
            yield value
        return
    descriptor = os.environ.get("CHG351_AUTH_PACKET_FD")
    if descriptor is None:
        pytest.skip("BLOCKED: current approved CHG-351 anonymous OIDC packet required")
    with os.fdopen(int(descriptor)) as stream:
        packet = json.load(stream)
    original = Path(packet["original_root"])
    approval = json.loads((original / "docs/CHG-351-PLAN-STATUS.json").read_text())
    runtime = json.loads((original / ".operator/chg351/runtime/run.json").read_text())
    assert approval["gate_4"]["status"] == "APPROVED"
    assert hashlib.sha256((original / approval["plan"]["path"]).read_bytes()).hexdigest() == approval["plan"]["sha256"]
    assert runtime["run_id"] == packet["run_id"] and not runtime.get("cleanup")
    assert packet["origin"] == runtime["origin"] == "https://localhost:38443"
    assert datetime.now().timestamp() < runtime["runtime_deadline"]
    assert packet["ca_file"] == str(Path(runtime["source"]) / "deploy/docker/generated/current/tls/active/edge-ca.crt")
    client = httpx.Client(base_url=packet["origin"] + "/api/backend", verify=ssl.create_default_context(cafile=packet["ca_file"]), trust_env=False, timeout=30)
    yield packet, client
    client.close()


def read(live, path, params=None, actor="owner", status=200):
    packet, client = live
    if packet.get("current_session_transport") is True:
        response = packet["actual_live"].actor(packet["actor_names"][actor]).get(path.lstrip("/"), params=params)
    else:
        response = client.get(path, params=params, headers={"Authorization": "Bearer " + packet["tokens"][actor]})
    assert response.status_code == status, f"HTTP {response.status_code}; expected {status}"
    return response.json()


def all_rows(live, path, params=None, actor="owner"):
    rows, seen, pages = [], set(), 0
    query = dict(params or {})
    while True:
        page = read(live, path, query, actor)
        pages += 1
        assert pages <= 20
        for row in page["items"]:
            assert row["id"] not in seen
            seen.add(row["id"])
            rows.append(row)
        if not page["has_more"]:
            assert page["next_cursor"] is None
            return rows, pages
        assert page["next_cursor"]
        query["cursor"] = page["next_cursor"]


def test_pending_filters_apply_before_cursor(live):
    seed = live[0]["seed"]
    expected = {r["task_id"] for r in seed["records"] if r["status"] == "pending" and r["stage"] == "owner_review"}
    rows, pages = all_rows(live, "/approvals/pending")
    assert pages >= 2
    assert {r["id"] for r in rows} == expected


def test_document_keyword_and_literal_wildcards(live):
    rows, _ = all_rows(live, "/approvals/pending", {"q": "目標報表"})
    assert {r["document_id"] for r in rows} == {r["document_id"] for r in live[0]["seed"]["records"] if r["index"] in (28, 29, 44)}
    rows, _ = all_rows(live, "/approvals/pending", {"q": "%_\\"})
    assert len(rows) == 1 and "%_\\" in rows[0]["document_title"]
    rows, _ = all_rows(live, "/approvals/pending", {"q": "quarterly target"})
    assert len(rows) == 1


def test_combined_filters_and_submitter_not_document_creator(live):
    seed = live[0]["seed"]
    query = {"q": "目標報表", "project_id": seed["projects"][0], "submitter_id": seed["actors"]["editor"], "stage": "owner_review", "priority": "high", "source_type": "upload"}
    rows, _ = all_rows(live, "/approvals/pending", query)
    assert {r["id"] for r in rows} == {r["task_id"] for r in seed["records"] if r["index"] == 29}
    query["submitter_id"] = seed["actors"]["owner"]
    assert all_rows(live, "/approvals/pending", query)[0] == []


def test_editor_alias_agrees_or_rejects_conflict(live):
    seed = live[0]["seed"]
    submitter = seed["actors"]["editor"]
    modern = all_rows(live, "/approvals/pending", {"submitter_id": submitter})[0]
    legacy = all_rows(live, "/approvals/pending", {"editor_id": submitter})[0]
    both = all_rows(live, "/approvals/pending", {"editor_id": submitter, "submitter_id": submitter})[0]
    assert [r["id"] for r in modern] == [r["id"] for r in legacy] == [r["id"] for r in both]
    error = read(live, "/approvals/pending", {"editor_id": seed["actors"]["owner"], "submitter_id": submitter}, status=422)
    assert error["code"] == "approval_filter_conflict"


def test_my_submissions_preserves_self_and_current_stage(live):
    seed = live[0]["seed"]
    expected = {r["request_id"] for r in seed["records"] if r["submitter_id"] == seed["actors"]["editor"]}
    rows, pages = all_rows(live, "/approvals/my-submissions", actor="editor")
    assert pages >= 2 and {r["id"] for r in rows} == expected
    rows, _ = all_rows(live, "/approvals/my-submissions", {"stage": "owner_review"}, "editor")
    assert {r["id"] for r in rows} == {r["request_id"] for r in seed["records"] if r["submitter_id"] == seed["actors"]["editor"] and r["stage"] == "owner_review" and r["status"] == "pending"}
    assert all_rows(live, "/approvals/my-submissions", actor="viewer")[0] == []


def test_history_and_rejected_scope(live):
    seed = live[0]["seed"]
    rejected = {r["task_id"] for r in seed["records"] if r["status"] == "rejected"}
    assert {r["id"] for r in all_rows(live, "/approvals/history", {"result": "rejected"})[0]} == rejected
    assert {r["id"] for r in all_rows(live, "/approvals/rejected")[0]} == rejected
    assert len(all_rows(live, "/approvals/history", {"result": "cancelled"})[0]) == 4


def test_candidate_paging_and_scope(live):
    candidates, pages = all_rows(live, "/approvals/filter-options", {"kind": "submitter", "tab": "pending"})
    assert len(candidates) > 20 and pages >= 2
    assert all_rows(live, "/approvals/filter-options", {"kind": "submitter", "tab": "pending"}, "viewer")[0] == []
    scoped, _ = all_rows(live, "/approvals/filter-options", {"kind": "project", "tab": "pending"}, "manager")
    assert live[0]["seed"]["projects"][2] not in {r["id"] for r in scoped}


def test_actor_and_filter_cursor_binding(live):
    page = read(live, "/approvals/pending", {"limit": 1})
    assert page["has_more"]
    for query, actor in [({"limit": 1, "q": "目標報表"}, "owner"), ({"limit": 1}, "manager")]:
        query["cursor"] = page["next_cursor"]
        assert read(live, "/approvals/pending", query, actor, 422)["code"] == "cursor_scope_mismatch"
    option = read(live, "/approvals/filter-options", {"kind": "submitter", "tab": "pending", "limit": 1})
    assert read(live, "/approvals/filter-options", {"kind": "project", "tab": "pending", "cursor": option["next_cursor"]}, status=422)["code"] == "cursor_scope_mismatch"


def test_inclusive_database_microsecond_boundary(live):
    rows, _ = all_rows(live, "/approvals/pending", {"date_from": "2026-10-17T16:00:00Z", "date_to": "2026-10-18T15:59:59.999999Z"})
    assert {r["document_id"] for r in rows} == {r["document_id"] for r in live[0]["seed"]["records"] if r["index"] == 31}


def test_denied_project_does_not_leak_options(live):
    query = {"kind": "project", "tab": "pending", "project_id": live[0]["seed"]["projects"][2]}
    read(live, "/approvals/filter-options", query, "manager", 403)
    assert all_rows(live, "/approvals/pending", actor="viewer")[0] == []


def test_invalid_and_duplicate_filters(live):
    for params in [{"q": "x" * 101}, {"stage": "unknown"}, {"date_from": "2026-10-20T00:00:00Z", "date_to": "2026-10-19T00:00:00Z"}, [("q", "a"), ("q", "b")], {"limit": 101}]:
        read(live, "/approvals/pending", params, status=422)
    assert all_rows(live, "/approvals/pending", {"q": "   "})[0] == all_rows(live, "/approvals/pending")[0]


def test_unauthenticated_read_is_denied(live):
    response = live[1].get("/approvals/pending")
    assert response.status_code == 401

"""PREPUB-004: real session authorization, encryption and an actual FTP import.

The explicitly owned FTP daemon is a real protocol server. This case does not
qualify cleartext transport as safe or replace the human risk decision.
"""
import json
import time
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.db.models import AuditLog, DataConnection, DataSyncRun, DocumentVersion
from current_live_support import current_live  # noqa: F401
from current_ftp_api_support import ftp_api_input  # noqa: F401


def test_ftp_project_boundary_secret_redaction_and_real_worker_import(current_live, ftp_api_input):
    context = current_live.context
    service = context["ftp_api"]
    assert service["provider_owner"] == service["operation_uuid"] == ftp_api_input["operation_uuid"]
    assert service["dataset_run_uuid"] == context["run_id"]
    assert service["host"] == "localhost" and service["port"] >= 1024
    project_id = service["project_id"]
    path = f"projects/{project_id}/data-sources"
    payload = dict(service_type="FTP", name="Owned FTP boundary " + context["run_id"],
                   host=service["host"], port=service["port"], username="reader",
                   credential=service["password"], remote_path="/", file_name="source.md",
                   schedule_mode="once", timezone="Asia/Taipei")
    viewer = current_live.actor("project_viewer")
    editor = current_live.actor("project_editor")
    with current_live.database() as session:
        before = set(session.scalars(select(DataConnection.id).where(DataConnection.project_id == UUID(project_id))))
    assert viewer.post(path + "/test-connection", json=payload).status_code == 403
    assert viewer.post(path, json=payload).status_code == 403
    with current_live.database() as session:
        assert set(session.scalars(select(DataConnection.id).where(DataConnection.project_id == UUID(project_id)))) == before
    probe = editor.post(path + "/test-connection", json=payload)
    assert probe.status_code == 200 and probe.json()["status"] == "success"
    assert service["password"] not in probe.text
    created = editor.post(path, json=payload)
    assert created.status_code == 201
    result = created.json()
    assert service["password"] not in created.text
    connection_id = UUID(result["data_source"]["id"])
    run_id = UUID(result["sync_run"]["id"])
    assert result["data_source"]["credential_configured"] is True
    # The actual producer already committed; all following observations are
    # read-only. A failed/unknown outcome never resends the create operation.
    with current_live.database() as session:
        row = session.get(DataConnection, connection_id)
        assert row.service_type == "FTP" and row.credential_encrypted.startswith("v1:")
        assert service["password"] not in row.credential_encrypted
        secret = EnvelopeCipher(get_settings().encryption_key_bytes).decrypt(
            row.credential_encrypted, context=f"data-source-connection:{connection_id}")
        assert secret == service["password"]
        audit = list(session.scalars(select(AuditLog).where(AuditLog.resource_id == connection_id)))
        assert audit and service["password"] not in json.dumps([a.summary for a in audit], default=str)
    from current_ftp_api_support import publish_exact_owned_sync
    publish_exact_owned_sync(current_live, connection_id, run_id)
    deadline = time.monotonic() + 60
    while True:
        with current_live.database() as session:
            run = session.get(DataSyncRun, run_id)
            if run.status not in {"queued", "running"}:
                assert run.status == "success", run.error_code
                version = session.get(DocumentVersion, run.document_version_id)
                assert version.original_snapshot_uri.startswith("s3://")
                assert run.content_fingerprint
                break
        assert time.monotonic() < deadline, "owned_ftp_import_did_not_complete"
        time.sleep(0.5)
    history = viewer.get(path + f"/{connection_id}/sync-runs")
    assert history.status_code == 200 and service["password"] not in history.text

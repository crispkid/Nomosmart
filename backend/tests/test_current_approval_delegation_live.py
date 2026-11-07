"""Current manager delegation on genuine completed approval evidence."""
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.db.models import (ApprovalRequest, ApprovalTask, ProjectMember, ProjectOwner, ReviewRecord,
                           Role, RolePermission, RoleUser, User)
from current_live_support import CurrentLive, load_current_context


def test_current_manager_delegate_read_and_immediate_revocation():
    current = load_current_context()
    root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
    # This references an actual normal UI publication, never a seeded task.
    browser = json.loads((root / "browser-work/context.json").read_text())
    assert browser["run_id"] == current["run_id"]
    task_id = UUID(browser["approval_task_id"])
    actor_id = UUID(current["actors"]["system_editor"]["user_id"])
    role_id = uuid4()
    role_name = "chg370-delegation-read-" + uuid4().hex
    proof = {"run_uuid": current["run_id"], "phase": "READ_ONLY_PREFLIGHT", "observations": [],
             "cleanup_complete": False, "provider_calls": 0, "approval_writes": 0}
    receipt = root / ("current-delegation-read-" + uuid4().hex + ".json")
    saved_manager = None
    added_member = False
    baseline = None

    def save():
        receipt.write_text(json.dumps(proof, indent=2))
        receipt.chmod(0o600)

    fingerprint = text("""SELECT md5(jsonb_build_object(
        'request',(SELECT to_jsonb(r) FROM approval_requests r WHERE r.id=:request),
        'tasks',(SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM approval_tasks t WHERE t.approval_request_id=:request),
        'evidence',(SELECT to_jsonb(e) FROM approval_evidence_manifests e WHERE e.approval_request_id=:request))::text)""")
    with ExitStack() as stack:
        live = CurrentLive(current, stack)
        try:
            with live.database() as session:
                task = session.get(ApprovalTask, task_id)
                approval = session.get(ApprovalRequest, task.approval_request_id)
                assert task.status == "approved" and approval.status == "published"
                assert str(approval.project_id) == browser["project_id"]
                submitter = session.get(User, approval.submitter_id)
                manager = session.get(User, submitter.manager_user_id)
                assert manager and manager.is_active and manager.directory_enabled and not manager.locally_disabled
                assert actor_id not in {submitter.id, manager.id}
                assert session.get(ProjectOwner, (approval.project_id, actor_id)) is None
                assert session.scalar(select(ApprovalTask.id).where(
                    ApprovalTask.approval_request_id == approval.id,
                    (ApprovalTask.assignee_user_id == actor_id) | (ApprovalTask.original_manager_user_id == actor_id))) is None
                assert session.scalar(select(ReviewRecord.id).where(
                    ReviewRecord.document_version_id == approval.document_version_id,
                    ReviewRecord.reviewer_id == actor_id)) is None
                project_id, request_id, manager_id = approval.project_id, approval.id, manager.id
                saved_manager = (manager.manager_delegate_user_id, manager.manager_delegate_start_at,
                                 manager.manager_delegate_end_at, manager.is_active,
                                 manager.directory_enabled, manager.locally_disabled)
                baseline = session.scalar(fingerprint, {"request": request_id})
                proof.update(phase="RBAC_AND_DELEGATION_INPUT_INTENT", manager_id=str(manager_id),
                             role_id=str(role_id), actor_id=str(actor_id), request_id=str(request_id))
                save()
                session.add(Role(id=role_id, name=role_name, is_active=True, is_system=False))
                session.flush()
                session.add(RolePermission(role_id=role_id, module_name="Menu", function_name="KnowledgeProjects", can_view=True))
                session.add(RoleUser(role_id=role_id, user_id=actor_id, source="manual"))
                member = session.scalar(select(ProjectMember).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == actor_id))
                if member is None:
                    added_member = True
                    session.add(ProjectMember(project_id=project_id, user_id=actor_id, project_role="viewer", created_at=datetime.now(UTC)))
                else:
                    assert member.project_role == "viewer"
                session.commit()
            client = live.actor("system_editor")
            for scenario, expected in [("active", 200), ("expired", 403), ("future", 403),
                                       ("inactive_manager", 403), ("directory_disabled_manager", 403),
                                       ("locally_disabled_manager", 403), ("removed", 403)]:
                now = datetime.now(UTC)
                with live.database() as session:
                    manager = session.get(User, manager_id)
                    manager.manager_delegate_user_id = None if scenario == "removed" else actor_id
                    manager.manager_delegate_start_at = now + timedelta(minutes=5) if scenario == "future" else now - timedelta(minutes=5)
                    manager.manager_delegate_end_at = now - timedelta(seconds=1) if scenario == "expired" else now + timedelta(minutes=5)
                    manager.is_active = scenario != "inactive_manager"
                    manager.directory_enabled = scenario != "directory_disabled_manager"
                    manager.locally_disabled = scenario == "locally_disabled_manager"
                    session.commit()
                observations = []
                for path in ["approval-requests/" + str(request_id), "approvals/" + str(task_id)]:
                    response = client.get(path)
                    observations.append({"path": path.split("/")[0], "http": response.status_code,
                                         "code": response.json().get("code")})
                    proof["observations"].append({"scenario": scenario, **observations[-1]})
                    save()
                    assert response.status_code == expected
                    if expected == 403:
                        assert response.json()["code"] == "approval_read_denied"
                listing = client.get("approval-requests")
                assert listing.status_code == 200
                assert (str(request_id) in {row["id"] for row in listing.json()}) == (expected == 200)
        finally:
            if saved_manager is not None:
                with live.database() as session:
                    manager = session.get(User, manager_id)
                    (manager.manager_delegate_user_id, manager.manager_delegate_start_at,
                     manager.manager_delegate_end_at, manager.is_active,
                     manager.directory_enabled, manager.locally_disabled) = saved_manager
                    if added_member:
                        member = session.get(ProjectMember, (project_id, actor_id, "viewer"))
                        if member is not None:
                            session.delete(member)
                    role = session.get(Role, role_id)
                    if role is not None:
                        assert role.name == role_name and not role.is_system
                        session.delete(role)
                    session.commit()
                    assert session.scalar(fingerprint, {"request": request_id}) == baseline
                    assert session.get(Role, role_id) is None
                    assert (manager.manager_delegate_user_id, manager.manager_delegate_start_at,
                            manager.manager_delegate_end_at, manager.is_active,
                            manager.directory_enabled, manager.locally_disabled) == saved_manager
                proof.update(phase="EXACT_INPUTS_RESTORED", cleanup_complete=True, approval_fingerprint_unchanged=True)
            proof["logout"] = [client.post("auth/logout").status_code for client in live.clients.values()]
            save()
            assert all(code == 204 for code in proof["logout"])

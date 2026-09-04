from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sys
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.requests import Request


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.projects import list_project_member_candidates, remove_project_member, replace_project_member
from app.api.schemas import ProjectMemberUpdate
from app.core.errors import AppError
from app.db.models import AuditLog, Project, ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
from app.db.session import get_engine, get_session_factory
from app.security.auth import IdentityPrincipal
from app.security.context import resolve_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
            "state": {"request_id": f"chg288-{uuid4()}"},
        }
    )


def _principal(subject: str) -> IdentityPrincipal:
    return IdentityPrincipal(
        subject=subject,
        employee_id=None,
        email=None,
        display_name="CHG-288 user",
        groups=(),
        session_id=f"chg288-{uuid4()}",
        auth_time=0,
    )


def _user(label: str, *, employee_id: str, eligible_email: str | None = None) -> User:
    return User(
        employee_id=employee_id,
        keycloak_user_id=f"chg288-{label}-{uuid4()}",
        ldap_dn=f"uid={label}-ldap,ou=people,dc=nomosmart,dc=test",
        email=eligible_email or f"chg288-{label}-{uuid4()}@example.test",
        given_name=label.title(),
        family_name="Candidate",
        display_name=f"Candidate {label.title()}",
        auth_source="keycloak",
        is_active=True,
    )


@contextmanager
def _isolated_session():
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed(session: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]
    owner = _user("owner", employee_id=f"Z{suffix}001")
    other_owner = _user("otherowner", employee_id=f"Z{suffix}002")
    eligible = _user("user02", employee_id=f"Z{suffix}003", eligible_email="user02@nomosmart.test")
    ineligible = _user("user05", employee_id=f"Z{suffix}005", eligible_email="user05@nomosmart.test")
    role = Role(
        name=f"chg288-knowledge-project-user-{uuid4()}",
        description="CHG-288 isolated candidate role",
        is_active=True,
        is_system=False,
    )
    session.add_all([owner, other_owner, eligible, ineligible, role])
    session.flush()
    session.add(
        RolePermission(
            role_id=role.id,
            module_name=MENU_MODULE,
            function_name=MENU_KNOWLEDGE_PROJECTS,
            can_view=True,
            can_create=False,
            can_edit=False,
            can_delete=False,
            can_execute=False,
        )
    )
    session.add_all(
        [
            RoleUser(role_id=role.id, user_id=owner.id, source="manual"),
            RoleUser(role_id=role.id, user_id=other_owner.id, source="manual"),
            RoleUser(role_id=role.id, user_id=eligible.id, source="manual"),
        ]
    )
    project = Project(
        name=f"CHG-288 project {uuid4()}",
        description="Candidate search and protected Owner",
        status="active",
        created_by=owner.id,
        lock_version=1,
    )
    session.add(project)
    session.flush()
    session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=owner.id, project_role="owner", created_at=now),
            ProjectOwner(project_id=project.id, user_id=owner.id, created_at=now),
            ProjectMember(project_id=project.id, user_id=eligible.id, project_role="viewer", created_at=now),
        ]
    )
    session.flush()
    return {
        "project": project,
        "owner": owner,
        "other_owner": other_owner,
        "eligible": eligible,
        "ineligible": ineligible,
        "role": role,
    }


def _candidate_search(session: Session, seeded: dict[str, object], query: str):
    project = seeded["project"]
    owner = seeded["owner"]
    assert isinstance(project, Project)
    assert isinstance(owner, User)
    context = resolve_identity_context(session, _principal(owner.keycloak_user_id))
    return list_project_member_candidates(
        project_id=project.id,
        q=query,
        offset=0,
        limit=20,
        context=context,
        session=session,
    )


def test_chg288_candidate_search_supports_safe_aliases_and_reports_ineligible_matches() -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        eligible = seeded["eligible"]
        ineligible = seeded["ineligible"]
        assert isinstance(eligible, User)
        assert isinstance(ineligible, User)

        for query in (
            "user02",
            "USER02@NOMOSMART.TEST",
            eligible.employee_id,
            "Candidate User02",
            "User02 Candidate",
            "CandidateUser02",
            "user02-ldap",
        ):
            result = _candidate_search(session, seeded, query)
            assert result.total == 1
            assert [item.id for item in result.items] == [eligible.id]
            assert result.ineligible_match_count == 0
            assert result.items[0].email == "user02@nomosmart.test"
            assert not hasattr(result.items[0], "keycloak_user_id")
            assert not hasattr(result.items[0], "ldap_dn")

        for query in ("user05", "user05@nomosmart.test", ineligible.employee_id or ""):
            missing_access = _candidate_search(session, seeded, query)
            assert missing_access.items == []
            assert missing_access.total == 0
            assert missing_access.ineligible_match_count == 1

        escaped = _candidate_search(session, seeded, "%_\\")
        assert escaped.items == []
        assert escaped.ineligible_match_count == 0
        session.rollback()


def test_chg288_v048_seeds_only_the_minimal_unassigned_base_role() -> None:
    with _isolated_session() as session:
        role = session.scalar(
            select(Role).where(
                Role.name == "knowledge-project-user",
                Role.deleted_at.is_(None),
            )
        )
        assert role is not None
        assert role.is_active is True
        assert role.is_system is False
        permissions = list(session.scalars(select(RolePermission).where(RolePermission.role_id == role.id)))
        assert len(permissions) == 1
        permission = permissions[0]
        assert (permission.module_name, permission.function_name) == (MENU_MODULE, MENU_KNOWLEDGE_PROJECTS)
        assert permission.can_view is True
        assert permission.can_create is False
        assert permission.can_edit is False
        assert permission.can_delete is False
        assert permission.can_execute is False
        assert session.scalar(select(RoleUser).where(RoleUser.role_id == role.id).limit(1)) is None
        session.rollback()


def test_chg288_candidate_search_is_project_owner_only() -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        project = seeded["project"]
        eligible = seeded["eligible"]
        assert isinstance(project, Project)
        assert isinstance(eligible, User)
        viewer_context = resolve_identity_context(session, _principal(eligible.keycloak_user_id))

        with pytest.raises(AppError) as denied:
            list_project_member_candidates(
                project_id=project.id,
                q="user02",
                offset=0,
                limit=20,
                context=viewer_context,
                session=session,
            )
        assert denied.value.code == "project_owner_required"
        session.rollback()


def test_chg288_sole_and_self_owner_rows_are_transactionally_protected() -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        project = seeded["project"]
        owner = seeded["owner"]
        other_owner = seeded["other_owner"]
        assert isinstance(project, Project)
        assert isinstance(owner, User)
        assert isinstance(other_owner, User)
        owner_context = resolve_identity_context(session, _principal(owner.keycloak_user_id))

        with pytest.raises(AppError) as sole_update:
            replace_project_member(
                project_id=project.id,
                user_id=owner.id,
                payload=ProjectMemberUpdate(roles=["editor"], lock_version=project.lock_version),
                request=_request("PUT", f"/api/v1/projects/{project.id}/members/{owner.id}"),
                context=owner_context,
                session=session,
            )
        assert sole_update.value.code == "last_project_owner"

        with pytest.raises(AppError) as sole_delete:
            remove_project_member(
                project_id=project.id,
                user_id=owner.id,
                request=_request("DELETE", f"/api/v1/projects/{project.id}/members/{owner.id}"),
                lock_version=project.lock_version,
                context=owner_context,
                session=session,
            )
        assert sole_delete.value.code == "last_project_owner"

        now = datetime.now(UTC)
        session.add_all(
            [
                ProjectMember(project_id=project.id, user_id=other_owner.id, project_role="owner", created_at=now),
                ProjectOwner(project_id=project.id, user_id=other_owner.id, created_at=now),
            ]
        )
        session.flush()

        with pytest.raises(AppError) as self_update:
            replace_project_member(
                project_id=project.id,
                user_id=owner.id,
                payload=ProjectMemberUpdate(roles=["editor"], lock_version=project.lock_version),
                request=_request("PUT", f"/api/v1/projects/{project.id}/members/{owner.id}"),
                context=owner_context,
                session=session,
            )
        assert self_update.value.code == "project_owner_self_protected"

        persisted = set(
            session.scalars(
                select(ProjectMember.project_role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == owner.id,
                )
            )
        )
        assert persisted == {"owner"}
        session.rollback()


def test_chg288_owner_can_change_another_owner_when_more_than_one_exists() -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        project = seeded["project"]
        owner = seeded["owner"]
        other_owner = seeded["other_owner"]
        assert isinstance(project, Project)
        assert isinstance(owner, User)
        assert isinstance(other_owner, User)
        now = datetime.now(UTC)
        session.add_all(
            [
                ProjectMember(project_id=project.id, user_id=other_owner.id, project_role="owner", created_at=now),
                ProjectOwner(project_id=project.id, user_id=other_owner.id, created_at=now),
            ]
        )
        session.flush()
        owner_context = resolve_identity_context(session, _principal(owner.keycloak_user_id))

        members = replace_project_member(
            project_id=project.id,
            user_id=other_owner.id,
            payload=ProjectMemberUpdate(roles=["editor"], lock_version=project.lock_version),
            request=_request("PUT", f"/api/v1/projects/{project.id}/members/{other_owner.id}"),
            context=owner_context,
            session=session,
        )
        updated = next(item for item in members if item.user_id == other_owner.id)
        assert updated.roles == ["editor"]
        assert session.get(ProjectOwner, (project.id, other_owner.id)) is None
        audit = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "project.member.replace",
                AuditLog.resource_id == project.id,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.summary["before_role"] == "owner"
        assert audit.summary["after_role"] == "editor"
        assert audit.summary["roles"] == ["editor"]


def test_chg291_role_replacement_is_atomic_and_keeps_owner_parity() -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        project = seeded["project"]
        owner = seeded["owner"]
        eligible = seeded["eligible"]
        assert isinstance(project, Project)
        assert isinstance(owner, User)
        assert isinstance(eligible, User)
        owner_context = resolve_identity_context(session, _principal(owner.keycloak_user_id))
        original_lock_version = project.lock_version

        members = replace_project_member(
            project_id=project.id,
            user_id=eligible.id,
            payload=ProjectMemberUpdate(roles=["editor"], lock_version=project.lock_version),
            request=_request("PUT", f"/api/v1/projects/{project.id}/members/{eligible.id}"),
            context=owner_context,
            session=session,
        )
        assert next(row for row in members if row.user_id == eligible.id).roles == ["editor"]
        assert project.lock_version == original_lock_version + 1
        assert set(
            session.scalars(
                select(ProjectMember.project_role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == eligible.id,
                )
            )
        ) == {"editor"}
        assert session.get(ProjectOwner, (project.id, eligible.id)) is None

        with pytest.raises(AppError) as stale:
            replace_project_member(
                project_id=project.id,
                user_id=eligible.id,
                payload=ProjectMemberUpdate(roles=["viewer"], lock_version=original_lock_version),
                request=_request("PUT", f"/api/v1/projects/{project.id}/members/{eligible.id}"),
                context=owner_context,
                session=session,
            )
        assert stale.value.code == "stale_project_version"

        replace_project_member(
            project_id=project.id,
            user_id=eligible.id,
            payload=ProjectMemberUpdate(roles=["owner"], lock_version=project.lock_version),
            request=_request("PUT", f"/api/v1/projects/{project.id}/members/{eligible.id}"),
            context=owner_context,
            session=session,
        )
        assert session.get(ProjectOwner, (project.id, eligible.id)) is not None

        members = replace_project_member(
            project_id=project.id,
            user_id=eligible.id,
            payload=ProjectMemberUpdate(roles=["viewer"], lock_version=project.lock_version),
            request=_request("PUT", f"/api/v1/projects/{project.id}/members/{eligible.id}"),
            context=owner_context,
            session=session,
        )
        assert next(row for row in members if row.user_id == eligible.id).roles == ["viewer"]
        assert session.get(ProjectOwner, (project.id, eligible.id)) is None
        audit = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "project.member.replace",
                AuditLog.resource_id == project.id,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.summary["before_role"] == "owner"
        assert audit.summary["after_role"] == "viewer"


def test_chg291_concurrent_same_version_replacements_have_one_winner() -> None:
    factory = get_session_factory()
    with factory() as session:
        seeded = _seed(session)
        project = seeded["project"]
        owner = seeded["owner"]
        eligible = seeded["eligible"]
        role = seeded["role"]
        assert isinstance(project, Project)
        assert isinstance(owner, User)
        assert isinstance(eligible, User)
        assert isinstance(role, Role)
        project_id = project.id
        owner_subject = owner.keycloak_user_id
        target_user_id = eligible.id
        role_id = role.id
        user_ids = [value.id for value in (owner, seeded["other_owner"], eligible, seeded["ineligible"]) if isinstance(value, User)]
        lock_version = project.lock_version
        session.commit()

    barrier = Barrier(2)

    def replace(role_name: str) -> tuple[str, str]:
        with factory() as session:
            context = resolve_identity_context(session, _principal(owner_subject))
            barrier.wait(timeout=5)
            try:
                members = replace_project_member(
                    project_id=project_id,
                    user_id=target_user_id,
                    payload=ProjectMemberUpdate(roles=[role_name], lock_version=lock_version),
                    request=_request("PUT", f"/api/v1/projects/{project_id}/members/{target_user_id}"),
                    context=context,
                    session=session,
                )
            except AppError as error:
                session.rollback()
                return "error", error.code
            persisted = next(row for row in members if row.user_id == target_user_id)
            return "success", persisted.roles[0]

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(replace, ("editor", "owner")))

        assert sorted(status for status, _ in results) == ["error", "success"]
        assert [value for status, value in results if status == "error"] == ["stale_project_version"]
        with factory() as session:
            final_roles = list(
                session.scalars(
                    select(ProjectMember.project_role).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.user_id == target_user_id,
                    )
                )
            )
            assert len(final_roles) == 1
            assert final_roles[0] in {"editor", "owner"}
            assert session.get(Project, project_id).lock_version == lock_version + 1
            assert (session.get(ProjectOwner, (project_id, target_user_id)) is not None) is (final_roles[0] == "owner")
    finally:
        with factory() as session:
            session.execute(delete(AuditLog).where(AuditLog.resource_id == project_id))
            session.execute(delete(Project).where(Project.id == project_id))
            session.execute(delete(Role).where(Role.id == role_id))
            session.execute(delete(User).where(User.id.in_(user_ids)))
            session.commit()


@pytest.mark.parametrize("roles", ([], ["viewer", "viewer"], ["editor", "viewer"]))
def test_chg291_invalid_role_cardinality_does_not_mutate_member(roles: list[str]) -> None:
    with _isolated_session() as session:
        seeded = _seed(session)
        project = seeded["project"]
        owner = seeded["owner"]
        eligible = seeded["eligible"]
        assert isinstance(project, Project)
        assert isinstance(owner, User)
        assert isinstance(eligible, User)
        owner_context = resolve_identity_context(session, _principal(owner.keycloak_user_id))
        original_lock_version = project.lock_version

        with pytest.raises(AppError) as rejected:
            replace_project_member(
                project_id=project.id,
                user_id=eligible.id,
                payload=ProjectMemberUpdate(roles=roles, lock_version=project.lock_version),
                request=_request("PUT", f"/api/v1/projects/{project.id}/members/{eligible.id}"),
                context=owner_context,
                session=session,
            )

        assert rejected.value.code == "invalid_project_role_cardinality"
        assert project.lock_version == original_lock_version
        assert set(
            session.scalars(
                select(ProjectMember.project_role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == eligible.id,
                )
            )
        ) == {"viewer"}
        assert session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "project.member.replace",
                AuditLog.resource_id == project.id,
            )
        ) is None

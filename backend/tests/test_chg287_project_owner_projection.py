from __future__ import annotations

from datetime import UTC, datetime
import inspect
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import select
from starlette.requests import Request


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.projects import archive_project, create_project, get_project, list_projects, remove_project_member, replace_project_member, retry_archive_cleanup, update_project
from app.api.schemas import ProjectMemberUpdate, ProjectResponse
from app.core.errors import AppError
from app.db.models import Project, ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
from app.db.session import get_session_factory
from app.domain.project_access import project_capabilities
from app.security.auth import IdentityPrincipal
from app.security.context import resolve_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE


def _principal(subject: str) -> IdentityPrincipal:
    return IdentityPrincipal(
        subject=subject,
        employee_id=None,
        email=None,
        display_name="CHG-287 live user",
        groups=(),
        session_id=f"chg287-{uuid4()}",
        auth_time=0,
    )


def _request(*, method: str = "GET", path: str = "/api/v1/projects", query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": [],
        }
    )


def _user(subject: str, label: str) -> User:
    return User(
        employee_id=f"Z{uuid4().hex[:9]}",
        keycloak_user_id=subject,
        email=f"chg287-{label}-{uuid4()}@example.test",
        display_name=f"CHG-287 {label}",
        auth_source="keycloak",
        is_active=True,
    )


@pytest.mark.parametrize(
    "handler",
    (
        list_projects,
        create_project,
        get_project,
        update_project,
        archive_project,
        retry_archive_cleanup,
        remove_project_member,
    ),
)
def test_chg287_project_response_routes_use_the_shared_projection(handler) -> None:
    assert "_project_response_projection" in inspect.getsource(handler)


def test_chg287_live_owner_projection_is_consistent_across_list_and_detail() -> None:
    factory = get_session_factory()
    now = datetime.now(UTC)
    owner_subject = f"chg287-owner-{uuid4()}"
    viewer_subject = f"chg287-viewer-{uuid4()}"

    with factory() as session:
        owner = _user(owner_subject, "owner")
        viewer = _user(viewer_subject, "viewer")
        role = Role(
            name=f"chg287-role-{uuid4()}",
            description="CHG-287 live response projection",
            is_active=True,
            is_system=False,
        )
        session.add_all([owner, viewer, role])
        session.flush()
        session.add_all(
            [
                RolePermission(
                    role_id=role.id,
                    module_name=MENU_MODULE,
                    function_name=MENU_KNOWLEDGE_PROJECTS,
                    can_view=True,
                ),
                RoleUser(role_id=role.id, user_id=owner.id, source="manual"),
                RoleUser(role_id=role.id, user_id=viewer.id, source="manual"),
            ]
        )
        project = Project(
            name=f"CHG-287 projection {uuid4()}",
            description="Owner projection regression",
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
                ProjectMember(project_id=project.id, user_id=viewer.id, project_role="viewer", created_at=now),
            ]
        )
        session.flush()

        owner_context = resolve_identity_context(session, _principal(owner_subject))
        detail = ProjectResponse.model_validate(get_project(project.id, owner_context, session))
        listed = list_projects(
            request=_request(query="status=active&sort=updated_desc&offset=0&limit=50"),
            response=Response(),
            status="active",
            q=None,
            role=None,
            model_state=None,
            sort="updated_desc",
            offset=0,
            limit=50,
            context=owner_context,
            session=session,
        )
        listed_project = ProjectResponse.model_validate(next(item for item in listed if item.id == project.id))

        assert detail.is_owner is True
        assert detail.current_user_project_roles == ["owner"]
        assert detail.capabilities == listed_project.capabilities
        assert detail.is_owner == listed_project.is_owner
        assert detail.current_user_project_roles == listed_project.current_user_project_roles
        assert detail.capabilities == project_capabilities(
            session,
            project,
            user_id=owner.id,
            visible_project_ids={project.id},
        )

        project.status = "archived"
        assert not any(
            project_capabilities(
                session,
                project,
                user_id=owner.id,
                visible_project_ids={project.id},
            ).values()
        )
        project.status = "active"

        viewer_context = resolve_identity_context(session, _principal(viewer_subject))
        viewer_detail = ProjectResponse.model_validate(get_project(project.id, viewer_context, session))
        assert viewer_detail.is_owner is False
        assert viewer_detail.current_user_project_roles == ["viewer"]
        assert viewer_detail.capabilities["can_manage_lifecycle"] is False

        with pytest.raises(AppError) as denied:
            replace_project_member(
                project_id=project.id,
                user_id=viewer.id,
                payload=ProjectMemberUpdate(roles=["editor"], lock_version=project.lock_version),
                request=_request(method="PUT", path=f"/api/v1/projects/{project.id}/members/{viewer.id}"),
                context=viewer_context,
                session=session,
            )
        assert denied.value.code == "project_owner_required"

        persisted_roles = set(
            session.scalars(
                select(ProjectMember.project_role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == viewer.id,
                )
            )
        )
        assert persisted_roles == {"viewer"}
        session.rollback()

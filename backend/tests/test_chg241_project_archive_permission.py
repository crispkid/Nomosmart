from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import select, text
from starlette.requests import Request

from app.api.routes.projects import _require_project_archive_authority, list_projects
from app.api.routes.roles import _validate_managed_permissions
from app.api.schemas import PermissionValue
from app.core.errors import AppError
from app.db.models import AIModel, Document, DocumentVersion, Project, ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
from app.db.session import get_session_factory
from app.security.auth import IdentityPrincipal
from app.security.context import resolve_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, PROJECT_ARCHIVE, PROJECT_MODULE, PermissionAction, PermissionGrant, has_permission


ROOT = Path(__file__).resolve().parents[2]


def _request(query: str = "") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/v1/projects", "query_string": query.encode(), "headers": []})


def _principal(subject: str) -> IdentityPrincipal:
    return IdentityPrincipal(
        subject=subject,
        employee_id=None,
        email=None,
        display_name="CHG-241 live user",
        groups=(),
        session_id=f"chg241-{uuid4()}",
        auth_time=0,
    )


def test_chg241_migration_and_permission_contract() -> None:
    migration = (ROOT / "sql/migrations/V032__project_archive_execute_permission.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN can_execute boolean NOT NULL DEFAULT false" in migration
    assert "'Project', 'ProjectArchive', false, false, false, false, true" in migration
    assert "ix_project_members_user_role_project" in migration
    assert "can_execute" in RolePermission.__table__.columns

    grant = PermissionGrant(module_name=PROJECT_MODULE, function_name=PROJECT_ARCHIVE, can_execute=True)
    assert has_permission(
        [grant],
        PROJECT_MODULE,
        PROJECT_ARCHIVE,
        PermissionAction.EXECUTE,
    ) is True


def test_chg241_permission_allowlist_rejects_unsupported_actions() -> None:
    _validate_managed_permissions(
        [PermissionValue(module_name=PROJECT_MODULE, function_name=PROJECT_ARCHIVE, can_execute=True)]
    )
    with pytest.raises(AppError) as menu_execute:
        _validate_managed_permissions(
            [PermissionValue(module_name=MENU_MODULE, function_name=MENU_KNOWLEDGE_PROJECTS, can_execute=True)]
        )
    assert menu_execute.value.code == "unsupported_permission_action"
    with pytest.raises(AppError) as archive_delete:
        _validate_managed_permissions(
            [PermissionValue(module_name=PROJECT_MODULE, function_name=PROJECT_ARCHIVE, can_delete=True)]
        )
    assert archive_delete.value.code == "unsupported_permission_action"


def test_chg241_live_project_discovery_and_archive_execute_revocation() -> None:
    factory = get_session_factory()
    now = datetime.now(UTC)
    subject = f"chg241-{uuid4()}"
    with factory() as session:
        assert session.scalar(text("select version from flyway_schema_history where success = true order by installed_rank desc limit 1")) == "032"
        actor = User(
            employee_id=f"Z{uuid4().hex[:9]}",
            keycloak_user_id=subject,
            email=f"chg241-{uuid4()}@example.test",
            display_name="CHG-241 project member",
            auth_source="keycloak",
            is_active=True,
        )
        role = Role(name=f"chg241-role-{uuid4()}", description="Project archive execution", is_active=True, is_system=False)
        models = [
            AIModel(name=f"chg241-{kind.lower()}-{uuid4()}", model_type=kind, provider="custom", is_active=True, is_default=False, config={})
            for kind in ("Chat", "Embedding", "OCR")
        ]
        session.add_all([actor, role, *models])
        session.flush()
        session.add_all(
            [
                RolePermission(role_id=role.id, module_name=MENU_MODULE, function_name=MENU_KNOWLEDGE_PROJECTS, can_view=True),
                RolePermission(role_id=role.id, module_name=PROJECT_MODULE, function_name=PROJECT_ARCHIVE, can_execute=True),
                RoleUser(role_id=role.id, user_id=actor.id, source="manual"),
            ]
        )
        complete = Project(
            name=f"Alpha% Governance {uuid4()}",
            description="Searchable compliance project",
            status="active",
            llm_model_id=models[0].id,
            embedding_model_id=models[1].id,
            ocr_model_id=models[2].id,
            created_by=actor.id,
            lock_version=1,
        )
        incomplete = Project(name=f"Beta {uuid4()}", description="No model configuration", status="active", created_by=actor.id, lock_version=1)
        session.add_all([complete, incomplete])
        session.flush()
        session.add_all(
            [
                ProjectMember(project_id=complete.id, user_id=actor.id, project_role="editor", created_at=now),
                ProjectMember(project_id=complete.id, user_id=actor.id, project_role="viewer", created_at=now),
                ProjectMember(project_id=incomplete.id, user_id=actor.id, project_role="viewer", created_at=now),
            ]
        )
        document = Document(
            project_id=complete.id,
            document_code=f"CHG241-{uuid4().hex[:8]}",
            title="Published evidence",
            source_type="file_upload",
            status="active",
            is_deleted=False,
            created_by=actor.id,
        )
        session.add(document)
        session.flush()
        session.add(
            DocumentVersion(
                project_id=complete.id,
                document_id=document.id,
                version_major=1,
                extraction_revision=1,
                version_label="v1.0",
                status="active",
                published_at=now,
                published_by=actor.id,
                chunk_strategy={},
                lock_version=1,
            )
        )
        session.flush()

        context = resolve_identity_context(session, _principal(subject))
        response = Response()
        projects = list_projects(
            request=_request("status=active&q=Alpha%25&role=editor&model_state=complete&sort=updated_desc&offset=0&limit=12"),
            response=response,
            status="active",
            q="Alpha%",
            role=["editor"],
            model_state="complete",
            sort="updated_desc",
            offset=0,
            limit=12,
            context=context,
            session=session,
        )
        assert response.headers["X-Total-Count"] == "1"
        assert [project.id for project in projects] == [complete.id]
        assert projects[0].current_user_project_roles == ["editor", "viewer"]
        assert projects[0].document_count == 1
        assert projects[0].published_version_count == 1
        assert projects[0].last_activity_at is not None

        authorized_project, is_owner = _require_project_archive_authority(session, complete.id, context)
        assert authorized_project.id == complete.id
        assert is_owner is False

        execute_grant = session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.module_name == PROJECT_MODULE,
                RolePermission.function_name == PROJECT_ARCHIVE,
            )
        )
        assert execute_grant is not None
        session.delete(execute_grant)
        session.flush()
        revoked_context = resolve_identity_context(session, _principal(subject))
        with pytest.raises(AppError) as revoked:
            _require_project_archive_authority(session, complete.id, revoked_context)
        assert revoked.value.code == "project_archive_permission_required"

        session.add(ProjectOwner(project_id=complete.id, user_id=actor.id, created_at=now))
        session.flush()
        owner_project, is_owner = _require_project_archive_authority(session, complete.id, revoked_context)
        assert owner_project.id == complete.id
        assert is_owner is True

        owner_response = Response()
        owner_projects = list_projects(
            request=_request("status=active&role=owner&sort=name_asc&offset=0&limit=12"),
            response=owner_response,
            status="active",
            q=None,
            role=["owner"],
            model_state=None,
            sort="name_asc",
            offset=0,
            limit=12,
            context=revoked_context,
            session=session,
        )
        assert [project.id for project in owner_projects] == [complete.id]
        assert owner_projects[0].current_user_project_roles == ["editor", "owner", "viewer"]

        with pytest.raises(AppError) as repeated:
            list_projects(
                request=_request("status=active&status=archived"),
                response=Response(),
                status="archived",
                q=None,
                role=None,
                model_state=None,
                sort="updated_desc",
                offset=0,
                limit=12,
                context=revoked_context,
                session=session,
            )
        assert repeated.value.code == "repeated_project_query_parameter"
        session.rollback()

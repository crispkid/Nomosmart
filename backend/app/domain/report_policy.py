from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ApprovalTask, ProjectMember, ProjectOwner
from app.security.context import IdentityContext
from app.security.permissions import (
    MENU_REPORTS,
    MENU_SYSTEM_MANAGEMENT,
    REPORT_MODEL_REPORT,
    REPORT_MODULE,
    PermissionAction,
    has_menu_permission,
    has_permission,
    require_menu_permission,
)


@dataclass(frozen=True)
class ReportPolicyDecision:
    scope: str
    project_ids: set[UUID] | None
    can_view_model_detail: bool


class ReportScopePolicy:
    def __init__(self, session: Session, context: IdentityContext) -> None:
        require_menu_permission(list(context.grants), MENU_REPORTS, PermissionAction.VIEW)
        self.session = session
        self.context = context
        owner_ids = set(
            session.scalars(select(ProjectOwner.project_id).where(ProjectOwner.user_id == context.user_id))
        )
        owner_ids.update(
            session.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == context.user_id,
                    func.lower(ProjectMember.project_role) == "owner",
                )
            )
        )
        reviewer_ids = set(
            session.scalars(
                select(ApprovalTask.project_id).where(ApprovalTask.assignee_user_id == context.user_id)
            )
        )
        scopes: dict[str, set[UUID] | None] = {
            "owner_projects": owner_ids,
            "accessible": set(context.visible_project_ids),
            "reviewer": reviewer_ids,
        }
        if has_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW):
            scopes["system"] = None
        self.scopes = scopes
        self.can_view_model_detail = has_permission(
            list(context.grants),
            REPORT_MODULE,
            REPORT_MODEL_REPORT,
            PermissionAction.VIEW,
        )

    def decide(self, *, scope: str | None, project_id: UUID | None, topic: str | None = None) -> ReportPolicyDecision:
        resolved = scope.strip().lower() if scope is not None else ("system" if "system" in self.scopes else "accessible")
        if resolved not in self.scopes:
            raise AppError("report_scope_denied", "The requested report scope is not available", status_code=403)
        project_ids = self.scopes[resolved]
        if project_id is not None:
            if project_ids is not None and project_id not in project_ids:
                raise AppError("project_scope_denied", "Report project is outside the user's visible scope", status_code=403)
            project_ids = {project_id}
        if topic == "model_usage_metrics" and not self.can_view_model_detail:
            raise AppError(
                "report_model_permission_required",
                "Report.ModelReport permission is required for model invocation and cost detail",
                status_code=403,
            )
        return ReportPolicyDecision(
            scope=resolved,
            project_ids=project_ids,
            can_view_model_detail=self.can_view_model_detail,
        )

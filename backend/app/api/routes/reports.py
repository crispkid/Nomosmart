from __future__ import annotations

import asyncio
import csv
import io
import math
from dataclasses import dataclass
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ReportFilterOptionsResponse,
    ReportMetricCard,
    ReportProjectOption,
    ReportProjectRankingItem,
    ReportScopeOption,
    ReportSummaryResponse,
)
from app.core.errors import AppError
from app.core.config import get_settings
from app.db.models import (
    AIModel,
    AIModelUsageEvent,
    ApprovalRequest,
    ApprovalTask,
    ChatRecord,
    Document,
    DocumentReference,
    DocumentReferenceEvent,
    DocumentVersion,
    Notification,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectMember,
    ProjectOwner,
    ValidationRun,
    ValidationRunItem,
)
from app.db.session import get_db
from app.domain.report_policy import ReportScopePolicy
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_REPORTS, MENU_SYSTEM_MANAGEMENT, PermissionAction, has_menu_permission, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_PAGE_SIZE = 20
REPORT_SCOPES = {"owner_projects", "accessible", "reviewer", "system"}

REPORT_TOPICS = {
    "system_overview",
    "project_ranking",
    "project_reference_ranking",
    "document_reference_ranking",
    "owner_project_summary",
    "document_pipeline_metrics",
    "rag_quality_metrics",
    "validation_run_metrics",
    "model_usage_metrics",
    "alert_metrics",
}

TOPIC_COLUMNS: dict[str, list[str]] = {
    "system_overview": ["metric_key", "metric_value", "date_from", "date_to"],
    "project_ranking": ["rank", "project_id", "project_name", "document_count", "active_documents", "pipeline_runs", "qa_count", "validation_runs", "active_users_30d", "success_rate", "failure_rate"],
    "project_reference_ranking": ["rank", "source_project_id", "source_project", "reference_count", "target_project_count", "referenced_document_count", "new_references_30d", "pending_source_events", "quality_score"],
    "document_reference_ranking": ["rank", "source_document_id", "document_name", "source_project_id", "source_project", "reference_count", "target_project_count", "active_version", "last_source_update", "pending_sync_count", "qa_hit_count", "human_correct_rate"],
    "owner_project_summary": ["project_id", "project_name", "active_documents", "pending_manager_review", "pending_owner_review", "approved_unpublished", "inbound_references", "outbound_references", "no_answer_rate", "validation_pass_rate", "open_alerts"],
    "document_pipeline_metrics": ["project_id", "project_name", "pipeline_runs", "completed_runs", "failed_runs", "retry_count", "avg_pipeline_seconds", "p95_pipeline_seconds"],
    "rag_quality_metrics": ["project_id", "project_name", "qa_count", "no_answer_rate", "cited_answer_rate", "human_correct_rate", "needs_revision_rate"],
    "validation_run_metrics": ["project_id", "project_name", "validation_runs", "completed_runs", "failed_runs", "pass_rate", "failed_questions", "manual_review_count"],
    "model_usage_metrics": ["model_type", "ai_model_name", "provider", "project_name", "usage_purpose", "source_channel", "call_count", "success_count", "failure_count", "input_tokens", "output_tokens", "total_tokens", "embedding_tokens", "ocr_pages", "ocr_images", "vector_count", "chunk_count", "avg_latency_ms", "p95_latency_ms", "provider_reported_cost", "estimated_cost", "currency", "cost_source", "error_rate"],
    "alert_metrics": ["level", "alert_type", "project_id", "project_name", "count", "oldest_at"],
}

HEADER_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "zh": {
        "metric_key": "指標代碼",
        "metric_value": "指標值",
        "date_from": "起日",
        "date_to": "迄日",
        "rank": "排名",
        "project_id": "專案 ID",
        "project_name": "專案名稱",
        "document_count": "文件數",
        "active_documents": "活躍文件",
        "pipeline_runs": "Pipeline 次數",
        "qa_count": "問答次數",
        "validation_runs": "驗證批次數",
        "active_users_30d": "30 天活躍使用者",
        "success_rate": "成功率",
        "failure_rate": "失敗率",
        "source_project_id": "來源專案 ID",
        "source_project": "來源專案",
        "reference_count": "被引用次數",
        "target_project_count": "引用專案數",
        "referenced_document_count": "被引用文件數",
        "new_references_30d": "30 天新增引用",
        "pending_source_events": "待處理來源異動",
        "quality_score": "品質分數",
        "source_document_id": "來源文件 ID",
        "document_name": "文件名稱",
        "active_version": "Active version",
        "last_source_update": "最近來源更新時間",
        "pending_sync_count": "待同步數",
        "qa_hit_count": "問答命中數",
        "human_correct_rate": "人工正確率",
        "pending_manager_review": "待主管審核",
        "pending_owner_review": "待 Owner 審核",
        "approved_unpublished": "已核准未發布",
        "inbound_references": "被引用數",
        "outbound_references": "引用外部數",
        "no_answer_rate": "無答案率",
        "validation_pass_rate": "驗證通過率",
        "open_alerts": "未處理告警",
        "completed_runs": "完成次數",
        "failed_runs": "失敗次數",
        "retry_count": "重試次數",
        "avg_pipeline_seconds": "平均 Pipeline 秒數",
        "p95_pipeline_seconds": "P95 Pipeline 秒數",
        "cited_answer_rate": "有引用率",
        "needs_revision_rate": "需修正率",
        "pass_rate": "通過率",
        "failed_questions": "失敗題數",
        "manual_review_count": "待人工檢視",
        "provider": "Provider",
        "ai_model_name": "模型名稱",
        "model_name": "模型名稱",
        "model_type": "模型類型",
        "token_count": "Token 數",
        "call_count": "呼叫次數",
        "success_count": "成功次數",
        "failure_count": "失敗次數",
        "input_tokens": "Input Token",
        "output_tokens": "Output Token",
        "total_tokens": "總 Token",
        "embedding_tokens": "Embedding Token",
        "ocr_pages": "OCR 頁數",
        "ocr_images": "OCR 影像數",
        "vector_count": "向量數",
        "chunk_count": "切片數",
        "usage_purpose": "用途",
        "source_channel": "來源管道",
        "provider_reported_cost": "官方成本",
        "estimated_cost": "估算成本",
        "currency": "幣別",
        "cost_source": "成本來源",
        "p95_latency_ms": "P95 latency ms",
        "error_rate": "錯誤率",
        "avg_latency_ms": "平均 latency ms",
        "level": "等級",
        "alert_type": "告警類型",
        "count": "數量",
        "oldest_at": "最早時間",
    },
    "en": {
        "metric_key": "Metric Key",
        "metric_value": "Metric Value",
        "date_from": "Date From",
        "date_to": "Date To",
        "rank": "Rank",
        "project_id": "Project ID",
        "project_name": "Project Name",
        "document_count": "Documents",
        "active_documents": "Active Documents",
        "pipeline_runs": "Pipeline Runs",
        "qa_count": "Chat Queries",
        "validation_runs": "Validation Runs",
        "active_users_30d": "Active Users 30d",
        "success_rate": "Success Rate",
        "failure_rate": "Failure Rate",
        "source_project_id": "Source Project ID",
        "source_project": "Source Project",
        "reference_count": "Reference Count",
        "target_project_count": "Target Projects",
        "referenced_document_count": "Referenced Documents",
        "new_references_30d": "New References 30d",
        "pending_source_events": "Pending Source Events",
        "quality_score": "Quality Score",
        "source_document_id": "Source Document ID",
        "document_name": "Document Name",
        "active_version": "Active Version",
        "last_source_update": "Last Source Update",
        "pending_sync_count": "Pending Sync Count",
        "qa_hit_count": "Q&A Hits",
        "human_correct_rate": "Human Correct Rate",
        "pending_manager_review": "Pending Manager Review",
        "pending_owner_review": "Pending Owner Review",
        "approved_unpublished": "Approved Unpublished",
        "inbound_references": "Inbound References",
        "outbound_references": "Outbound References",
        "no_answer_rate": "No-answer Rate",
        "validation_pass_rate": "Validation Pass Rate",
        "open_alerts": "Open Alerts",
        "completed_runs": "Completed Runs",
        "failed_runs": "Failed Runs",
        "retry_count": "Retry Count",
        "avg_pipeline_seconds": "Average Pipeline Seconds",
        "p95_pipeline_seconds": "P95 Pipeline Seconds",
        "cited_answer_rate": "Cited Answer Rate",
        "needs_revision_rate": "Needs Revision Rate",
        "pass_rate": "Pass Rate",
        "failed_questions": "Failed Questions",
        "manual_review_count": "Manual Review Count",
        "provider": "Provider",
        "ai_model_name": "Model Name",
        "model_name": "Model Name",
        "model_type": "Model Type",
        "token_count": "Token Count",
        "call_count": "Call Count",
        "success_count": "Success Count",
        "failure_count": "Failure Count",
        "input_tokens": "Input Tokens",
        "output_tokens": "Output Tokens",
        "total_tokens": "Total Tokens",
        "embedding_tokens": "Embedding Tokens",
        "ocr_pages": "OCR Pages",
        "ocr_images": "OCR Images",
        "vector_count": "Vector Count",
        "chunk_count": "Chunk Count",
        "usage_purpose": "Usage Purpose",
        "source_channel": "Source Channel",
        "provider_reported_cost": "Provider-reported Cost",
        "estimated_cost": "Estimated Cost",
        "currency": "Currency",
        "cost_source": "Cost Source",
        "p95_latency_ms": "P95 Latency ms",
        "error_rate": "Error Rate",
        "avg_latency_ms": "Average Latency ms",
        "level": "Level",
        "alert_type": "Alert Type",
        "count": "Count",
        "oldest_at": "Oldest At",
    },
}


@router.get("/filter-options", response_model=ReportFilterOptionsResponse)
def get_report_filter_options(
    scope: str = Query(default="owner_projects", max_length=32),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ReportFilterOptionsResponse:
    policy = ReportScopePolicy(session, context)
    scope = _validated_scope(scope)
    decision = policy.decide(scope=scope, project_id=None)
    scope_sets = policy.scopes
    selected_ids = decision.project_ids
    projects = _projects(session, selected_ids)
    return ReportFilterOptionsResponse(
        selected_scope=scope,
        scopes=[
            ReportScopeOption(value=value, project_count=_scope_project_count(session, project_ids))
            for value, project_ids in scope_sets.items()
        ],
        projects=[ReportProjectOption(id=project.id, name=project.name) for project in projects],
    )


@router.get("/summary", response_model=ReportSummaryResponse)
def get_report_summary(
    topic: str = Query(default="system_overview", max_length=80),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    project_id: UUID | None = None,
    scope: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=REPORT_PAGE_SIZE, ge=REPORT_PAGE_SIZE, le=REPORT_PAGE_SIZE),
    limit: int | None = Query(default=None, ge=1, le=500, deprecated=True),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
    model_type: str | None = Query(default=None, max_length=32),
    usage_purpose: str | None = Query(default=None, max_length=64),
    source_channel: str | None = Query(default=None, max_length=64),
    usage_status: str | None = Query(default=None, max_length=32),
) -> ReportSummaryResponse:
    policy = ReportScopePolicy(session, context)
    topic = _validated_topic(topic)
    decision = policy.decide(scope=scope, project_id=project_id, topic=topic)
    scope = decision.scope
    _validate_date_range(date_from, date_to)
    scoped_project_ids = decision.project_ids
    metrics = _summary_metrics(session, scoped_project_ids, date_from, date_to)
    rows, total_rows = _topic_page(
        session,
        topic=topic,
        project_ids=scoped_project_ids,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
        model_filters=ReportModelFilters(
            model_type=model_type,
            usage_purpose=usage_purpose,
            source_channel=source_channel,
            usage_status=usage_status,
        ),
    )
    total_pages = math.ceil(total_rows / page_size) if total_rows else 0
    if page > 1 and (total_pages == 0 or page > total_pages):
        raise AppError(
            "report_page_out_of_range",
            "Requested report page is outside the available result set",
            status_code=422,
            details={"page": page, "total_pages": total_pages},
        )
    return ReportSummaryResponse(
        topic=topic,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        scope=scope,
        page=page,
        page_size=page_size,
        total_rows=total_rows,
        total_pages=total_pages,
        metrics=metrics,
        project_rankings=_project_rankings(session, scoped_project_ids, date_from, date_to, 100),
        columns=TOPIC_COLUMNS[topic],
        rows=rows,
        status="live" if rows else "empty",
        partial_reasons=[],
    )


@router.get("/export.csv", response_model=None)
def export_report_csv(
    request: Request,
    topic: str = Query(default="system_overview", max_length=80),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    project_id: UUID | None = None,
    scope: str | None = Query(default=None, max_length=32),
    locale: str = Query(default="zh-TW", max_length=16),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
    model_type: str | None = Query(default=None, max_length=32),
    usage_purpose: str | None = Query(default=None, max_length=64),
    source_channel: str | None = Query(default=None, max_length=64),
    usage_status: str | None = Query(default=None, max_length=32),
) -> StreamingResponse:
    policy = ReportScopePolicy(session, context)
    topic = _validated_topic(topic)
    decision = policy.decide(scope=scope, project_id=project_id, topic=topic)
    scope = decision.scope
    _validate_date_range(date_from, date_to)
    scoped_project_ids = decision.project_ids
    settings = get_settings()
    model_filters = ReportModelFilters(
        model_type=model_type,
        usage_purpose=usage_purpose,
        source_channel=source_channel,
        usage_status=usage_status,
    )
    columns = TOPIC_COLUMNS[topic]
    headers = _localized_headers(locale, columns)
    export_id = uuid4()
    started_at = datetime.now(UTC)
    started_monotonic = monotonic()
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="report.csv.export.started",
        resource_type="report",
        resource_id=project_id,
        result="started",
        request_id=request.state.request_id,
        summary={
            "export_id": str(export_id),
            "topic": topic,
            "scope": scope,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "project_id": str(project_id) if project_id else None,
            "locale": locale,
            "batch_size": settings.report_export_batch_size,
            "timeout_seconds": settings.report_export_timeout_seconds,
            "started_at": started_at.isoformat(),
        },
    )
    session.commit()
    _set_report_statement_timeout(
        session,
        settings.report_export_timeout_seconds,
    )
    batches = _iter_topic_batches(
        session,
        topic=topic,
        project_ids=scoped_project_ids,
        date_from=date_from,
        date_to=date_to,
        batch_size=settings.report_export_batch_size,
        model_filters=model_filters,
    )
    try:
        first_batch = next(batches)
    except StopIteration:
        first_batch = []
    except Exception:
        batches.close()
        session.rollback()
        add_audit(
            session,
            actor_user_id=context.user_id,
            action="report.csv.export.failed",
            resource_type="report",
            resource_id=project_id,
            result="failed",
            request_id=request.state.request_id,
            summary={
                "export_id": str(export_id),
                "topic": topic,
                "scope": scope,
                "project_id": str(project_id) if project_id else None,
                "row_count": 0,
                "error_code": "report_export_query_failed",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        session.commit()
        raise
    filename = _report_filename(topic, date_from, date_to)

    async def stream_rows():
        row_count = 0
        result = "completed"
        error_code: str | None = None
        deadline = started_monotonic + settings.report_export_timeout_seconds
        try:
            yield "\ufeff" + _report_csv_row(headers)
            current_batch = first_batch
            while True:
                if monotonic() >= deadline:
                    result = "failed"
                    error_code = "report_export_timeout"
                    raise TimeoutError("report export exceeded its configured timeout")
                if await request.is_disconnected():
                    result = "cancelled"
                    error_code = "client_disconnected"
                    raise asyncio.CancelledError
                for row in current_batch:
                    yield _report_csv_row(
                        [_csv_value(row.get(column)) for column in columns]
                    )
                    row_count += 1
                await asyncio.sleep(0)
                try:
                    current_batch = next(batches)
                except StopIteration:
                    break
        except asyncio.CancelledError:
            result = "cancelled"
            error_code = error_code or "client_disconnected"
            raise
        except GeneratorExit:
            result = "cancelled"
            error_code = "transport_closed"
            raise
        except Exception:
            result = "failed"
            error_code = error_code or "report_export_transport_failed"
            raise
        finally:
            batches.close()
            session.rollback()
            completed_at = datetime.now(UTC)
            add_audit(
                session,
                actor_user_id=context.user_id,
                action=f"report.csv.export.{result}",
                resource_type="report",
                resource_id=project_id,
                result=result,
                request_id=request.state.request_id,
                summary={
                    "export_id": str(export_id),
                    "topic": topic,
                    "scope": scope,
                    "project_id": str(project_id) if project_id else None,
                    "row_count": row_count,
                    "error_code": error_code,
                    "started_at": started_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "duration_ms": max(
                        0,
                        int((completed_at - started_at).total_seconds() * 1000),
                    ),
                },
            )
            session.commit()

    return StreamingResponse(
        stream_rows(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-NomoSmart-Export-Id": str(export_id),
        },
    )


def _validated_topic(topic: str) -> str:
    normalized = topic.strip()
    if normalized not in REPORT_TOPICS:
        raise AppError("report_topic_unsupported", "Report topic is not supported", status_code=422, details={"topic": topic})
    return normalized


def _validated_scope(scope: str) -> str:
    normalized = scope.strip().lower()
    if normalized not in REPORT_SCOPES:
        raise AppError("report_scope_unsupported", "Report scope is not supported", status_code=422, details={"scope": scope})
    return normalized


def _resolved_scope(scope: str | None, context: IdentityContext) -> str:
    if scope is not None:
        return _validated_scope(scope)
    if has_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW):
        return "system"
    return "accessible"


def _validate_date_range(date_from: datetime | None, date_to: datetime | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise AppError("report_date_range_invalid", "date_from must be before date_to", status_code=422)


def _available_scope_project_ids(session: Session, context: IdentityContext) -> dict[str, set[UUID] | None]:
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
        session.scalars(select(ApprovalTask.project_id).where(ApprovalTask.assignee_user_id == context.user_id))
    )
    scopes: dict[str, set[UUID] | None] = {
        "owner_projects": owner_ids,
        "accessible": set(context.visible_project_ids),
        "reviewer": reviewer_ids,
    }
    if has_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW):
        scopes["system"] = None
    return scopes


def _scope_project_count(session: Session, project_ids: set[UUID] | None) -> int:
    statement = select(func.count()).select_from(Project)
    if project_ids is not None:
        statement = statement.where(Project.id.in_(project_ids))
    return int(session.scalar(statement) or 0)


def _scoped_project_ids(
    session: Session,
    context: IdentityContext,
    scope: str,
    project_id: UUID | None,
) -> set[UUID] | None:
    scopes = _available_scope_project_ids(session, context)
    if scope not in scopes:
        raise AppError("report_scope_denied", "The requested report scope is not available", status_code=403)
    visible = scopes[scope]
    if project_id is not None:
        if visible is not None and project_id not in visible:
            raise AppError("project_scope_denied", "Report project is outside the user's visible scope", status_code=403)
        return {project_id}
    return visible


def _summary_metrics(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> list[ReportMetricCard]:
    chat_count = _count_chats(session, project_ids, date_from, date_to)
    validation_count = _count_validation_runs(session, project_ids, date_from, date_to)
    citation_count = _count_citations(session, project_ids, date_from, date_to)
    avg_latency = _avg_chat_latency(session, project_ids, date_from, date_to)
    return [
        ReportMetricCard(key="chat_count", label="Chat Queries", value=chat_count),
        ReportMetricCard(key="validation_run_count", label="Validation Runs", value=validation_count),
        ReportMetricCard(key="citation_count", label="Citations", value=citation_count),
        ReportMetricCard(key="avg_latency_ms", label="Average Latency", value=round(avg_latency or 0, 2), unit="ms"),
    ]


def _topic_rows(session: Session, topic: str, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    builders: dict[str, Callable[[Session, set[UUID] | None, datetime | None, datetime | None, int], list[dict]]] = {
        "system_overview": _system_overview_rows,
        "project_ranking": _project_ranking_rows,
        "project_reference_ranking": _project_reference_rows,
        "document_reference_ranking": _document_reference_rows,
        "owner_project_summary": _owner_project_rows,
        "document_pipeline_metrics": _pipeline_rows,
        "rag_quality_metrics": _rag_quality_rows,
        "validation_run_metrics": _validation_rows,
        "model_usage_metrics": _model_usage_rows,
        "alert_metrics": _alert_rows,
    }
    return builders[topic](session, project_ids, date_from, date_to, limit)


@dataclass(frozen=True)
class ReportModelFilters:
    model_type: str | None = None
    usage_purpose: str | None = None
    source_channel: str | None = None
    usage_status: str | None = None


PROJECT_ROW_TOPICS = {
    "project_ranking",
    "owner_project_summary",
    "document_pipeline_metrics",
    "rag_quality_metrics",
    "validation_run_metrics",
}


def _topic_page(
    session: Session,
    *,
    topic: str,
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
    offset: int,
    limit: int,
    model_filters: ReportModelFilters,
) -> tuple[list[dict], int]:
    if topic == "system_overview":
        rows = _system_overview_rows(
            session,
            project_ids,
            date_from,
            date_to,
            limit,
        )
        return rows[offset : offset + limit], len(rows)
    if topic in PROJECT_ROW_TOPICS:
        statement = _project_report_statement(
            topic,
            project_ids,
            date_from,
            date_to,
        )
        projects = list(session.scalars(statement.offset(offset).limit(limit)))
        rows = _project_batch_rows(
            session,
            topic,
            projects,
            date_from,
            date_to,
            rank_offset=offset,
        )
        return rows, _scope_project_count(session, project_ids)
    if topic == "project_reference_ranking":
        statement = _project_reference_group_statement(
            project_ids,
            date_from,
            date_to,
        )
        total = _group_count(session, statement)
        rows = [
            _project_reference_mapping(
                session,
                row,
                date_from,
                date_to,
                rank=offset + index,
            )
            for index, row in enumerate(
                session.execute(statement.offset(offset).limit(limit)),
                start=1,
            )
        ]
        return rows, total
    if topic == "document_reference_ranking":
        statement = _document_reference_group_statement(
            project_ids,
            date_from,
            date_to,
        )
        total = _group_count(session, statement)
        rows = [
            _document_reference_mapping(
                session,
                row,
                date_from,
                date_to,
                rank=offset + index,
            )
            for index, row in enumerate(
                session.execute(statement.offset(offset).limit(limit)),
                start=1,
            )
        ]
        return rows, total
    if topic == "model_usage_metrics":
        statement = _model_usage_statement(
            project_ids,
            date_from,
            date_to,
            model_type=model_filters.model_type,
            usage_purpose=model_filters.usage_purpose,
            source_channel=model_filters.source_channel,
            usage_status=model_filters.usage_status,
        )
        total = _group_count(session, statement)
        rows = [
            _model_usage_mapping(row)
            for row in session.execute(statement.offset(offset).limit(limit))
        ]
        return rows, total
    if topic == "alert_metrics":
        statement = _alert_group_statement(project_ids, date_from, date_to)
        total = _group_count(session, statement)
        rows = [
            _alert_mapping(session, row)
            for row in session.execute(statement.offset(offset).limit(limit))
        ]
        return rows, total
    raise AppError(
        "report_topic_unsupported",
        "Report topic does not have a bounded query adapter",
        status_code=422,
    )


def _iter_topic_batches(
    session: Session,
    *,
    topic: str,
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
    batch_size: int,
    model_filters: ReportModelFilters,
):
    if topic == "system_overview":
        rows = _system_overview_rows(
            session,
            project_ids,
            date_from,
            date_to,
            batch_size,
        )
        if rows:
            yield rows
        return
    if topic in PROJECT_ROW_TOPICS:
        result = session.scalars(
            _project_report_statement(
                topic,
                project_ids,
                date_from,
                date_to,
            ).execution_options(
                stream_results=True,
                yield_per=batch_size,
                max_row_buffer=batch_size,
            )
        )
        rank_offset = 0
        try:
            for projects in result.partitions(batch_size):
                rows = _project_batch_rows(
                    session,
                    topic,
                    list(projects),
                    date_from,
                    date_to,
                    rank_offset=rank_offset,
                )
                rank_offset += len(rows)
                if rows:
                    yield rows
        finally:
            result.close()
        return
    if topic == "project_reference_ranking":
        statement = _project_reference_group_statement(
            project_ids,
            date_from,
            date_to,
        )
        mapper = lambda row, rank: _project_reference_mapping(
            session,
            row,
            date_from,
            date_to,
            rank=rank,
        )
    elif topic == "document_reference_ranking":
        statement = _document_reference_group_statement(
            project_ids,
            date_from,
            date_to,
        )
        mapper = lambda row, rank: _document_reference_mapping(
            session,
            row,
            date_from,
            date_to,
            rank=rank,
        )
    elif topic == "model_usage_metrics":
        statement = _model_usage_statement(
            project_ids,
            date_from,
            date_to,
            model_type=model_filters.model_type,
            usage_purpose=model_filters.usage_purpose,
            source_channel=model_filters.source_channel,
            usage_status=model_filters.usage_status,
        )
        mapper = lambda row, _rank: _model_usage_mapping(row)
    elif topic == "alert_metrics":
        statement = _alert_group_statement(project_ids, date_from, date_to)
        mapper = lambda row, _rank: _alert_mapping(session, row)
    else:
        raise AppError(
            "report_topic_unsupported",
            "Report topic does not have a bounded export adapter",
            status_code=422,
        )
    result = session.execute(
        statement.execution_options(
            stream_results=True,
            yield_per=batch_size,
            max_row_buffer=batch_size,
        )
    )
    rank = 0
    try:
        for partition in result.partitions(batch_size):
            rows = []
            for row in partition:
                rank += 1
                rows.append(mapper(row, rank))
            if rows:
                yield rows
    finally:
        result.close()


def _group_count(session: Session, statement) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )


def _set_report_statement_timeout(session: Session, timeout_seconds: int) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.scalar(
        select(
            func.set_config(
                "statement_timeout",
                str(timeout_seconds * 1000),
                True,
            )
        )
    )


def _project_report_statement(
    topic: str,
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    statement = select(Project)
    if project_ids is not None:
        statement = statement.where(Project.id.in_(project_ids))
    if topic != "project_ranking":
        return statement.order_by(Project.name, Project.id)
    chat_count = _correlated_project_count(
        ChatRecord,
        ChatRecord.created_at,
        date_from,
        date_to,
    )
    validation_count = _correlated_project_count(
        ValidationRun,
        ValidationRun.created_at,
        date_from,
        date_to,
    )
    pipeline_count = _correlated_project_count(
        PipelineRun,
        PipelineRun.created_at,
        date_from,
        date_to,
    )
    return statement.order_by(
        chat_count.desc(),
        validation_count.desc(),
        pipeline_count.desc(),
        Project.id,
    )


def _correlated_project_count(
    model,
    date_column,
    date_from: datetime | None,
    date_to: datetime | None,
):
    statement = select(func.count()).select_from(model).where(
        model.project_id == Project.id
    )
    if date_from is not None:
        statement = statement.where(date_column >= date_from)
    if date_to is not None:
        statement = statement.where(date_column <= date_to)
    return statement.correlate(Project).scalar_subquery()


def _project_batch_rows(
    session: Session,
    topic: str,
    projects: list[Project],
    date_from: datetime | None,
    date_to: datetime | None,
    *,
    rank_offset: int,
) -> list[dict]:
    if not projects:
        return []
    project_ids = {project.id for project in projects}
    rows = _topic_rows(
        session,
        topic,
        project_ids,
        date_from,
        date_to,
        len(projects),
    )
    order = {project.id: index for index, project in enumerate(projects)}
    rows.sort(
        key=lambda row: order.get(
            row.get("project_id"),
            len(order),
        )
    )
    if topic == "project_ranking":
        for index, row in enumerate(rows, start=rank_offset + 1):
            row["rank"] = index
    return rows


def _reference_scope_filter(statement, project_ids: set[UUID] | None):
    if project_ids is not None:
        statement = statement.where(
            DocumentReference.source_project_id.in_(project_ids)
        )
    return statement


def _reference_date_filter(
    statement,
    date_from: datetime | None,
    date_to: datetime | None,
):
    statement = statement.where(DocumentReference.status == "active")
    if date_from is not None:
        statement = statement.where(DocumentReference.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(DocumentReference.created_at <= date_to)
    return statement


def _project_reference_group_statement(
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    statement = select(
        DocumentReference.source_project_id.label("source_project_id"),
        func.max(DocumentReference.source_project_name_snapshot).label(
            "source_project"
        ),
        func.count(DocumentReference.id).label("reference_count"),
        func.count(func.distinct(DocumentReference.target_project_id)).label(
            "target_project_count"
        ),
        func.count(func.distinct(DocumentReference.source_document_id)).label(
            "referenced_document_count"
        ),
    )
    statement = _reference_scope_filter(statement, project_ids)
    statement = _reference_date_filter(statement, date_from, date_to)
    return statement.group_by(DocumentReference.source_project_id).order_by(
        func.count(DocumentReference.id).desc(),
        DocumentReference.source_project_id,
    )


def _project_reference_mapping(
    session: Session,
    row,
    date_from: datetime | None,
    date_to: datetime | None,
    *,
    rank: int,
) -> dict:
    mapping = row._mapping
    project_id = mapping["source_project_id"]
    pending = _count_reference_events(
        session,
        {project_id},
        date_from,
        date_to,
    )
    return {
        "rank": rank,
        "source_project_id": project_id,
        "source_project": mapping["source_project"],
        "reference_count": int(mapping["reference_count"]),
        "target_project_count": int(mapping["target_project_count"]),
        "referenced_document_count": int(
            mapping["referenced_document_count"]
        ),
        "new_references_30d": int(mapping["reference_count"]),
        "pending_source_events": pending,
        "quality_score": max(0, 100 - pending * 5),
    }


def _document_reference_group_statement(
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    statement = select(
        DocumentReference.source_document_id.label("source_document_id"),
        func.max(DocumentReference.source_document_name_snapshot).label(
            "document_name"
        ),
        DocumentReference.source_project_id.label("source_project_id"),
        func.max(DocumentReference.source_project_name_snapshot).label(
            "source_project"
        ),
        func.count(DocumentReference.id).label("reference_count"),
        func.count(func.distinct(DocumentReference.target_project_id)).label(
            "target_project_count"
        ),
    )
    statement = _reference_scope_filter(statement, project_ids)
    statement = _reference_date_filter(statement, date_from, date_to)
    return statement.group_by(
        DocumentReference.source_document_id,
        DocumentReference.source_project_id,
    ).order_by(
        func.count(DocumentReference.id).desc(),
        DocumentReference.source_document_id,
    )


def _document_reference_mapping(
    session: Session,
    row,
    date_from: datetime | None,
    date_to: datetime | None,
    *,
    rank: int,
) -> dict:
    mapping = row._mapping
    project_id = mapping["source_project_id"]
    document_id = mapping["source_document_id"]
    latest_version = session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.project_id == project_id,
            DocumentVersion.status == "active",
        )
        .order_by(
            DocumentVersion.version_major.desc(),
            DocumentVersion.extraction_revision.desc(),
            DocumentVersion.id.desc(),
        )
        .limit(1)
    )
    return {
        "rank": rank,
        "source_document_id": document_id,
        "document_name": mapping["document_name"],
        "source_project_id": project_id,
        "source_project": mapping["source_project"],
        "reference_count": int(mapping["reference_count"]),
        "target_project_count": int(mapping["target_project_count"]),
        "active_version": latest_version.version_label if latest_version else None,
        "last_source_update": _iso(
            latest_version.updated_at if latest_version else None
        ),
        "pending_sync_count": _count_reference_events(
            session,
            {project_id},
            date_from,
            date_to,
        ),
        "qa_hit_count": _count_chats(
            session,
            {project_id},
            date_from,
            date_to,
        ),
        "human_correct_rate": _human_correct_rate(
            session,
            {project_id},
            date_from,
            date_to,
        ),
    }


def _alert_group_statement(
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    severity_rank = func.max(
        case(
            (Notification.severity.in_(("critical", "high")), 3),
            (Notification.severity == "medium", 2),
            else_=1,
        )
    ).label("severity_rank")
    statement = select(
        Notification.notification_type.label("alert_type"),
        Notification.project_id.label("project_id"),
        func.count(Notification.id).label("count"),
        func.min(Notification.created_at).label("oldest_at"),
        severity_rank,
    ).where(Notification.resolved_at.is_(None))
    statement = _project_date_filters(
        statement,
        Notification,
        Notification.created_at,
        project_ids,
        date_from,
        date_to,
    )
    return statement.group_by(
        Notification.notification_type,
        Notification.project_id,
    ).order_by(
        func.count(Notification.id).desc(),
        Notification.notification_type,
        Notification.project_id.nulls_first(),
    )


def _alert_mapping(session: Session, row) -> dict:
    mapping = row._mapping
    project_id = mapping["project_id"]
    project = session.get(Project, project_id) if project_id else None
    severity_rank = int(mapping["severity_rank"] or 1)
    return {
        "level": "high"
        if severity_rank >= 3
        else "medium"
        if severity_rank == 2
        else "low",
        "alert_type": mapping["alert_type"],
        "project_id": project_id,
        "project_name": project.name
        if project
        else "全系統"
        if project_id is None
        else "",
        "count": int(mapping["count"]),
        "oldest_at": _iso(mapping["oldest_at"]),
    }


def _projects(session: Session, project_ids: set[UUID] | None, limit: int | None = None) -> list[Project]:
    statement = select(Project)
    if project_ids is not None:
        statement = statement.where(Project.id.in_(project_ids))
    statement = statement.order_by(Project.name)
    if limit:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def _count_documents(session: Session, project_ids: set[UUID] | None, status: str | None = None, *, deleted: bool | None = None) -> int:
    query = select(func.count()).select_from(Document)
    if project_ids is not None:
        query = query.where(Document.project_id.in_(project_ids))
    if status:
        query = query.where(Document.status == status)
    if deleted is not None:
        query = query.where(Document.is_deleted.is_(deleted))
    return int(session.scalar(query) or 0)


def _count_chats(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> int:
    return _count_project_dated(session, ChatRecord, ChatRecord.created_at, project_ids, date_from, date_to)


def _count_validation_runs(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> int:
    return _count_project_dated(session, ValidationRun, ValidationRun.created_at, project_ids, date_from, date_to)


def _count_project_dated(session: Session, model, date_column, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, status: str | None = None) -> int:
    query = select(func.count()).select_from(model)
    if project_ids is not None:
        query = query.where(model.project_id.in_(project_ids))
    if date_from:
        query = query.where(date_column >= date_from)
    if date_to:
        query = query.where(date_column <= date_to)
    if status and hasattr(model, "status"):
        query = query.where(model.status == status)
    return int(session.scalar(query) or 0)


def _count_citations(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> int:
    query = select(
        func.coalesce(
            func.sum(func.jsonb_array_length(ChatRecord.reference_docs)),
            0,
        )
    )
    query = _chat_filters(query, project_ids, date_from, date_to)
    return int(session.scalar(query) or 0)


def _avg_chat_latency(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> float | None:
    query = select(func.avg(ChatRecord.latency_ms)).where(ChatRecord.latency_ms.is_not(None))
    query = _chat_filters(query, project_ids, date_from, date_to)
    value = session.scalar(query)
    return float(value) if value is not None else None


def _chat_filters(query, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None):
    if project_ids is not None:
        query = query.where(ChatRecord.project_id.in_(project_ids))
    if date_from:
        query = query.where(ChatRecord.created_at >= date_from)
    if date_to:
        query = query.where(ChatRecord.created_at <= date_to)
    return query


def _system_overview_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, _limit: int) -> list[dict]:
    validation_total = _count_validation_runs(session, project_ids, date_from, date_to)
    validation_completed = _count_project_dated(session, ValidationRun, ValidationRun.created_at, project_ids, date_from, date_to, "completed")
    chat_aggregates = _chat_filters(
        select(
            func.count(ChatRecord.id).label("chat_count"),
            func.sum(
                case(
                    (
                        (ChatRecord.answer.like("無法確認%"))
                        | (ChatRecord.evaluation == "needs_revision"),
                        1,
                    ),
                    else_=0,
                )
            ).label("no_answer_count"),
            func.sum(
                case(
                    (func.jsonb_array_length(ChatRecord.reference_docs) > 0, 1),
                    else_=0,
                )
            ).label("cited_count"),
        ),
        project_ids,
        date_from,
        date_to,
    )
    chat_row = session.execute(chat_aggregates).one()
    chat_count = int(chat_row.chat_count or 0)
    no_answer = int(chat_row.no_answer_count or 0)
    cited = int(chat_row.cited_count or 0)
    values = {
        "document_count": _count_documents(session, project_ids),
        "active_documents": _count_documents(session, project_ids, "active", deleted=False),
        "deleted_documents": _count_documents(session, project_ids, deleted=True),
        "chat_count": chat_count,
        "no_answer_rate": _rate(no_answer, chat_count),
        "cited_answer_rate": _rate(cited, chat_count),
        "validation_run_count": validation_total,
        "validation_pass_rate": _rate(validation_completed, validation_total),
    }
    return [{"metric_key": key, "metric_value": value, "date_from": _iso(date_from), "date_to": _iso(date_to)} for key, value in values.items()]


def _project_rankings(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int = 20) -> list[ReportProjectRankingItem]:
    projects = list(
        session.scalars(
            _project_report_statement(
                "project_ranking",
                project_ids,
                date_from,
                date_to,
            ).limit(limit)
        )
    )
    rows = _project_batch_rows(
        session,
        "project_ranking",
        projects,
        date_from,
        date_to,
        rank_offset=0,
    )
    return [
        ReportProjectRankingItem(project_id=row["project_id"], project_name=row["project_name"], chat_count=row["qa_count"], validation_run_count=row["validation_runs"], citation_count=_count_citations(session, {row["project_id"]}, date_from, date_to))
        for row in rows
    ]


def _project_ranking_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    rows: list[dict] = []
    for project in _projects(session, project_ids):
        scoped = {project.id}
        pipeline_total = _count_project_dated(session, PipelineRun, PipelineRun.created_at, scoped, date_from, date_to)
        pipeline_failed = _count_project_dated(session, PipelineRun, PipelineRun.created_at, scoped, date_from, date_to, "failed")
        chat_count = _count_chats(session, scoped, date_from, date_to)
        validation_count = _count_validation_runs(session, scoped, date_from, date_to)
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "document_count": _count_documents(session, scoped, deleted=False),
                "active_documents": _count_documents(session, scoped, "active", deleted=False),
                "pipeline_runs": pipeline_total,
                "qa_count": chat_count,
                "validation_runs": validation_count,
                "active_users_30d": _active_user_count(session, scoped),
                "success_rate": _rate(pipeline_total - pipeline_failed, pipeline_total),
                "failure_rate": _rate(pipeline_failed, pipeline_total),
            }
        )
    rows.sort(key=lambda item: (item["qa_count"], item["validation_runs"], item["pipeline_runs"]), reverse=True)
    return [dict({"rank": index + 1}, **row) for index, row in enumerate(rows[:limit])]


def _project_reference_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    references = _references(session, project_ids, date_from, date_to)
    grouped: dict[UUID, list[DocumentReference]] = {}
    for reference in references:
        grouped.setdefault(reference.source_project_id, []).append(reference)
    rows = []
    for source_project_id, items in grouped.items():
        scoped = {source_project_id}
        pending = _count_reference_events(session, scoped, date_from, date_to)
        rows.append(
            {
                "source_project_id": source_project_id,
                "source_project": items[0].source_project_name_snapshot,
                "reference_count": len(items),
                "target_project_count": len({item.target_project_id for item in items}),
                "referenced_document_count": len({item.source_document_id for item in items}),
                "new_references_30d": len(items),
                "pending_source_events": pending,
                "quality_score": max(0, 100 - pending * 5),
            }
        )
    rows.sort(key=lambda item: item["reference_count"], reverse=True)
    return [dict({"rank": index + 1}, **row) for index, row in enumerate(rows[:limit])]


def _document_reference_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    references = _references(session, project_ids, date_from, date_to)
    grouped: dict[UUID, list[DocumentReference]] = {}
    for reference in references:
        grouped.setdefault(reference.source_document_id, []).append(reference)
    rows = []
    for source_document_id, items in grouped.items():
        latest_version = session.get(DocumentVersion, items[0].source_version_id)
        rows.append(
            {
                "source_document_id": source_document_id,
                "document_name": items[0].source_document_name_snapshot,
                "source_project_id": items[0].source_project_id,
                "source_project": items[0].source_project_name_snapshot,
                "reference_count": len(items),
                "target_project_count": len({item.target_project_id for item in items}),
                "active_version": latest_version.version_label if latest_version else None,
                "last_source_update": _iso(latest_version.updated_at if latest_version else None),
                "pending_sync_count": _count_reference_events(session, {items[0].source_project_id}, date_from, date_to),
                "qa_hit_count": _count_chats(session, {items[0].source_project_id}, date_from, date_to),
                "human_correct_rate": _human_correct_rate(session, {items[0].source_project_id}, date_from, date_to),
            }
        )
    rows.sort(key=lambda item: item["reference_count"], reverse=True)
    return [dict({"rank": index + 1}, **row) for index, row in enumerate(rows[:limit])]


def _owner_project_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    rows = []
    for project in _projects(session, project_ids, limit):
        scoped = {project.id}
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "active_documents": _count_documents(session, scoped, "active", deleted=False),
                "pending_manager_review": _count_approval(session, scoped, "pending_manager_review"),
                "pending_owner_review": _count_approval(session, scoped, "pending_owner_review"),
                "approved_unpublished": _count_approval(session, scoped, "approved"),
                "inbound_references": _count_references(
                    session,
                    project.id,
                    "source",
                    date_from,
                    date_to,
                ),
                "outbound_references": _count_references(
                    session,
                    project.id,
                    "target",
                    date_from,
                    date_to,
                ),
                "no_answer_rate": _no_answer_rate(session, scoped, date_from, date_to),
                "validation_pass_rate": _validation_pass_rate(session, scoped, date_from, date_to),
                "open_alerts": _count_notifications(session, scoped, unresolved_only=True),
            }
        )
    return rows


def _pipeline_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    rows = []
    for project in _projects(session, project_ids, limit):
        scoped = {project.id}
        duration_seconds = func.greatest(
            0.0,
            func.extract(
                "epoch",
                PipelineRun.completed_at
                - func.coalesce(PipelineRun.started_at, PipelineRun.created_at),
            ),
        )
        aggregate_query = _project_date_filters(
            select(
                func.count(PipelineRun.id).label("pipeline_runs"),
                func.sum(
                    case((PipelineRun.status == "completed", 1), else_=0)
                ).label("completed_runs"),
                func.sum(
                    case((PipelineRun.status == "failed", 1), else_=0)
                ).label("failed_runs"),
                func.avg(duration_seconds)
                .filter(PipelineRun.completed_at.is_not(None))
                .label("avg_pipeline_seconds"),
                func.percentile_cont(0.95)
                .within_group(duration_seconds)
                .filter(PipelineRun.completed_at.is_not(None))
                .label("p95_pipeline_seconds"),
            ),
            PipelineRun,
            PipelineRun.created_at,
            scoped,
            date_from,
            date_to,
        )
        aggregate = session.execute(aggregate_query).one()
        retry_query = (
            select(func.coalesce(func.sum(PipelineRunStep.retry_count), 0))
            .join(PipelineRun, PipelineRun.id == PipelineRunStep.run_id)
        )
        retry_query = _project_date_filters(
            retry_query,
            PipelineRun,
            PipelineRun.created_at,
            scoped,
            date_from,
            date_to,
        )
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "pipeline_runs": int(aggregate.pipeline_runs or 0),
                "completed_runs": int(aggregate.completed_runs or 0),
                "failed_runs": int(aggregate.failed_runs or 0),
                "retry_count": int(session.scalar(retry_query) or 0),
                "avg_pipeline_seconds": round(
                    float(aggregate.avg_pipeline_seconds),
                    2,
                )
                if aggregate.avg_pipeline_seconds is not None
                else None,
                "p95_pipeline_seconds": round(
                    float(aggregate.p95_pipeline_seconds),
                    2,
                )
                if aggregate.p95_pipeline_seconds is not None
                else None,
            }
        )
    return rows


def _rag_quality_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    rows = []
    for project in _projects(session, project_ids, limit):
        scoped = {project.id}
        aggregate_query = _chat_filters(
            select(
                func.count(ChatRecord.id).label("qa_count"),
                func.sum(
                    case((ChatRecord.answer.like("無法確認%"), 1), else_=0)
                ).label("no_answer_count"),
                func.sum(
                    case(
                        (func.jsonb_array_length(ChatRecord.reference_docs) > 0, 1),
                        else_=0,
                    )
                ).label("cited_count"),
                func.sum(
                    case((ChatRecord.evaluation == "correct", 1), else_=0)
                ).label("correct_count"),
                func.sum(
                    case(
                        (ChatRecord.evaluation == "needs_revision", 1),
                        else_=0,
                    )
                ).label("needs_revision_count"),
                func.sum(
                    case(
                        (ChatRecord.evaluation != "not_evaluated", 1),
                        else_=0,
                    )
                ).label("evaluated_count"),
            ),
            scoped,
            date_from,
            date_to,
        )
        aggregate = session.execute(aggregate_query).one()
        qa_count = int(aggregate.qa_count or 0)
        evaluated_count = int(aggregate.evaluated_count or 0)
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "qa_count": qa_count,
                "no_answer_rate": _rate(
                    int(aggregate.no_answer_count or 0),
                    qa_count,
                ),
                "cited_answer_rate": _rate(
                    int(aggregate.cited_count or 0),
                    qa_count,
                ),
                "human_correct_rate": _rate(
                    int(aggregate.correct_count or 0),
                    evaluated_count,
                ),
                "needs_revision_rate": _rate(
                    int(aggregate.needs_revision_count or 0),
                    evaluated_count,
                ),
            }
        )
    return rows


def _validation_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    rows = []
    for project in _projects(session, project_ids, limit):
        scoped = {project.id}
        run_query = _project_date_filters(
            select(
                func.count(ValidationRun.id).label("validation_runs"),
                func.sum(
                    case((ValidationRun.status == "completed", 1), else_=0)
                ).label("completed_runs"),
                func.sum(
                    case(
                        (
                            ValidationRun.status.in_(("failed", "partial_failed")),
                            1,
                        ),
                        else_=0,
                    )
                ).label("failed_runs"),
            ),
            ValidationRun,
            ValidationRun.created_at,
            scoped,
            date_from,
            date_to,
        )
        run_aggregate = session.execute(run_query).one()
        item_query = (
            select(
                func.sum(
                    case(
                        (
                            (ValidationRunItem.score.is_not(None))
                            & (ValidationRunItem.score >= Decimal("0.8")),
                            1,
                        ),
                        else_=0,
                    )
                ).label("passed_items"),
                func.sum(
                    case(
                        (ValidationRunItem.score.is_not(None), 1),
                        else_=0,
                    )
                ).label("scored_items"),
                func.sum(
                    case((ValidationRunItem.status == "failed", 1), else_=0)
                ).label("failed_questions"),
                func.sum(
                    case(
                        (
                            (ValidationRunItem.score.is_not(None))
                            & (ValidationRunItem.score < Decimal("0.8")),
                            1,
                        ),
                        else_=0,
                    )
                ).label("manual_review_count"),
            )
            .join(
                ValidationRun,
                ValidationRun.id == ValidationRunItem.run_id,
            )
            .where(ValidationRunItem.is_current.is_(True))
        )
        item_query = _project_date_filters(
            item_query,
            ValidationRun,
            ValidationRun.created_at,
            scoped,
            date_from,
            date_to,
        )
        item_aggregate = session.execute(item_query).one()
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "validation_runs": int(run_aggregate.validation_runs or 0),
                "completed_runs": int(run_aggregate.completed_runs or 0),
                "failed_runs": int(run_aggregate.failed_runs or 0),
                "pass_rate": _rate(
                    int(item_aggregate.passed_items or 0),
                    int(item_aggregate.scored_items or 0),
                ),
                "failed_questions": int(item_aggregate.failed_questions or 0),
                "manual_review_count": int(
                    item_aggregate.manual_review_count or 0
                ),
            }
        )
    return rows


def _model_usage_rows(
    session: Session,
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    *,
    model_type: str | None = None,
    usage_purpose: str | None = None,
    source_channel: str | None = None,
    usage_status: str | None = None,
    offset: int = 0,
) -> list[dict]:
    statement = _model_usage_statement(
        project_ids,
        date_from,
        date_to,
        model_type=model_type,
        usage_purpose=usage_purpose,
        source_channel=source_channel,
        usage_status=usage_status,
    )
    return [
        _model_usage_mapping(row)
        for row in session.execute(statement.offset(offset).limit(limit))
    ]


def _model_usage_statement(
    project_ids: set[UUID] | None,
    date_from: datetime | None,
    date_to: datetime | None,
    *,
    model_type: str | None = None,
    usage_purpose: str | None = None,
    source_channel: str | None = None,
    usage_status: str | None = None,
):
    effective_model_name = func.coalesce(
        AIModel.config["model_name"].astext,
        AIModel.name,
    )
    attempted = func.sum(
        case((AIModelUsageEvent.attempted.is_(True), 1), else_=0)
    ).label("call_count")
    successes = func.sum(
        case(
            (
                and_(
                    AIModelUsageEvent.attempted.is_(True),
                    AIModelUsageEvent.status == "success",
                ),
                1,
            ),
            else_=0,
        )
    ).label("success_count")
    failures = func.sum(
        case(
            (
                and_(
                    AIModelUsageEvent.attempted.is_(True),
                    AIModelUsageEvent.status.in_(
                        ("failed", "timeout", "cancelled", "partial")
                    ),
                ),
                1,
            ),
            else_=0,
        )
    ).label("failure_count")
    statement = (
        select(
            AIModelUsageEvent.model_type.label("model_type"),
            AIModel.name.label("ai_model_name"),
            func.min(effective_model_name).label("model_name"),
            AIModelUsageEvent.provider.label("provider"),
            Project.name.label("project_name"),
            AIModelUsageEvent.usage_purpose.label("usage_purpose"),
            AIModelUsageEvent.source_channel.label("source_channel"),
            AIModelUsageEvent.cost_currency.label("currency"),
            attempted,
            successes,
            failures,
            func.coalesce(func.sum(AIModelUsageEvent.input_tokens), 0).label(
                "input_tokens"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.output_tokens), 0).label(
                "output_tokens"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.total_tokens), 0).label(
                "total_tokens"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.embedding_tokens), 0).label(
                "embedding_tokens"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.ocr_pages), 0).label(
                "ocr_pages"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.ocr_images), 0).label(
                "ocr_images"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.vector_count), 0).label(
                "vector_count"
            ),
            func.coalesce(func.sum(AIModelUsageEvent.chunk_count), 0).label(
                "chunk_count"
            ),
            func.avg(AIModelUsageEvent.latency_ms).label("avg_latency_ms"),
            func.percentile_cont(0.95)
            .within_group(AIModelUsageEvent.latency_ms)
            .label("p95_latency_ms"),
            func.sum(AIModelUsageEvent.provider_reported_cost).label(
                "provider_reported_cost"
            ),
            func.sum(AIModelUsageEvent.estimated_cost).label("estimated_cost"),
            func.min(AIModelUsageEvent.cost_source).label("min_cost_source"),
            func.max(AIModelUsageEvent.cost_source).label("max_cost_source"),
        )
        .join(AIModel, AIModel.id == AIModelUsageEvent.model_id)
        .outerjoin(Project, Project.id == AIModelUsageEvent.project_id)
    )
    if project_ids is not None:
        statement = statement.where(AIModelUsageEvent.project_id.in_(project_ids))
    if date_from is not None:
        statement = statement.where(AIModelUsageEvent.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(AIModelUsageEvent.created_at <= date_to)
    if model_type:
        statement = statement.where(AIModelUsageEvent.model_type == model_type)
    if usage_purpose:
        statement = statement.where(AIModelUsageEvent.usage_purpose == usage_purpose)
    if source_channel:
        statement = statement.where(AIModelUsageEvent.source_channel == source_channel)
    if usage_status:
        statement = statement.where(AIModelUsageEvent.status == usage_status)
    group_columns = (
        AIModelUsageEvent.model_type,
        AIModel.name,
        AIModelUsageEvent.provider,
        Project.name,
        AIModelUsageEvent.usage_purpose,
        AIModelUsageEvent.source_channel,
        AIModelUsageEvent.cost_currency,
    )
    return statement.group_by(*group_columns).order_by(
        AIModelUsageEvent.model_type,
        AIModel.name,
        AIModelUsageEvent.provider,
        Project.name.nulls_first(),
        AIModelUsageEvent.usage_purpose,
        AIModelUsageEvent.source_channel,
        AIModelUsageEvent.cost_currency.nulls_first(),
    )


def _model_usage_mapping(row) -> dict:
    mapping = row._mapping
    calls = int(mapping["call_count"] or 0)
    failures = int(mapping["failure_count"] or 0)
    cost_source = (
        mapping["min_cost_source"]
        if mapping["min_cost_source"] == mapping["max_cost_source"]
        else "mixed"
    )
    return {
        "model_type": mapping["model_type"],
        "ai_model_name": mapping["ai_model_name"],
        "provider": mapping["provider"],
        "model_name": mapping["model_name"],
        "project_name": mapping["project_name"],
        "usage_purpose": mapping["usage_purpose"],
        "source_channel": mapping["source_channel"],
        "call_count": calls,
        "success_count": int(mapping["success_count"] or 0),
        "failure_count": failures,
        "input_tokens": int(mapping["input_tokens"] or 0),
        "output_tokens": int(mapping["output_tokens"] or 0),
        "total_tokens": int(mapping["total_tokens"] or 0),
        "embedding_tokens": int(mapping["embedding_tokens"] or 0),
        "ocr_pages": int(mapping["ocr_pages"] or 0),
        "ocr_images": int(mapping["ocr_images"] or 0),
        "vector_count": int(mapping["vector_count"] or 0),
        "chunk_count": int(mapping["chunk_count"] or 0),
        "avg_latency_ms": round(float(mapping["avg_latency_ms"]), 2)
        if mapping["avg_latency_ms"] is not None
        else None,
        "p95_latency_ms": float(mapping["p95_latency_ms"])
        if mapping["p95_latency_ms"] is not None
        else None,
        "provider_reported_cost": float(mapping["provider_reported_cost"])
        if mapping["provider_reported_cost"] is not None
        and cost_source in {"provider_reported", "mixed"}
        else None,
        "estimated_cost": float(mapping["estimated_cost"])
        if mapping["estimated_cost"] is not None
        and cost_source in {"estimated", "mixed"}
        else None,
        "currency": mapping["currency"],
        "cost_source": cost_source,
        "error_rate": round(failures / calls, 5) if calls else 0,
    }


def _alert_rows(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None, limit: int) -> list[dict]:
    notifications = list(session.scalars(_project_date_filters(select(Notification), Notification, Notification.created_at, project_ids, date_from, date_to)))
    grouped: dict[tuple[str, UUID | None], list[Notification]] = {}
    for notification in notifications:
        if notification.resolved_at is None:
            grouped.setdefault((notification.notification_type, notification.project_id), []).append(notification)
    rows = []
    project_names = {project.id: project.name for project in _projects(session, project_ids)}
    for (alert_type, pid), items in grouped.items():
        rows.append({"level": _alert_level(items), "alert_type": alert_type, "project_id": pid, "project_name": project_names.get(pid, "全系統" if pid is None else ""), "count": len(items), "oldest_at": _iso(min(item.created_at for item in items))})
    rows.sort(key=lambda item: item["count"], reverse=True)
    return rows[:limit]


def _references(session: Session, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None) -> list[DocumentReference]:
    query = select(DocumentReference).where(DocumentReference.status == "active")
    if project_ids is not None:
        query = query.where((DocumentReference.source_project_id.in_(project_ids)) | (DocumentReference.target_project_id.in_(project_ids)))
    if date_from:
        query = query.where(DocumentReference.created_at >= date_from)
    if date_to:
        query = query.where(DocumentReference.created_at <= date_to)
    return list(session.scalars(query))


def _count_references(
    session: Session,
    project_id: UUID,
    direction: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> int:
    project_column = (
        DocumentReference.source_project_id
        if direction == "source"
        else DocumentReference.target_project_id
    )
    query = select(func.count()).select_from(DocumentReference).where(
        DocumentReference.status == "active",
        project_column == project_id,
    )
    if date_from is not None:
        query = query.where(DocumentReference.created_at >= date_from)
    if date_to is not None:
        query = query.where(DocumentReference.created_at <= date_to)
    return int(session.scalar(query) or 0)


def _project_date_filters(query, model, date_column, project_ids: set[UUID] | None, date_from: datetime | None, date_to: datetime | None):
    if project_ids is not None and hasattr(model, "project_id"):
        query = query.where(model.project_id.in_(project_ids))
    if date_from:
        query = query.where(date_column >= date_from)
    if date_to:
        query = query.where(date_column <= date_to)
    return query


def _active_user_count(session: Session, project_ids: set[UUID]) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(ChatRecord.created_by))).where(
                ChatRecord.project_id.in_(project_ids)
            )
        )
        or 0
    )


def _count_approval(session: Session, project_ids: set[UUID], status: str) -> int:
    return int(session.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.project_id.in_(project_ids), ApprovalRequest.status == status)) or 0)


def _count_reference_events(session: Session, project_ids: set[UUID], date_from: datetime | None, date_to: datetime | None) -> int:
    query = select(func.count()).select_from(DocumentReferenceEvent).where(DocumentReferenceEvent.source_project_id.in_(project_ids), DocumentReferenceEvent.resolved_at.is_(None))
    if date_from:
        query = query.where(DocumentReferenceEvent.created_at >= date_from)
    if date_to:
        query = query.where(DocumentReferenceEvent.created_at <= date_to)
    return int(session.scalar(query) or 0)


def _count_notifications(session: Session, project_ids: set[UUID], *, unresolved_only: bool) -> int:
    query = select(func.count()).select_from(Notification).where(Notification.project_id.in_(project_ids))
    if unresolved_only:
        query = query.where(Notification.resolved_at.is_(None))
    return int(session.scalar(query) or 0)


def _pipeline_retry_count(session: Session, run_ids: list[UUID]) -> int:
    if not run_ids:
        return 0
    return int(session.scalar(select(func.coalesce(func.sum(PipelineRunStep.retry_count), 0)).where(PipelineRunStep.run_id.in_(run_ids))) or 0)


def _no_answer_rate(session: Session, project_ids: set[UUID], date_from: datetime | None, date_to: datetime | None) -> float:
    query = _chat_filters(
        select(
            func.count(ChatRecord.id).label("total"),
            func.sum(
                case((ChatRecord.answer.like("無法確認%"), 1), else_=0)
            ).label("no_answer"),
        ),
        project_ids,
        date_from,
        date_to,
    )
    row = session.execute(query).one()
    return _rate(int(row.no_answer or 0), int(row.total or 0))


def _validation_pass_rate(session: Session, project_ids: set[UUID], date_from: datetime | None, date_to: datetime | None) -> float:
    query = _project_date_filters(
        select(
            func.count(ValidationRun.id).label("total"),
            func.sum(
                case((ValidationRun.status == "completed", 1), else_=0)
            ).label("completed"),
        ),
        ValidationRun,
        ValidationRun.created_at,
        project_ids,
        date_from,
        date_to,
    )
    row = session.execute(query).one()
    return _rate(int(row.completed or 0), int(row.total or 0))


def _human_correct_rate(session: Session, project_ids: set[UUID], date_from: datetime | None, date_to: datetime | None) -> float:
    query = _chat_filters(
        select(
            func.sum(
                case(
                    (ChatRecord.evaluation != "not_evaluated", 1),
                    else_=0,
                )
            ).label("evaluated"),
            func.sum(
                case((ChatRecord.evaluation == "correct", 1), else_=0)
            ).label("correct"),
        ),
        project_ids,
        date_from,
        date_to,
    )
    row = session.execute(query).one()
    return _rate(int(row.correct or 0), int(row.evaluated or 0))


def _alert_level(items: list[Notification]) -> str:
    if any(item.severity in {"critical", "high"} for item in items):
        return "high"
    if any(item.severity == "medium" for item in items):
        return "medium"
    return "low"


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _localized_headers(locale: str, columns: list[str]) -> list[str]:
    labels = HEADER_LABELS["en" if locale.lower().startswith("en") else "zh"]
    return [labels.get(column, column) for column in columns]


def _csv_value(value) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _report_csv_row(values: list) -> str:
    output = io.StringIO()
    csv.writer(output, lineterminator="\r\n").writerow(values)
    return output.getvalue()


def _report_filename(topic: str, date_from: datetime | None, date_to: datetime | None) -> str:
    start = date_from.date().isoformat() if date_from else "all"
    end = date_to.date().isoformat() if date_to else "all"
    return f"nomosmart_{topic}_{start}_{end}.csv"

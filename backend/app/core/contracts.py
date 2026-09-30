from __future__ import annotations

from enum import StrEnum


class StableErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    HTTP_ERROR = "http_error"
    PERMISSION_DENIED = "permission_denied"
    PROJECT_SCOPE_DENIED = "project_scope_denied"
    IDEMPOTENCY_KEY_REQUIRED = "idempotency_key_required"
    IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
    IDEMPOTENCY_KEY_IN_PROGRESS = "idempotency_key_in_progress"
    IDEMPOTENCY_KEY_EXPIRED = "idempotency_key_expired"


STABLE_ERROR_STATUS: dict[StableErrorCode, int] = {
    StableErrorCode.VALIDATION_ERROR: 422,
    StableErrorCode.NOT_FOUND: 404,
    StableErrorCode.HTTP_ERROR: 400,
    StableErrorCode.PERMISSION_DENIED: 403,
    StableErrorCode.PROJECT_SCOPE_DENIED: 403,
    StableErrorCode.IDEMPOTENCY_KEY_REQUIRED: 422,
    StableErrorCode.IDEMPOTENCY_KEY_CONFLICT: 409,
    StableErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS: 409,
    StableErrorCode.IDEMPOTENCY_KEY_EXPIRED: 409,
}


class AuditAction(StrEnum):
    REPORT_CSV_EXPORT = "report.csv.export"
    PROJECT_ARCHIVE_REQUESTED = "project.archive.requested"
    PROJECT_ARCHIVE_COMPLETED = "project.archive.cleanup.completed"
    PROJECT_ARCHIVE_FAILED = "project.archive.cleanup.failed"
    NOTIFICATION_PRODUCED = "notification.produced"
    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_REEXTRACT = "document.reextract"
    DOCUMENT_SWITCH_ACTIVE = "document_version.switch_active"
    CHUNK_EDIT = "knowledge.chunk.edit"
    GRAPH_QUERY = "knowledge_graph.query"
    GRAPH_SYNC_RETRY = "graph_sync.retry"
    CHAT_QUERY = "project_chat.query"
    VALIDATION_RUN_CREATE = "validation_run.create"
    REVIEW_SUBMIT = "approval.submit"
    REVIEW_APPROVE = "approval.approve"
    REVIEW_REJECT = "approval.reject"
    INTEGRATION_CLIENT_CREATE = "integration_client.create"
    INTEGRATION_CLIENT_ROTATE = "integration_client.key.rotate"
    RUNTIME_SECRET_REFERENCE_DENIED = "runtime_secret.reference.denied"
    RUNTIME_SECRET_RESOLUTION_FAILED = "runtime_secret.resolution.failed"


class IdempotencyState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


IDEMPOTENCY_TRANSITIONS: dict[IdempotencyState, frozenset[IdempotencyState]] = {
    IdempotencyState.PENDING: frozenset(
        {IdempotencyState.PROCESSING, IdempotencyState.CANCELLED, IdempotencyState.EXPIRED}
    ),
    IdempotencyState.PROCESSING: frozenset(
        {
            IdempotencyState.SUCCEEDED,
            IdempotencyState.FAILED,
            IdempotencyState.CANCELLED,
            IdempotencyState.EXPIRED,
        }
    ),
    IdempotencyState.SUCCEEDED: frozenset(),
    IdempotencyState.FAILED: frozenset({IdempotencyState.PROCESSING, IdempotencyState.EXPIRED}),
    IdempotencyState.CANCELLED: frozenset(),
    IdempotencyState.EXPIRED: frozenset(),
}


class ProjectCapability(StrEnum):
    UPLOAD = "can_upload"
    UPDATE_SOURCE = "can_update_source"
    START_EXTRACTION = "can_start_extraction"
    REEXTRACT = "can_reextract"
    EDIT_CHUNKS = "can_edit_chunks"
    CREATE_REFERENCE = "can_create_reference"
    SYNC_SOURCE = "can_sync_source"
    VIEW_GRAPH = "can_view_graph"
    SUBMIT_REVIEW = "can_submit_review"
    MANAGE_LIFECYCLE = "can_manage_lifecycle"
    ARCHIVE_PROJECT = "can_archive_project"
    RETRY_ARCHIVE_CLEANUP = "can_retry_archive_cleanup"


PROJECT_CAPABILITY_KEYS = tuple(capability.value for capability in ProjectCapability)


def empty_project_capabilities() -> dict[str, bool]:
    return {capability: False for capability in PROJECT_CAPABILITY_KEYS}

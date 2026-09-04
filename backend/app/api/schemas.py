from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserSummary(ORMModel):
    id: UUID
    employee_id: str | None
    keycloak_user_id: str
    email: str | None
    given_name: str | None
    family_name: str | None
    display_name: str
    department: str | None
    title: str | None
    auth_source: str
    is_active: bool
    knowledge_owner: bool = False
    system_notes: str | None = None
    last_synced_at: datetime | None


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserLocalUpdate(BaseModel):
    manager_delegate_user_id: UUID | None = None
    manager_delegate_start_at: datetime | None = None
    manager_delegate_end_at: datetime | None = None
    knowledge_owner: bool | None = None
    system_notes: str | None = Field(default=None, max_length=4000)


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class RoleUpdate(BaseModel):
    lock_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class RoleResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    is_active: bool
    is_system: bool
    lock_version: int = 1


class PermissionValue(BaseModel):
    module_name: str
    function_name: str
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_execute: bool = False


class PermissionMatrixUpdate(BaseModel):
    lock_version: int = Field(ge=1)
    permissions: list[PermissionValue]


class PermissionMatrixResponse(BaseModel):
    lock_version: int
    permissions: list[PermissionValue]


class RoleUsersUpdate(BaseModel):
    lock_version: int = Field(ge=1)
    user_ids: list[UUID]


class RoleUserResponse(BaseModel):
    user_id: UUID
    source: str


class RoleUsersResponse(BaseModel):
    lock_version: int
    users: list[RoleUserResponse]


class ProjectMemberInput(BaseModel):
    user_id: UUID
    roles: list[str]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    llm_model_id: UUID | None = None
    embedding_model_id: UUID | None = None
    ocr_model_id: UUID | None = None
    members: list[ProjectMemberInput] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    llm_model_id: UUID | None = None
    embedding_model_id: UUID | None = None
    ocr_model_id: UUID | None = None
    lock_version: int = Field(ge=1)


class ProjectMemberUpdate(BaseModel):
    roles: list[str]
    lock_version: int = Field(ge=1)


class ProjectMemberResponse(BaseModel):
    user_id: UUID
    given_name: str | None = None
    family_name: str | None = None
    display_name: str
    email: str | None
    roles: list[str]


class ProjectMemberCandidate(BaseModel):
    id: UUID
    employee_id: str | None = None
    email: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    display_name: str
    is_active: bool


class ProjectMemberCandidatePage(BaseModel):
    items: list[ProjectMemberCandidate]
    total: int
    offset: int
    limit: int
    ineligible_match_count: int


class ProjectResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    status: str
    llm_model_id: UUID | None
    embedding_model_id: UUID | None
    ocr_model_id: UUID | None
    lock_version: int
    archived_at: datetime | None = None
    archived_by: UUID | None = None
    archive_cleanup_status: str | None = None
    is_owner: bool = False
    current_user_project_roles: list[str] = Field(default_factory=list)
    document_count: int = 0
    published_version_count: int = 0
    last_activity_at: datetime | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class ProjectArchiveImpactResponse(BaseModel):
    project_id: UUID
    project_name: str
    lock_version: int
    completed_document_count: int
    completed_version_count: int
    unfinished_version_count: int
    unfinished_document_count: int
    deleted_document_count: int
    unfinished_file_count: int
    unfinished_pipeline_count: int
    unfinished_sync_count: int
    unfinished_validation_count: int
    unfinished_approval_count: int
    unfinished_staging_index_count: int
    unfinished_embedding_build_count: int
    unfinished_graph_count: int


class ProjectArchiveRequest(BaseModel):
    lock_version: int = Field(ge=1)
    confirmation_name: str = Field(min_length=1, max_length=255)


class PipelineSummary(BaseModel):
    id: UUID | None = None
    status: str
    progress_percent: float
    current_step_name: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None


class PipelineStepSummary(BaseModel):
    id: UUID
    step_name: str
    status: str
    progress_percent: float
    progress_message: str | None = None
    retry_count: int
    output_artifact_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class PipelineRunDetail(PipelineSummary):
    project_id: UUID
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    run_type: str
    started_at: datetime | None = None
    steps: list[PipelineStepSummary] = Field(default_factory=list)


class RetryPipelineStepPayload(BaseModel):
    step_name: str = Field(min_length=1, max_length=100)


class DocumentVersionSummary(BaseModel):
    id: UUID
    version_label: str
    status: str
    original_file_name: str | None
    canonical_extension: str | None
    mime_type: str | None
    file_size: int | None
    storage_bucket: str | None
    storage_key: str | None
    ocr_model_id: UUID | None
    ocr_config_version: int | None
    lock_version: int = 1
    created_at: datetime
    updated_at: datetime


class DocumentServiceSourceSummary(BaseModel):
    data_source_id: UUID
    service_type: str
    location: str
    schedule_mode: str
    cron_expression: str | None = None
    timezone: str | None = None


class DocumentReferenceSourceSummary(BaseModel):
    reference_id: UUID | None = None
    source_project_id: UUID
    source_document_id: UUID
    source_version_id: UUID
    project_name: str
    document_name: str
    snapshot_version: str
    latest_active_version: str | None = None
    has_access: bool = False
    status: str
    detected_at: datetime | None = None
    pending_event_count: int = 0


class DocumentSummary(BaseModel):
    id: UUID
    project_id: UUID
    document_code: str
    title: str
    source_type: str
    status: str
    created_by: UUID | None
    lock_version: int
    created_at: datetime
    updated_at: datetime
    latest_version: DocumentVersionSummary | None = None
    versions: list[DocumentVersionSummary] = Field(default_factory=list)
    latest_pipeline: PipelineSummary | None = None
    service_source: DocumentServiceSourceSummary | None = None
    reference_source: DocumentReferenceSourceSummary | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class DocumentUploadResult(BaseModel):
    index: int
    filename: str
    status: Literal["success", "failed"]
    document: DocumentSummary | None = None
    started_extraction: bool = False
    error_code: str | None = None
    message: str | None = None


class DocumentUploadResponse(BaseModel):
    request_id: str
    success_count: int
    failed_count: int
    results: list[DocumentUploadResult]


class DocumentUpdateResponse(BaseModel):
    document: DocumentSummary
    latest_pipeline: PipelineSummary | None = None
    no_change: bool = False
    message: str | None = None


class DocumentReextractPayload(BaseModel):
    source_version_id: UUID
    source_content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    lock_version: int = Field(ge=1)
    ocr_model_id: UUID | None = None
    force_ocr: bool = False


class DocumentReextractResponse(BaseModel):
    document_id: UUID
    source_version_id: UUID
    document_version_id: UUID
    version_label: str
    pipeline_run_id: UUID
    status: str


class DataSourceConnectionPayload(BaseModel):
    service_type: Literal["FTP", "FTPS", "SFTP", "S3", "HTTP_API"]
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(default="", max_length=500)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    credential: str | None = Field(default=None, max_length=8000)
    credential_secret_ref: str | None = Field(default=None, max_length=1000)
    bucket: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=100)
    remote_path: str = Field(default="", max_length=2000)
    file_name: str = Field(min_length=1, max_length=255)
    schedule_mode: Literal["once", "cron"] = "once"
    cron_expression: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="Asia/Taipei", min_length=1, max_length=100)
    verify_tls: bool = True
    verify_host_key: bool = True
    url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    auth_mode: Literal["none", "bearer", "api_key_header"] = "none"
    api_key_header_name: str | None = Field(default=None, max_length=100)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_bytes: int | None = Field(default=None, ge=1)


class DataSourceConnectionTestResponse(BaseModel):
    status: Literal["success", "configuration_valid", "unavailable", "failed"]
    detail_code: str
    message: str
    credential_configured: bool
    fingerprint: str | None = None
    latency_ms: int | None = None
    tested_at: datetime | None = None


class DataSourceResponse(ORMModel):
    id: UUID
    project_id: UUID
    service_type: str
    name: str
    connection_metadata: dict[str, Any]
    source_identity: dict[str, Any]
    schedule_mode: str
    cron_expression: str | None
    timezone: str
    enabled: bool
    last_sync_status: str | None
    last_synced_at: datetime | None
    next_run_at: datetime | None
    lock_version: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    credential_configured: bool = False
    last_test_status: str | None = None
    last_tested_at: datetime | None = None
    last_test_fingerprint: str | None = None
    last_test_latency_ms: int | None = None
    last_test_detail_code: str | None = None
    last_test_actor_id: UUID | None = None


class DataSyncRunResponse(ORMModel):
    id: UUID
    data_connection_id: UUID
    document_id: UUID
    trigger_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    content_fingerprint: str | None
    remote_metadata: dict[str, Any]
    document_version_id: UUID | None
    error_code: str | None
    error_summary: str | None
    retry_count: int
    created_at: datetime


class DataSourceCreateResponse(BaseModel):
    data_source: DataSourceResponse
    document: DocumentSummary
    sync_run: DataSyncRunResponse


class StartExtractionPayload(BaseModel):
    ocr_model_id: UUID | None = None
    force_ocr: bool = False


class StartExtractionResponse(BaseModel):
    document: DocumentSummary
    pipeline: PipelineSummary


class SubmitReviewPayload(BaseModel):
    evidence_revision: str = Field(min_length=64, max_length=64)
    lock_version: int = Field(ge=1)
    owner_user_id: UUID | None = None


class ApprovalDecisionPayload(BaseModel):
    lock_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=4000)


class ApprovalRejectPayload(ApprovalDecisionPayload):
    comment: str = Field(min_length=1, max_length=4000)


class PublishVersionPayload(BaseModel):
    lock_version: int = Field(ge=1)
    impact_confirmed: bool = True


class SwitchActiveVersionPayload(BaseModel):
    lock_version: int = Field(ge=1)
    impact_confirmed: bool
    audit_reason: str = Field(min_length=1, max_length=1000)


class LifecycleUpdatePayload(BaseModel):
    lock_version: int = Field(ge=1)
    status: str
    impact_confirmed: bool = False
    reason: str | None = Field(default=None, max_length=1000)


class LifecycleImpactResponse(BaseModel):
    document_id: UUID
    requested_status: str
    impacted_reference_count: int
    impacted_active_version_count: int
    requires_confirmation: bool


class DocumentReferenceCreatePayload(BaseModel):
    source_document_id: UUID
    source_version_id: UUID | None = None
    reference_mode: Literal["linked", "detached"] = "linked"


class ReferenceSourceVersionResponse(BaseModel):
    id: UUID
    version_label: str
    status: str
    is_active: bool
    created_at: datetime


class ReferenceExistingTargetResponse(BaseModel):
    target_document_id: UUID
    target_title: str
    source_version_label: str


class ReferenceSourceDocumentResponse(BaseModel):
    id: UUID
    title: str
    owner: str | None = None
    versions: list[ReferenceSourceVersionResponse] = Field(default_factory=list)
    duplicate: ReferenceExistingTargetResponse | None = None


class ReferenceSourceProjectResponse(BaseModel):
    id: UUID
    name: str
    status: str
    documents: list[ReferenceSourceDocumentResponse] = Field(default_factory=list)


class DocumentReferenceImportItemPayload(BaseModel):
    source_document_id: UUID
    source_version_id: UUID
    old_version_confirmed: bool = False


class DocumentReferenceImportPayload(BaseModel):
    mode: Literal["reference", "copy"] = "reference"
    items: list[DocumentReferenceImportItemPayload] = Field(min_length=1, max_length=20)


class DocumentReferenceImportResult(BaseModel):
    status: Literal["created", "skipped", "failed"]
    document: DocumentSummary | None = None
    reference: DocumentReferenceResponse | None = None
    error_code: str | None = None
    message: str | None = None


class DocumentReferenceImportResponse(BaseModel):
    results: list[DocumentReferenceImportResult]


class DocumentReferenceUpdatePayload(BaseModel):
    source_version_id: UUID
    old_version_confirmed: bool = False


class DocumentReferenceResponse(ORMModel):
    id: UUID
    target_project_id: UUID
    target_document_id: UUID
    source_project_id: UUID
    source_document_id: UUID
    source_version_id: UUID
    source_project_name_snapshot: str
    source_document_name_snapshot: str
    reference_mode: str
    status: str
    created_by: UUID | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentReferenceEventResponse(ORMModel):
    id: UUID
    reference_id: UUID
    event_type: str
    source_project_id: UUID
    source_document_id: UUID
    old_source_version_id: UUID | None
    new_source_version_id: UUID | None
    message: str
    is_read: bool
    resolved_at: datetime | None
    created_at: datetime


class ImpactedReferenceProject(BaseModel):
    target_project_id: UUID
    reference_count: int


class ImpactedReferenceProjectsResponse(BaseModel):
    source_document_id: UUID
    projects: list[ImpactedReferenceProject]


class ReviewRecordResponse(ORMModel):
    id: UUID
    review_stage: str
    reviewer_id: UUID
    delegated_from_user_id: UUID | None
    status: str
    comment: str | None
    created_at: datetime


class ApprovalChunkEvidence(BaseModel):
    id: UUID
    chunk_index: int
    title: str | None
    content: str
    markdown_content: str | None
    display_markdown: str | None = None
    retrieval_text: str | None = None
    embedding_content_hash: str | None = None
    content_type: str
    heading_path: list[str] = Field(default_factory=list)
    heading_level: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    sequence: int | None = None
    stable_chunk_key: str | None = None
    source_mapping: list
    token_count: int | None
    confidence_score: float | None
    lineage_id: UUID
    parent_chunk_id: UUID | None = None
    revision: int = 0
    change_type: str = "generated"
    tags: list[str] = Field(default_factory=list)
    tag_details: list["KnowledgeTagResponse"] = Field(default_factory=list)


class ProcessingDebugNode(BaseModel):
    id: str
    type: str
    text: str
    markdown: str
    start_offset: int
    end_offset: int
    sequence: int
    heading_path: list[str] = Field(default_factory=list)
    heading_level: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessingDebugChunk(BaseModel):
    id: UUID
    chunk_index: int
    sequence: int | None = None
    stable_chunk_key: str | None = None
    raw_markdown: str | None = None
    display_markdown: str | None = None
    display_text: str
    retrieval_text: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    token_count: int | None = None
    embedding_content_hash: str | None = None
    source_mapping: list[Any] = Field(default_factory=list)
    processing_metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessingDebugResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    markdown_artifact_status: str
    raw_markdown: str | None = None
    parser_version: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[ProcessingDebugNode] = Field(default_factory=list)
    chunks: list[ProcessingDebugChunk] = Field(default_factory=list)
    processing_versions: dict[str, Any] = Field(default_factory=dict)


class KnowledgeTagResponse(BaseModel):
    tag_id: UUID
    tag_text: str
    source: str
    confidence_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime


class ManualChunkCreatePayload(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    view_mode: Literal["original", "markdown"]
    source_anchor: str = Field(min_length=1, max_length=500)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    offset_unit: Literal["unicode_code_point"] | None = None
    offset_scope: Literal["canonical_markdown", "source_anchor"] | None = None
    lock_version: int = Field(ge=1)


class ChunkEditPayload(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    markdown_content: str | None = Field(default=None, max_length=50000)
    title: str | None = Field(default=None, max_length=500)
    source_mapping: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    lock_version: int = Field(ge=1)


class KnowledgeTagCreatePayload(BaseModel):
    tag_text: str = Field(min_length=1, max_length=80)


class KnowledgeAutoTagPayload(BaseModel):
    max_tags: int = Field(default=5, ge=1, le=12)


class ApprovalChatEvidence(BaseModel):
    id: UUID
    conversation_id: UUID
    conversation_title: str | None = None
    scope_mode: str | None = None
    document_version_id: UUID | None = None
    selected_document_version_ids: list[UUID] = Field(default_factory=list)
    question: str
    answer: str | None
    reference_docs: list[dict[str, Any]]
    evaluation: str
    revision_suggestion: str | None = None
    created_by: UUID
    asked_at: datetime
    answered_at: datetime | None


class ApprovalTaskResponse(ORMModel):
    id: UUID
    approval_request_id: UUID
    project_id: UUID
    project_name: str | None = None
    document_id: UUID
    document_title: str | None = None
    document_version_id: UUID
    version_label: str | None = None
    submitter_id: UUID
    submitter_given_name: str | None = None
    submitter_family_name: str | None = None
    submitter_name: str | None = None
    submitter_email: str | None = None
    priority: str = "normal"
    source_type: str | None = None
    assignee_user_id: UUID | None
    review_stage: str
    status: str
    lock_version: int
    submitted_at: datetime
    completed_at: datetime | None
    created_at: datetime


class ApprovalRequestResponse(ORMModel):
    id: UUID
    project_id: UUID
    project_name: str | None = None
    document_id: UUID
    document_title: str | None = None
    document_version_id: UUID
    version_label: str | None = None
    submitter_id: UUID
    submitter_given_name: str | None = None
    submitter_family_name: str | None = None
    submitter_name: str | None = None
    submitter_email: str | None = None
    owner_user_id: UUID | None
    evidence_revision: str | None = None
    priority: str = "normal"
    source_type: str | None = None
    status: str
    current_task_id: UUID | None
    submitted_at: datetime
    approved_at: datetime | None
    published_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


class ApprovalTaskPage(BaseModel):
    items: list[ApprovalTaskResponse]
    next_cursor: str | None = None


class ApprovalRequestPage(BaseModel):
    items: list[ApprovalRequestResponse]
    next_cursor: str | None = None


class ApprovalPendingPublishResponse(BaseModel):
    approval_request_id: UUID | None = None
    approval_task_id: UUID | None = None
    project_id: UUID
    project_name: str | None = None
    document_id: UUID
    document_title: str | None = None
    document_version_id: UUID
    version_label: str | None = None
    version_status: str
    lock_version: int
    submitter_id: UUID | None = None
    submitter_given_name: str | None = None
    submitter_family_name: str | None = None
    submitter_name: str | None = None
    submitter_email: str | None = None
    approved_at: datetime | None = None


class ApprovalTaskDetail(BaseModel):
    task: ApprovalTaskResponse
    request: ApprovalRequestResponse
    document: DocumentSummary
    version: DocumentVersionSummary
    latest_version_id: UUID
    evidence_stale: bool = False
    read_only: bool = False
    read_only_reason: str | None = None
    evidence_revision: str | None = None
    evidence_generated_at: datetime | None = None
    evidence_verifiable: bool = False
    evidence_manifest: dict[str, Any] | None = None
    original_file: "OriginalFileViewerMetadata | None" = None
    document_layout: "DocumentLayoutArtifact | None" = None
    source_text: str | None = None
    markdown_text: str | None = None
    markdown_artifact_status: Literal["available", "processing", "missing", "failed", "invalid"] = "missing"
    markdown_artifact_reason_code: str | None = None
    source_mapping_available: bool = False
    markdown_available_count: int = 0
    missing_markdown_count: int = 0
    document_tags: list[KnowledgeTagResponse] = Field(default_factory=list)
    review_records: list[ReviewRecordResponse] = Field(default_factory=list)
    chunks: list[ApprovalChunkEvidence] = Field(default_factory=list)
    chat_records: list[ApprovalChatEvidence] = Field(default_factory=list)


class KnowledgeDetailResponse(BaseModel):
    document: DocumentSummary
    version: DocumentVersionSummary
    pipeline: PipelineRunDetail | None = None
    original_file: "OriginalFileViewerMetadata | None" = None
    document_layout: "DocumentLayoutArtifact | None" = None
    source_text: str | None = None
    markdown_text: str | None = None
    markdown_artifact_status: Literal["available", "processing", "missing", "failed", "invalid"] = "missing"
    markdown_artifact_reason_code: str | None = None
    source_mapping_available: bool = False
    markdown_available_count: int = 0
    missing_markdown_count: int = 0
    manual_edit_enabled: bool = False
    manual_edit_reason: str | None = None
    active_chunk_count: int = 0
    chunk_artifact_status: Literal["ready", "queued", "running", "failed", "chunks_required"] = "chunks_required"
    next_stage_allowed: bool = False
    next_stage_block_reason: str | None = None
    document_tags: list[KnowledgeTagResponse] = Field(default_factory=list)
    chunks: list[ApprovalChunkEvidence] = Field(default_factory=list)


class SubmissionEvidenceActor(BaseModel):
    user_id: UUID
    given_name: str | None = None
    family_name: str | None = None
    display_name: str
    email: str | None = None
    department: str | None = None
    title: str | None = None


class SubmissionEvidenceResponse(BaseModel):
    detail: KnowledgeDetailResponse
    evidence_revision: str
    lock_version: int
    generated_at: datetime
    next_stage_allowed: bool
    block_reasons: list[str] = Field(default_factory=list)
    can_submit_review: bool
    creator: SubmissionEvidenceActor | None = None
    manager: SubmissionEvidenceActor | None = None
    owners: list[SubmissionEvidenceActor] = Field(default_factory=list)
    models: dict[str, dict[str, Any]] = Field(default_factory=dict)
    content_type_counts: dict[str, int] = Field(default_factory=dict)
    chunk_count: int = 0
    tag_count: int = 0
    average_confidence: float | None = None
    graph: dict[str, Any] = Field(default_factory=dict)
    chat_records: list[ApprovalChatEvidence] = Field(default_factory=list)
    validation_runs: list[dict[str, Any]] = Field(default_factory=list)


class OriginalFileViewerMetadata(BaseModel):
    original_file_name: str | None = None
    extension: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    viewer_type: Literal["download_only", "markdown", "unsupported"]
    preview_status: Literal["available", "pending", "unavailable", "failed"]
    preview_error_code: str | None = None
    original_url: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    markdown_source_mode: Literal["rendered_original_raw_markdown", "pipeline_markdown"] = "pipeline_markdown"


class DocumentLayoutBox(BaseModel):
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class DocumentLayoutListItem(BaseModel):
    text: str
    inline_markdown: str | None = None
    value: int | None = None
    children: list["DocumentLayoutListItem"] = Field(default_factory=list)
    child_lists: list["DocumentLayoutNestedList"] = Field(default_factory=list)
    continuation: bool = False


class DocumentLayoutNestedList(BaseModel):
    ordered: bool = False
    start: int = 1
    items: list[DocumentLayoutListItem] = Field(default_factory=list)


class DocumentLayoutBlock(BaseModel):
    id: str
    type: Literal["heading", "paragraph", "list", "table", "image", "caption", "code", "blockquote", "horizontal_rule", "unknown"] = "paragraph"
    source_anchor: str | None = None
    text: str | None = None
    inline_markdown: str | None = None
    level: int | None = None
    items: list[str] = Field(default_factory=list)
    list_ordered: bool | None = None
    list_start: int | None = None
    list_items: list[DocumentLayoutListItem] = Field(default_factory=list)
    table_header: list[str] = Field(default_factory=list)
    table_header_markdown: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    rows_markdown: list[list[str]] = Field(default_factory=list)
    caption: str | None = None
    caption_markdown: str | None = None
    image_source: str | None = None
    code_language: str | None = None
    confidence: float | None = None
    bbox: DocumentLayoutBox | None = None
    continuation_of: str | None = None
    continuation_index: int | None = None
    continuation_count: int | None = None
    source_start_offset: int | None = None
    source_end_offset: int | None = None
    continuation_text_start: int | None = None
    continuation_text_end: int | None = None


class DocumentLayoutPage(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    blocks: list[DocumentLayoutBlock] = Field(default_factory=list)


class DocumentLayoutArtifact(BaseModel):
    status: Literal["available", "partial", "missing", "failed"]
    reason_code: str | None = None
    source: str | None = None
    layout_version: str | None = None
    pagination: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[DocumentLayoutPage] = Field(default_factory=list)


class ApprovalSummary(BaseModel):
    pending_total: int
    pending_manager_review: int
    pending_owner_review: int
    my_submissions: int


class PublishResult(BaseModel):
    document_version_id: UUID
    status: str
    active_manifest_id: UUID
    publication_generation: int
    opensearch_index: str
    graph_sync_job_id: UUID


class ProjectGraphNode(BaseModel):
    id: str
    type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str


class ProjectGraphResponse(BaseModel):
    project_id: UUID | None = None
    nodes: list[ProjectGraphNode]
    edges: list[ProjectGraphEdge]
    truncated: bool = False
    node_limit: int = 120


class ProjectServingDocumentStatus(BaseModel):
    document_id: UUID
    document_title: str
    document_version_id: UUID
    version_label: str
    publication_generation: int
    chunk_count: int = 0
    index_ready: bool
    graph_sync_status: str | None = None
    graph_node_count: int | None = None
    graph_edge_count: int | None = None


class ProjectServingStatusResponse(BaseModel):
    project_id: UUID
    readiness: Literal["ready", "empty", "partial"]
    active_document_count: int
    ready_index_count: int
    graph_ready_count: int
    documents: list[ProjectServingDocumentStatus] = Field(default_factory=list)


class ProjectChatQueryPayload(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_version_ids: list[UUID] | None = None
    scope_mode: Literal["published", "document_staging"]
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: UUID | None = None
    conversation_title: str | None = Field(default=None, max_length=500)


class ProjectChatCitation(BaseModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    chunk_index: int | None = None
    title: str | None = None
    score: float | None = None
    excerpt: str | None = None
    content_type: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = None
    source_mapping: list[Any] = Field(default_factory=list)
    index_name: str | None = None
    display_markdown: str | None = None
    generation_text: str | None = Field(default=None, exclude=True)
    raw_markdown: str | None = Field(default=None, exclude=True)


class ProjectChatQueryResponse(BaseModel):
    chat_record_id: UUID | None = None
    conversation_id: UUID | None = None
    conversation_title: str | None = None
    answer: str
    citations: list[ProjectChatCitation]
    manifest_version_ids: list[UUID]
    selected_version_ids: list[UUID] = Field(default_factory=list)
    status: Literal["answered", "no_answer"] = "answered"
    retrieval_strategy: Literal["keyword", "vector", "hybrid"] = "keyword"
    prompt_version: str | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None
    llm_model_id: UUID | None = None
    token_usage: dict[str, Any] | None = None
    latency_ms: int | None = None


class ProjectChatRecordResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    conversation_title: str | None = None
    scope_mode: Literal["published", "document_staging"] | None = None
    selected_document_version_ids: list[UUID] = Field(default_factory=list)
    question: str
    answer: str | None = None
    citations: list[ProjectChatCitation] = Field(default_factory=list)
    evaluation: Literal["correct", "needs_revision", "not_evaluated"] = "not_evaluated"
    revision_suggestion: str | None = None
    llm_model_id: UUID | None = None
    prompt_version: str | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None
    token_usage: dict[str, Any] | None = None
    latency_ms: int | None = None
    asked_at: datetime
    answered_at: datetime | None = None


class ProjectChatConversationResponse(BaseModel):
    id: UUID
    title: str
    scope_mode: Literal["published", "document_staging"] | None = None
    selected_document_version_ids: list[UUID]
    message_count: int
    updated_at: datetime
    can_continue: bool = True
    records: list[ProjectChatRecordResponse] = Field(default_factory=list)


class ProjectChatConversationPage(BaseModel):
    items: list[ProjectChatConversationResponse]
    next_cursor: str | None = None


class ProjectChatConversationDeleteResponse(BaseModel):
    conversation_id: UUID
    deleted_count: int
    deleted_at: datetime


class ProjectChatFeedbackPayload(BaseModel):
    evaluation: Literal["correct", "needs_revision", "not_evaluated"]
    revision_suggestion: str | None = Field(default=None, max_length=4000)


class IntegrationClientCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_ids: list[UUID] = Field(default_factory=list)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_department: str | None = Field(default=None, max_length=255)
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    requests_per_minute: int | None = Field(default=60, ge=1, le=10000)


class IntegrationClientUpdatePayload(BaseModel):
    lock_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_department: str | None = Field(default=None, max_length=255)
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    requests_per_minute: int | None = Field(default=None, ge=1, le=10000)


class IntegrationClientLifecyclePayload(BaseModel):
    lock_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class IntegrationClientProjectScopesPayload(BaseModel):
    lock_version: int = Field(ge=1)
    project_ids: list[UUID] = Field(default_factory=list)


class IntegrationClientResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    status: str
    effective_status: str
    api_key_prefix: str
    api_key_version: int
    contact_name: str | None
    contact_email: str | None
    contact_department: str | None
    valid_from: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    requests_per_minute: int | None = None
    project_ids: list[UUID] = Field(default_factory=list)
    last_used_at: datetime | None
    last_used_project_id: UUID | None
    success_count: int
    failure_count: int
    lock_version: int
    created_at: datetime
    updated_at: datetime


class IntegrationClientCreateResponse(IntegrationClientResponse):
    api_key: str


class IntegrationClientPage(BaseModel):
    items: list[IntegrationClientResponse]
    next_cursor: str | None = None


class IntegrationClientUsageItem(BaseModel):
    id: UUID
    project_id: UUID
    result: str
    http_status: int
    response_mode: str
    end_user_employee_id: str
    retrieval_status: str | None
    latency_ms: int | None
    error_code: str | None
    created_at: datetime


class IntegrationClientUsageSummary(BaseModel):
    client_id: UUID
    success_count: int
    failure_count: int
    last_used_at: datetime | None
    recent_requests: list[IntegrationClientUsageItem] = Field(default_factory=list)


class PublicApiEndUser(BaseModel):
    employee_id: str = Field(min_length=1, max_length=100)
    employee_name: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)


class PublicApiChatScope(BaseModel):
    document_ids: list[UUID] | None = None


class PublicApiChatPayload(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    end_user: PublicApiEndUser
    scope: PublicApiChatScope | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class PublicApiChatCitation(BaseModel):
    """Stable public citation shape; internal canonical indexes stay private."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str | None = None
    score: float | None = None
    excerpt: str | None = None
    content_type: str | None = None
    page: int | None = None
    source_mapping: list[Any] = Field(default_factory=list)
    index_name: str | None = None


class PublicApiChatResponse(BaseModel):
    response_id: UUID
    answer: str
    citations: list[PublicApiChatCitation]
    status: Literal["answered", "no_answer"] = "answered"
    retrieval_strategy: Literal["keyword", "vector", "hybrid"] = "hybrid"
    selected_document_ids: list[UUID] = Field(default_factory=list)
    selected_document_version_ids: list[UUID] = Field(default_factory=list)
    prompt_version: str | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None
    llm_model_id: UUID | None = None
    token_usage: dict[str, Any] | None = None
    latency_ms: int | None = None
    request_id: str | None = None


class PublicApiFeedbackPayload(BaseModel):
    feedback: Literal["good", "bad"]
    comment: str | None = Field(default=None, max_length=4000)
    end_user: PublicApiEndUser


class PublicApiFeedbackResponse(BaseModel):
    feedback_event_id: UUID
    response_id: UUID
    latest_feedback: Literal["good", "bad"]
    comment: str | None
    created_at: datetime


class ValidationRunQuestionPayload(BaseModel):
    input_item_id: UUID | None = None
    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    selected_document_ids: list[UUID] | None = None
    category: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, max_length=32)


class ValidationRunCreatePayload(BaseModel):
    uploaded_file_name: str | None = Field(default=None, max_length=255)
    scope_mode: Literal["published", "document_staging"]
    selected_document_version_ids: list[UUID] | None = None
    questions: list[ValidationRunQuestionPayload] = Field(min_length=1)


class ValidationRunItemResponse(BaseModel):
    id: UUID
    parent_item_id: UUID | None = None
    attempt: int = 1
    is_current: bool = True
    input_item_id: UUID
    input_ordinal: int
    input_content_hash: str
    question: str
    expected_answer: str | None = None
    expected_keywords: list[str] | None = None
    selected_document_ids: list[UUID] = Field(default_factory=list)
    category: str | None = None
    priority: str | None = None
    answer: str | None = None
    citations: list[ProjectChatCitation] = Field(default_factory=list)
    chat_record_id: UUID | None = None
    status: Literal["pending", "running", "passed", "failed", "needs_review", "error", "completed", "skipped", "cancelled"]
    score: float | None = None
    evaluation_reason: str | None = None
    error_message: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None


class ValidationRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    uploaded_file_name: str | None = None
    status: Literal["queued", "running", "completed", "partial_failed", "failed", "cancelled"]
    run_scope: str
    selected_document_ids: list[UUID] = Field(default_factory=list)
    execution_manifest: dict[str, Any] = Field(default_factory=dict)
    execution_manifest_hash: str
    max_attempts: int
    total_count: int
    completed_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    items: list[ValidationRunItemResponse] = Field(default_factory=list)


class ValidationRunPage(BaseModel):
    items: list[ValidationRunResponse]
    next_cursor: str | None = None


class ValidationRunItemPage(BaseModel):
    items: list[ValidationRunItemResponse]
    next_cursor: str | None = None


class ValidationCancellationResponse(BaseModel):
    validation_run_id: UUID
    status: str
    cancelled_item_count: int
    completed_at: datetime


class ReportMetricCard(BaseModel):
    key: str
    label: str
    value: int | float
    unit: str | None = None


class ReportProjectRankingItem(BaseModel):
    project_id: UUID
    project_name: str
    chat_count: int = 0
    validation_run_count: int = 0
    citation_count: int = 0


class ReportSummaryResponse(BaseModel):
    topic: str
    date_from: datetime | None = None
    date_to: datetime | None = None
    project_id: UUID | None = None
    scope: str = "owner_projects"
    page: int = 1
    page_size: int = 20
    total_rows: int = 0
    total_pages: int = 0
    metrics: list[ReportMetricCard]
    project_rankings: list[ReportProjectRankingItem] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["live", "empty", "partial"] = "live"
    partial_reasons: list[str] = Field(default_factory=list)


class ReportScopeOption(BaseModel):
    value: str
    project_count: int


class ReportProjectOption(BaseModel):
    id: UUID
    name: str


class ReportFilterOptionsResponse(BaseModel):
    selected_scope: str
    scopes: list[ReportScopeOption] = Field(default_factory=list)
    projects: list[ReportProjectOption] = Field(default_factory=list)


class NotificationResponse(ORMModel):
    id: UUID
    recipient_user_id: UUID
    project_id: UUID | None
    notification_type: str
    severity: str
    title: str
    message: str
    action_type: str | None
    action_payload: dict[str, Any]
    is_read: bool
    resolved_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    next_cursor: str | None = None


class NotificationCountResponse(BaseModel):
    unread_count: int


class SystemParametersPayload(BaseModel):
    max_upload_size_mb: int
    default_timezone: str
    staging_index_ttl_days: int
    session_expired_form_draft_ttl_minutes: int = 30


class UploadConfigResponse(BaseModel):
    max_upload_size_mb: int


class OperationComponentStatus(BaseModel):
    name: str
    status: str
    detail_code: str
    checked_at: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)


class OperationRecentError(BaseModel):
    source: str
    action: str
    result: str
    detail_code: str
    created_at: datetime


class OperationsStatusResponse(BaseModel):
    status: str
    generated_at: datetime
    dependencies: list[OperationComponentStatus]
    providers: list[OperationComponentStatus]
    worker: OperationComponentStatus
    queue: OperationComponentStatus
    retrieval: OperationComponentStatus
    recent_errors: list[OperationRecentError] = Field(default_factory=list)


class SessionDraftCreatePayload(BaseModel):
    form_key: str = Field(min_length=1, max_length=120)
    return_path: str = Field(min_length=1, max_length=2048)
    nonce: str = Field(min_length=16, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionDraftRestorePayload(BaseModel):
    return_path: str = Field(min_length=1, max_length=2048)
    nonce: str = Field(min_length=16, max_length=255)


class SessionDraftCreateResponse(BaseModel):
    draft_id: UUID
    form_key: str
    return_path: str
    expires_at: datetime
    field_count: int


class SessionDraftRestoreResponse(BaseModel):
    draft_id: UUID
    form_key: str
    return_path: str
    payload: dict[str, Any]
    expires_at: datetime


class AIModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model_type: str
    provider: str = Field(min_length=1, max_length=100)
    endpoint: str | None = None
    api_key: str | None = None
    api_key_secret_ref: str | None = None
    is_active: bool = True
    is_default: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class AIModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: str | None = Field(default=None, min_length=1, max_length=100)
    endpoint: str | None = None
    api_key: str | None = None
    api_key_secret_ref: str | None = None
    clear_credential: bool = False
    credential_clear_confirmation: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    config: dict[str, Any] | None = None


class AIModelDeleteRequest(BaseModel):
    confirmation_name: str = Field(min_length=1, max_length=255)
    config_version: int = Field(ge=1)


class AIModelResponse(ORMModel):
    id: UUID
    name: str
    model_type: str
    provider: str
    endpoint: str | None
    api_key_configured: bool
    api_key_secret_ref: str | None
    is_active: bool
    is_default: bool
    config: dict[str, Any]
    config_version: int
    last_test_status: str | None
    last_tested_at: datetime | None
    last_test_fingerprint: str | None = None
    last_test_latency_ms: int | None = None
    last_test_detail_code: str | None = None
    last_test_actor_id: UUID | None = None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None


class SystemPromptVersionCreate(BaseModel):
    content: str = Field(default="", max_length=8000)
    is_active: bool = True
    change_reason: str | None = Field(default=None, max_length=1000)


class SystemPromptCreate(SystemPromptVersionCreate):
    prompt_scope: Literal["global", "model"]
    model_type: Literal["Chat", "Judge"]
    model_id: UUID | None = None


class SystemPromptActivatePayload(BaseModel):
    version_id: UUID | None = None


class SystemPromptVersionResponse(ORMModel):
    id: UUID
    prompt_id: UUID
    version_number: int
    content: str
    content_hash: str
    is_active: bool
    change_reason: str | None = None
    created_by: UUID | None = None
    created_at: datetime


class SystemPromptResponse(ORMModel):
    id: UUID
    prompt_scope: Literal["global", "model"]
    model_type: Literal["Chat", "Judge"]
    model_id: UUID | None = None
    is_active: bool
    current_version_id: UUID | None = None
    current_version_number: int | None = None
    content: str = ""
    content_length: int = 0
    content_hash: str | None = None
    lock_version: int
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    versions: list[SystemPromptVersionResponse] = Field(default_factory=list)


class IdentitySyncProviderResultResponse(ORMModel):
    id: UUID
    provider_id: str
    provider_name: str
    provider_vendor: str
    requested_scope: str
    status: str
    user_sync_status: str
    group_sync_status: str
    users_added: int
    users_updated: int
    users_removed: int
    users_failed: int
    users_ignored: int
    user_sync_ignored: bool
    error_code: str | None = None
    started_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None


class IdentitySyncRunResponse(ORMModel):
    id: UUID
    source: str
    status: str
    trigger_type: str = "manual"
    requested_scope: str = "people_and_groups"
    phase: str = "queued"
    queued_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
    users_created: int
    users_updated: int
    users_disabled: int
    groups_created: int
    groups_updated: int
    role_memberships_updated: int
    error_message: str | None
    error_code: str | None = None
    attempt: int = 0
    provider_results: list[IdentitySyncProviderResultResponse] = Field(default_factory=list)


class IdentitySyncRunPage(BaseModel):
    items: list[IdentitySyncRunResponse]
    next_cursor: str | None = None


class ExternalGroupResponse(ORMModel):
    id: UUID
    source: str
    external_group_id: str
    group_dn: str | None
    group_name: str
    path: str | None
    identity_origin: str
    is_active: bool
    last_synced_at: datetime | None
    member_count: int = 0
    mapped_role_id: UUID | None = None


class ExternalGroupRoleMappingResponse(BaseModel):
    external_group_id: UUID
    role_id: UUID


class RoleExternalGroupMappingUpdate(BaseModel):
    external_group_id: UUID | None = None
    lock_version: int = Field(ge=1)


class RoleExternalGroupMappingResponse(BaseModel):
    role_id: UUID
    external_group_id: UUID | None
    lock_version: int
    derived_member_count: int


class IdentitySettingsCandidate(BaseModel):
    issuer_url: str
    realm: str
    client_id: str
    audience: str
    discovery_url: str
    jwks_url: str
    enabled: bool = True
    sync_enabled: bool = True
    sync_scope: Literal["people", "groups", "people_and_groups"] = "people_and_groups"
    sync_schedule: str = "0 2 * * *"
    timezone: str = "Asia/Taipei"


class IdentitySettingsResponse(BaseModel):
    state: str
    configuration: dict[str, Any]
    secret_configured: bool
    editable: bool
    configuration_source: Literal["deployment", "database"]
    revision: int | None = None


class DirectoryProviderResponse(BaseModel):
    id: str
    name: str
    vendor: str
    enabled: bool
    custom_user_search_filter: str
    config_hash: str
    checked_at: datetime


class DirectoryProviderFilterUpdate(BaseModel):
    custom_user_search_filter: str = Field(default="", max_length=2048)
    config_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class BreakGlassStatusResponse(BaseModel):
    username: str | None
    status: Literal["configured_disabled", "not_configured", "attention_required", "unavailable"]
    detail_code: str
    configured: bool
    enabled: bool | None
    local_account: bool | None
    system_admin_mapped: bool | None
    credential_update_required: bool | None
    required_actions: list[str]
    credential_source: str
    runbook_evidence: str
    alerting_evidence: str
    lifecycle_control: str
    checked_at: datetime

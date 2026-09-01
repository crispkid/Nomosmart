from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_history_is_scoped_by_surface_and_document_version() -> None:
    models = read("backend/app/db/models.py")
    migration = read("sql/migrations/V016__chat_record_scope_mode.sql")
    schemas = read("backend/app/api/schemas.py")
    serving = read("backend/app/api/routes/serving.py")
    validation_runner = read("backend/app/domain/validation_runner.py")
    approvals = read("backend/app/api/routes/approvals.py")
    api = read("frontend/src/lib/api.ts")
    project_chat = read("frontend/src/components/ProjectChatTest.tsx")
    document_chat = read("frontend/src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx")
    submit_review = read("frontend/src/app/project/[id]/knowledge/[knowledgeId]/submit-review/page.tsx")

    assert "scope_mode: Mapped[str | None]" in models
    assert "ADD COLUMN IF NOT EXISTS scope_mode" in migration
    assert "idx_chat_records_scope_history" in migration
    assert "idx_chat_records_document_scope" in migration
    assert 'scope_mode: Literal["published", "document_staging"]\n' in schemas
    assert 'scope_mode: Literal["published", "document_staging"] | None = None' in schemas

    assert "scope_mode=payload.scope_mode" in serving
    assert "def list_project_chat_conversations(" in serving
    assert 'scope_mode: Literal["published", "document_staging"] = Query(...)' in serving
    assert "document_version_id: UUID | None = Query(default=None)" in serving
    assert "filters.append(ChatRecord.document_version_id == document_version_id)" in serving
    assert "ChatRecord.scope_mode == scope_mode" in serving
    assert "records = _authorized_conversation_records(" in serving
    assert "include_records=True" in serving
    assert "document_version_scope_required" in serving

    assert 'run_scope = "document_staging" if payload.scope_mode == "document_staging" else "project_chat"' in serving
    assert 'if run.run_scope == "document_staging":' in validation_runner
    assert "_search_document_staging_chunks" in validation_runner
    assert 'chat_scope_mode = "document_staging"' in validation_runner
    assert "scope_mode=chat_scope_mode" in validation_runner
    assert 'ChatRecord.scope_mode == "document_staging"' in approvals

    assert 'options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string }' in api
    assert 'params.set("scope_mode", options?.scope_mode ?? "published")' in api
    assert 'params.set("document_version_id", options.document_version_id)' in api
    assert "listProjectChatConversations(apiFetch, projectId)" in project_chat
    assert 'scope_mode: "document_staging", document_version_id: loaded.version.id' in document_chat
    assert "getDocumentVersionSubmissionEvidence" in submit_review
    assert "submissionEvidence.chat_records" in submit_review
    assert "evidence_revision: evidence.evidence_revision" in submit_review
    assert 'scope_mode: "document_staging"' in document_chat
    assert "selected_document_version_ids: [versionId]" in document_chat
    assert "_resolve_retrieval_scope(session, project.id, payload.document_version_ids)" in serving
    assert "_resolve_retrieval_scope(session, project.id, payload.selected_document_version_ids)" in serving
    assert "def _active_retrieval_manifest_query(project_id: UUID)" in serving
    assert "Document.status == \"active\"" in serving
    assert "DocumentVersion.status == \"active\"" in serving
    assert "Document.is_deleted.is_(False)" in serving
    assert "_active_retrieval_manifest_query(project.id).order_by" in serving
    assert "_active_retrieval_manifest_query(project_id).where(ActiveVersionManifest.index_ready.is_(True))" in serving
    assert "requested_ids.issubset(manifest_ids)" in serving
    assert "Retrieval scope must be active published document versions in this project" in serving
    assert "validation_scope_denied" in serving


def test_review_locked_document_versions_block_extraction_mutations_but_stay_viewable() -> None:
    documents = read("backend/app/api/routes/documents.py")
    knowledge_page = read("frontend/src/app/project/[id]/knowledge/[knowledgeId]/page.tsx")
    import_page = read("frontend/src/app/project/[id]/import/page.tsx")
    zh = read("frontend/src/i18n/locales/zh.json")
    en = read("frontend/src/i18n/locales/en.json")

    assert 'REVIEW_LOCKED_VERSION_STATUSES = {"pending_manager_review", "pending_owner_review", "approved"}' in documents
    assert "def _ensure_not_review_locked" in documents
    assert "document_version_review_locked" in documents
    assert 'details={"version_id": str(version.id), "status": version.status, "action": action}' in documents
    assert '_ensure_not_review_locked(version, "document.extraction.start")' in documents
    assert '_ensure_not_review_locked(version, "document.pipeline.retry")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.chunk.manual_create")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.chunk_tag.add")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.chunk_tag.delete")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.chunk_tag.auto")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.document_tag.add")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.document_tag.delete")' in documents
    assert '_ensure_not_review_locked(version, "knowledge.document_tag.auto")' in documents
    assert "manual_edit_enabled, manual_edit_reason = _manual_edit_state(session, version, pipeline, context)" in documents
    assert 'return False, "review_locked"' in documents

    assert 'reason === "review_locked"' in knowledge_page
    assert "const mutationLocked = liveDetail?.manual_edit_reason === \"review_locked\"" in knowledge_page
    assert "reviewLocked={mutationLocked}" in knowledge_page
    assert "disabled={!liveDetail || mutationLocked}" in knowledge_page
    assert "knowledgeDetailReviewLockedReason" in knowledge_page

    assert "function isReviewLockedVersionStatus" in import_page
    assert "const reviewLocked = isReviewLockedVersionStatus(displayedVersionStatus)" in import_page
    assert "projectImportReviewExtractionLocked" in import_page
    assert "disabled={reviewLocked || !failedStep" in import_page
    assert "disabled={reviewLocked}" in import_page

    assert "knowledgeDetailReviewLockedReason" in zh
    assert "knowledgeDetailReviewLockedReason" in en
    assert "projectImportReviewExtractionLocked" in zh
    assert "projectImportReviewExtractionLocked" in en

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_break_glass_lifecycle_evidence_is_safe_and_complete() -> None:
    keycloak = read("backend/app/integrations/keycloak.py")
    system = read("backend/app/api/routes/system.py")
    schemas = read("backend/app/api/schemas.py")
    config = read("backend/app/core/config.py")
    frontend = read("frontend/src/components/SystemManagementWorkspace.tsx")
    api = read("frontend/src/lib/api.ts")
    zh = read("frontend/src/i18n/locales/zh.json")
    en = read("frontend/src/i18n/locales/en.json")

    assert '"UPDATE_PASSWORD"' in keycloak
    assert "credential_update_required = \"UPDATE_PASSWORD\" in required_actions" in keycloak
    assert "break_glass_runbook_uri" in config
    assert "break_glass_alerting_evidence" in config
    assert "_break_glass_deployment_evidence" in system
    assert "deployment_evidence_missing" in system
    assert "credential_update_required: bool | None" in schemas
    assert "runbook_evidence: str" in schemas
    assert "alerting_evidence: str" in schemas
    assert "lifecycle_control: str" in schemas
    assert "credential_update_required" in api
    assert "runbook_evidence" in api
    assert "alerting_evidence" in api
    assert "lifecycle_control" in api
    assert "identityCredentialUpdate" in frontend
    assert "identityRunbookEvidence" in frontend
    assert "identityAlertingEvidence" in frontend
    assert "identityLifecycleControl" in frontend
    assert "identityRunbookEvidence" in zh
    assert "identityRunbookEvidence" in en
    route_block = system.split("def get_break_glass_status", 1)[1].split('@router.put("/parameters"', 1)[0]
    assert "initial_password" not in route_block
    assert "password" not in route_block.lower()
    assert "enableBreakGlass" not in frontend
    assert "rotateBreakGlass" not in frontend
    assert "breakGlassPassword" not in frontend


def test_published_opensearch_index_contract_is_profile_scoped_and_traceable() -> None:
    review_publish = read("backend/app/domain/review_publish.py")

    writer_block = review_publish.split("class LiveOpenSearchPublishedAdapter", 1)[1].split("def delete_staging_documents", 1)[0]
    index_function = review_publish.split("def published_index_name", 1)[1].split("def _project", 1)[0]

    assert "published_index_name(self.settings.opensearch_index_prefix, version.embedding_profile_id)" in writer_block
    assert "vector_document_id(version.embedding_profile_id, version.id, chunk.id)" in writer_block
    assert '"index_scope": "published"' in writer_block
    assert '"project_id": str(project_id)' in writer_block
    assert '"document_id": str(document.id)' in writer_block
    assert '"document_version_id": str(version.id)' in writer_block
    assert '"chunk_id": str(chunk.id)' in writer_block
    assert '"embedding_vector": vector' in writer_block
    assert '"embedding_profile_id": str(version.embedding_profile_id)' in writer_block
    assert '"embedding_model_id": str(version.embedding_model_id)' in writer_block
    assert '"vector_dimension": profile.vector_dimension' in writer_block
    assert '"mapping_version": profile.mapping_version' in writer_block
    assert '"version_status": "published"' in writer_block
    assert "return f\"{prefix}-published-profile-{str(embedding_profile_id)[:8]}\".lower()" in index_function
    assert "project_id" not in index_function
    assert "document_version_id" not in index_function


def test_formal_retrieval_is_manifest_first_and_exact_version_filtered() -> None:
    serving = read("backend/app/api/routes/serving.py")

    resolve_block = serving.split("def _resolve_retrieval_scope", 1)[1].split("def _active_retrieval_manifest_query", 1)[0]
    active_query_block = serving.split("def _active_retrieval_manifest_query", 1)[1].split("def _resolve_document_staging_scope", 1)[0]
    scope_filter_block = serving.split("def _scope_filters", 1)[1].split("def _keyword_query_body", 1)[0]
    hybrid_scope_block = serving.split("def _hybrid_index_scopes", 1)[1].split("def _opensearch_hybrid_search", 1)[0]

    assert "_active_retrieval_manifest_query(project_id)" in resolve_block
    assert "ActiveVersionManifest.index_ready.is_(True)" in resolve_block
    assert "active_manifest_required" in resolve_block
    assert "requested_ids.issubset(manifest_ids)" in resolve_block
    assert "retrieval_scope_denied" in resolve_block
    assert "Document.status == \"active\"" in active_query_block
    assert "DocumentVersion.status == \"active\"" in active_query_block
    assert '{"term": {"project_id": str(project_id)}}' in scope_filter_block
    assert '{"term": {"index_scope": scope}}' in scope_filter_block
    assert '{"terms": {"document_version_id": version_ids}}' in scope_filter_block
    assert "published_index_name(prefix, version.embedding_profile_id)" in hybrid_scope_block
    assert "staging_index_name(prefix, project_id, version.id)" in hybrid_scope_block


def test_old_version_switch_updates_manifest_without_vector_cleanup() -> None:
    review_publish = read("backend/app/domain/review_publish.py")
    approvals = read("backend/app/api/routes/approvals.py")

    switch_block = review_publish.split("def switch_active_version", 1)[1].split("def published_index_name", 1)[0]
    route_block = approvals.split("def switch_document_version_active", 1)[1].split("def _pending_query", 1)[0]

    assert "if not impact_confirmed" in switch_block
    assert "if not audit_reason.strip()" in switch_block
    assert "version.lock_version != lock_version" in switch_block
    assert 'version.status not in {"inactive", "active"} or version.published_at is None' in switch_block
    assert "existing_manifest is None or not existing_manifest.index_ready" in switch_block
    assert "existing_manifest.embedding_profile_id != version.embedding_profile_id" in switch_block
    assert 'EmbeddingBuild.status == "published"' in switch_block
    assert "existing_manifest.document_version_id = version.id" in switch_block
    assert "existing_manifest.embedding_build_id = build.id" in switch_block
    assert "existing_manifest.publication_generation += 1" in switch_block
    assert "document_version.switch_active" in switch_block
    assert "delete_staging_documents" not in switch_block
    assert 'Header(default=None, alias="Idempotency-Key")' in route_block
    assert "ProjectOwner" in route_block
    assert "project_owner_required" in route_block

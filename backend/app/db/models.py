from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("employee_id IS NULL OR employee_id ~ '^Z.{0,9}$'", name="employee_id_format").ddl_if(dialect="postgresql"),)

    employee_id: Mapped[str | None] = mapped_column(String(10), unique=True)
    keycloak_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ldap_dn: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    given_name: Mapped[str | None] = mapped_column(String(255))
    family_name: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[str] = mapped_column(String(32), nullable=False, default="keycloak")
    manager_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    manager_delegate_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    manager_delegate_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_delegate_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    knowledge_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    system_notes: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        Index(
            "uq_roles_undeleted_name",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("deleted_at IS NULL OR is_active = false", name="roles_deleted_inactive_check"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class RoleUser(TimestampMixin, Base):
    __tablename__ = "role_users"
    role_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False, default="manual")


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "module_name", "function_name"),)
    role_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    module_name: Mapped[str] = mapped_column(String(100), nullable=False)
    function_name: Mapped[str] = mapped_column(String(100), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_create: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ExternalGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_groups"
    __table_args__ = (UniqueConstraint("source", "external_group_id"),)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    group_dn: Mapped[str | None] = mapped_column(Text)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    identity_origin: Mapped[str] = mapped_column(String(32), nullable=False, default="keycloak_local")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalGroupRoleMapping(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "external_group_role_mappings"
    __table_args__ = (
        UniqueConstraint("external_group_id", name="uq_external_group_role_mappings_external_group"),
        UniqueConstraint("role_id", name="uq_external_group_role_mappings_role"),
    )
    external_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("external_groups.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExternalGroupUser(Base):
    __tablename__ = "external_group_users"
    external_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("external_groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentitySyncRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "identity_sync_runs"
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    requested_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="people_and_groups", server_default=text("'people_and_groups'"))
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", server_default=text("'queued'"))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    users_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    groups_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    groups_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role_memberships_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_results: Mapped[list["IdentitySyncProviderResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="IdentitySyncProviderResult.created_at, IdentitySyncProviderResult.provider_id",
    )


class IdentitySyncProviderResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "identity_sync_provider_results"
    __table_args__ = (UniqueConstraint("run_id", "provider_id", name="uq_identity_sync_provider_results_run_provider"),)

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("identity_sync_runs.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    user_sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_requested")
    group_sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_requested")
    users_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_ignored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_sync_ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    run: Mapped[IdentitySyncRun] = relationship(back_populates="provider_results")


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="projects_status_check"),
        CheckConstraint(
            "(status = 'active' AND archived_at IS NULL AND archived_by IS NULL) OR "
            "(status = 'archived' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)",
            name="projects_archive_metadata_check",
        ),
        Index("ix_projects_status_name", "status", "name", "id"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    llm_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    embedding_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    ocr_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    work_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class ProjectArchiveRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_archive_runs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="project_archive_runs_status_check"),
        Index(
            "uq_project_archive_runs_open_project",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_project_archive_runs_project_queued", "project_id", "queued_at", "id"),
    )
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    requested_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unfinished_version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_s3_object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_search_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_graph_version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_role: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectOwner(Base):
    __tablename__ = "project_owners"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemParameter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "system_parameters"
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    default_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class IdentitySetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identity_settings"
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False)
    secret_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_last_known_good: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class IdentityUnlockGrant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "identity_unlock_grants"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentityReauthFlow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "identity_reauth_flows"
    __table_args__ = (
        UniqueConstraint("state_digest"),
        UniqueConstraint("completion_token_digest"),
        Index("ix_identity_reauth_flows_expires_at", "expires_at"),
        Index("ix_identity_reauth_flows_user_session_scope", "user_id", "session_id", "scope"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    pkce_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(500), nullable=False)
    jwks_url: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    return_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    completion_token_digest: Mapped[str | None] = mapped_column(String(64))
    authenticated_subject: Mapped[str | None] = mapped_column(String(255))
    authenticated_session_id: Mapped[str | None] = mapped_column(String(255))
    authenticated_auth_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevokedAuthToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "revoked_auth_tokens"
    __table_args__ = (
        UniqueConstraint("token_identity"),
        Index("ix_revoked_auth_tokens_expires_at", "expires_at"),
        Index("ix_revoked_auth_tokens_subject_session", "subject", "session_id"),
    )

    token_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    audience: Mapped[str] = mapped_column(String(500), nullable=False)
    token_id: Mapped[str | None] = mapped_column(String(255))
    session_id: Mapped[str | None] = mapped_column(String(255))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SessionExpiredFormDraft(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "session_expired_form_drafts"
    __table_args__ = (
        Index("ix_session_expired_form_drafts_user_status", "user_id", "status"),
        Index("ix_session_expired_form_drafts_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    form_key: Mapped[str] = mapped_column(String(120), nullable=False)
    return_path: Mapped[str] = mapped_column(Text, nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        Index(
            "uq_ai_models_active_name_type",
            "name",
            "model_type",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    api_key_secret_ref: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_test_status: Mapped[str | None] = mapped_column(String(32))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_test_detail_code: Mapped[str | None] = mapped_column(String(100))
    last_test_actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key_encrypted or self.api_key_secret_ref)


class AIModelUsageEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_model_usage_events"
    __table_args__ = (
        Index("ix_ai_model_usage_events_created", "created_at"),
        Index("ix_ai_model_usage_events_project_created", "project_id", "created_at"),
        Index("ix_ai_model_usage_events_model_created", "model_id", "created_at"),
        Index("ix_ai_model_usage_events_purpose_created", "usage_purpose", "created_at"),
        Index("ix_ai_model_usage_events_client_created", "integration_client_id", "created_at"),
        CheckConstraint("cost_source IN ('provider_reported', 'estimated', 'unavailable')", name="ai_model_usage_events_cost_source_check"),
        CheckConstraint("provider_reported_cost IS NULL OR provider_reported_cost >= 0", name="ai_model_usage_events_provider_cost_check"),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ai_model_usage_events_estimated_cost_check"),
    )

    model_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"))
    document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    pipeline_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pipeline_runs.id"))
    pipeline_step_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pipeline_run_steps.id"))
    chat_record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_records.id"))
    validation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("validation_runs.id"))
    validation_run_item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("validation_run_items.id"))
    public_api_request_log_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("public_api_request_logs.id"))
    integration_client_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("integration_clients.id"))
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    source_channel: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correlation_id: Mapped[str | None] = mapped_column(String(255))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    embedding_tokens: Mapped[int | None] = mapped_column(BigInteger)
    ocr_pages: Mapped[int | None] = mapped_column(Integer)
    ocr_images: Mapped[int | None] = mapped_column(Integer)
    vector_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    raw_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provider_reported_cost: Mapped[float | None] = mapped_column(Numeric(20, 8))
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(20, 8))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    cost_source: Mapped[str] = mapped_column(String(32), nullable=False, default="unavailable")
    cost_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemPrompt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "system_prompts"
    __table_args__ = (
        CheckConstraint("prompt_scope IN ('global', 'model')", name="system_prompts_scope_check"),
        CheckConstraint("model_type IN ('Chat', 'Judge')", name="system_prompts_model_type_check"),
        CheckConstraint(
            "(prompt_scope = 'global' AND model_id IS NULL) OR (prompt_scope = 'model' AND model_id IS NOT NULL)",
            name="system_prompts_scope_model_check",
        ),
        UniqueConstraint("model_id", name="uq_system_prompts_model_id"),
    )
    prompt_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class SystemPromptVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "system_prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version_number", name="uq_system_prompt_versions_number"),
        CheckConstraint("char_length(content) <= 8000", name="system_prompt_versions_content_length_check"),
    )
    prompt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("system_prompts.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    request_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IntegrationClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_clients"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'revoked')", name="integration_clients_status_check"),
        UniqueConstraint("api_key_hash", name="uq_integration_clients_api_key_hash"),
        Index("ix_integration_clients_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    api_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_department: Mapped[str | None] = mapped_column(String(255))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    rate_limit_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class IntegrationClientProjectScope(Base):
    __tablename__ = "integration_client_project_scopes"
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("integration_clients.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmbeddingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "embedding_profiles"
    __table_args__ = (UniqueConstraint("model_id", "model_version", "vector_dimension", "distance_method", "mapping_version"),)
    model_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_method: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_strategy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="inactive")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_major", "extraction_revision"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    original_file_name: Mapped[str | None] = mapped_column(String(255))
    canonical_extension: Mapped[str | None] = mapped_column(String(16))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_name_salt: Mapped[str | None] = mapped_column(String(128))
    storage_name_hash: Mapped[str | None] = mapped_column(String(64))
    storage_bucket: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(Text)
    storage_etag: Mapped[str | None] = mapped_column(String(255))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_snapshot_uri: Mapped[str | None] = mapped_column(Text)
    markdown_artifact_uri: Mapped[str | None] = mapped_column(Text)
    extraction_artifact_uri: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(100))
    ocr_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    ocr_config_version: Mapped[int | None] = mapped_column(Integer)
    chunk_strategy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    chunk_size: Mapped[int | None] = mapped_column(Integer)
    chunk_overlap: Mapped[int | None] = mapped_column(Integer)
    embedding_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    embedding_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("embedding_profiles.id"))
    llm_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    inactive_reason: Mapped[str | None] = mapped_column(String(255))
    source_document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"))
    source_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    source_snapshot_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmbeddingBuild(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "embedding_builds"
    __table_args__ = (UniqueConstraint("document_version_id", "embedding_profile_id", "build_revision"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    embedding_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("embedding_profiles.id"), nullable=False)
    build_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_name: Mapped[str | None] = mapped_column(String(255))
    checksum: Mapped[str | None] = mapped_column(String(64))
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    vector_dimension: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmbeddingBuildVector(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "embedding_build_vectors"
    __table_args__ = (
        UniqueConstraint("embedding_build_id", "chunk_id"),
        UniqueConstraint("embedding_build_id", "chunk_index"),
        Index("ix_embedding_build_vectors_build", "embedding_build_id", "chunk_index"),
    )
    embedding_build_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("embedding_builds.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list] = mapped_column(JSONB, nullable=False)
    vector_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActiveVersionManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "active_version_manifests"
    __table_args__ = (UniqueConstraint("document_id"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    embedding_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("embedding_profiles.id"), nullable=False)
    embedding_build_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("embedding_builds.id"), nullable=False)
    publication_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    index_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class IdempotencyKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_summary: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbox_events"
    topic: Mapped[str] = mapped_column(String(150), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    project_generation: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[str | None] = mapped_column(String(255))


class DataConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_connections"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    credential_encrypted: Mapped[str | None] = mapped_column(Text)
    credential_secret_ref: Mapped[str | None] = mapped_column(Text)
    source_identity: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="Asia/Taipei")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(32))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    last_test_status: Mapped[str | None] = mapped_column(String(32))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_test_detail_code: Mapped[str | None] = mapped_column(String(100))
    last_test_actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class FileScanRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "file_scan_runs"
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    scanner_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_result_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quarantine_bucket: Mapped[str | None] = mapped_column(String(255))
    quarantine_key: Mapped[str | None] = mapped_column(Text)
    accepted_bucket: Mapped[str | None] = mapped_column(String(255))
    accepted_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantine_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_references"
    __table_args__ = (UniqueConstraint("target_project_id", "source_project_id", "source_document_id"),)
    target_project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    target_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    source_project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    source_project_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    source_document_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    reference_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="linked")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentReferenceEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_reference_events"
    reference_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_references.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    old_source_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    new_source_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataSyncRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "data_sync_runs"
    data_connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("data_connections.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    remote_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pipeline_runs"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"))
    document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    run_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    current_step_name: Mapped[str | None] = mapped_column(String(100))
    current_waiting_role: Mapped[str | None] = mapped_column(String(100))
    current_action_url: Mapped[str | None] = mapped_column(Text)
    estimated_remaining_seconds: Mapped[int | None] = mapped_column(Integer)
    triggered_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineRunStep(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pipeline_run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_name"),)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_artifact_ref: Mapped[str | None] = mapped_column(Text)
    output_artifact_ref: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_fingerprint: Mapped[str | None] = mapped_column(String(64))
    artifact_payload: Mapped[dict | None] = mapped_column(JSONB)


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_requests"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    submitter_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    evidence_revision: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", server_default=text("'normal'"))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("approval_tasks.id", use_alter=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalEvidenceManifest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_evidence_manifests"
    __table_args__ = (
        UniqueConstraint("approval_request_id"),
        UniqueConstraint("manifest_hash"),
        Index("ix_approval_evidence_version_submitted", "document_version_id", "submitted_at"),
    )
    approval_request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    evidence_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class ApprovalTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_tasks"
    approval_request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    submitter_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assignee_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    review_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_records"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    review_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    delegated_from_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index(
            "uq_chunks_active_version_index",
            "document_version_id",
            "chunk_index",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_content: Mapped[str | None] = mapped_column(Text)
    display_markdown: Mapped[str | None] = mapped_column(Text)
    retrieval_text: Mapped[str | None] = mapped_column(Text)
    embedding_content_hash: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text)
    # V046 permits SQL NULL or an array; JSON null is not an absent heading path.
    heading_path: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    heading_level: Mapped[int | None] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    sequence: Mapped[int | None] = mapped_column(Integer)
    stable_chunk_key: Mapped[str | None] = mapped_column(String(64))
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    source_mapping: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    chunk_strategy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    embedding_vector_ref: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(6, 5))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_manual_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    lineage_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()"))
    parent_chunk_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chunks.id"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, default="generated", server_default=text("'generated'"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chunks.id"))


class Tag(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChunkTag(Base):
    __tablename__ = "chunk_tags"
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    confidence_score: Mapped[float | None] = mapped_column(Numeric(6, 5))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentVersionTag(Base):
    __tablename__ = "document_version_tags"
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    confidence_score: Mapped[float | None] = mapped_column(Numeric(6, 5))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_records"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    scope_mode: Mapped[str | None] = mapped_column(String(32))
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_title: Mapped[str | None] = mapped_column(String(500))
    selected_document_version_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    reference_docs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evaluation: Mapped[str] = mapped_column(String(32), nullable=False, default="not_evaluated")
    revision_suggestion: Mapped[str | None] = mapped_column(Text)
    llm_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    embedding_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    system_prompt_source: Mapped[str | None] = mapped_column(String(32))
    system_prompt_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("system_prompt_versions.id"))
    system_prompt_content_hash: Mapped[str | None] = mapped_column(String(64))
    system_prompt_layers: Mapped[list | None] = mapped_column(JSONB)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class PublicApiRequestLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "public_api_request_logs"
    __table_args__ = (
        Index("ix_public_api_request_logs_client_created", "integration_client_id", "created_at"),
        Index("ix_public_api_request_logs_project_created", "project_id", "created_at"),
    )

    integration_client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("integration_clients.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255))
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    response_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    end_user_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    end_user_employee_name: Mapped[str | None] = mapped_column(String(255))
    end_user_department: Mapped[str | None] = mapped_column(String(255))
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    selected_document_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    selected_document_version_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    retrieval_strategy: Mapped[str | None] = mapped_column(String(32))
    retrieval_status: Mapped[str | None] = mapped_column(String(32))
    llm_model_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_models.id"))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    system_prompt_source: Mapped[str | None] = mapped_column(String(32))
    system_prompt_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("system_prompt_versions.id"))
    system_prompt_content_hash: Mapped[str | None] = mapped_column(String(64))
    system_prompt_layers: Mapped[list | None] = mapped_column(JSONB)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    request_hash: Mapped[str | None] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    end_user_identity_hash: Mapped[str | None] = mapped_column(String(64))
    question_encrypted: Mapped[str | None] = mapped_column(Text)
    answer_encrypted: Mapped[str | None] = mapped_column(Text)
    citations_encrypted: Mapped[str | None] = mapped_column(Text)
    end_user_metadata_encrypted: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatFeedbackEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_feedback_events"
    __table_args__ = (
        CheckConstraint("source IN ('ui', 'api')", name="chat_feedback_events_source_check"),
        Index("ix_chat_feedback_events_chat_record_created", "chat_record_id", "created_at"),
        Index("ix_chat_feedback_events_public_response_created", "public_response_id", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    chat_record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_records.id", ondelete="CASCADE"))
    public_response_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("public_api_request_logs.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    feedback_value: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    integration_client_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("integration_clients.id"))
    end_user_employee_id: Mapped[str | None] = mapped_column(String(100))
    end_user_employee_name: Mapped[str | None] = mapped_column(String(255))
    end_user_department: Mapped[str | None] = mapped_column(String(255))
    end_user_identity_hash: Mapped[str | None] = mapped_column(String(64))
    end_user_metadata_encrypted: Mapped[str | None] = mapped_column(Text)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValidationQuestion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_questions"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_keywords: Mapped[list | None] = mapped_column(JSONB)
    category: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValidationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_runs"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    uploaded_file_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("approval_tasks.id"))
    document_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"))
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    llm_model: Mapped[str | None] = mapped_column(String(255))
    selected_document_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    execution_manifest: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "manifest_version": "legacy-unavailable",
            "state": "legacy_manifest_unavailable",
        },
        server_default=text(
            """'{"manifest_version":"legacy-unavailable","state":"legacy_manifest_unavailable"}'::jsonb"""
        ),
    )
    execution_manifest_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="54a0c752dcb50c178767c0a43649fd8d682ff573137bdf5bc30679d115107473",
        server_default=text(
            "'54a0c752dcb50c178767c0a43649fd8d682ff573137bdf5bc30679d115107473'"
        ),
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValidationRunItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_run_items"
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False)
    parent_item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("validation_run_items.id"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    input_item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid4)
    input_ordinal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=lambda: uuid4().int % 2_000_000_000,
    )
    input_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_keywords: Mapped[list | None] = mapped_column(JSONB)
    selected_document_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    category: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[str | None] = mapped_column(String(32))
    answer: Mapped[str | None] = mapped_column(Text)
    reference_docs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    chat_record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_records.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(8, 5))
    evaluation_reason: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    system_prompt_source: Mapped[str | None] = mapped_column(String(32))
    system_prompt_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("system_prompt_versions.id"))
    system_prompt_content_hash: Mapped[str | None] = mapped_column(String(64))
    system_prompt_layers: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("source_event_id", "recipient_user_id"),
        Index("ix_notifications_business_recipient_open", "business_key", "recipient_user_id", "resolved_at"),
    )
    source_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("notification_events.id"))
    recipient_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    notification_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(32))
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    business_key: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_reason: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_notification_events_status_created", "status", "created_at", "id"),
    )
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    business_key: Mapped[str] = mapped_column(String(255), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_user_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphSyncJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "graph_sync_jobs"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    project_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    parent_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("graph_sync_jobs.id"))
    requested_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    request_id: Mapped[str | None] = mapped_column(String(255))
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

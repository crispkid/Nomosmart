"""Protocol identity persistence; no external identity product owns these IDs."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DirectorySource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "directory_sources"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema: Mapped[str] = mapped_column(String(16), nullable=False)


class AuthenticationIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "authentication_identities"
    __table_args__ = (UniqueConstraint("source_id", "issuer", "subject"),)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("directory_sources.id"), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)


class AuthSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (CheckConstraint("login_method IN ('oidc','ldap','emergency')", name="auth_session_login_method"),)
    secret_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    login_method: Mapped[str] = mapped_column(String(16), nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emergency_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upstream_ciphertext: Mapped[str | None] = mapped_column(Text)
    upstream_key_id: Mapped[str | None] = mapped_column(String(80))


class AuthLoginFlow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_login_flows"
    state_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    nonce_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    setting_id: Mapped[UUID] = mapped_column(ForeignKey("identity_settings.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    initiating_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("auth_sessions.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    return_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthConnectionSecret(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_connection_secrets"
    __table_args__ = (UniqueConstraint("setting_id", "purpose"),)
    setting_id: Mapped[UUID] = mapped_column(ForeignKey("identity_settings.id"), nullable=False)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("directory_sources.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    context_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    envelope: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthCandidateEvidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_candidate_evidence"
    setting_id: Mapped[UUID] = mapped_column(ForeignKey("identity_settings.id"), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    candidate_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthEmergencyAccess(Base):
    __tablename__ = "auth_emergency_access"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_verifier: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthAttemptWindow(Base):
    __tablename__ = "auth_attempt_windows"
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)

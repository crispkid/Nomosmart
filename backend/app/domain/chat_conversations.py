"""Conversation identity is global; reading a Project is not owning its chats.

Read projections use metadata only. Mutations serialize with the same PostgreSQL
transaction lock before any provider work and hold it until record commit.
"""
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ChatRecord


@dataclass(frozen=True)
class ConversationIdentity:
    project_ids: frozenset[UUID]
    scope_modes: frozenset[str | None]
    creator_id: UUID | None
    selected_ids: frozenset[UUID]
    valid: bool
    deleted: bool


def conversation_identities(session: Session, ids: list[UUID]) -> dict[UUID, ConversationIdentity]:
    if not ids:
        return {}
    groups = defaultdict(list)
    rows = session.execute(select(
        ChatRecord.conversation_id, ChatRecord.project_id, ChatRecord.scope_mode,
        ChatRecord.created_by, ChatRecord.selected_document_version_ids,
        ChatRecord.document_version_id, ChatRecord.deleted_at,
    ).where(ChatRecord.conversation_id.in_(ids)))
    for row in rows:
        groups[row.conversation_id].append(row)
    result = {}
    for conversation_id, records in groups.items():
        projects = frozenset(row.project_id for row in records)
        modes = frozenset(row.scope_mode for row in records)
        creators = {row.created_by for row in records}
        selected = set()
        consistent = True
        for row in records:
            try:
                values = row.selected_document_version_ids
                if not isinstance(values, list) or not values:
                    raise ValueError("Missing fixed scope")
                versions = frozenset(UUID(str(value)) for value in values)
                selected.add(versions)
                if row.scope_mode == "document_staging":
                    consistent &= versions == frozenset({row.document_version_id})
                elif row.document_version_id is not None:
                    consistent &= versions == frozenset({row.document_version_id})
            except (TypeError, ValueError):
                consistent = False
        deleted = any(row.deleted_at is not None for row in records)
        creator = next(iter(creators)) if len(creators) == 1 else None
        result[conversation_id] = ConversationIdentity(
            project_ids=projects, scope_modes=modes, creator_id=creator,
            selected_ids=next(iter(selected)) if len(selected) == 1 else frozenset(),
            valid=(consistent and not deleted and len(projects) == 1 and len(modes) == 1
                   and modes <= {"published", "document_staging"} and creator is not None and len(selected) == 1),
            deleted=deleted,
        )
    return result


def lock_conversation(session: Session, conversation_id: UUID) -> None:
    # Do not block a worker waiting on an in-flight LLM request. A retryable
    # conflict is bounded and cannot call a provider or write a competing turn.
    key = int.from_bytes(sha256(b"nomosmart.chat:" + conversation_id.bytes).digest()[:8], "big", signed=True)
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
        raise AppError("conversation_busy", "Conversation is processing another request; retry later", status_code=409)


def validate_visible_identity(identity: ConversationIdentity, *, project_id: UUID, scope_mode: str,
                              document_version_id: UUID | None = None) -> None:
    if (identity.deleted or identity.project_ids != {project_id} or scope_mode not in identity.scope_modes
            or None in identity.scope_modes or not identity.scope_modes <= {"published", "document_staging"}):
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    if not identity.valid:
        raise AppError("conversation_identity_conflict", "Conversation identity is inconsistent", status_code=409)
    if scope_mode == "document_staging" and identity.selected_ids != {document_version_id}:
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)


def require_conversation_identity(session: Session, *, project_id: UUID, conversation_id: UUID,
                                  user_id: UUID, scope_mode: str, requested_ids: set[UUID] | None,
                                  unused_only: bool = False) -> ConversationIdentity | None:
    lock_conversation(session, conversation_id)
    identity = conversation_identities(session, [conversation_id]).get(conversation_id)
    if identity is None:
        return None
    document_version_id = next(iter(requested_ids)) if requested_ids and len(requested_ids) == 1 else None
    validate_visible_identity(identity, project_id=project_id, scope_mode=scope_mode,
                              document_version_id=document_version_id)
    if identity.creator_id != user_id:
        raise AppError("conversation_read_only", "Only the conversation creator may change it", status_code=403)
    if unused_only:
        raise AppError("conversation_identity_conflict", "Conversation identity is already used", status_code=409)
    if requested_ids is not None and identity.selected_ids != requested_ids:
        raise AppError("conversation_scope_locked", "Conversation scope is fixed after the first turn", status_code=409)
    return identity

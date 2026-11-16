"""CHG-435 MTURN435-002..005: multi-turn context shared by both question-answering entries.

Earlier turns come only from stored records (public API logs or chat-test records), are
checked against the caller's identity, bounded by turns and characters, and, when a
follow-up exists, the question is rewritten into a standalone search question.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel, ChatRecord, PublicApiRequestLog
from app.domain.ai_provider import rewrite_follow_up_question
from app.domain.model_usage import record_query_rewrite_usage

_MARKER = re.compile(r"\s?\[\d+\]")
RewriteStatus = Literal["not_needed", "rewritten", "failed"]


@dataclass
class ConversationContext:
    """What one question is sent with: earlier turns (oldest first) and the search question."""

    previous_id: UUID | None = None
    history: list[tuple[str, str]] = field(default_factory=list)
    truncated: bool = False
    search_question: str = ""
    rewritten_query: str | None = None
    rewrite_status: RewriteStatus = "not_needed"

    @property
    def turns_used(self) -> int:
        return len(self.history)

    def extension(self) -> dict:
        return {"turns_used": self.turns_used, "truncated": self.truncated,
                "rewritten_query": self.rewritten_query, "rewrite_status": self.rewrite_status}


def not_found() -> AppError:
    return AppError("previous_response_not_found", "The previous response was not found", status_code=404,
                    details={"param": "previous_response_id"})


def strip_citation_markers(text: str | None) -> str:
    return _MARKER.sub("", text or "").strip()


def public_turns(session: Session, settings: Settings, previous_id: UUID, *, client_id: UUID,
                 identity_hash: str, project_id: UUID) -> list[tuple[str, str]]:
    """Newest first, at most CHAT_HISTORY_MAX_TURNS; the first record must be usable or 404."""

    cipher = EnvelopeCipher(settings.encryption_key_bytes)
    turns: list[tuple[str, str]] = []
    current: UUID | None = previous_id
    while current is not None and len(turns) < settings.chat_history_max_turns:
        log = session.get(PublicApiRequestLog, current)
        usable = (log is not None and log.integration_client_id == client_id and log.end_user_identity_hash == identity_hash
                  and log.project_id == project_id and log.deleted_at is None and log.result == "success"
                  and log.question_encrypted and log.answer_encrypted)
        if not usable:
            if not turns:
                raise not_found()
            break  # an older turn removed by retention simply ends the history
        question = json.loads(cipher.decrypt(log.question_encrypted, context=f"public-response:{log.id}:question"))
        answer = json.loads(cipher.decrypt(log.answer_encrypted, context=f"public-response:{log.id}:answer"))
        turns.append((str(question), strip_citation_markers(str(answer))))
        current = log.previous_response_id
    return turns


def chat_test_turns(session: Session, settings: Settings, previous_id: UUID, *, user_id: UUID, project_id: UUID,
                    conversation_id: UUID) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    current: UUID | None = previous_id
    while current is not None and len(turns) < settings.chat_history_max_turns:
        record = session.get(ChatRecord, current)
        usable = (record is not None and record.created_by == user_id and record.project_id == project_id
                  and record.conversation_id == conversation_id and record.deleted_at is None and record.answer)
        if not usable:
            if not turns:
                raise not_found()
            break
        turns.append((record.question, strip_citation_markers(record.answer)))
        current = record.previous_response_id
    return turns


def bound_history(turns_newest_first: list[tuple[str, str]], settings: Settings, truncation: str | None) -> tuple[list[tuple[str, str]], bool]:
    """Apply the character limit; `disabled` truncation refuses instead of dropping (MTURN435-004)."""

    kept: list[tuple[str, str]] = []
    used = 0
    for question, answer in turns_newest_first:
        size = len(question) + len(answer)
        if used + size > settings.chat_history_max_characters:
            break
        kept.append((question, answer))
        used += size
    truncated = len(kept) < len(turns_newest_first)
    if truncated and truncation == "disabled":
        raise AppError("context_length_exceeded", "Earlier turns exceed the configured context limit", status_code=400,
                       details={"param": "truncation"})
    return list(reversed(kept)), truncated


def rewrite_question(session: Session, settings: Settings, context: ConversationContext, question: str, model: AIModel | None,
                     *, source_channel: str, project_id: UUID, actor_user_id: UUID | None = None,
                     integration_client_id: UUID | None = None, correlation_id: str | None = None) -> None:
    """Fill the search question; on failure keep the original question (D435-03)."""

    context.search_question = question
    if not context.history:
        return
    if model is None:
        context.rewrite_status = "failed"
        return
    started = perf_counter()
    try:
        rewritten, usage = rewrite_follow_up_question(model, context.history, question, settings)
    except AppError as exc:
        context.rewrite_status = "failed"
        record_query_rewrite_usage(model=model, source_channel=source_channel, status="failed", error_code=exc.code,
                                   latency_ms=_elapsed(started), project_id=project_id, actor_user_id=actor_user_id,
                                   integration_client_id=integration_client_id, correlation_id=correlation_id)
        return
    record_query_rewrite_usage(model=model, source_channel=source_channel, status="success", token_usage=usage,
                               latency_ms=_elapsed(started), project_id=project_id, actor_user_id=actor_user_id,
                               integration_client_id=integration_client_id, correlation_id=correlation_id)
    context.search_question = rewritten
    context.rewritten_query = rewritten
    context.rewrite_status = "rewritten"


def _elapsed(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def chat_test_mode(session: Session, conversation_id: UUID, requested_mode: str | None, previous_id: UUID | None) -> str:
    """MTURN435-009 / D435-04, D435-05: the first question fixes the mode; multi-turn is linear."""

    from sqlalchemy import select

    rows = session.execute(
        select(ChatRecord.id, ChatRecord.conversation_mode, ChatRecord.created_at)
        .where(ChatRecord.conversation_id == conversation_id, ChatRecord.deleted_at.is_(None))
        .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
    ).all()
    if not rows:
        if previous_id is not None:
            raise AppError("previous_response_not_latest", "A new conversation has no earlier answer to continue", status_code=409,
                           details={"param": "previous_response_id"})
        return requested_mode or "single"
    mode = rows[-1].conversation_mode or "single"
    if requested_mode is not None and requested_mode != mode:
        raise AppError("conversation_mode_mismatch", "The conversation mode is fixed by its first question", status_code=409,
                       details={"param": "nomosmart:conversation.mode"})
    if mode == "single":
        if previous_id is not None:
            raise AppError("conversation_mode_mismatch", "A single-turn conversation does not continue earlier answers", status_code=409,
                           details={"param": "previous_response_id"})
        return mode
    if previous_id != rows[0].id:
        raise AppError("previous_response_not_latest", "A multi-turn conversation continues from its latest answer", status_code=409,
                       details={"param": "previous_response_id"})
    return mode


def chat_test_context(session: Session, settings: Settings, project, payload, *, user_id: UUID, conversation_id: UUID) -> tuple[str, ConversationContext]:
    """Mode rule, earlier turns and search question for one chat-test question."""

    from app.domain.project_retrieval import _select_chat_model

    mode = chat_test_mode(session, conversation_id, payload.conversation_mode, payload.previous_id)
    context = ConversationContext(previous_id=payload.previous_id, search_question=payload.question)
    if payload.previous_id is None:
        return mode, context
    turns = chat_test_turns(session, settings, payload.previous_id, user_id=user_id, project_id=project.id, conversation_id=conversation_id)
    context.history, context.truncated = bound_history(turns, settings, payload.truncation)
    try:
        model = _select_chat_model(session, project)
    except AppError:
        model = None
    rewrite_question(session, settings, context, payload.question, model, source_channel="chat_test", project_id=project.id, actor_user_id=user_id)
    return mode, context

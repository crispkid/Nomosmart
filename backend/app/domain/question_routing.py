"""CHG-445 ROUTE445-001/003: decide whether a published-scope question asks about document references.

The project's Chat model receives the question and the titles of the published documents inside this authorized
scope, and answers with JSON: an intent (`referenced_by`, `references` or `none`) and the titles it refers to. Only
listed titles are accepted. Any failure (provider error, 10 second timeout, malformed answer) yields `none`, so the
question is answered the usual way; every attempt is recorded as `question_routing` model usage.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from uuid import UUID

from app.core.errors import AppError
from app.db.models import AIModel

PROMPT_VERSION = "reference-routing-v1"
TIMEOUT_SECONDS = 10
MAX_TITLES = 300
INTENTS = {"referenced_by", "references", "none"}
SYSTEM_PROMPT = """You classify one question asked to a document knowledge base. Do not answer it.
Decide whether the question asks about references between documents:
- "referenced_by": which documents cite, refer to, are based on, or apply a named document.
- "references": which documents a named document cites, refers to, or is based on.
- "none": anything else, including questions about document content, effects or who is affected.
Choose the named documents only from the provided title list; an abbreviation or short name may match a listed title.
If no listed title fits, use "none".
Reply with JSON only: {"intent": "referenced_by" | "references" | "none", "documents": ["<exact listed title>", ...]}"""


@dataclass
class RoutingDecision:
    intent: str = "none"
    document_ids: list[UUID] = field(default_factory=list)
    status: str = "skipped"


def _shortlist(question: str, titles: list[str]) -> list[str]:
    if len(titles) <= MAX_TITLES:
        return titles
    chars = set(question)
    return sorted(titles, key=lambda title: (-len(chars.intersection(title)), title))[:MAX_TITLES]


def _parse(content: str, allowed: dict[str, UUID]) -> RoutingDecision:
    text = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    intent = data.get("intent") if isinstance(data, dict) else None
    names = data.get("documents") if isinstance(data, dict) else None
    if intent not in INTENTS or not isinstance(names, list):
        raise ValueError("routing answer is malformed")
    ids = list(dict.fromkeys(allowed[name] for name in names if isinstance(name, str) and name in allowed))
    if intent == "none" or not ids:
        return RoutingDecision("none", [], "success")
    return RoutingDecision(intent, ids, "success")


def classify_question(*, model: AIModel, question: str, documents: dict[str, UUID], settings, source_channel: str,
                      project_id: UUID, actor_user_id: UUID | None) -> RoutingDecision:
    from app.domain.ai_provider import _invoke_chat_provider
    from app.domain.model_usage import record_question_routing_usage
    if not documents or not question.strip():
        return RoutingDecision()
    titles = _shortlist(question, sorted(documents))
    prompt = [{"role": "system", "content": SYSTEM_PROMPT},
              {"role": "user", "content": "Titles:\n" + "\n".join(f"- {title}" for title in titles) + f"\n\nQuestion:\n{question.strip()[:4000]}"}]
    # Same model and credentials, but a short timeout so routing never delays an answer for long.
    probe = AIModel(**{column.key: getattr(model, column.key) for column in AIModel.__table__.columns})
    probe.config = {**(model.config or {}), "timeout_seconds": TIMEOUT_SECONDS}
    started = perf_counter()
    try:
        payload, answer_of, usage = _invoke_chat_provider(probe, prompt, settings, unsupported="Chat Model provider is not supported for question routing")
        decision = _parse(answer_of(payload), {title: documents[title] for title in titles})
    except (AppError, ValueError, TypeError, KeyError) as exc:
        record_question_routing_usage(model=model, source_channel=source_channel, status="failed",
                                      error_code=getattr(exc, "code", "question_routing_invalid_answer"),
                                      latency_ms=int((perf_counter() - started) * 1000), project_id=project_id,
                                      actor_user_id=actor_user_id, prompt_version=PROMPT_VERSION)
        return RoutingDecision(status="failed")
    record_question_routing_usage(model=model, source_channel=source_channel, status="success", token_usage=usage,
                                  latency_ms=int((perf_counter() - started) * 1000), project_id=project_id,
                                  actor_user_id=actor_user_id, prompt_version=PROMPT_VERSION)
    return decision

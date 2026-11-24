"""Retrieval depth and breadth per question: Top K, Top P and optional reranking (CHG-486).

- K (`top_k`): at most K chunks per retrieval step.
- P (`top_p`): with reranking, chunks are taken in descending rerank score until their cumulative share of the
  candidate pool's total score reaches P (TOPKP486-002). Without reranking P has no effect.
- Reranking happens only when the system switch is on, an active rerank model is selected and the project
  switch is on (RERANK486-005).

`RetrievalTuning.trace` is the per-question retrieval trace stored on chat records and validation items
(RTRACE486-001). It holds only numbers, flags and identifiers, never question or chunk text.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AIModel, Project

logger = logging.getLogger("nomosmart.retrieval")

TOP_K_RANGE = (1, 20)
TOP_P_RANGE = (0.1, 1.0)
TRACE_VERSION = 1


@dataclass
class RetrievalTuning:
    top_k: int
    top_p: float = 1.0
    min_score: float = 0.0
    rerank_model: AIModel | None = None
    trace: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trace:
            self.trace = {
                "version": TRACE_VERSION,
                "top_k": self.top_k,
                "top_p": self.top_p,
                "min_score": self.min_score,
                "rerank": "on" if self.rerank_model is not None else "off",
                "rerank_model_id": str(self.rerank_model.id) if self.rerank_model is not None else None,
                "stages_ms": {},
                "steps": [],
            }

    @property
    def reranking(self) -> bool:
        return self.rerank_model is not None and self.trace.get("rerank") == "on"

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            stages = self.trace.setdefault("stages_ms", {})
            stages[name] = stages.get(name, 0) + max(0, int((perf_counter() - started) * 1000))

    def record_step(self, step: str, *, candidates: int, selected: int) -> None:
        self.trace.setdefault("steps", []).append({"step": step, "candidates": candidates, "selected": selected})

    def mark_rerank_failed(self, error_code: str) -> None:
        self.trace["rerank"] = "failed"
        self.trace["rerank_error"] = error_code


def as_tuning(value: "RetrievalTuning | int") -> RetrievalTuning:
    """Callers that pass a bare K get the pre-CHG-486 behavior: no reranking, P has no effect."""
    return value if isinstance(value, RetrievalTuning) else RetrievalTuning(top_k=int(value))


def select_by_top_p(scores: list[float], *, top_k: int, top_p: float, min_score: float = 0.0) -> list[int]:
    """TOPKP486-002: indexes of the chunks to keep, in descending score order.

    Chunks below `min_score` are dropped first. The rest are taken in descending score; each chunk's share is its
    score divided by the total score of the chunks that passed; taking stops once the cumulative share reaches
    `top_p`. At least one chunk (when any passed) and at most `top_k` chunks are kept. `top_p >= 1` keeps the
    first `top_k`.
    """
    passed = [(score, index) for index, score in enumerate(scores) if score >= min_score]
    if not passed or top_k <= 0:
        return []
    ordered = sorted(passed, key=lambda item: (-item[0], item[1]))
    if top_p >= 1.0:
        return [index for _score, index in ordered[:top_k]]
    total = sum(score for score, _index in ordered)
    if total <= 0:
        return [ordered[0][1]]
    kept: list[int] = []
    cumulative = 0.0
    for score, index in ordered:
        kept.append(index)
        cumulative += score / total
        if len(kept) >= top_k or cumulative >= top_p - 1e-9:
            break
    return kept


def validate_top_k(value: Any) -> bool:
    return type(value) is int and TOP_K_RANGE[0] <= value <= TOP_K_RANGE[1]


def validate_top_p(value: Any) -> bool:
    return type(value) in (int, float) and TOP_P_RANGE[0] <= value <= TOP_P_RANGE[1]


def rerank_model_for_project(session: Session, project_id: UUID, qa: dict | None = None) -> AIModel | None:
    """RERANK486-005: the rerank model when the system switch, the selected model and the project switch all allow it."""
    from app.domain.system_parameter_store import question_answering_settings

    qa = qa if qa is not None else question_answering_settings(session)
    if not system_rerank_available(session, qa):
        return None
    project = session.get(Project, project_id)
    if project is None or not project.rerank_enabled:
        return None
    return session.get(AIModel, UUID(qa["retrieval_rerank_model_id"]))


def resolve_retrieval_tuning(session: Session, project_id: UUID, *, top_k: int | None = None, top_p: float | None = None,
                             min_score: float | None = None) -> RetrievalTuning:
    """TOPKP486-001/003: user values win; missing values come from the system settings read now."""
    from app.domain.system_parameter_store import question_answering_settings

    qa = question_answering_settings(session)
    return RetrievalTuning(
        top_k=int(top_k if top_k is not None else qa["retrieval_top_k"]),
        top_p=float(top_p if top_p is not None else qa["retrieval_top_p"]),
        min_score=float(min_score if min_score is not None else qa["retrieval_rerank_min_score"]),
        rerank_model=rerank_model_for_project(session, project_id, qa),
    )


def rerank_select(tuning: RetrievalTuning, query: str, items: list[Any], text_of, *, limit: int | None = None,
                  step: str) -> list[Any] | None:
    """Rerank `items` against `query` and keep those chosen by `select_by_top_p`, best first.

    Returns None when reranking is off or the rerank call failed (the trace then says `failed`); the caller keeps
    its RRF order. `limit` overrides K as the upper bound (reference expansion keeps its own maximum).
    """
    if not tuning.reranking or not items:
        return None
    from app.core.errors import AppError
    from app.domain.reranking import rerank_scores

    try:
        with tuning.stage("rerank"):
            scores = rerank_scores(tuning.rerank_model, query, [text_of(item) or "" for item in items])
    except AppError as exc:
        logger.warning("rerank_failed", extra={"error_code": exc.code, "step": step})
        tuning.mark_rerank_failed(exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 - RERANK486-005: a failing reranker never fails the answer
        logger.warning("rerank_failed", extra={"error_code": type(exc).__name__, "step": step})
        tuning.mark_rerank_failed(type(exc).__name__)
        return None
    keep = select_by_top_p(scores, top_k=limit if limit is not None else tuning.top_k, top_p=tuning.top_p, min_score=tuning.min_score)
    return [items[index] for index in keep]


def system_rerank_available(session: Session, qa: dict | None = None) -> bool:
    """RERANK486-002: the system switch is on and the selected rerank model is active."""
    from app.domain.system_parameter_store import question_answering_settings

    qa = qa if qa is not None else question_answering_settings(session)
    if qa.get("retrieval_rerank_enabled") is not True or not qa.get("retrieval_rerank_model_id"):
        return False
    model = session.get(AIModel, UUID(qa["retrieval_rerank_model_id"]))
    return model is not None and model.deleted_at is None and model.is_active and model.model_type == "Reranker"

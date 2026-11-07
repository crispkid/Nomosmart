from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RetrievalExpectation:
    query: str
    expected_document_id: str
    expected_section: tuple[str, ...] = ()
    expected_chunk_id: str | None = None


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalMetrics:
    case_count: int
    recall_at_k: float
    mean_reciprocal_rank: float
    top_k_hit_rate: float


def evaluate_retrieval(
    cases: Iterable[tuple[RetrievalExpectation, list[RetrievalHit]]],
    *,
    k: int,
) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be positive")
    prepared = list(cases)
    if not prepared:
        return RetrievalMetrics(case_count=0, recall_at_k=0.0, mean_reciprocal_rank=0.0, top_k_hit_rate=0.0)
    hit_count = 0
    reciprocal_rank = 0.0
    for expectation, hits in prepared:
        rank = next((index for index, hit in enumerate(hits[:k], start=1) if _matches(expectation, hit)), None)
        if rank is not None:
            hit_count += 1
            reciprocal_rank += 1.0 / rank
    count = len(prepared)
    rate = hit_count / count
    return RetrievalMetrics(case_count=count, recall_at_k=rate, mean_reciprocal_rank=reciprocal_rank / count, top_k_hit_rate=rate)


def _matches(expectation: RetrievalExpectation, hit: RetrievalHit) -> bool:
    if hit.document_id != expectation.expected_document_id:
        return False
    if expectation.expected_chunk_id is not None and hit.chunk_id != expectation.expected_chunk_id:
        return False
    if expectation.expected_section:
        expected = expectation.expected_section
        return hit.heading_path[: len(expected)] == expected or hit.heading_path[-len(expected) :] == expected
    return True

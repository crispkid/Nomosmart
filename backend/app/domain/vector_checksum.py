"""Checksums for stored embedding vectors (CHG-454 F454-NEGZERO-01, NEGZERO454-001).

PostgreSQL JSONB stores numbers as ``numeric``, which has no negative zero: a vector
written with ``-0.0`` reads back as ``0.0``.  New vectors are normalized before any
checksum is taken (see ``normalize_vector``).  Rows written before that fix carry a
checksum computed over ``-0.0``; ``stored_vector_matches`` accepts such a row only when
re-negating some of its zero values reproduces the stored checksum exactly.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from typing import Any

LEGACY_NEGATIVE_ZERO_LIMIT = 12


def normalize_vector(values: list[float]) -> list[float]:
    """Return the vector with every ``-0.0`` replaced by ``0.0`` (identical for similarity)."""
    return [0.0 if value == 0.0 else value for value in values]


def vector_checksum(vector: list[Any]) -> str:
    return hashlib.sha256(json.dumps(vector, separators=(",", ":")).encode("utf-8")).hexdigest()


def stored_vector_matches(vector: list[Any], expected: str | None) -> bool:
    """True when ``vector`` (as read back from JSONB) has checksum ``expected``.

    Only the sign of zero values may differ, because JSONB cannot hold ``-0.0``.
    """
    if not expected:
        return False
    if vector_checksum(vector) == expected:
        return True
    zeros = [index for index, value in enumerate(vector)
             if isinstance(value, float) and value == 0.0]
    if not zeros or len(zeros) > LEGACY_NEGATIVE_ZERO_LIMIT:
        return False
    for size in range(1, len(zeros) + 1):
        for chosen in combinations(zeros, size):
            candidate = list(vector)
            for index in chosen:
                candidate[index] = -0.0
            if vector_checksum(candidate) == expected:
                return True
    return False

"""CHG-442 CHUNK442-003: which active chunks share source text (manual chunks may overlap existing ones)."""
from __future__ import annotations

from app.db.models import Chunk


def chunk_overlaps(chunks: list[Chunk]) -> tuple[dict[str, list[str]], int]:
    """Return {chunk_id: [overlapping chunk ids]} and the number of overlap groups (connected sets of 2+ chunks).

    Uses the canonical markdown offsets kept on each chunk; chunks without both offsets are ignored.
    """
    spans = sorted(((c.start_offset, c.end_offset, str(c.id)) for c in chunks
                    if type(c.start_offset) is int and type(c.end_offset) is int and c.end_offset > c.start_offset))
    overlaps: dict[str, set[str]] = {}
    active: list[tuple[int, str]] = []
    for start, end, cid in spans:
        active = [(e, other) for e, other in active if e > start]
        for _e, other in active:
            overlaps.setdefault(cid, set()).add(other)
            overlaps.setdefault(other, set()).add(cid)
        active.append((end, cid))
    seen: set[str] = set()
    groups = 0
    for cid in overlaps:
        if cid in seen:
            continue
        groups += 1
        stack = [cid]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(overlaps[node] - seen)
    return {cid: sorted(others) for cid, others in overlaps.items()}, groups

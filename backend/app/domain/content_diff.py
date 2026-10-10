"""Exact source rebasing. No fuzzy lookup or duplicate-text first-match fallback."""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from difflib import SequenceMatcher
from hashlib import sha256


def text_digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EqualRange:
    old_start: int
    new_start: int
    length: int
    reliable: bool = True


def equal_source_ranges(old: str, new: str) -> list[EqualRange]:
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    old_offsets, new_offsets = [0], [0]
    for line in old_lines:
        old_offsets.append(old_offsets[-1] + len(line))
    for line in new_lines:
        new_offsets.append(new_offsets[-1] + len(line))
    result = []
    before_counts, after_counts = Counter(old_lines), Counter(new_lines)
    # Match whole lines first so long repeated documents don't trigger a
    # character-level quadratic comparison. Refine only bounded replacements.
    for kind, a, b, c, d in SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        left, right = old_offsets[a], new_offsets[c]
        if kind == "equal":
            for old_index,new_index in zip(range(a,b),range(c,d),strict=True):
                line = old_lines[old_index]
                reliable = not (line.strip() and max(before_counts[line],after_counts[line]) > 1
                                and before_counts[line] != after_counts[line])
                value = EqualRange(old_offsets[old_index],new_offsets[new_index],len(line),reliable)
                if result and result[-1].reliable == reliable and result[-1].old_start+result[-1].length == value.old_start and result[-1].new_start+result[-1].length == value.new_start:
                    previous = result.pop()
                    result.append(EqualRange(previous.old_start,previous.new_start,previous.length+value.length,reliable))
                else:
                    result.append(value)
        elif kind == "replace" and max(old_offsets[b] - left, new_offsets[d] - right) <= 32768:
            for match in SequenceMatcher(None, old[left:old_offsets[b]], new[right:new_offsets[d]], autojunk=False).get_matching_blocks():
                if match.size:
                    result.append(EqualRange(left + match.a, right + match.b, match.size))
    return result


def rebase_range(ranges: list[EqualRange], start: int | None, end: int | None) -> tuple[int, int] | None:
    if start is None or end is None or start < 0 or end <= start:
        return None
    for match in ranges:
        if match.reliable and match.old_start <= start and end <= match.old_start + match.length:
            target = match.new_start + start - match.old_start
            return target, target + end - start
    return None

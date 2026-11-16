"""CHG-436 MTVAL436-001..007: multi-turn scenarios in CSV validation runs.

Rows that share a `conversation_key` form one scenario and run in `turn` order as one
multi-turn conversation; rows without both fields stay single-turn as before.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from app.core.errors import AppError


def validate_scenarios(questions: Sequence[Any], *, max_turns: int) -> None:
    """Refuse the whole file when a scenario is malformed; rows are 1-based CSV data rows."""

    problems: list[dict[str, Any]] = []
    groups: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    for row, question in enumerate(questions, start=1):
        key = (question.conversation_key or "").strip() or None
        if (key is None) != (question.turn is None):
            problems.append({"conversation_key": key, "rows": [row], "reason": "conversation_key_and_turn_required_together"})
            continue
        if key is not None:
            groups[key].append((row, question))
    for key, members in groups.items():
        rows = [row for row, _question in members]
        turns = [question.turn for _row, question in members]
        if len(set(turns)) != len(turns):
            problems.append({"conversation_key": key, "rows": rows, "reason": "duplicate_turn"})
        elif sorted(turns) != list(range(1, len(turns) + 1)):
            problems.append({"conversation_key": key, "rows": rows, "reason": "turns_not_consecutive_from_1"})
        if len(members) > max_turns:
            problems.append({"conversation_key": key, "rows": rows, "reason": "too_many_turns", "max_turns": max_turns})
        scopes = {tuple(sorted(str(value) for value in question.selected_document_ids)) if question.selected_document_ids else None
                  for _row, question in members}
        if len(scopes) > 1:
            problems.append({"conversation_key": key, "rows": rows, "reason": "selected_document_ids_differ"})
    if problems:
        raise AppError("validation_scenario_invalid", "Multi-turn scenarios in the CSV are invalid", status_code=422,
                       details={"problems": problems})


def normalized_key(value: str | None) -> str | None:
    return (value or "").strip() or None


def execution_order(items: Iterable[Any]) -> list[Any]:
    """Single-turn rows keep CSV order; a scenario runs in turn order where its first row appears."""

    items = list(items)
    first_ordinal: dict[str, int] = {}
    for item in items:
        if item.conversation_key is not None:
            first_ordinal[item.conversation_key] = min(first_ordinal.get(item.conversation_key, item.input_ordinal), item.input_ordinal)

    def position(item: Any) -> tuple[int, int, int]:
        if item.conversation_key is None:
            return (item.input_ordinal, 0, 0)
        return (first_ordinal[item.conversation_key], item.turn_index, item.input_ordinal)

    return sorted(items, key=position)


def scenario_summary(items: Iterable[Any]) -> dict[str, Any] | None:
    """A scenario passes when every current turn passed (MTVAL436-007)."""

    statuses: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.conversation_key is not None:
            statuses[item.conversation_key].append(item.status)
    if not statuses:
        return None
    passed = sum(1 for values in statuses.values() if values and all(status == "passed" for status in values))
    return {"scenario_count": len(statuses), "passed_scenario_count": passed, "pass_rate": round(passed / len(statuses), 4)}

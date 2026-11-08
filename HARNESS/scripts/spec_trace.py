#!/usr/bin/env python3
"""Validate active specification-to-test traceability without historical leakage."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


CHANGE_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(CHG-\d+)\s*\|")
STABLE_ID = re.compile(r"\b(?:[A-Z][A-Z0-9]*)(?:-[A-Z0-9]+)*-\d{3}\b")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
INCOMPLETE = re.compile(r"^\s*(?:TBD|TODO|待定|待補)(?:\s*[:：-].*)?\s*$", re.IGNORECASE)
PENDING = re.compile(r"\b(?:pending|planned)\b|待核准|規劃中", re.IGNORECASE)
DONE = re.compile(r"\b(?:implemented|complete|completed|verified|accepted)\b|已完成|已驗證", re.IGNORECASE)
PARTIAL = re.compile(r"\b(?:partial|baseline|foundation|reopened)\b|部分|基線", re.IGNORECASE)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def active_change(changelog: str) -> tuple[str, str, str]:
    first: tuple[str, str, str] | None = None
    for line in changelog.splitlines():
        match = CHANGE_ROW.match(line)
        if not match:
            continue
        date, change_id = match.groups()
        if first is None:
            first = (change_id, date, line)
    if first is None:
        fail("SPEC_CHANGELOG.md has no dated CHG-NNN row.")
    return first


def active_spec_section(specification: str, change_id: str) -> str:
    lines = specification.splitlines()
    start = None
    level = None
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if match and change_id in match.group(2):
            start = index
            level = len(match.group(1))
            break
    if start is None or level is None:
        fail(f"SPECIFICATION.md has no active section headed by {change_id}.")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = HEADING.match(lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def trace_rows(traceability: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in traceability.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {"Requirement ID", "---"}:
            continue
        if STABLE_ID.fullmatch(cells[0]):
            rows.append(cells)
    return rows


def main(root_argument: str) -> None:
    root = Path(root_argument).resolve()
    required_files = {
        name: root / name
        for name in (
            "SPECIFICATION.md",
            "SPEC_CHANGELOG.md",
            "DEVELOPMENT_PLAN.md",
            "TEST_PLAN.md",
            "TRACEABILITY.md",
        )
    }
    missing = [name for name, path in required_files.items() if not path.is_file()]
    if missing:
        fail(f"Missing traceability control files: {', '.join(missing)}")

    texts = {name: path.read_text(encoding="utf-8") for name, path in required_files.items()}
    change_id, change_date, changelog_row = active_change(texts["SPEC_CHANGELOG.md"])
    if INCOMPLETE.search(change_date) or INCOMPLETE.search(changelog_row):
        fail(f"Active change {change_id} has a missing/TBD owner or date.")

    active_section = active_spec_section(texts["SPECIFICATION.md"], change_id)
    required_ids = {
        stable_id
        for stable_id in STABLE_ID.findall(active_section)
        if not stable_id.startswith("CHG-")
    }

    rows = trace_rows(texts["TRACEABILITY.md"])
    identifiers = [row[0] for row in rows]
    duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        fail(f"TRACEABILITY.md contains duplicate requirement IDs: {', '.join(duplicates)}")

    by_identifier = {row[0]: row for row in rows}
    missing_ids = sorted(required_ids - by_identifier.keys())
    if missing_ids:
        fail(
            f"TRACEABILITY.md is missing active {change_id} requirement mappings: "
            f"{', '.join(missing_ids)}"
        )

    active_rows = [
        row
        for row in rows
        if row[0] in required_ids or any(change_id in cell for cell in row)
    ]
    if not active_rows:
        fail(f"TRACEABILITY.md has no row mapped to active change {change_id}.")

    for row in active_rows:
        if len(row) < 6:
            fail(f"Trace row {row[0]} is missing required columns.")
        labels = ("Specification Section", "Implementation Area", "Tests", "Harness Command", "Status")
        for offset, label in enumerate(labels, start=1):
            value = row[offset] if offset < len(row) else ""
            if not value or INCOMPLETE.search(value):
                fail(f"Trace row {row[0]} has a missing or TBD {label} mapping.")
        status = row[5]
        if PENDING.search(status) and DONE.search(status) and not PARTIAL.search(status):
            fail(f"Trace row {row[0]} has contradictory planned and completed status: {status}")

    if re.search(r"Gate 4 approved", changelog_row, re.IGNORECASE):
        for row in active_rows:
            if re.search(r"Gate 4 pending|Gate 4 remains pending", row[5], re.IGNORECASE):
                fail(f"Trace row {row[0]} contradicts approved Gate 4 for {change_id}.")

    print(
        f"ok: {change_id} has {len(required_ids)} active requirement mappings, "
        f"unique stable IDs and complete trace columns"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: spec_trace.py ROOT_DIR")
    main(sys.argv[1])

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


SELECTOR_COLUMNS = {
    "project_id": "project_id",
    "document_version_id": "document_version_id",
    "created_by": "created_by",
    "conversation_id": "conversation_id",
}


@dataclass(frozen=True)
class BackfillPlan:
    scope_mode: str
    selectors: dict[str, str]
    apply_changes: bool
    expected_count: int | None
    sample_limit: int


@dataclass(frozen=True)
class BackfillResult:
    candidate_count: int
    updated_count: int
    samples: list[dict]


def parse_args(argv: list[str] | None = None) -> BackfillPlan:
    parser = argparse.ArgumentParser(
        description="Safely classify legacy chat_records.scope_mode rows for an explicit bounded scope.",
    )
    parser.add_argument("--scope-mode", required=True, choices=("published", "document_staging"))
    parser.add_argument("--project-id", type=_uuid_arg)
    parser.add_argument("--document-version-id", type=_uuid_arg)
    parser.add_argument("--created-by", type=_uuid_arg)
    parser.add_argument("--conversation-id", type=_uuid_arg)
    parser.add_argument("--apply", action="store_true", help="Apply the update. The default is dry-run.")
    parser.add_argument("--expected-count", type=int, help="Required with --apply; aborts unless candidate count matches exactly.")
    parser.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args(argv)
    selectors = {
        "project_id": args.project_id,
        "document_version_id": args.document_version_id,
        "created_by": args.created_by,
        "conversation_id": args.conversation_id,
    }
    selectors = {key: value for key, value in selectors.items() if value}
    if not selectors:
        parser.error("at least one bounded selector is required")
    if args.apply and args.expected_count is None:
        parser.error("--expected-count is required with --apply")
    if args.expected_count is not None and args.expected_count < 0:
        parser.error("--expected-count must be zero or greater")
    if args.sample_limit < 1 or args.sample_limit > 100:
        parser.error("--sample-limit must be between 1 and 100")
    return BackfillPlan(
        scope_mode=args.scope_mode,
        selectors=selectors,
        apply_changes=args.apply,
        expected_count=args.expected_count,
        sample_limit=args.sample_limit,
    )


def build_where_clause(selectors: dict[str, str]) -> tuple[str, dict[str, str]]:
    if not selectors:
        raise ValueError("at least one bounded selector is required")
    clauses = ["scope_mode IS NULL"]
    params: dict[str, str] = {}
    for key, value in selectors.items():
        column = SELECTOR_COLUMNS.get(key)
        if column is None:
            raise ValueError(f"unsupported selector: {key}")
        clauses.append(f"{column} = :{key}")
        params[key] = value
    return " AND ".join(clauses), params


def ensure_scope_column(conn: Connection) -> None:
    exists = conn.execute(
        text(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_name = 'chat_records'
              AND column_name = 'scope_mode'
            """
        )
    ).scalar()
    if not exists:
        raise RuntimeError("chat_records.scope_mode is missing; apply V016 before running scoped history backfill")


def run_backfill(conn: Connection, plan: BackfillPlan) -> BackfillResult:
    ensure_scope_column(conn)
    where_clause, params = build_where_clause(plan.selectors)
    candidate_count = int(
        conn.execute(
            text(f"SELECT count(*) FROM chat_records WHERE {where_clause}"),
            params,
        ).scalar()
        or 0
    )
    samples = [
        dict(row)
        for row in conn.execute(
            text(
                f"""
                SELECT id, project_id, document_version_id, created_by, conversation_id, created_at, left(question, 80) AS question
                FROM chat_records
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :sample_limit
                """
            ),
            {**params, "sample_limit": plan.sample_limit},
        ).mappings()
    ]
    if not plan.apply_changes:
        return BackfillResult(candidate_count=candidate_count, updated_count=0, samples=samples)
    if candidate_count != plan.expected_count:
        raise RuntimeError(f"candidate count {candidate_count} did not match expected count {plan.expected_count}; no rows updated")
    updated_count = int(
        conn.execute(
            text(f"UPDATE chat_records SET scope_mode = :scope_mode WHERE {where_clause}"),
            {**params, "scope_mode": plan.scope_mode},
        ).rowcount
        or 0
    )
    return BackfillResult(candidate_count=candidate_count, updated_count=updated_count, samples=samples)


def main(argv: list[str] | None = None) -> int:
    plan = parse_args(argv)
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())
    context = engine.begin() if plan.apply_changes else engine.connect()
    with context as conn:
        result = run_backfill(conn, plan)
        _print_result(plan, result)
    return 0


def _uuid_arg(value: str) -> str:
    return str(UUID(value))


def _print_result(plan: BackfillPlan, result: BackfillResult) -> None:
    mode = "apply" if plan.apply_changes else "dry-run"
    print(f"mode={mode}")
    print(f"scope_mode={plan.scope_mode}")
    print(f"candidate_count={result.candidate_count}")
    print(f"updated_count={result.updated_count}")
    for row in result.samples:
        print(
            "sample "
            f"id={row['id']} "
            f"version={row['document_version_id']} "
            f"user={row['created_by']} "
            f"conversation={row['conversation_id']} "
            f"created={row['created_at']} "
            f"question={row['question']!r}"
        )


if __name__ == "__main__":
    raise SystemExit(main())

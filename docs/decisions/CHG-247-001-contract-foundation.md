# CHG-247-001 — Shared Contract Foundation

- Status: accepted by the CHG-247 Gate 4 approval
- Date: 2026-07-26
- Requirements: `PERM-005`, `IDEMP-001`, `OPS-002`, `TRACE-002`, `I18N-004`

## Decision

Backend behavior uses one stable vocabulary for error identities, audit actions,
idempotency states/transitions and the ten fixed Project/Document capability
keys. Capabilities are deny-by-default presentation projections; every mutation
still performs current Backend authorization. Audit and error identifiers are
machine-safe and never contain secret values.

Frontend visible copy is guarded through an AST-aware ESLint rule. Its allowlist
contains only reviewed exact literals in the typed protocol, stable-field,
technical-ID and external-brand categories. Regex scanning remains a quick
secondary guard.

Governance and coverage evidence are source-bound. Trace rows require unique
stable requirement IDs and complete mapping columns. Coverage evidence binds
the canonical full-suite command to the commit, tracked/untracked source/test
diff, suite manifest, timestamps, report path and SHA-256.

## Consequences

- New capability keys require a specification change; clients cannot infer
  missing keys.
- A stale or manually changed coverage report cannot satisfy the 80% gate.
- General English or Chinese UI copy cannot be hidden in a broad allowlist.

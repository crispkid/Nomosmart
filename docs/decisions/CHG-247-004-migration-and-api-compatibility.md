# CHG-247-004 — Migration And API Compatibility

- Status: accepted by the CHG-247 Gate 4 approval
- Date: 2026-07-26
- Requirements: `MIGRATE-001`, `API-COMPAT-001`, `API-PAGE-001`

## Decision

All CHG-247 schema changes are additive Flyway migrations. Existing supported
schemas use expand/contract for capability, evidence, idempotency and cursor
contracts. Backfill either derives verifiable evidence or records an explicit
legacy/unavailable state; it never fabricates evidence or broad permissions.

The exact canonical paths, methods, status codes and envelopes are maintained in
`API_COMPATIBILITY.md`. Stable pagination uses signed opaque cursors bound to
endpoint, actor, scope, filters and sort. Offset values wrapped in an opaque
string are not compatible implementations.

The scoped graph removal is the intentional security-breaking exception. No
unscoped compatibility alias is permitted, and rollback preflight rejects images
that would reopen one.

# CHG-247-002 — Scoped Knowledge Graph Cutover

- Status: accepted by the CHG-247 Gate 4 approval
- Date: 2026-07-26
- Requirement: `GRAPH-008`

## Decision

NomoSmart retains one unified internal graph model but exposes graph content only
through explicit Project or Document scope. The former
`/api/v1/knowledge-graph`, `/neighbors` and `/paths` routes and the global
frontend preview are removed without an authorization-weak compatibility alias.
System Management or System Admin status grants no content bypass.

Project graph, neighbor and path calls authorize the Project first. A
cross-project edge may be returned only when the caller can view both ends.
Document/version evidence uses the already-authorized nested Project/Document
identity.

## Rollout And Rollback

The Backend 404 cutover and scoped client are deployed together or through a
blue-green boundary that proves the old routes absent before traffic switches.
An image that re-registers an unscoped route is rollback-incompatible.

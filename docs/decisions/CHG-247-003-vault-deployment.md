# CHG-247-003 — Bundled And External Vault Deployment

> **Historical decision — superseded by CHG-260 / SECRET-002.** Vault is no longer a NomoSmart runtime or deployment dependency. This record is retained only for audit history; current installations use operator-owned Kubernetes/Docker Secrets as defined in Specification section 10.17 and [`deploy/README.md`](../../deploy/README.md).

- Status: accepted by the CHG-247 Gate 4 approval
- Date: 2026-07-26
- Requirements: `SECRET-001`, `DEPLOY-011`, `OCR-003`

## Decision

Vault KV v2 is the only formal runtime secret resolver. The package exposes
`vault.mode=bundled|external` and defaults new installations to bundled mode.
Both modes use TLS/CA verification, canonical `vault://mount/path#field`
references, distinct Backend/Worker identities and fail-closed readiness.

Bundled Compose is a persistent TLS-only single-node Integrated Raft server and
is explicitly non-HA. Bundled production Helm vendors a pinned official Vault
chart and runs three Raft servers with independent retained PVCs, persistent
audit storage, hard hostname anti-affinity and a `minAvailable >= 2` PDB.
Neither mode creates public Vault ingress, host ports or a product UI.

Auto-unseal with operator KMS/HSM/Transit is the production default. Shamir 5/3
is the self-contained alternative. The package never retains unseal/recovery
shares, root/bootstrap tokens, auto-unseal credentials or resolved secrets.

## Consequences

Existing encrypted credentials are explicit read-only migration inputs and are
never copied automatically. Release checks must cover initialization,
bootstrap/root revocation, seal/quorum failure, snapshot/restore,
upgrade/rollback, image/chart provenance, vulnerability scanning and SBOM.

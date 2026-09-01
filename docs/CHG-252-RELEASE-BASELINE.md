# CHG-252 Clean Release Baseline

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

This record defines the source boundary for the clean CHG-252 release branch.
It does not authorize image publication, Docker Scout processing, Kubernetes
mutation or factory deletion.

## Source boundary

- Git base: `b02336408a756ba5d48844d32c345d5571594941`
  (`origin/main`, commit subject `day 15`).
- Release branch: `codex/chg-252-production-ha-release`.
- The release baseline includes the approved CHG-247 through CHG-252 dependency
  chain because CHG-252 Helm, Vault, OpenSearch, guided installer, schema V042,
  security and signed-release contracts are not independently buildable from
  the old Git base.
- The shared `main` worktree remains untouched: no stash, reset, checkout,
  deletion or implicit staging is permitted.

## Included source classes

- specification, changelog, development/test plans and traceability;
- Backend, Frontend and SQL migration source needed by the approved baseline;
- Docker Compose, Helm, package, Vault, OpenSearch, release and guided-installer
  source;
- automated tests, harness policy and operator/runbook documentation; and
- vendored dependency artifacts explicitly covered by checksum/provenance
  policy, including the locked Vault chart.

## Mandatory exclusions

- `.git`, `.playwright-cli`, `test-results`, coverage output and browser
  screenshots;
- `node_modules`, `.next`, Python virtual environments, bytecode and caches;
- `.env`, generated runtime packages, kubeconfig, Docker credential stores,
  Vault custody/root/share material, TLS private keys and Kubernetes Secrets;
- visual design/branding/poster working assets, because they are not runtime
  dependencies of CHG-252; and
- any unclassified file that fails release source hygiene or cannot be traced
  to the approved baseline.

## Acceptance before commit

The independent worktree must be clean after committing and must pass source
hygiene, governance/traceability, secret-pattern review, Python syntax,
Frontend lint/build, Helm lint/render, Docker config, installer tests, signed
release contract tests and the CHG-251/252 focused suite. The existing
Frontend/Backend 80% coverage, all-runtime CVE/SPDX, disposable live HA/PITR
and exact-UAT factory gates remain separate and cannot be reclassified as
passing merely because the source branch is clean.

## Clean-builder findings

The 2026-08-05 clean-builder run found and corrected two release-test isolation
defects: disposable contract tests now generate their own SPDX input, and the
release command captures freshly produced coverage evidence before assembling
the closed package. The repository-root Migration Docker context now denies all
paths except the required migration SQL, Dockerfile and secret-file entrypoint.
Dependency audit also required upgrading the locked Backend runtime to
`cryptography` 50.0.0. Production `npm audit`, `pip-audit` and Bandit then
passed; container-image scanning remains separately authorized and open.

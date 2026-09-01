# NomoSmart Release Readiness Checklist

This checklist is the release handoff record for Docker Compose and Helm
deployments. Complete it for every production-oriented release candidate.

## Required Harness Gates

Run these commands from the repository root and attach the output to the release
record:

```bash
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh coverage:check
./HARNESS/harness.sh security:dependencies
./HARNESS/harness.sh i18n:hardcoded
./HARNESS/harness.sh i18n:ast
./HARNESS/harness.sh test:security-simplification
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:config-policy
```

If a required local tool is unavailable, record the exact command, the missing
tool, the owner, and the follow-up date. Do not mark the gate as passed.

## Security And SBOM Entry Points

Use the selected organization-approved tools. Until a single toolchain is
mandated, the release record must show which of these entry points were used or
why they were unavailable:

- Frontend dependencies: `npm audit --omit=dev` from `frontend/`.
- Backend dependencies: `pip-audit` or an equivalent Python dependency scanner
  against the locked backend environment.
- Container images: `trivy image`, `grype`, Docker Scout, or an equivalent image
  scanner for frontend and backend images.
- SBOM: `syft packages`, `docker sbom`, or an equivalent SPDX/CycloneDX
  generator for frontend and backend images.
- Static analysis: organization-approved SAST for Python, TypeScript and Docker
  files.

High or critical findings require either a fix before release or a written human
risk acceptance with owner, expiry date, affected component and compensating
controls.

## Backup And Restore

Before production upgrade:

- Confirm PostgreSQL backup completion and restore test result.
- Confirm object storage backup or versioning policy for document originals and
  generated artifacts.
- Confirm OpenSearch index snapshot or rebuild procedure.
- Confirm Neo4j backup, dump, or graph rebuild procedure.
- Confirm Keycloak realm export or managed identity-provider recovery plan.
- Confirm Kubernetes/Docker Secret backup, access-control and rotation procedure
  without recording Secret values in release evidence.
- Record backup timestamps, storage location, retention period and operator.

Restore validation must use a disposable environment or documented dry-run. A
release cannot rely on an untested backup procedure.

## Rollback

Docker Compose rollback:

```bash
docker compose pull
docker compose up -d
docker compose logs -f backend
```

Use the previous image tags and previous `deploy/docker/nomosmart.env` revision.
Database migrations are append-only; if a migration is not backward compatible,
document the manual data rollback or forward-fix plan before deployment.

For CHG-237 V030, code-only rollback is prohibited after a deleted Local-role
name is reused. The supported recovery paths are a forward fix or a complete
restore of the pre-deployment PostgreSQL backup with the compatible prior
application version; a previous image must not run against that post-V030
database state.

For CHG-239 V031, code-only rollback is prohibited after any archive cleanup
has deleted unfinished PostgreSQL or external S3/OpenSearch/Neo4j artifacts.
Confirm there are no queued, running or failed `project_archive_runs` before a
release transition. Recovery requires a forward fix or a coordinated restore
of the pre-archive PostgreSQL and external-store backups with the compatible
application version.

Helm rollback:

```bash
helm history nomosmart
helm rollback nomosmart <REVISION> --wait --timeout 20m
kubectl rollout status deployment/<release>-backend
kubectl logs deployment/<release>-backend
```

Rollback must preserve externally managed Secrets. Do not roll back by editing
committed values with real credentials.

## Log Inspection

After deploy or rollback, inspect:

- Flyway migration Job/service and deployment-bootstrap Job/service completion.
- Bootstrap evidence for the current Compose release ID or Helm revision.
- Backend health and readiness responses.
- Backend structured logs for startup, migration and adapter errors.
- Worker logs for queue connection and job failures.
- Frontend logs for failed backend proxy calls.
- PostgreSQL, OpenSearch, Neo4j, object storage and Keycloak connectivity.
- Runtime Secret mount/readiness fingerprints and workload connectivity state.
  Do not log mounts, paths, tokens or values.

Logs must not contain passwords, tokens, client secrets, API keys, private keys
or document content beyond intentional metadata.

## Known Gaps And Risk Acceptance

Every release candidate must include a known-gap table:

| Gap | Requirement | Impact | Owner | Target Date | Risk Accepted By |
| --- | --- | --- | --- | --- | --- |
| Application-tier HA live acceptance pending | DEPLOY-009 / CHG-247 | Production values, PDB, hard cross-node separation, zero-unavailable rollout and graceful-drain configuration are implemented and pass static Helm policy; real multi-node continuous-traffic, node-drain, redelivery and rollback evidence is still required | Platform Engineering | Before formal Release | Not accepted |
| Report datastore paging/export live acceptance pending | REPORT-014 / CHG-247 | Summary now uses stable datastore count/page queries and CSV uses configured server-cursor batches, pre-header validation, disconnect/timeout cancellation and start/result/actual-row-count audit. Production-scale PostgreSQL query-plan, bounded-memory, slow-client, timeout and disconnect evidence is still required | Application Engineering | Before formal Release | Not accepted |
| Validation immutable-manifest live acceptance pending | RAG-019 / CHG-247 | V041 and the scoped create/runner contract persist immutable input identity/order/content hashes and an exact hashed execution manifest with safe public projection. Fresh/upgrade/rerun migration, real Worker/provider execution, configuration-change refusal and legacy-run evidence are still required | Application Engineering | Before formal Release | Not accepted |
| Live CHG-247 backend and browser suites pending | TEST-002, TEST-003 / CHG-247 | The complete Backend suite cannot collect while the configured Keycloak endpoint is offline; browser E2E also lacks live URLs and Peter/John credentials | Application Engineering / Identity Engineering | Before formal Release | Not accepted |
| CHG-260 live migration and security-simplification acceptance pending | SECRET-002, UPLOAD-SEC-003, DEPLOY-019, AUTH-020 | Static/focused, package, installer, deployment and security checks pass, but real disposable mounted-Secret consumers, direct S3/PostgreSQL ingestion, bundled password-only Keycloak upgrade, external-Provider MFA preservation and restart evidence are still required | Application Engineering / Platform Engineering / Identity Engineering | Before formal Release | Not accepted |
| Production backup custody pending | DEPLOY-004..005 | Local PostgreSQL/Keycloak logical backups and Redis/RustFS/OpenSearch/Neo4j offline backups passed isolated restore rehearsals, but the acceptance copy is not encrypted or copied to an operator-managed off-host repository | Platform Engineering | 2026-07-31 | Not accepted |
| Full-stack Compose failure/rollback pending | DEPLOY-002..004 | Complete fresh bundled stack, migration/bootstrap, trusted-CA onboarding, restart and retained state passed; deliberate component-failure and image/config rollback acceptance remain open | Platform Engineering | 2026-07-31 | Not accepted |
| Bundled Keycloak LDAP/AD federation pending | AUTH-012 | Operator must configure real non-production LDAPS/AD provider, mappers and sync before identity acceptance | Identity Engineering | 2026-07-31 | Not accepted |
| Frontend/backend coverage below 80% | TEST-001, TEST-005 | CHG-260 Frontend behavior/component tests pass, but V8 line coverage is `7.33%`; fresh Backend coverage is blocked by the unavailable TEST-002 live stack | Application Engineering | Before formal Release | Not accepted |
| Container scan and SBOM pending | SECRET-002, DEPLOY-019 | Locked npm/Python dependency audits and high-severity Backend static analysis pass with no known production dependency or high-severity finding; release images still require an approved container scan and retained SPDX/CycloneDX SBOM | Platform Engineering / Security Engineering | Before formal Release | Not accepted |
| Real model-provider success configuration pending | CONNTEST-001, PUBLIC-API-003, EMBED-003 | AI/OCR/Embedding success, provider-delta SSE timing and canonical provider call-count acceptance remain unavailable | Application Engineering | 2026-07-31 | Not accepted |
| Interactive fresh-reauth browser acceptance pending | OIDC-REAUTH-001 | Normal OIDC E2E is proven, but dedicated fresh-reauth callback/replay evidence is incomplete | Identity Engineering | 2026-07-31 | Not accepted |
| Neo4j Community native users are admin-equivalent | DEPLOY-007 / CHG-243 | Bundled Community cannot enforce role-level least privilege. Built-in `neo4j` bootstrap and `nomosmart` application credentials provide rotation and audit attribution only. Internal-only ports, service-specific NetworkPolicy, bootstrap-only admin Secret mounts, independent rotation and explicit readiness evidence are mandatory compensating controls. | Platform Engineering | Review on every Neo4j edition or network-boundary change | Peter, 2026-07-20 |

Unset owners, missing target dates, or undocumented high/critical risks block
release handoff.

CHG-243 is a narrowly scoped standing product exception, not permission to
waive any compensating control or another service's least-privilege boundary.
Missing Neo4j network/Secret boundaries or missing
`neo4j_community_admin_equivalent` evidence still blocks production.

## CHG-260 Current Security Baseline

- [x] Deployment contains no scanner or external secret-server workload, image,
  volume, health check, network policy or installer stage.
- [x] Backend and Worker mount the runtime Kubernetes Secret read-only with
  `0400` files; Compose uses `/run/secrets`.
- [x] First-use peripheral defaults and bootstrap exceptions match CHG-260;
  production rotation owner and timing are recorded.
- [ ] Keycloak browser login is password-only and the identity checkpoint
  validates real login plus directory group/role mapping.
- [ ] Upload and remote-sync samples write canonical objects and start
  extraction without scan/quarantine records; orphan compensation is verified.

The sections below are historical evidence for earlier releases. Their removed
service/scanner/authentication behavior is superseded by CHG-260 and must not be
used as the current deployment runbook.

## CHG-243/CHG-244 Sequential Packaging Evidence (Historical)

Recorded 2026-07-20:

- Fresh complete Compose passed all bundled service, Flyway 13.0.0/schema `032`,
  bootstrap, trusted-CA OIDC, Peter-entered password/TOTP, System Admin mapping,
  retained-volume restart and SSO revalidation checks. Compose was then stopped
  without deleting its state before Minikube started.
- Docker-driver profile `nomosmart-acceptance` publishes every node port only on
  `127.0.0.1`; no complete Compose workload runs concurrently.
- Helm generation `63c04a94b7db51a7` completed its revision 3 onboarding,
  revision 4 upgrade, revision 5 rollback-to-3 and retained-PVC uninstall. A
  clean release history now has revision 1 deployed in namespace
  `nomosmart-acceptance`; all eleven long-running Pods are ready, both new
  revision-scoped Jobs completed, the same six PV identities are Bound, and
  verified Portal/OIDC/backend requests return 200 from `127.0.0.1` without TLS
  bypass.
- Live Helm acceptance found and fixed exact Secret-byte delivery, deterministic
  numeric non-root application/migration identities, the bounded official
  ClamAV startup capability set, the packaged RustFS image reference, first-use
  readiness Secret wiring and NetworkPolicy-safe OpenSearch self-readiness.
- An OpenSearch validation error printed the rejected prior generation's old
  admin credential. That failed namespace was deleted, the entire prior
  generation was replaced, and the exposed rejected directory was permanently
  removed. No current generation Secret was printed.
- Peter trusted the Helm generation's distinct edge CA and personally completed
  the password/TOTP actions. Portal OIDC returned to `/`, System Management was
  accessible as `NomoSmart Administrator`, and the live Keycloak Admin API
  reported a local enabled account, System Admin mapping, zero remaining
  required actions and an OTP credential. No new password, OTP code or seed was
  captured, and no browser warning was bypassed.
- Helm Frontend and Backend were rolled out after onboarding. Both replacements
  became ready with zero restarts, the existing browser session still reached
  System Management, and Portal/OIDC/backend readiness returned 200 from
  `127.0.0.1` using the packaged active CA. All other long-running Pods remained
  ready; the migration/bootstrap Jobs remained succeeded and no Compose service
  was running concurrently.
- Before lifecycle mutation, PostgreSQL `nomosmart` and `keycloak` logical dumps
  were restored into isolated databases. Redis, RustFS and OpenSearch offline
  PVC archives were restored into isolated PVCs and started as temporary
  services; Neo4j Community used official `neo4j-admin dump/load` into an
  isolated PVC. Every restored service returned its unique non-secret marker.
  Temporary Pods/PVCs and live markers were removed after verification.
- The ignored local backup is
  `deploy/package/generated/helm/current/backups/helm-rev3-20260720T150830Z`.
  Every artifact and its manifest is mode `0600`; `SHA256SUMS` passed. Retention
  is until operator-approved deletion. This acceptance copy is not encrypted or
  off-host and therefore does not close production backup-custody policy.
- Helm revision 4 reran migration/bootstrap and retained every marker. Rollback
  created revision 5 targeting the historical revision 3 manifest; newly
  restarted application Pods passed the target `nomosmart-3` readiness evidence.
  Uninstall removed the release while Portal returned 404, left all six PVCs
  and four external Secret/TLS resources intact, and a fresh revision 1 install
  created `nomosmart-1` evidence while reusing the exact prior PV identities.
  Flyway remained `032`; Keycloak retained the changed password state, OTP
  credential, zero required actions and System Admin mapping.
- A fresh in-app Browser automation instance did not inherit the earlier CA
  trust and correctly refused the post-reinstall page. No warning was bypassed
  and no credential was re-entered; packaged-CA HTTPS plus Keycloak Admin API
  evidence was used for post-reinstall verification. The earlier trusted-CA
  browser onboarding remains accepted.
- Specification/plan/test gates, focused deployment/initialization/Secret tests,
  frontend OIDC tests, lint/build, backend syntax, Docker config, Helm lint and
  deployment policy pass. Full Backend tests cannot run while the required
  direct Compose Keycloak endpoint is stopped under the one-runtime rule;
  frontend aggregate coverage is 6.51%, so the 80% release gate remains failed.

## CHG-216 Batch A Evidence

Recorded 2026-07-12:

- `./HARNESS/harness.sh security:dependencies`: passed; npm and backend locked
  production dependencies reported no known vulnerabilities.
- Frontend security versions: Next.js `16.2.10`, PostCSS `8.5.10` override.
- Backend security versions: cryptography `49.0.0`, Paramiko `5.0.0`.
- OSV `CVE-2026-44405` affects Paramiko through 4.0.0; the locked 5.0.0 release
  is outside the affected versions, so no temporary SFTP risk acceptance is
  required for this advisory.
- `frontend:lint`, `frontend:build`, `test:frontend`, `backend:syntax` and the
  focused CHG-216 production configuration tests passed.
- Backend production settings now reject all-zero encryption keys, disabled
  scanner, local/non-HTTPS OIDC/CORS/service URLs, disabled required staging
  writes, disabled TLS verification and missing/placeholder production secrets.
- Helm base values are development-oriented. The production overlay supplies
  HTTPS/TLS/scanner/live-write/ingress TLS settings and is constrained by
  `values.schema.json`.
- Helm lint, container scanning and SBOM generation remain blocked by the tool
  gaps recorded above and are not marked passed.
- Full Backend live regression was attempted outside the sandbox and blocked by
  the configured local Keycloak endpoint refusing the service-token connection;
  the result is unavailable, not passed.
- CHG-216 Batch B adds V020 OIDC reauthentication state and fail-closed appliance
  provisioning. Live Keycloak callback/replay, Flyway migration and disposable
  appliance provisioning acceptance remain blocked by unavailable services and
  tools; Batch B is not production-accepted.
- CHG-216 Batch C adds V021 quarantine/outbox/step-lease/canonical-vector state,
  ClamAV and Celery Beat Compose services, Helm Beat deployment, quarantine-only
  upload/sync, asynchronous extraction, bubblewrap-isolated LibreOffice and
  per-connection S3 credentials. Focused tests and static/deployment config
  checks pass, but the Docker daemon is not running, so real migration,
  scanner/S3/Celery/converter/OpenSearch acceptance is blocked. Model-provider
  call-count acceptance also waits for operator-supplied provider settings.
- CHG-216 Batch D adds V022 connection evidence, real bounded provider/protocol
  probes, fingerprint invalidation, HTTP destination pinning/allowlists and
  SFTP known-hosts mounts. Focused tests and config checks pass. Real provider
  success waits for operator configuration; protocol/TLS/DNS and migration
  acceptance remain blocked while Docker is stopped and Helm is unavailable.

## CHG-216 Final Evidence

Recorded 2026-07-12:

- Docker services were available. V023/V024 live Flyway acceptance, Compose
  configuration and deployment policy checks passed.
- The full live backend suite executed 120 passing behavior tests. Aggregate
  coverage is 72.92%; the unchanged 80% release gate correctly fails.
- Frontend lint and production build passed; 71 contract tests and five rendered
  component tests pass. Honest all-source V8 coverage remains below 80% and the
  release gate correctly fails.
- Browser E2E passed the configured John submit, Peter manager approval, Owner
  approval and publish workflow, including PostgreSQL, OpenSearch and Neo4j
  verification and cleanup.
- Production dependency audit, Bandit, frontend/backend Docker Scout Critical/
  High scans and SPDX SBOM generation passed. Both final images report zero
  Critical or High finding.
- Controlled historical test residue was deleted from PostgreSQL/OpenSearch/
  Neo4j; follow-up dry-run reports zero matching records.
- Helm was intentionally not tested. Real provider success waits for operator
  configuration. These are not reported as passing.

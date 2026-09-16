# NomoSmart deployment operations

This runbook describes the checked-in Compose/Helm contracts. Commands below are
operator procedures, not authorization to run them against an existing system.
Follow `SPECIFICATION.md`, the current approved change scope and
`deploy/RELEASE_READINESS.md`. Record exact context, namespace, release, image
IDs, render digest, schema baseline, backup custody and rollback decision first.

## Configuration and secrets

Use `deploy/docker/nomosmart.env.example` as the **non-secret** Compose template.
Keep real runtime settings outside Git in an operator-owned config file and
provide the referenced Secret files with restrictive permissions. Do not print
resolved Compose config, Helm Secret manifests, tokens or private keys in logs.
Use the checked-in mounted-file contracts; do not bake credentials into images.

The default Compose profiles are
`postgresql,redis,rustfs,opensearch,neo4j,keycloak`. A profile selects the bundled
service, not permission to replace an existing external datastore. To use an
external service, disable its profile and explicitly configure its endpoint,
credential files and TLS trust. Confirm readiness against the intended service.
Preserve public OIDC issuer/audience while configuring internal discovery/JWKS
transport separately. Never disable verification to make a TLS failure pass.

For Helm, use `deploy/helm/nomosmart/values.yaml` plus an environment-specific
overlay and approved image tags/digests. Each peripheral supports `mode: bundled`
or `mode: external`; see `values-bundled.example.yaml` and
`values-external-services.example.yaml`. Non-sensitive values become ConfigMaps;
use existing/external Secret references for secrets. Check PVC/PV retention,
storage classes, issuer/TLS, Ingress allowlists and supporting-service ownership.

## Validation before writes

Run from the repository root:

```sh
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:config-policy
```

Also complete Backend/Frontend tests, independent 80% coverage, live E2E,
dependency/image scans and SBOM checks listed in the release checklist. A syntax
or template pass is not runtime acceptance. Missing services or model authority
are blockers, not reasons to substitute fabricated success evidence.

Render with the exact approved release/revision and values; use hidden-Secret
server-side dry runs when authorized, retaining a canonical digest and bounded
resource diff. A dry run does not permit Helm writes, Jobs or migrations.

## Startup and migration

### CHG-301 Compose preparation (implementation; acceptance incomplete)

Compose alone selects `compose-secret-entrypoint.sh` with a fixed service
profile and a dedicated `/run/nomosmart` tmpfs. Its short root phase copies only
mounted, allowlisted ordinary Secret/TLS files; host files stay owner-only and
read-only. Private copies are service-owned `0400`; root-owned `0710` parents
permit only service-group traversal, not replacement of paths. The helper
rejects symlinks, unexpected destinations and legacy arbitrary-copy controls,
then runs the real command under the service UID/GID. PostgreSQL retains its
upstream initialization and `gosu` handling; its Compose `command: [postgres]`
is explicit because an entrypoint override clears the image's default CMD.
Do not invoke this Compose helper
from Helm or add global `NOMOSMART_RUN_AS` settings to shared images.

The shared Secret-export entrypoint performs no copy or privilege change, so
Migration can still start directly with Helm's UID 10001/security restrictions.
Backend/Worker/Beat retain their commands. Worker and Beat now directly await
successful migration/bootstrap and a healthy bundled Redis; they do not wait
for Backend health, which depends on actual Worker heartbeats. Migration target
checks remain required; an unset target is not a successful installation.

Fresh Compose packages generate distinct strong OpenSearch admin/service
passwords. Repeating `init` preserves an existing package byte-for-byte; this is
not automatic password rotation or a repair of an existing weak credential.
Other Helm profiles and operator-supplied credentials keep their prior contract.
Missing minikube does not require installing it for Compose; host/port and other
runtime checks remain in place.

CHG-301 has not been merged or deployed. See
`docs/CHG-301-VERIFICATION.md` for passing isolated Compose tests and package
coverage, remaining full-application coverage/live-Kubernetes acceptance gaps
and the separate approval required before any current-environment operation.

### CHG-300 target contract (new code; deployment separately approved)

The application/init readiness gate requires `MIGRATION_REQUIRED_VERSION` and
`MIGRATION_REQUIRED_CHECKSUM`. Helm uses `migration.requiredVersion` and
`migration.requiredChecksum`; set the version as a string. Checksum is Flyway's
signed 32-bit SQL checksum, **not** the file SHA-256. Obtain it from a source-bound
isolated migrate/validate run with the exact candidate; never copy the current
database value and treat that as an independently verified expectation.

Examples intentionally leave both values blank. Rendering an example may pass,
but its runtime gate fails closed until the operator supplies the pair. Old
`--reuse-values` releases will not supply these newly required values automatically.
`MIGRATION_CHECK_TIMEOUT_SECONDS` / `migration.checkTimeoutSeconds` default to 10
(range 1–60); connection and statement waits are bounded, not an overall bootstrap
duration guarantee. Do not override chart-managed migration keys via backend or
frontend environment dictionaries.

Backend/Worker/Beat/bootstrap use the same read-only history check. Frontend init
compares the verified `deployment.database.detail` in Backend's existing readiness
JSON against its typed target contract (`migrated:<canonical version>:<checksum>`).
This adds no Frontend database credentials or network access. A healthy old Backend
without the matching verified detail is not sufficient. Missing/failed target,
wrong checksum or a newer unapproved schema blocks startup/readiness; no repair,
DDL or automatic target downgrade occurs in the checker.

This protects new main-container startup, **not** the stronger requirement that
Helm must finish migration before updating Deployment templates. Job/hook/stage
ordering, old replica availability and compatible rollback require a separately
reviewed deployment strategy. Flyway 13.6.0 is pinned in the candidate recipe only;
its new image, license/platform/runtime compatibility, SBOM and security scan must
still be verified after separate build/scan approval.

For a separately approved, configured Compose environment, explicitly select the
same project name, file and operator configuration for every operation:

```sh
docker compose --env-file /operator/path/nomosmart.env -f docker-compose.yml up -d
docker compose --env-file /operator/path/nomosmart.env -f docker-compose.yml ps
```

The absolute `/operator/path` above is a placeholder, not a default config source.
Review the actual `migration` and `deployment-bootstrap` services before startup.
Flyway is append-only; a new migration image can apply **all** included pending
migrations. Do not assume an application-first release permits new DDL or V049.
Initial onboarding and `DEPLOYMENT_PHASE=operational` have different bootstrap
authority. Preserve bootstrap receipts and audit Jobs; idempotent bootstrap can
still perform bounded operational writes, which must be included in approval.

For an approved Helm upgrade, use the reviewed chart/values and correct explicit
context/namespace. Select the installed Helm version's supported failure rollback
flag, `--wait`, `--wait-for-jobs` and approved timeout. Check hooks/Jobs in the
render first. `--reuse-values` retains old settings but is not a substitute for
drift comparison. Do not automatically retry a failed migration or upgrade.

## Network and diagnosis

The edge is the normal entry point. Datastore ports remain internal. The optional
debug profile binds only `127.0.0.1`; enabling it requires a bounded diagnostic
scope. Example suffix on the same configured Compose invocation:

```sh
docker compose --env-file /operator/path/nomosmart.env -f docker-compose.yml --profile debug up -d debug-ports
```

Disable the debug service when finished. Never publish these ports on all host
interfaces. Inspect readiness, migration/bootstrap exit status, structured
Backend/Worker logs and Frontend proxy logs. For 504 errors, check Service
endpoints and both pod-to-pod directions before changing timeouts or restarting
stateful components. Do not turn a diagnostic into unapproved data repair.

## Shutdown, backup and rollback

Use `docker compose ... stop` for a non-destructive stop. Keep named volumes and
Secret/config custody. Do not use `down -v`, blanket prune, PVC deletion or Helm
uninstall as a rollback procedure. Deletion of data resources requires its own
inventory, approval and recovery plan.

Before a mutating release, retain a complete pre-deployment PostgreSQL backup
and prove restoration in an isolated environment. Include object storage,
OpenSearch, Neo4j, Keycloak and Secret recovery; PostgreSQL alone cannot restore
external artifacts. Record protected row/resource counts and digest baselines
without secret values. A Helm application rollback does not undo SQL or Jobs.

### CHG-237 V030 restriction

After a deleted local-role name is reused, a code-only rollback is prohibited.
Use a forward fix or coordinated restore of the complete pre-deployment
PostgreSQL backup and compatible application version. V031 archive cleanup also
requires coordinated external-store recovery after any destructive cleanup.
Check queued/running/failed archive work before a release transition. See
`RELEASE_READINESS.md` for these and other compatibility restrictions.

## Acceptance record

CHG-301 R2 formal-dependency remediation pins RustFS beta.10's official base and
four Alpine security packages, upgrades Frontend's build-time npm to the
checksum-bound official 11.19.1 bundle, and qualifies checksum-bound uv 0.11.33
with the existing Ubuntu 24.04 base pinned for Backend. That remediation phase
left application lockfiles and SQL unchanged (the earlier separately approved R2
test change pins pytest 9.0.3). These source changes are **not deployment approval**: other
formal dependencies and the Redis Sentinel regression remain unresolved. Consult
[the scoped result](../docs/CHG-301-R2-FORMAL-DEPENDENCY-RESULT.md) before building
or distributing; local ARM64 evidence does not qualify untested platforms.

The subsequent application-only CHG-301 R2 scope removes unused Backend builder
compiler/libpq development packages only after clean ARM64 and AMD64 locked
installs, full scans and non-root CLI qualification. Application lockfiles and
runtime libpq5 remain unchanged. See the
[application security result](../docs/CHG-301-R2-APPLICATION-SECURITY-RESULT.md)
for completion status and exact platform/stage evidence. Peripheral findings and
the historical Redis Sentinel failure are deferred by the user for this PR, not
fixed or accepted as safe. The existing exact FTP plaintext exception remains
disclosed; this checkpoint is not deployment or whole-system release approval.

Record health/readiness, real service connectivity, authenticated scope checks,
Job receipts, protected-baseline differences and source-bound test/security
reports. Explicitly distinguish failed, blocked and not-run checks. Do not submit
a provider-billable query, rebuild a document/index or change membership merely
to demonstrate availability without separate authority.

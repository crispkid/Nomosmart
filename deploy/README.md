# NomoSmart deployment operations

Operational configuration for NomoSmart 0.1.1. Start with the complete installation
guide in [English](../README.md) or [繁體中文](../README.zh-TW.md).
Record the target context, Namespace, release, image digests, migration contract,
and recovery procedure before changing an existing deployment.

## Configuration and secrets

### Document upload transport limit

The existing Backend setting `NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB` is the
per-file authority (legacy `MAX_UPLOAD_SIZE_MB` fallback, default 100 MiB).
The edge must also allow multipart framing: its finite whole-request default is
the effective file limit **plus 1 MiB**, so 100 MiB files use a 101 MiB envelope.
All units here are 1024² bytes. The extra space does not increase the file limit.
Multiple files keep their existing single multipart request and per-file results;
the entire batch including framing must fit the request envelope. An oversized
request receives edge HTTP 413 before Backend; split it into smaller batches.
This does not promise unlimited batches or change automatic-extraction rules.

Helm optional `ingress.documentUpload.requestMaxSizeMiB` overrides the request
limit; leave it omitted to derive from Backend, including old `--reuse-values`.
The integer must be at least the file limit plus 1 and at most 10241. Explicit
null, empty, zero, non-integer and conflicting path/annotation values fail closed.
The separate `*-document-upload` Ingress sends `/api/backend/projects` to the
same Frontend proxy, preserving host, TLS, class and source/security annotations.
It covers uploads and version updates without exposing Backend directly. Root,
identity/admin and public API limits are not raised, and the three existing
Ingress resources are not renamed or edited by this new template.

Compose uses the same exact/slash-prefix path. Its mounted executable
`16-document-upload-config.sh` derives a numeric nginx include before template
expansion; it does not rely on exports from a child script. Optional
`DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB` belongs in the configured runtime `env_file`
(not a blank placeholder); omission derives the limit. The per-file settings in
the edge environment mirror the Backend Compose environment. Changing deployment
configuration requires applying it to the edge/workloads, not rebuilding images.
Keep this script executable and `/etc/nginx/includes` writable at startup.

Verify the actual generated nginx location limits and inherited allowlists,
then prove transport/auth rejection and real authorized upload separately.
A Backend 401 proves transport to authorization, not successful file ingestion.
The Frontend forwards bounded chunks and the Backend uses bounded disk scratch
space. Watch memory, disk capacity, and restarts during boundary checks;
do not increase memory limits or remove the cap just to make validation pass.

### Public API edge routing

The external contract remains `POST /api/public/v1/projects/{project_id}/chat`,
the same path plus `/stream`, and `POST /api/public/v1/chat/responses/{response_id}/feedback`.
These are API-key endpoints, not the web UI's `/api/backend` OIDC proxy.

Compose's existing TLS edge forwards only `/api/public/v1/` to the internal HTTP
origin `BACKEND_EDGE_UPSTREAM` (default `http://backend:8000`). It must not contain
credentials, a path, query or fragment. The mounted `15-public-api-config.sh`
validates settings before nginx template expansion. Keep this script executable.
`PUBLIC_API_READ_TIMEOUT_SECONDS` defaults to `600`, integer `1..3600`; it only
sets the public proxy's idle-read timeout, not a Provider timeout. Existing edge
TLS, host bindings, body limits and identity-admin restrictions are unchanged.

Helm creates a separate `*-public-api` Ingress by default, sharing the main
Ingress hosts, TLS, class and effective source/security annotations (including
the onboarding allowlist). Public-only buffering and upstream retry are disabled.
The existing two Ingress resources are not renamed or edited by this template.
Backend NetworkPolicy retains Frontend access and adds only the configured
Ingress controller namespace AND pod selector on Backend's named `http` port.
It does not expose an internal API or open Backend to all Pods.

Optional `ingress.publicApi.enabled` (default `true`) and
`ingress.publicApi.readTimeoutSeconds` (default `600`, integer `1..3600`) have
template defaults even when omitted from an old release's `--reuse-values`.
Explicit null or invalid values fail schema checks. Disabling the public route
also omits its extra network rule. Conflicting public paths, rewrite/regex,
snippet or SSL-passthrough annotations are rejected instead of silently changing
the API or weakening inherited access controls. Review the new Ingress and exact
NetworkPolicy delta before any approved upgrade; editing defaults alone is not
evidence that the running release has changed.

Validate missing-key JSON `401 api_key_required` through the actual TLS edge,
then separately test authorized JSON/SSE, scope and revoked-key behavior.
Do not follow a failed/unknown POST by automatically retrying a billable query.
No source restriction is removed: a local allowlist still means local access,
not public Internet access. nginx ingress uses no proxy cache by default; do not
enable a controller-wide cache/custom template for these credentialed endpoints.

Frontend upload feedback accepts optional `FRONTEND_UPLOAD_WAIT_NOTICE_MS` (default
`30000`, integer `1000..300000`) through Compose or Helm `frontend.env`. It controls
only the slow-confirmation notice. It does not time out uploads, cancel server work,
change file-processing policy, or generate percentages. Omitted legacy settings
use the default; explicitly invalid values fail validation. Unknown progress is
animated without a percentage; confirmed Pipeline reports retain percentage bars.

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

Backend readiness has an optional `backend.readinessTimeoutSeconds` integer
(1–60). Omitted keys, including older `--reuse-values` releases, retain 5 seconds.
The Docker Desktop values overlay sets it to 10 seconds.
This only tolerates occasional readiness latency; it does not speed up requests,
change health results, or extend liveness (5 seconds), dependency or Ingress
timeouts. Explicit null, zero, wrong types and out-of-range values are rejected.

Bundled OpenSearch probes have explicit, bounded budgets: Kubernetes timeout
10 seconds, curl connection timeout 2 seconds, total curl timeout 8 seconds and
readiness server wait 5 seconds. Configure `opensearch.probes.timeoutSeconds`
(1–60), `connectTimeoutSeconds` (1–30), `maxTimeSeconds` (1–60) and
`readinessWaitSeconds` (1–30). Require connection <= total < Kubernetes timeout
and server wait < total. Periods/failure counts, authenticated TLS and hostname
verification are unchanged. No retry-until-success or unlimited timeout is used.

The optional example in `values.yaml` is deliberately commented out: omitted
keys (including old `--reuse-values` releases) use template defaults, while
explicit null, zero, wrong types and conflicting budgets are rejected rather
than lost during Helm's default coalescing. External OpenSearch has no bundled
probe or resource changes. The Docker Desktop overlay alone requests 2 GiB and
limits 4 GiB for OpenSearch; other profiles keep their memory defaults. CPU,
512 MiB Java heap, image, replica count and volumes are unchanged. Account for
the shared Docker VM's capacity, not the sum of kind nodes' reported memory.

An existing release needs only the approved explicit overrides with reuse-values,
not reapplication of the entire local overlay. Changing probes/resources rolls
the StatefulSet Pod; single-node search can be briefly unavailable. Retained
PVCs are not backups. A rollback can restore the previous smaller memory limit
and probe budget; verify actual health instead of assuming recovery.

Run from the repository root:

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
helm lint deploy/helm/nomosmart
```

After startup, verify health, readiness, identity synchronization, model
connections, and a basic document workflow as described in the installation
guide. Configuration rendering checks syntax; runtime verification checks the
installed services.

Render with the exact approved release/revision and values; use hidden-Secret
server-side dry runs when authorized, retaining a canonical digest and bounded
resource diff. A dry run does not permit Helm writes, Jobs or migrations.

## Startup and migration

### Compose Secret preparation

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

### Migration contract

NomoSmart 0.1.1 delivers [B051](../sql/migrations/B051__nomosmart_0_1_0.sql) for
empty databases and preserves V001–V051 for databases with existing migration
history. Official Flyway applies B051 once on an empty database. The source-bound
[migration contract](migrations/release-contract.json) defines the accepted version,
type, file hash, and Flyway checksum.

The generated Compose and Helm configuration supplies
`MIGRATION_REQUIRED_VERSION=051`, `MIGRATION_REQUIRED_CHECKSUM=1782483375`, and
`MIGRATION_BASELINE_CHECKSUM=1904638595`. Helm uses `migration.requiredVersion`,
`migration.requiredChecksum`, and `migration.baselineChecksum`. Keep the version
as a string. Flyway's signed 32-bit checksum and the SQL file's SHA256 hash serve
different purposes. Preserve the values supplied with the release.

For source development, add these values to `backend/.env` as described in the
installation guide. Review all migration settings before reusing older values.
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

These checks protect new application startup. Review Job ordering, old replica
availability, and rollback compatibility when planning an upgrade. The official
Flyway image is pinned in [external-dependencies.lock.json](release/external-dependencies.lock.json)
and consumes NomoSmart SQL through mounts or ConfigMaps.

For a separately approved, configured Compose environment, explicitly select the
same project name, file and operator configuration for every operation:

```sh
docker compose --env-file /operator/path/nomosmart.env -f docker-compose.yml up -d
docker compose --env-file /operator/path/nomosmart.env -f docker-compose.yml ps
```

The absolute `/operator/path` above is a placeholder, not a default config source.
Review the actual `migration` and `deployment-bootstrap` services before startup.
Flyway applies all applicable pending migrations. Review the delivered SQL before
an upgrade; an application rollback does not undo database changes.
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

### Role reuse and archive recovery

After a deleted local-role name is reused, a code-only rollback is prohibited.
Use a forward fix or coordinated restore of the complete pre-deployment
PostgreSQL backup and compatible application version. V031 archive cleanup also
requires coordinated external-store recovery after any destructive cleanup.
Check queued, running, and failed archive work before a release transition.

## Bounded document upload

HTTP document upload and file replacement use per-process receiving limits. The
PDF-processing policy is initialized separately as described in the main guide.

`NOMOSMART_UPLOAD_MAX_INFLIGHT=2`, `IO_CHUNK_KIB=64`, `METADATA_MAX_KIB=1024`,
`PART_HEADER_MAX_KIB=16`, `IDLE_TIMEOUT_SECONDS=60`, `TOTAL_TIMEOUT_SECONDS=600`
(all keys have the `NOMOSMART_UPLOAD_` prefix). Single-file limits are unchanged.
`DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB` includes all multipart parts and framing;
omission derives the file limit plus 1 MiB. Helm generates the same value for the
edge and both applications from `ingress.documentUpload.requestMaxSizeMiB`.
Set other shared limits in `backend.env`, not conflicting Frontend overrides.

Scratch is **disk**, not tmpfs: Helm uses a non-memory emptyDir, Compose a named
volume mounted only on Backend at `/var/lib/nomosmart-upload`. The application
creates a private 0700 child, `/var/lib/nomosmart-upload/private`, with unlinked
0600 temporary files. Compose's existing privilege-dropping preparation grants
only this fixed mount's group access; no arbitrary-path chown is allowed.
No PVC or additional service is introduced. `NOMOSMART_UPLOAD_SCRATCH_MAX_MIB=256`
must cover slots × request limit + 16 MiB. Application reservations and free-space
checks are mandatory: emptyDir sizeLimit and a named volume are not hard disk
quotas. The process cannot fall back to unlimited RAM or disk.

These examples run one ASGI process per container. Do not add `--workers` or
share the scratch volume across processes/replicas without separately bounding
their combined reservations. CPU/RAM limits are not raised. New text uploads
reference their original S3 object rather than duplicating plaintext into JSONB;
legacy snapshots remain readable and no migration/backfill is needed.

### Independent Beat resources

`beat.resources` is optional. Omission, `null`, or `{}` keeps the legacy
`worker.resources` fallback, including upgrades with `--reuse-values`. A partial
object overrides only its supplied `requests` / `limits` fields; unspecified
CPU, memory and limits still inherit Worker. Empty child objects override nothing.
The standalone Beat, HA Beat and capacity report use the same copied merge,
so resolving Beat never changes Worker resources or their capacity report.

To raise only this local Worker's CPU reservation, keep the complete existing
Beat resource object explicit in the release overrides:

```yaml
worker:
  resources:
    requests: {cpu: 500m}
beat:
  resources:
    requests: {cpu: 250m, memory: 512Mi}
    limits: {cpu: "1", memory: 1Gi}
```

These are example release overrides, not new global defaults. Both processes
retain a one-CPU limit in this example. The values schema rejects invalid object
shapes and quantity types; use Kubernetes server dry-run to validate resource
quantity syntax and request/limit relationships before an upgrade.

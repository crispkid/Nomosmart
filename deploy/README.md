# NomoSmart deployment operations

Current source uses authentication contract2. Start with [English README](../README.md), [繁中README](../README.zh-TW.md), and the [authentication guide](../docs/AUTHENTICATION.en.md). There is no bundled or optional identity-provider component in Compose/Helm. The directory and optional external OIDC service remain operator-managed.

This is an operating guide, not a statement of production readiness. [Current gaps](../docs/AUTHENTICATION-STATUS.md), [configuration verification](../docs/AUTHENTICATION-STATUS.md#deployment-file-checks) and [historical instructions](../docs/archive/authentication-contract-1/README.md) are separate records.

Latest AD qualification: [Windows Server 2025 / strict LDAPS results](../docs/CHG-368-RESULT.md) cover sign-in, user/group changes and actual 1500+1 member ranges. This used an isolated authentication runtime; Compose/Helm deployment results were reused within their recorded source limits. The AD VM remains available; media/snapshot cleanup is complete after Peter approved option A, with strict LDAPS availability confirmed after restart.

## Docker Compose

Prepare the operator `deploy/docker/nomosmart.env` from the [public example](docker/nomosmart.env.example), referenced platform Secret files, trusted edge/datastore TLS, a real directory Bind password and the [bootstrap configuration](docker/auth-bootstrap.example.json). The JSON contains configuration plus `admin_group_id`, not passwords. The group must exist in the real directory and contain the intended first administrator.

The package tool can generate platform Secret/TLS inputs; inspect `./deploy/package/nomosmart-package init --help` for the target/profile first. Existing generations are not automatically overwritten or rotated. Operator directory/OIDC credentials must match real external accounts, not a newly generated substitute. Protect credential files as regular owner-only files. An empty public previous-keyring example contains no keys; real previous keys require a private file.

For reviewed current source or explicitly compatible reviewed images:

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
docker compose --env-file deploy/docker/nomosmart.env build frontend backend
docker compose --env-file deploy/docker/nomosmart.env up -d
docker compose --env-file deploy/docker/nomosmart.env ps
```

Complete migration/bootstrap first. Sign in through the configured LDAP/OIDC mode as a synchronized normal administrator; OIDC administrators must also complete fresh authentication in system settings. Then:

```sh
docker compose --env-file deploy/docker/nomosmart.env run --rm --no-deps deployment-finalize
```

After success, change `DEPLOYMENT_PHASE=operational` in the operator file and recreate Backend, Worker, Beat, Frontend and edge with the same configuration. Verify `/api/backend/ready` through trusted HTTPS. A completed setup Job alone does not prove normal sign-in, authorization or a business workflow. There is no fixed initial application password.

For an existing bound installation, `./nomosmart status --json`, `logs` and `down` retain the host workflow's ownership/configuration checks. Its `up` command requires prepared real directory inputs; do not use it as a replacement for configuring the enterprise identity source. `down` preserves data volumes.

## Helm installation

If a local platform has unreliable DNS, optional `podHostAliases` can provide operator-managed IP/hostname mappings for this deployment's Pods. It defaults to an empty list and does not change cluster DNS. Keep database URLs and TLS hostname verification unchanged, and update mappings when Service IPs change. Test-only addresses must not be copied into production values.

Helm merges nested label maps when applying values. When selecting a custom ingress proxy, explicitly override every retained default selector key (including `app.kubernetes.io/name`) to match that proxy, or deliberately remove an unused key while retaining restrictive selectors. Check the rendered NetworkPolicy against the actual proxy labels; adding a new selector key does not replace the default labels.


| Path | Supported input and lifecycle |
| --- | --- |
| Protocol installer | `external-services`, existing runtime Secret, explicit owned namespace/context; plan → install/resume → normal sign-in → finalize → verify |
| Direct chart | Reviewed bundled or external-services values; operator performs the same bootstrap/onboarding/finalization stages |
| Current one-click | `--protocol-config`, external-services only; private initialization → read-only plan → bound confirmation → normal sign-in checkpoint |
| Legacy factory/contract1 | Archived source; excluded from current protocol packages and current installation entry points |

For the protocol installer, copy the [target TOML](installer/nomosmart-install.protocol.example.toml) and [values JSON](installer/protocol-values.example.json) to a private operator directory. Replace all example endpoints, CA/Secret names, image references, source/group identifiers, application origin and target fields. Use an absolute chart path or a correct path relative to the target TOML. Set endpoint allowlists to the real directory and chosen OIDC hosts; never disable TLS verification.

The target example names `protocol-values.json`. Save the copied JSON under that name in the operator directory, or adjust `values_file` explicitly.

The runtime Secret supplies platform/database/migration/storage credentials and encryption keys. Bootstrap additionally needs `DIRECTORY_BIND_PASSWORD` and, for an OIDC client that requires one, `OIDC_CLIENT_SECRET`. Keep `secrets.data={}` and use `secrets.existingSecret`. Authentication CA Secret keys must match `ca_reference` filenames in bootstrap configuration. Persist the encryption keys required by existing database ciphertext.

Create only the intended namespace. If the operator precreates it to provision Secrets, label that **new** namespace with `nomosmart.io/protocol-installation` equal to the target `installation_id`. A namespace owned by another installation must not be relabeled or reused. The installer will reject mismatched ownership.

```sh
./deploy/installer/nomosmart-install plan --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install install --protocol-config /operator/path/target.toml
# Complete synchronized normal-administrator sign-in in the browser first.
./deploy/installer/nomosmart-install finalize --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install verify --protocol-config /operator/path/target.toml
```

`/operator/path` is a placeholder. `install`/`resume` may return exit10 with `action-required`; this is the normal sign-in checkpoint, not completed onboarding. After interruption inspect `status` before another mutating command. The installer does not administer an IdP or create a directory user.

For a **direct bundled chart** deployment, begin with [values-bundled.example.yaml](helm/nomosmart/values-bundled.example.yaml) and complete bundled operator values including runtime/TLS Secrets, authentication bootstrap, images, storage and ingress. Do not reuse the external-services JSON unchanged. Inspect the real rendering first:

```sh
helm lint deploy/helm/nomosmart
helm template "$NOMOSMART_RELEASE" deploy/helm/nomosmart \
  --namespace "$NOMOSMART_NAMESPACE" \
  -f deploy/helm/nomosmart/values-bundled.example.yaml \
  -f "$NOMOSMART_HELM_VALUES" --set installer.deploymentStage=application
```

Rendered manifests can contain Secret data; keep output private and do not paste it into logs/chat. Apply only to the explicit reviewed context/namespace. Initial application-stage values use `bootstrap.deploymentPhase=onboarding`. After normal administrator sign-in, apply the same complete values with `bootstrap.finalize.enabled=true`; after that Job succeeds, set it false and change both `installer.deploymentStage` and `bootstrap.deploymentPhase` to `operational`. Wait for real Jobs and readiness at each stage. The protocol installer automates these stages for its external-services path.

Across the contract2 upgrade, remove retired `keycloak.*`, `global.keycloakPath`, `bootstrap.keycloak*`, product-specific env/Secret/PostgreSQL fields and identity routes. Supply complete explicit values with `--reset-values`; do not carry old values across with `--reuse-values`. An actual upgrade removes old release-owned identity workloads/routes/product Secrets, so arrange independent IdP/data/credential custody first. Published SQL and historical identity fields remain; these scripts do not DROP old databases or clear retained PVCs.

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
limit; leave it omitted to derive from Backend, including compatible prior values.
The integer must be at least the file limit plus 1 and at most 10241. Explicit
null, empty, zero, non-integer and conflicting path/annotation values fail closed.
The separate `*-document-upload` Ingress sends `/api/backend/projects` to the
same Frontend proxy, preserving host, TLS, class and source/security annotations.
It covers uploads and version updates without exposing Backend directly. Root,
other application and public API limits are not raised, and other application
Ingress resources retain their paths and limits.

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
TLS, host bindings, body limits and onboarding source restrictions are unchanged.

Helm creates a separate `*-public-api` Ingress by default, sharing the main
Ingress hosts, TLS, class and effective source/security annotations (including
the onboarding allowlist). Public-only buffering and upstream retry are disabled.
Other application Ingress resources retain their paths and limits.
Backend NetworkPolicy retains Frontend access and adds only the configured
Ingress controller namespace AND pod selector on Backend's named `http` port.
It does not expose an internal API or open Backend to all Pods.

Optional `ingress.publicApi.enabled` (default `true`) and
`ingress.publicApi.readTimeoutSeconds` (default `600`, integer `1..3600`) have
template defaults even when omitted from compatible prior values.
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
`postgresql,redis,rustfs,opensearch,neo4j`. A profile selects the bundled
service, not permission to replace an existing external datastore. To use an
external service, disable its profile and explicitly configure its endpoint,
credential files and TLS trust. Confirm readiness against the intended service.
Configure OIDC issuer/client/metadata in authentication bootstrap or unlocked Web settings,
with explicit allowlisted internal transport only when needed. Never disable verification to make a TLS failure pass.

For Helm, use `deploy/helm/nomosmart/values.yaml` plus an environment-specific
overlay and approved image tags/digests. Each peripheral supports `mode: bundled`
or `mode: external`; see `values-bundled.example.yaml` and
`values-external-services.example.yaml`. Non-sensitive values become ConfigMaps;
use existing/external Secret references for secrets. Check PVC/PV retention,
storage classes, issuer/TLS, Ingress allowlists and supporting-service ownership.

## Validation before writes

Backend readiness has an optional `backend.readinessTimeoutSeconds` integer
(1–60). Omitted keys, including compatible prior values, retain 5 seconds.
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
keys (including compatible prior values releases) use template defaults, while
explicit null, zero, wrong types and conflicting budgets are rejected rather
than lost during Helm's default coalescing. External OpenSearch has no bundled
probe or resource changes. The Docker Desktop overlay alone requests 2 GiB and
limits 4 GiB for OpenSearch; other profiles keep their memory defaults. CPU,
512 MiB Java heap, image, replica count and volumes are unchanged. Account for
the shared Docker VM's capacity, not the sum of kind nodes' reported memory.

Within an already compatible contract2 release, review only the necessary
probe/resource changes while supplying the complete approved configuration. Changing probes/resources rolls
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

Current source targets [V056](../sql/migrations/V056__native_pdf_cleanup.sql).
For an empty database, official Flyway applies the unchanged
[B054](../sql/migrations/B054__protocol_authentication_and_sessions.sql) baseline,
then V055 and V056. Existing databases retain their published migration chain and continue
through V056. No B056 or rewritten historical SQL is introduced. The source-bound
[migration contract](migrations/release-contract.json) defines the current SQL
target's version, file hash and Flyway checksum. Historical054 SQL/SQL_BASELINE
contracts remain readable for their original releases.

The generated Compose and Helm configuration supplies
`MIGRATION_REQUIRED_VERSION=056`, `MIGRATION_REQUIRED_CHECKSUM=99561060`, and
an empty `MIGRATION_BASELINE_CHECKSUM`. Helm uses `migration.requiredVersion`,
`migration.requiredChecksum`, and `migration.baselineChecksum`. The current056
contract validates the additive SQL target, rather than inventing a same-version
baseline. Flyway still validates the installed migration history. Keep the version
as a string. Flyway's signed32-bit checksum and the SQL file's SHA256 hash serve
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
render first. Use complete reviewed values with `--reset-values` across the authentication-contract transition;
retired settings must not be carried forward. Drift comparison remains required. Do not automatically retry a failed migration or upgrade.

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
OpenSearch, Neo4j, encrypted authentication settings and Secret recovery; PostgreSQL alone cannot restore
external artifacts. The external IdP/directory operator owns their separate recovery. Record protected row/resource counts and digest baselines
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
`worker.resources` fallback, including compatible contract2 upgrades. A partial
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


Private host-workflow state under `deploy/docker/.nomosmart-workflow/` remains
outside Git and package delivery. See the current Compose section above for prerequisites.


### Helm application node placement

The existing `nodeSelector` value applies to Backend, Frontend, Worker, both Beat variants, and migration/bootstrap/finalize Jobs. Its default `{}` leaves placement to the scheduler. Set matching node labels in environment-specific values when a constrained development or operations topology requires them. Operator-managed external services retain their own placement; check available nodes and keep HA affinity requirements in mind. A successful single-node smoke does not qualify cross-node networking or HA.

既有 `nodeSelector` 現在一致套用到後端、前端、Worker、兩種 Beat，以及 migration／bootstrap／finalize 工作。預設 `{}` 由排程器安排；需要指定節點時在環境 values 填入節點標籤。外部服務仍由操作人員管理其節點位置；單節點驗證不代表跨節點網路或 HA 已通過。

## Current protocol release contract (draft v4)

The current source adds the `local-verified-release` v4 format and the separate [protocol dependency lock](release/external-dependencies.protocol.lock.json); historical v2/v3 validation retains its own lock and contract. The current lock has no mandatory Keycloak image. This source is not a qualified or signed package.

Inspect the draft interface with `PYTHONPATH=deploy/release python3 -m nomosmart_release.cli assemble-local --help`. Assembly requires a clean detached source, complete same-source test/coverage/security/image evidence, actual platform-scope approval and independent signer trust. Missing live prerequisites or skipped tests cannot become passed gates. Do not use an old package/manifest to qualify this checkout. See [current verification and remaining work](../docs/CHG-369-RESULT.md).

既有部署相容性：Compose 啟動準備仍可為已掛載的舊版 IdP 憑證參照建立私有 tmpfs 檔案，供尚未升級的容器安全讀取。此相容處理不建立 Keycloak 服務，也不變更登入協定。既有容器更換憑證時應沿用其已核對的映像與掛載，先確認啟動腳本相容，再依維護計畫重啟；認證架構切換與資料庫升級仍走各自的升級程序。

## Current installer and package cleanup (CHG-375)

Use `installer/nomosmart-one-click --protocol-config /operator/private/target.toml --init-config` to create new owner-only target and values files in an existing mode700 directory. It never overwrites files or changes directory permissions. Edit actual service/CA/Secret/directory references, then use `--plan-only`; apply only with the returned `--confirm-digest` or explicit `--yes`. The wrapper invokes the real protocol installer, stops at the administrator sign-in checkpoint (exit10), and does not finalize on the operator's behalf. Legacy `--config` and bundled-wrapper input fail before operations; direct Helm retains bundled support.

The protocol payload contains only the current installer import closure and examples. Original wrapper/CLI/templates are preserved with hashes in [the archival inventory](../docs/CHG-375-ARCHIVE-INVENTORY.json); explicitly marked old templates and inactive source remain for historical tests, outside current entry points and payloads. The local tunnel example forwards only datastore traffic. Configure any external OIDC service explicitly using the actual issuer and trusted TLS.

Legacy `nomosmart-release create` and `assemble-validation` reject the current protocol chart before reading keys, building or creating output. Historical `verify-package` remains available. `assemble-local` retains its actual full-suite, 80% coverage, security and signing requirements; this cleanup does not produce a signed package or qualify production publication.

V056 keeps historical policy/receipt evidence. Stop old application writers first; retain an encrypted055 recovery snapshot. New policy v2 exposes only document settings. See [native PDF operations](../docs/NATIVE-PDF-OCR-OPERATIONS.md); no local PDF companion chart is required.

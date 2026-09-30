# CHG-305 PDF processing — inactive deployment source

> Historical / retired by CHG-305 R20 (2026-09-23). This document preserves prior
> design and evidence only; referenced container code and tools have been retired.
> Do not run these installation or recovery commands. The current Worker-local
> implementation and verification limits are in docs/CHG-305-R20-SOURCE-HANDOFF.md
> at the repository root. Source retirement did not uninstall any live resources.

## Current R18 R4 integration status (2026-09-22)

Peter approved the bounded R4 integration/current test-deployment plan and the
D12 dedicated node evidence channel. The dated R12/R16/R17/R3 sections below
retain historical limits, not the current R4 authorization. **Source integration
is still incomplete; no R4 image build, node installation or deployment yet.**
Current v3/grant3 uses compatible schema5 journals; legacy admission still denies
v3 until complete guard/capability/runtime wiring and genuine acceptance exist.

The node-only TLS identity can POST bounded start/stop metadata to the existing
private coordinator listener. It cannot GET health/status/results, create or
cancel work, read PDF bytes or gain Kubernetes-write access. Its private key
belongs only on the approved node, not in the coordinator or parser mounts.
Evidence ACK/durable records alone are not proof that the reported runtime facts
are true; the consumer still requires live source and capability checks.

Optional companion values `nodeEvidence.enabled` and `nodeEvidence.nodeCIDRs`
add only exact IPv4 /32 sources on the existing TLS port and a separate
`evidence` subPath of the existing state PVC. Create this directory as UID10001,
mode0700 during the approved installation; set coordinator
`node_evidence.directory` to `/var/lib/nomosmart-pdf/evidence` and configure the
approved sender fingerprints/pins. No new PVC, Service, hostPath, init container
or RBAC is rendered. Empty/duplicate/wide/invalid sources are rejected. Host/node
NetworkPolicy treatment varies by platform; **an IP is not authentication**.
Verify the actual path/mTLS during installation. The default remains disabled
and the legacy companion render is byte-identical. Docker/v2 is unchanged.

## Historical implementation checkpoints

R18 R3 source-in-progress (2026-09-21): explicit Worker
`PDF_COORDINATOR_SESSION_PROTOCOL_VERSION` and coordinator
`session_protocol_version` default to 2. Docker must stay on 2. A future accepted
guarded Kubernetes path must explicitly use 3 with its matching fixed entrypoint,
grant v2 and new capability evidence. **The current legacy capability reader and
new-work admission reject v3**, so changing the number alone does not enable it.
The example remains admission-disabled; no live configuration is changed.

v3 private codec/result/status/recovery readers carry the original DB attempt and
never downgrade a request. New schema4 journal records retain input-transfer
intents, not proof of a safe runtime. Old schema2/3 histories remain readable and
unchanged. Do not roll back to a reader that cannot read schema4 or delete journal
records to force a rollback. Build source explicitly includes only codec modules
in Worker/coordinator images, not parser runners or management SDKs in Worker.
Parser source includes separate v2/v3 entries; its default entrypoint is still v2.
No image/runtime acceptance or activation is claimed by these source changes.

Latest R17 status (2026-09-21): inactive Role source now uses `pods/attach:
[get, create]`, with no other permission expansion; offline chart lint/render
passes, but no chart was installed or actual Role changed. R17 stopped before new
control tests: the old exact Job is Failed/DeadlineExceeded, while its Pod and
matching CRI container record no longer exist. Required individual exit evidence
cannot be recovered; Job/namespace remain, node is stopped, smoke driver removed,
and protected14 metadata/configuration unchanged. No PDF/capability acceptance.
See `docs/CHG-305-R17-EXECUTION-RESULT.md`. Historical R16 retained-Pod description
below records that earlier observation, not a claim that the Pod still exists.

R16 status (2026-09-21): first-token initialization was fixed and real restricted
API/TLS/token-rotation tests passed. Attach handshake still failed; source shows
the GET-only attach Role lacks the create check required by default Kubernetes
1.36.4. That handshake's HTTP code was not captured, so causality is not fully
proven. No permissions were expanded. Control acceptance remains INCOMPLETE.
The retained node is stopped and drivers removed, but one test namespace/Job/Pod
is retained because Pod terminal evidence was missing; do not restart implicitly.
No parser profile/capability/deployment was enabled. See
`docs/CHG-305-R16-TOKEN-FIX-RETEST-RESULT.md`, historical CONTROL-RESULT, and
`docs/CHG-305-R16-PARSER-PROFILE-DESIGN.md`. The proposed dedicated OCI launch
guard is **not installed or approved for implementation by R16**. Historical R12
source-only statements below describe that original packaging stage, not a claim
that no later diagnostic images have ever been built.

This is **not a runnable default configuration or deployment approval**. R12 A
prepares sources/static checks only. No image has been built from these recipes,
and no live isolation, control-plane, migration or business acceptance is implied.

## Data and authority boundaries

The thirteen file-processing business parameters remain in PostgreSQL (V050),
including both concurrency limits. The configuration here contains deployment
safety ceilings, transport budgets, identities and storage; it must not replace
the DB policy or introduce a fallback concurrency of ten. Runtime safety capacity
must agree with the Backend's `FILE_PROCESSING_CAPABILITIES_JSON`, deployment UUID,
fixed parser profile/image and the independently approved real capability receipt.
All candidate migrations/task dispatch and old-message draining need separate
release acceptance; enabling the sidecar alone is not a safe upgrade.

Worker -> mTLS coordinator -> one short-lived parser per document. Only the
coordinator has Docker/Kubernetes management identity. No database, S3, OIDC,
model key or Worker/operator client key belongs in its filesystem/environment.
It does hold its own server key, a read-only observer key for probes and the
explicit runtime credential. Treat its compromise as runtime-control compromise.
The parser receives bytes over attach, has no network/credential mount, and only
fixed operations. Neither a template nor a successful HTTP response proves this.

## Immutable packaging inputs (future authorized build only)

R18 R3 source addition: `backend/pdf_coordinator/Dockerfile.guarded` is an opt-in
second packaging step, not a change to the legacy v2 build. Supply approved
digest-pinned `GO_IMAGE` (Go1.26.5, matching target architecture) and the previously
built/import-checked `COORDINATOR_IMAGE`. The build is offline/stdlib-only and
copies only `pdf-grant-sign` into the non-root coordinator. It does not install
the node guard, include a signing seed, enable v3, or generate an acceptance
receipt. Record the actual final binary SHA256 as `kubernetes_start_grant.signer_sha256`
and use `/usr/local/bin/pdf-grant-sign` only after real image smoke validation.
No image has been built by adding this recipe; no mutable image default is given.

- Build context is `backend/` for both new recipes.
- `pdf_coordinator/Dockerfile`: explicit Python3.12 base and uv-tool image, both
  `repository@sha256:digest`. Same Python base in builder/final stage. Frozen
  independent `pyproject.toml`/`uv.lock`; immutable AnyIO4.14.2+nomosmart.2 remains
  included. No test sources, product app dependencies or parser binaries copied.
- `pdf_executor/Dockerfile.session`: explicit Debian/Ubuntu-compatible base
  digest/approved apt snapshot, exact Python3.12/Poppler/Tesseract package versions.
  Existing encoding contract retains poppler-data0.4.12-1. Inventory all transitive
  OS packages and image IDs at build; version arguments do not freeze repositories.
  No implicit language substitution: the sample recipe includes eng/chi_tra only;
  a requested absent pack fails closed. Other languages need approved package/image
  inputs and real document validation, not a claim based on these two packs.
- No current build/pull/smoke-test authority. Image security, package provenance,
  exact base selection and the AnyIO exception must be reconsidered for B/C/release.

## Explicit configuration and private storage

R13/R14 optional Docker control binding is source-only, NOT operationally accepted.
Set both `docker_control_journal_id` and `docker_control_epoch` to independently
approved UUIDs only for a dedicated HTTPS/mTLS Docker runtime; leave both null for
legacy capability or Kubernetes. They are deployment identities, not DB business
parameters. A bound journal cannot be used for new work with schema1 fallback.
Control grant schema2 retains all five isolation cases and adds strict reviewed
control evidence; no receipt is shipped. A receipt hash does not enforce access.

Before any future activation, operators must prove sole normal controller access,
no duplicate key/journal controller, old identity revocation and continuous handoff.
No changes to daemon authorization, certificates or infrastructure are authorized
by this README. Consumer acceptance alone is not sufficient. Source details and
unrun cases: `backend/pdf_coordinator/tests/CONTROL_RECOVERY.md`.

The separately authorized local-only command
`python -B -m pdf_coordinator.control_binding --config <private-config> --config-sha256 <approved-hash>`
holds the real journal lock, validates the grant and initial/adoption heads, then
creates `.control-identity.json` exclusively; startup never adopts automatically.
Existing matching marker is verified without rewrite. This command does not
contact/verify the daemon and cannot grant runtime control. Do not run it merely
because the source is present. Client cert/key are loaded once into an exact TLS
context on Linux via opened file descriptors; no private key copies or auto-rotation.

Journal writer v3 reads v2 histories and only appends. Never-started evidence is
not an exit code, successful output or parent-document release. New marker,
capability and journal formats require a compatible rollback reader even after
drain; do not delete evidence/downgrade JSON. No SQL/V052 is required.

Packaging prerequisite: the existing protected coordinator Dockerfile enumerates
individual modules and does NOT yet copy `control_evidence.py`/`control_binding.py`.
R14 expressly excludes Dockerfile changes/builds. Future packaging authorization
must add these runtime sources (not tests), preserve dependency pins and run image
import/TLS smoke checks. This source candidate is not an image/deployable milestone.

`config.example.json` is deliberately **invalid until filled**: null ceilings,
placeholder hashes/identities and `admission_enabled:false`. Do not replace nulls
with guessed defaults. `config.py` is the typed field/range contract. Changing any
of the capability-bound fields requires fresh acceptance. No successful receipt
is supplied in this repository. TLS Worker, observer and operator SHA256 sets are
nonempty/disjoint. Certificates require real CA/hostname validation; loopback probe
uses a server certificate with IP SAN127.0.0.1. Mounted server/client CA roots may
coincide if explicitly intended; cert roles must not.

Startup requires `--config-sha256` matching the exact mounted config bytes. Helm
uses its `configSha256` value for both annotation and startup guard; Compose uses
`PDF_COORDINATOR_CONFIG_SHA256`. A changed file without the approved new hash
rejects startup; do not treat a checksum annotation by itself as enforcement.

Coordinator journal and scratch directories must already be owned10001:10001,
mode0700; intent/page files are created0600 exclusively. No startup recursive chown,
unknown-file cleanup or reuse of previously staged results. Persistent storage
quotas must cover the configured reservation (input+max output per active job),
retained results and append-only journal growth. Journal capacity exhaustion
blocks new work; do not delete audit records just to clear that blocker.

Worker page scratch is a bounded ephemeral volume; an unclean restart can leave
private pages. Do not delete them merely because a heartbeat expired. Exact-owned
maintenance and quota behavior still require fault acceptance. Parser `/work` is
a separate per-runtime limited tmpfs. Provision memory for tmpfs as well as native
tools; a size limit is not an independent reservation outside the memory limit.

## Docker Compose path

Use the opt-in `deploy/docker/pdf-processing.compose.yml` alongside root Compose
only in a later approved environment, with profile `pdf-processing`. Required
variables intentionally make an incomplete overlay fail configuration. Supply
digest-bound coordinator image, `pull_policy:never`, explicit CPU/memory/PID,
private existing bind paths and a TLS Docker daemon endpoint in config. No host
ports/build/socket are provided. A remote TLS daemon still grants powerful runtime
control; the approval must name that daemon and client identity.

For Docker config replace the Kubernetes-specific fields in the example with:
`docker_endpoint` (verified HTTPS), `docker_api_version`,
`docker_empty_config_directory=/var/lib/nomosmart-pdf/docker`, `docker_ca_file`,
`docker_client_cert_file`, `docker_client_key_file` (all in the TLS directory),
`docker_seccomp_file=/etc/nomosmart-pdf/parser-seccomp.json` and its exact SHA256.
The Docker config directory is0700 owned10001 with exactly an empty-object
config.json file0600. Never mount the operator's Docker config or credential helper.
Do not add arbitrary bind mounts/proxy environment to the coordinator.

Worker receives only its own three TLS files. Supply a unique trusted
`FILE_PROCESSING_WORKER_RUNTIME_ID` for each container incarnation; this overlay
does not support scaling multiple Workers with the same literal identity. An
operator must change it for a replacement. This label alone never proves an old
process stopped. Existing root app environment provides accepted capacity JSON.
Coordinator shutdown grace must exceed parser+recovery deadlines; drain first.

## Kubernetes Helm path

Existing `nomosmart` chart defaults `pdfProcessing.enabled:false`; its rendering
must remain byte-identical when disabled. Enabling mounts only the Worker client
Secret and memory-limited page scratch; a nonroot init creates/checks0700 pages.
Worker Pod UID provides a runtime identity component, not process-stop proof.
The configured capacity JSON stays in the existing Backend ConfigMap. Resource
requests/limits must account for Worker scratch and parallel Provider processing.

The separate `deploy/helm/nomosmart-pdf` chart defaults disabled (zero resources).
Its one Recreate coordinator uses an **existing** claim and existing TLS/config/
capability Secrets. It creates no Namespace, PVC, parser Job, migration or data.
The configured dedicated parser namespace must already exist and contain no other
workloads: its NetworkPolicy denies all ingress/egress. Never point it at an app,
system or shared namespace. Chart installation grants scoped create/get/delete
Jobs, get/list/delete Pods and GET attach only; no exec, Secrets, Nodes, patch,
RoleBinding management or cluster role. Runtime-controlled creation is fixed by
code AND must be restricted by an already enforced admission/profile policy.

`existingAdmissionPolicy` is an operational binding, **not enforcement or proof**.
Before activation, deny-test alternate images, command/args, service accounts,
host namespace/volumes, privileges, resources, annotations and parser pod changes;
verify the policy covers both Job creation and Job-controller Pods. The reusable
admission chart/source is now in `deploy/helm/nomosmart-pdf-admission`; see its
README for exact inputs, digest binding and prepared real API dry-run cases.
Its separate disabled default renders no resources. Actual controller-Pod,
forbidden-subresource and kernel capability probes remain A/test work. No node PID limit
or `resources.pids` is fabricated. RuntimeClass/node list must match live receipt.
Only preloaded parser/coordinator digests are used (`Never`).

Kubernetes config now also requires `kubernetes_admission_sha256`, binding the
canonical policy/binding/quota bundle into capability security metadata. Existing
unreleased Kubernetes configurations/receipts must be regenerated and genuinely
accepted for that binding; Docker config/receipts are unchanged. A digest alone
does not prove installation or runtime isolation. No live receipt ships here.

Coordinator API URL must use an explicitly accepted IP with matching TLS SAN;
the egress rule permits that API CIDR/port only, not general DNS or internet.
Projected short-lived runtime token rotates on its directory mount; the CA uses
a separate read-only subPath to satisfy no-follow validation. CA/config/capability
subPath updates require deliberate drain/restart, not silent live replacement.
Worker is admitted from the named namespace/release/component. Maintenance/
monitoring clients need the coordinator-specific operator Pod label in the same
namespace AND the appropriate TLS certificate; labels alone authorize nothing.

Prepare existing PVC root gid10001 mode2770 so OnRootMismatch does not recursively
alter its already prepared journal/scratch subdirectories (uid10001 mode0700).
Verify actual CSI behavior before use. No root chown/init is supplied. Deletion/
uninstall of RBAC or policy while any workload is unknown can destroy recovery
access; retain controls/evidence until exact terminal cleanup is independently
verified. Never Helm-rollback a live parser ownership generation casually.

## Drain, recovery and rollback

1. Stop/hold new **document dispatch** under an approved application maintenance
   scope. Coordinator drain alone does not stop all business/OCR tasks.
2. Operator mTLS POST `/v2/drain` with empty body. Success durably writes the
   private marker; new reservations stop, already admitted owners finish. Status,
   result retrieval and exact reconciliation remain available. Worker/observer
   certificates cannot drain. There is no HTTP resume.
3. GET `/v2/admission` shows blockers and actual unfinished intents/jobs/readers.
   `/ready` remains200 for usable recovery even while drained, full or orphaned.
   `/health` is only process responsiveness. Neither endpoint certifies isolation.
   `/metrics` contains fixed aggregate gauges, no per-document labels.
4. Unknown create/attach/stop retains the journal and DB slot. Reconcile only the
   exact original execution/generation/request fingerprint; no new POST/replay,
   force deletion, finalizer change or declaring404 stopped. Lost result bytes
   are not reconstructed by reconciliation. A failed scratch cleanup is not a
   failed Provider action and must not cause Provider replay.
5. Drain complete means zero local non-stopped intents/jobs/readers; separately
   verify DB document/task/slot and Worker quiescence before rollout/rollback.
   Keep all journals/receipts and protected baselines. Unresolved work blocks a
   safe rollback; preserve the last compatible image/schema until reviewed.
6. Restart does not clear the drain marker or adopt old scratch. To reopen,
   separately authorize exact marker/orphan maintenance **after** evidence review,
   then explicitly enable config admission. No blanket directory deletion or
   automatic recovery script is provided. The exact-parser operator source below
   does not cover unknown Worker crashes or pre-create/orphan recovery.

### Exact parser recovery source (not authorized for execution by A)

`python -m app.deployment.pdf_recovery inspect|reconcile-parser` accepts explicit
`--request-file`, `--request-sha256`, `--operator-cert`, `--operator-key`. The
private stdin object has only `access_token`; do not put tokens in shell history,
argv or reports. The request file is0600/owned/no-symlink and contains the exact
original session open metadata from the private journal. It contains neither
document bytes nor operator-asserted stopped/cleanup evidence. Preserve the
original request fingerprint; reconstructing an approximate request will reject.

Existing OIDC/revocation/SystemManagement view is required for inspect, view+edit
for reconciliation. A distinct operator certificate must pass the operator-only
GET `/v2/maintenance`; Worker/observer identities cannot use this endpoint or POST
session reconciliation. Configuration supplies the fixed HTTPS endpoint/CA and
bounded deadlines. No SDK credentials or runtime inventory are read by the CLI.

Before network I/O validate DB scope and an already fenced parser. One exact POST
may stop/reconcile it, followed by bounded status GETs; no upload/retry/Provider or
Worker kill. After network I/O revalidate OIDC/grants and immutable DB scope before
applying the coordinator's verified stop/cleanup. Release parser as failed only,
never reconstruct lost results. Pipeline status/business content stay unchanged.
Unknown/404/no UID keeps the slot. After durable DB release another call is a
read-only no-op. Inspect and successful/failed recovery have metadata-only audits.

The claimant's body_quiesced_at means its calls and heartbeat have closed; it does
not mean its parser stopped. The document finalizer requires BOTH that bound
receipt and all released children, plus the valid non-yield pipeline outcome.
A Worker crash without its own receipt remains occupied even after parser cleanup.
This source is not a general repair command or permission to manually set receipts,
delete operational rows, resume a recovery yield, or clear an orphan directory.

## Prepared verification, not executed

- Offline Compose model/Helm lint/template checks do not contact daemons/clusters.
- `tests/test_source_primitives.py`: real private journal drain/restart/corruption
  sources, alongside existing real files/socket/request cases, NOT_RUN.
- `tests/test_control_live.py`: nineteen bounded real HTTPS requests against a
  human-bound disposable/empty coordinator, including two idempotent drain writes.
  Requires a0600 scope manifest/hash, source hash, server cert hash and three real
  cert identities. Missing scope errors as BLOCKED, not a successful skip. No
  parser/Provider creation; leaves its exact journal drained for evidence review.
- Backend `test_chg305_recovery_live.py`: four real PostgreSQL domain cases for
  cooperative cancellation, unknown child holds, heartbeat-only refusal and wrong
  claim receipt rejection. They deliberately launch no runtime or Provider.
- `test_chg305_pdf_processing_live.py`: one real parser/DB client case exercising
  bind/progress and stopping/release with autoflush disabled, without a Provider.
- `test_chg305_recovery_control_live.py`: one real OIDC/DB/mTLS recovery case using
  a pre-existing actual fault-campaign epilogue; checks view/edit and TLS roles,
  one exact reconciliation, separate document finalization and no replay. It does
  not itself create the fault or supply stop evidence. Both require new private,
  hash-bound disposable scopes/source hashes; no old runtime budgets are reused.
- This narrow suite does not prove PDF output, runtime isolation, DB admission,
  crash recovery, migration, full coverage or the25-document/10-parser case.
  All B/C resources, report ownership, budgets and cleanup need separate approval.

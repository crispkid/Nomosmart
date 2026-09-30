# Dedicated parser admission — source only

> Historical / retired by CHG-305 R20 (2026-09-23). This document preserves prior
> design and evidence only; referenced container code and tools have been retired.
> Do not run these installation or recovery commands. The current Worker-local
> implementation and verification limits are in docs/CHG-305-R20-SOURCE-HANDOFF.md
> at the repository root. Source retirement did not uninstall any live resources.

This separate chart defaults to `enabled: false`, producing **zero resources**.
It is not installed by the application or coordinator chart. R12 A has not
installed it, compiled its CEL on an API server, or proved enforcement.

When explicitly enabled with all inputs it renders three
ValidatingAdmissionPolicies, their three Deny bindings, and one parser-namespace
ResourceQuota. Policies are cluster-scoped, but their fixed match condition is
`request.namespace == <exact parser namespace>`. Changing a namespace label does
not bypass this match. No Namespace, Job, Pod, image, Secret, Role, RuntimeClass,
Node setting or application data is created by this chart.

## Inputs and ownership

Use `values.schema.json` as the complete input contract. `profile` binds the
dedicated parser namespace, separate coordinator namespace/SA, parser SA, fixed
image digest/command, deployment UUID/profile, accepted RuntimeClass/node names,
startup/termination timings, and **observed** Job-controller usernames. Obtain
controller identities from the approved isolated cluster, not a guessed common
name or a copied production credential. No operator-provided CEL is accepted.

`ceilings` limits one parser's CPU, memory and scratch; it must equal the relevant
three values of coordinator `platform_maxima`. `quota` bounds retained Jobs,
nonterminal Pods and aggregate resource requests/limits. These are platform
safety bounds; PostgreSQL remains the only business concurrency setting. Size
quota for the approved concurrency and retention budget. Completed Jobs still
consume the Job object quota until exact-owned cleanup. A lower quota can block
work; it does not silently change DB policy or permit replay/force cleanup.

The coordinator chart's `existingAdmissionPolicy` names the Job policy from this
bundle (`<admission release>-pdf-jobs`); that annotation alone proves nothing.
Neither chart may be pointed at a shared/application/system namespace. Admission
does not grant RBAC. Only the coordinator may create Jobs, only configured genuine
Job controllers may create Pods or perform metadata-only updates. Existing spec,
identity annotations/labels and owners are immutable. Job-tracking finalizer
removal remains possible. Scheduling binding and status operations are not matched
by these policies; normal Kubernetes RBAC/Node authorization must protect them.

The subresource policy rejects ephemeral-container/resize updates and exec/port-
forward connections; only the coordinator may attach, subject also to RBAC. It
does not permit deleting an unknown workload or prove that a disappeared Pod has
stopped. Existing SDK UID/termination/cleanup guards remain mandatory.

## Canonical binding, then genuine acceptance

`deploy/pdf-processing/admission_bundle.py` reads an offline Helm render from
stdin and emits canonical JSON on stdout, without writing files or calling a
cluster. SHA256 covers the output bytes **without** a trailing newline. The
projection contains apiVersion/kind, exact name/namespace and full spec, ordered
by kind/namespace/name; volatile API metadata/status and Helm ownership labels
are excluded. Quota quantities are normalized to decimal base units, so `1Gi`
and `1024Mi` compare identically. Keep the separately approved resource UIDs too.
No arbitrary resource kinds or partial bundles are accepted.

Set `kubernetes_admission_sha256` in the coordinator's private hash-bound config
to this digest. It also enters `security_config_sha256` in the real capability
receipt. Changing the bundle invalidates the old receipt. This is a binding to
reviewed content, not an automatic live cluster inspection: later acceptance must
verify actual installed specs, UIDs, bindings, freshness and drift. Coordinator
RBAC is not widened to read cluster policies or nodes.

The prepared `backend/pdf_coordinator/tests/test_admission_live.py` uses a real
API server, an actual coordinator test SA and a distinct read-only inspector SA;
no impersonation, mocks or policy installation. It verifies a hash-bound scope,
run-owned empty namespace UID, seven installed resource UIDs/specs, completed CEL
type checking with no warnings, and both authenticated usernames. Then it sends
one valid Job and **17 unsafe variants**, all hard-coded `dry_run=All`. Each
rejection must be HTTP403 and name the expected policy and `PDF_ADMISSION_*`
code. RBAC denial, schema rejection, CEL error or connection failure is not PASS.
Finally it rechecks the bundle and absence of Jobs/Pods. Maximum64 requests,
180seconds total; request timeout1..5seconds. No document bytes are uploaded.

To prepare a separately approved run, its private0600 JSON scope uses the exact
fields validated in `LiveAdmission.setUpClass`: schema1, run identity, explicit
disposable/dry-run approvals, namespace UID, source hashes, original synthetic
session metadata/hash, coordinator config/hash, canonical bundle/hash, all seven
resource UIDs, accepted nodes, dedicated inspector token path and both usernames.
The inspector needs GET on these exact policies/bindings/quota and namespace,
bounded list Pods/Jobs, plus SelfSubjectReview; the coordinator needs its normal
Job create and SelfSubjectReview only. SelfSubjectReview is a nonpersistent auth
check, not a Job. Neither test identity is cluster-admin or a production token.
The test does not grant itself permissions or print tokens/raw error responses.

All live cases above are **NOT_RUN** in A. Do not run them using the current
Docker Desktop context or treat test source as a new authorization.

## Limitations that must remain gates

- Uses stable admissionregistration/v1/CEL and Job `podReplacementPolicy`. The
  exact target server, supported fields/defaulting and controller identity must
  pass genuine server type checking and positive/negative acceptance. An offline
  Helm render cannot prove CEL syntax/type correctness. Unsupported configuration
  blocks adoption; do not change Fail to Ignore or Deny to Warn to pass.
- Actual Job-controller Pod creation, scheduler binding, finalizer progression,
  exact cleanup, forbidden subresources and update immutability still require
  separate live cases. CEL cannot join a Pod owner to its live Job; the genuine
  controller identity and SDK actual owner-UID checks provide distinct layers.
- Restricted profile intentionally refuses extra mounts, sidecars, injected
  annotations, custom scheduling, and RuntimeClass overhead. Mutation webhooks
  or runtimes that inject them need a separately reviewed profile, not exceptions
  added silently. Standard Job labels and bounded not-ready/unreachable
  tolerations are accommodated. The namespace must remain dedicated and empty
  before activation; these policies do not sanitize pre-existing workloads.
- API admission/quota is **not** kernel network/PID/memory proof. There is no
  invented `resources.pids` field. Real network positive/negative controls,
  PID/resource exhaustion, credential/mount absence and actual accepted-node
  evidence are still required. No receipt/probe success is generated here.
- A privileged cluster administrator can change policies, nodes or RBAC. The
  digest is not continuous attestation; exact installation/maintenance/drift
  checks and the time-bound capability acceptance remain operator obligations.

Primary references used for this source design: [Kubernetes validating admission
policy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
(Fail/Deny, request identity, asynchronous type checking) and [Kubernetes CEL
library](https://kubernetes.io/docs/reference/using-api/cel/) (quantity comparison).

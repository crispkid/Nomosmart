# CHG-295 — Exact run-owned E2E cleanup amendment

Date: 2026-09-11. Scope owner/approver: Peter.
**Gate 2 confirmed; Gate 3 prepared; amendment Gate 4 APPROVED.**

Peter approved this plan on 2026-09-11 with
`Peter approves CHG-295 Exact Run-Owned E2E Cleanup Plan Amendment`.
Bounded implementation and fresh isolated non-Provider verification may begin.
The pending-gate/planning results below are historical, not the current gate.

Peter replied `Ok` to cleanup of only the exact resources created by this test
run, preserving shared data, without Provider calls or deployment. This is the
detailed implementation/test plan for that added scope. Original CHG-295
approval/results remain valid for their original scope. No added implementation
or feature test begins before this amendment is approved.

## 1. Current behavior and defect

`backend/scripts/e2e_governance_fixture.py:cleanup_fixture(project_id)` checks a
project prefix, then calls `_collect_scope(... prefixes=(PREFIX,))`, collecting
multiple matching projects. Its graph cleanup traverses up to three undirected
hops and DETACH DELETEs related nodes. Its index check tests only a partial
profile ID before deleting the whole index. None proves single-run ownership.

`frontend/tests/e2eLive.mjs` creates the fixture and launches the browser before
its cleanup `try/finally`; failures between these steps can leave resources.
A cleanup exception can hide the primary failure. The fixture's current fixed
vectors/completed builds do not certify genuine ingestion under TEST-002.

These are source-identified risks, not evidence of current-data loss. No old E2E
cleanup was executed in this planning continuation or the preceding checkpoint.

## 2. Scope and exclusions

Requirements: specification 10.52 `ACCEPT-CLEAN-001..004`, retained
`ACCEPT-REPAIR-002`, `TEST-002`.

In scope: E2E-specific helper/runner wiring, resource receipts, safe lifecycle,
real isolated tests and evidence. Out of scope:

- General `backend/scripts/cleanup_test_data.py` behavior or broad cleanup.
- Existing application data, identities, roles, models, memberships and indexes.
- Adoption/deletion of historical test resources without a creation receipt.
- Application API/schema, new dependencies, migrations/V049, images or deployment.
- Provider execution or substituting stored fixtures for generation evidence.
- Any coverage threshold or test inventory reduction.

These are internal test CLI contracts, not application API changes. The old
`cleanup --project-id` alone must fail closed. Require a run manifest, and make
any supplied project ID exactly match it. Do not preserve a prefix fallback.

## 3. Manifest and creation contract

Add an E2E-specific module, tentatively `backend/scripts/e2e_run_resources.py`.
Reuse existing clients/serialization as appropriate; do not create a general
destructive framework or derive ownership from all reachable rows.

Record:

- Schema version, random run ID, timestamp, lifecycle state and source revision.
- Disposable service/database/schema identities and non-secret configuration
  hash. Endpoints alone are insufficient if a service can be replaced at the
  same address; bind backend-specific resource identities as well.
- One project ID; exact owned SQL primary keys, including composite keys;
  immutable owner/scope fields and creation receipts.
- Exact graph node/relationship identities, endpoint IDs, labels and types.
- Dedicated index name, immutable UUID and run ownership metadata; exact
  document IDs where supported. Never use an alias/wildcard/prefix as a target.
- Exact object bucket/key/version and creation metadata/ETag where supported.
- Per-resource creation intent, confirmed receipt, cleanup result and safe error.

Existing users/models/roles referenced by setup are explicitly **retained**, not
owned. No credentials, document text, prompts, vectors or credential-bearing URLs
go into receipts/logs. Use a unique private test directory, restricted file mode,
atomic updates, validated names/IDs and rejection of symlink/oversized/malformed
input. Preserve receipts after failure.

Write creation intent before external writes/SQL commit. Register only resources
the current setup actually creates; never scan by prefix, actor, timestamp or
neighbors to adopt resources. Use exact creation checks, not an upsert that
silently adopts an existing resource. After interruption, intent plus a creation
marker must prove ownership; insufficient proof means manual review, not guessing.

Keep input preparation distinct from execution evidence. Canonical Markdown
parsing may run without a Provider, but do not insert fixed vectors/completed
builds as successful ingestion. Missing actual generation authority stays an
explicit blocked prerequisite. This amendment does not approve model execution.

## 4. Preflight and deletion algorithm

### Common entry

1. Validate receipt schema, service binding and explicit test isolation.
2. Stop only this run's new work and establish bounded writer quiescence/fencing;
   never stop unrelated workers or acquire unbounded production locks.
3. Inventory exact remaining resources/dependencies in every participating
   service before the first destructive operation.
4. Reject unowned/shared/unknown dependencies. Do not enlarge the deletion set.
5. Recheck ownership before each bounded action and persist its receipt.

### PostgreSQL

Use an explicit supported table set and complete primary keys. Parameterize
values; do not interpolate arbitrary manifest table/column strings. Lock in
stable order, refresh ownership and inspect actual inbound FK metadata,
including CASCADE/SET NULL. Validate children through exact parent keys when
project_id is absent. Unknown schema, trigger or cycle behavior requires review.

Unowned inbound rows cause refusal, not implicit orphan adoption. Shared users,
roles, models and memberships are not changed to facilitate cleanup. Delete
owned children before parents; nullable cycle breaking is limited to explicitly
owned rows. Keep constraints and SQL transaction atomicity. Audit/accounting
cleanup also requires exact creation receipts, not actor/project-wide deletion.

### Neo4j

Match recorded identities and validate uniqueness, labels, owner properties,
relationship types and endpoints. No traversal builds a broader deletion set.
Delete only owned edges; retained/shared nodes survive. An edge to a shared Tag
can be removed only with its own creation receipt. Unknown incident edges cause
refusal. Use a real write transaction, explicit edge deletion and ordinary node
DELETE so a late edge fails instead of being swept away by DETACH DELETE.

### OpenSearch and object storage

Whole-index deletion requires the exact dedicated index UUID/creation marker,
no aliases and no foreign documents. Use supported scoped writer quiescence;
do not assume away ownership races. Shared indexes are not whole-index targets.
Without a supported exact-document conditional deletion plan/receipt, refuse
rather than add broad delete-by-query cleanup.

Delete only exact recorded object versions/keys after checking creation metadata
and conditional identity where supported. If replacement cannot safely be
distinguished, refuse. Never delete a bucket or recursively list/delete a prefix.

## 5. Partial failure, retry and runner wiring

There is no cross-service atomic transaction. If one backend has committed and
another fails, report `cleanup_partial` and retain each receipt; do not claim
rollback of previously deleted external resources. Retry revalidates binding
and operates only on remaining exact resources. A missing project row cannot
short-circuit surviving recorded graph/index/object cleanup.

Only report `cleanup_complete` when all targets are confirmed absent and retained
resource checks pass. Distinguish original setup/product/browser failure,
blocked generation, cleanup conflict/partial failure and unresolved resources.

Restructure the runner so a receipt exists before setup, and cleanup covers
setup failure, browser launch failure and workflow failure. Track optional
browser handles safely. Closing the browser must not prevent cleanup, and
cleanup must not overwrite the primary failure. Use bounded CLI timeouts and
safe serialization. Never auto-clean older runs or current environments.

## 6. Files and trace

| File / entry point | Purpose |
| --- | --- |
| `backend/scripts/e2e_governance_fixture.py`: setup/inspect/cleanup | Require receipt; remove generic prefix cleanup/multi-hop traversal; preserve blocked generation. |
| `backend/scripts/e2e_run_resources.py` (new if needed) | Receipt validation, ownership/preflight, exact SQL/graph/index/object operations and retry receipts. |
| `frontend/tests/e2eLive.mjs`: fixtureCommand/lifecycle | Pass receipt, cover partial startup, retain primary and cleanup failures. |
| `backend/tests/test_chg295_e2e_cleanup.py` (new) | Real exact-ID, shared dependency, race and retry tests. |
| Bounded `frontend/tests/` runner tests if needed | Genuine process/lifecycle/error reporting, no fake browser/service success. |
| CHG-295 spec/changelog/plan/test/trace and new follow-up report | Source-bound results and requirement/test mapping; old failures retained. |

Do not edit generated/dependency folders or unrelated product code. If this needs
application schema/dependency or general maintenance changes, stop for review.

## 7. Test strategy and commands

T21..T30 in TEST_PLAN.md cover receipt rejection, same-prefix A/B isolation,
shared resource retention, inbound CASCADE/SET NULL rejection, graph unknown/late
edges, index UUID/alias/foreign-document denial, object replacement denial,
missing SQL root, partial-service retry and failed-startup lifecycle.

Use fresh real PostgreSQL/Neo4j/OpenSearch/S3 and controlled storage inputs, not
mocks/fakes or generated-success substitutes. Provision only needed services;
retain the existing cap of eight containers / 8 CPU / 12 GiB, internal-only
network, explicit loopback transport and exact outer-stack cleanup. No reuse of
cleaned runs/current credentials/production volumes. Migrate disposable DBs
through V048; no V049 or live DDL. Real browser work, if needed, remains within
the existing skill and fresh-identity requirements.

After amendment approval:

```text
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
python -m pytest tests/test_chg295_e2e_cleanup.py
# Selected real lifecycle tests, then the existing CHG-295 focused regression.
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh coverage:check
```

Full-suite/E2E claims require genuine prerequisites. Original 529 PASS/11 FAIL,
59.3662% Backend coverage and Frontend/browser gaps remain unresolved until new
source-bound evidence proves otherwise. Planning/static PASS cannot approve
this amendment, waive missing Provider prerequisites or authorize deployment.

## 8. Implementation decisions within the approved scope (2026-09-11)

- `e2e_external_resources.py` separates real graph/index/versioned-S3 clients
  from SQL/journal handling. Production clients and general maintenance remain
  unchanged. The test-only S3 signer adds query/version/metadata signing.
- PostgreSQL locks exact participating tables in stable order with 3-second
  lock/10-second statement bounds, and checks actual inbound constraints and
  triggers. Neo4j uses ordinary DELETE, not DETACH. OpenSearch fences the owned
  index's writes before rechecking its UUID, aliases and exact documents.
  Service-admin metadata replacement cannot be made conditional by index UUID;
  require exclusively owned disposable services with other writers quiesced.
  A failed post-fence check may leave this owned index write-blocked for retry;
  it does not authorize clearing the block on unrelated resources.
- S3 cleanup requires enabled versioning and confirmed immutable version ID,
  ETag and creation markers. It retains a newer same-key version and siblings.
  An uncertain create without a version receipt requires manual review.
- Per-index/per-object deletion receipts are durable immediately; graph/SQL
  receipts follow their transaction commits. A lost deletion acknowledgement is
  partial/unresolved, never evidence of a cross-service rollback.
- `init` creates a private receipt before setup; `prepare-input` only parses
  supplied Markdown. `setup` now explicitly returns E2E_BLOCKED. Removal of the
  old synthetic completed build does **not** establish a replacement real
  ingestion/publication path. Integrating genuine generation and workflow-created
  resource receipts remains open; no current or historical data can be adopted.
- CLI cleanup requires `--manifest`; optional `--project-id` must match the one
  owned project. Explicit `E2E_ISOLATION=fresh-disposable` and
  `E2E_WRITERS_QUIESCED=1` supplement service identity proofs, not replace them.
  No app `.env` fallback. New fixture setup remains blocked even if credentials
  happen to exist. This is not a removal/waiver of the existing browser test.
- External API references (actual isolated compatibility must also pass):
  [OpenSearch index blocks](https://docs.opensearch.org/latest/api-reference/index-apis/blocks/),
  [S3 DeleteObject/versionId/If-Match](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObject.html).

## Historical approval request

Approve this bounded amendment for repository implementation and fresh isolated
non-Provider tests, without application images, Kubernetes/Helm, current-data
cleanup or identity changes.

Suggested explicit confirmation:
`Peter approves CHG-295 Exact Run-Owned E2E Cleanup Plan Amendment`

## Planning verification

2026-09-11: `spec:doctor`, `spec:trace` (14 active requirement mappings),
`plan:doctor`, `test:plan` and `git diff --check` pass. `plan:approved` correctly
exits 1 because this amendment is pending Gate 4. The active gate/changelog row
now identifies the pending amendment while retaining the original approval in
history; the harness was not changed to bypass that distinction.

Only specification/plan/test-design/trace documents changed in this continuation.
No feature test, service provisioning, cleanup execution, application edit,
Provider call or Kubernetes/Helm operation occurred. Earlier acceptance numbers
are historical evidence, not a result of this planning check.

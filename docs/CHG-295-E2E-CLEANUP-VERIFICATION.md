# CHG-295 — Exact Run-Owned E2E Cleanup Verification

Date: 2026-09-11. Peter's amendment Gate 4 approval recorded in
`DEVELOPMENT_PLAN.md` and `CHG-295-E2E-CLEANUP-PLAN.md`.
Requirement scope: SPECIFICATION §10.52 `ACCEPT-CLEAN-001..004` and retained
`ACCEPT-REPAIR-002`. This is **focused implementation/verification, not complete
CHG-295 or release acceptance**. No deployment or Provider authorization added.

## Implemented

| File / entry | Purpose |
| --- | --- |
| `backend/scripts/e2e_run_resources.py`: RunJournal | Private locked atomic receipts, creation intent before writes, exact IDs, immutable target binding, one project, safe errors and resumable state. |
| Same: SqlResources / SqlBatch / cleanup_run | Exact complete PKs, creation/scope fingerprints, actual inbound FK/trigger preflight, bounded stable locks, child-first SQL transaction, only owned nullable cycle links, all-store preflight and per-store/item receipts. |
| `backend/scripts/e2e_external_resources.py`: GraphResources / GraphBatch | Exact node/edge identities and fingerprints, shared-node retention, unknown/late edge refusal, ordinary DELETE without traversal/DETACH. |
| Same: IndexResources / IndexBatch | Exact dedicated index UUID/run marker, no aliases or foreign documents, write fencing, exact-name deletion; no shared-index delete-by-query. |
| Same: ObjectResources / ObjectBatch | Test-only real S3 SigV4 query client; confirmed version ID/ETag/run metadata; delete only that version; retain newer same-key versions, siblings and bucket. |
| `backend/scripts/e2e_governance_fixture.py` | Receipt-required CLI, no app .env fallback or generic cleanup imports. Old fixed vectors/completed-build seeding removed. Input-only Markdown parser path; generation-dependent setup explicitly blocked. |
| `frontend/tests/e2eRunLifecycle.mjs`, `e2eLive.mjs` | Private receipt path before setup, bounded helper process, cleanup after setup/startup/workflow failures, optional browser handle, primary/close/cleanup errors retained separately. |
| `backend/tests/test_chg295_e2e_cleanup.py`, `frontend/tests/chg295E2ELifecycle.test.mjs` | Real resource, failure, retry and process verification; no mock services or generated-success adapters. |

`cleanup_test_data.py` is unchanged. This amendment does not change application
API, schema, permissions, chunks, identity or ingestion algorithms. Earlier
CHG-293/294/295 dirty work was preserved.

## Results

| Check | Result |
| --- | --- |
| Real cleanup suite, final source | **28 passed, 0 failed**, 40.37 seconds. |
| Actual helper/process lifecycle | **4 passed**; blocked setup still cleans; cleanup refusal preserves both errors; actual process startup/close errors do not suppress cleanup; legacy receipt-less CLI rejected. |
| Existing Traditional Chinese/English deletion error formatter regression | **2 passed**. Combined Node invocation: 6 passed. |
| Narrow Python coverage, three E2E helper modules | 86.8254% combined; 87.5954% statements; 83.0189% branches; zero exclusions. Not global coverage. |
| Per-module narrow combined coverage | run resources 99.3127%, external resources 100%, governance CLI 26.3636%. The separate actual CLI subprocess tests are not included in this pytest coverage report. |
| spec:doctor / spec:trace / plan:approved / test:plan / backend:syntax | PASS. Trace has 14 active mappings. |
| Targeted ESLint on e2eLive/e2eRunLifecycle/chg295E2ELifecycle, Node syntax and git diff --check | PASS. |
| coverage:check | **FAIL**, exit 1: missing full Frontend source-bound coverage evidence. No threshold or evidence bypass. |
| Full test:e2e, clean environment | **BLOCKED**, exit 1: fresh app/OIDC endpoints and user credentials missing. No browser or Provider launched. |
| Targeted high-severity/high-confidence Bandit scan | **BLOCKED**, module not installed. No new dependency installed or scan PASS claimed. |
| Complete Backend and Frontend suites | Not rerun: this stack intentionally has no app/OIDC/browser services. Historical 529 PASS / 11 FAIL and 59.3662% Backend combined coverage remain unresolved; not results for this source. |

Real cases include same-prefix A/B across all four stores; shared user/role/model/
Tag retention; complete composite PKs; restrictive/CASCADE/SET NULL foreign rows;
SQL creation/scope replacement; owned nullable cycles; actual custom trigger
refusal; graph duplicate identity and a genuinely concurrent late edge; index
aliases/foreign documents/marker mismatch and actual delete/recreate same-name
UUID replacement; immutable S3 version replacement/ETag mismatch; missing SQL
root with surviving external resources; foreign service binding; private,
symlinked, malformed, duplicate and concurrently locked receipts.

The partial failure case observes a committed graph deletion, terminates only
the named test-owned PostgreSQL transaction via its exact PID, and verifies
`cleanup_partial`, retained SQL rows, successful reconnect/retry and a second
idempotent retry. No whole service or unrelated session is stopped.

## Commands and reproducibility

The fresh private launcher provides only explicit CHG295_CLEANUP_* credentials,
PYTHONPATH and tool paths; it does not read current app .env. Host interpreter:
`backend/.venv/bin/python`; Node: 24.21.0 previously available on this host.

```text
backend/.venv/bin/python /tmp/chg295-cleanup.ucZv6b/run.py \
  backend/tests/test_chg295_e2e_cleanup.py \
  --cov=scripts.e2e_run_resources --cov=scripts.e2e_external_resources \
  --cov=scripts.e2e_governance_fixture --cov-branch --cov-report=term-missing \
  --cov-report=json:/tmp/chg295-cleanup.ucZv6b/cleanup-final-coverage.json \
  --junitxml=/tmp/chg295-cleanup.ucZv6b/cleanup-final-junit.xml
node --test frontend/tests/chg295E2ELifecycle.test.mjs frontend/tests/chg295DeletionErrors.test.mjs
node --check frontend/tests/e2eLive.mjs
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh coverage:check
# test:e2e invoked through env -i with only HOME and tool PATH:
./HARNESS/harness.sh test:e2e
backend/.venv/bin/python -m bandit -q -r backend/scripts/e2e_run_resources.py \
  backend/scripts/e2e_external_resources.py backend/scripts/e2e_governance_fixture.py -lll -iii
git diff --check
```

The temporary launcher/environment is no longer runnable against its services:
they were removed. Reproduction requires a **new** disposable stack and fresh
credentials, not reusing this run's resource identities. JUnit/coverage/migration
logs remain in its private directory; source and artifact SHA-256 values are in
`CHG-295-E2E-CLEANUP-EVIDENCE.json`. No secrets are copied to repository evidence.

## Isolation and cleanup

New stack `chg295-cleanup-uczv6b`: PostgreSQL, Neo4j, OpenSearch, RustFS and one
read-only relay; internal network and explicit loopback-only byte transport.
Existing pinned images used; no image built. Flyway helper ran with target 48.

Initial isolated migration failed at V042 because the newly created database
was named `acceptance`; V042 requires `nomosmart`. A fresh `nomosmart` database
was created in that same disposable instance, and unchanged V001..V048 applied
successfully. No migration edited or skipped; no V049 or current/live DDL.

After verification, exact container IDs and ownership labels were checked, then
all **five new containers, their anonymous test volumes and the empty run-owned
network** were removed. Test data in those volumes is not recoverable; recreating
the isolated stack is required. Private receipts/reports are retained. The exact
loopback relay PID was stopped after command-path verification. Final label
queries returned no remaining containers/networks. The four pre-existing ingress
loopback/LDAP/phpLDAPadmin containers remained running. No Kubernetes/Helm call,
current MAAS data access/write, current index mutation, model execution or
membership/permission change was performed.

## Remaining limitations and next work

1. Full governance E2E setup intentionally stays blocked. Implementing genuine
   model execution and capturing workflow-created resources at creation time is
   still required; the old synthetic fixture is not a valid replacement. This
   cleanup amendment neither completes that integration nor authorizes Provider
   calls or retrospective ownership adoption.
2. Actual browser startup/close failure and authenticated full E2E were not
   exercised. Real process failure tests verify lifecycle logic, not browser UX.
3. OpenSearch write blocking protects in-flight document writes, not arbitrary
   administrative index replacement. Require exclusive disposable-service
   ownership and quiesced outside writers. A post-fence conflict may leave the
   owned index blocked; retain its receipt for review/retry. These constraints
   are part of the test-only contract, not production cleanup guarantees.
4. Unconfirmed S3 version receipts, custom triggers, unknown/cross-schema SQL
   dependencies and ambiguous ownership fail closed for review. Receipts are
   trusted private execution records, not signed anti-forgery authorization.
5. Focused 100% external-module coverage does not imply exhaustive fault/race
   coverage. Broader outage combinations, lost acknowledgements and full CLI
   configuration branches remain additional verification work.
6. Original Backend failures, independent full Frontend/Backend coverage gates,
   full security scan and genuine E2E remain open. **Do not deploy on this report.**

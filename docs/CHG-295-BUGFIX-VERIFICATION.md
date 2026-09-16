# CHG-295 B01 — Candidate/governance lock inversion

Date: 2026-09-11. **Confirmed product Bug repaired; focused verification passes.
Not a full release acceptance or deployment.**

Peter requested `先針對Bug處理`. This continuation stays inside approved
CHG-295 §10.52 `CHUNK-DEL-001/003/004` concurrency and preservation scope.
It does not rewrite the eleven remaining broad assertions to make them pass.

## Root cause and correction

Manual candidate writes and artifact reconciliation locked DocumentVersion
before Project. Existing tag/review/graph governance uses Project -> Document
-> DocumentVersion. Two real concurrent transactions could therefore each hold
the row the other needed. PostgreSQL detected the cycle as **40P01 deadlock**.
On DELETE this could become a safe conflict, while other write paths could fail;
error translation did not remove the underlying inversion.

The corrected entry order is **Project -> Document -> DocumentVersion -> Chunk**.
The existing Version-before-Chunk fence is preserved. Staging readers acquire
parent KEY SHARE locks before Version SHARE and hold them through evidence
commit, so a new ChatRecord's parent FK cannot form the reverse wait cycle.
State is refreshed after waiting; cached active/non-deleted ORM objects cannot
authorize a mutation after a concurrent archive/deletion.

| File / function | Purpose |
| --- | --- |
| `backend/app/domain/chunk_artifacts.py` — `lock_chunk_write_scope` | Shared entry-only parent-first fence; suppress premature autoflush and refresh locked scope. |
| Same — `execute_chunk_artifact_reconciliation` | Same order at entry and error-path reacquisition; refuse deleted/missing scope before external artifacts; preserve generation/revision protections. |
| `backend/app/api/routes/documents.py` — `_lock_manual_edit_scope`, `_ensure_manual_edit_allowed`, `_delete_chunk_transaction` | Apply the fence before candidate create/edit/delete; retain existing target/stale/review/permission rules and repeated-delete 404. |
| `backend/app/api/routes/serving.py` — `_resolve_document_staging_scope` | Parent-compatible read locks before shared Version locks; deterministic document/version ordering and current scope validation through evidence commit. |
| `backend/tests/test_chg295_lock_order.py` | Eight real-storage concurrency/state cases; no Provider/generation success substitution. |
| `backend/tests/test_chg295_chunk_deletion.py` | Adds authenticated actual DELETE versus governance/tag lock race. |

No schema, migration, dependency, permission, API wire, Frontend or configuration
change was required for B01. The larger dirty worktree includes earlier approved
changes; its entire diff is not solely attributable to this repair.

## Actual verification

| Run | Result |
| --- | --- |
| Before repair, concurrent `edit_enqueue` and `reconcile` versus governance | **2 FAIL**, both actual PostgreSQL **40P01**. These first two test cases were not relaxed for the repair. |
| Same two cases after repair | **2 PASS**. |
| Expanded T31 lock/state/storage suite | **8 PASS**, 0.81 s. Includes archive, deleted document, review lock, stale revision, worker scope refusal and reader-FK commit versus waiting edit. |
| First combined API attempt | **15 PASS / 63 setup errors**, no test failures, 1.959 s. Schema-only fixture could not resolve public `pgcrypto.digest` from its isolated search path; recorded as an infrastructure failure, not a product PASS. |
| Combined rerun on a separate fresh API database | **78 PASS / 0 FAIL / 0 setup errors / 0 skipped**, one existing multipart import deprecation warning, 19.313 s. Includes the 8 T31 cases, new authenticated DELETE race, and 69 prior focused cases. |

The combined run covers actual PostgreSQL, Keycloak tokens/JWKS and FastAPI
authorization, editor CRUD and history policy, protected deletion/rollback,
accounting retention, Neo4j/OpenSearch exact zero-candidate cleanup/retry and
unknown-edge refusal. Stored candidate/history inputs prove storage and locking,
**not** LLM generation, embedding readiness or a successful publish workflow.

Tests run with the repository Python environment, clean explicitly supplied
test configuration, `pytest -c /dev/null --rootdir=<repository> -p no:cacheprovider
--tb=short -q`, and these files:

- `backend/tests/test_chg295_lock_order.py`
- `backend/tests/test_chg295_chunk_deletion.py`
- `backend/tests/test_chg295_acceptance_contracts.py`
- `backend/tests/test_chg293_project_content_and_chat_history.py`

The new lock suite requires `CHG295_BUG_DATABASE_URL` for a fresh V048-migrated
database. Existing API fixtures use separate `CHG293_DATABASE_URL` /
`CHG295_DATABASE_URL`, their own disposable schemas, and explicit fresh Keycloak,
Neo4j and OpenSearch endpoints. No `.env` fallback or current credentials.
No test assertion, product migration or threshold was altered for the setup fix.

Raw logs/JUnit remain private under `/tmp/chg295-bugs.ViCm2F`; failure contexts
can contain disposable login tokens and must not be published. Safe hashes,
source bindings and final verification/cleanup status are recorded in
`CHG-295-BUGFIX-EVIDENCE.json`.

## Isolation, gates and remaining work

Only fresh labelled PostgreSQL/Keycloak/Neo4j/OpenSearch/byte-relay containers
were used, on one internal-only network. Existing local images were reused;
there was no image build, Helm/Kubernetes action, current-data operation,
Provider/billing call, reindex or production graph repair. Bounded transient
Flyway migrated only the fresh database through unchanged V048.

Final governance commands `spec:doctor`, `spec:trace`, `plan:approved`,
`test:plan`, `backend:syntax`, and `git diff --check` all exited 0.
Five exact run-owned containers, three disposable anonymous volumes and the
empty internal-only network were removed after label/ID checks. Three exact
host relay processes were stopped. No run-labelled container, network or owned
anonymous volume remains. Existing HTTP/HTTPS loopback and LDAP/phpLDAPadmin
containers retain their IDs, running state and start times. These disposed
test resources/data are not recoverable; the private verification logs remain.
Safe exact resource/source bindings are in the evidence JSON.

Remaining limitations are not hidden by this focused result:

- The historical full Backend result **529 PASS / 11 FAIL** was not rerun or
  cleared; full coverage remains below 80% (historical combined 59.3662%).
- Full Frontend/browser conflict-state and genuine E2E acceptance remain open.
- Remaining concurrency/reference combinations in the full T05..T10 matrix
  are not all covered by these nine newly added cases.
- Parent locking can increase same-project contention while a reader or artifact
  worker runs. Load/performance and Provider-backed nonzero reconciliation are
  not claimed by these no-Provider tests.
- No deployment occurred. Existing conditional deployment remains blocked by
  the separate release acceptance gates.

# CHG-295 — Candidate deletion integrity and acceptance repair checkpoint

Date: 2026-09-11. **Partial implementation; release acceptance FAILED/incomplete.**
Peter approved the detailed CHG-295 plan. Specification: 10.52
`CHUNK-DEL-001..004`, `ACCEPT-REPAIR-001..003`; existing `CHUNK-002/003`,
`USAGE-001`, `TEST-002` and independent 80% coverage gates remain in force.

## Outcome

The original candidate-delete defect is corrected: the authorized exact active
candidate row is physically removed, not merely marked deleted. The original
broad permanent-delete assertion and corrected CHG-293 edit/delete test pass.
Predecessor content and accounting rows survive; only necessary nullable links
to the deletion set are detached with ID-only audit, in the same transaction.
Protected or unprovable scope rejects atomically. This is not a historical-row
cleanup or a change to ordinary document/conversation soft deletion.

This does **not** complete the whole plan. Eleven broad Backend cases still fail;
coverage, remaining concurrency/protection combinations, full Frontend/browser
and genuine E2E preparation/acceptance remain open. No image, deployment,
Provider, live migration or current-environment data operation occurred.

## Verification results

| Check | Actual result |
| --- | --- |
| New CHG-295 deletion suite | 20 PASS on real PostgreSQL/OIDC; actual Neo4j/OpenSearch zero-cleanup cases included. |
| Combined CHG-295 deletion/defaults and CHG-293 regressions | 69 PASS, one warning, 11.88 s. This includes the 20 cases above, not another independent 69 new cases. |
| Contract subset | 47 PASS; approval Markdown layout, chat pagination source contract, canonical graph source contract, clean-process settings, Helm schema behavior, substantive deployment/LDAP docs. |
| Follow-up contract subset | 12 PASS; actual Flyway set/checksums and CHG-293 Editor archive denial, plus copied API compatibility documentation. Overlaps the full suite. |
| Full Backend r1 | 527 PASS / 13 FAIL / zero setup errors, exit 1, 69.47 s. Preserved. |
| Full Backend r2 | **529 PASS / 11 FAIL / zero setup errors**, exit 1, 64.27 s. |
| Full Backend coverage | Lines/statements **63.4306%** (11,911 / 18,778); branches **44.7841%** (2,344 / 5,234); combined pytest-cov **59.3662%**, below 80%. Original denominator/threshold rules retained. |
| New deletion helper coverage | Lines 87.9032%, branches 81.5789%, combined 86.4198%; this module result does not satisfy the full Backend gate. |
| Pure Frontend error formatter | 2 PASS: actual zh/en dictionaries, safe conflict/request-ID formatting, no raw server-message leakage and fallback status handling. Not browser evidence. |
| TypeScript no-emit check | Exit 2: existing generated `frontend/.next/dev/types/validator.ts:161` references missing `src/app/setup/page.js` (TS2307). No generated/dependency directory was edited. Clean build/type generation remains needed. |
| Full Frontend / browser / E2E | Not rerun in this checkpoint. Earlier Frontend 12.64% lines / 9.51% branches is historical, not new source-bound evidence. No complete E2E PASS. |
| Governance/static checks | `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`, `backend:syntax` and `git diff --check`: all exit 0 after checkpoint documentation updates. |
| Cleanup | Seven exact run-owned containers and disposable anonymous volumes removed; empty internal-only network removed. Label queries return no remaining containers/networks. API/relay processes stopped. |

Machine-readable totals, failed node IDs, artifact hashes and 261 matching tested
application/Backend test files:
[CHG-295-VERIFICATION-EVIDENCE.json](CHG-295-VERIFICATION-EVIDENCE.json).
Raw logs remain private in `/tmp/chg295-acceptance.qzlGDz`; do not publish them
because pytest failure context can include disposable authentication tokens.

## Implementation and trace

| Files / functions | Requirement and purpose |
| --- | --- |
| `backend/app/domain/chunk_deletion.py`: `delete_candidate_chunk` | Exact reference inventory and FK catalog checks; same-scope lineage, chat/validation, usage, vectors/builds, approval/public evidence checks; nullable detachment/audit; ordered physical deletion; retained-run counters. |
| `backend/app/api/routes/documents.py`: `delete_chunk`, manual-edit lock, active reindex | Version-first transaction locking, existing authorization/status/lock precedence, rollback and safe known database-conflict translation; one revision and durable reconciliation; no reindex of historical Chunks. Removes obsolete unsafe evidence helper. |
| `backend/app/api/routes/serving.py`: `_resolve_document_staging_scope` | Shared version fence held through staging chat/validation evidence commit; prevents JSON citations arriving after delete inventory. Real two-connection fence test, no generation call. |
| `backend/app/domain/chunk_artifacts.py` | Reconciliation refreshes under the same version lock, including failure handling; zero-candidate path invokes bounded graph cleanup and existing OpenSearch deletion. |
| `backend/app/domain/graph_reconciliation.py`: `clear_zero_candidate_chunks` | Separate candidate-only cleanup with relational eligibility and exact graph ownership/edge checks. Ordinary DELETE, not broad DETACH; unknown edges fail before deletion. Existing CHG-292 formal repair safeguards remain. |
| `frontend/src/lib/operationalMessages.ts`, `frontend/src/i18n/locales/{zh,en}.json` | Safe localized `chunk_delete_reference_conflict`; no foreign scope details. |
| `frontend/src/app/project/[id]/knowledge/[knowledgeId]/page.tsx` | Actual delete error state consumes the safe localized message; failed request does not take the success path that removes cards/selection. Browser state still needs acceptance. |
| `backend/tests/test_chg295_chunk_deletion.py`, corrected `test_chg293_project_content_and_chat_history.py` | Real storage/FK/HTTP/auth, predecessor retention, exact deletion, financial retention, denial, audit rollback, concurrency and zero-artifact cleanup. |
| `backend/tests/test_chg295_acceptance_contracts.py`, `test_chg209_public_api_behavior.py` | Real HTTP Integration Client defaults, invalid pagination/filter rejection, scoped temporary grant and revoked-grant denial; direct function test no longer accidentally receives FastAPI Query objects. |
| Other named Backend contract tests | Current layout/pagination/graph/config/schema/migration/archive contracts, without production guard relaxation. See mapping below. |
| `frontend/tests/chg295DeletionErrors.test.mjs` | Pure formatter/localization behavior, not mocked API or browser success. |
| `deploy/README.md`, `deploy/docker/ldap-test/README.md` | Restored substantive secret/config/lifecycle/rollback and synthetic-directory/non-assignment guidance; commands not executed against the current environment. |

No SQL/ORM/schema migration was needed for this repair. Existing relevant FKs
are nullable. No new dependency, image, API endpoint or permission grant was
introduced by CHG-295. Existing unrelated CHG-293/294 dirty edits are preserved;
the complete Git diff is not solely attributable to CHG-295.

### Focused evidence and limits

- Owner/Editor exact deletion, raw/other-version preservation, orphan/shared tag
  retention, vectors tied to owned versus foreign builds, and repeated 404.
- Real usage/chat/validation restrictive FKs: retain amounts/tokens/attempt
  history; scoped link detachment and safe audit; preserve unrelated retry items.
- Cross-version lineage, chat/citation/usage/retry scope, submitted/cancelled
  evidence and an unknown FK table reject without partial mutation.
- A real database CHECK failure on audit creation rolls back the transaction;
  two actual DELETEs produce one success/one 404 and a single revision/outbox.
- Real staging reader lock delays deletion; the committed late evidence is then
  included in deletion inventory. No fabricated Session or lock behavior.
- Real Neo4j and OpenSearch zero cleanup preserves shared/non-target resources;
  an unknown graph edge fails closed, with safe retry after removing only the
  test-owned edge. These are controlled storage inputs, not generated vectors.

The complete T05..T10 cross-scope/state/assignment/concurrency matrix is not yet
exhausted. In particular, broader edit/reconciliation/tag-assignment races and
browser conflict/selection behavior remain. Shared locks span real answer
generation in production, so contention/timeout behavior needs load acceptance.
Nonzero successful re-embedding remains separately Provider-gated; queued/error
observations are not successful generation evidence.

## Original failure mapping and remaining eleven cases

Historical baseline remains unchanged: **496 PASS / 23 FAIL** in
`CHG-294-R2-FULL-ACCEPTANCE.md`. The repair did not delete tests or lower coverage.

| Baseline area | Current disposition |
| --- | --- |
| Candidate physical deletion (`test_live_permanent_chunk_deletion_is_version_scoped_and_blocks_zero_chunk_next_stage`) | Product repaired; retained original assertion now passes. Corrected CHG-293 soft-delete assertion to the specification. |
| Approval evidence/layout (`test_approval_evidence_parity.py`) | Current canonical Markdown/layout helper, consistent with CHG-282/284; PASS. |
| Chat scope/history (`test_chat_scope_and_review_lock.py`) | Current paginated frontend list API/cursor source contract; PASS. Behavioral shared history remains in real CHG-293 tests. |
| CHG-202 graph source contract | Shared canonical labels/relations and projection builder rather than obsolete inline graph-node spelling; PASS. |
| CHG-209 Integration Client defaults | Explicit arguments for direct helper invocation plus new actual HTTP default/permission test; PASS. |
| CHG-216 defaults | Clean subprocess environment; `_env_file=None` alone does not ignore environment; PASS without weakening TLS. |
| CHG-229 Helm/schema | Actual template validation, inline/ref schema equivalence, ambiguous service modes and all peripheral floating-tag negatives retained; PASS. |
| CHG-237/264 runbook failures (four cases) | Two substantive missing runbooks restored; whitespace-independent prose checks; PASS. |
| CHG-241 migration/archive | Actual applied set through V048 and every Flyway checksum, not literal 032 or arbitrary minimum. Editor cannot archive even with a grant; appropriate non-Editor/Owner checks retained; PASS. |

Remaining failures all live in `backend/tests/test_live_backend_api_behavior.py`:

| Test suffix (`test_live_…`) | Observed failure / needed work |
| --- | --- |
| `system_reports_and_session_drafts` | 403 `report_model_permission_required`; fixture lacks `Report.ModelReport`. Re-prove explicit denial then bounded grant/allow, not broad permission bypass. |
| `seeded_document_knowledge_serving_chat_and_notifications` | Published-tag mutation expects 200; current `published_tag_revision_required` correctly requires reviewed candidate revision. Repair valid positive preparation and retained published denial. |
| `seeded_reference_and_approval_workflows` | `submission_evidence_not_ready`: graph preview, pipeline and staging index prerequisites missing. Do not fabricate completed evidence. |
| `external_services_and_domain_adapters` | New isolated Keycloak realm has no ordinary users; real snapshot is empty. Create only run-owned real identities for this scenario; subsequent canonical retrieval inputs also need review. |
| `integration_adapter_embedding_and_switch_edges` | Obsolete embedding secret-reference error expectation; current runtime resolver rejects invalid references. Later workflow prerequisites remain to validate. |
| `configuration_identity_worker_and_sync_edges` | Identity sync list API is paginated, test expects a bare list; review all later assertions against current API contracts. |
| `pipeline_execution_and_publish_edge_behaviors` | Incomplete canonical retrieval fixture fails before the intended publish-state guard. Prepare genuine non-Provider inputs and retain precise denial, not just substitute a different error. |
| `serving_and_document_response_helpers` | Calls removed `_try_add_graph_node`/`_append_graph_edge`; replace with equivalent canonical projection/deduplication/truncation behavior tests. |
| `extraction_ai_provider_and_publish_helper_edges` | Obsolete model/OCR secret-reference error expectations; verify current resolver contract and later genuine prerequisites. |
| `approval_project_and_data_source_route_edges` | Calls removed project-route member helpers; use current public/domain eligibility behavior with actual permissions. |
| `compatibility_routes_execute_governed_workflows` | Iterates a paged API response as a bare list; later governed workflow preparation must also be genuine. |

These are observed first failures, not proof that each entire broad case only
needs one assertion change. The existing shared seed manually writes completed
pipeline/build state; it cannot certify real ingestion/publish under TEST-002.
No blanket test expectation replacement or fabricated success was made.

## E2E safety discussion — not executed

`backend/scripts/e2e_governance_fixture.py` still needs the approved genuine
parser/chunker/normalizer preparation. Its existing fixed-vector/completed-build
path was **not run** in this checkpoint. A second source-identified issue needs
an explicit safe boundary before extending cleanup behavior:

1. `cleanup_fixture(project_id)` passes the global E2E prefix to `_collect_scope`,
   not the exact project ID; multiple matching projects can enter SQL cleanup.
2. Neo4j cleanup walks undirected relationships up to three hops and uses DETACH
   DELETE; shared related entities are not proven to belong to that one run.
3. OpenSearch cleanup removes a whole index after a partial profile-ID check;
   ownership/sharing must be established, not inferred from the name.

No incident against current data was observed or caused. Proposal for Peter:
bind creation and cleanup to a per-run exact resource manifest, retain shared
entities, reject ambiguous ownership, and make partial-setup cleanup resumable.
Keep the general maintenance cleanup utility unchanged unless separately scoped.
Only fresh disposable test resources and non-Provider verification are proposed;
no current-data cleanup, Provider approval or deployment follows from this choice.
This does not block or waive all other remaining contract/coverage work.

## Commands and source binding

Executed focused tests with a clean environment and fresh service configuration:

```text
python /tmp/chg295-acceptance.qzlGDz/run.py backend/tests/test_chg295_chunk_deletion.py backend/tests/test_chg295_acceptance_contracts.py backend/tests/test_chg293_project_content_and_chat_history.py --junitxml=/tmp/chg295-acceptance.qzlGDz/chg295-and-chg293-r3.xml
python /tmp/chg295-acceptance.qzlGDz/run_api.py suite r2
# Above invokes unchanged ./HARNESS/harness.sh test:backend in the clean source copy.
node --test frontend/tests/chg295DeletionErrors.test.mjs
node frontend/node_modules/typescript/bin/tsc --noEmit --incremental false -p frontend/tsconfig.json
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
git diff --check
```

Runtime: existing Backend Python 3.12 venv, Node 24.21.0. Main disposable database
used real Flyway through V048 including V042, plus independent suite databases;
V049 was not applied. All service endpoints/credentials were freshly provisioned,
not loaded from current `.env` or Kubernetes Secrets. Internal-only Docker network
and loopback allowlisted byte transport; no TLS termination or response stubbing.

The r2 source manifest was generated before the full test run. Tested Backend
application/tests and Frontend application bytes match the repository at this
checkpoint. New pure Frontend test has its own current source hash. Evidence
contains no raw credentials, answers, documents, vectors or failure-log bodies.
Earlier focused fixture import/conversation-ID errors, README line-wrap failure,
r1 copied-doc omission and obsolete Editor archive assertion are retained in
hashed logs/JUnit, not overwritten as successful initial runs.

## Safety and remaining acceptance

Exact disposable containers/network/anonymous volumes and fresh test data were
removed; evidence/source remain. Removed test data is not an application backup.
No Kubernetes read/write, Helm revision, existing application image, current
database/identity/index or Provider operation was performed in CHG-295. Therefore
this report makes no new claim about the health/revision of the current cluster.

Next work: confirm the proposed E2E cleanup refinement, finish the eleven broad
contract/preparation cases, remaining deletion matrix and real UI checks, then
expand both full coverage suites. Real Provider-dependent acceptance requires
separately bounded models/data/cost approval. All 80% and E2E release gates remain;
no deployment should proceed from this partial report.

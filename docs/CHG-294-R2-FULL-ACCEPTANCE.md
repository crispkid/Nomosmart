# CHG-294 R2 — Full acceptance continuation

Date: 2026-09-11. Peter requested `先完成驗收`. Status: this acceptance run is
finished but FAILED; release acceptance remains incomplete and no deployment
occurred. Requirements unchanged: specification 10.51 FESEC-003/004,
TEST-002 and separate Frontend/Backend 80% coverage gates.

## Scope and safety

- Establish fresh bounded real disposable services, test identities and data;
  never load the current deployment's environment, Secrets or MAAS data.
- Use existing suites and source without changing product behavior/assertions.
- No Provider calls, Kubernetes/Helm writes, image build or current-data action.
- Existing known stored vectors/history are test inputs for persistence and
  governance, not successful embedding/generation evidence.
- Preserve earlier successful image/security/focused tests and failed coverage.
  Report discovered defects; further repairs require separately confirmed scope.
- Clean only this run's exact labelled services/network and disposable scopes.

## Results

| Check | Actual result |
| --- | --- |
| Full Backend harness | **496 passed, 23 failed, zero setup errors**, 1 warning, 56.17 seconds; 519 collected cases completed. Exit 1. |
| Backend coverage | Lines/statements **62.7349%** (11,685 / 18,626), branches **43.6897%** (2,264 / 5,182), combined pytest-cov 58.5895%. Below 80%; no passing coverage manifest produced. |
| Clean Frontend install/build | Locked `npm ci` and `npm run build` pass on verified Node 24.21.0. No dependency/script-policy grant or product change. |
| Full E2E harness | All 5 prerequisite/reachability/runner checks pass. The actual governance/publish case **fails during fixture setup**, before its browser workflow. This is not 5 passing product E2Es. |
| Supplementary Playwright CLI | Fresh real test user signs into the isolated Keycloak realm; callback reaches the authenticated NomoSmart home as `Peter Acceptance`. Limited login/proxy evidence only, not publish acceptance. |
| Earlier Frontend coverage | Unchanged-product prior full-suite result remains **12.64% lines / 11.45% statements / 12.06% functions / 9.51% branches**. Not rerun merely to repeat a known failure; no current full-suite passing claim. |
| `coverage:check` | Exit 1: no full Frontend source-bound passing evidence. No manufactured manifest, exclusion or lower threshold. |
| Governance | `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`, `git diff --check` pass. |

Machine-readable results, all 23 failing node IDs, coverage totals, service image
IDs, source and artifact hashes:
[CHG-294-R2-FULL-ACCEPTANCE-EVIDENCE.json](CHG-294-R2-FULL-ACCEPTANCE-EVIDENCE.json).

## Established blockers and classification

2026-09-11 specification-review correction: blocker 3 below originally left
candidate Chunk deletion for review. That review now confirms a **product
violation of `CHUNK-002`**, not an obsolete hard-delete expectation. Section 6.4
requires the exact candidate Chunk row to be physically removed; `PROJECT-013`
preserves that contract. The CHG-293 focused test's soft-delete assertion also
conflicts with it. Prior counts and raw test evidence are unchanged. Retention
and foreign-key decisions needed for the repair are recorded, pending approval,
in `CHG-295-UNDERSTANDING.md`; no new test result is claimed.

1. **E2E fixture contract is obsolete.**
   `backend/scripts/e2e_governance_fixture.py:233` calls `_content_fingerprint`
   with a chunk that lacks the current retrieval strategy. Actual exception:
   `KeyError: 'normalizer_version'` at `backend/app/domain/embeddings.py:215`.
   The fixture also does not supply `tokenizer_version`; further prerequisite
   gaps must be checked after a scoped repair. Do not invent version values or
   bypass canonical retrieval/approval readiness to force publication.
2. **Several broad tests encode obsolete contracts.** Examples include exact
   Flyway `032` despite real `048`, list assertions against paginated
   `{items, next_cursor}`, calls to removed `_try_add_graph_node` and
   `_users_with_knowledge_project_view`, and literal source/layout `$ref`
   assumptions after approved refactors. These do not prove equivalent user
   paths are broken; they require specification-led test review.
3. **Security/lifecycle fixtures and expectations need review.** The broad
   suite expects model-report access without `Report.ModelReport`, modifies
   published tags, submits without current graph/staging/pipeline evidence,
   expects earlier secret-reference errors and physical deletion where the
   current route marks a chunk deleted. Do not relax production guards simply
   to satisfy these expectations. Any actual behavior/spec disagreement must
   be separately confirmed before changing code.
4. **Two referenced runbooks are absent in the repository itself**:
   `deploy/README.md` and `deploy/docker/ldap-test/README.md`, affecting four
   tests. They were not replaced with placeholders. `API_COMPATIBILITY.md`
   initially omitted from the isolated copy was restored unchanged; that test
   now passes.
5. **One configuration test is not environment-isolated.**
   `Settings(_env_file=None)` still reads environment values. Its default-HTTP
   assertion conflicts with the full suite's mandatory real HTTPS OIDC issuer.
   `_env_file=None` does not mean environment variables are ignored. This needs
   a real subprocess/config isolation design, not a TLS downgrade.
6. **Coverage remains a substantial independent gap.** Fixing setup or the
   above failing assertions alone cannot be claimed to meet either 80% gate.
   Additional meaningful real-service/UI cases need a separately confirmed
   test-remediation scope; do not exclude uncovered modules or inflate metrics.

No product/test assertion was changed in this continuation. Remaining failures
are recorded for review rather than all being labelled production bugs or all
being assumed harmless test drift.

## Isolation, corrections and retained failures

- Workspace: `/tmp/chg294-acceptance.R5Y9Ar`, created with `mktemp -d`.
  Fresh source excludes private `.env`, dependencies and old generated state.
  Required ignored harness/spec files were copied without editing them.
- Six new real service containers plus a bounded Python transport container
  use an explicitly internal-only Docker network. Docker Desktop did not expose
  published ports on that network; a loopback-only byte relay forwards only the
  seven allowlisted test ports through `docker exec`, without TLS termination,
  response substitution, external routing or mounting the Docker socket.
- Keycloak HTTPS discovery passes normal certificate validation using a newly
  generated disposable certificate. Browser login uses a separate HTTP-loopback
  development realm; this is not a claim of production HTTPS browser parity.
- OpenSearch/Neo4j use isolated development authentication settings required by
  the existing suites. No current service security/configuration was weakened;
  these results are not production transport/security acceptance.
- Initial setup errors are retained: Redis's stored repo tag required its actual
  image ID; relay `signal.pause()` ended after child activity and was replaced
  with a persistent wait; S3 provisioning initially omitted its bucket argument;
  required ignored HARNESS files were initially missing. These are setup/tool
  issues, not application test failures, and were corrected before final results.
- First full Backend run: 426 passed / 25 failed / 68 setup errors, combined
  coverage about 52%. The 68 errors came from pgcrypto being installed in public
  while the two suites use a dedicated schema-only search path. Final setup uses
  a different empty database for each of CHG-292 and CHG-293, allowing their
  existing fixtures to install their own extensions; all those errors clear.
- The main full-suite database was recreated separately using **real Flyway
  13.0.0**, with all 48 migrations including V042 applied and genuine audit rows.
  V049 was not applied. The obsolete `032` assertion now fails against real
  `048`, rather than against an absent history table. No audit row was forged.
- Keycloak Admin API was initially missing its task-specific endpoint and two
  adapter checks failed authentication; the refined run explicitly targets the
  new TLS Keycloak service and those checks reach later retrieval-contract
  assertions. No existing deployment credentials were loaded or granted.
- Existing controlled vectors/history are test inputs. The E2E fixture fails
  before commit; no generated answer or actual embedding success is claimed.

## Commands and evidence

The temporary `run.py` launcher supplies only this run's fresh configuration and
uses `NOMOSMART_HARNESS_ROOT_DIR` for the source copy:

```text
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh test:e2e
npm ci --prefer-offline --no-audit --no-fund
npm run build
./HARNESS/harness.sh coverage:check
```

Complete private logs/coverage and a non-sensitive authenticated-home screenshot
remain under the workspace, with SHA-256 references in the evidence JSON.
The 419 checked product/test/schema/chart/package files match repository bytes.
The protected product/chart fingerprint remains
`578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79`;
package/lock/Dockerfile and candidate images were not changed or rebuilt.

## Cleanup and deployment state

All seven exact-label/ID-bound temporary containers, their disposable anonymous
volumes and the empty internal network were removed. The temporary Flyway
container removed itself. Four validated host processes were stopped and the
dedicated Playwright session closed. Test data/realms were disposable and removed;
reports/source/screenshot remain, not a recoverable application-data backup.
Docker label queries and loopback-listener checks confirmed no remaining service.

Final read-only check: `nomosmart-local` stays at **revision 36, deployed**;
Backend/Frontend/Worker/Beat and Keycloak are each Ready 1/1, Redis Sentinel 3/3.
No Helm write, Kubernetes Job, application image build, current application-data
change, live migration or Provider call was performed. Deployment remains held.

## Next decision

Confirm a bounded acceptance-test remediation scope: align fixtures/contracts
with the approved specification, restore required operations documentation,
isolate configuration tests and add meaningful real-service/UI coverage.
No production security guard, product permission rule, API/schema behavior,
threshold or test inventory may be weakened. Product behavior fixes, if needed,
require separate discussion/approval; deployment is still not authorized by a
test-remediation approval.

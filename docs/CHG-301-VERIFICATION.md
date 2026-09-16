# CHG-301 implementation and isolated verification

Date: 2026-09-15. **Focused package test/coverage gate PASS; full release acceptance remains incomplete.**
Approved plan: [PR1 integration plan](CHG-301-PR1-INTEGRATION-PLAN.md).
Requirements: local SPECIFICATION §10.58, CMPSTART-001 through CMPSTART-005.

## Source and authority

- Main source: `5f1a0a2505dee9c85ee621bd2c8680b92d397a45`.
- Original PR #1 head: `c261a494283835af57c0e0678afc7ee7e2c0dcc8`.
- Local branch: `fix/compose-method1-installer`; a non-rewriting merge of main
  is in progress, with the CHG-301 repairs in the working tree. No commit, push,
  PR merge, main update, deployment or registry publication was performed.
- `git diff main -- frontend backend/app backend/Dockerfile sql deploy/helm`
  is empty. Changes visible in those areas relative to the old PR are the
  preserved main integration, not additional CHG-301 behavior.
- No existing environment/config/credential/data source was used for behavior
  testing. No Kubernetes writes/Jobs, Provider, graph/index operation or scan.

## Implementation

| Area | Change |
| --- | --- |
| Package CLI | Catch only missing minikube executable; generate distinct strong OpenSearch admin/service passwords for fresh Compose; preserve existing init and other Helm profiles |
| Shared Secret entrypoint | No root preparation; validated variable/file references and explicit original/private Secret roots; execute the real command unchanged |
| New Compose entrypoint | Fixed service profiles and file allowlist; dedicated private tmpfs; 0400 copies; root-owned 0710 directories; exact path remapping and fail-closed privilege drop |
| PostgreSQL | Keep upstream entrypoint/CMD, native postgres identity and upstream gosu; explicit Compose `command: [postgres]` because overriding entrypoint clears the image CMD; tested init/restart against a new isolated database |
| Migration/RustFS | Default UID10001 remains usable without Compose preparation; Compose opts into the root helper explicitly; no Flyway downgrade |
| Compose | Worker/Beat depend directly on successful migration/bootstrap and healthy bundled Redis, eliminating the Backend-health cycle without removing readiness checks |
| Build context | Explicit allowlists for the new helper and PostgreSQL/RustFS contexts; generated Secret directories excluded |
| Tests/runbook | Real Docker/file/process checks, original PR failure reproduction, negative cases, source hashes and exact cleanup; updated old Flyway version assertion |

The runtime parent remains owned by root on repeat preparation; the service can
read its files but cannot replace path entries with symlinks. PostgreSQL's
upstream `gosu` path is separate from application `su-exec`/`setpriv` paths.
SQL V001–V049, Helm security contexts, frontend and business APIs are unchanged.

## Verification performed

### Isolated container suite

`backend/tests/test_chg301_compose_entrypoints.py`: **19 passed** on the final
candidate suite. The final rerun after making timeout-safe cleanup explicit also
passed19/19 in23.08seconds, journal `/private/tmp/chg301-ycwp02dm/journal.json`.
After the final Compose CMD correction and full-stack runs, it passed again:
**19/19 in23.15seconds**, `/private/tmp/chg301-sc_26s5r/journal.json`.
The latest test-closeout rerun also passed **19/19 in23.06seconds**,
`/private/tmp/chg301-ndkv4srv/journal.json`, with exact cleanup.
Real checks include:

1. UID10001 reads the exact private-copy bytes; source remains 0600/unchanged,
   destination0400, restricted directories, original umask and repeat preparation.
2. Ten negative cases: empty/symlink/missing source, traversal/outside reference,
   legacy root control, missing tmpfs, nonroot preparation, invalid service
   profile and invalid export variable all reject before the command succeeds.
3. The original PR wrapper, under its original `NOMOSMART_RUN_AS` contract,
   actually exits64 under UID10001. The candidate runs real Flyway13.6.0 under
   UID10001, cap-drop ALL, no-new-privileges and read-only rootfs.
4. All three candidate images contain the exact current helper bytes; Migration
   contains the exact checked-in SQL files. Selected unchanged Backend config,
   bootstrap, migration gate, worker and DB-session modules match the local source.
5. Real Backend Settings resolves private paths; command exit23 is preserved.
   This is not an HTTP Backend/Worker readiness test.
6. Real PostgreSQL18.4 initializes via its upstream entrypoint as postgres, runs
   all49 real Flyway migrations, reports V049/checksum `-1579162252`, restarts and
   preserves the test row and migration history. All writes target its new DB.
7. Real bootstrap checks reject missing history, wrong checksum and missing
   target; the migrated DB passes its read-only contract and missing bootstrap
   evidence is rejected. No successful bootstrap evidence was fabricated.
8. RustFSbeta10 starts as UID10001 using test TLS, passes CA-verified HTTPS health
   and handles stop without forced SIGKILL. Keycloak's real version command can
   read its 0600 test Secret through the current shared wrapper.

The application image was the existing CHG-300 image with identical inspected
application modules; the two new helpers were mounted read-only. It is not
reported as a newly built Backend image. Keycloak used its existing image with
the current shared helper mounted read-only, not a newly built Keycloak image.

Command (explicit opt-in, no conftest/live environment):

```sh
CHG301_ISOLATED=1 PYTHONPATH=backend APP_ENV=test backend/.venv/bin/python -m pytest -c /dev/null --rootdir=. --noconftest -p no:cacheprovider --tb=short -q -s backend/tests/test_chg301_compose_entrypoints.py
```

### Regression/configuration checks

- **30 passed**: `test_chg242_secret_packaging.py`,
  `test_chg231_deployment_initialization.py`,
  `test_chg229_full_stack_deployment.py` with the same isolated pytest options.
- **2 passed**: CHG-262's existing strong/distinct local-Helm password and
  Compose-rejection-of-Helm-only-flag tests. No Helm profile credential change.
- PASS: `spec:doctor`, `spec:trace`, `plan:doctor`, `plan:approved`, `test:plan`,
  `backend:syntax`, `docker:config`, `helm:lint`, `deploy:config-policy`, shell
  syntax and `git diff --check`.
- Docker config used `COMPOSE_DISABLE_ENV_FILE=1 COMPOSE_ENV_FILES=/dev/null`
  with the harness's `--no-env-resolution --quiet`; no operator env was resolved.
  Python syntax used a temporary pycache prefix, not application imports.
- Static configuration tests are not service readiness or live Kubernetes proof.

### Real Compose acceptance after the authorized OpenSearch download

Peter's subsequent `允許` authorized download of the exact checked-in
`opensearchproject/opensearch:2.19.1`; digest/image ID
`sha256:72fe2fc84be8295906b8efca020b46c58ed45c8da60cd9b8b49e1991e38e89a4`.
No substitution, registry push or live deployment occurred.

Runner: `backend/scripts/chg301_compose_acceptance.py`, explicit `CHG301_ISOLATED=1`.
It uses the actual Compose service commands/dependency chain and exact image IDs
with a fresh private package, internal-only network and no host ports. Only the
test copy replaces data volumes with capped tmpfs (6.75GiB); total service limits
are7CPU/10.75GiB RAM. This complements, not replaces, the earlier PG persistent
volume restart test. A custom package output intentionally does not generate the
operator env; the runner supplies a local test-plan URI and captured factory
terminal-log reference. These are not production alert/operational acceptance.

| Case | Result | Redacted journal |
| --- | --- | --- |
| Fresh startup and repeated up | PASS: six dependencies healthy,49 real migrations and bootstrap exit0; Backend/Worker/Beat healthy; Backend `/api/v1/ready`200 with current Worker heartbeat and migrated49/-1579162252; CA-verified OpenSearch admin and runtime service authentication; repeated up preserves IDs and original package bytes | `/private/tmp/chg301-compose-9d15v9it/journal.json` |
| Wrong Flyway credential | PASS: real PostgreSQL authentication fails, Flyway exits1; bootstrap/Backend/Worker/Beat remain Created; original package unchanged | `/private/tmp/chg301-compose-jxewr0za/journal.json` |
| Wrong expected V049 checksum | PASS: real49 migrations exit0, bootstrap exits1 with `database_migration_checksum_mismatch`; Backend/Worker/Beat remain Created; original package unchanged | `/private/tmp/chg301-compose-0s349cpg/journal.json` |

All three runs' exact cleanup passed, including original container-ID baseline equality.
The final test-closeout rerun passed all three scenarios again, exit0:

- startup: `/private/tmp/chg301-compose-tflf0yc9/journal.json`;
- migration-failure: `/private/tmp/chg301-compose-gnzhqkne/journal.json`;
- bootstrap-failure: `/private/tmp/chg301-compose-frku1iun/journal.json`.

All three latest journals record acceptance PASS and cleanup PASS, with no
existing container changes. These supersede the prior runs for final evidence.
Commands: runner with default `--scenario startup`, `--scenario migration-failure`
and `--scenario bootstrap-failure`, sequentially only. The30-test regression suite
passed again after the explicit PostgreSQL Compose CMD correction.

### Coverage: original failed gate (historical; superseded by R2 below)

The30-test regression run was separately measured with
`--cov=deploy/package --cov-branch --cov-fail-under=80`.

- Measured package-directory coverage: **49.16%**, required80%, command exit1.
- Modified `nomosmart_package.py`: approximately61% combined coverage.
- The directory measurement also includes the unchanged
  `generate_opensearch_tls.py`, unexecuted in that command. No exclusion was
  added to raise the number. Child-process execution is not automatically
  included in the parent coverage report.
- Full Backend/Frontend80% release evidence and broader E2E/security scans have
  not been regenerated. No previous release's waivers were reused.

### R2 package coverage closeout — Peter「請完成測試」

The previous49.16% blocker has been resolved by adding real tests and measuring
child Python processes, **not by reducing scope/thresholds or excluding files**.
Both `deploy/package` modules remain included. No product code was changed in
this continuation; package CLI/helper/Compose/SQL/application source remains as
bound above. New files:

- `backend/tests/test_chg301_package_boundaries.py`: real CLI/TTY, private-file
  and host-file validation, non-overwrite/lifecycle/finalization rejection,
  signed TLS SAN/key/EKU negatives, operator edge-certificate rotation, real
  OpenSSL/GnuPG CA encryption/decryption with public-key match and cleanup.
- `backend/tests/chg301_coverage.ini`: branch/subprocess measurement, same whole
  package and80% threshold. No exclusions.
- `backend/scripts/chg301_package_verify.py`: fixed-scope automated verification,
  fail on skips/failures/source drift/wrong coverage file set; each module and
  aggregate must pass lines, branches and combined coverage >=80%. Records
  source SHA-256 and machine-derived test results; removes test files/keyrings.
- CHG-242's actual missing-minikube/permission child tests preserve **only**
  coverage instrumentation variables alongside their isolated empty PATH.

Final command:

```sh
CHG301_ISOLATED=1 backend/.venv/bin/python backend/scripts/chg301_package_verify.py
```

**81 passed, zero skipped/failed; harness exit0.**

| Measured source | Lines | Branches | Combined |
| --- | --- | --- | --- |
| nomosmart_package.py | 85.15% | 80.13% | 84.06% |
| generate_opensearch_tls.py | 97.30% | 93.33% | 96.63% |
| Whole deploy/package | 87.69% | 82.26% | 86.56% |

Machine evidence: `/private/tmp/chg301-package-evidence-a7p778cl/result.json`
and sibling `coverage.json`. Source hashes were identical before/after the run.
The harness removes its raw JUnit/test fixture files (including generated test
Secrets); only private machine coverage/case summaries remain. GnuPG recipient
keyrings use their own temporary homes; their agents are stopped on teardown.

Earlier attempts are preserved: R2 had68PASS/2FAIL and67.64%; one test confused
public username metadata with secret values, corrected to check real primitive
Secrets; actual GnuPG agent IPC was denied by the sandbox, then the same bounded
test was rerun with execution permission. R3 had70PASS but79.84% failed coverage;
added real TTY/CLI/SAN/EKU/directory guards produced R4's81PASS/86.11%, then final
child-process measurement above86.56%. No failure was waived or skipped.
Reports: `/private/tmp/chg301-r2-coverage.json`, `chg301-r3-coverage.json`,
`chg301-r4-coverage.json` in the same directory.

The standard full-system `./HARNESS/harness.sh coverage:check` was also attempted:
TEST-002 guard PASS, then exit1 for **missing full Frontend coverage evidence**.
This focused report is not substituted into `frontend/coverage` or
`backend/coverage.json`; no full-suite manifest or deployment acceptance is forged.

## Original failures retained

| Iteration | Actual outcome / resolution |
| --- | --- |
| First host command | Collection failed without PYTHONPATH; rerun with explicit backend path, not an application fix |
| First regression | 29pass/1fail: old assertion expected Flyway13.0; corrected to the already approved13.6 pinned digest |
| First14-case runtime run | 12pass/2fail: PostgreSQL helper incorrectly required application drop tool; Backend test lacked import path |
| Subsequent runtime runs | 14pass/1fail, then15pass/1fail: synthetic encryption key did not meet the existing64-hex contract; test inputs corrected, no product validator relaxed |
| Corrected runtime | 17pass, then final19pass with image/source bindings and additional DB-gate checks |
| Coverage run | 30tests passed, but49.16% coverage gate failed; resolved by R2 real tests/subprocess measurement86.56%, original failure retained |
| Full Compose preflight | Missing standalone Redis tag; used the already-cached same7.4.2 version+digest, without downloading/substituting/retagging it |
| First Compose resource discovery | Runner incorrectly redacted internal Docker JSON, corrupting a label containing a factory password string; fixed redaction at output boundaries only; containers had not started, exact recovery cleanup passed |
| First full startup | Actual PostgreSQL exited64 because Compose entrypoint override removed image CMD; fixed with explicit Compose `command: [postgres]`; preserved failure `/private/tmp/chg301-compose-gp7hdjm9/journal.json` |
| Next startup | Test-only tmpfs parent0700 blocked upstream postgres after its privilege drop; parent changed to0755 like image/volume, PGDATA remains upstream-restricted; `/private/tmp/chg301-compose-gnfhorf6/journal.json` |
| Bootstrap missing test config | Actual `break_glass_evidence_missing`, downstream remained Created; supplied real local test-plan/log metadata, did not disable validation; `/private/tmp/chg301-compose-2wpbu5vy/journal.json` |

The two stalled migration retry loops after PostgreSQL failure were stopped only
by exact run-owned container ID to end the failed tests early; their exit137 is
not reported as a spontaneous migration bug. All these failed runs were cleaned.
Automatic execution review also twice failed due to review-service capacity;
no test ran on those attempts. The same requests were retried only after plan,
source/bounds and cleanup checks; there was no alternate execution route.

## Remaining work / stop conditions

1. OpenSearch prerequisite and actual admin/service password admission are now
   resolved/PASS on2.19.1. This is not a live Kubernetes deployment result.
2. Full Compose startup, repeated up, failed-migration dependency behavior and
   checksum-negative bootstrap dependency protection now PASS.
3. **CHG-301 package coverage80% now met**, including each module's lines/branches.
   Full application coverage is a separate still-unmet release-evidence gate.
4. Preflight missing-executable and permission errors are covered by genuine
   subprocesses, but the complete host/port/active-minikube matrix is not yet
   verified. Existing nonzero minikube status handling was not broadened here.
5. Complete live Kubernetes installation, full application coverage and security
   scans remain separate release gaps, outside this operation's live authority.

No PR push was performed during this testing request. Focused package coverage
now passes; broader release acceptance is incomplete. Before eventual push,
recheck remote main/PR SHAs and preserve any new
author changes; no force push or automatic merge.

## Isolation and cleanup

Each run records exact container IDs, private network ID, anonymous volume IDs,
image IDs and source hashes in a0700 temporary directory. Containers have1CPU,
512MiB–1GiB memory limits and bounded logs; tests run sequentially on an internal
network with no host ports, Docker socket or existing volumes. No current
container was stopped or changed. The complete container-ID baseline was equal
after exact cleanup, and the final label query returned no CHG-301 containers
or networks. Runtime test Secret files were removed by exact paths; redacted
journals and the separate test images are retained. Volume disk consumption was
not separately captured, so no measured disk-quota result is claimed.

Relevant redacted journals: `/private/tmp/chg301-ot0mt2mn/journal.json` (initial
runtime failures), `/private/tmp/chg301-2fo7u8y0/journal.json`,
`/private/tmp/chg301-2shmpn4a/journal.json`,
`/private/tmp/chg301-eh52yo6y/journal.json`,
`/private/tmp/chg301-upz53ahn/journal.json`,
`/private/tmp/chg301-_pt3duz7/journal.json` (19pass/source binding).
Historical coverage: `/private/tmp/chg301-package-final-coverage.json`.
Latest coverage: `/private/tmp/chg301-package-evidence-a7p778cl/coverage.json`.

## Final candidate/source binding

| Artifact | SHA-256 |
| --- | --- |
| migrations:chg301-test image | 7e065b8eea47d323a20543984db4b020da9b43caad7c082fdbd3425907ad7d19 |
| postgresql:chg301-test image | 0b3904c4ff039d23e2d0437b091107c708c6116e5616874ae0130b6da260a525 |
| rustfs:chg301-test image | e9ab1a1b9c8e47ff8481ff52611025c8d23a0eaaa643a29ec9020fa7bc761755 |
| shared entrypoint | 7f2689288c068e5c4619867e025d6e63b45c8df420377753aed22516bf14cce7 |
| Compose entrypoint | 236ed90a923b8d1770cd0abd765f01ef2f83369c02baedd3974ffe6f30894eb1 |
| docker-compose.yml | 8480e9ddc9902d1ab623c3a34d89ca0f11da14ec4f8f15479be30e96a5e03848 |
| full Compose acceptance runner | 0083bba9e9680d803223312ef03bddd111a14743cdd225ebe44031dc249ee465 |
| container test module | c8d259c1aa98e1c56af5242c669b9662465f601f9db64401e35787ab5ab953a1 |
| package CLI | c453e9e1e97aacf7c0fe728cebb8c80fb73a8ed8e6f9d0bf6652b4e686aaa0de |
| package coverage harness | 4bc5edb09f1c861148b247ea244214d6ce212130583a07c365db1c27f6fa6789 |
| package boundary tests | a1112c77239ca4b39cc7498bed8a58a0f550582f1f93d8076b1fce5dda7d2b25 |
| package coverage configuration | 3be55f101cfe87cab09814309952e3ebe892a5b6be88aba29c2af23e003d8168 |

These are local test artifacts, not release or deployment approvals. Final
governance checks and `git diff --check` passed after recording the partial status.

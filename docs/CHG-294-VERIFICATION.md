# CHG-294 Repository Verification — Partial, Scope Review Required

Date: 2026-09-10. Peter approved the original Gate 4 with
`Peter approves CHG-294 Frontend Security Dependency And Base Image Remediation`.
Requirements: SPECIFICATION.md 3.1 / 10.51, FESEC-001..004 and DEPSEC-002.

R1 follow-up (2026-09-10): Peter's subsequent `OK` confirms the additional scope
proposed at the end of this report and preparation of its revised plan. Current
R1 Gate 4 was then explicitly approved on 2026-09-10; execution evidence is in
`docs/CHG-294-R1-VERIFICATION.md`. The findings below remain the historical first-pass results, not R1
verification. See `docs/CHG-294-PLAN.md` and `DEVELOPMENT_PLAN.md` for current scope.

**Not complete and not deployable.** The bounded package/base edits are present,
but the complete dependency audit found additional security packages outside the
approved list, and the production build stopped on existing test-data type
errors. These trigger the approved stop-and-review condition. No additional
package upgrade, test repair, image build or deployment is authorized by this
report. No High/Critical finding or coverage threshold has been waived.

## Implemented scope

| File | Change / evidence |
| --- | --- |
| `frontend/package.json` | Exact Next and eslint-config-next 16.3.3; sharp override 0.35.4. React/React DOM 19.2.3 and all other overrides retained. |
| `frontend/package-lock.json` | npm-generated required closure, reviewed against the pre-change lock; 43 changed package entries including root and metadata-only changes. Clean isolated npm ci succeeds. |
| `frontend/Dockerfile` | Explicit common Node 24.20.0 / Alpine 3.24 base for deps, builder, prod-deps and runner; bounded openssl/libssl3/libcrypto3 3.5.8-r0 installation; existing non-root startup retained. This is source configuration, not an executed OS repair. |
| `frontend/tests/chg294SecurityDependencies.test.mjs` | Three direct static package/lock/native-variant/Dockerfile contract checks, 3 PASS. Not exploit or runtime proof. |
| `frontend/scripts/chg294-runtime-smoke.mjs` | Real installed sharp PNG/JPEG encode/resize/pixel-decode and benign AVIF encode/header parsing. Optional loopback Next optimizer checks are written but not executed. The AVIF result label was clarified to describe header parsing, not full pixel decoding. |
| Specification / plan / tests / trace | Original approval recorded; upstream AVIF bypass clarified; partial results, new findings and additional-scope discussion recorded. |

Lock closure: Next/env/SWC/eslint plugin 16.2.12 → 16.3.3; sharp and native
packages 0.35.3 → 0.35.4; sharp libvips packages 1.3.2 → 1.3.3; required
`@swc/helpers` 0.5.15 → 0.5.23; sharp-wasm32's required nested
`@emnapi/runtime` 1.11.3 added. Existing top-level emnapi 1.11.1 retains its
version/integrity and becomes dev-only. Next's postcss requirement changes to
8.5.23, already satisfied by the unchanged intentional override.

The first npm resolution also moved unrelated fastq 1.20.1 → 1.20.3. Its parent
range was unchanged, so the original exact entry and integrity were restored
before promoting the lock. A second clean npm ci succeeded. No broad npm update,
audit fix, new unrelated override or manually edited node_modules was used.

## Runtime and isolation

Temporary workspace: `/tmp/chg294-work.J6K7Mn` (macOS resolves it under
`/private/tmp`). Source copied without shared node_modules or .next; npm installed
the new lock there. Existing host tsconfig build-info was copied, so this is not
claimed as a fully cache-free TypeScript acceptance. The temporary harness copy
also omitted two required static resources; their failures are reported below.
Existing repository generated/dependency folders were not modified.

Host runtime: Node **24.18.0**, npm **11.16.0**, darwin/arm64,
Node OpenSSL **3.6.2**. Installed Next **16.3.3**, sharp **0.35.4**,
libvips **8.18.6**, libheif **1.23.2**. These are host-test observations, not the
future Node 24.20.0 linuxmusl-arm64 image or evidence that its crypto is fixed.

`npm ci` warned that fsevents 2.3.2 / 2.3.3 and unrs-resolver 1.12.2 install
scripts were not covered by allowScripts. No scripts were approved and no policy
was bypassed. Native smoke and lint nevertheless ran successfully; the warning
remains explicit for subsequent reproducibility review.

Read-only OCI manifest inspection resolved the same official base:

- Tag: `node:24.20.0-alpine3.24`.
- Index: `sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf`.
- arm64/v8 child: `sha256:d3724e44ee368606d753e0027eb8d2a94fc1f275e5d9e4620178a12edb655f5f`.

No image was built or pulled by this action. The actual three-package apk repair,
final-image linkage/SBOM and image vulnerabilities remain unverified pending
separate image approval. Old CHG-293 image scans remain unchanged evidence.

## Verification results

Commands below ran in the isolated workspace with Node 24 on PATH, unless noted.

| Command / scope | Result |
| --- | --- |
| `npm install --package-lock-only --ignore-scripts --no-audit --no-fund` | PASS; reviewed lock closure, then removed unrelated fastq drift. |
| `npm ci --no-audit --no-fund` | PASS twice, including after restoring fastq; script-policy warnings retained. |
| `npm ls next sharp eslint-config-next` | PASS; actual target versions installed. |
| `node --test tests/chg294SecurityDependencies.test.mjs` | Initially failed all three before edits; final static contracts 3/3 PASS. |
| `npm run lint` | PASS. |
| `node scripts/chg294-runtime-smoke.mjs --fixtures-dir=/tmp/chg294-work.J6K7Mn/frontend/public/__chg294-smoke` | PASS for actual host PNG/JPEG processing and benign AVIF encoding/header parsing; no HTTP option used. |
| `npm run build` | FAIL: Turbopack compilation completed; TypeScript checking failed in existing test files. No runnable production build accepted. |
| `NOMOSMART_HARNESS_ROOT_DIR=/tmp/chg294-work.J6K7Mn ./HARNESS/harness.sh test:frontend` | FAIL: policy scan passed, 147/149 contracts passed; two ENOENT failures in the incomplete temporary copy. Component/coverage phase did not run. |
| `npm audit --json` | FAIL: 0 Critical, 2 High and 4 Moderate package entries; details below. Not a container scan. |
| Actual Next optimizer HTTP / OIDC / CHG-293 browser/API regression | NOT RUN after stop condition; no disposable service or browser started. |
| Backend tests, complete E2E and separate 80% coverage | NOT RUN in this pass; original full-release gaps remain, no new coverage measurement. |
| Image-native smoke, container scan, SBOM, Helm dry-run/deployment | NOT RUN; outside this approval. |

Final repository governance checks after recording the pause: `spec:doctor`,
`spec:trace` (five active mappings), `plan:approved`, `test:plan` and
`git diff --check` PASS. These validate documentation and the original approval;
they do not approve the additional scope or turn feature/security failures green.

Build/type diagnostics were observed in:

- `frontend/tests/chg282MarkdownViewer.component.test.tsx`: layout test objects
  omit required nullable fields such as caption/confidence/bbox; related
  text/level variants do not match the current typed layout contract.
- `frontend/tests/chg285ChunkSelectionGroup.component.test.tsx`: incomplete
  paragraph layout objects and implicit `this` in an existing geometry stub.
- `frontend/tests/homeMetrics.component.test.tsx`: capabilities test data lacks
  required `can_manage_lifecycle`.

These files were not edited. Their existing source does not satisfy current
types; no controlled old/new build comparison has proved the upgrade introduced
the errors. Do not hide them with ignoreBuildErrors, weakened API types, broad
casts, test exclusion or lowered thresholds. Read-only inspection also found
CHG-285's existing getBoundingClientRect mock; it cannot count as TEST-002 real
layout verification. Replacing simulated geometry with actual browser evidence
belongs in the proposed test repair scope, not an unreviewed passing workaround.

The two contract ENOENTs referenced the temporary root `.gitignore` and
`deploy/keycloak/themes/nomosmart/login/login.ftl`. These are copy/setup failures,
not evidence of product failure. Restore the required existing static resources
when testing resumes; do not skip those tests. No rerun occurred after the stop.

AVIF clarification: installed Next 16.3.3 includes AVIF in BYPASS_TYPES, returning
upstream bytes before sharp optimization. T06 and the optional HTTP helper now
expect a byte-preserving unoptimized response for the local AVIF sample rather
than inventing a mandatory rejection. This path has been inspected, **not tested
over HTTP**. There is no new application fallback or upload restriction.

## Additional dependency findings — not fixed in this scope

The complete audit reported six affected package entries, not six independent
vulnerabilities. Classification below comes from the actual lock. No exploit
payload was run and no conclusion of live compromise is made.

| Installed package | Lock scope | Audit severity / advisory | Upstream repair for discussion |
| --- | --- | --- | --- |
| browserslist 4.28.2 | dev-only, via Babel tooling | High; GHSA-c83g-rgw3-j3cx and GHSA-73wf-gq98-2v4g | 4.28.7 |
| js-yaml 4.3.1 | dev-only, ESLint chain; pinned override | High; GHSA-2883-xcg3-v3hh | 4.3.2 |
| baseline-browser-mapping 2.10.38 | production/shared, including Next | Moderate; GHSA-w5vr-8v7q-w6rv | 2.11.0 |
| vitest 4.1.10 | dev-only | Moderate; GHSA-82fw-gwwq-j7x9 | 4.1.11 |
| @vitest/mocker 4.1.10 | dev-only | Moderate; same Vitest advisory | matched Vitest closure |
| @vitest/coverage-v8 4.1.10 | dev-only | Moderate; indirect Vitest propagation | matched 4.1.11 |

This is a transcription of the observed audit findings and lock classification;
the raw full npm JSON was returned in tool output, not saved as a raw audit file.
A subsequent approved scan should persist its original machine-readable report.
Dev-only does not waive the gate or eliminate CI exposure. The browserslist
cache advisory is Moderate in the maintainer notice but High in this npm audit;
the separate stats/prototype advisory is High in both. Both are retained, not
silently downgraded. The Moderate production/shared finding also remains open.

Primary sources checked on 2026-09-10:

- [Browserslist cache advisory](https://github.com/browserslist/browserslist/security/advisories/GHSA-c83g-rgw3-j3cx)
  and [stats advisory](https://github.com/browserslist/browserslist/security/advisories/GHSA-73wf-gq98-2v4g)
  identify 4.28.7 as repaired.
- [js-yaml maintainer advisory](https://github.com/nodeca/js-yaml/security/advisories/GHSA-2883-xcg3-v3hh)
  identifies the 4.x fix as 4.3.2.
- [baseline-browser-mapping 2.11.0 release](https://github.com/web-platform-dx/baseline-browser-mapping/releases/tag/v2.11.0)
  and [upstream repair](https://github.com/web-platform-dx/baseline-browser-mapping/pull/137)
  address invalid-input process termination.
- [Vitest maintainer advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9)
  identifies the stable 4.x fix as 4.1.11; the risk is development-server file
  reading with the stated reachability/authentication preconditions, not evidence
  of an exposed production app route.

## Protected source and operational boundaries

SHA-256 after the approved edits:

| File | SHA-256 |
| --- | --- |
| frontend/package.json | f54760401b282d08c0641679024416e402e82b84b3af5c41276e320da27c685a |
| frontend/package-lock.json | e00e09c6aa22f587679e7971760c637d0dcee3f8e273c8c5746f8065e93f4937 |
| frontend/Dockerfile | e19e8fac0d245b2c92bf7714bba6e4da308048f77c85a460df0e6494f4d71086 |

The pre-existing tracked CHG-293 backend/frontend diff, excluding those three
files, remains `c950d2c2eb59d5f253923d5bd6cd6d8bd33742eeb5f10ee13481875bc9d8c254`.
All seven separately fingerprinted untracked CHG-293 implementation/test files
also retain their pre-edit SHA-256 values. No unrelated user change was reset.

No Kubernetes query/write, Helm action, app-image build, Job, service container,
database/schema/realm creation, MAAS/identity/data/index mutation or Provider
call occurred. No Next server or browser session was started. Finished build/
test/install processes left the disposable workspace for reproducible resumption;
it has not been deleted. Only small benign generated samples were added there.
Public package/advisory/OCI metadata requests do not count as a Provider call.

## Original discussion — subsequently confirmed for R1 planning

Recommend adding the four bounded dependency repair groups above, their strictly
required lock closure, and the three identified existing test-file repairs to
CHG-294. Test repair must align explicit test data to the existing real contract
and replace fabricated geometry with real browser assertions, preserving coverage
and assertions. Fix the temporary test-resource copy list as part of setup.

Peter has now confirmed this discussion list; the revised plan is prepared but
**not approved for execution**. Do not execute additional upgrades or tests until
the R1 plan is approved. Product behavior, Backend/Migration,
current data, images, deployment and Provider boundaries remain unchanged.

After that review, rerun clean install/build, the complete audit and affected
real tests. Do not report security/coverage or deployment completion from the
partial native/static successes above.

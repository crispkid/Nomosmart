# CHG-294 R1 Repository Verification

Date: 2026-09-10 (Asia/Taipei). Authority:
`Peter approves CHG-294 R1 Additional Security Dependencies And Test Contract Remediation`.
Specification 3.1 / 10.51, FESEC-001..004 and DEPSEC-002. This report supersedes
the first-pass build/npm findings, not its preserved historical evidence.

**Bounded repository remediation and focused verification pass. Release is not
complete or authorized:** independent 80% coverage, full E2E and final-image
security remain open. No risk waiver, image build, Kubernetes action or Provider.

## Changes and dependency closure

| Area | R1 change |
| --- | --- |
| `frontend/package.json` / lock | browserslist 4.28.7, js-yaml 4.3.2, baseline-browser-mapping 2.11.0, vitest / coverage-v8 4.1.11 and matched @vitest packages. Next/eslint-config-next 16.3.3, sharp 0.35.4, React/ReactDOM 19.2.3 retained. |
| `frontend/tests/chg294SecurityDependencies.test.mjs` | Four static packaging/closure/base checks, including nested copies and integrity. These are not runtime or exploit tests. |
| `chg282MarkdownViewer.component.test.tsx` | Explicit required nullable layout block fields and page dimensions; unchanged production types and existing assertions. |
| `chg285ChunkSelectionGroup.component.test.tsx` | Same required input fields; remove fabricated DOMRect test only after real replacement passes. Existing structural/grouping/click/keyboard assertions remain. |
| `homeMetrics.component.test.tsx` | Supply required `can_manage_lifecycle` capability on existing Owner input, without changing expected metrics. |
| `chg294SelectionGeometry.browser.mjs`, `.fixture.tsx`, `.html` | Mandatory real Chrome component/CSS geometry test. Existing Vite serves the production renderers with explicit component inputs on ephemeral loopback. No API interception, DOMRect/ResizeObserver replacement, fabricated service or OCR response. |
| package test scripts | `test:geometry` is required by both `test` and `test:coverage`, before coverage measurement. Missing browser/isolation prerequisites fail rather than skip. Existing source-wide 80% thresholds unchanged. |
| `frontend/scripts/chg294-runtime-smoke.mjs` | Benign 64×48 samples; native PNG/JPEG resize/decode; actual Next allowed 32px HTTP optimization; AVIF byte-preserving bypass. Writes samples only to the disposable workspace. |
| Governance | Approval, results and gaps recorded in specification, changelog, development/test plans and traceability. No product behavior/API/schema/role change. |

R1 changes **16 semantic lock entries**, including root devDependencies:

- vitest and eight @vitest packages: 4.1.10 → 4.1.11.
- browserslist: 4.28.2 → 4.28.7; baseline-browser-mapping: 2.10.38 → 2.11.0;
  js-yaml: 4.3.1 → 4.3.2.
- Required browserslist data closure: caniuse-lite 1.0.30001799 → 1.0.30001810;
  electron-to-chromium 1.5.376 → 1.5.425; node-releases 2.0.48 → 2.0.55.
  New parent minimum ranges (^1.0.30001806 / ^1.5.393 / ^2.0.51) exclude the old versions.

Initial npm resolution also moved unrelated Vite/Rolldown/OXC/lightningcss and
other permitted-range packages. Their exact baseline entries/integrities were
restored before a second clean npm ci and lock promotion. Vite remains 8.1.4;
Rolldown remains 1.1.5. No broad npm update/audit fix or edited node_modules.
The existing Dockerfile source repair is unchanged in R1; OS repair is not yet executed.

## Verification results

Commands ran in `/tmp/chg294-r1.1AfKo7` (realpath `/private/tmp/...`), with
Node 24 on PATH; root documentation checks ran in the repository.

| Command / scope | Result |
| --- | --- |
| `npm ci --no-audit --no-fund`, twice around bounded lock review | PASS, 592 installed packages; no install-script policy override. |
| `npm ls next sharp vitest @vitest/coverage-v8 @vitest/mocker browserslist js-yaml baseline-browser-mapping vite --depth=5` | PASS, expected installed versions and no invalid dependency tree. |
| `npm audit --json`, `npm audit --omit=dev --json` | PASS, all severities zero. Complete raw reports: `CHG-294-R1-NPM-AUDIT-FULL.json` / `CHG-294-R1-NPM-AUDIT-PRODUCTION.json`. |
| `node --test tests/chg294SecurityDependencies.test.mjs` | 4/4 PASS. |
| `npm run build` with prior `.next` moved outside Frontend | PASS, fresh optimized build, TypeScript and all routes; no ignoreBuildErrors or copied tsbuildinfo. |
| `npm run lint`; `harness.sh i18n:ast` | PASS; four bilingual/static guard tests also pass. |
| `harness.sh test:frontend` | Live-only guard PASS; 150 contracts PASS; mandatory real geometry PASS; 20 files / 94 component tests PASS; overall command FAIL at unchanged 80% coverage threshold. |
| Real DB/OIDC CHG-293 pytest suite | 48 PASS, 1 existing Starlette/httpx deprecation warning. Actual PostgreSQL, Keycloak tokens/JWT and FastAPI; no Provider. |
| Native / real Next HTTP image smoke | PASS, PNG/JPEG decode and actual HTTP optimization, AVIF unchanged bytes/MIME/dimensions. |
| Real Chrome + production Next + Backend + Keycloak | Normal Editor login/callback/logout, scoped author history, read-only controls and reload/paging verified; detailed bounded scope below. Not the full E2E suite. |
| `harness.sh security:dependencies` | PASS: npm production and frozen Python requirements have no known vulnerabilities. |
| `harness.sh security:static` | PASS configured High-severity/High-confidence gate. Bandit scanned 42,466 lines; High 0; existing Low 61 / Medium 31 retained, not erased. |
| `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan` | PASS, five active mappings and explicit independent R1 approval. |
| `backend:syntax`, `docker:config`, `helm:lint`, `deploy:config-policy` | PASS; Compose no-env-resolution and local Helm lint only, not a cluster dry-run. |
| `harness.sh test:e2e` | BLOCKED/exit 1: generic Peter/John governance/publish suite lacks its complete E2E environment. It was not pointed at current data or adapted into a fake pass. |
| `harness.sh coverage:check` | FAIL/exit 1: no passing complete source-bound suite evidence; focused measurements do not satisfy this gate. |
| Application image / linuxmusl-arm64 smoke / image scan / SBOM / Helm | NOT RUN, requires separate authority. Old 4 Critical / 8 High image findings are not waived or claimed repaired in an image. |

Source-wide Frontend coverage: statements **11.45%**, branches **9.51%**,
functions **12.06%**, lines **12.64%**. Geometry evidence is not inserted into
Vitest coverage. Backend whole-app coverage from the focused 48-test run is
**27%**, with 18,626 statements / 5,182 branches; `coverage report --fail-under=80`
exits 2. This is not a full Backend suite result. Full independent coverage and
critical-flow/E2E completion remain owned by the project release workstream.

### Actual browser and image observations

Geometry runs through real production `CanonicalMarkdownSource`,
`DocumentLayoutViewer` and globals.css. DOMRange rectangles must be contained
within the overlay and the actual range bounding box must agree within **1.5 CSS
pixels**, with nonzero dimensions. Desktop 1280px produces 12 text rectangles;
375px produces 48. Actual internal scroll is 76px at desktop (its maximum),
85px narrow. Checks cover source/offset preservation, separate Chunks, a single
Original group over paragraph+list, page-local identity, non-contiguous exclusion
and real keyboard/click callbacks. No simulated browser geometry is used.

OIDC/browser uses only disposable Editor credentials and normal authorization-code
PKCE login. Project Chat shows three creators, others read-only with query,
feedback and export disabled. Its own conversation is honestly non-continuable
because this test has no active manifest. Document Chat shows Owner/Viewer/Editor
names; Owner has two stored turns, not four messages. Selecting Editor's own
stored conversation enables the input; no question is submitted. Reload restores
the real history, and Load More grows 50 → 55 rows. English switches to `lang=en`
and accurate read-only text; narrow viewport rendering was captured. The test
records are explicitly seeded historical records, **not generated LLM output**.
Absent document layout/index artifacts are shown honestly; these are not OCR,
retrieval-quality or end-to-end ingestion acceptance.

Invalid refresh token returns 401 `oidc_refresh_failed`; anonymous proxied
`auth/me` returns 401 `authentication_required` with no-store. Login/history
alone is not the full T07 nonce/expiry/revocation/session-security matrix.
Browser diagnostics include expected denied system-overview report 403 for this
Editor and a missing favicon 404, not an uncaught Markdown/React exception.
During the first read-only browser run, ChatRecords stayed at 118 with content
MD5 `bc68e7889e8a7caf1d277215881b75e8` across the later selection/reload/paging
checks; usage and models were both zero. This is a disposable-test preservation
check, not a current-environment inventory or hash.

Image runtime is **darwin/arm64 Node 24.18.0 / npm 11.16.0 / Node OpenSSL 3.6.2**,
Next 16.3.3, sharp 0.35.4, libvips 8.18.6, libheif 1.23.2.
This is not final Node 24.20.0 Alpine/musl evidence. Next PNG/JPEG HTTP output is
32×24; AVIF stays byte-identical 64×48 with image/avif. No exploit input, external
image fetch, unsafe fallback or configuration relaxation.

Evidence screenshots and `geometry.json` are under
`/tmp/chg294-r1.1AfKo7/output/playwright/chg294-r1/`; Chrome snapshots remain in
that workspace's `.playwright-cli/`. These temporary artifacts may be reclaimed;
the command/results and source hashes here remain the durable summary.

## Isolation, failures and boundaries

- Copied source excludes node_modules, .next, tsbuildinfo, prior browser/coverage
  and environment files. Root .gitignore, tracked Compose and Keycloak theme are
  present. Production/shared dependency and build directories were not changed.
- Setup mistake: an initial broad **temporary deploy copy** included ignored
  private/generated files. Filename-only inspection caught it before use;
  the exact owned temp deploy directory was removed and replaced with git-tracked
  deploy files only. No private values were read, printed or used; originals were
  untouched. Final filename check has no private env/generated Secret matches.
- Test containers are `chg294-r1-postgres-1afko7` and
  `chg294-r1-keycloak-1afko7`, label `nomosmart.change=CHG-294-R1`, reused existing
  service images only. PostgreSQL data is disposable tmpfs. The first internal
  network did not publish host ports; only these owned containers/network were
  recreated as an isolated test bridge with 127.0.0.1 ports 15493/18093.
  Backend/Next bind only 127.0.0.1:18094/13093. Unexercised integrations point
  at unused loopback with no Provider credentials; no worker is started.
- First geometry attempt requested 85px where maximum scroll was 76px. Corrected
  the test to assert min(requested, actual maximum) and nonzero scroll, retaining
  all real enclosure assertions. This was a test expectation, not a product fix.
- First fresh-build lint attempt inspected an archived build temporarily renamed
  inside Frontend; it failed on generated files. Moved that archive outside the
  Frontend tree and reran unchanged lint successfully, without exclusions.
- First image HTTP smoke used disallowed width 16 and generated public assets
  after server startup (400/404). Changed only bounded smoke inputs to allowed
  32px, generated 64px source before restarting the owned server, then passed.
- First logout attempt returned Keycloak `Invalid redirect uri`: the unchanged
  CHG-293 test setup enabled login redirects but omitted the post-logout URI.
  The bounded retest registers only `http://127.0.0.1:13093/login` in
  `post.logout.redirect.uris` on the exact new disposable `chg293-test` client
  using real Keycloak administration. No production identity, relaxed wildcard
  redirect or product-code workaround is involved; the original failure remains
  recorded. Retest PASS: normal UI logout returned to `/login`; screenshot
  `logout.png` records the actual login page. Successful token-refresh rotation
  and the complete nonce/expiry/revocation matrix remain unverified, not waived.
- Initial pipe-hosted fixture termination left its temporary schema/realm, and
  attempted reuse exposed its schema-owned pgcrypto extension. Both owned test
  containers were discarded/recreated to remove all such disposable state before
  retesting. Existing CHG-293 helpers and all current services remain unchanged.
- Final retest exited normally through its terminal: helper reported 118 stored
  ChatRecords, zero usage and zero models before dropping its own schema/realm.
  Both named Chrome sessions and loopback Backend/Next servers were closed.
  Verified remaining `chg293_%` schema count **0** and exact realm discovery
  **404**, then stopped the two `--rm` test containers and removed only network
  `chg294-r1-1afko7`. Final label-filtered container/network inventories are empty.
  Disposable records were discarded and can be regenerated by test setup; source
  and temporary screenshots/reports remain. No current application resource was removed.
- npm reports unapproved install-script warnings for fsevents 2.3.2/2.3.3 and
  unrs-resolver 1.12.2. No allowScripts bypass; actual install/build/native results
  are retained separately from the warning.
- Backend suite and browser helpers create only random disposable schemas/realms.
  No live V049, current role/member/identity, document/index/manifest, Provider,
  application image or Kubernetes operation occurred.

## Protected source and handoff

Existing CHG-293 tracked diff, excluding the approved package/Dockerfile and
three R1 test files, remains SHA-256
`c950d2c2eb59d5f253923d5bd6cd6d8bd33742eeb5f10ee13481875bc9d8c254`.
Seven existing untracked CHG-293 production/helper/test files retain their
recorded hashes. No CHG-293 behavior repair was mixed into this R1.

| File | SHA-256 |
| --- | --- |
| frontend/package.json | 76cf6331e73990bc2598aa5dd94728a1dfb58cdfb2c86cd37229be9debbfa404 |
| frontend/package-lock.json | 0c00961b9a9baa799788c85cb6fdeff573d34ca8605b685fcaad17671e9ac025 |
| frontend/Dockerfile (unchanged R1) | e19e8fac0d245b2c92bf7714bba6e4da308048f77c85a460df0e6494f4d71086 |
| chg282MarkdownViewer.component.test.tsx | 72c6a2894bae5a5dccd96d7b86ab6f9e6dd719ac0e80d4ce0a840cd4d95cfea1 |
| chg285ChunkSelectionGroup.component.test.tsx | 9141957f847659dcad826936db1320082c081501390496d142309a63505dd93f |
| homeMetrics.component.test.tsx | 2cd77ec121f8c97372762368c8f7b550d68011c4114fd741002cf72f4b3d06b3 |
| chg294SelectionGeometry.browser.mjs | f8b407cfaef8ad2b2e7cb772696070753e1f878be4947d487c83480464d6367f |
| chg294SelectionGeometry.fixture.tsx | 30831495f6ad527afccf886e7236e82442d87ba1f6460be98c460c8538460d11 |
| chg294-runtime-smoke.mjs | a6970100a7b7ff19086609aa272dd86e249dda33038b4ccd076858e4920e1449 |

Next stage, only if independently authorized: build the bounded new Frontend
candidate; verify real arm64-musl crypto/native runtime, scanner findings and SBOM
before any fresh release-baseline/dry-run work. It does not waive coverage/E2E,
authorize Helm writes, or permit reuse of an old image/render binding.

### Reproduction notes

From a fresh verified `/tmp/chg294-r1.<suffix>/frontend` copy, install the exact
lock, then run `npm run test:coverage` (contracts → mandatory browser geometry →
Vitest, currently failing only its global coverage gate). Run `npm run build`
without a prior .next or tsbuildinfo; place any archived build outside Frontend
so lint does not scan generated code. Copy only tracked deployment resources,
root `.gitignore` and `docker-compose.yml`; never copy ignored operator settings.

For native/HTTP smoke, generate benign samples **before** `next start`:
`node scripts/chg294-runtime-smoke.mjs --fixtures-dir=/tmp/chg294-r1.<suffix>/frontend/public/__chg294-smoke`;
then repeat with `--next-origin=http://127.0.0.1:13093`. Do not override Next image
configuration to accommodate an invalid smoke request.

Backend focused command uses the unchanged CHG-293 fixture's four explicit test
environment variables (`CHG293_DATABASE_URL`, `CHG293_KEYCLOAK_URL`,
`CHG293_KEYCLOAK_ADMIN`, `CHG293_KEYCLOAK_PASSWORD`) against the disposable services:
`python -m coverage run --branch --source=app -m pytest -c /dev/null -p no:cacheprovider --tb=short -q tests/test_chg293_project_content_and_chat_history.py`.
The real browser fixture is `backend/scripts/chg293_browser_fixture.py`, run in a
terminal and stopped with Ctrl-C. Set only its exact disposable client logout URI
as described above; never modify the historical helper or current realm for this test.

# CHG-294 R2 — Repository and Isolated Runtime Verification

Started 2026-09-10; verification/cleanup completed 2026-09-11 (Asia/Taipei). Authority:
`Peter approves CHG-294 R2 Bundled Node OpenSSL Remediation`.
Specification 10.51 FESEC-001..004, DEPSEC-002; tests T01..T20.

**Repository repair and focused host/isolated checks are implemented. This is not
release completion, a built R2 application image, or deployment acceptance.**
Full independent 80% coverage, full E2E/session matrix, final linux-arm64-musl
crypto/native checks and new image scans/SBOM remain open. No risk waiver.

Subsequent image-stage update (2026-09-11, separately approved): see
[R2 image preparation](CHG-294-R2-IMAGE-PREPARATION.md). New image now exists and
Scout/SBOM pass; actual diagnostic confirms bundled OpenSSL 3.5.8. Its complete
functional smoke fails at the network-isolation interface guard before Next/native
work. This report's original host-stage results below remain historical; no
coverage/E2E waiver or deployment follows from the new image result.

## Root cause and change

The retained chg294 application image has system crypto 3.5.8-r0 but Node 24.20.0
reports bundled OpenSSL 3.5.7 and does not dynamically link system libssl/crypto.
Upgrading apk packages alone therefore does not repair Node's bundled library.
The old scanner-zero result remains historical, not proof of that repair or of
the reachability of each upstream vulnerability.

| Changed area | R2 delta only |
| --- | --- |
| `frontend/Dockerfile` | Common base becomes exact official Node 24.21.0 Alpine 3.24 index digest. Preserve four consuming stages, crypto pins 3.5.8-r0, UID 10001, runtime/start/config. |
| `frontend/tests/chg294SecurityDependencies.test.mjs` | Update exact base contract; retain all four tests and existing package/integrity/native/no-broad-upgrade assertions. |
| `frontend/scripts/chg294-image-smoke.mjs` | New reusable fail-closed actual-image helper: no unknown options, explicit R2 scope, linux/arm64/musl, uid 10001, read-only root, network none, named tmpfs only, Node 24.21.0 and **bundled 3.5.8**, independent system crypto/linkage, locked packages and real native/Next image smoke. No application route/entrypoint changes. |
| `frontend/scripts/chg294-runtime-smoke.mjs` | Add R2 disposable-path allowance only; existing benign native/HTTP assertions unchanged. |
| `frontend/tests/chg294SelectionGeometry.browser.mjs` | Add bounded R2 workspace/output path only; real geometry tolerance and production components unchanged. |
| Specification/plan/tests/trace and this report | Approval, provenance, results, limitations and separate build/deploy authority. |

No R2 package.json/lock mutation; no Backend, Migration, product UI/i18n, API,
permission, data schema or current application-data change. Existing dirty CHG-293
and CHG-294/R1 edits are preserved, not reset or relabeled as new R2 work.

## Provenance and independent runtime layers

The [official Node 24.21.0 release](https://nodejs.org/en/blog/release/v24.21.0)
lists OpenSSL 3.5.8 and inherent runtime changes including Undici and CA roots.
The [official Docker source](https://github.com/nodejs/docker-node/blob/93a7bafc324a85ac1ee461604cff87cffacb6d7a/24/alpine3.24/Dockerfile)
is the source commit returned by the actual manifest inspection. Its arm64 path
builds Node from source upstream; this work does not introduce a custom Node build.

Read-only command:
`docker buildx imagetools inspect docker.io/library/node:24.21.0-alpine3.24`.
No application-image pull/build/run occurred.

| Artifact | Verified value |
| --- | --- |
| Official index / pinned base | `sha256:be80f76cf40ec8e42b9bec49f60a55e0660f30af58d3e5a25530785b30ea67e2` |
| linux/arm64/v8 platform manifest | `sha256:c90fbae51ca047f2fda9ea92fb85eb936c08e6df18df7462bb782bad7c6afa3d` |
| Source commit | `93a7bafc324a85ac1ee461604cff87cffacb6d7a` |
| Source Dockerfile SHA-256 | `13d963885341e2bacab8c72cca9b314152d44747e03d88855e8ce06f8a99fe68` |
| Official darwin-arm64 archive SHA-256 | `bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057` |
| Clearsigned SHASUMS256.txt.asc SHA-256 | `dd0fe71660e64f4dc01342664835509c84679d8a87ab4d76cc2f15fdda82ea3e` |
| Verified release signing fingerprint | `5BE8A3F6C8A5C01D106C0AD820B1A390B168D356` |
| Executed host runtime | darwin/arm64 Node **24.21.0**, npm **11.19.0**, bundled OpenSSL **3.5.8**, bundled Undici **7.29.1** |
| Bundled TLS roots | 121; SHA-256 of newline-joined roots `8403bc9ed3ae3e71b4af96a4d37c23999d7ba8c2fc9411fc6d6feb5e7ee8c4f7` |
| Installed app/native runtime | Next 16.3.3, sharp 0.35.4, libvips 8.18.6, libheif 1.23.2 |

Archive and clearsigned checksums came from the
[official release directory](https://nodejs.org/dist/v24.21.0/); the signing key
was matched to the [official release key repository](https://github.com/nodejs/release-keys).
GPG verified in a new private temp keyring. Its normal web-of-trust warning is
retained: this was explicit official fingerprint verification, not an assertion
of a locally certified key. Because the .asc is clearsigned, its signed payload
was separately decoded and its exact archive checksum compared with actual bytes
**before** archive extraction/execution; standalone plaintext checksums were not
mistaken for a verified detached signature.

Host default Node 25.9.0 was not used as R2 runtime evidence. Every npm/build/test
command used the extracted official 24.21.0 binary on a task-local PATH. Its
bundled Undici 7.29.1 is distinct from the unchanged application override 7.29.0.
Actual Alpine apk revisions, ldd and application-image runtime are still unrun;
future build must stop on an unexpected crypto pin downgrade/closure.

## Commands and outcomes

Fresh workspace: `/tmp/chg294-r2.5S694K` (realpath `/private/tmp/...`). Source was
copied using git's tracked/nonignored file list, excluding private environment
files, shared dependencies/builds and prior test state. Root documents and only
safe tracked deployment resources were added explicitly. No ignored operator
settings or current service credentials were copied or used.

| Command / test | Result |
| --- | --- |
| `npm ci --no-audit --no-fund --cache=<R2 temp cache>` | PASS; 592 installed packages; unchanged package and lock hashes. No install-script policy bypass. |
| `npm audit --json`; `npm audit --omit=dev --json` | PASS; all severities zero in both. Complete JSON command outputs are retained in `CHG-294-R2-NPM-AUDITS.json`. |
| `npm run build` | PASS, fresh Next/TypeScript production build and routes. |
| `npm run lint`; harness `i18n:ast` | PASS; four bilingual guard tests. |
| harness `test:frontend` / `npm run test:coverage` | 150 contracts PASS, real Chrome geometry PASS, 20 files / 94 component tests PASS; overall **FAIL** at unchanged global 80% threshold. |
| Real DB/OIDC CHG-293 pytest suite under branch coverage | **48 PASS**; existing Starlette/httpx deprecation warning retained. |
| `coverage report --fail-under=80` | **FAIL**, exit 2, focused whole-app Backend 30%; not the full suite. |
| Host `chg294-runtime-smoke.mjs`, then `--next-origin=http://127.0.0.1:13093` | PASS: real native PNG/JPEG encode/resize/decode and real Next HTTP optimization; AVIF is original bytes, MIME and 64×48 dimensions. |
| Temp `tls-smoke.mjs` on actual Node 24.21.0 | PASS, local TLS 1.2/1.3 trusted handshakes and untrusted-cert rejection; default-trust HTTPS to official Node 200. No disabled TLS validation. |
| Temp `auth-smoke.mjs` on actual Next/Backend/Keycloak | PASS after explicit setup restoration correction: authenticated proxy and positive refresh 200; missing refresh 400, invalid refresh 401, anonymous proxy 401, unbound state 400, genuine expired signed JWT 401. Exact observed token lifetime restored to 300s. |
| `node --check scripts/chg294-image-smoke.mjs`; actual host rejection probes | PASS syntax; missing scope, unknown options and host-as-image invocation all exit 1 before test writes/network. **Not an actual image pass.** |
| harness `security:dependencies` | PASS after one PyPI connectivity retry; npm production and frozen Python requirements have no known vulnerabilities. |
| harness `security:static` | PASS configured High-severity/High-confidence gate: 42,466 lines; High 0, existing Low 61 / Medium 31 retained. |
| harness `docker:config`, `helm:lint`, `deploy:config-policy` | PASS; local Compose no-env-resolution and Helm lint only, not cluster dry-runs. |
| harness `spec:doctor`, `spec:trace`, `plan:doctor`, `plan:approved`, `test:plan`, `backend:syntax`; `git diff --check` | PASS; five active mappings and explicit R2 approvals, no gate relaxation. |
| harness `test:e2e` | **BLOCKED / exit 1**, missing complete Peter/John governance/publish E2E environment; no current services or fake adapter substituted. |
| harness `coverage:check` | **FAIL / exit 1**, no successful complete source-bound suite evidence. |
| R2 application image / actual linux-musl crypto / scan / SBOM / Kubernetes | **NOT RUN**, independent approval required. Existing chg294 candidate and reports preserved. |

Frontend coverage: statements **11.45%** (897/7,834), branches **9.51%**
(744/7,820), functions **12.06%** (276/2,288), lines **12.64%** (766/6,057).
The existing API-route exclusion was not changed; runtime API checks are separate
evidence, not inserted into coverage. Backend focused measurement: 19,591
statements / 5,182 branches, **30%** overall; no claim of improved full-suite
coverage compared with differently scoped R1 measurements.

Actual geometry at 1280/375px retained 1.5 CSS-pixel tolerance, 12/48 text
rectangles, internal scroll 76/85px, one group for paragraph+list, exact offsets,
separate Chunks, cross-page identity, noncontiguous safety, keyboard/click.
No DOMRect/ResizeObserver/service replacement or static mock pass.

### Browser retest on the new Node runtime

Playwright CLI used a new named Chrome session, actual production Next, actual
FastAPI and the disposable Keycloak realm. After verified lifetime restoration,
normal authorization-code/PKCE login and silent reload succeeded. Both projects
loaded as Editor; upload/content controls were available while project governance
controls remained absent. No content or permission change was submitted.

Project Chat displayed Owner/Editor/Viewer names. Other creators were read-only
with query/feedback/export disabled; the Editor's own published conversation was
honestly non-continuable because this test has no active manifest. Document Chat
showed Owner's two stored turns, not four messages. Real browser assertions
confirmed other history remains read-only after reload, the Editor's own input
is enabled, and actual pagination grows 50 to 55 stored conversations. No question,
feedback, deletion, upload or export was submitted. Normal UI logout returned
to `/login` and removed the actor from the app shell. Session names were
`chg294-r2` (failed setup, closed) and `chg294-r2-retest` (passed, closed).

These are deliberately seeded historical records, not generated answers or
retrieval/index/Provider acceptance. Images and geometry evidence remain under
`/tmp/chg294-r2.5S694K/output/playwright/chg294-r2/`. Full negative nonce,
refresh-replay/revocation, automatic browser-expiry matrix and generic E2E are
not claimed complete. Two CLI assertion attempts first failed parsing because
the installed CLI requires an `async (page) => { ... }` function; corrected
same-scope assertions then executed and passed, with no product/test expectation
changes or fake responses.

## Isolation incidents and honest retests

- Initial expected service image names were not installed. Metadata lookup
  resolved existing `postgres:17.10-bookworm` and `nomosmart/keycloak:26.0.8`;
  `--pull=never` reused those images only for fresh labelled R2 test services.
- Bandit initially could not write the shared uv cache under sandbox policy.
  It then used a dedicated R2 temp cache and completed. Initial pip-audit package
  download failed with PyPI host unreachable; one same-scope retry completed.
  No failed attempt was silently labeled PASS.
- A browser navigation permission review timed out; its one permitted identical
  scoped retry completed. A stale UI reference failed and was replaced by a fresh
  snapshot/navigation, not guessed controls.
- The first expiry setup used a 3-second disposable client token lifetime.
  Keycloak retained the omitted attribute on PUT; an initial assumed restoration
  was therefore wrong. Fresh-token inspection proved `expires_in=3`. This caused
  repeated refreshes/aborted project requests and repeated denied homepage report
  requests in that **isolated test**. That browser was closed. The helper now
  explicitly restores the realm's actual inherited 300s lifetime, reads the client
  back and asserts a newly issued token has `expires_in=300`. Fresh-browser retest
  then loaded both projects normally. No product/permission code was modified to
  hide this setup failure; this is not evidence of a new deployed homepage bug.
- npm's unapproved-script warnings for fsevents and unrs-resolver remain visible;
  no allowScripts override, npm update or audit fix was used.

## Preservation, open gates and next stage

Cleanup completed on 2026-09-11: stopped only this run's loopback Next and Backend
processes. The unchanged fixture exited normally, reporting 118 stored test
ChatRecords, zero usage events and zero models before dropping its own schema
and realm. Verified remaining `chg293_%` schema count 0 and exact realm discovery
404. Then stopped/removal via `--rm` only
`chg294-r2-postgres-5s694k` and `chg294-r2-keycloak-5s694k`, after verifying
`nomosmart.change=CHG-294-R2`, no host application mounts and owned network
membership. Removed only network `chg294-r2-5s694k`; label-filtered container and
network inventories are empty. PostgreSQL data was tmpfs; Keycloak data only in
the disposable container. Test records can be regenerated. Temporary source,
reports and screenshots are retained; no existing PVC/volume/image was removed.
The ephemeral TLS private key was removed after its tests; no key was committed.

Old candidate `nomosmart/frontend:0.1.0-chg294` remains exactly
`sha256:5281abacf6c0ba6fc07c757325aebf9ba9b964ca2eb8ce4f68bd664c36683655`.
All seven protected CHG-293 untracked source/helper/test hashes match the R1
baseline; no changes were made to those helpers to accommodate R2 testing.

| File / protected content | SHA-256 |
| --- | --- |
| `frontend/package.json` unchanged | `76cf6331e73990bc2598aa5dd94728a1dfb58cdfb2c86cd37229be9debbfa404` |
| `frontend/package-lock.json` unchanged | `0c00961b9a9baa799788c85cb6fdeff573d34ca8605b685fcaad17671e9ac025` |
| R2 Dockerfile | `3b5e7c827f4bdc9f28e9088002e61d50615270792a300ff33aeb0a18b53157bf` |
| R2 image helper | `3277cb5595235d3e9bd92b973b88d61d8b831f37e64ff6de191aea8668eb797a` |
| R2 host helper | `eb183d6e83631a2b114b75a92724c695cf4e8e53c178cf2fd5b81a2f23c6cf0a` |
| R2 static test | `1da7c4b6241256325cc46dcf479782e495780d41fa6007b27e9bf7b6877189be` |
| R2 geometry runner | `7c211029b18316d0a0ad9ba4c65b81634bf826e67f642939075d5becd4cd66be` |
| Product/chart file-list fingerprint unchanged | `578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79` |

Fingerprint command: sorted `rg --files --hidden frontend/src frontend/public
backend/app deploy/helm/nomosmart`, excluding pycache/pyc, each file SHA-256 then
SHA-256 of the listing. Neither shared node_modules/.next nor current data changed.

Next independent Stage A can build a **new** `nomosmart/frontend:0.1.0-chg294-r2`
candidate, not overwrite chg294. It must run actual strict crypto/native smoke,
scan and SBOM; this host report cannot replace those checks. Before deployment,
full coverage/full E2E and full critical-flow gates still require completion, or
any allowed risk disposition must be explicit rather than inferred. Kubernetes
baseline/dry-run/exact Stage B binding remains separate. No live V049, current role/group/member
mutation, graph repair, document reprocess, re-embedding/reindex, manifest switch
or Provider/billing calls were performed.

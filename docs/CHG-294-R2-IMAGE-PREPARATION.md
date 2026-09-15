# CHG-294 R2 — Frontend Image Preparation

Date: 2026-09-11. Status: image built; scans/SBOM pass; actual functional smoke
blocked by its network-isolation guard. **Historical first-run result below.**

Subsequent separately approved correction:
[isolation verification](CHG-294-R2-ISOLATION-VERIFICATION.md). Four real negative
cases and full positive crypto/native/Next smoke now pass on this unchanged image.
Coverage/full E2E still prevent conditional deployment; no cluster action occurred.
The original failure/evidence below is preserved, not retroactively changed.

## Authority and boundaries

Peter replied `核准` directly to the next-step proposal for new Frontend image
build, actual container verification and security scanning. Follow the existing
approved R2 plan, SPECIFICATION.md 10.51 FESEC-001..004 / DEPSEC-002 and
TEST_PLAN.md T17..T20 without behavior or threshold changes.

1. Read-only check Docker Desktop context and old/new candidate identities;
   confirm exact source/package hashes. Stop on unexplained drift or existing tag.
2. Pull only the exact verified official Node 24.21.0 Alpine 3.24 base; inspect
   linux-arm64 runtime/system crypto in a labelled read-only network-none disposable
   container. Stop if fixed package pins would downgrade newer crypto.
3. Build only `nomosmart/frontend:0.1.0-chg294-r2`, linux/arm64, from a fresh
   Git-tracked/nonignored Frontend copy excluding operator settings, shared
   dependencies/builds and prior test state. Do not overwrite chg294 or push.
4. Run the approved fail-closed helper against the exact image ID: UID 10001,
   no network/host ports, read-only root, dropped capabilities, only named tmpfs,
   no live config/data mounts. Require bundled OpenSSL 3.5.8 independently of
   system crypto 3.5.8-r0, package hashes, ldd/musl and actual native/Next images.
5. Scan only this Frontend candidate using existing Docker Scout: High/Critical
   gate plus all-severity report and SPDX SBOM, preserving exact IDs and report
   hashes. No VEX/suppression or new registry login. Do not invoke the harness
   command that rebuilds both application images; use equivalent Frontend-only
   scanner commands rather than expanding authority to Backend/Migration.
6. Record results and clean only this stage's labelled temporary containers.

Not authorized: Kubernetes query/dry-run/write, Helm action/Jobs/bootstrap,
Backend/Migration rebuild, current application or identity data, roles/groups,
V049, graph repair, reprocess/re-embed/reindex, manifest switch or Provider/billing.
Full independent 80% coverage, full E2E/session matrix and any later fresh-bound
deployment approval remain open. A successful image is not release completion.

## Preflight

Context `desktop-linux` uses the local Docker Desktop socket. New R2 tag does not
exist. Old chg294 remains
`sha256:5281abacf6c0ba6fc07c757325aebf9ba9b964ca2eb8ce4f68bd664c36683655`.
Docker Scout is v1.24.0. Isolated artifact directory:
`/tmp/chg294-r2-image.86XvU9`.

Package, lock, Dockerfile and smoke helper SHA-256 exactly match the completed
repository verification. Product/chart fingerprint is still
`578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79`.
No application code/config changes are planned during this stage.

## Results

| Check | Result |
| --- | --- |
| Exact official base pull and read-only linux/arm64 inventory | PASS: Node 24.21.0, bundled OpenSSL 3.5.8, musl. Full `apk info -v` shows base libssl3/libcrypto3 3.5.7-r0, not a newer version; approved installation upgrades these to 3.5.8-r0 and adds openssl 3.5.8-r0. No downgrade. |
| Fresh secret-excluding Frontend build context | PASS: 158 tracked/nonignored files, 4.4 MiB; only `.env.example`, no operator settings/shared node_modules/.next. Package/lock/Dockerfile/helper hashes match. |
| `docker --context desktop-linux build --platform linux/arm64 --progress=plain --iidfile /tmp/chg294-r2-image.86XvU9/frontend.iid -t nomosmart/frontend:0.1.0-chg294-r2 /tmp/chg294-r2-image.86XvU9/source/frontend` | PASS, exit 0. Fresh npm installs and Next 16.3.3/TypeScript production build; no push or old-tag overwrite. |
| Exact-image fail-closed smoke helper via stdin | **FAIL**, exit 1 at network interface guard, before package/crypto assertions, test writes, native image work or Next startup. No final-image functional pass claimed. |
| Separate read-only network/runtime diagnostic | PASS as diagnostic only: Docker network `none`, UID 10001, read-only root, all capabilities dropped, no-new-privileges, no IP/gateway/published ports. All nine non-loopback interfaces are administratively down; no IPv4 route; IPv6 routes only on lo. |
| Separate actual-image crypto/linkage observation | Node **24.21.0**, bundled OpenSSL **3.5.8**, system openssl/libssl3/libcrypto3 **3.5.8-r0**, musl/arm64; no dynamic system libssl/libcrypto linkage. This confirms the targeted library version independently, not completion of the failed smoke. |
| Frontend-only Scout High/Critical gate | PASS, exit 0, SARIF results 0. |
| Frontend-only Scout all-severity report | PASS, exit 0, SARIF results 0. No suppression/VEX waiver. |
| SPDX SBOM | PASS, SPDX-2.3; Scout indexes 350 packages, JSON has 351 including container document root. Exact R2 image purl present. Node 24.21.0 and system crypto 3.5.8-r0 are listed; bundled OpenSSL is not a separate package, so diagnostic runtime evidence remains necessary. |
| Post-run preservation and cleanup | PASS: old/new tags retained, all protected source hashes unchanged, stage-labelled container inventory empty. Only two stopped diagnostic containers removed, with no application/data mounts. |

Build npm reports zero known vulnerabilities for 591 development/181 production
audited packages. Platform-specific optional dependencies explain the difference
from prior darwin counts; lock bytes are unchanged. Existing npm warning for the
unapproved `unrs-resolver` postinstall is retained; no script grant, policy bypass
or npm-major update was performed. This did not fail installation or build.

## Exact artifact identities

| Artifact | SHA-256 |
| --- | --- |
| New image / OCI index | `2c65c3eab7f7601612297a6c1ec11f8445ac0b2c174c18f4076cf98c2a70eb9d` |
| linux-arm64 manifest | `a315c612e79edb4423fe694c288778e3d1664db790518c8f2c69ea82de68c4fa` |
| Image config | `4918560774440d178266a6d7f86eed509bca572b585c14613111234cd805562b` |
| Build attestation manifest | `118852c1fdea2142da0dd9251ed936207e4006246d67b1e99d7a01ec88a1783d` |
| Build log | `d4b7ebdb33bf9c650258fd2dddac19fd7ce31ab39b7d5b03e740ecca5380aa93` |
| High/Critical SARIF | `d5792a5052fb157aaf686dec92fd7a5a2d83f524c846c9c4032fc13e820a44df` |
| All-severity SARIF | `d5792a5052fb157aaf686dec92fd7a5a2d83f524c846c9c4032fc13e820a44df` |
| SPDX JSON | `0bda048055641813c1489a3ac92911b5db56dd2b88d3448d6dffeb7250564c0a` |
| Docker diagnostic configuration JSON | `3c7300c102c90be7a7fdac8692174fdd890affe83d1149a83a9578b30f7854f2` |
| Actual runtime/network diagnostic JSON | `ec35f42596be252be25895ea12e8646ad0d49d7eae719bdc44cc5a4ef60e8cef` |

Raw artifacts remain under `/tmp/chg294-r2-image.86XvU9`; scanner artifacts are in
its `security/` directory. Machine-readable summary:
`docs/CHG-294-R2-IMAGE-EVIDENCE.json`. Old chg294 image and reports remain intact.

Scanner commands used the exact `local://sha256:2c65c3eab7f7601612297a6c1ec11f8445ac0b2c174c18f4076cf98c2a70eb9d`
with `docker --context desktop-linux scout cves --exit-code --only-severity
critical,high --format sarif --output ...`, another `cves --format sarif --output
...` without the severity filter, and `sbom --format spdx --output ...`.
These are the Frontend-only equivalents of harness `security:containers` /
`security:sbom`, not a claim that the two-service harness ran this turn.

## Functional smoke blocker and safe next scope

The unchanged helper at `frontend/scripts/chg294-image-smoke.mjs:27` equates
network isolation with an interface-name array containing exactly `["lo"]`.
Docker Desktop's current network namespace also exposes `tunl0`, `gre0`,
`gretap0`, `erspan0`, `ip_vti0`, `ip6_vti0`, `sit0`, `ip6tnl0`, `ip6gre0`.
The read-only diagnostic found each extra interface `operstate=down`, with no
IFF_UP flag. Docker confirms `NetworkMode=none`, no addresses/gateway/ports;
there is no non-loopback route. The exact-name assertion is incompatible with
these inactive kernel interfaces. It is not evidence of a product startup failure
or proof that this container had external connectivity.

The helper was not edited, removed, bypassed or run on a different network.
No kernel/module/interface configuration, NET_ADMIN capability or container
privilege was added. The empty `smoke.json` is **not** a successful result;
stderr assertion and exit 1 are recorded in the machine-readable summary.

Two diagnostic setup attempts are not counted as passes: the first auto-removed
after 45 seconds before inspection; the second tried treating sysfs
`bonding_masters` as an interface and failed ENOTDIR. The final read-only probe
enumerated `/proc/net/dev`, captured Docker configuration and completed exit 0.
The initial base `apk info -v <name>` probe did not reliably list installed
versions; full `apk info -v` corrected that observation before build.

Recommended follow-up, **not implemented or approved by this stage**: change only
the verification helper to check actual isolation (all non-loopback interfaces
down, no non-loopback route, Docker network-none metadata bound to the run),
retain fail-closed negative tests and all crypto/native assertions, then rerun
the complete smoke against this same image ID. No product behavior/dependency
change is indicated by the current evidence. Request human confirmation before
changing the protected helper/hash contract.

Coverage remains below the independent 80% release gates; full E2E/session matrix
remains incomplete as documented in R2 repository verification. No Kubernetes
query/dry-run/write, Helm operation, Backend/Migration build, data/identity
mutation, Provider call or release waiver occurred. **No render SHA was produced.**

Final documentation checks: `./HARNESS/harness.sh spec:doctor`, `spec:trace`
(five mappings), `plan:approved`, `test:plan`, and `git diff --check` all pass.
An independent JSON/hash check confirms all six raw artifact digests in the
machine-readable evidence, while asserting the smoke exit remains 1 and deployed
remains false. SPECIFICATION.md 10.51 is unchanged in this image-only stage.

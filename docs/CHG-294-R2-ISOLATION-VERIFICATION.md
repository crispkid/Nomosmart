# CHG-294 R2 — Corrected isolation verification and deployment gate

Date: 2026-09-11 (Asia/Taipei). Peter approved:
`核准，如果驗證沒問題，請幫我部署更新`.

**Helper correction and exact-image functional verification PASS. Deployment is
not performed because the complete coverage and E2E release conditions remain
unsatisfied.** Conditional deployment approval is recorded, not treated as a
waiver. No Kubernetes query/dry-run/write or Helm action occurred.

## Scoped implementation

SPECIFICATION.md 10.51 FESEC-004 and TEST_PLAN.md T21 define the corrected
isolation requirement. Changelog, approved plan refinement and trace were updated
before implementation; no product/API/schema/permission/dependency change.

- `frontend/scripts/chg294-image-smoke.mjs`: replace `[lo]` name-array equality
  with real kernel flags/state, BusyBox netlink address listing (including down
  devices), IPv4 and IPv6 route checks. All non-loopback interfaces must be down,
  addressless and unrouted. Malformed/unavailable observations fail closed.
  Add the observed isolation metadata to the result.
- `frontend/scripts/chg294-image-verify.mjs`: narrow host runner bound to the
  existing R2 image ID and Docker Desktop context. Inspect each created container
  before start: image, run label, non-root UID, read-only root, no privilege/caps,
  no-new-privileges, no ports/host mounts and only three size-limited tmpfs paths.
  Ordinary smoke requires network-none. Internal-only networking is accepted
  solely for the explicit negative probe and is independently inspected.

All original mount/package/crypto/native/Next/cleanup assertions after the network
guard were compared byte-for-byte with the prior built-source helper, excluding
only the added network metadata output; comparison PASS. No Dockerfile/lock/image
change is needed: this helper is supplied via stdin, not included in runtime.

## Exact-image positive and negative results

Image: `nomosmart/frontend:0.1.0-chg294-r2`

`sha256:2c65c3eab7f7601612297a6c1ec11f8445ac0b2c174c18f4076cf98c2a70eb9d`

Command (Node is the previously signature/checksum-verified host runtime):

```bash
NOMOSMART_IMAGE_SMOKE_SCOPE=CHG-294-R2 \
  /tmp/chg294-r2.5S694K/node-v24.21.0-darwin-arm64/bin/node \
  frontend/scripts/chg294-image-verify.mjs
```

| Case | Actual result |
| --- | --- |
| Active non-loopback interface on a new internal-only network | PASS rejection: host ordinary-smoke inspector rejects it; actual helper exits 1 at administrative-down assertion before native work. No external egress or NET_ADMIN. |
| Incorrect scope | PASS rejection, exit 1 before writes/Next. |
| Unexpected option | PASS rejection, exit 1 before writes/Next. |
| Missing required tmpfs | PASS rejection, exit 1 before writes/Next. |
| Correct network-none with inactive kernel tunnel devices | PASS, exit 0. Nine down interfaces are tolerated; only lo has addresses/routes. |
| Actual image runtime | linux/arm64/musl, UID 10001, Node 24.21.0, bundled OpenSSL 3.5.8, all three system crypto packages 3.5.8-r0; Node has no dynamic system crypto linkage. |
| Actual native libraries | Next 16.3.3, sharp 0.35.4, libvips 8.18.6, libheif 1.23.2. |
| Native PNG/JPEG | Encode, resize and raw decode PASS. |
| Next `/login` | HTTP 200, actual NomoSmart response. |
| Next PNG/JPEG optimizer | HTTP 200, image/webp, 32×24, valid decodable output. |
| Next AVIF | HTTP 200, image/avif, unchanged 64×48 original bytes; no forced optimization. |
| Static packaging contracts | 4/4 PASS; both helper syntax checks PASS. |

All probes use actual Docker/kernel/application results, not fake interfaces,
mock adapters, synthesized versions or successful exit substitutions. This is
container smoke, not a complete authenticated workflow or readiness test.

Run label: `chg294-r2-verify-35bcd7b6`. All five containers and the internal-only
network were removed by exact ID after run-label verification. Independent
post-run label inventories are empty. No host/kernel settings changed. Old and
new Frontend image IDs are retained; no Provider or current data was accessed.

## Conditional deployment decision

The user's deployment condition is **not fully satisfied**:

- `./HARNESS/harness.sh coverage:check` fails, exit 1: no current source-bound
  successful full Frontend coverage evidence. Prior R2 measured frontend lines
  12.64%, statements 11.45%, functions 12.06%, branches 9.51%, below 80%.
  Prior focused Backend measurement was 30%, not the full suite. This turn does
  not invent a replacement coverage manifest or relabel focused results.
- `./HARNESS/harness.sh test:e2e`, pointed at a fresh prerequisite-only copy of
  the unchanged runner/package via `NOMOSMART_HARNESS_ROOT_DIR`, fails exit 1,
  one blocked prerequisite check. All seven E2E URL/account variables are absent.
  No test endpoints were substituted and no live fixture/setup/browser ran.
- Previous same-image Scout/SBOM evidence remains valid for the unchanged bytes;
  it is not a waiver for these independent release gates. The full OIDC/session
  matrix and source-bound full-suite acceptance are still incomplete.

Therefore no cluster baseline query, render, Helm upgrade, Job, bootstrap,
migration/V049, identity/data/index mutation or Provider call was performed.
Next work is completing the missing full-suite test environment/coverage scope,
not requesting another blanket deploy approval or lowering the threshold.
Once those conditions actually pass, fresh image/source/render/protected-resource
and rollback checks still precede an authorized deployment; old revision-37
render/operational bindings are not reused.

## Evidence and preservation

Artifacts: `/tmp/chg294-r2-verify.95D56v`.

| Artifact | SHA-256 |
| --- | --- |
| Corrected smoke helper | `4426b474c3ccfe3217fceb047c8a4f73a036e3fc0c5905746691bcba2793609d` |
| Host verifier | `e90b94ffdb38675fae103ee51df1492a257bb2692f0509efb62a18260b9b90af` |
| `verification.jsonl` | `ac01e379843c993716d028b668fd169e480b3d3d7df963de78120ef719f80673` |
| `coverage-gate.log` | `c5340c121065376ff85e56d0d2d210aec9bbcef383f9981977a750df99a507bc` |
| `e2e/test-results/e2e/summary.json` | `abb5dbce3d0254932297999ed2543033fceb03a5cfb26f9485db0cf6e0437417` |

Package SHA-256 `76cf6331e73990bc2598aa5dd94728a1dfb58cdfb2c86cd37229be9debbfa404`,
lock `0c00961b9a9baa799788c85cb6fdeff573d34ca8605b685fcaad17671e9ac025`, Dockerfile
`3b5e7c827f4bdc9f28e9088002e61d50615270792a300ff33aeb0a18b53157bf` and product/chart
fingerprint `578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79` remain
unchanged. The prior failing helper/hash and scanner reports are preserved in
the original image preparation/evidence, not overwritten as successful.

Final `spec:doctor`, `spec:trace` (five mappings), `plan:approved`, `test:plan`
and `git diff --check` pass. Independent JSONL checks confirm four rejection
cases, one positive case, cleanup and all three raw evidence hashes above.

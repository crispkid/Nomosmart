# CHG-294 Stage A — Image preparation and deployment preflight

Date: 2026-09-10. Status: image built and bounded smoke/scan/SBOM complete;
promotion stopped for bundled Node crypto review. No dry-run or Helm write.

## Authority and unchanged requirements

Peter's latest request is `可以部署`, following disclosure of the R1 verification
gaps. Apply the existing DEVELOPMENT_PLAN.md staged delivery strategy: execute
only its Stage A prerequisites, then stop for the separate exact-bound Stage B
decision. No risk acceptance is inferred. SPECIFICATION.md 10.51 FESEC-001..004,
TEST_PLAN.md CHG-294 T01..T16 and the 80% coverage/full E2E gates are unchanged.

## Bounded operations

1. Recheck source hashes and explicit Docker/Kubernetes contexts, release status
   and local images without outputting credentials, Secret bodies or Helm values.
   Stop on unexpected baseline/source drift. Historical baseline is revision 36,
   Backend/Frontend chg292, Migration chg288; do not assume it remains current.
2. Build only `nomosmart/frontend:0.1.0-chg294` for linux/arm64 from the approved
   Dockerfile/lock and secret-excluding build context. Do not overwrite an existing
   candidate tag without verifying its origin. Do not rebuild Backend/Migration.
3. Run isolated, labelled, network-none, non-root final-image smoke containers.
   Check actual system crypto and Node linkage separately, sharp/native versions,
   benign PNG/JPEG processing and the approved AVIF behavior. Keep writes in
   disposable container/tmpfs test paths, no current data/config mounts.
4. Scan exact local image IDs, generate full finding reports and SPDX SBOM with
   existing Docker Scout; no push, new registry authentication, suppression/VEX or
   private configuration upload. Out-of-scope required repairs stop promotion.
5. Verify the preserved CHG-293 Backend candidate source/image binding. Only if
   fresh baseline and candidate checks permit, render the prospective revision
   twice using reuse-values, backend chg293, frontend chg294, migration chg288 and
   unchanged forward-v047. Use `--dry-run=server --hide-secret`; compare canonical
   HOOKS-through-EOF UTF-8 SHA-256 and non-Secret manifest differences in memory.
   A render is not deployment approval, nor proof that bootstrap is write-free.
6. Record exact evidence and remaining gates; remove only this stage's labelled
   disposable smoke containers. Do not deploy while unmet gates remain.

Forbidden: Helm write, Job creation, Kubernetes mutation, V049, backup/data or
permission changes, graph repair, reprocess, re-embed, reindex, manifest switch,
Provider or billing query. No existing application/identity/PVC/index changes.

## Verification status

R1 source results remain in CHG-294-R1-VERIFICATION.md. This stage does not repeat
or replace those broader tests. Machine-readable facts are in
[CHG-294-IMAGE-EVIDENCE.json](CHG-294-IMAGE-EVIDENCE.json).

### Built candidate and source preservation

- New Frontend tag: `nomosmart/frontend:0.1.0-chg294`.
- Docker image/index ID: `sha256:5281abacf6c0ba6fc07c757325aebf9ba9b964ca2eb8ce4f68bd664c36683655`.
- Platform manifest: `sha256:f1dbb690feb209f678df4cbfeac562692dcec69fa6008344428eb1c7c88a3b6f`;
  image config: `sha256:6ce1479aabb099900269c57d18eb27b39d2760618e2974861b20df6005cc38bb`.
- Build: linux/arm64, fresh isolated context containing only Git-tracked and
  approved nonignored Frontend source (157 files), 4.30 MB transferred; shared
  node_modules/.next and private environment files were not copied. No image push.
- `npm ci`: 590 builder packages, 180 production packages; both report zero audit
  findings. Next build and TypeScript passed. The existing unrs-resolver lifecycle
  script policy warning remains; no extra script permission was granted.
- Build ID: `jjyhtjhie3xw5n6z488q6pl8r` (Docker Desktop build history).
- Backend chg293 and Migration chg288 IDs match prior evidence; no rebuild.
  All 113 packaged Backend source files match the current source, not just named
  changed files. The historical ten recorded Backend hashes also match.
- Product/chart source fingerprint before/after:
  `578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79`.
  Package, lock and Dockerfile hashes remain the R1 values. No product edits.

### Final-image checks: functional pass, crypto promotion unresolved

Actual container is linux/arm64/musl, UID 10001, Node 24.20.0, Next 16.3.3,
sharp 0.35.4, libvips 8.18.6 and libheif 1.23.2. Packaged package/lock hashes match.

| Layer/check | Observed result |
| --- | --- |
| Alpine openssl/libssl3/libcrypto3 | All 3.5.8-r0; only these three packages changed/installed in base |
| openssl CLI/library | 3.5.8 |
| Node `process.versions.openssl` | **3.5.7** |
| `ldd /usr/local/bin/node` | musl, libstdc++, libgcc; no dynamically linked libssl/libcrypto |
| Native PNG/JPEG | Actual encode, 16×12 resize and decoded bytes pass |
| `/login` | Actual production Next HTTP 200 |
| Next PNG/JPEG optimization | HTTP 200, image/webp, 32×24 decoded dimensions |
| Next AVIF safe bypass | HTTP 200, image/avif, 64×48, exactly original bytes |

The system upgrade does **not** update Node's bundled crypto. This is direct
runtime/linkage evidence, not a conclusion from the CLI alone. The existing
FESEC-002 / approved plan explicitly requires scope review if the Node runtime
needs an additional upgrade. We cannot certify complete crypto remediation from
the package scan. This run did not establish reachability/exploitability of each
OpenSSL CVE through NomoSmart, and does not falsely label every upstream CVE as an
exploitable Node High/Critical finding.

Upstream verification on 2026-09-10:

- [OpenSSL advisory, 2026-08-25](https://openssl-library.org/news/secadv/20260825.txt)
  and [3.5 release notes](https://mirror.openssl-library.org/news/openssl-3.5-notes/)
  identify 3.5.8 security fixes; applicability depends on the affected APIs.
- [Node 24.21.0 release, 2026-09-08](https://nodejs.org/en/blog/release/v24.21.0)
  explicitly updates bundled OpenSSL to 3.5.8. It also changes bundled Undici,
  roots and other runtime components: this is a new bounded review decision,
  not a silent Dockerfile substitution under the 24.20.0 scope.

Recommendation awaiting understanding/scope confirmation: consider CHG-294 R2
to adopt official Node 24.21.0 with verified Alpine 3.24/arm64 digest and actual
bundled crypto checks, keeping application packages, product behavior, Backend,
Migration and existing data unchanged. Image availability/digest and the new
runtime's full impact have **not** been verified or approved yet. Do not treat
this recommendation as an approved R2 development plan.

### Security and SBOM

Docker Scout v1.24.0; local-only image resolution, no push, new registry login,
private configuration upload, suppression or VEX. `security:containers` passes:
Backend and Frontend each have zero High/Critical results. A separate exact-ID
Frontend all-severity SARIF also reports zero findings. This is the scanner's
result, **not proof that statically bundled OpenSSL 3.5.7 is repaired/unaffected**.

`security:sbom` passes for both candidates. Frontend SBOM identifies Node 24.20.0
and system crypto 3.5.8-r0; its inventory does not give a separate 3.5.7 OpenSSL
package entry. Runtime/linkage evidence is therefore retained independently.
Scanner indexing counts are 340/350; SPDX package arrays include the image
package itself (341/351). Raw evidence paths and hashes are in the JSON record.

### Boundaries and remaining gates

- Pre/post read-only Helm observations: `nomosmart-local`, namespace nomosmart,
  docker-desktop, revision **36/deployed**, four app Deployments generation 32,
  each Ready 1/1 at chg292. Three nodes were Ready on preflight.
- No revision 37 Jobs; completed historical audit Jobs retained. No server dry
  run attempted: candidate promotion was stopped before spending/approving the
  next delivery step. No canonical render hash is claimed.
- No full protected-data inventory performed this stage; no write command,
  application API mutation, mounted live config/data, Provider or billing call.
  This is not a complete new data-preservation certificate.
- Isolated smoke containers had network none, read-only root, dropped
  capabilities and no host ports; only benign tmpfs files were written. Both
  were auto-removed, label inventory empty. Local image and evidence remain.
- Full Frontend 80% coverage, full Backend coverage and full E2E gates remain
  open from R1. No waiver. A Node upgrade alone would not close those gaps.
- Exact source/image/render/protected baseline/bootstrap/rollback scope approval
  for Stage B is still required after prerequisites are resolved.

### Commands and reproducibility

Build command:

```bash
docker --context desktop-linux build --platform linux/arm64 --progress=plain \
  --iidfile /tmp/chg294-image.wyZJzX/frontend.iid \
  -t nomosmart/frontend:0.1.0-chg294 /tmp/chg294-image.wyZJzX/source/frontend
```

The temporary `check_backend.py` and `image-smoke.mjs` contain the exact bounded
checks; their hashes are recorded in the JSON evidence. They use no app import
with DB side effects and no Provider. Image smoke is run via stdin into the exact
image ID with `--network=none --read-only --cap-drop=ALL`, no host mounts and only
`/tmp`, `/app/public/__chg294-smoke`, `/app/.next/cache` tmpfs mounts.

Security commands used `NOMOSMART_SECURITY_OUTPUT_DIR` pointing to the isolated
evidence directory and `NOMOSMART_SCAN_BACKEND_IMAGE=local://nomosmart/backend:0.1.0-chg293`,
`NOMOSMART_SCAN_FRONTEND_IMAGE=local://nomosmart/frontend:0.1.0-chg294`:

```bash
./HARNESS/harness.sh security:containers
./HARNESS/harness.sh security:sbom
docker --context desktop-linux scout cves --format sarif \
  --output /tmp/chg294-image.wyZJzX/security/frontend.all-severities.sarif.json \
  local://sha256:5281abacf6c0ba6fc07c757325aebf9ba9b964ca2eb8ce4f68bd664c36683655
```

`spec:doctor`, `spec:trace`, `plan:approved` and `git diff --check` passed before
execution. Specification behavior is unchanged; this report records a discovered
runtime gap and the existing stop condition, not a new approved implementation.

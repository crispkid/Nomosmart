# PDF coordinator — CHG-305 R12 source integration checkpoint

> Historical / retired by CHG-305 R20 (2026-09-23). This document preserves prior
> design and evidence only; referenced container code and tools have been retired.
> Do not run these installation or recovery commands. The current Worker-local
> implementation and verification limits are in docs/CHG-305-R20-SOURCE-HANDOFF.md
> at the repository root. Source retirement did not uninstall any live resources.

Latest R18 R3 D07 (2026-09-22): v3 gated create/bind/sign/release source,
pre-payload input barrier, fixed shared startup deadline and original-grant
recovery validation are wired. Explicit image Python imports are now complete.
Optional `kubernetes_start_grant` config supplies expected deployment pins and
the read-only signer/key paths; it is not a runtime attestation or activation flag.
No signer binary/private key is silently created or installed by this source.
**The node guard and independently verified v3 attach are still incomplete;
v3 capability/start_attach remain closed. Do not activate or deploy this path.**
Local91 Python cases90PASS/1SKIP; selected coverage74.06% fails the unchanged80%
gate. Full Linux/Kubernetes startup/transfer/PDF acceptance is NOT_RUN. See
`docs/CHG-305-R18-R3-EXECUTION-RESULT.md` for evidence and remaining work.

Latest P14 source increment: opt-in Docker/Helm recipes and Worker mounts,
separate TLS observer/Worker/operator roles, durable drain, control readiness,
aggregate metrics and control integration test sources. See
`deploy/pdf-processing/README.md` and
`docs/CHG-305-R12-SOURCE-PACKAGING-RESULT.md` at repository root. Twenty-six
coordinator test methods are prepared, NOT_RUN. This supersedes only the source
inventory below, not its runtime warnings or historical results.

**Not runtime-verified or deployment-ready.** R12 A is partially
implemented. The fixed-AnyIO A-only risk decision is now accepted; independent
dependency closure/provenance and initial source primitives are prepared.
Official-client/lifecycle, mTLS HTTP entrypoint, private result storage and Backend
client/PDF routing source are now present. No product imports or behavioral tests
ran. The repository candidate routes PDF entrypoints through the new client;
the deployed application has NOT been updated. Do not activate this candidate
without completing packaging, capability proof and isolated acceptance.

## Prepared source, not runtime acceptance

- session_v2/protocol.py: strict versioned requests, policy/identity/hash binding,
  sequential page frames, UTF-8 and cumulative output validation. A failed read
  poisons the session; staged output cannot be published without the final frame.
- session_v2/runner.py: one-document, sequential fixed PDF operations; existing
  200DPI/layout/language behavior, bounded native tool output and private scratch.
  The candidate pipeline now calls the coordinator client; parser packaging and
  real execution remain unverified.
- journal.py: real-filesystem immutable intent revisions and process ownership,
  current-process concurrency, restart/recovery admission fencing. Schema2 records
  observed termination before exact cleanup. Record shape validation is not
  itself proof that a workload stopped.
- transport.py: bounded Docker binary and Kubernetes WebSocket frame readers.
  Complete transport EOF is distinguished from truncated frames and from actual
  process termination. Official SDK construction/handshake/lifecycle sources are
  prepared in platform_clients.py and docker_runtime.py/kubernetes_runtime.py;
  none are runtime-verified. No Docker/Kubernetes API was contacted.
- lifecycle.py: serial internal session owner; durable create/sequence intents,
  provisional page sinks, close/EOF/zero-exit/cleanup publication gate and explicit
  exact reconciliation without recreation or replay. service.py/server.py now
  provide the fixed mTLS ASGI routes, not public product endpoints.
- config.py / mtls.py: independent typed deployment configuration and actual TLS
  peer fingerprint bridge wired to the explicit server entrypoint. capabilities.py consumes a
  hash-approved, fresh real-acceptance receipt bound to runtime/safety configuration.
  No receipt producer, successful sample or actual isolation proof is supplied.
- results.py and shared session_v2/local_files.py/result.py: private result quota,
  ordered hashes, independent Worker envelope validation and lazy one-page reads.
- app/domain/pdf_processing.py and extraction_pipeline.py: current claim, DB
  parser admission, no-capacity yield, conditional same-session text/OCR fallback,
  actual progress, verified stop before DB release and fresh claim before Provider.
  No unguarded local PDF fallback; non-PDF tools remain on their existing paths.
- tests/test_source_primitives.py: request, filesystem and socket test sources.
  Twenty-one methods NOT_RUN, plus a parameterized Backend missing-claim guard.
  They do not replace actual PDF/mTLS/runtime/concurrency
  acceptance. No successful runtime stop receipt is fabricated by these cases.

Next within the existing A plan: complete fault/recovery orchestration, constrained
admission/probe sources and full live integration sources, then the consolidated
B/C readiness inventory. Packaging/operational sources now exist but are not
runtime verified. Retained CHG-304 sandbox
test assertions now explicitly target the historical helper, not the new production
route. Old exhausted probe scripts/receipts are unchanged and must not be rerun.
Do not enable this candidate or call A complete at this partial checkpoint.
Current source/static checkpoint: docs/CHG-305-R12-SOURCE-INTEGRATION-RESULT.md at
repository root. Historical FOUNDATION/LIFECYCLE result/evidence remain unchanged.

## Independent environments

- `pyproject.toml` / `uv.lock`: Python3.12 Linux aarch64/x86_64 only,36 necessary
  package versions. Nine original direct requirements are Docker7.2.0,
  Kubernetes36.0.3, FastAPI0.138.0, Uvicorn0.49.0, Pydantic-settings2.14.2,
  Pydantic2.13.4, Starlette1.3.1, H110.16.0 and local AnyIO4.14.2+nomosmart.2.
- `tools/pyproject.toml` / `tools/uv.lock`: separate macOS arm64 Python3.12
  package-audit environment, pip-audit2.10.1 plus28 necessary dependencies.
  These tools are not parser/coordinator runtime dependencies.
- Complete closures explicitly pin verified wheel URLs with SHA256 in PEP508
  requirements. Platform-specific wheel markers are retained. Source builds,
  extra package indexes and implicit Python downloads were not used.
- Kubernetes's actual36.0.3 wheel requires aiohttp and its closure in addition
  to synchronous-client requirements. They are not silently pruned merely because
  the planned adapter uses the synchronous client. Google-auth/SSH extras absent.

Original Backend/Frontend dependency files, environments and AnyIO vendor are
unchanged. Do not run a Backend sync to prepare this package.

## Historical dependency verification and subsequent risk decision

All44 runtime wheel entries (including8 architecture-specific duplicates) and
29 tool wheel entries match downloaded/source SHA256. Both frozen offline
exports succeed. Only the audit-tool environment was installed, offline with
`uv pip sync --require-hashes --strict`; no product environment was installed.

Strict runtime pip-audit exits1 at the local AnyIO version: UNKNOWN, not a known
vulnerability. Its fail-closed result is retained. Separate bounded genuine PyPI
queries cover all35 published runtime versions and upstream AnyIO4.14.2: no
reported advisories at this check. Tool audit29/29 reports no known vulnerabilities.
These findings do not prove overall security, platform behavior, image security,
or the safety of the local downstream patch. The local wheel's two modified
modules match existing upstream/member/patch provenance; no vendor rebuild.

Peter subsequently confirmed retaining4.14.2+nomosmart.2 in both Backend and this
coordinator. Both manifests/locks already reference the exact same vendor wheel;
the coordinator-only official4.14.2 proposal is withdrawn. Environments remain
independent. Do not silently substitute or rebuild that wheel.

R12 requires an explicit risk decision before integrating a necessary UNKNOWN.
Version selection alone was not that decision. The two-hunk review and
the A-only, hash-bound exception (subsequently accepted by Peter「Ok」) are recorded in
`docs/CHG-305-R12-SHARED-ANYIO-DECISION.md` at the repository root. Historical
strict audit failure, SBOM status and unexecuted tests remain unchanged.

Details: `../../docs/CHG-305-R12-RESULT.md` from the repository root perspective
(`docs/CHG-305-R12-RESULT.md`), and public dependency/SBOM evidence in that directory.

## Tool boundaries

P17 real parser lifecycle, owned-process crash/restart and ten-session test
sources are documented in `tests/README.md`. They are NOT_RUN under A and excluded
from production images. The pure-local `describe` inventory is not acceptance;
actual execution requires a new bounded B/C scope and already accepted real
capability evidence. Parser concurrency does not replace25/10 business-flow proof.

`prepare_dependencies.py` fetches bounded public metadata/wheels and verifies
identity/hashes without importing packages. `audit_bounded.py` invokes the genuine
fixed pip-audit CLI with strict mode and a transport-only host/size/deadline guard;
no advisory responses or findings are fabricated. `supplement_advisories.py`
retains strict UNKNOWN while inventorying remaining real public advisories and
read-only comparison of the existing patch. Private run receipts must never be
interpreted as authority to rerun tests, build images, access runtimes or deploy.

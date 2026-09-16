# CHG-298 R2 — current-model acceptance, 2026-09-12

## Result

The eleven originally failing named cases now aggregate **10 PASS / 1 FAIL**
across serial, source-identical invocations. This is not a single full-suite
run, a new coverage result or release/deployment acceptance.

| Original case | Latest result | Evidence |
| --- | --- | --- |
| 3 — reference and approval workflows | PASS | Real parsing, tagging, embedding, staging and graph preview; retained submission, stale-lock refusal, manager/Owner approvals and history checks |
| 4 — external services and domain adapters | FAIL, downstream S3 sync | Actual canonical vector, publish, OpenSearch and complete Neo4j projection checks passed; the retained later S3 sync assertion failed |
| 5 — embedding and active-version switch | PASS | Two genuinely extracted/approved/published versions; earlier canonical build permits domain-level switch; legacy/invalid target still refused |
| 11 — compatibility routes | PASS | Completed graph-job retry remains 409 with no changes; separate real failed-only retry/worker test also passed |
| Other seven original cases | PASS | Together with case 11, eight non-Provider cases passed in this fresh run |

Additional guards: CHG-296 **39 PASS**, CHG-297 **47 PASS**, and the separate
CHG-298 real graph retry **1 PASS**. Test writers ran serially; no assertion was
relaxed, no failure was relabeled skipped/xfail, and product/test source matches
the previous CHG-298 source-bound evidence.

## Model authorization and actual use

Peter answered `Ok` to the explicit synthetic sample, tagging instructions,
`api.openai.com` destination, existing two models and at most 20 short requests.
Only the harmless age-18 / identity-document / manager-confirmation test source
was used; no MAAS document or real user's personal data was sent.

- `nomosmart-chat` / `gpt-5.6-luna`: 8 real Responses requests.
- `nomosmart-embedding` / `text-embedding-3-small`: 4 real Embeddings requests.
- Total: **12 requests, all HTTP 200; 2,421 reported tokens**. Eight unused
  request slots were not consumed. No billing query, pricing change or increase
  to an existing limit. Provider-side spending limits were not independently read.
- Existing Provider credentials stayed in their configured Backend runtime.
  Isolated SQL held only a freshly generated loopback transport token. The
  transport forwarded genuine requests/responses, without canned output or
  generated/fixed vectors. Each request rechecked current model configuration.
- Four actual completed embedding builds each contained one 1,536-dimensional
  vector. Four versions completed genuine approvals; three were actually
  published, across two documents/manifests. The successful switch test rolls
  back its final domain transaction after checking manifest and queued work;
  it does not certify a persisted positive HTTP switch/replay or graph execution
  for the switched-back version.
- Provider transport was stopped after request 12. No Provider error or
  ambiguous outbound request was replayed.

## Remaining defect — discuss before repairing

The isolated S3-only diagnostic returns:

```text
status: failed
error_code: ocr_model_required
error_summary: An active OCR model is required
```

The file fetch and snapshot path reaches
`backend/app/domain/data_sync.py::_execute_data_source_sync_attempt`. It sets
`ready_for_extraction`, but then calls `queue_document_extraction` immediately.
That function requires an OCR model on the new version. The sync-created version
does not have one, so synchronization is marked failed and its snapshot attempt
is compensated instead of becoming ready for manual extraction.

This conflicts with the existing `DSYNC-001` / `APISRC-001` contract and acceptance
criteria: first sync and changed-content sync must finish at ready-for-extraction,
without automatically starting extraction. Creation in `api/routes/data_sources.py`
and later `_new_version` both omit an OCR execution choice, consistent with the
user making that choice when manually starting extraction.

Recommended discussion outcome: separate synchronization from extraction.
Successful sync saves the source/version and waits; only the explicit extraction
action selects/validates OCR and enqueues its pipeline. Preserve unchanged-content
handling, generation fences, scheduling, compensation, permissions and auditing.
Do not conceal this defect by assigning an arbitrary OCR model, bypassing the
guard, or changing the expected sync result to failure. No repair is implemented
under this acceptance-only scope.

The initial S3 failure prevented subsequent unchanged/scheduled/provider-refusal
assertions in that case from running. They remain in the test and are not claimed
as passed by other suites. Other sync protocols were not newly exercised here.

## Intermediate results retained

1. `approval-first.xml`: one failure at local model transport, before any
   outbound attempt. The receipt was exactly zero requests. A local GET verified
   the listener and a diagnostic invocation of the same test then passed with
   real calls. No product changes were made; the transient connection failure's
   exact cause is unproven, not presented as a fixed product bug.
2. The Provider input guard was adjusted before the first request to validate
   the approved synthetic body rather than require a Markdown heading that a
   structure-aware chunk legitimately omits. A zero-attempt startup was restarted;
   the used budget was never reset or reopened.
3. A diagnostic SQL query first used `purpose` instead of `usage_purpose`, and
   the S3-only diagnostic initially called the session factory twice. Both were
   diagnostic-script mistakes, corrected without application-code changes.
4. The previous egress-review rejection and first-run test setup/concurrency
   failures remain in `CHG-298-VERIFICATION.md` and its evidence, not overwritten.

## Execution and evidence

Private run root: `/tmp/chg298-provider.hinpQj`. Fresh real PostgreSQL through
existing Flyway V048, Keycloak realm `chg298-api-hinpqj`, OpenSearch, Neo4j, S3 and
Redis, with an internal-only Docker network and exact run labels. Source copy
excluded repository `.env`; no existing credentials/realm/data were reused.
Installed images only; no image build/pull, Kubernetes mutation, Helm deployment,
current MAAS reprocessing/reindexing or current manifest/permission changes.

Original broad test file: `backend/tests/test_live_backend_api_behavior.py`.
Focused commands used `run_capture.py` / `run_focused.py` with the exact node IDs
above, then `run_nonprovider.py` serially and `test_chg298_graph_retry.py` alone.
The approval diagnostic used Python exception tracing of endpoint/type only,
without replacing calls, responses, data or assertions; its XML is retained.

Verification gates: `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`,
`backend:syntax` and `git diff --check`. Source hashes, every XML result,
Provider receipt hashes/usage, actual-generation audit, safe model-preservation
comparison and exact cleanup are recorded in
`CHG-298-R2-VERIFICATION-EVIDENCE.json`.

Cleanup verified: removed exactly 7 run-owned containers, 5 exclusively consumed
anonymous volumes and 1 internal network; stopped the owned relay and Provider
processes. All 14 preexisting containers retained the same running/stopped state
and start time; no images were removed. Disposable test data is not recoverable;
private evidence is retained. Current model configuration and MAAS model bindings
were independently reread and unchanged. Full-suite coverage (80% required), frontend,
browser/E2E, security scanning, images and deployment were not certified here.

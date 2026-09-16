# CHG-296 verification — partial, not release accepted

2026-09-12. Peter approved the exact CHG-296 plan at Gate 4. Specification
§10.53 and `CURSOR-META-001`, `SWITCH-EVIDENCE-001`, `SWITCH-ATOMIC-001`,
`REPAIR-VERIFY-001` govern this work. No deployment or Provider authority.

## 結論（白話）

- 已補上分頁「還有下一頁」資訊，沒有改變排序、游標簽章或權限。
- 已補上版本切換的資料核對：不能只憑「已發布」標記就切換。
- 本次新增 39 項核心檢查：37 通過、2 未通過。2 項卡在另外發現的既有 Bug。
- 原 11 項：6 通過、5 未通過，其中 3 項缺真實模型／發布流程證據。
- 不能宣稱全部修好或可以部署。下列三個產品 Bug 保留原失敗，等待討論。

## Implemented scope

| Files / functions | Change and proof |
| --- | --- |
| `backend/app/api/schemas.py` — eight cursor page models | Required boolean `has_more`; preserve nullable cursor and items. |
| `routes/compatibility.py` — PipelineRunPage, GraphSyncJobPage, AuditLogPage and construction sites | Same metadata, including explicit false on no-visible-project early returns. No query/security rewrite. |
| `routes/serving.py`, `identity.py`, `approvals.py`, `integration_clients.py` — page constructors | Pass the existing authoritative limit+1 continuation result, not displayed item count. |
| `frontend/src/lib/api.ts` | Align existing cursor response types only; offset/total/autocomplete and navigation unchanged. |
| `domain/embeddings.py::load_published_embeddings` | Validate the exact selected published build, scope, active chunks, final model-bound retrieval hash, fingerprint, profile and vector count/mapping/dimensions/checksums. Never substitute a newer staged build. |
| `domain/embeddings.py::_load_embedding_batch` | Reuse validation with `bind_version=False`; reject malformed/nonfinite numeric vectors. Normal embedding callers retain existing binding behavior. |
| `domain/review_publish.py::LiveOpenSearchPublishedAdapter.verify_published_build` | Read concrete index mapping, scoped count, exact-ID mget in batches of 100 with 10-second request timeouts and bounded response reads. No index writes/refresh/repair. Other-version rows remain untouched. |
| `domain/review_publish.py::switch_active_version` | Project → Document → Version/manifest fence; reload after waits; check evidence before state/job/notification/audit mutations, inside no-autoflush validation. Active chunks only. |
| `routes/approvals.py::switch_document_version_active` | Pass the request's configured Settings to the guard. Auth/Owner/idempotency contract unchanged. |
| `frontend/src/lib/operationalMessages.ts`, zh/en locales | Safe translated `published_index_evidence_invalid` message. |
| `tests/test_chg296_cursor_and_switch_guards.py` | Real authenticated paging, real SQL invalid-evidence/atomicity/concurrency and real OpenSearch read/mismatch tests. |
| `tests/test_live_backend_api_behavior.py` — original case 6 | Fix wrong test layer: missing queued work is an idempotent no-op, while direct domain execution must still raise exactly `validation_run_not_found`. Other original failures/assertions retained. |

Cursor inventory: ApprovalTaskPage (pending/history), ApprovalRequestPage,
ProjectChatConversationPage, IntegrationClientPage, ValidationRunPage (project
and inventory), ValidationRunItemPage, NotificationPage, IdentitySyncRunPage,
PipelineRunPage, GraphSyncJobPage, AuditLogPage. Actual OpenAPI verifies all 11
models. Multi-page HTTP covers notifications, chat, both validation inventories,
validation items, identity and clients. Existing CHG-293 verifies cross-user chat
cursor rejection. Existing cursor format has no expiry field/TTL: expiry-specific
testing is not applicable; this change does not invent a new expiry contract.
Nonempty graph-job list coverage remains FAIL, not waived by empty-page checks.

No new dependency, SQL schema, migration, backfill, image or deployment change.
Invalid old targets need a separately authorized rebuild, not an automatic fix.

## Verification results

| Run | Result |
| --- | --- |
| New focused final `tests/test_chg296_cursor_and_switch_guards.py` | **37 PASS / 2 FAIL**, 0 errors, 0 skips, 15.681s |
| Original eleven final node IDs | **6 PASS / 5 FAIL**, 0 errors, 0 skips, 15.217s |
| CHG-293 history/permissions + CHG-295 deletion/lock/contract regression files | **78 PASS**, 14.247s |
| Eight selected actual CHG-281/283 parser/normalizer/hash functions | **8 PASS**, 0.638s; fake-session/adapter tests were not used as evidence |
| `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`, `backend:syntax`, `git diff --check` | PASS |
| Frontend `node --test frontend/tests/i18nGuard.test.mjs` | **4 PASS** |
| Frontend full configured `tsc --noEmit --incremental false -p frontend/tsconfig.json` | FAIL: preexisting generated `.next/dev/types/validator.ts` imports absent `src/app/setup/page.js`. Generated files untouched. |
| Source-only tsc using recorded isolated `tsconfig-source.json` | PASS; not a substitute for full build/Frontend acceptance |

Initial focused test preparation errors (route prefix/required stored fields/
required scope parameter) are retained in r1..r4 artifacts; final inputs use
the actual existing contract. Original eleven r1 was 5 PASS/6 FAIL; final case 6
now passes with the stricter layer-specific assertion described above.

### Original eleven, individually

| # | Scenario | Final result / reason |
| --- | --- | --- |
| 1 | Reports/session drafts | PASS |
| 2 | Knowledge, chat, notifications, data sources | FAIL later at data-source creation; pagination assertions now pass. New Bug B01. |
| 3 | Reference/review workflows | FAIL / BLOCKED genuine submission prerequisites: graph/pipeline/staging evidence missing. |
| 4 | External services/domain adapters | FAIL / BLOCKED genuine canonical embedding build. |
| 5 | Embedding/switch edges | Required legacy refusal now passes; later genuine positive build/switch prerequisite remains FAIL / BLOCKED. |
| 6 | Configuration/identity/worker/sync | PASS |
| 7 | Pipeline/publish refusal edges | PASS |
| 8 | Serving/document helpers | PASS |
| 9 | Extraction/parser/helper edges | PASS |
| 10 | Approval/project/data-source route edges | PASS |
| 11 | Compatibility/governed workflows | FAIL later at nonempty GraphSyncJobPage conversion; pipeline pagination now passes. New Bug B02. |

## New bugs requiring discussion, not silently repaired

1. **B01 — Creating a data source raises 500.**
   `backend/app/api/routes/data_sources.py:165` sends `project_generation` to
   `DocumentVersion`, whose model/schema has no such field. Proposed next scope:
   correct generation ownership on the sync work/outbox, keep project lifecycle
   fencing, and cover create/rollback/concurrency. Do not casually add a DB column.
2. **B02 — Nonempty graph-job lists raise 500.**
   `routes/compatibility.py::GraphSyncJobResponse` is a plain BaseModel but the
   page receives ORM rows. Proposed next scope: explicit safe ORM projection
   without changing exposed fields, with nonempty/multi-page/denied-scope tests.
3. **B03 — Active-version HTTP requests fail before the domain guard.**
   `routes/approvals.py:513` constructs an idempotency scope from the operation
   plus two UUIDs, exceeding `idempotency_keys.scope VARCHAR(100)`
   (`app/db/models.py:642`). New authenticated test retains this failure.
   Proposed next scope: bounded deterministic operation/actor/target-bound scope,
   preserving replay/conflict security and existing-record compatibility;
   inventory sibling operations before deciding any migration is necessary.

The approved plan explicitly stops on newly revealed unrelated product changes.
No fixes to B01/B02/B03 were made. T07 HTTP acceptance is blocked by B03;
domain refusal/atomicity and concurrency checks pass. T09 genuine successful
generation/publication/switch remains BLOCKED; no fixed vectors, stored status
or controlled index inputs certify a successful workflow.

## Isolation, safety and remaining gates

Private run root: `/tmp/chg296-guards.gYP6UX`. Scripts use installed immutable
images, a fresh internal Docker network, fresh credentials/realm/DB, resource
limits, no current config and loopback-only byte forwarding to real services.
Six service containers plus one relay; transient Flyway was the eighth, targeting
only the fresh V048 database. No worker process automatically executes queued work.

Controlled stored vectors/status/index documents test validators and read-back
only. Every switch invocation must refuse; only the read-only validator is used
for consistent stored evidence. Runtime audit confirms zero successful switch
audit rows and zero newly active guard targets. No Provider calls or current
application/index/identity mutations; no images built or Helm/Kubernetes writes.

Cleanup result and exact source/artifact digests are recorded in
`CHG-296-VERIFICATION-EVIDENCE.json`; test logs and XML are retained privately.
This is **partial acceptance**. Historical full Backend 529 PASS/11 FAIL and
59.3662% coverage are not replaced by these focused results. Full Backend/Frontend,
80% coverage on each side, browser/E2E and release/security/deploy gates remain
unmet or unexecuted. No test/threshold was deleted or lowered.

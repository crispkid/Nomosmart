# CHG-297 verification — scoped repairs passed, overall acceptance partial

2026-09-12. Peter approved `CHG-297 Data Sync Generation, Graph Job Response And
Idempotency Scope Repair` at Gate 4. Specification §10.54 and its four requirement
IDs govern this work. No image/deployment/current-data/Provider authority.

## 白話結論

1. 資料服務建立及立即同步的程式錯誤已修復，並保留專案權限及封存防護。
2. 有資料的圖譜工作列表可以正常回傳、翻頁，不再因 ORM 轉換而 500。
3. 版本切換不再因防重送識別過長而 500；仍會拒絕無權限、過期或證據不足的切換。

新增 47 項、CHG-296 的 39 項、相關回歸 80 項皆通過。原十一項仍有四項
未通過，不能稱為整套系統驗收完成。未部署，也未變更目前環境的應用資料。

## Implementation and trace

| File / function | Requirement and change |
| --- | --- |
| `backend/app/api/routes/data_sources.py::_lock_enqueue_project` | DSYNC-GEN-001: authorize first, then lock Project before enqueue, refresh cached state after waiting, reject inactive state, hold parent lock through run/outbox commit. |
| `data_sources.py::create_data_source` | Remove nonexistent DocumentVersion field; explicitly bind initial DataSyncRun and outbox column/payload to current generation. Flush connection/document before version to preserve FK ordering, in one transaction. |
| `data_sources.py::queue_data_source_sync` | Fix undefined project variable; serialize duplicate-run check/enqueue under the parent fence. No credential/source/Cron rewrite or HTTP remote fetch. |
| `backend/app/api/routes/compatibility.py::list_graph_sync_jobs` | GRAPH-DTO-001: explicit declared DTO `model_validate(row, from_attributes=True)` projection, same safe fields and authorized cursor query. |
| `backend/app/core/idempotency.py::storage_scope` | IDEMP-SCOPE-001: <=100 characters unchanged; longer scopes use reserved `scope:v1:sha256:` plus complete UTF-8 SHA256 digest (80 characters). |
| `backend/app/domain/public_api_controls.py::begin_idempotent_operation` | Normalize once before lookup/insert/unique-conflict reread. Existing key HMAC, request hash, TTL/lease, conflicts and replay stay unchanged. |
| `backend/tests/test_chg297_sync_graph_idempotency.py` | REPAIR-VERIFY-002: real SQL/OIDC/HTTP, uniqueness rollback, lock waits, duplicate enqueue, safe pagination, actual second identity, idempotency concurrent claim and switch refusal snapshots. |

No ORM model or SQL schema changes, migrations, backfill, Frontend changes,
dependency/config changes, image builds or deployment. `DocumentVersion` does
not gain a generation column. Old idempotency records are not rewritten/deleted.
The shared helper is the only application lookup of `(scope,key)` found in the
source inventory; no application cleanup code depends on parsing raw scope IDs.

### Scope compatibility inventory

Existing server-generated scopes were inspected in `documents.py`, `approvals.py`,
`compatibility.py` and `public_api.py`; request payloads never select the scope.
The reserved hash prefix does not collide with any existing caller namespace.

| Caller identity | Standard shape effect |
| --- | --- |
| approve/reject, publish, submit-review, graph retry | Existing two-UUID scopes <=100: unchanged. |
| public chat JSON/SSE, public feedback | Client/project or response identity and transport suffix retained; <=100 unchanged. No Provider request was made. |
| upload and upload item | Existing project/actor/item scopes retained when <=100; long future item suffix uses full scope hash. |
| switch-active | Operation plus two UUIDs =104 characters; stored as 80-character full-scope hash. |
| re-extract | Existing project/document/actor scope also exceeds 100; same bounded persistence fix, no extraction redesign or execution. |

SQL V001 and ORM both specify scope VARCHAR(100), unique `(scope,key)`.
Actual isolated DB verified length100. Such a schema cannot store an old raw
104-character value. Short legacy rows still replay using the same scope and
HMAC key. Tests cover boundaries99/100/101, Unicode, differing tails/identities,
same request replay, payload409, failed replay, TTL/lease, mandatory keys and
two real transactions contending on the unique constraint.

## Verification results

All pytest runs use a source copy without `.env`, explicit fresh service config,
and the repo's installed Python. Canonical command wrapper:
`backend/.venv/bin/python /tmp/chg297-repair.8ATeC6/run_capture.py <run> <node IDs>`.
The wrapper invokes `pytest -o addopts= -p no:cacheprovider --tb=short -q` and
records JUnit XML privately. This is focused verification, not a coverage run.

| Run / target | Result |
| --- | --- |
| `focused-final`: `tests/test_chg297_sync_graph_idempotency.py` | 47 PASS, 0 FAIL/errors/skips; 3.771s |
| `chg296-r1`: `tests/test_chg296_cursor_and_switch_guards.py` | 39 PASS, 0 FAIL/errors/skips; 15.370s (previously37/2) |
| `regressions-r1`: CHG-293 history/authority, CHG-295 contracts/deletion/locks and two CHG-247 idempotency contracts | 80 PASS, 0 FAIL/errors/skips; 14.704s |
| `eleven-r1`: original eleven named cases in `test_live_backend_api_behavior.py` | 7 PASS/4 FAIL, 0 errors/skips; 13.558s (previously6/5) |
| `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`, `backend:syntax`, `git diff --check` | PASS; exact outputs in the evidence JSON. |

Initial focused run was 37 PASS/3 FAIL: two stored archive inputs lacked required
archived_at/archived_by, and one cursor test prepended ignored base64 punctuation
without changing signed bytes. Corrected only those test inputs; product schema
and cursor decoder were not changed. Run 2 was 41 PASS, then six extra manual
permission/switch-rollback checks produced final 47 PASS. Original tests unchanged.
Intermediate XML/logs remain retained. No fake service or authentication override.

### Original eleven: unchanged assertions

| # | Case | Result |
| --- | --- | --- |
| 1 | Reports/session drafts | PASS |
| 2 | Knowledge/chat/notifications/data sources | PASS; prior constructor failure repaired |
| 3 | Reference/review workflows | FAIL / prerequisite BLOCKED: genuine graph preview, pipeline submission and staging evidence absent |
| 4 | External services/domain adapters | FAIL / prerequisite BLOCKED: genuine canonical embedding build absent |
| 5 | Embedding/switch edges | FAIL / prerequisite BLOCKED: later genuine canonical build absent; required invalid-target refusal still passes |
| 6 | Configuration/identity/worker/sync | PASS |
| 7 | Pipeline/publish refusal edges | PASS |
| 8 | Serving/document helpers | PASS |
| 9 | Extraction/parser/helper edges | PASS |
| 10 | Approval/project/data-source edges | PASS |
| 11 | Compatibility/governed workflows | Graph list now passes; later completed-job retry assertion fails |

Case 11 now calls retry on a **completed** graph job without an Idempotency-Key,
expecting 200/completed. The existing failed-only retry contract correctly returns
409 `graph_sync_retry_not_available` before the key check. This is a newly exposed
test-contract mismatch, not evidence that completed jobs should be replayed.
Do not relax the backend. Recommended follow-up, subject to scope confirmation:
assert completed-job 409/no writes; use an actual failed job and mandatory key for
separate 202 durable enqueue/replay/conflict checks. No such follow-up edit was made.

## Isolation and remaining gates

Private root `/tmp/chg297-repair.8ATeC6`; unique label `chg297-repair-8atec6`.
Six real service containers and one byte-only relay, internal Docker network,
fresh credentials, fresh OIDC realm and loopback ports. Transient Flyway was the
eighth container and applied existing migrations only through V048 on the new DB.
No automatically running worker consumed queued work. Existing images only;
no pulls/builds/current secrets/Helm/Kubernetes or Provider calls.

Runtime audit confirms Flyway 48, zero successful switch audit and zero activated
guard targets. Stored status/vector inputs prove reads/refusals/transactions only;
they are not evidence of real model generation or publication.

Source-bound hashes, all case results, runtime and exact cleanup receipt are in
`docs/CHG-297-VERIFICATION-EVIDENCE.json`. Cleanup removed only 7 run-owned
containers, 5 exclusively consumed anonymous volumes and 1 internal network;
all 14 preexisting containers (4 running/10 stopped) and all images were preserved.
Logs/source copies stay available; disposed test service data cannot be recovered.

Global coverage was not rerun. Historical Backend 59.3662%, full Backend/Frontend,
each 80% threshold, browser/E2E, security and image/deployment acceptance remain
open/unexecuted. Focused passes do not waive these gates or certify a release.

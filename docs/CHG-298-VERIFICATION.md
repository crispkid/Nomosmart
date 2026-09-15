# CHG-298 — Partial verification and explicit Provider egress boundary

2026-09-12. Specification 10.55; Peter authorized the previously presented four
cases and directed using current models/limits without another generic approval.
This report does not claim all four complete, full coverage, release or deployment.

## 白話結果

- 四項中，**圖譜工作重試已完成驗證**：已完成的工作不能重試；真正失敗的工作
  可以排入一次重試，重送不重複，實際 Neo4j 工作能完成。
- 其餘 **送審、索引、版本切換三項仍未驗證**。已補測試準備，但執行安全審核
  拒絕啟動外部模型傳輸，要求明確核准外送資料與目的地。沒有繞過拒絕。
- **零 Provider 呼叫**，未取得或複製 Provider API Key；沒有目前 MAAS 資料寫入。
- 八項不需模型的原測試、CHG-297 的 47 項及單獨執行的 CHG-296 的 39 項通過。
  不是一次完整十一項皆通過；歷史 7 PASS / 4 FAIL 紀錄保留。

## Changes

| File | Purpose / verification |
| --- | --- |
| `backend/tests/test_live_backend_api_behavior.py` | Case 11 now checks exact 409 and unchanged job/outbox for completed retry (PASS). Cases 3/4/5 now call genuine isolated preparation; retained positive and negative assertions, no synthetic published status accepted (runtime BLOCKED). |
| `backend/tests/chg298_live_preparation.py` | Explicit-isolation, safe model-binding input; actual S3 source readback, parser/chunker/tagging/embedding/staging; real authenticated review/publish and graph work. Written/syntax-checked, **not exercised against a Provider**. |
| `backend/tests/test_chg298_graph_retry.py` | Actual refused Neo4j TCP connection creates failure, missing key 422, keyed 202, SQL parent/child/outbox, replay, real worker completion and redelivery terminal-audit uniqueness. PASS. |
| Specification, plan, test plan, trace and understanding | Record current-model direct-test instruction, unchanged contracts, outcomes and the later execution permission boundary. |

No product application code, API/schema, migration, dependency, Frontend or
deployment changed in CHG-298. Unrelated existing dirty changes were preserved.
The Provider bridge is private one-run operational code, not a production adapter.

## Actual test results

Private run: `/tmp/chg298-live.KUXjJE`, label `chg298-live-kuxjje`.
Commands use `backend/.venv/bin/python <run>/run_capture.py <name> <node IDs>`;
the wrapper invokes `pytest -o addopts= -p no:cacheprovider --tb=short -q` from
an explicit source copy without repository `.env` and records JUnit XML.

| Run | Outcome |
| --- | --- |
| `retry-first` / original case 11 | 1 PASS, 6.547s |
| `graph-real` / initial new test plus original case 11 | 1 FAIL + 1 setup ERROR, 36.249s; retained below |
| `graph-real-r2` / new graph test alone | 1 PASS, 36.589s |
| `eight-nonprovider` / original cases 1,2,6,7,8,9,10,11 | 8 PASS, 6.143s |
| `guards296` / initial regression | 38 PASS / 1 FAIL, 15.999s; overlapping writer, retained below |
| `guards296-serial` / unchanged regression, all other writers stopped | 39 PASS, 15.106s |
| `guards297` | 47 PASS, 3.802s |
| `spec:doctor`, `spec:trace`, `plan:approved`, `test:plan`, `backend:syntax`, `git diff --check` | PASS |

No skip/xfail conversion. Overlapping runs are not additive coverage. Full
Backend/Frontend suites, per-side 80% coverage, browser/E2E, security and
image/deployment acceptance were not run or waived.

### Intermediate failures retained and explained

1. The new test initially expected `parent_job_id` in the public DTO. That field
   is internal; corrected the test to verify the exact relation in SQL. No public
   schema change, and parent/child/outbox verification remains strict.
2. Importing the same session test fixture in two modules of one invocation
   tried to create the same temporary role twice (`uq_roles_undeleted_name`).
   Separate invocations retain actual role creation and no constraint relaxation.
3. A graph test was still writing notifications while the first CHG-296 run took
   whole-table protected snapshots. Its failed job completed at
   `07:22:15.439744 UTC` for version `6403d5fb-d553-4778-a8eb-ef83690a6922`;
   the failing snapshot contains that exact version's notification. The real
   retry completed at `07:22:16.029873 UTC`. After all writers finished, the
   unchanged 39 tests passed. This was test-run scheduling contamination, not
   evidence to weaken atomicity checks. Future related runs must be serial or
   use separate databases. Audit timestamps are preserved in the evidence JSON.

## Current models and safety-review blocker

Read-only configured Backend inventory verified MAAS selections:

- `nomosmart-chat`, ID `70536f5c-4b5b-4665-93ed-e7e344da919c`, OpenAI
  `gpt-5.6-luna`, config version 2, Responses API.
- `nomosmart-embedding`, ID `4b7eca6c-c2f9-4994-93b0-4feb001a4d50`, OpenAI
  `text-embedding-3-small`, config version 1.

The model settings do not expose a spending-cap field. Peter's existing
provider-side cap is retained, not independently verified through a billing
query. No pricing or limit change was made.

Safety review rejected **startup** of the bounded real-request bridge: the
generic current-model test authorization did not, in that review, sufficiently
identify the data being sent to the external destination. No bridge process or
request receipt exists, and the isolated DB has zero selected-model usage events.
The rejection was not retried through another path. It is unrelated to the
correctly enforced application permission/graph guards.

### Specific outbound scope requiring confirmation

Only this self-authored non-sensitive raw text (versions 1 and 2), its parsed/
normalized representation, document title and built-in tagging instructions:

```markdown
# CHG298 acceptance

版本 1 的驗收說明。申請人須年滿 **18 歲**，並提出身分證明。

1. 提交申請。
2. 管理人員確認文件。
```

The second version changes only `版本 1` to `版本 2`. No existing MAAS document,
user identity, private business content or Provider credential is in the payload.
Destinations: `https://api.openai.com/v1/responses` and
`https://api.openai.com/v1/embeddings`, using the two configured models above.
At most 20 short requests per newly authorized run, request body <=16 KiB,
Chat output <=existing limit (current code default 1,024 when not specified),
unchanged provider-side limits; stop on any Provider error without automatic
retry. Test data and workflow writes stay in fresh disposable services; Provider
keys remain in their existing runtime. No billing API, model setting mutation,
current MAAS reprocessing or deployment is requested.

## Isolation and cleanup

Six fresh real services plus a byte-only internal-network relay; existing images,
fresh credentials/realm and Flyway through V048 on an empty isolated database.
No running Celery worker consumed the test broker queue. Provider bridge startup
was denied. Current Kubernetes access was read-only model/deployment inventory.

Exact cleanup removed **7 run-owned containers, 5 exclusively used anonymous
volumes and 1 internal network**, and stopped relay PID 20503. All 14 preexisting
containers retained their running/stopped state and start time; all images
preserved. Test service data is disposed and cannot be recovered. Private
logs, XML, source copies and redacted evidence remain. A later authorized
continuation needs fresh services, not reuse of removed resources.

Machine-readable source hashes, test outcomes, timing and cleanup receipt:
`docs/CHG-298-VERIFICATION-EVIDENCE.json`.

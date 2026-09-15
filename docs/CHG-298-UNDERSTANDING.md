# CHG-298 — Remaining four acceptance cases: understanding and discussion

2026-09-12. Status: **Gate 1 investigation completed; four-case scope confirmed
by Peter with `允許`; Gate 2 operational decisions and Gate 4 plan approval
pending.** The confirmation does not specify model identities, credential access
or a cost/request limit. Do not infer those values or start Provider execution.
This is an understanding/discussion record, not
an approved development plan. No implementation, feature tests, Provider calls,
image builds, deployment or runtime mutations were performed in this review.

2026-09-12 subsequent decision: Peter selected current configured models and
existing limits and explicitly instructed `請直接執行測試`. The operational model
decision is resolved; DEVELOPMENT_PLAN records direct execution authorization
for the already presented scope. The earlier pending notes below are historical,
not a request for another formulaic approval. No authority to raise limits or
change current application data is inferred.

## 白話結論

2026-09-12 R2：Peter 以 `Ok` 核准明確列出的 CHG298 合成測試文字及貼標指令
送至 `api.openai.com`，沿用上述兩個模型及既有上限，最多 20 次短請求；
不含 MAAS 原文或使用者個資。先前 outbound-data 確認缺口已解決。

CHG-297 留下的是四個尚未通過的長測試，不是四個已確認的產品 Bug。
一項有過時的測試期待；另外三項缺少真正的模型及發布流程證據。
目前結果仍是原十一項 **7 PASS / 4 FAIL**，本次唯讀調查沒有改變測試結果。

## Four cases and intended outcomes

All four node IDs are in `backend/tests/test_live_backend_api_behavior.py`.

| 原編號 / test suffix after `test_live_` | 已確認原因 | 預期完成內容 |
| --- | --- | --- |
| 3 / `seeded_reference_and_approval_workflows` | `submission_evidence_not_ready`：缺 pipeline submission readiness、staging index、graph preview。 | 用真正萃取與模型輸出產生送審證據，再保留原本送審、主管與 Owner 審核的成功及拒絕檢查。 |
| 4 / `external_services_and_domain_adapters` | `canonical_embedding_build_required`：切片經過正規化，但沒有匹配的真正向量建置。 | 真實 Embedding 產生 canonical build，核對 OpenSearch 寫入／讀回；繼續既有 Neo4j、identity、S3、資料同步等後續檢查。 |
| 5 / `integration_adapter_embedding_and_switch_edges` | 同樣缺 canonical build；手填 published 狀態不能證明該版本真正發布過。 | 在隔離環境真正完成兩個版本的萃取、審核及發布，再驗證切回先前版本；保留權限、過期及無效證據的拒絕檢查。 |
| 11 / `compatibility_routes_execute_governed_workflows` | 舊測試對 completed graph job 要求 retry 回 200/completed；實際契約只允許 failed job。 | completed retry 應為 409 且無寫入；另以 failed job、必要 Idempotency-Key 驗證 202 排入、重送不重複及真正圖譜工作執行。 |

## Source findings

- `submission_evidence.py::build_submission_evidence` checks all extraction steps,
  artifacts, source mapping, staging build and generated graph preview. A chat
  record is collected as evidence, but this function does not require a new
  successful chat query when there are no validation runs. Do not add unrelated
  question-answer billing to the scope by assumption.
- `extraction_pipeline.py::_apply_llm_tags` calls Chat for document tags and for
  each chunk's tags. `build_embeddings` calls the actual embedding flow. Required
  call counts therefore depend on chunk count and retry behavior; four test
  cases do not mean four Provider requests.
- The reliable text-layer path can skip OCR without substituting a fake adapter.
  `_parse_document_payload` supports supplied source text and DOCX parsing; a
  file extension alone is not proof that a Markdown upload was parsed. Test
  preparation must document the actual input path and must not claim PDF/OCR or
  upload acceptance that it did not exercise.
- `_seed_live_document_workspace` currently points its model endpoints at
  `127.0.0.1:65535`. These refused endpoints are useful for negative checks, not
  genuine generation. Keep positive preparation separate so configuring real
  models does not turn negative tests into unintended billable requests.
- `review_publish.py::publish_version` uses canonical vectors, writes the actual
  published index and binds the manifest to its build. Positive switching must
  use this workflow, not direct updates to published/readiness fields.
- The broad switch case later invokes global `worker.dispatch_outbox()`. With
  real models this could consume unrelated queued test work. The eventual plan
  must bound workers/queues to exact run-owned work or separate their isolation;
  enabling Provider access for the existing broad setup as-is is unsafe.
- `compatibility.py::retry_graph_sync_job` already implements failed-only retry,
  Owner authorization and durable idempotency. No relaxation of this product
  contract is proposed.

## Boundaries to confirm at Gate 2

- New disposable services, test identities/projects and non-sensitive short
  documents only. Existing MAAS data, permissions, indexes, manifests and current
  model configuration remain untouched. No image build or deployment.
- Real configured Chat and Embedding models are required for the three positive
  flows. Human confirmation must identify the allowed models, the authorized
  credential/configuration mechanism and a cost/request limit before use.
  Do not infer permission to extract current Kubernetes/DB secrets for another
  environment. No keys or document content in general logs or committed files.
- Any permitted publication, version switch, graph failure/retry and cleanup
  apply only to exact run-owned disposable resources. Existing environment
  resources are excluded. Prior CHG-297 test services have already been removed.
- Preserve all downstream assertions and negative guards. Do not use fixed
  vectors, fake responses, manually completed processing or widened accepted
  status codes as positive acceptance evidence. Newly exposed product defects
  require specification discussion before expanding the repair scope.

## Pending human decisions

1. Confirmed by Peter on 2026-09-12 with `允許`: this four-case scope as CHG-298,
   including genuine isolated processing, review, publication and version-switch
   acceptance. This is scope confirmation, not detailed-plan approval.
2. Which Chat and Embedding models may the isolated tests use, through which
   already-authorized configuration, and what is the maximum allowed cost?

After confirmation, record the specification/test impact and submit the detailed
development and verification plan for Gate 4 approval. Until then the previous
four failures, full-suite/coverage gaps and deployment status remain unchanged.

References: `docs/CHG-297-VERIFICATION.md`, specification §10.53 / §10.54,
`TEST-002`, `ACCEPT-REPAIR-002` and the existing failed-only graph retry contract.

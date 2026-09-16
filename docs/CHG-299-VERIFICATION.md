# CHG-299 S3 同步／手動萃取分離：驗證紀錄

日期：2026-09-12。核准：Peter 先確認修正方向，再以「同意」核准
DEVELOPMENT_PLAN.md 的 CHG-299 計畫。對應 SPECIFICATION.md §6.4、§10.56，
DSYNC-MANUAL-001..003。

## 結果與根因

程式已修正，未部署。S3 同步應保存來源並停在「待萃取」，不是自動執行 OCR。
舊程式先將版本設為 `ready_for_extraction`，隨即呼叫
`queue_document_extraction`，因版本未選 OCR 而得到 `ocr_model_required`；
整次來源保存也跟著回復。現在移除這個不應存在的呼叫，沒有預塞模型或放寬驗證。

新流程：S3 真實取檔 → 驗證內容 → 保存快照／指紋／版本 → 同步成功、待萃取。
使用者明確啟動萃取時，才檢查 OCR、權限、來源、工作互斥並建立工作。
未變更仍為 `unchanged`；內容更新建立下一個 major version，不替換 Active 綁定。

## 實際改動

| 檔案 | CHG-299 改動 |
| --- | --- |
| backend/app/domain/data_sync.py | 移除同步成功路徑的自動萃取 enqueue／unused import；時間變數改名 synced_at；其餘來源保存、補償、audit 保留 |
| backend/tests/test_chg299_s3_manual_extraction.py | 28 項真實服務及 Cron 純計算回歸 |
| backend/tests/test_live_backend_api_behavior.py | 將原第 4 項 S3 段落抽為 `_assert_live_s3_sync_contract`，原測試仍呼叫它 |
| SPECIFICATION.md、SPEC_CHANGELOG.md、DEVELOPMENT_PLAN.md、TEST_PLAN.md、TRACEABILITY.md | 需求、核准、測試及結果追溯 |

比對 CHG-298 R2 的 164 個來源雜湊，只有 data_sync.py 與原廣域測試檔改變，
其餘 162 個保持原狀；另外新增 CHG-299 測試。原第 4 項重新內嵌 helper 後
AST 完全相同，39 個 assertion 全數保留。沒有改動手動萃取 domain/API、
其他待提交修正、UI、API schema、migration、索引、設定或依賴。

## 測試與命令

使用獨立 `/tmp/chg299-live.IP4kuZ/source` 副本，不複製 repository `.env`。
全新真實 PostgreSQL、RustFS/S3、Keycloak/OIDC、Redis、OpenSearch、Neo4j；
內部 Docker 網路及 loopback byte relay，不替換回應，不使用 mocks/stubs。
僅使用已安裝映像；全新測試資料庫執行既有 migrations 到 V048，未執行 V049。

核准資源上限八個容器、八 CPU、12 GiB；實際七個長駐測試容器，migration
期間短暫第八個，合計容器 memory limit 不超過 6.7 GiB。

下表為最終有效結果，合計 116 個不同案例，來自分開的 invocation，不是完整 suite：

| 命令目標（pytest） | 數量 | 結果 | 證據 |
| --- | ---: | --- | --- |
| tests/test_chg299_s3_manual_extraction.py | 28 | PASS | audited-focused.xml |
| tests/test_chg296_cursor_and_switch_guards.py | 39 | PASS | guards296.xml |
| tests/test_chg297_sync_graph_idempotency.py | 47 | PASS，最終單獨重跑 | serial-guards297.xml |
| tests/test_chg298_graph_retry.py | 1 | PASS | graph298.xml |
| tests/test_live_backend_api_behavior.py::test_live_configuration_identity_worker_and_sync_edges | 1 | PASS，最終單獨重跑 | serial-config.xml |

實際執行入口：

```sh
backend/.venv/bin/python -B /tmp/chg299-live.IP4kuZ/run_capture.py audited-focused \
  tests/test_chg299_s3_manual_extraction.py \
  --cov=app.domain.data_sync --cov-branch --cov-append --cov-report=term-missing \
  --cov-report=json:/tmp/chg299-live.IP4kuZ/coverage-final.json
backend/.venv/bin/python -B /tmp/chg299-live.IP4kuZ/run_capture.py guards296 \
  tests/test_chg296_cursor_and_switch_guards.py
backend/.venv/bin/python -B /tmp/chg299-live.IP4kuZ/run_capture.py serial-guards297 \
  tests/test_chg297_sync_graph_idempotency.py
backend/.venv/bin/python -B /tmp/chg299-live.IP4kuZ/run_capture.py graph298 \
  tests/test_chg298_graph_retry.py
backend/.venv/bin/python -B /tmp/chg299-live.IP4kuZ/run_capture.py serial-config \
  tests/test_live_backend_api_behavior.py::test_live_configuration_identity_worker_and_sync_edges
```

run_capture 使用私有環境設定、實際新建 realm、`pytest -o addopts= -p no:cacheprovider
--tb=short -q` 及 JUnit；沒有改變 coverage 的 80% 門檻。測試 stack 已於驗收後清除，
重跑須依核准的隔離程序重新建立真實服務，不能直接使用現行 MAAS。

主要驗證內容：

- Owner／Editor 首次同步使用 API 建立的 placeholder，未選 OCR 也能成功。
- 實際讀回 S3 bytes、SHA-256；重送、未變更不新增快照／版本；更新保留舊快照與 Active 綁定。
- 同步前後整筆 SQL 資料比較，沒有新增 Pipeline／steps／extraction outbox／usage／chunk／vector／graph job。
- 缺檔、空檔、非法 UTF-8／PDF、損壞或不完整來源設定安全失敗。
- S3 實際接受過長 MIME metadata，PostgreSQL 既有 varchar(255) 真正拒絕寫入；
  首次及更新兩種情境都補償掉本次新快照，原版本與舊快照不動。沒有注入例外或新增 DDL。
- 手動萃取缺少／錯誤 OCR、Viewer、非待萃取版本、缺少來源、重複操作均維持拒絕；
  Owner／Editor 明確選擇測試資料庫中的 local OCR 設定後，只排入一個真正工作與 outbox。
- 手動 enqueue 僅驗證入列契約，未啟動 OCR，也不冒充模型執行或完整萃取成功。
- 真實 encrypted credential 的既有 context 相容性、Cron range/list/Sunday／不可能日期、
  排程 generation、過期工作取消及成功／失敗 audit 保留。

Active 綁定測試使用明確標記的 SQL preservation input（staged build、index_ready=false），
只驗證同步不修改該資料，不宣稱這是有效發布或真實向量生成的結果。

## 覆蓋率與中途紀錄

`data_sync.py` 的合併 statement/branch coverage 最終 **80.00%**：362 statements、
108 branches，376/470 covered opportunities。資料由 focused、CHG-297、既有
configuration/sync case 串接蒐集；不是 whole-backend 或 frontend 的覆蓋率。
未執行的 adapter 分支、注入 adapter 路徑等仍列在 coverage-final.json，未加排除標記。

保留的中途結果，不覆寫成成功：

1. 初次 focused：8 PASS／9 FAIL。新測試誤用 object-only signer 簽帶 query 的
   ListObjectsV2。改以同一帳密與權限的 ListObjectsV1；未改產品 signer、ACL 或權限。
2. 17 項功能斷言全通過，但 coverage 63.83% 導致命令 exit 1；加入既有回歸後
   74.89%，仍 exit 1。補齊來源設定／加密相容性／Cron 邊界後，門檻80%通過。
3. 僅將隔離副本換回舊 data_sync.py：Owner／Editor 首次同步兩項都如預期因
   `ocr_model_required` 失敗。隨後恢復修正版，沒有對 repository 做 reset。
4. 一次 CHG-297 重跑與尚未結束的 graph retry 意外重疊，雖47項通過，不採為
   最終串行證據；兩者結束後重新單獨執行，serial-guards297.xml 47項通過。
5. 沿用 Starlette TestClient 的既有 deprecation warning，未在此範圍改依賴。

Harness：`spec:doctor`、`spec:trace`、`plan:approved`（含 plan:doctor）、
`test:plan`、`backend:syntax`、`git diff --check` 通過。

## 邊界與尚未驗收項目

- 零 Provider 呼叫；測試資料庫 model usage rows=0。沒有 Provider bridge 或現行模型金鑰。
- 所有 CHG-299 手動萃取工作保持 queued、started_at=NULL；對應 outbox 未 dispatch。
  SQL 中 failed／queued sync rows 含負向測試、舊程式重現及防護輸入，不代表產品新增故障。
- 原完整第4項需真正模型處理／發布的前置，本次未重跑；只獨立驗證保留的 S3 段落。
  不宣稱「原11項已完整重跑全過」。
- FTP／FTPS／SFTP／HTTP 的完整正向協定整合未測；共用成功路徑改變符合原契約，
  但不能把 S3 PASS 推論為所有 adapter 已驗收。
- 全部 frontend/backend coverage、完整 E2E、映像安全掃描、Compose／Helm部署
  與現場驗收仍為後續 release gates。此變更不含映像建置／部署。
- 現行失敗同步工作沒有重試／修補。修正版部署後，仍須另行授權或由使用者操作重試。

## 資源清理

精確清理與既有容器／映像保護結果見同目錄 CHG-299-VERIFICATION-EVIDENCE.json。
清理只針對本次核准建立、依 ID／label／獨占 volume 關係核對的測試資源。
已停止本次 relay，移除 7 個測試容器、5 個獨占匿名 volume、1 個 internal network。
清理前後核對 14 個既有容器的 ID、running/stopped 與 StartedAt 完全一致；
既有映像均保留，沒有刪除映像。被清除的只有可重新建立的測試資料，未保留測試 DB 備份。
私有 journal、來源副本及測試報告保留於 /tmp/chg299-live.IP4kuZ，未將測試密碼寫入 repository。

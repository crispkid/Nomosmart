# CHG-293 部署前相容性唯讀盤點

日期：2026-09-10。依據：SPECIFICATION.md 10.50 / CHAT-COMPAT-001、PROJECT-014。

## 範圍與授權

Peter 在前一輪交付提出「部署前唯讀盤點」後回覆「下一步」，本輪僅執行該範圍。
原 CHG-293 repository 實作核准不擴張為建置、部署或資料修復核准。

- 確認 docker-desktop / nomosmart / nomosmart-local 的 release、映像和健康摘要。
- 使用現有 Backend 正常配置的 PostgreSQL 連線，強制 READ ONLY、REPEATABLE READ，
  限制查詢時間及資料量；檢查 conversation ID、creator、surface、固定版本集合、
  刪除／legacy 狀態及建立者存在／啟用／姓名是否可用，不輸出問答全文或使用者 profile。
- 盤點 Project Owner／member rows、canonical role、有效本地角色 Menu view 與
  Editor+archive execute 組合；不更改 role、membership 或套用 V049。
- 確認既有 nullable heading_path 與 replacement 外鍵約束；只檢查 schema，不做 DDL。
- 本機保存安全統計、metadata digest 與差異報告；不是完整資料備份或完整保護基線。

停止條件：權限不足、release 漂移、識別／範圍歧義或健康失敗。即使發現問題也不擅自
修復或放寬 fail-closed 規則；先回報影響。正常舊 Editor+Viewer precedence 不視為
可自動清理的授權。盤點時點不代替正式部署前重新確認。

不建置映像、dry-run、Helm write、Kubernetes mutation、Job、bootstrap、migration、
graph/index repair、reprocess、re-embed、reindex、manifest switch、Provider 或權限寫入。
完整 coverage／全流程 E2E／release 門檻保留，不能將本次盤點當作通過或風險豁免。

## 執行結果

**本次限定相容性盤點未發現需要先修復的 identity 衝突；不代表 release 已通過。**
兩次 SQL 快照為 2026-09-10 02:36:41、02:37:30（Asia/Taipei），安全原始結果見
`CHG-293-READONLY-INVENTORY-EVIDENCE.json`。產品程式與 SPECIFICATION.md 未修改。

| 項目 | 實際結果／影響 |
| --- | --- |
| Release | 前後均為 revision 36 / deployed。Backend、Frontend CHG-292；Migration CHG-288；schemaContract forward-v047。 |
| 健康 | 15 個 Running Pods 均 Ready；四個 application Pod restart=0，兩次觀察無新增 restart。三個 trusted HTTPS GET（login、health、ready）均 200。 |
| 歷史總數 | 11 個 ChatRecords＝11 輪，分成 2 個 document_staging conversations；目前均同一位實際 creator，各自固定不同文件版本。沒有 published 或 public API 歷史。 |
| 歸屬／範圍 | 沒有跨 Project、creator、surface、固定版本集合衝突；沒有未分類、缺失／失效 creator、缺姓名或已刪除 conversation identity。 |
| 未刪除文件 | 4 輪歷史，版本 ce1c4c6a-ff64-4dfb-9535-fb8c608e8f65。依新程式 scope 規則，符合授權的成員可讀取；他人不可續問。這是 metadata/code 相容性判讀，尚未在 live 部署新版 API 驗收。 |
| 已刪除文件 | 另外 7 輪仍保留在資料庫，版本 98050420-1be2-401c-9209-53ab271681b8 的文件已 soft-delete。既有 document scope guard 會拒絕存取，不因 CHG-293 重新公開／復原／搬移。不是 identity 歧義。 |
| user02 | 唯一符合既有帳號識別的 active User；本地有效角色具有 Menu.KnowledgeProjects.view。Project 原始 rows 為 Editor＋Viewer，依既有 precedence 得 Editor，沒有 Owner 關係，沒有 archive execute grant。 |
| Owner／角色 | 1 Owner、3 member rows／2 人；唯一的 Editor＋Viewer overlap 保留。Editor+archive execute 組合為 0；Owner 原有 execute grant 保留。 |
| Schema | 48 筆成功 Flyway 紀錄、V049=0；heading_path 為 nullable JSONB，NULL-or-array CHECK 與 superseded_by self-FK 都已 validated。38 Chunks 中 27 SQL NULL、11 array、0 JSON null；本次兩項 ORM/flush 修正不需 DDL／回填。 |
| 其他限定統計 | 84 usage events、0 public API request logs、0 active manifests；34 outbox 全為 dispatched。沒有據此宣稱所有 queue／worker 全部無工作。 |

### 讀取與保護證據

- 使用現有 Backend Pod `nomosmart-local-backend-84d697f6b6-mzqgj`，UID
  `f2af07b3-2deb-4cda-bd8a-c496caf5fd97` 的正常 DATABASE_URL 配置；未另取憑證。
- `transaction_read_only=on`、`repeatable read`、statement timeout 10s、lock timeout 1s，
  單類 metadata 上限 10,000；交易最後 rollback。只 SELECT metadata／聚合／schema。
- 不 import application entrypoint、不呼叫 bootstrap、不安裝或複製程式到 Pod，
  診斷程式經 stdin 執行且 PYTHONDONTWRITEBYTECODE=1。
- 兩次 chat、user flags、member、owner、project、version、effective-grant metadata
  SHA-256 全部一致；counts、約束及 migration 摘要亦相同。
- Chat metadata SHA-256：`0512c71a287c2a0283e7abc4a9c6187526efa73dca55e9868751ee5103e601fc`。
- 診斷程式：`/tmp/chg293-readonly.rl5RIj/inventory.py`；SHA-256
  `671eaaa5ea03751b9908d3785b27e92a8d867e58d364e37aad0777f846976d33`。
  依據的四份 repository policy/serving 程式 SHA-256 另記於 JSON 證據；沒有套用到 live。

### 限制與下一步

- metadata/count 相同不是完整內容／Secrets／PVC／圖譜／索引保護基線；本次未盤點
  這些額外範圍，也未執行新版本 authenticated API/UI 或 Provider 驗收。
- HTTP GET 各約 5.05–5.16 秒，雖回 200，未分解 DNS／network／application latency；
  單輪通過不是持續可用性或效能驗收。支援服務原有重啟計數保持原狀，沒有修復。
- 完整 Frontend／Backend 80% coverage、全流程 E2E 與 production release 缺口仍開放；
  本次沒有風險豁免，不能宣稱部署條件全部完成。
- 下一個可單獨核准的 preparation scope：建置 `nomosmart/backend:0.1.0-chg293`
  與 `nomosmart/frontend:0.1.0-chg293`、隔離 image smoke、掃描／SBOM（若工具可用）、
  驗證仍為 revision 36 後，使用 reuse-values 僅覆寫 Backend／Frontend tags，
  進行 revision 37 hidden-Secret server-side dry-run，產出 canonical render SHA-256
  與兩個 image IDs。保留 Migration CHG-288、forward-v047，不建置 Migration、不套 V049。
  **此 preparation scope 尚未核准／執行**；不包含 Helm write、Job、目前資料／權限修改，
  亦不包含 Provider、graph/index 修復、重建或 manifest switch。漂移即停止。
- 即使 preparation 通過，實際部署仍需另行更新完整保護基線、明列 bootstrap 必要
  operational writes 與 rollback／維護窗口；不得沿用舊 revision-36 核准當作新授權。

## 治理檢查

以下命令均 PASS：`./HARNESS/harness.sh spec:doctor`、`spec:trace`（六項映射）、
`plan:approved`、`test:plan` 及 `git diff --check`。`plan:approved` 驗證的是既有
CHG-293 repository 開發核准，不是尚未核准的 image preparation 或部署。
JSON comparison 四項均 true；證據檔 SHA-256：
`e3645f700f3f581765e1be0a22c13531ee4ed7360a78edb936349b301e94314b`。
本輪只增加唯讀盤點／治理證據，沒有重新宣稱產品或 coverage 測試通過。

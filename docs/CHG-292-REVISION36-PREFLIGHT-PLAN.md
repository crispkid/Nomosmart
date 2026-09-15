# CHG-292 revision 36 部署前檢查計畫

日期：2026-09-09。狀態：**唯讀檢查已核准；實際部署仍未核准**。
Peter 核准原文：「核准 CHG-292 revision 36 部署前唯讀保護基線盤點與回退風險檢查，
依上述檢查計畫執行；不授權實際部署、Job 建立、資料修改、圖譜修復或 Provider 呼叫。」
依據：SPECIFICATION.md 10.49 / GRAPH-009..013、DEVELOPMENT_PLAN.md CHG-292。
本步不修改產品規格、程式、測試門檻或 CHG-291 V049 的獨立核准範圍。

執行結果見 `CHG-292-REVISION36-PREFLIGHT-RESULT.md`：保護基線比對穩定，
但現有 HTTPS/readiness 健康驗收失敗；實際部署維持暫停，沒有擅自修復。

後續 Peter 已另行指示先恢復健康；有限環境修復與 12 輪驗收已完成，見
`CHG-292-ENVIRONMENT-HEALTH-RECOVERY.md`。這不將本唯讀計畫擴張為部署授權。

## 已完成與下一步

Backend／Frontend CHG-292 映像、隔離 smoke tests 及兩次 hidden-Secret server-side
dry-run 已完成；見 `CHG-292-REVISION36-BUILD-DRYRUN.md`。最後觀察為 revision 35。
下一步先取得目前保護基線並核對回退條件，再提交獨立、綁定雜湊的實際部署核准。
不得將舊 MAAS 範圍盤點或 Helm values digest 當成完整保護基線。

固定候選產物：

- renderSha256：`fad6bb97fcaeadbccfd90d8b32a3a4a41e578be2ba37a776be7a78f278b32b67`
- Backend `nomosmart/backend:0.1.0-chg292`：
  `sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1`
- Frontend `nomosmart/frontend:0.1.0-chg292`：
  `sha256:82df26d3807ebc3904826135ae61f10aaf3a6a2a6a5464d2d822638a7935bbd9`
- 保留 Migration `nomosmart/migrations:0.1.0-chg288`、`forward-v047`；不套用 V049。

## 已核准的唯讀範圍

1. 核對 docker-desktop / nomosmart / nomosmart-local revision 35、image IDs、
   effective values、現有 Jobs、四個 application Deployments 與 supporting workloads。
   如需重做 render，仍限 `--dry-run=server --hide-secret`；必須符合上列 hash。
2. 取得此 release 的 PVC/PV UID 與綁定摘要、受保護 Secret UID/data digest、
   Ingress UID/allowlist、相關身分與支援服務的安全配置摘要。Secret 僅於記憶體計算
   digest，不輸出或另存 Secret 明文，不擷取憑證以供其他用途。
3. 使用既有正常配置的服務客戶端執行 PostgreSQL read-only transaction、Neo4j
   read transaction 與 OpenSearch read request。盤點 migration history、業務資料
   計數/安全摘要、模型/權限/成員、Embedding/manifest、索引 identity/count 及
   MAAS canonical/Neo4j scope digest。不輸出文件全文、標籤全文或個資清單。
4. 檢查 graph/outbox/processing 待處理或執行中工作及正式版本狀態，評估新舊 writer
   混用期間的風險；發現有衝突的工作即停止，不擅自清除、暫停或重送。
5. 對照 migration-36/bootstrap-36 的既有行為，列出實際部署會新增的 operational
   evidence/audit/sync 紀錄與可能觸及的服務設定，供下一份部署核准精確界定。

允許本機安全摘要報告；不建立備份或匯出完整業務資料。未取得必要權限即停止，
不切換到額外憑證。盤點只是一個時間點的證據，實際部署前仍必須重驗漂移。

## 已查明的 bootstrap 與 rollback 風險

- `bootstrap-job.yaml` 使用 `python -m app.deployment.bootstrap --mode ensure`。
- `run_bootstrap` 會 ensure OpenSearch/Neo4j runtime identity，可能建立 bucket；
  OpenSearch ensure 明確使用安全管理 API PUT，不是唯讀健康檢查。
- Keycloak manage/verify 路徑都會呼叫 `_reconcile_identity_database`，寫入
  identity sync/audit 紀錄，且可能隨來源差異更新使用者、群組或角色衍生資料。
- `_record_bootstrap_evidence` 會為新的 release 寫入部署證據。
- 因此本次唯讀檢查不得執行 bootstrap ensure/verify，不能將未改變的 Job template
  等同於「完全沒有資料寫入」。實際部署核准需明確區分必要 operational 紀錄與
  必須保持不變的業務資料／身分設定；如 scope 無法兼容，先回報，不暗中改 Job。
- Revision 35 與 CHG-292 的資料庫 schema 相容，不代表 graph writer 契約相容。
  舊版可能重寫候選圖或遺失 tag 關係。沒有待處理 graph 工作也不能保證未來不會
  有新請求；部署窗口的使用者操作限制／必要隔離須明確核准，不能暗中 scale。
- 若已產生新正式 graph evidence，不得宣稱無條件 rollback 到舊 writer 安全；
  必須另提保持新圖譜證據的恢復策略。Helm rollback 本身不會回復外部資料庫副作用。

## 停止條件及交付

Revision、產物、配置漂移；權限不足；身分／資源不明；活動寫入影響比較；新正式
graph 狀態或舊 writer 回退不相容時停止。不自動部署另一個 revision，不修復差異。
完成後交付安全基線、Job 寫入邊界、回退條件、尚缺的驗收及精確部署核准文字。

實際部署、Job 建立、服務身分變更、SQL/Neo4j DDL、V049、graph repair、
reprocess/re-embed/reindex、manifest switch、正式發布及 Provider 呼叫均不在本步。
全庫 coverage、完整 live suite、authenticated Browser 及新 image scan/SBOM 的
現有缺口維持公開；本步不將它們標記通過或豁免。

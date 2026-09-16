# CHG-292 revision 36 唯讀部署前盤點結果

後續更新（2026-09-09 22:40 Asia/Taipei）：Peter 另行要求先恢復環境健康後，
已完成既有 HTTPS 代理／kindnet 的有限修復及 12 輪健康驗收，保護基線一致。
詳見 `CHG-292-ENVIRONMENT-HEALTH-RECOVERY.md`。以下保留原唯讀盤點時的失敗
事實；revision 36 實際部署仍未核准／執行。

日期：2026-09-09（Asia/Taipei）。範圍依 Peter 本次明確核准與
`CHG-292-REVISION36-PREFLIGHT-PLAN.md`。規格 10.49 / GRAPH-009..013 不變。

## 結論：保護基線穩定，但健康驗收未通過，暫停部署

已完成目前保護基線與回退風險盤點；**不可將本結果當成 revision 36 部署核准**。
沒有執行 Helm write、Kubernetes mutation、Job 建立、bootstrap、Migration、圖譜
修復、資料修改、Provider 呼叫、reprocess/re-embed/reindex 或 manifest switch。

最後健康檢查發現：

- 主機 `https://nomosmart.local/login` 兩次 curl 均 exit 35：
  `Recv failure: Connection reset by peer`，HTTP code `000`，未停用 TLS 驗證。
- 既有 Backend Pod loopback `http://127.0.0.1:8000/api/v1/ready` 在 20 秒內
  沒有回應（`httpx.ReadTimeout`）。
- 同 Pod `/api/v1/health` 回應 HTTP 200 / healthy。Kubernetes 當時仍顯示 1/1
  Ready；Pod UID 未變，3 次重啟中的最近一次在約 22 小時前，非本次造成的新重啟。
- 現有 readiness/liveness probe 分別指向上述端點，timeout 5 秒、period 20 秒、
  failureThreshold 6。因此一次狀態清單上的 Ready 不等同本次端到端健康驗收通過。

尚未定位 HTTPS 與 readiness 異常的根因，也不能據此認定是 CNI、Ingress、資料庫
或 CHG-292 程式問題。CHG-292 尚未部署，現有工作負載仍為 CHG-291。
本次未擅自重啟 Pod、修改網路、放寬 TLS／allowlist 或更動代理設定。

## 安全證據

完整安全摘要：`CHG-292-REVISION36-PREFLIGHT-EVIDENCE.json`。
該檔案 SHA-256：

`9040ccad82dc16000148d050699219c000ac9f52c63aecf8615a5e9cb6ff1dec`

僅含 IDs、筆數、狀態與摘要，不含 Secret 明文、文件全文、標籤全文、使用者姓名／
Email 或模型憑證。這不是資料備份，也不是原始物件／向量全文匯出。

### Kubernetes / Docker

- `docker-desktop` / `nomosmart` / `nomosmart-local`：revision **35 / deployed**。
- 四個 app Deployments 原有 main/init image 均保持 CHG-291；Keycloak、Neo4j、
  OpenSearch、PostgreSQL、RustFS、Redis HA/Sentinel 均保持原有 spec 與 Ready 數量。
- 7 組 PVC/PV 都是 Bound，claim UID 對應正確。本文所用（含 spec digest 的）
  canonical binding SHA-256：`55080d5ad353b80a91655dd05c0fdbc257b153a8b59032749431aac469e5531e`。
- 主受保護 Secret `nomosmart-local-secrets`：
  UID `1c97c03f-a53e-4bae-9ad5-c1c22d9aecca`；本次 data SHA-256
  `c5882876a22837d3bd197de252039296784dea00a4ad400aa0d435d23cc1587f`。
  此 digest 定義為 Kubernetes base64 `data` map 的 sorted compact JSON SHA-256，
  不直接與歷次其他序列化算法的摘要比較。另記錄 4 個 runtime 引用 TLS/CA Secrets。
- 兩個 Ingress UID 維持 `ca265ba3-b664-4dd7-ac66-fe50962dfdb2`、
  `fafc437c-9685-4e2f-ba12-59991ef496fa`；allowlist 都是
  `127.0.0.1/32,10.244.0.0/16`。
- 所有既有 audit Jobs 保留，含舊 revision-5 失敗紀錄；沒有活動 Job，也沒有
  migration-36/bootstrap-36。沒有清理歷史失敗 Job。
- 受盤點的 workload/Secret/PVC/PV/Ingress/ConfigMap/Job 摘要前後相同：
  `3663917ffdeb0337847683471c5aaaf8d9b55b6ed77ab791e4f41c45a936f505`。
- OpenLDAP/phpLDAPadmin Docker 容器當時 healthy，兩個既有 LDAP named volumes、
  掛載與設定 identity 已記錄；不讀取卷內檔案，也不建立／重建容器。

### PostgreSQL / identity

交易使用 `default_transaction_read_only=on`、`REPEATABLE READ, READ ONLY`、
15 秒 statement timeout，結束 rollback。沒有呼叫會寫入的 reconciliation。
有效完整資料快照是 **02:59:06 與 03:02:30**（台北時間）。

| 項目 | 現況 |
| --- | --- |
| Flyway | 001–048 共 48 筆成功；沒有 V049；結構仍為 V047 + V048 data-only migration |
| Project / Document / Version | 1 / 3 / 3 |
| Chunk | 38 total / 37 status-active（不代表都屬於有效正式文件） |
| ChatRecord / usage event | 11 / 84 |
| Model | 5 total / 4 undeleted |
| Embedding Build / vector | 5 / 113 |
| Published Version / active manifest | 0 / 0 |
| 使用者 / 外部群組 | 8 active / 8 active |
| Project Owner / member | 1 Owner；3 member rows、2 人，角色列 owner/editor/viewer 各 1 |
| 本地角色 / role-user / group mapping | 2 / 3 / 1 |
| canonical Tag / 文件標籤關係 / 切片標籤關係 | 115 / 16 / 164（含已刪除切片關係） |

59 張盤點資料表的筆數與 full-row digest 前後全部相同：

- table inventory SHA-256：`9dd711fbc65901f6869dccadde63b9ba77c33b4549ea6fa41456bea6eff94364`
- business subset SHA-256：`2f558246ff5c7251c36ba7cde7702550f34a6ad4dc5e6d17c90fd308e5d3b4c4`

每表使用 PostgreSQL `to_jsonb(row)` 的 MD5，再將 row digests 排序串接取 MD5；
僅在資料庫內處理原始內容。MD5 是本次差異偵測器，不宣稱抗惡意竄改的完整性證明。
這些快照早於最後 HTTP 健康檢查，不是對任意未來時間的資料不變保證。

Keycloak 以正常配置的 service-account 取得短期 token 後僅執行 Admin GET。
來源 8 人、8 群組、10 個使用者群組關聯，與 PostgreSQL 的業務欄位及衍生角色
關聯相符：**預期新增／移除／業務欄位差異為 0**。未輸出身分明文；realm、
clients、LDAP provider 與 13 個 mapper 的設定 digest 已留存。

### Background work / graph / indexes

- graph jobs 3 completed；沒有 queued/running graph job。
- outbox 33 dispatched 是歷史送出紀錄，不是 pending/dispatching 工作。
- pipeline 1 failed、2 submission_ready；23 pending steps 分屬失敗流程的後續
  13 步，以及尚未啟動的審核／發布 10 步，沒有執行中的 pipeline step。
- Redis 初次看到短暫佇列，後續確實辨識到週期性的 `app.worker.dispatch_outbox`；
  不將它誤報為圖譜工作。最後 queues（優先級 0/3/6/9）、unacked 均為 0。
  沒有對佇列執行 ack、刪除、重送或 Celery control broadcast。
- 無 DataConnection 排程；identity cron 為台北時間每日 02:00。
- Neo4j 110 nodes / 143 relationships，包括 81 Tag、107 CHUNK_HAS_TAG、
  8 VERSION_HAS_TAG。沒有 schema constraints，只有兩個既有 LOOKUP indexes；
  本次未建立 DDL，不能聲稱已有資料庫唯一約束保護。
- MAAS 兩次 canonical／Neo4j scope digests 相同，亦與上一份唯讀盤點吻合。
  已有 Neo4j graph 屬於未發布且已刪除文件；正式補同步合格 scope 仍為空。
  不發布候選、不復活舊文件、不清除 legacy graph。
- OpenSearch 兩個既有 index UUID 與 `_count` 保持
  `y9N0ThJdQlyujWvz344KxA` = 26、`41mhbFFZSAqe6HcomzDrDQ` = 11；
  mapping/settings/aliases/sequence-number 摘要前後相同，health 當時為 yellow。

## 產物與 render

Source HEAD `bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3` 不變。沒有重新建置映像。
兩次再次 hidden-Secret server dry-run 均為 revision 36、96,181 canonical bytes：

- render SHA-256：`fad6bb97fcaeadbccfd90d8b32a3a4a41e578be2ba37a776be7a78f278b32b67`
- Backend CHG-292：`sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1`
- Frontend CHG-292：`sha256:82df26d3807ebc3904826135ae61f10aaf3a6a2a6a5464d2d822638a7935bbd9`
- 保留 Migration CHG-288：`sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab`

非 Secret render 只包含已批准的 app image／release annotation 與 Job revision 變化。
該 dry-run 成功不代表最後 HTTP 健康檢查成功。

## 既有 Jobs 的真正寫入範圍

| 元件 | 實際行為與未來核准要求 |
| --- | --- |
| migration-36 | 保留 CHG-288 / 048；現有 001–048 已套用，預期無新 migration。不得順帶 V049 或 repair/checksum 修改。 |
| bootstrap evidence | 新增 `nomosmart-local-36` 的部署證據；重試冪等。 |
| identity sync / audit | 成功一次會增加 deployment identity-sync run 與 audit；重試可能多於一次，不能未驗證就承諾 exactly one。 |
| users / external_groups | 即使業務內容一致，也更新 `last_synced_at` / `updated_at`。 |
| 衍生成員 | 重建 10 個 external_group_users、1 個 external_sync role-user、1 個 break_glass role-user；關聯集合須不變，但 created/updated timestamps 會變。人工 role-user、Project member/Owner 不應改變。 |
| OpenSearch / Neo4j | OpenSearch ensure 會 PUT 既有 runtime user/role/mapping；同密碼寫入仍可能改變內部 password hash。Neo4j 會檢查或必要時建立／修正 runtime user。不可稱為唯讀。 |
| Keycloak / S3 | manage 會 ensure realm/flow/clients/mapper/break-glass 等；S3 ensure 可能建立缺少 bucket。若預檢發現缺少資源或設定不同，先停止，不能擴大成修復身分／建立資料資源的授權。 |

以上是本地程式查核的預期副作用，**本次均未執行**。資料來源相符只證明該時間點
沒有預期業務差異，不能保證之後來源不會改變。仍需獨立核准必要 operational 寫入，
並明確保護業務內容、權限及關聯集合，而不是籠統承諾所有資料列 bytes 完全不變。

## 回退與下一步

1. **先處理現有 revision 35 的 HTTPS／readiness 健康異常。** 本報告只記錄現象，
   未核准也未執行修復。恢復並重新通過健康檢查前，不建議核准 revision 36 寫入。
2. 恢復後重驗上述 baseline/image/render，明確約定部署窗口不做文件／標籤／發布／
   成員操作或 Provider 查詢，且沒有業務工作在排隊／執行。必要的強制寫入隔離
   （scale、Ingress 或功能開關）必須另外核准，不能暗中實施。
3. 精確部署範圍仍是 Backend/Worker/Beat main+init、Frontend readiness init、
   bootstrap 升級 CHG-292；Frontend main 升級 CHG-292；Migration CHG-288 不變，
   只新增 migration-36/bootstrap-36 並保留歷史 audit Jobs。未核准實際執行。
4. 若無 CHG-292 graph/business 寫入，且來源/圖譜 digest 維持原樣，才可評估
   CHG-291 的有限回退；這仍會恢復舊 writer 的已知行為。新正式 graph evidence
   一旦產生，不得無條件退回舊 writer。Helm rollback 不會撤銷外部 DB/identity
   副作用，不能當作跨服務交易；需要保留新證據的恢復方案並另行核准。
5. 完整 coverage、broad Backend、authenticated Browser、新映像 scan/SBOM 的
   既有缺口仍未通過，不將此地方環境盤點冒充正式 release acceptance。

本輪只有計畫／證據文件與 `/tmp` 唯讀盤點程式變更，沒有產品程式變更。
盤點程式初版曾將歷史 dispatched/pending 步驟過度分類為活動工作、將 `048`
誤比對為 `48`，以及使用錯誤欄位 `role`；均先停止、查核實際契約後修正並重跑。
SQL 錯誤交易已 rollback，這些不是正式系統失敗或 migration 缺失。

治理驗證：`spec:doctor`、`spec:trace`、`plan:approved`、`git diff --check`。
沒有重跑產品 feature tests；原先測試／coverage 結果見 CHG-292 verification report。

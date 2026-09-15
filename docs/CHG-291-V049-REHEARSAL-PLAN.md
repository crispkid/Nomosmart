# CHG-291 V049 隔離演練與後續備份計畫

日期：2026-09-12。狀態：Peter 已回覆後續 `Ok` 核准本計畫第一關（Gate 4）。

## 目的與已確認理解

Peter 在唯讀盤點後回覆 `Ok`，確認繼續處理 V049 的備份還原與相容性風險。
這不是現行資料庫備份、Migration apply 或部署授權。本次先提出可獨立核准的
隔離演練計畫；執行前仍須取得本計畫的明確核准。

現行環境上次盤點為 docker-desktop / nomosmart / nomosmart-local revision36、
Flyway V048。MAAS/user01 保留 Owner；MAAS/user02 的 Editor+Viewer 預計只移除
Viewer 一筆。這是歷史快照，不能替代正式執行前的 fresh baseline。

不改變 SPECIFICATION.md 10.48 PROJECT-012 的 owner > editor > viewer、唯一角色、
Owner 保護及 Local Role 權限聯集；遵循 MIGRATE-001、DEPLOY-004/006、TEST-002。
本計畫沒有產品行為修改，SPECIFICATION.md 不變；SPEC_CHANGELOG.md 僅追加
本次隔離驗證核准紀錄，既有角色規則與 Migration 契約不變。
V049 原檔 SHA-256：
`b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`。

## 第一關：本次請求核准的隔離演練

### 授權邊界

- 只增加本地演練 runner、測試及安全摘要證據，不修改產品程式或 V049 SQL。
- 只用新建的真實 PostgreSQL 與必要的真實 OIDC/相依服務。以自行建立的測試資料
  重現「一位 Owner、另一位 Editor+Viewer」及其他邊界案例；不複製現行 MAAS
  文件、帳號、模型資料、Secrets、DB dump 或環境檔。
- 使用已安裝映像，先綁定 image ID；不 pull、不 build。至多八個隔離容器，
  合計八個 CPU／12 GiB 記憶體上限。只連接 run-owned internal network，
  不開公開 host port，不掛 Docker socket、現行 volume 或 repository .env。
- 只產生新測試憑證；不使用現行 APP_ENCRYPTION_KEY、OIDC 憑證或 Provider key。
  不啟動 Beat、一般 extraction worker、全域 queue drain 或 Provider bridge。
- 允許測試資料庫的建表、種入測試資料、V048→V049、測試資料備份及還原。
  允許隔離 API 的成員異動與其必要 audit/lock 寫入；現行服務完全不變。
- 不呼叫 Provider，不修改 Kubernetes/Helm，不備份或還原現行資料庫；不做
  role/group assignment、Project membership、文件、圖譜或索引的現行資料變更。

### 步驟

1. 保存工作區相關來源、V049、安裝映像 ID，以及既有容器/volume/network 的
   安全識別基線；保留 CHG-293..299 所有既有修改。若缺必要已安裝映像，停止，
   不自行下載。不得輸出包含 Secrets 的完整 inspect/environment。
2. 建立 runner 的 fail-closed 隔離檢查：必須核對 run ID、容器/network/volume
   所有權、明確 test DB allowlist、fresh credentials 和測試目標；不可僅以 DB
   名稱前綴視為安全。清除繼承的連線/Proxy/.env 設定，不連現行 Kubernetes DB。
3. 在空白測試 DB 用真實 Flyway 建立 V048，再種入自建資料。不得以 ORM
   create_all 冒充舊版 schema，不以固定回傳值、mock 或假服務通過行為測試。
4. 對測試 DB 執行 custom-format pg_dump，記錄 digest、schema/Flyway、各表
   row count 與穩定排序的資料摘要。將 dump 還原到另一個空白隔離 DB，實際
   比對資料、constraint、sequence/必要 ownership/ACL；不得只用檔案存在或
   pg_restore --list 宣稱可還原。缺少的 cluster roles 不以現行密碼補入。
5. 用原 V049 經 Flyway 升級測試 DB；驗證唯一角色、Owner 雙向一致、精確刪除
   項目、unique constraint、audit 與 Flyway history，並比對所有無關資料未變。
   再執行 Flyway migrate，驗證無額外資料/audit/history 變更；SQL 本身冪等性
   可在另一個測試 DB 驗證，但不能把直接 SQL 執行當作正式 Flyway 路徑驗收。
6. 在各自獨立的 DB 驗證缺 Owner、單側 Owner、archived project、多種 role
   組合，以及真實競爭鎖與 timeout。錯誤案例須證明 transaction 無部分資料/DDL
   留存；保留實際 Flyway failure 記錄結果，不以 repair/clean 隱藏失敗。
7. 用已安裝 CHG-292 Backend 原始映像，以及目前累積工作區 Backend，分別對
   V048/V049 執行相同的真實 SQL/OIDC/API 角色矩陣：清單、單角色替換、多角色
   422、stale lock、唯一/本人 Owner 保護、權限拒絕、並行變更與 audit 原子性。
   現行 CHG-292 是「待驗證的回退候選」，不是預先認定安全。
8. 在隔離 V049 DB 上改回執行 CHG-292 映像，重新驗證讀寫；不移除 constraint，
   不回填被移除的 Viewer。另把步驟4備份還原到新的空白 DB，驗證可回到測試
   V048 的原始三筆 membership。這兩種演練分別證明程式回退與資料還原，不能混稱。
9. 記錄備份/還原/遷移/鎖等待耗時、精確命令、測試結果及來源綁定。執行靜態
   harness 與相關角色回歸；不降低 coverage 門檻，不以本次聚焦結果冒充整體
   Backend/Frontend 80%、完整 E2E、Frontend UI 或新映像發布驗收。
10. 停止演練自己的 writer。核對精確 ID、所有權及未被其他容器使用後，僅清理
    本次建立的容器、專用 volume/network 及含自建資料的演練 dump。保留不含
    憑證/資料全文的摘要證據。比對所有先前存在的資源仍保持原狀。

### 預計檔案及驗證命令

- `backend/scripts/chg291_v049_rehearsal.py`：隔離檢查、資料庫生命週期、備份還原、
  Flyway/映像綁定與安全證據；盡量沿用既有隔離工具，不改通用產品行為。
- `backend/tests/test_chg291_v049_live_rehearsal.py`：下列 V49-R01..R10 真實測試。
- `backend/tests/test_chg291_exclusive_project_member_role.py`：保留既有測試，不以
  SQL 字串檢查代替新增的真實 migration/API 驗證。
- `docs/CHG-291-V049-REHEARSAL-RESULT.md` 及安全 evidence JSON：執行後才建立結果。
- DEVELOPMENT_PLAN.md、TEST_PLAN.md、TRACEABILITY.md：本計畫與執行狀態。

核准後才執行 `./HARNESS/harness.sh plan:approved`、`spec:doctor`、`spec:trace`、
`test:plan`、`backend:syntax`、`git diff --check`，以及透過隔離 runner 的 pytest
和真實 pg_dump/pg_restore/Flyway。結果必須列出展開後命令及 DB/image/source binding。
不得直接執行可能讀取現行連線設定的 `backend/scripts/migration_live_acceptance.py`；
其中既有靜態/合成 bootstrap evidence 亦不得充作本計畫的 live readiness 證據。

### 停止條件

隔離或資源所有權無法證明、工具缺失、來源/image/V049 digest 漂移、權限被拒、
任何非預期外連、必要服務不可用、資料/Owner/unique/audit 驗證不符：停止受影響
階段並報告，不自行修 V049、放寬權限或擴張外連。測試發現產品 Bug 時先討論
修正範圍；不可把本演練核准當作任意產品修正、部署或資料修補授權。

## 第二關：正式備份與部署，仍須另外核准

第一關通過只能說「做法及相容性已經演練」，不能說「現行資料已有可用備份」。
後續正式執行前必須另定以下範圍：

1. 指定受保護的本機備份目的地、加密方式、由 Peter 保管的解密材料與保留期限。
   NomoSmart DB 備份可能包含真實文件、個資及加密的模型設定，不能寫入 Git、
   一般 evidence/log、雲端同步資料夾或無保護的暫存檔。不可假設 FileVault 已開啟。
2. 明確核准備份該 DB 並還原到隔離 PostgreSQL；還原副本只供 DB 驗證，不啟動
   App/Worker/Bootstrap 讀取副本中的現行 endpoint/credential。cluster roles/ACL、
   extensions、加密金鑰可用性需另核對，不盲目匯出含密碼的全域角色資料。
   PostgreSQL dump 不包含 S3 原檔、Keycloak DB、Neo4j/OpenSearch、Redis 或 PVC，
   不宣稱整個平台 disaster recovery；本次 V049 不得修改這些服務。
3. 執行前重取成員/Owner、schema、映像及保護基線。任何 Owner 矛盾、新專案或
   名單差異先停止交由 Peter 確認。備份演練後若資料再變，必須另取新 recovery point。
4. 核准維護窗口與停止所有相關 writer（API、排程/worker、管理/同步工具）的
   明確資源/方式，再取得一致性備份；設 lock/statement timeout。實測與估算時間
   應明列，不能保證任意固定停機時間。備份失敗或實際還原未通過不得套用 V049。
5. 累積 Backend/Frontend/Migration 候選需另行 build、安全掃描、smoke、完整
   發布 gates 及 fresh canonical Helm render。工作區來源相容性不是新 image 驗收。
   migration readiness/schema contract、bootstrap bounded operational writes 與
   回退目標須以實際 chart/render 檢查，不能只改 compatibility label 當作保證。
6. 真正 V049 apply 的批准需綁定備份驗證證據、fresh 精確名單、三個 image ID、
   render digest、Job 範圍、maintenance/rollback 條件；不複用歷史 revision35 批准。
   第一階段 application-first 已經發生，不因本計畫重做舊部署。

Helm rollback **不會**恢復被 V049 移除的角色列。若 V049 已完成，優先使用實測
相容的程式回退並保留 V049；資料整庫還原是另一個受控事件，會丟失備份之後的
所有 DB 寫入，且需核對其他服務一致性，必須再次取得明確批准。

## 本次核准用語

`Peter approves CHG-291 V049 isolated migration, synthetic-data backup/restore and
CHG-292/current-source compatibility rehearsal under docs/CHG-291-V049-REHEARSAL-PLAN.md;
no live-data backup, live migration, image build, deployment or Provider call.`

Peter 已於 2026-09-12 以後續 `Ok` 直接答覆本計畫核准請求，第一關可開始；
第二關不包含在本次核准內。

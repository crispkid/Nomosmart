# CHG-300 Migration 安全修正與目標版本檢查計畫

2026-09-13 Peter「好」確認修正方向，Gate 2 confirmed；Gate 3 完成。
**Gate 4：Peter 於 2026-09-13 以「Ok」核准本計畫的修正與隔離測試。**
此回覆直接承接書面核准問題；Gate 5 開始。建置／部署仍需另行核准。

## 1. 範圍與基線

先修 Migration 工具映像安全，再讓共用啟動檢查確認目標版本與 checksum。
不改 V001–V049 SQL、Owner／成員規則、API、Frontend UI、資料來源整合，
保留全部已核准的累積 dirty-worktree 變更。

[掃描證據](CHG-291-CANDIDATE-SCOUT-EVIDENCE.json) 的 36 筆 High/Critical
分為系統套件 13、額外資料庫驅動 17、共用 Netty 6，不是 36 個不同漏洞。
[整合準備結果](CHG-291-INTEGRATED-RELEASE-RESULT.md) 已用真實 V048 DB
證明 `_database_check` 不要求 V049。兩個問題需分別驗證。
規格：SPECIFICATION.md 10.57 MIGSEC-001、MIGGATE-001/002、MIGSAFE-001。

## 2. 本次 Gate 4 已核准界線

允許 repository recipe/config/backend/check/test/doc 修補；使用已核對的既有
測試服務映像、新憑證與自建資料進行有界真實隔離測試，以及本地無副作用的
source/config/Compose/Helm 驗證。沒有 Provider 呼叫。

另行核准：新映像建置、image smoke、對新候選的外部 scanner metadata 傳輸、
server-side dry-run、現行環境盤點／備份／維護停寫、live V049、Helm/Kubernetes
Job 或部署。前次 Scout「是」只綁舊三個 IDs，不能延用到本次新候選。
不執行現行資料修復、flyway repair/clean、角色分配、索引修改、文件重跑或 push。

## 3. 實作步驟（Gate 4 後）

### A. Migration recipe

- 固定目前 recipe、SQL hashes、finding→套件位置對照；優先採官方 Flyway
  相容新版整體升級，記錄版本、digest、平台、JRE、來源、license，不使用 latest。
- 前次官方研究顯示 13.6.0 與 JRE 變更，僅列評估候選，不代表已驗證安全／arm64
  相容或已取得 image digest。鎖定前核對官方 artifact metadata，不虛構 digest。
- 一併處理 OS、bundled/shaded Java libraries；不能只 apk upgrade。若完整
  官方映像仍有不必要弱點，才建立 PostgreSQL 所需模組／依賴閉包的明確清單。
  不模糊刪除 JAR 或任意混用版本；保留必要 CA、Secret wrapper、法律文件、
  non-root/read-only 與 CLI 相容性，執行時不新增套件下載或任意連外。
- 若需改 licensing、registry、必要 driver 或無相容修補方案，先討論。新 recipe
  在另行批准建置／掃描前只列待驗證，不 suppression、不將舊 PASS 挪用。

### B. 目標契約與共用唯讀 gate

- Typed settings 加 `MIGRATION_REQUIRED_VERSION`／`MIGRATION_REQUIRED_CHECKSUM`；
  Helm 對應 `migration.requiredVersion`／`migration.requiredChecksum`，Compose
  與所有 app/init/bootstrap 同源。非敏感 release config 外部化，不硬編 V049。
- checksum 使用 Flyway signed 校驗值，與 file/source SHA-256 分開保存。
  expected 必須由固定 SQL 的真實 Flyway migrate/validate 證據綁定；不能從
  現行 DB 自動學習後作為 expected。配對缺失、空值、格式錯誤均安全拒絕。
- 驗證 history、failed migrations、目標 success/version/checksum，保留所有
  既有 schema／安全／外部 readiness 檢查。拒絕未核准較新 schema，不因數字較大
  就跳過 checksum；回退版本需明確相容契約。保留合法 adoption baseline。
- 使用參數化唯讀 SQL；無 DB/history／錯誤 checksum／未完成 target 時 CLI
  非零退出、既有 readiness not ready。一般輸出只含穩定 code/safe metadata，
  不洩露 Secret、SQL、URL 或文件內容；不得寫 DDL/history 或執行 migration。
- 在 bootstrap ensure 的外部 identity 寫入之前先檢查。check 與 runtime
  共用同一 verifier；Web runtime 不啟動 migration。拒絕 backend.env 等重複鍵
  靜默覆蓋目標契約，不以預設空值或 schemaContract 標記放行。
- 實作接線決策：既有網路政策隔離 Frontend 與 DB，因此不採直接 DB probe，
  不新增 Secret 或網路權限。Frontend 比對 Backend 現有 readiness JSON 的
  `deployment.database.detail=migrated:<canonical version>:<signed checksum>`；
  只有共用 DB gate 與原有 schema 檢查成功才回此值。只回 HTTP 200 的舊 Backend
  不足以放行。窄版 typed target 與完整 Settings 共用驗證，業務 API 不變。
- 隔離來源綁定：Python safe path 避免容器工作目錄 `/app` 蓋過 `/current`；
  current-source 驗收必須檢查實際模組路徑。舊映像測試不得冒充新來源驗收。

### C. 順序與回退界線

共用 gate 保證缺目標時新 main containers 不工作；不冒充 Helm 尚未更新
Deployment templates 的證明，也不承諾舊副本等待時一定仍有足夠容量。
本次可改目標 config/init 接線，不直接更換 installer stages／Job hooks。

若現有流程仍不滿足 migration 先於 rollout，提出 hook／兩階段策略及新裝
DB/Secret 先備、升級舊服務保留、audit Job 保留、timeout、rollback 影響，另請核准。
不得以省略現有 Deployments 的 render 造成 Helm 刪除它們。Code rollback
不等於 schema/data 降回 V048；需驗證精確舊 artifact 在 V049 的相容性。

## 4. 預定檔案

| 區域 | 修改目的 |
| --- | --- |
| deploy/migrations/Dockerfile、必要 dependency manifest | 官方升級、鎖定與條件式精簡 |
| backend/app/core/config.py | 外部化 typed version/checksum |
| backend/app/deployment/bootstrap.py、必要小型 verifier module | 共用唯讀 gate、ensure 前置檢查、安全錯誤 |
| docker-compose.yml、deploy/docker/nomosmart.env.example | 同源目標契約 |
| deploy/helm/nomosmart values/schema/ConfigMap/init/bootstrap templates | 驗證／傳遞目標，不直接更換部署階段 |
| backend/tests/test_chg300_migration_gate.py、隔離 runner、現有部署合約測試 | 真實 PG/Flyway 正負向與接線回歸 |
| 規格、變更記錄、計畫、測試計畫、trace、部署文件 | 要求至證據與操作界線 |

若 build context/init 必須攜帶驗證 metadata，先記錄 spec/source manifest，
不私下建立第二個 SQL 執行路徑。Frontend UI、Backend datasource adapters 及 SQL 不改。

## 5. 驗收與資源

TEST_PLAN.md M300-T01..T10：先跑最窄契約／真實 V048 拒絕與 V049 通過，再跑
新安裝、重跑、故障、鎖定、checksum、Owner／角色與相容回退。沒有 mocks、
fixture adapters 或手填成功 history；checksum 負例改 expected 或明確隔離
SQL 副本，原 SQL 不動，正向 history 必須由 Flyway 建立。

最多八個自有容器、總上限 8 CPU／12 GiB；internal network、新憑證、自建資料，
不掛 Docker socket／現有 volume，不用 host network／正式憑證／Provider。
沿用精確 run-owned receipts 清理，保留所有 preexisting resources／報告；
若必要服務映像不在本機、需下載或需擴大權限／資源，先確認再執行。

Gate 4 後命令：harness spec:doctor、spec:trace、plan:approved、test:plan、
backend:syntax；綁定隔離服務的 pytest／coverage；本地 docker:config、helm:lint、
deploy:config-policy 用安全輸入，不啟動目前 Compose stack。新 runner 精確命令
在實作時記錄，不虛構已存在的入口。各端全來源 80% 與完整 E2E 門檻不降低。

新映像階段另核准後才產生 SBOM、全嚴重度／High/Critical scan、image smoke、
Flyway validate／migrate 與 source/image/render 綁定。其他發布失敗、完整備份、
保護基線、維護窗口與回退仍待完成；本次 scoped PASS 不能解鎖整批發布。

## 6. 狀態與研究依據

核准當下所有 M300 測試 NOT RUN；後續執行另記來源綁定證據。以下為核准前歷史。

2026-09-13 文件治理驗證：spec:doctor、spec:trace、plan:doctor、test:plan、
git diff --check PASS；plan:approved 正確回傳 exit 1（Gate 4 pending）。
首次 spec:trace 將「SHA-256」誤辨為 requirement ID；只將本節算法名稱寫成
「SHA256 雜湊」後通過，未更動 harness／門檻或新增假需求。未跑功能測試。

- [官方 Flyway release notes](https://documentation.red-gate.com/fd/release-notes-for-flyway-engine-179732572.html)：前次已核對新版與 JRE 變更，仍需相容驗證。
- [官方 PostgreSQL module／driver](https://documentation.red-gate.com/flyway/reference/database-driver-reference/postgresql-database)：PostgreSQL 支援所需模組。
- [候選掃描結果](CHG-291-CANDIDATE-SCOUT-RESULT.md)：舊候選實際證據，不是新候選已通過。

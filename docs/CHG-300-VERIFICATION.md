# CHG-300 Migration 修正與驗證

日期：2026-09-13（Asia/Taipei）。Peter 的 `Ok` 核准 repository 修補及有界隔離測試，
**不是新映像建置、安全掃描傳輸、目前環境異動或部署核准**。
規格：SPECIFICATION.md §10.57；計畫：[修正計畫](CHG-300-MIGRATION-SECURITY-AND-GATE-PLAN.md)。

## 結論與範圍

已實作程式側目標 migration gate，Migration recipe 改為精確官方候選。
新映像安全問題尚不能結案：尚未建置／執行／掃描 Flyway 13.6.0 候選。
完整發布也仍受全來源 coverage、E2E、備份、保護基線及部署順序等既有 gates 限制。
未變更 V001–V049、現行資料、角色權限、Provider、Helm release 或 Kubernetes。

## 根本修正

1. 原本只看 history/table 存在，V048 也可能通過。現在 operator 必須指定
   migration version 與 Flyway signed checksum；缺值、錯值、目標未完成或較新
   未核准版本均拒絕。不能把目前 DB 的值自動學習為期望值。
2. 共用唯讀、repeatable-read transaction，連線／statement 有界；保留原有
   schema/system-parameter/legacy-security 檢查。驗證不做 DDL、repair 或回填。
3. bootstrap ensure 先驗證 DB，才允許後續既有的初始化行為；CLI 配置錯誤安全退出，
   不在 traceback 印出憑證。runtime readiness 共用同一 verifier。
4. Frontend 不只看 HTTP 200：比對既有 readiness JSON 中已驗證的
   `dependencies["deployment.database"].detail`，格式為
   `migrated:<canonical version>:<signed checksum>`。舊版 `ready` 不足以放行。
   **不新增 Frontend DB Secret、網路存取權或業務 API**。
5. Compose/Helm 同源傳值，拒絕部分契約與大小寫不同的環境覆寫；空範例可 render，
   但不能通過 runtime gate。沿用舊 values 時必須另填新契約，不能直接部署空值。

這只保證新 main-container 的啟動門檻；不代表 Helm 尚未更新 Deployment template，
也不代表舊副本容量必然保留。嚴格先 migration 後 rollout 的策略仍需另行審查。

## 變更檔案

| 檔案 | 目的 |
| --- | --- |
| `deploy/migrations/Dockerfile` | 官方 Flyway 13.6.0 Alpine multi-platform index digest 鎖定 |
| `backend/app/core/config.py` | 共用 typed target、窄版 DB probe 與完整 Settings；保留 production/Secret 規則 |
| `backend/app/deployment/migration_gate.py` | 唯讀目標驗證、版本正規化、readiness target 比對 |
| `backend/app/deployment/bootstrap.py` | 共用 gate、ensure 前置檢查、CLI 安全錯誤與 readiness detail |
| `docker-compose.yml`、`deploy/docker/nomosmart.env.example` | 同源版本／checksum／timeout |
| Helm `values.yaml`、`values.schema.json`、`templates/configmap.yaml`、`templates/_bootstrap-init.tpl` | 配置驗證與四條 app init 接線；不改 hook/stage/NetworkPolicy |
| `backend/scripts/chg300_migration_checks.py`、`backend/tests/test_chg300_migration_gate.py` | 新來源綁定真實 PG/Flyway gate、CLI、唯讀與錯誤測試 |
| `backend/tests/test_chg300_config.py` | 本地 Helm render/Compose 契約檢查，不冒充 Kubernetes 驗收 |
| `backend/scripts/chg291_v049_rehearsal.py`、`backend/tests/test_chg291_v049_live_rehearsal.py` | 修正 Python source shadowing，驗證實際模組來源，再跑保留矩陣 |
| 規格／changelog／plan／test／trace、`deploy/README.md` | 契約、部署影響與驗收界線 |

## 映像候選（未建置）

唯讀官方 registry manifest 查詢：
`docker --context desktop-linux buildx imagetools inspect flyway/flyway:13.6.0-alpine`。

- multi-platform index：`sha256:fb7f326765649205574551e25ba774e432ea840b126983d6ec3bbda8f21b137c`
- linux/arm64：`sha256:cacd72ebf4f8193b52b69b2318428a23789911304551ad6356d1c4002a3e1883`
- linux/amd64：`sha256:0689ed4bcf1a81de2e6b2de3266799413f27dcb10def838ae0a3c7944baff9fc`

[官方 release notes](https://documentation.red-gate.com/fd/release-notes-for-flyway-engine-179732572.html)
記錄 13.6.0（2026-09-10）Docker JRE 21→25，因此平台/JRE/CLI/TLS/Secret/non-root/
read-only 相容性、打包的 license/notices、PostgreSQL 依賴閉包與 shaded libraries
都需在另核准的新映像階段驗證。保留官方完整套件，沒有模糊刪 JAR、混用單一
Java library、新增授權 token 或 runtime download。新版本不等於沒有漏洞。
舊 Migration 的 4 Critical／32 High 報告保留，不挪作新候選證據。

## 測試

最終 run `v49-57f4d71b567a`、目錄 `/private/tmp/chg300-isolated-9jknktf4`：
兩階段 exit codes `[0,0]`，cleanup/source/baseline equality 全部 true。
完整來源與 artifact hashes：[機器證據](CHG-300-VERIFICATION-EVIDENCE.json)。

- CHG-300 gate：53 PASS，新增 verifier branch coverage 95.37%（74/76 statements、
  29/32 branches；無 exclusions）。不是整個 Backend 的 coverage。
- 本地 Helm/Compose：16 PASS。
- 保留 V049 真實 migration/Owner/OIDC/rollback：13 主測試 PASS（163.32 秒），
  其中5組子矩陣各22 PASS，共110次執行，並非110種不同案例；無 skip/error。
  角色模組 coverage 各100%，不是全 Backend coverage。
- 靜態 Bandit 使用原 `-lll -iii` gate：High=0；仍有 Medium=32、Low=61，未作零漏洞聲明。

| 實際程式來源 | DB | 結果 |
| --- | --- | --- |
| 既有 CHG-292 原始映像 | V048 | 22 PASS |
| 既有 CHG-292 原始映像 | V049 | 22 PASS |
| 此輪 current 掛載來源，含模組路徑校驗 | V048 | 22 PASS |
| 此輪 current 掛載來源，含模組路徑校驗 | V049 | 22 PASS |
| current 測試之後換回 CHG-292，同一 V049 DB | V049 | 22 PASS |

使用真實 PostgreSQL/Flyway/Keycloak，原 V049 的全新安裝、V048 升級、重跑、
ownerless 拒絕、鎖競爭/timeout、備份還原、唯一角色與 Owner 保護均保留。
SQL source 雜湊 `b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`；
本輪自建 DB 的真實 Flyway V049 checksum 為 `-1579162252`。此 checksum 綁本輪
不可變 SQL／既有 Flyway 測試映像，不能直接取代未來新映像的 validate 證據。

精確 run-owned containers、PG volume、internal network、測試密碼與自建 dump
均已清理；保留 XML/coverage/安全摘要，不保留測試憑證。既有 Docker baseline
與 app/SQL 來源前後一致。這不是現行 MAAS 資料盤點或正式備份。

命令：

```sh
backend/.venv/bin/python -B backend/scripts/chg300_migration_checks.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider --tb=short -q backend/tests/test_chg300_config.py
UV_OFFLINE=1 ./HARNESS/harness.sh security:static
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh deploy:config-policy
git diff --check
```

每個 harness target 分別呼叫；多個參數的一次呼叫只執行第一個，不列為其餘項目通過。
上列治理／語法／配置 harness 與 diff check 全部通過；最後重核189個來源／artifact
雜湊一致。這些靜態檢查不取代新映像與完整發布測試。
Docker socket、registry metadata 與 uv cache 在 sandbox 拒絕後均經標準權限核准，
沒有繞過；Bandit 保持離線，未下載套件或傳送程式碼。

## 中途失敗（保留，不隱藏）

1. `/private/tmp/chg300-isolated-2k_jsite`：新 gate collection 失敗，Python 工作目錄
   `/app` 蓋過 `/current`，找不到新 module。該輪 [2,0] 不通過；retained current
   source 列不能當新程式驗收。已加 `PYTHONSAFEPATH=1` 與實際模組位置 assertion。
   舊 CHG-291 演練報告加更正註記，原 artifact 不回改。
2. `/private/tmp/chg300-isolated-k2rqi3yw`：40 PASS／1 FAIL，baseline-only DB 沒跑
   V042 app-role grants，實際查得 `has_table_privilege(...,'SELECT')=false`，先因
   權限不足被拒絕。只補自建 baseline DB history 的 SELECT，讓案例測到 BASELINE
   不能冒充完成 SQL；未放寬 gate、未修改 Flyway 成功紀錄。該輪 retained 13 PASS。
3. 設定測試首輪 12 PASS／4 FAIL：同時使用 `--set-string` 與 `--set` 使正確值
   蓋過負例；改為每個 key 只送一次後16 PASS，不修改 Helm 驗證門檻。
4. 初步 Frontend 直接 DB probe 方案與現有 NetworkPolicy 不相容；在 source
   檢查發現後改採已驗證 readiness metadata，比對版本但不擴大存取權。

## 限制與下一關

- 真實 Flyway source rehearsal 使用既有 13.0 映像，不是 13.6.0 新映像驗收。
- PostgreSQL 的失敗 V049 transaction 會 rollback，已測拒絕／無部分異動；持久化
  failed history row、successful repeatable 與 engine 建立前失敗的部分分支未覆蓋，
  無 mock 補成功。Frontend 目前是實際 DB verifier＋target 比對與 render 接線，
  未完成新映像／全服務 HTTP／Kubernetes Pod 驗收。
- 新映像 build、SBOM、全嚴重度掃描及 High/Critical gate仍需另核准並完成。
- 全產品雙端80%／完整 E2E／其他既有發布失敗、實際加密備份、保護基線、
  維護窗口及嚴格 rollout-order／精確 artifact rollback 仍不可豁免。
- 本次沒有對目前 MAAS／DB／Neo4j／OpenSearch／Kubernetes 做任何操作；測試帳號、
  DB 與隔離資源只屬於本次 runner。

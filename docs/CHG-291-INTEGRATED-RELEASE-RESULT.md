# CHG-291 累積三映像／V049 準備結果

2026-09-12，Peter「同意」核准準備 A–C。**已有候選映像，但準備尚未完成、不可部署。**
產品規格與原 V049 不變；沒有修改產品程式、SQL、相依版本、Dockerfile 或 chart。
本輪只修改核准的測試／執行工具與證據文件。現行環境仍為 revision 36，未建立
Kubernetes Job、未套用 live V049、未修改現行應用資料、未呼叫 Provider。

機器可讀證據：[CHG-291-INTEGRATED-RELEASE-EVIDENCE.json](CHG-291-INTEGRATED-RELEASE-EVIDENCE.json)。
核准範圍：[CHG-291-INTEGRATED-RELEASE-PLAN.md](CHG-291-INTEGRATED-RELEASE-PLAN.md)。

## 1. 已完成什麼

| 項目 | 實際結果與界線 |
| --- | --- |
| 來源固定 | 684 個檔案的私有副本；包含累積未提交來源，排除私有設定／憑證／依賴／產物 |
| 三個映像 | Backend、Frontend、Migration 均建置成功，arm64、非 root，沒有覆寫舊 tag 或 push |
| Frontend 功能 | 156 個 contract tests、94 個 component tests，以及實際 Chrome geometry checks 通過 |
| Frontend 覆蓋率 | statements **11.45%**、lines **12.64%**、functions **12.06%**、branches **9.51%**；完整 harness exit 1，未達 80% |
| Backend 全套 | **620 PASS、3 FAIL、82 setup ERROR，共 705**；不是 85 個已確認產品 Bug |
| Backend 全來源覆蓋率 | coverage.py statement＋branch **48.51%**，lines/statements **52.58%**、branches **33.96%**；未達 80% |
| 分程序重跑 | CHG-297 **47/47**、CHG-298 graph retry **1/1**、CHG-299 **28/28** 斷言通過；各自仍保留全來源 80% 門檻的非零 exit |
| 原本 11 項 | 同一候選來源無 Provider 的 **8 項 PASS**；其餘 **3 項 BLOCKED**，沒有模型呼叫授權與 transport |
| 廣泛 API 檔案獨立執行 | **18 PASS、3 BLOCKED，共 21**；原 11 項是此檔案中的子集，不能再加總為不同測試 |
| 新 Migration 實際執行 | 新 PostgreSQL 18.4／Flyway 13.0.0，先套 V001–V048，再套原 V049 成功，既有 49 個 migrations validation 通過 |
| 映像 smoke | Backend 真實 loopback health 200／OpenAPI；Frontend 真實 Next login 200、sharp/native image checks，加四項隔離負向測試通過 |
| 安全靜態分析 | 既有 Bandit，offline、高嚴重度／高信心門檻通過；不等於所有嚴重度零問題 |
| 候選 container／SBOM | 補充授權後三者掃描與 SPDX 完成；Backend／Frontend High/Critical PASS，Migration **4 Critical／32 High、gate FAIL** |
| Compose／Helm／設定 | config、lint、policy 通過；兩次 hidden-Secret server dry-run 完全一致 |

Frontend geometry 使用 Playwright 技能要求的真實瀏覽器方式，保留 production
renderer/CSS 與原斷言；工具只新增新來源路徑的 private-directory/hash 綁定，
未改成模擬畫面。1280／375 px、捲動／跨頁／非連續範圍／鍵盤事件均有實際證據。
另檢視 1280 px screenshot；這是隔離 component 畫面，不是完整登入 E2E。

Source SHA-256：
`aea6a1ce709e925c6c6396bdcee1c25a7a6fdb7f66644c5fca3e2d6d2e0f0e95`

HEAD：`bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3`。HEAD 不代表所有累積工作區內容。
私有來源／報告根目錄：`/private/tmp/chg291-release-385z05xz`。
完整 file manifest 與各工具版本 hash 保留；後續新增執行工具另行綁定，不宣稱它們
是早先已固定副本／映像中的內容。

## 2. 候選映像及 dry-run

三者 tag 都是 `0.1.0-chg299-v049`：

| Repository | Image ID |
| --- | --- |
| nomosmart/backend | `sha256:b9c5cefc215650b2b3dbdc3bbfecd6a3f035a5566077be4479b987ad13b1e338` |
| nomosmart/frontend | `sha256:3fb90bfc19cf0548ad5bcd3d2db4b5915e6b0d37ed7c381c4dff8e36ae57cd8f` |
| nomosmart/migrations | `sha256:f9abf8575034e44d0a1ce050d1150b8cd2e18f1ef1545b7b37799ad0b2a78018` |

新 Migration 在空白合成資料庫完成 48→49；**這不是現行 MAAS 資料 migration，
也沒有重新完成全部 exact-image 角色／回退矩陣**。先前獨立 V049 演練仍依其
原來源／映像／測試界線有效，不挪成新三映像的完整驗收。

Backend smoke 只驗證 liveness、十個 production source hashes 與既有合約；
不冒充資料庫 readiness 或完整 authenticated E2E。Frontend smoke 保留 Node
24.21.0、bundled/system OpenSSL 3.5.8、Next 16.3.3、sharp 0.35.4、libheif 1.23.2
與既有 package/lockfile hash 斷言，未為新映像降低標準。

Dry-run：目前 revision 36；預期 revision 37，兩次 canonical bytes **96,231**。
SHA-256：`98f564723f02b408145c001d750bf64d5faa0fc28ac7799d1392d92c4d39537a`。
規則：Helm 輸出自 `HOOKS:\n` 起至結尾的 UTF-8 bytes；不保存 Secret/完整 values。

```sh
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg299-v049 \
  --set-string image.frontend.tag=0.1.0-chg299-v049 \
  --set-string image.migration.tag=0.1.0-chg299-v049 \
  --set-string compatibility.schemaContract=forward-v049 \
  --dry-run=server --hide-secret --timeout 15m
```

渲染只含預期兩個 revision-scoped Jobs；Backend 引用 8、Frontend 1、Migration 1。
其餘非 Secret manifests 正規化比對一致。前後 revision／effective values digest／
deployment specs digest 不變，revision-37 Jobs 仍為零。
這是候選 render，不是部署核准；若修正順序機制，必須重新 render／綁定。

## 3. 阻擋項目與待討論事項

### 1）部署順序保護不足——已用新映像重現

在另一個全新、實際 Flyway V048 資料庫中，使用本次 Backend image 呼叫
`app.deployment.bootstrap._database_check`。查明成功 V049 rows 為 **0**，
該函式仍回傳 `{"name":"database","detail":"migrated"}`。

現行 migration 為一般 Job；Backend init 執行 bootstrap check。bootstrap ensure
也使用同一個 database check，並不校驗本次要求的 V049／checksum。revision-specific
bootstrap evidence 能證明 bootstrap 自己通過，但不是目標 migration 成功的證明。

這能證明缺少版本 gate，**沒有聲稱已在目前 Kubernetes 觀察到提前啟動或資料損壞**。
建議討論：要求實際目標 migration/checksum 通過才放行，或核准明確兩階段部署。
不改 V049 SQL、不把 `forward-v049` 標記／`wait-for-jobs` 當成替代證明。
本輪沒有擅自修 chart 或 bootstrap。

### 2）兩項斷言失敗仍需處理，不能把測試改鬆

- `test_chg203_auth_search_revalidation::test_old_version_switch_updates_manifest_without_vector_cleanup`：
  舊測試要求連續出現一段原始碼字串；CHG-296 現行條件多了 project scope 檢查，
  所以字串不再相同。這是測試合約落後的證據，不等於少了 readiness 檢查。
  應保留「無 manifest／非 ready 拒絕」及新增跨 project 拒絕的語意驗證。
- `TagGraphTests::test_real_publish_switch_history_and_readiness`：真實發布後切換
  歷史版本，在 OpenSearch `_count` 證據檢查得到 `published_index_evidence_invalid`。
  尚未證明是 refresh 可見性時序、測試資料或產品儲存問題；不能先稱為已修復。
  應追查實際 count／chunk／index evidence，不能移除安全比對或手填成功向量。

### 3）完整套件的測試協調與覆蓋率仍不合格

全套 82 setup errors 中：13 項 V049 演練需要其專用 runner/state；69 項是同一
`live_client` 被不同測試檔匯入，於同一程序建立同名 role 造成衝突。分程序後，
這 69 項中的無 Provider 操作不再被該 fixture 衝突阻擋；原全套報告仍保留失敗。
另有一項 prerequisites FAIL 是獨立 Backend HTTP server 未在隔離 port 18437 啟動，
不代表現行服務故障。兩個正向 app image liveness smoke 不能抵銷此全套缺口。

第一次 233 項局部合跑為 159 PASS／74 setup ERROR，其中 25 項 cleanup suite
缺明確新服務綁定；補齊到新隔離服務後它們在全套通過。其餘為上述角色 fixture。
未刪除／skip／xfail 測試，未降低 80% 門檻；分程序成功不是全套改列成功。

### 4）三項需要模型的正向測試，本次沒有呼叫授權

1. `test_live_seeded_reference_and_approval_workflows`
2. `test_live_external_services_and_domain_adapters`
3. `test_live_integration_adapter_embedding_and_switch_edges`

實際 runner 不提供 `CHG298_MODEL_BINDING`，在建立 Provider 路徑前安全拒絕。
pytest 原始結果是 FAIL，發布矩陣按原因列為 BLOCKED；不重新標成通過。
後續需要既有模型＋合成內容＋具體上限的獨立批准，不沿用舊呼叫額度。

### 5）安全掃描完成；Migration 未通過門檻

歷史：Docker Scout 因可能傳送 package inventory／SBOM metadata 至外部服務，
首次執行被審核拒絕，當時沒有繞過。Peter 隨後回覆「是」明確核准該傳輸範圍；
本次依補充授權完成三個精確 image IDs 的掃描與 SBOM。

Backend／Frontend High/Critical gate 通過；Migration 檢出 **4 Critical、32 High**
紀錄（28 個不重複 advisory IDs），gate exit 2。問題指向映像內作業系統／Java
相依套件，不是 V049 SQL；尚未逐項證明可利用性。Backend 另有 57 Medium／9 Low。
完整結果與 artifacts hashes 見 [候選掃描報告](CHG-291-CANDIDATE-SCOUT-RESULT.md)
及 [證據](CHG-291-CANDIDATE-SCOUT-EVIDENCE.json)。獨立 dependency audit 仍未執行。
沒有自動修正／重建、風險豁免或部署；Migration 安全修正需先討論核准。

Bandit 最初受本機 cache 權限限制；核准僅存取 cache 的 offline 重試後通過，
該次 Bandit 沒有下載套件或傳送來源；此次 Scout 傳輸依上述補充核准。

### 6）備份與完整發布驗收尚未完成

加密備份工具／安全測試、現行資料加密匯出／tmpfs 還原、完整 fresh protected
baseline／writer inventory、exact-image V049 角色與回退矩陣、完整 browser/E2E
尚未完成。本輪沒有匯出真實資料或產生明文／加密 dump。
實際備份密碼仍須 Peter 在自己的 Terminal 輸入，不在對話收取。

## 4. 保留與清理

隔離測試只使用新 credentials、合成資料與 internal network 真實服務。
建置與大型 stack 依序；最大七個常駐服務/relay＋一個有上限短命測試容器。
已核對並清除 **7 個本輪容器、5 個專屬匿名 volumes、1 個 network 與 relay**；
原 **14 個 Docker 容器的 ID、running/startedAt** 未變，沒有刪除任何映像。
隨後 5 個 Frontend smoke 容器／其負向測試 internal network，以及 1 個 Backend
smoke 容器均精確清除。候選 images、私有測試報告保留；合成測試資料隨容器／
volume 清除，不是可恢復的應用備份。現行 MAAS 資料未作清理。

早期 `/private/tmp/chg291-release-3n8yzhjl` 的 Frontend run 因 `E2E_PYTHON`
沒有指向既有測試 Python 而有 4 項測試工具失敗；修正執行環境、新建來源副本後
156 項通過。原失敗未覆寫。後續每次重跑保留自己的 log／JUnit／coverage。

## 5. 工具、規格與驗證

本輪工具位於 `backend/scripts/chg291_integrated_preparation.py`、
`chg291_integrated_lab.py`、`chg291_isolated_tests.py`、`chg291_candidate_checks.py`、
`chg291_frontend_image_check.py`、`chg291_dryrun.py`；geometry guard 位於
`frontend/tests/chg294SelectionGeometry.browser.mjs`。工具不提供正式部署或 live apply 入口。

確認規格未變：SPECIFICATION.md 10.48 PROJECT-012/010、10.50–10.56、
MIGRATE-001、DEPLOY-004/006、FESEC-004、TEST-002/005。需求對照 V49-I01..I08
見 TEST_PLAN.md／TRACEABILITY.md；準備計畫仍 approved，發布仍 blocked。

實際命令包括：

```sh
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh frontend:lint
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:config-policy
docker compose config --no-env-resolution --quiet
uvx --offline bandit -r backend/app deploy/installer/nomosmart_installer deploy/release/nomosmart_release -lll -iii
git diff --check
```

上述靜態／治理命令通過。候選 `test:frontend` 與 full Backend
`pytest --cov=app --cov-fail-under=80` 未通過，報告沒有刪除門檻失敗。執行檔、完整命令、來源／
映像／log hashes 見 evidence JSON。**下一步應先討論已確認的 gate 缺口與
Migration 映像安全修正，不能直接核准部署這份 render。**

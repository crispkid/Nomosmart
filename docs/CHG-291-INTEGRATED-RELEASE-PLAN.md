# CHG-291 V049 ＋ CHG-293..299 累積整合發布計畫

2026-09-12。Peter 回覆「Ok，往這個方向執行」，確認 Backend、Frontend、
Migration 納入同一發布批次，包含 V049。Gate 2 已確認；Gate 3 完成；
**Gate 4：Peter 已於 2026-09-12 以「同意」核准準備階段 A–C。**
此回覆直接承接書面準備計畫核准問題；Gate 5 開始。不含正式部署／V049 live
套用／Provider，這些仍需另行核准。下方待核准及靜態結果文字保留為提出時紀錄。

2026-09-12 補充授權：Peter 回覆「是」，直接同意為已建置的三個
`0.1.0-chg299-v049` 候選映像執行 Docker Scout，允許向 Docker Scout
外部服務傳送套件清單／SBOM 中繼資料以完成掃描。沿用既有掃描工具與精確
image IDs；不包含上傳工作區／現行資料、push image、部署、產品修正或模型呼叫。
這解除先前 scanner metadata 傳輸的授權阻擋，不豁免任何安全／驗收門檻。

## 1. 結論與範圍

V049 已在 main 的正式 migration 目錄，不建立平行功能或第二套成員權限邏輯。
這次把它與已核准、尚未部署的 CHG-293..299 累積修正作為同一候選版本驗證。
本文件取代 CHG-299-DEPLOY-UNDERSTANDING.md 中「保持舊 Migration、不套 V049」
的候選組合建議；保留歷史文件與核准，不追溯擴大任何舊部署授權。

同一發布批次不代表三個服務必須同時啟動，也不預先承諾只需一個 Helm revision。
既有規格要求 migration 成功才解除新應用 rollout gate；維持此順序並驗證。
若現有部署機制不能證明順序，停止該發布步驟、提出修正討論，不擅自改 chart。

產品規格不變：SPECIFICATION.md 10.48 PROJECT-012/PROJECT-010、10.50–10.56
已批准行為；MIGRATE-001、DEPLOY-004/006、FESEC-004、TEST-002/005。
不新增 API、權限、資料處理或 UX 行為。V049 SQL 不改寫、不併入歷史 migration。

## 2. 已知證據與未完成項目

| 項目 | 已知狀態 | 本次處理 |
| --- | --- | --- |
| V049 SQL 與角色相容性 | 隔離真實服務 13 主測試、五組各 22 子測試通過；非全產品驗收 | 保留證據，後續再綁定新三映像測試 |
| 主線及來源 | HEAD `bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3`，工作區另有累積未提交修改 | 使用經盤點的工作區內容；不僅依 Git commit 宣稱建置內容 |
| 現行部署 | 最近唯讀證據 revision 36／CHG-292／V048 | 重新唯讀確認；不得沿用舊 render／image／Secret 雜湊批准新部署 |
| 真實資料備份 | 已確認位置、加密、保管與保留；尚未備份 | 沿用獨立備份計畫的完整保護界線 |
| 原 11 項失敗案例 | CHG-298 R2 為 10 PASS/1 FAIL；CHG-299 修復 S3，28＋88 局部回歸通過 | 原 11 項在同一候選來源完整重跑，不加總舊結果冒充新全過 |
| 完整回歸／coverage | 先前 Backend／Frontend 全來源 coverage 未達各 80%；完整 E2E 未完成 | 重取全套證據；不得放寬、隱藏或視為已被核准豁免 |
| 候選安全／映像 | CHG-294 R2 安全結果屬舊 Frontend 產物 | 新三映像分別 smoke、掃描、SBOM，不能沿用舊 PASS |

證據索引：CHG-291-V049-REHEARSAL-RESULT.md、CHG-293-VERIFICATION.md、
CHG-294-R2-FULL-ACCEPTANCE.md、CHG-295-BUGFIX-VERIFICATION.md、
CHG-296-VERIFICATION.md、CHG-297-VERIFICATION.md、CHG-298-R2-VERIFICATION.md、
CHG-299-VERIFICATION.md。各文件保留自身來源、日期、失敗與受測界線。

## 3. 候選內容與變更原則

- Backend：既有 Editor 內容權限、共享唯讀對話／作者、候選切片刪除完整性、
  cursor／active-version 證據防護、同步 generation／graph job／idempotency、
  S3 同步停在待手動萃取，以及已存在的單一成員角色相容程式。
- Frontend：已核准共享對話／作者／唯讀 UI、安全依賴／base image 與相關修正。
- Migration：完整既有 V001–V049（依目錄實際清單核對）；只允許現行 V048
  向前套用未執行的原 V049。不變更 V001–V048 checksums，不加入 V050。
- V049 SHA-256 固定為
  `b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`。
- 建議本次三個候選標籤同為 `0.1.0-chg299-v049`，repositories 為
  `nomosmart/backend`、`nomosmart/frontend`、`nomosmart/migrations`。
  建置前檢查衝突；不覆寫任何已存在且內容不同的 tag，不推送 registry。
- 預期設定 `compatibility.schemaContract=forward-v049`；這是發布相容標記，
  **不是完成 V049 的證據**，仍需實際 Flyway checksum／constraint／資料驗證。

允許在準備計畫核准後調整：本計畫列明的備份工具、既有隔離測試執行／來源綁定
工具、累積需求對應的真實測試與安全證據文件。保留原斷言與測試數量，不直接
修改產品程式、migration、依賴版本、Dockerfile、chart 或安全／coverage 門檻。
若驗證發現新產品缺陷、真正的契約衝突或高風險依賴，先回報並討論修正。

## 4. 準備階段（本次 Gate 4 的核准範圍）

### A. 固定候選與整理同源證據

1. 列出相對目前部署的累積變更，建立 frontend/backend/migrations/config/tests
   的完整檔案清單及 SHA-256；包含已核准未提交檔案，排除私有 .env、憑證、
   dependency/generated folders。保留原工作區，使用新私有隔離建置／測試副本。
2. 檢查每項已核准需求與對應測試；執行 spec:doctor、spec:trace、plan:approved、
   test:plan、backend:syntax、diff hygiene。測試或來源更動後重新綁定，受影響
   的舊報告不得充作新候選通過證據。

### B. 全套驗證與新映像

1. 使用新建真實隔離 PostgreSQL、Keycloak、Redis、S3、OpenSearch、Neo4j 與
   必要測試應用服務，使用自建資料及新憑證，不載入目前 MAAS 資料／Secrets。
   採既有 exact run-owned receipts／cleanup；禁止 prefix cleanup 或共享資源刪除。
2. 跑累積修正對應測試與完整 Backend／Frontend suite、全來源 coverage，
   保留所有 failure／blocked。V048 與 V049 的角色相容／Owner／拒絕／並行測試
   都保留，完整主驗收以 V049 為候選資料庫版本。
3. 原 11 項、共享唯讀歷史、Editor 操作與禁止治理變更、Chunk 刪除／FK／UI
   conflict、同步 generation／S3 手動萃取、V049 單角色 reload 和端到端治理
   均列入矩陣。真實成功流程不能手填 completed pipeline／固定向量來替代。
4. 本準備階段不授權新的 Provider／billing 呼叫。需要真實模型的正向案例列為
   BLOCKED，沿用現有模型的測試方法提出具體合成內容、目的地及呼叫上限再核准。
   舊 CHG-298 R2 的 20 次核准不自動轉成新 run 額度。這不阻擋無 Provider 的驗證。
5. 以同一候選建置三個新映像，lockfile／Dockerfile 不變；正常 build 可存取原
   Dockerfile／lockfile 指定的套件與映像來源。不得上傳工作區或登入新 registry。
   Registry/scanner 若要求新的資料分享或權限，先說明，不繞過限制。
6. 三映像分別記錄 image ID／平台／建置來源；非 root／安全設定及實際 runtime
   smoke；執行依賴、靜態、三個 container 的 High/Critical 與全嚴重度掃描及 SBOM。
   使用已安裝掃描工具，不自動增設工具、豁免或壓低偵測結果。
7. 新 Migration 映像在自建 V048 DB 上跑真正 Flyway→V049，核對全部歷史
   checksum／預期資料／constraint；新 Backend/Frontend 在該 DB 驗證整合，
   並測試已綁定 CHG-292 回退候選在 V049 上的受測相容性。
8. Compose config／Helm lint／設定安全檢查與必要隔離整合檢查納入發布矩陣。
   不可直接在現行 stack 執行可能啟動服務或改資料的通用 harness。

隔離資源上限沿用有界方式：最多八個容器同時存在、aggregate limits 不超過
8 CPU／12 GiB；映像建置與大型 stack 測試依序，不能靠同時啟動超量服務加速。
真實資料備份還原階段與此測試 stack 不並行，採備份計畫更嚴格的獨立限制。
執行與來源相關的真實測試，不以 mock、skip 或新的 exclusion 提高 coverage。
若完整門檻未達，列精確缺口和下一步，不能宣稱已具部署資格。

### C. 現行資料備份及唯讀部署預檢

1. 納入 `CHG-291-V049-LIVE-BACKUP-PLAN.md` 的全部來源、密碼、加密保存、
   network-none/tmpfs restore、比對、保留及精確清理限制。本整合計畫核准後
   可開始其工具與自建資料安全測試；實際加密匯出仍由 Peter 在自己的 Terminal
   輸入密碼。未完成備份不當作通過，不在 chat 收取密碼。
2. 唯讀確認 revision／Pod／來源／成員／Owner 新基線，並盤點新部署必要的
   schema、資料表摘要、七組 PVC/PV、Secrets UID/摘要、Ingress UID/allowlist、
   身分／支援服務、模型、對話／usage、build／vector／manifest、搜尋／圖譜摘要。
   只輸出安全摘要，不把 Secret、模型金鑰、文件原文寫入報告。
3. 盤點 writer：Backend API、Worker、Beat、排程／正在執行工作、其他可能寫入
   的服務；提出維護窗口、drain／停止／恢復的精確對象與等待上限。
   本階段僅盤點，不實際停止、縮放、重試或清空佇列。
4. 以新三映像、fresh reuse-values 產生 hidden-Secret server-side dry-run，
   計算可重現 canonical render SHA-256。預期下一 revision 由當下 Helm 狀態
   決定，不重用舊 revision-37 render，不覆蓋已存在 Job。
5. 明列 migration／bootstrap／init 的順序與 operational writes。目前 chart 的
   migration 是一般 revision-named Job；僅有 wait-for-jobs 或 compatibility
   標記不能直接證明它一定早於新程式 ready。必須檢查／隔離驗證實際 gate；
   如需改程式或額外部署階段，先呈交，不把「同批發布」解釋為略過順序驗證。
6. Dry-run 只驗證 render／API admission，不執行 Job、不套 V049，不能當作真實
   schema／bootstrap／Ingress／CNI／容量驗收。若新安全基線／schema 超出本
   計畫，停止並列差異，不擅自套用。

## 5. 正式部署階段（另行核准，現在不得執行）

準備通過後提交一份精確 deployment scope，綁定三個 image IDs、來源 hash、
實際 chart／values／render SHA、來源／目標 revision、保護基線、維護窗口、
有限 operational writes、V049 前後差異和回退條件。

後續核准範圍須包含：

1. 精確 writer drain／凍結方式、等待上限與維護告知；不刪現有工作。
2. 維護窗口內重新取得新備份與驗證，作為真正 migration 前的復原點；準備期
   在線備份不能替代。檢查角色差異仍符合核准名單；Owner 矛盾先人工確認。
3. Flyway V049 完成及 checksum／唯一約束／Owner parity／資料差異通過後，
   才解除新程式 rollout gate。原 V049 及其 audit/history 是唯一 schema/data
   migration 改動；bootstrap operational writes 另外逐項界定，不宣稱零寫入。
4. Backend／Worker／Beat／Frontend init 使用同一新 Backend，Frontend main
   使用同批新 Frontend；Migration 使用本次新 Migration。保留既有 audit Jobs。
   不更換周邊服務映像或 PVC／Secrets／Ingress／身份／搜尋資源。
5. Rollout 使用相應 Helm 版本支援的 rollback-on-failure、wait、wait-for-jobs、
   timeout；精確命令在部署 scope 中才定稿。
6. 驗收包括 Flyway／資料保留、服務 health/readiness、雙向內部連線、host HTTPS、
   OIDC／登入、唯讀角色及畫面檢查；任何需要新增／更改真實資料或模型查詢的
   現場驗收，另列 exact scope，不隱含在「健康檢查」內。

V049 成功後若應用 rollout 失敗，優先回到已實測相容程式並保留 V049。
Helm rollback 不會還原被移除的 Viewer row；不得退到允許多角色寫入的舊程式。
整庫還原為另一項操作，可能失去備份後寫入，必須保持停寫、另行核准，不自動執行。
若 migration 失敗，確認原交易回滾與歷史狀態，不使用 repair／clean 偽裝成功。

## 6. 輸出與 Gate 4

準備輸出：同源測試／coverage 報告、三映像來源／ID／安全／SBOM、加密備份與
還原證據、唯讀保護基線、hidden-Secret dry-run／canonical render 與完整缺口表。
規劃位置：`docs/CHG-291-INTEGRATED-RELEASE-RESULT.md`／`-EVIDENCE.json`，
實際執行後才新增，不能預填 PASS。測試分組見 TEST_PLAN.md V49-I01..I08。

待核准的是以上**準備階段 A–C**：測試／備份安全工具、隔離無 Provider 驗證、
三映像建置與安全檢查、規定方式的加密備份／隔離還原、唯讀預檢及 dry-run。
不授權產品修補、Provider、live DDL/DML、停止現行服務、Job 建立或實際部署。
核准前只做本次文件整理／靜態治理檢查。

### 本次文件檢查

2026-09-12：`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`test:plan` 與
`git diff --check` 通過。`./HARNESS/harness.sh plan:approved` exit 1，正確
指出新準備計畫 Gate 4 待核准。未執行新功能測試、建置、備份、dry-run、
Provider 呼叫或現行環境變更；只有讀取來源及整理上述治理文件。

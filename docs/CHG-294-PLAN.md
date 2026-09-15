# CHG-294 Frontend Security Dependency And Base Image Remediation

日期：2026-09-10。**目前版本 R2：Peter 已核准 Gate 4。**
R2 repository 結果：[R2 驗證紀錄](CHG-294-R2-VERIFICATION.md)。未建置新應用映像或部署。
最新範圍與計畫見 [R2 計畫](CHG-294-R2-PLAN.md) 與 DEVELOPMENT_PLAN.md 首段。
Peter 先以 `同意` 確認追加 Node 24.21.0 並先更新計畫、保持現有環境不變，
再以 `Peter approves CHG-294 R2 Bundled Node OpenSSL Remediation` 核准實作。
下方 R1 範圍、核准與執行結果均作歷史紀錄，不取代 R2 Gate 4。

歷史 R1：Peter 已核准 Gate 4，有界實作與隔離驗證已執行。
Peter 曾核准原範圍 Gate 4；初次驗證遇到追加範圍而停止。最新 `OK` 確認
追加範圍並要求提出修訂計畫；本次另收到下方精確 R1 核准，不重用舊核准。

## 確認範圍

只修補 Frontend 安全相依與基底，保留 CHG-293 Editor 內容權限、共享唯讀歷史、
作者姓名，以及既有登入／Markdown／引用功能。接受官方 AVIF 最佳化安全限制，
不新增不安全 fallback，不修改既有文件與圖片。

| 項目 | 計畫目標 |
| --- | --- |
| Next.js / eslint-config-next | 16.3.3；必要 Next env/SWC/plugin 隨 lock 對齊 |
| sharp | override 0.35.4；必要 native/libvips lock entries 同步 |
| R1：browserslist | 4.28.7；有界 transitive override／lock 修補 |
| R1：js-yaml | 既有 override 更新至 4.3.2 |
| R1：baseline-browser-mapping | 2.11.0；有界 transitive override／lock 修補 |
| R1：Vitest／coverage | vitest、@vitest/coverage-v8 4.1.11，必要 mocker／peer closure 對齊 |
| openssl / libssl3 / libcrypto3 | Alpine 3.24 的 3.5.8-r0；四階段共用明確 base |
| 保留 | Node 24.20.0、React/React DOM 19.2.3、musl/arm64、UID 10001、Backend/Migration 生產程式及所有現有資料 |

研究及官方來源沿用
[安全研究](CHG-293-FRONTEND-SECURITY-REMEDIATION-RESEARCH.md)。版本是有界修補目標，
不是永久最新或無漏洞保證。base digest 已經唯讀解析，詳見
[部分驗證結果](CHG-294-VERIFICATION.md)；尚未建置映像或證明 OS 已修補。

## 分階段授權

1. **R1 已核准：repository 實作與隔離驗證。** 修改 package.json、lockfile、
   Dockerfile，以及必要測試／文件。審核每項相依差異；真實 npm/Next/native 圖片、
   OIDC／API／Markdown／CHG-293 回歸。僅可用精確界定的 disposable 測試服務／
   schema／realm；不可操作 Docker Desktop 現有資料或呼叫 Provider。
   追加三份 chg282MarkdownViewer、chg285ChunkSelectionGroup、homeMetrics
   測試資料的型別修正，保留既有斷言；以必跑的真實瀏覽器尺寸檢查取代幾何 mock。
   補齊隔離副本 .gitignore／Keycloak theme，排除舊 build/型別快取與私密設定。
2. **另行核准：Frontend 映像建置與 dry-run。** 新候選預計
   `nomosmart/frontend:0.1.0-chg294`；實際 arm64-musl crypto／sharp smoke、完整
   掃描與 SBOM，再依 fresh baseline 做兩次 hidden-Secret canonical dry-run。
   不重用舊 Frontend image ID/render hash，不建立 Helm Jobs。
3. **再次另行核准：實際部署。** 綁定新 image/render、當時 release 與保護基線，
   明列 Backend 候選重用、Migration、rollouts、bootstrap operational writes、
   維護與 rollback。不能把既有 idempotent Jobs 視為沒有寫入。

不包含 V049、資料修復、role/group/member 變更、圖譜修復、文件重處理、
re-embed、reindex、manifest switch 或 Provider。出現需要額外升級、無法取得
固定版本、未知相依漂移或超出範圍的功能修正時停止並回報。

## 測試與風險

正式計畫：[DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 的 CHG-294。
規格：[SPECIFICATION.md](../SPECIFICATION.md) 3.1／10.51，FESEC-001..004。
測試：[TEST_PLAN.md](../TEST_PLAN.md) CHG-294 T01..T16（R1 新增 T13..T16）。
追蹤：[TRACEABILITY.md](../TRACEABILITY.md) CHG-294 與重新開啟的 DEPSEC-002。

重點是鎖定安裝、native musl/arm64、OS 與 Node crypto 分開驗證、AVIF 安全行為、
OIDC/session/proxy、Editor/Owner/Viewer 與雙 Chat surface 的真實回歸。
原 4 Critical／8 High 未豁免；新掃描出現未接受 High/Critical 仍停止交付。
完整 frontend/backend 各自 80% coverage 與 E2E 缺口仍保留，不以局部 smoke 取代。

歷史 Gate 3 只跑規格／計畫／追蹤／測試設計與 whitespace 檢查。
當時 `plan:approved` 正確拒絕未核准的計畫，沒有沿用 CHG-293 approval。

2026-09-10 Gate 3 文件檢查結果：`spec:doctor`、`spec:trace`（五項 mappings，包含既有
安全門檻）、`plan:doctor`、`test:plan` 與 whitespace 檢查通過；`plan:approved`
exit 1，明確拒絕 CHG-294 尚未核准的 Gate 4，符合預期。package.json、lockfile
及 Dockerfile SHA-256 與研究時相同；未執行功能、映像或部署驗證。

## 歷史原範圍 Gate 4 核准（2026-09-10；不適用於 R1）

`Peter approves CHG-294 Frontend Security Dependency And Base Image Remediation`

只核准上述 repository 修補與隔離非 Provider 驗證，不包含映像建置、Kubernetes
dry-run／部署或目前環境資料變更。

## 歷史結果：原範圍部分完成；當時 R1 等待核准

已更新核准的 Next／sharp 相依及 Dockerfile。乾淨隔離安裝、lint、三項靜態
包裝檢查與原生圖片 smoke 通過；完整 build 因既有測試資料的型別缺漏失敗。
完整 npm audit 另發現範圍外的 2 High、4 Moderate 套件項目，沒有豁免。
原核准計畫要求出現此情況即停止；沒有擅自增加升級或修正測試。

Peter 當時的 `OK` 確認四組相依、三份測試資料／真實瀏覽器斷言修正及隔離
測試資源的追加範圍。R1 正式計畫寫入 DEVELOPMENT_PLAN.md 後等待另行核准。
原產品行為、Backend 生產程式、資料、映像建置／部署與 Provider 邊界不變。

詳細版本、測試失敗、來源與保存證據見
[CHG-294 部分驗證報告](CHG-294-VERIFICATION.md)。目前不可宣稱可部署。

## 已收到修訂計畫核准（2026-09-10）

`Peter approves CHG-294 R1 Additional Security Dependencies And Test Contract Remediation`

已收到上述核准，可繼續追加修補與隔離測試；新發現需額外修正時仍停止回報。

歷史 R1 Gate 3 文件檢查：spec:doctor、spec:trace（五項對應）、plan:doctor、test:plan 與
git diff --check 通過；plan:approved 正確以 exit 1 阻止未核准的 R1 執行。
當時僅更新文件，相依、Dockerfile、三份測試與既有測試 helper 雜湊均未改變。

## R1 實作與驗證結果

追加相依與三份測試資料修正已完成；幾何測試已改用必跑的真實 Chrome 量測。
完整／production npm 與 Python 相依掃描為零已知漏洞；乾淨 build、lint、
150 契約、94 元件、48 真實 DB/OIDC 測試，以及 native／Next HTTP 圖片驗證通過。
Frontend 全域 coverage 與 Backend 完整 coverage、完整 E2E 仍未達交付門檻；
不能宣稱可部署，也沒有沿用舊映像的安全結果。

詳見 [R1 驗證報告](CHG-294-R1-VERIFICATION.md)。映像建置／掃描／SBOM、
Kubernetes dry-run 與正式部署仍分別需要後續授權。

## 後續交付請求（2026-09-10）

Peter 在上述缺口揭露後表示 `可以部署`。依既有分階段計畫，先執行 Stage A
映像準備與唯讀 dry-run 前提，不將此句視為 coverage／E2E／安全豁免，亦不
取代 Stage B 新 image/render／基線／bootstrap 寫入範圍的精確核准。
範圍與執行結果另記於 [映像準備紀錄](CHG-294-IMAGE-PREPARATION.md)。

Stage A 結果：新 Frontend 建置、實際 arm64-musl functional smoke、候選
High/Critical 掃描與 SBOM 已完成；Node 內建 OpenSSL 仍為 3.5.7，系統則是
3.5.8-r0，符合既有需停下審查 runtime 追加範圍的條件。尚未執行 dry-run／部署，
目前環境仍 revision 36。提出 Node 24.21.0 的 R2 理解／範圍確認，未擅自改碼。

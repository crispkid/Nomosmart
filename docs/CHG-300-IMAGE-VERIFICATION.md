# CHG-300 新映像建置與隔離驗證

日期：2026-09-13，規格 §10.57。接續 Peter 的 `Ok，繼續`，完成已獲准的本機
Backend／Migration 建置及真實隔離驗證。**未部署；外部安全掃描尚未執行。**
最新指示：Peter 要求 `不掃描，直接部署`；不再等待或執行 Scout 掃描。
部署資料保護及其他未完成門檻另列於 [部署理解](CHG-300-DEPLOY-UNDERSTANDING.md)，
以下外傳待核准文字只保留作為當時歷史，不是繼續掃描的要求。
計畫：[映像階段](CHG-300-IMAGE-VERIFICATION-PLAN.md)。
機器證據：[來源、映像、artifact hashes](CHG-300-IMAGE-VERIFICATION-EVIDENCE.json)。

## 已完成

- 建置 `nomosmart/backend:0.1.0-chg300`（38.87 秒）。
  Image ID：`sha256:21283c4f28bb05cc444c416b8020ddd34719235ba56b8c64d51b42a786392ef2`。
- 建置 `nomosmart/migrations:0.1.0-chg300`（11.76 秒）。
  Image ID：`sha256:7c8c3625d3e965d9fd1e333ac4f2a55c8c432306312bb19f350baaf6085619e6`。
- 平台 linux/arm64；171 個安全 build inputs 的 source digest：
  `a1ddd517774f4f14905a26211382950edc42787a827a5ff98da347b50ae5f363`。
  build 使用排除憑證／generated／依賴目錄的私有快照，不靠 HEAD 代表累積工作區。
- Frontend main 未重建；舊 image tags/IDs 未覆寫或刪除。沒有 push/prune。

## 真實映像驗證

不是掛入 host app／SQL 的 source-only 測試：

| 驗證 | 結果 |
| --- | --- |
| 新 Backend 映像內 app hash 與凍結來源比對 | PASS |
| 新 Migration 映像內全部49份 SQL hash 比對 | PASS |
| Migration gate53項測試 | 53 PASS，6.34秒；模組 coverage95.37% |
| 新 Backend／真實 V048 DB 角色及 OIDC API | 22 PASS |
| 新 Backend／真實 V049 DB 角色及 OIDC API | 22 PASS |
| 換回既有 CHG-292／保留同一 V049 DB | 22 PASS |
| 真實 V048→V049、無 history、baseline-only、失敗 V049、wrong checksum、CLI拒絕 | PASS（包含於 gate setup／53項） |
| V049 migrate 重跑／資料與 history 比對 | PASS，無新增異動 |
| Secret wrapper覆蓋故意錯誤的 inherited password，再 validate真實 DB | PASS，49份 migrations validate成功 |
| 新映像非 root／唯讀 rootfs＋有界 `/tmp` tmpfs | PASS |
| run-owned清理、既有Docker baseline及app/SQL来源一致 | PASS |

Flyway 實際輸出 **OSS Edition13.6.0**；Java 為 Temurin25.0.4+7，Migration UID10001。
保留 `/flyway/licenses/LICENSE.md`、`LICENSES-THIRD-PARTY.txt` 及對應 notices；
PostgreSQL module13.6.0、JDBC42.7.12 存在。未切換 commercial edition、未新增
license/token/EULA接受動作。[官方 Docker 說明](https://documentation.red-gate.com/flyway/reference/usage/flyway-docker)
區分 `flyway/flyway` Open Source 版與 `redgate/flyway`；仍保留所有官方 bundled libraries，
此處不是已完成每個第三方套件的安全／法律審查。

Flyway 提示預設 `sql` 位置未來可能棄用；本次實際 migrate/validate成功，未擅自
改 SQL 路徑或 wrapper契約。這是待追蹤的相容性警告，不是此次 migrate失敗。

V049原始SHA256：`b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`。
新 Migration映像實際 Flyway checksum：`-1579162252`，與來源階段一致。

## 清理與資料界線

Build目錄 `/private/tmp/chg300-images-xyb3vm8y`；最終隔離run `v49-19b44028fde7`，
證據目錄 `/private/tmp/chg300-image-lab-l_vn5j70`。
最多4個同時存在容器（3服務＋1測試），受既有runner CPU/記憶體限制；
internal network、無公開port、全新測試憑證／DB，未掛現行volume或Docker socket。
自建容器、volume、network、測試密碼／private journal已清理，保留新映像及報告。
14個既有容器與既有資源baseline保持一致；不代表盤點或改動了Kubernetes內的應用。
沒有現行DB／MAAS／Neo4j／OpenSearch查詢／修改、備份、重建、Provider呼叫或部署。

完整保留四組 JUnit XML 與 coverage JSON：gate 53項，以及 image-48、image-49、
rollback-49 各22項；零 failure/error/skip。角色模組 `project_roles.py` 三組均100%，
不代表整個Backend達100%。每份檔案SHA256記錄於機器證據。

報告收集曾有兩次問題，原始證據均保留：第一run `v49-25301551330d` 執行日誌
全數通過，但停止唯讀容器後無法用 `docker cp` 保存新映像的tmpfs報告；第二run
`chg300-image-lab-wdk4m8tt` 的53項通過後，即使容器仍運行，`docker cp` 同樣失敗，
因此中止而未執行API矩陣。這兩次不能冒充最終完整驗收。修正runner為保持容器
運行、核對真實測試exit code，再用 `docker exec cat` 讀取原始報告位元組，最後
清理。最終重跑四組皆通過且檔案齊全；没有重建映像、修改產品程式或降低測試門檻。

## 唯一被拒絕的本階段動作：外部 Scout 掃描

auto-review拒絕了新image IDs的Docker Scout套件／SBOM metadata傳輸。
原因：先前明確外傳核准只綁舊映像；`Ok，繼續`未明確同意新ID、payload與目的地。
拒絕發生在執行前：沒有啟動掃描命令、沒有新SBOM／CVE報告，也沒有改用其他
外部服務繞過。**不能宣稱舊4 Critical／32 High已清除，也不能沿用舊掃描PASS。**

待Peter核准的精確範圍：

> 允許上列兩個CHG-300精確image IDs的套件清單／SBOM中繼資料傳送至Docker Scout，
> 產生SPDX SBOM、全嚴重度CVE報告及High/Critical門檻結果；不push映像、不傳送
> 業務資料或另上傳原始碼、不部署、不呼叫模型Provider。

## 命令與剩餘門檻

已執行：

```sh
backend/.venv/bin/python -B backend/scripts/chg300_image_preparation.py snapshot
backend/.venv/bin/python -B backend/scripts/chg300_image_preparation.py build --root /private/tmp/chg300-images-xyb3vm8y
backend/.venv/bin/python -B backend/scripts/chg300_image_checks.py --root /private/tmp/chg300-images-xyb3vm8y
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh helm:lint
git diff --check
```

上述命令最終驗證通過；較早報告收集失敗如上列明。scan命令未獲允許，故不列PASS。
新增有界build/scan入口及image smoke runner；保留原gate測試，只新增image模式的
映像內位置／hash校驗，沒有降低53項測試或80%覆蓋門檻。產品程式、SQL、UI不改。

95.37%只涵蓋migration verifier；3×22是矩陣重複執行，不是66種不同案例。
ASGI經真實PostgreSQL與Keycloak，不能代替瀏覽器／全服務HTTP／Pod驗收。
TLS專項、完整雙端80%coverage／E2E及其餘既有發布失敗、現行加密備份／保護基線、
停寫窗口、嚴格migration-before-rollout順序與精確部署核准仍未完成。

# CHG-301 R2 交付與正式安裝依賴初步盤點

2026-09-16 Asia/Taipei。**唯讀原始碼盤點，不是新掃描或安全通過。**
Peter已確認範圍；本文件支援[修訂計畫](CHG-301-R2-DELIVERY-SECURITY-PLAN.md)。
以下版本是repository目前宣告，不表示registry最新版本、目前部署值或已掃描實物。
既有工作樹包含main整合與先前核准修改，均保留，未執行Git/部署寫入。

## 範圍判斷

- IN_SCOPE_DELIVERY：交付原始碼、實際提供的binary及隨附相依。
- IN_SCOPE_INSTALL：受支援安裝路徑會下載、建置、建立或執行的元件。
- BUILD_INPUT：建置時執行的工具/基底；與final runtime分列，不因多階段而忽略供應鏈。
- EXTERNAL_PREREQUISITE：客戶自行管理、installer只驗證的基礎環境；記錄責任/前提。
- DEFERRED_TEST_INFRA：僅未啟用的隔離測試基礎映像，非正式安裝依賴，保持不啟用。
- UNRESOLVED：用途/平台/artifact不完整；不能自動當作測試或不適用。

分類對象是artifact及用途，不是CVE名稱。相同CVE存在於正式映像時仍需處理。
bundled/external、production/development與選配功能逐路徑列清，不為減少告警
更改預設或悄悄只驗external profile。

## 已確認的正式安裝來源

| 元件 | 程式宣告/來源 | 本輪應如何驗證 |
| --- | --- | --- |
| Frontend | frontend/Dockerfile；Compose frontend；Helm image.frontend | npm鎖檔、Next產物、Node及其內嵌crypto、Alpine套件；最終artifact與來源绑定 |
| Backend / Worker / Beat / bootstrap / readiness | backend/Dockerfile；Compose及Helm共用Backend image | Python runtime/鎖檔、Ubuntu、OCR與文件轉換工具；一個image可重用scan，但各啟動路徑分列 |
| Migration | deploy/migrations/Dockerfile：Flyway13.6.0-alpine固定digest，su-exec與兩支Secret helper | Flyway/Java/OS及helper；V001–V049不修改、不連現行DB；本次不執行正式migration |
| PostgreSQL standalone | deploy/postgresql/Dockerfile：postgres18.4-alpine；Compose postgresql profile | final派生映像、postgres/gosu、helper與CMD；不是只掃原base |
| PostgreSQL cluster | Helm postgresql.cluster：18.4-standard-trixie固定digest | 與standalone為不同artifact，不能共用不同平台/版本的安全結果 |
| CloudNativePG operator | installer/cloudnativepg.py固定1.30.0 manifest/image | installer會install/repair；必須納入，不當成外部Kubernetes本體 |
| Barman Cloud plugin + sidecar | installer/barman_cloud.py固定0.13.0雙image及manifest | PostgreSQL backup路徑啟用時納入；含動態注入sidecar，不能只grep Chart |
| Redis / Sentinel | Compose及Helm redis7.4.2-alpine | 正式bundled用途納入；external時改列客戶依賴，不能把bundled證據缺口抹除 |
| RustFS | deploy/rustfs/Dockerfile：1.0.0-beta.10派生，su-exec/helper | 原binary/OS與最終派生映像、TLS/Secret啟動契約 |
| OpenSearch Compose | docker-compose.yml預設opensearchproject/opensearch2.19.1 | 獨立列帳；舊Compose功能PASS不能替代本輪image安全掃描 |
| OpenSearch Helm | values.yaml與deploy/opensearch/Dockerfile：2.19.6-repository-s3，base固定digest | 與Compose版本不同；核對repository-s3相依與final artifact，不先合併版本 |
| Neo4j | Compose/Helm5.26.4-community | Java/OS/runtime相依與精確artifact |
| Keycloak | deploy/keycloak/Dockerfile：26.0.8 + themes/helper | final映像而非掛入新helper的歷史容器；Java/OS/身分安全契約 |
| Compose edge | docker-compose.yml：nginx1.27.5-alpine | 是正式Compose入口；與純測試Traefik不同，不能一起延期 |
| debug-ports | Compose debug profile：alpine/socat1.8.0.1 | 明列選配診斷用途；不能因非default便視同未交付測試工具，也不自動啟動 |
| package / installer / release CLI | deploy/package、deploy/installer、deploy/release | source/SAST、Secret處理、真實既有CLI回歸；檢查交付內容及runtime需求 |

Frontend base為node24.21.0-alpine3.24固定digest；Backend base為ubuntu24.04，
還有Pandoc/Tesseract/Poppler等原生工具。這些不在npm/pip套件清單內，仍需盤點。
Chart main/init/jobs、installer foundation/application/operational stage與
CNPG/Barman來源須在實作時建立可重現的完整帳列；上表不是完整closure已通過。

## 可延期與客戶前提

- 保留CHG-301 R2 kind測試node/預載映像、測試Cilium/Operator及測試Traefik的
  immutable evidence，標DEFERRED_TEST_INFRA，**不pull/run建立測試叢集**。
- 先前221筆未解High/Critical映像×ID不改成已修復；正式用途是否重疊要逐artifact
  確認，不能把221這個數直接視為全數排除的產品告警數。
- DEPLOY-012要求客戶提供Kubernetes/CNI/CSI/Ingress/LoadBalancer/DNS/企業CA；
  installer不得建立這些基礎環境。此處僅文件化責任與相容性要求，不掃目前叢集。
- Barman要求既有cert-manager，應列外部前提；CNPG/Barman本身可由installer
  建立，仍需正式用途安全證據。類似判斷適用於客戶external DB/LDAP/AD。
- 沒有因使用者提到二進位檔就新增native打包。先列實際artifact及來源；若交付
  清單確有binary但沒有檔案/平台/hash，明列缺口，不假稱已驗證。

## 現有證據與缺口

- HIGH-PR-RESULT已有247項必要artifact/policy regression PASS，但不是全應用
  coverage，也不是本輪正式安裝依賴的完整掃描。
- SECURITY-AMENDMENT-EVIDENCE有來源綁定npm/pip/SAST歷史結果；使用前重核
  exact source/hash/平台/時間與既有接受範圍，不把歷史資料寫成新scan。
- CHG-301-VERIFICATION有實際Compose/helper/migration失敗拒絕與cleanup證據；
  Backend/Keycloak部分是既有image掛新helper，不能代表新版final image。
- 正式候選映像閉包、交付binary清單、全artifact掃描與必要改動回歸仍待執行。
  本次只查檔案；未下載、掃描、建置、featuretest、修改產品或更新PR。

## 本輪文件檢查

spec:doctor、spec:trace（34 mappings）、plan:doctor、test:plan、git diff --check
通過。spec:trace初次將「not yet verified」誤判為已完成，改成NOT RUN後通過；
沒有放寬harness。plan:approved以exit1正確拒絕新Gate4尚未核准。
原HIGH-PR計畫及五支runner/test SHA與前輪證據一致，沒有偷偷修改執行guard。
新書面計畫SHA256：f73b28d6a30d4fc7581a91804b89e11f40065dc240b4d2d997a8358e2f43d1f0。

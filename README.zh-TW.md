CHG-419 現行發布品質：關鍵正常、拒絕、錯誤與資料保持情境必須有合格證據；前後端完整覆蓋率仍需量測，80%改作改善目標。`coverage:check`讀取明示的來源綁定審查（`NOMOSMART_QUALITY_REVIEW`）；`coverage:strict`保留舊全套／80%查驗。`release:readiness`如實列出缺證與風險。明示已簽署v5採`local-risk-reviewed-release`／`assemble-reviewed-local`；舊v4與未驗schema5測試包保留原義。本次沒有實際組包、安裝、正式平台認證、8443切換或發布。

# NomoSmart

CHG-376（2026-10-30）：8443系統主標題與瀏覽器頁標已隨語系切換，英文重新整理後也保持正確。一次前端建置與離線掃描通過，高／嚴重風險0；只更新前端。下方先前頁標缺口為原始觀察，保留歷史證據。[修正與驗證結果](docs/CHG-376-RESULT.md)。

CHG-375（2026-10-29）：安裝收尾及8443更新完成，19443／19444已退役。一次真LDAP登入及使用者／群組／身分頁讀取通過，390px無頁面橫向溢出。英文導覽與內容正常，但系統主標題及瀏覽器頁標仍為繁中，已記錄根因待修。[最少續驗結果](docs/CHG-375-8443-LDAP-UI-RESULT.md)。

CHG-374 本輪進度：清理後的合格候選已套用既有LDAP環境，一般LDAP登入通過；英文頁標缺口保持待修。沿用原建置與掃描，沒有重建／重掃。臨時OIDC入口先前依指示退役，實際OIDC登入仍未驗。[原證據與續驗](docs/CHG-374-RESULT.md)。

[English](README.md) | 繁體中文

CHG-370 歷史快照（2026-10-28；現行品質規則以CHG-419為準）：真網頁審核／發布及31分鐘持續操作／閒置登出驗證通過。Peter 核准後，原環境12組服務密碼已更換並通過消費端驗證；3組在寫入前保留缺口，一般帳號網頁登入仍待確認。原13個運行容器全部健康，容器、映像與資料卷相同，沒有升級資料庫。固定來源的3項FTP高風險已接受至11/27。完整測試、各端80%、其他憑證與可信發布仍未完成，詳見[輪替結果](docs/CHG-370-ORIGINAL-ROTATION-RESULT.json)、[測試缺口](docs/CHG-370-REMAINING-TEST-GAPS.json)及[覆蓋率](docs/CHG-370-COVERAGE-PROGRESS.json)。先前[CHG-369結果](docs/CHG-369-RESULT.md)保留原驗證範圍。

現行部署：[認證契約2與部署指南](docs/AUTHENTICATION.zh-TW.md)。Compose與Helm已移除Keycloak組件；舊教學另列歷史封存。

2026-10-27 最新實測：真 Windows Server 2025 AD／嚴格 LDAPS 的登入、使用者與群組同步、巢狀／主要群組、更名保持身分、停用撤權及1501人成員分段讀取均通過。AD VM 保留，臨時應用已清除，安裝媒體／失敗快照已依核准清理，AD重新開機後可用。[AD結果與限制](docs/CHG-368-RESULT.md)。先前[Helm結果](docs/CHG-367-RESULT.md)限單節點拓樸；本輪未重跑Compose／Helm。

NomoSmart 是企業知識管理平台，可將文件與外部資料整理成容易管理、搜尋及引用的知識內容。

## 1. 專案概述

NomoSmart 會讀取檔案與已連接的資料來源，必要時執行 OCR，再將內容轉成 Markdown，並切成適合搜尋的段落。團隊可以審核及發布不同版本、搜尋內容、查看資料之間的關係，也可以透過對話取得附有來源引用的回答。

平台適合知識負責人、編輯者、審核者、系統管理員、整合開發者與一般使用者。PostgreSQL 保存應用程式資料；Redis 與 Celery 處理背景工作；S3 相容儲存空間保存原始檔與產出內容；OpenSearch 負責搜尋；Neo4j 保存知識關係；登入採外部OIDC或直接LDAP／Windows AD。


## 2. 核心功能

- **從常見來源匯入資料** — 支援 PDF、UTF-8 TXT、Markdown，以及 FTP、FTPS、SFTP、S3 與 HTTP API。
- **整理文件內容** — 執行文件解析與 OCR、產生標準 Markdown、切分段落、加入標籤並建立 Embedding。
- **管理文件版本** — 保存來源檔、文件版本、顯示內容、段落、標籤、引用關係與目前發布版本。
- **審核與發布** — 讓內容依照既定流程完成審核，再發布核准的版本。
- **搜尋與問答** — 提供關鍵字、向量及混合搜尋，回答會標示來源文件、版本與段落。
- **查看知識關係** — 透過圖譜頁面與 API 查看專案、文件、段落及標籤之間的關係。
- **確認回答品質** — 收集單筆回饋、執行 CSV 批次檢查、保留重試歷程並匯出結果。
- **管理平台** — 管理專案、使用者、角色、權限、企業目錄映射、模型服務、System Prompt、API Client、報表與稽核日誌。
- **切換介面語言** — 提供繁體中文與英文介面。

## 3. 系統架構

```text
Browser / API Client
        |
        v
HTTPS Edge / Kubernetes Ingress
        |
        v
Next.js Frontend -----------> FastAPI Backend
                                  |
                                  +--> External OIDC / LDAP / Windows AD
                                  +--> PostgreSQL
                                  +--> Redis <--> Celery Worker / Beat
                                  +--> S3-compatible Storage / RustFS
                                  +--> OpenSearch
                                  +--> Neo4j
                                  +--> Chat / Embedding / OCR / Judge Service
```

應用程式進入 Ready 狀態前，Migration 與 Bootstrap 工作會先更新資料庫並準備必要服務。Readiness Endpoint 會檢查 PostgreSQL、Redis、Object Storage、OpenSearch、Neo4j、Database Migration 與初始化狀態。

## 4. 技術架構

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | Next.js 16.4.1、React 19.2.3、TypeScript 5 | Web Application、內部Session及同源Backend Proxy |
| Backend | Python 3.12、FastAPI、SQLAlchemy、Pydantic | REST API、設定、Domain Logic 與 Persistence |
| Background Processing | Celery 5.5+、Redis 7.4 | 匯入、同步、驗證與排程工作 |
| Database | PostgreSQL 18.4、Flyway 13.6 | 權威資料與 Forward-only Migration |
| Object Storage | S3 相容儲存；Bundled 部署使用 RustFS | 原始文件與產出物 |
| Search | OpenSearch 2.19 | Keyword、Vector、Hybrid 與 Staging Index |
| Graph | Neo4j 5.26 Community | 知識關係與 Traversal |
| Identity | 外部OIDC或直接LDAP／Windows AD | 認證、目錄同步與角色映射 |
| Deployment | Docker Compose v2、Helm Chart 0.2.0 | 單機與 Kubernetes 部署 |

## 5. 專案結構

```text
Nomosmart/
├── frontend/                  Next.js 應用程式、UI 元件與多語系內容
├── backend/                   FastAPI API、背景工作與應用程式服務
├── sql/migrations/            B054 首次安裝基線及 V001–V056 升級歷史
├── deploy/docker/             Docker Compose Runtime 設定
├── deploy/helm/nomosmart/     Helm Chart 與各環境 Values
├── deploy/installer/          支援 Profile 的 Kubernetes Installer
├── deploy/package/            Secret 與 TLS Package 生命週期工具
├── deploy/release/            發布打包與完整性檢查工具
├── docs/                      技術決策與操作文件
└── docker-compose.yml         單機 Deployment Model
```

## 6. 開始使用

目前採**認證契約 2**。每套部署選擇外部 OIDC 或直接 LDAP／Windows AD 登入；兩種模式都直接從一套目錄同步使用者及群組。Compose 與 Helm 已移除內建認證服務組件。

| 需求 | 閱讀入口 |
| --- | --- |
| Docker Compose | [部署操作](deploy/README.md#docker-compose)及[環境設定範例](deploy/docker/nomosmart.env.example) |
| Kubernetes 使用既有服務 | [協定安裝工具](deploy/README.md#helm-installation)、[目標設定](deploy/installer/nomosmart-install.protocol.example.toml)、[values 範例](deploy/installer/protocol-values.example.json) |
| Kubernetes 內建資料服務 | [Helm 操作](deploy/README.md#helm-installation)；企業目錄及選用 OIDC 服務仍由 operator 管理 |
| 本機 Kubernetes | [本機部署指南](deploy/local/README.zh-TW.md) |
| 認證、升級與復原 | [繁中認證指南](docs/AUTHENTICATION.zh-TW.md) |

先準備可信任的 HTTPS、PostgreSQL、Redis、S3／RustFS、OpenSearch、Neo4j、唯讀目錄帳號，以及初始管理員群組的固定 ID。OIDC 模式另需外部註冊的 client 與精確 callback。密碼、加密金鑰及私鑰放在 Git 之外。

公開hostname須解析到預期的edge／Ingress，憑證須由瀏覽器信任。Compose預設綁loopback的80／443；資料服務port留在私有網路，只有明確選用的診斷profile才對loopback開放。

目前原始碼仍**未達發布門檻**：必要情境證據與新版交付資格仍有缺口；80%依CHG-419改為改善目標，原已核准正式平台延期分帳保持。AD專項結果沿用，不等於整體發布合格。詳見[驗證紀錄](docs/AUTHENTICATION-STATUS.zh-TW.md)及[發布狀態](deploy/RELEASE_READINESS.md)。

## 7. Docker Compose

新安裝先複製公開範例；以下指令不覆寫已存在的 operator 設定：

```sh
cp -n deploy/docker/nomosmart.env.example deploy/docker/nomosmart.env
chmod 600 deploy/docker/nomosmart.env
```

啟動前先準備被引用的基礎設施 Secret 與 TLS 檔。Package 工具的 `init --help` 可查產生選項；產生平台設定不會替企業建立目錄帳號或密碼。另提供真實的 `DIRECTORY_BIND_PASSWORD_FILE`、目錄 CA 公開憑證及非秘密 bootstrap JSON，可依[LDAP](deploy/docker/auth-bootstrap.example.json)、[AD](deploy/docker/auth-bootstrap.ad.example.json)或[OIDC](deploy/docker/auth-bootstrap.oidc.example.json)範例準備。所有示範位址、來源 UUID、搜尋範圍及 `admin_group_id` 都要替換成已確認的值；OIDC 密鑰須與外部 client 註冊一致。

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
# 建置本次已檢視的原始碼，或設定相容且已檢視的映像。
docker compose --env-file deploy/docker/nomosmart.env build frontend backend
docker compose --env-file deploy/docker/nomosmart.env up -d
docker compose --env-file deploy/docker/nomosmart.env ps
```

Profile 為 `postgresql,redis,rustfs,opensearch,neo4j`。改用外部資料服務時，才停用相應 profile，並設定實際 endpoint、憑證及 TLS 信任。一般入口由 edge 提供；資料服務的診斷 port 僅綁 loopback。

Migration 與 bootstrap 成功後，在 onboarding 階段由已同步的一般管理員登入；OIDC 管理員另需在系統設定完成重新驗證。接著完成初始化：

```sh
docker compose --env-file deploy/docker/nomosmart.env run --rm --no-deps deployment-finalize
```

成功後將 operator 設定的 `DEPLOYMENT_PHASE` 改為 `operational`，以相同 Compose 設定重建應用服務並確認 readiness。沒有固定初始應用帳密。完整前提、Secret 保管與停止方式見[部署操作](deploy/README.md)。

## 8. Kubernetes 與 Helm

目前協定安裝工具要求 `deploymentProfile=external-services`、既有 runtime／TLS Secret，以及明確由 operator 管理的基礎設施。資料服務可以位於同一叢集；external 不代表公開網際網路服務。

將[目標 TOML](deploy/installer/nomosmart-install.protocol.example.toml)及[非秘密 values JSON](deploy/installer/protocol-values.example.json)複製至 operator 目錄。替換 context、namespace、release、installation UUID、chart 絕對路徑、映像、服務位址、Secret 名稱及目錄 bootstrap 設定；TOML 內相對路徑以該檔案位置為準。`secrets.data` 保持空值，以 `secrets.existingSecret` 引用秘密。

```sh
./deploy/installer/nomosmart-install plan --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install install --protocol-config /operator/path/target.toml
```

目標範例的`values_file="protocol-values.json"`：請將JSON範例另存為這個檔名，或把target改成實際檔名。

`/operator/path` 是待替換路徑。`install` 在需要一般管理員登入時退出碼為 10。先完成真實登入，才能執行 `finalize`；中斷後先查 `status`，再判斷是否 `resume`。

```sh
./deploy/installer/nomosmart-install finalize --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install verify --protocol-config /operator/path/target.toml
```

內建資料服務的 bundled 部署使用 chart 與獨立檢視過的 operator values，仍需 bootstrap、一般管理員登入與 finalize；協定安裝工具不接受 bundled profile。[部署指南](deploy/README.md#helm-installation)列出兩種路徑。目前一鍵入口只使用 `--protocol-config` 與 external-services；原 factory／認證契約1範例已明確封存並排除新版套件。

目前一鍵操作（先在私有目錄建立新檔案，再修改真實設定）：

```sh
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --init-config
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --plan-only
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --confirm-digest REVIEWED_PLAN_DIGEST
```

父目錄須先由操作者建立為700權限。初始化不覆寫任何檔案、不建立秘密或服務。套用確認綁目標、values與chart內容，設定改變需重新檢視plan；回傳10表示仍需一般管理員登入與另行finalize，不代表完成。


## 9. 登入與目錄管理

| 設定 | 目前行為 |
| --- | --- |
| 一般登入 | OIDC 或 LDAP／Windows AD 二擇一，不自動切換備援模式 |
| 目錄同步 | 兩種模式都直接讀 LDAP／AD；預設每天 02:00、`Asia/Taipei`，可改每日時間／時區及手動同步 |
| 人員識別 | 以目錄固定 ID 與內部 UUID 對應，不猜 email／姓名或自動建帳號 |
| 權限 | 由內部角色及專案治理管理，多角色權限取聯集 |
| 登入狀態 | 伺服器管理的 HttpOnly／Secure cookie；前景操作延長 30 分鐘閒置期限，一般登入沒有固定最長時數 |
| 連線設定 | 重新驗證後可從網頁修改；LDAP Bind 與 OIDC client secret 加密存 PostgreSQL，金鑰仍放部署 Secret |
| 緊急存取 | 平時停用，只能由部署 CLI 產生亂數密碼並啟用固定 15 分鐘窗口 |

OIDC 服務須註冊以下精確 callback，替換應用程式 origin：

```text
https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback
```

Discovery、code exchange、PKCE、state／nonce 與 token 驗證由 Backend 負責。瀏覽器不持有上游 Bearer token；本地登出會撤銷內部 session。欄位對應、重新驗證、金鑰輪替及復原見[認證指南](docs/AUTHENTICATION.zh-TW.md)。

## 10. 升級與原始碼開發

目前 migration target 為 `056`：[V056](sql/migrations/V056__native_pdf_cleanup.sql) 分離不可變辨識收據與可清除內容，並建立文件政策新版。新資料庫先套用不變的 [B054](sql/migrations/B054__protocol_authentication_and_sessions.sql)，再套 V055、V056；既有資料庫沿原升級鏈前進。精確 checksum 以 [migration contract](deploy/migrations/release-contract.json) 為準。升級前先停舊 Worker；回復使用升級前快照與舊 API 唯讀驗證，不刪新表或破壞性降版。

協調升級前先暫停舊登入／同步 producer，前後端及 worker 一致升級；保留內部 UUID、角色關係及歷史。既有瀏覽器需重新登入。先從舊 values 移除 `keycloak.*`、`global.keycloakPath`、`bootstrap.keycloak*`、產品 Secret 及 `/identity` 路由，檢視完整新配置，使用 `--reset-values`，不以 `--reuse-values` 帶回舊設定。

實際套用 Helm 升級時，舊 release 管理的認證工作負載、路由及產品 Secret 會列入移除差異。仍需使用的 IdP、資料與憑證須另行保管及獨立管理；本次文件更新沒有清除既有 DB／PVC。

原始碼開發使用[Backend](backend/.env.example)及[Frontend](frontend/.env.example)範例，連接真實的非正式服務。Backend 須設定 `AUTH_BOOTSTRAP_CONFIGURATION`、`AUTH_TRUST_ROOT`、endpoint 白名單、私有憑證及目前 migration target。瀏覽器經可信任的 HTTPS 入口，才能驗證 Secure cookie 與 callback 規則。Frontend 只需公開 origin 與同源 Backend proxy，OIDC 憑證由 Backend 持有。

## 11. 維運、驗證與文件歷史

檢查最後成功同步時間、失敗 run、登入 audit、worker 及 readiness。目錄讀取失敗保留最後成功快照；若不能等下次每日同步，使用手動同步。背景請求不會延長使用者登入。

從 repository root 執行窄範圍檢查：

```sh
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
python3 -m unittest discover -s backend/tests -p test_protocol_deployment.py -v
```

設定檢查不能取代真實登入或正式發布驗收。詳見[E2E 指南](docs/E2E-ENVIRONMENT-GUIDE.md)、[部署清理結果](docs/AUTHENTICATION-STATUS.zh-TW.md)及[現存缺口](docs/AUTHENTICATION-STATUS.zh-TW.md)。

舊 0.2.0 安裝教學已放入[歷史文件](docs/archive/authentication-contract-1/README.md)，目前 checkout 請使用上述現行指南。

## 12. API 與使用方式

### 12.1 API 位置與認證

| Interface | Location | Authentication |
| --- | --- | --- |
| Internal API | `/api/v1` | 伺服器管理的session cookie；寫入請求檢查CSRF與Origin |
| Public Integration API | `/api/public/v1` | `Authorization: Bearer <api-key>` 或 `X-NomoSmart-API-Key` |
| OpenAPI Document | `/openapi.json` | Backend Origin |
| Swagger UI | `/docs` | Backend Origin |
| 產品內 API Guide | `/api-docs` | 已登入的 NomoSmart 頁面 |
| Process Health | `/api/v1/health` | 回傳 `{"status":"healthy"}` |
| Dependency Readiness | `/api/v1/ready` | 回傳 `ready` Detail 或 HTTP 503 |

FastAPI 應用程式版本為 `0.2.0`，API 路徑保留 `/v1`。Backend Authorization 會合併 Local Role Permission 與 Project-scope Owner、Editor、Viewer Governance。

### 12.2 Public Chat 範例

將 Placeholder 替換為 Active Integration API Key、允許存取的 Project UUID 與 End-user Identity。

```bash
export NOMOSMART_API_ORIGIN="<backend-api-origin>"
export NOMOSMART_API_KEY="<api-key>"
export NOMOSMART_PROJECT_ID="<project-uuid>"
export NOMOSMART_IDEMPOTENCY_KEY="replace-with-a-unique-request-key"
curl --fail --silent --show-error \
  --request POST \
  --url "$NOMOSMART_API_ORIGIN/api/public/v1/projects/$NOMOSMART_PROJECT_ID/chat" \
  --header "Authorization: Bearer $NOMOSMART_API_KEY" \
  --header "Idempotency-Key: $NOMOSMART_IDEMPOTENCY_KEY" \
  --header "Content-Type: application/json" \
  --data '{
    "question": "How does this policy apply to onboarding?",
    "end_user": {
      "employee_id": "E12345",
      "employee_name": "Alex Chen",
      "department": "Legal"
    },
    "top_k": 5
  }'
```

成功的 Response 包含 `response_id`、`answer`、`citations`、`status`、選取的 Document/Version Identifier 與 `request_id`。Streaming 使用 `POST /api/public/v1/projects/{project_id}/chat/stream`；Feedback 使用 `POST /api/public/v1/chat/responses/{response_id}/feedback`。

## 13. 開發指令

### 13.1 Frontend 指令

```bash
cd frontend
npm ci
npm run dev -- --hostname 127.0.0.1
npm run lint
npm run build
```

### 13.2 Backend 與部署指令

```bash
cd backend
uv sync --locked --all-extras
cd ..
docker compose config --no-env-resolution --quiet
helm lint deploy/helm/nomosmart
```

## 14. 部署與維運

- **Docker Compose** 使用 [docker-compose.yml](docker-compose.yml)、產生的環境設定檔、受保護的 Secret、Health Check、Named Volume 與單一本機 HTTPS 入口。
- **Kubernetes** 使用 [Helm Chart](deploy/helm/nomosmart)、各 Profile 的 Values、ConfigMap、Secret、Probe、Service、Ingress、NetworkPolicy、Job、資源限制與 Persistent Storage。
- **安裝包完整性**透過 [deploy/release/nomosmart-release](deploy/release/nomosmart-release) 在安裝前檢查。
- **Database Migration** 使用 [sql/migrations](sql/migrations) 內只能往前套用的檔案。Compose 與 Helm 會在應用程式進入 Ready 狀態前完成套用。
- **平台初始化** 透過 Command 或 Kubernetes Job 準備Storage、Search、Graph、認證設定與直接目錄同步，不佈建外部IdP。

第 19 節提供部署與正式環境操作文件。

## 15. 可觀測性

- `GET /api/v1/health` 顯示 Backend Process 是否正常執行。
- `GET /api/v1/ready` 顯示必要服務與初始化步驟是否已準備完成。
- `LOG_FORMAT` 與 `LOG_LEVEL` 控制 JSON 或文字格式，以及 Log 詳細程度。
- `docker compose ps` 與各 Service Log 可查看 Compose 部署狀態。
- Kubernetes Workload 包含 Readiness 與 Liveness Probe。
- Installer 的 `status`、`verify` 與 `doctor` 指令會隱藏敏感值。
- System Management 顯示服務狀態與稽核日誌。

## 16. 安全性

- 登入模式為外部OIDC或直接LDAP／AD；瀏覽器使用共同HttpOnly／Secure session cookie，寫入請求受CSRF與Origin保護。
- Backend每次檢查內部角色及專案權限；不信任前端傳入的身分header。
- LDAP Bind／OIDC client secret加密存DB；加密金鑰、其他平台及商業憑證依部署Secret政策管理。
- 閒置30分鐘登出，持續前景操作可保持登入；背景poll不續期。設定解鎖10分鐘與緊急窗口15分鐘各自獨立。
- 保留TLS／CA／hostname驗證；log不得輸出密碼、token、cookie或callback query。敏感操作保留audit。

## 17. 故障排除

### 17.1 Compose Preflight 回報 Hostname 或 Port 問題

```bash
grep -n "nomosmart.local" /etc/hosts
lsof -nP -iTCP:80 -sTCP:LISTEN
lsof -nP -iTCP:443 -sTCP:LISTEN
./deploy/package/nomosmart-package preflight --runtime compose
```

保留一筆 `127.0.0.1 nomosmart.local` Mapping，並釋放 80 與 443 Port。主機準備完成後重新執行 Preflight。

### 17.2 Compose Service 仍在準備

```bash
export NOMOSMART_DIAGNOSTIC_SERVICE="backend"
docker compose --env-file deploy/docker/nomosmart.env ps
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 "$NOMOSMART_DIAGNOSTIC_SERVICE"
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 migration deployment-bootstrap
```

從第一個未達預期狀態的 Dependency 或 Job 開始檢查。產生的設定與 Named Volume 會保留，完成修正後可安全重試。

### 17.3 Health 成功且 Readiness 回傳 HTTP 503

```bash
curl --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/api/backend/ready
```

讀取 `dependencies` Object，並檢查對應的 PostgreSQL、Redis、S3/RustFS、OpenSearch、Neo4j、Migration 或 Bootstrap Service。

### 17.4 登入或目錄同步失敗

先查公開的`/api/backend/auth/config`確認目前模式，再看安全錯誤碼與最後成功同步時間。LDAP檢查唯讀帳號、搜尋範圍與CA；OIDC檢查實際issuer的Discovery、client註冊及精確callback。未同步、停用或綁定衝突不會自動建帳號。不要停用TLS、猜測人員配對或自動改用另一登入模式。

### 17.5 Kubernetes 安裝暫停

```bash
./deploy/installer/nomosmart-install status \
  --protocol-config "$NOMOSMART_INSTALL_CONFIG"
./deploy/installer/nomosmart-install doctor \
  --protocol-config "$NOMOSMART_INSTALL_CONFIG"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get pods,jobs
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get events --sort-by=.lastTimestamp
```

完成回報的前置條件或 Identity Checkpoint，再執行相同的 Explicit-profile 指令。設定變更會產生新的 Digest，並回到 Read-only Plan 核准流程。

### 17.6 Source Backend 無法連線 Dependency

```bash
cd backend
uv run python -c "from app.core.config import get_settings; print(get_settings().app_env)"
curl --silent --show-error http://127.0.0.1:8000/api/v1/ready
```

依 Readiness 顯示的 Dependency，檢查 `backend/.env` 的 Endpoint、Credential Source、TLS Mode 與 CA Path。

## 18. 安裝驗證清單

- Migration 056及bootstrap成功，應用、Worker與Beat正常，readiness回ready。
- LDAP／AD直接同步成功，管理群組映射正確，真實一般管理員可由所選模式登入及完成finalize。
- 日常權限、30分鐘閒置／前景續期、登出、停用及CSRF有真實證據。
- OIDC使用實際外部issuer及精確callback；只有選用該模式時才需要OIDC服務。
- 模型與文件的匯入、審核、發布、查詢及引用須另做真正業務驗收。
- Windows Server 2025／LDAPS的AD專項已通過，詳見[實機結果](docs/CHG-368-RESULT.md)；其他Windows／SASL等未驗範圍與真正關鍵／交付缺口另列；覆蓋率80%為改善目標，不因此重跑已過AD。

## 19. 相關文件

- [部署指南](deploy/README.md)
- [Docker 設定範例](deploy/docker/nomosmart.env.example)
- [Kubernetes 安裝器範例](deploy/installer/nomosmart-install.protocol.example.toml)
- [外部服務範例](deploy/installer/protocol-values.example.json)
- [Migration 發布契約](deploy/migrations/release-contract.json)

## 20. 授權

NomoSmart 採用 [Apache License 2.0](LICENSE)。

## PDF 原檔直接辨識

所有新 PDF 原檔交給組織明確設定的 OpenAI Responses 文件模型，包含可選取文字的
PDF。TXT／Markdown 直接讀取，不需要辨識模型。本機 OCR、抽文字、轉圖、拆頁及
自動備援已退役。超限、無可信輸入計數或已知不完整回應會停止，不發布部分成果。
輸入計數也會對外提交文件，計數與辨識都可能產生費用。

專案分別顯示「基本模型設定」與「PDF 辨識能力」：基本 Chat／Embedding 有效即可
使用純文字；PDF 另需相容模型。管理員由能力表單填入實際上限，不必手填 JSON；
一般連線成功不等於 PDF 實測成功，表單與進階 JSON 衝突時拒絕保存。

來源可追溯原始文件與版本；沒有可信頁碼就顯示「未知」，不推測頁碼。報表顯示文件數、
真 token 與費用，保留歷史已知頁／圖用量；未知與不適用不冒充零。

文件政策新版只保留併發、整份期限、派送讓出延遲及兩種輪詢間隔。舊解析器欄位、
政策快照及 hash 保留歷史用途。封存必須先確認工作停止與無未知付費結果，再清除
符合條件的未完成內容；不含正文的收據保留原始識別、指紋、用量及稽核。

詳見 [PDF 文件辨識操作說明](docs/NATIVE-PDF-OCR-OPERATIONS.md)。本來源調整不會
自動切換8443；完整測試保留實際統計、各端80%作改善目標，發布依關鍵情境與有效安全／交付證據判定。

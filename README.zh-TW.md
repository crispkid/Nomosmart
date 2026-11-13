# NomoSmart

[English](README.md) | 繁體中文

NomoSmart 是企業知識管理平台，將文件與外部資料整理為可審核、搜尋、引用與問答的知識內容。

版本：**0.2.4**。支援 Docker Compose 與 Kubernetes／Helm；前後端提供繁體中文與英文介面。

## 核心功能

- 匯入 PDF、UTF-8 TXT、Markdown，以及 FTP／FTPS／SFTP、S3 與 HTTP API 資料來源。
- PDF 原檔直接交給已設定的 LLM 產生 Markdown；TXT／Markdown 直接讀取。
- 建立知識切片、標籤與 Embedding，保存原始文件、版本及來源引用。
- 依專案權限送審、退審及發布；保留已完成成果與審核歷程。
- 提供關鍵字、向量與混合搜尋、知識圖譜，以及附來源引用的問答。
- 管理企業目錄、角色、模型、用量、API Client、報表與稽核紀錄。

## 系統架構

```text
瀏覽器 ── HTTPS ── Next.js 前端／同源代理 ── FastAPI Backend
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          │                       │                       │
                 外部 OIDC 或 LDAP／AD       PostgreSQL              Redis
                    登入與目錄同步          設定／版本／權限          工作佇列
                                                                          │
                                                               Celery Worker／Beat
                                                                          │
                               ┌──────────────────────────────────────────┤
                               │                                          │
                       原生 PDF 文件模型                        S3／OpenSearch／Neo4j
                       PDF → Markdown                           檔案／搜尋／知識關係
```

Backend 處理認證、授權、設定與工作派送；Worker 執行匯入及知識處理，Beat 負責排程。Chat、Embedding、PDF 辨識與 Judge 使用組織設定的模型服務。API Client 可透過獨立的對外 API 存取授權專案。

| 元件 | 技術／用途 |
| --- | --- |
| 前端 | Next.js 16.4.1、React 19.2.3、TypeScript；同源 Backend Proxy |
| 後端 | Python 3.12、FastAPI、SQLAlchemy、Pydantic |
| 背景工作 | Celery、Redis；匯入、目錄同步及排程 |
| 權威資料 | PostgreSQL 18.4；Flyway 管理只能向前套用的移轉 |
| 檔案儲存 | S3 相容服務；內建部署使用 RustFS |
| 搜尋／圖譜 | OpenSearch 2.19、Neo4j 5.26 Community |
| 部署 | Docker Compose v2、Helm Chart 0.2.4 |

## PDF 與模型設定

所有新 PDF 都以原檔送至組織明確設定、支援 `openai_responses` 的原生文件模型，包含已有文字的 PDF。新處理路徑不再使用本機 OCR、抽文字、轉圖、拆頁或自動備援。

- 在系統管理中設定服務、模型、價格與實際的 `native_pdf` 能力；系統不依模型名稱猜測容量。
- 專案的基本 Chat／Embedding 設定與 PDF 辨識能力分開；純文字處理不要求 OCR 模型。
- 輸入計數會把文件送至模型供應商，計數與生成都可能產生費用；後續標註及 Embedding 依專案設定處理。
- 超過模型或部署上限、無可信輸入計數、回應截斷或不完整時停止，不自動拆檔，也不發布部分成果。
- 新結果追溯至原始文件與版本；無可信實體頁碼時顯示「未知」，不讓模型猜頁碼。
- 已送出的付費請求若結果不明，不自動重送；先核對原收據及用量。取消工作仍保留已確認的帳務。

詳細能力欄位、傳輸上限、文件預算及復原方式見 [PDF 辨識操作指南](docs/NATIVE-PDF-OCR-OPERATIONS.md)。

## 登入、目錄同步與權限

每套部署選擇 **外部 OIDC** 或 **直接 LDAP／Windows AD** 登入，兩者不自動切換。兩種模式都直接從 LDAP／AD 同步使用者與群組，權限由 NomoSmart 內部角色與專案治理管理。

| 項目 | 行為 |
| --- | --- |
| OIDC | 通用協定介接；由 Backend 驗證 issuer、簽章、audience、state、nonce 與 PKCE |
| LDAP／AD | 以組織目錄驗證帳密，使用可信任的加密連線與 CA |
| 目錄同步 | 預設每天 02:00、`Asia/Taipei`；可設定每日時間／時區及手動同步 |
| 身分 | 使用目錄固定 ID 與內部 UUID；不靠姓名或 email 猜測配對 |
| 角色 | 多角色權限取聯集；view／create／edit／delete 各自判定 |
| 登入狀態 | 共用伺服器工作階段及 HttpOnly／Secure cookie；閒置 30 分鐘登出，持續前景操作可延長登入，背景輪詢不續期 |
| 設定 | 重新驗證後可從網頁修改重要連線設定；Bind／client secret 加密存資料庫，金鑰由部署 Secret 提供 |

Compose／Helm 不部署 Keycloak，也不依賴其 Admin API。OIDC 供應商由組織獨立管理；LDAP／AD 同樣是外部目錄，沒有固定的初始應用帳密。

OIDC 請註冊精確 callback：`https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback`。欄位映射、初始化管理員、緊急存取及復原見[認證指南](docs/AUTHENTICATION.zh-TW.md)。

## 安裝前準備與驗包

準備可信任的 HTTPS、所需資料服務、唯讀目錄帳號、目錄 CA 與初始管理員群組的固定 ID。OIDC 模式另需註冊的 client 與 callback。秘密與私鑰放在 Git 之外，以受保護檔案或 Secret 引用。

下載並解開版本包後，核對公開的 SHA-256，使用從獨立可信管道取得的簽署指紋驗證；不要只因金鑰附在下載包內就信任它：

```sh
python3 deploy/release/nomosmart-release verify-package \
  --package . \
  --purpose local-risk-reviewed-release \
  --trusted-fingerprint "$NOMOSMART_TRUSTED_FINGERPRINT"
```

需要 Python 與 GPG。此版本包為已簽署的本機風險審查格式；既有未驗收測試包與舊格式不能直接改名當成本版發布包。

## Docker Compose

以下在版本包或已檢視的原始碼根目錄執行。先複製公開設定範例，不覆寫既有 operator 設定：

```sh
cp -n deploy/docker/nomosmart.env.example deploy/docker/nomosmart.env
chmod 600 deploy/docker/nomosmart.env
```

依[部署操作指南](deploy/README.md#docker-compose)準備設定所引用的 Secret／TLS 檔，填入已檢視的映像、真實服務及[目錄 bootstrap 設定](deploy/docker/auth-bootstrap.example.json)。使用原始碼時才建置應用映像；版本包應使用其清單指定的映像。

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
docker compose --env-file deploy/docker/nomosmart.env up -d
docker compose --env-file deploy/docker/nomosmart.env ps
```

預設資料服務 profiles 為 `postgresql,redis,rustfs,opensearch,neo4j`。使用既有外部服務時停用對應 profile，並設定真實 endpoint、TLS 信任與秘密。

Migration／bootstrap 成功後，由已同步的一般管理員透過所選模式登入；OIDC 管理員另需完成系統設定重新驗證，再執行：

```sh
docker compose --env-file deploy/docker/nomosmart.env run --rm --no-deps deployment-finalize
```

成功後將 `DEPLOYMENT_PHASE` 改為 `operational`，以同一設定更新應用服務並確認 readiness。日誌、停止與平台設定產生方式見[部署指南](deploy/README.md)。

## Kubernetes／Helm

Chart 支援內建或外部資料服務；協定安裝工具目前使用 `deploymentProfile=external-services`。資料服務可位於同一叢集，external 指由 operator 管理，並非必須在公開網際網路。

將[目標 TOML](deploy/installer/nomosmart-install.protocol.example.toml)與[非秘密 values JSON](deploy/installer/protocol-values.example.json)複製到私有 operator 目錄。替換 context、namespace、installation UUID、chart 路徑、映像、服務、目錄／群組 ID 與 Secret 名稱；TOML 的相對路徑以該檔案位置為準。JSON 另存為範例所指定的 `protocol-values.json`。保留 `secrets.data={}`，以 `secrets.existingSecret` 引用秘密。

```sh
./deploy/installer/nomosmart-install plan --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install install --protocol-config /operator/path/target.toml
# 先完成一般管理員真實登入，再繼續初始化。
./deploy/installer/nomosmart-install finalize --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install verify --protocol-config /operator/path/target.toml
```

`/operator/path` 為待替換路徑。`action-required`／退出碼 10 代表等待一般管理員登入；中斷後先查 `status`，不要反覆重裝。直接使用 bundled chart 的完整設定與初始化階段見[Helm 操作指南](deploy/README.md#helm-installation)。

## 從舊版升級

1. 驗證版本包與映像摘要，保留可回復的既有資料、設定、加密金鑰與 TLS／CA；檢視目標部署差異。
2. 暫停舊匯入／同步 producer，停止舊 Worker／Beat，協調更新 Frontend、Backend、Worker 與 Beat，避免新舊寫入者混用。
3. 使用完整的新認證設定：選定 LDAP／AD 或 OIDC，保留內部 UUID、使用者／角色關係及歷史。移除舊 `keycloak.*` 等部署欄位；Helm 使用已檢視的完整 values 與 `--reset-values`，不要以 `--reuse-values` 帶回舊設定。
4. 讓正常 migration 流程將既有資料庫依序升到 **056**；全新資料庫使用 B054 基線後套 V055、V056。不可重寫舊 SQL 或手動刪除歷史欄位。[Migration 契約](deploy/migrations/release-contract.json)提供目標與 checksum。
5. 為新的 PDF 工作選定相容的原生文件模型，填入能力、價格及輸出預算。舊 OCR 模型、頁面結果、收據與用量保留歷史；舊未完成工作需明確檢視，不會自動改成新請求。
6. 完成 bootstrap／一般管理員登入／finalize，再確認服務就緒、登入及既有資料可讀。舊瀏覽器工作階段需重新登入。

移轉與版本回復是不同操作。不要以刪新表降版，或直接讓舊 Worker 寫入新版政策；依既有快照及相容版本做協調回復。[認證升級指南](docs/AUTHENTICATION.zh-TW.md)與[PDF 操作指南](docs/NATIVE-PDF-OCR-OPERATIONS.md)保留具體限制。發布版本不會自動更新既有部署。

## API、維運與驗收範圍

| 入口 | 用途 |
| --- | --- |
| `/api/v1` | Backend 內部 API；工作階段與後端權限檢查 |
| `/api/public/v1` | 整合 API；獨立 API Key 與專案 scope |
| `/openapi.json`、`/docs` | Backend OpenAPI／Swagger |
| `/api-docs` | 產品內 API 說明 |
| `/api/v1/health`、`/api/v1/ready` | 程序健康與依賴／初始化就緒狀態 |

日常檢查最後成功同步、失敗工作、佇列、稽核日誌及 readiness。目錄同步失敗保留最後成功快照；付費請求結果不明時先核對收據。日誌不應包含密碼、token、cookie 或文件正文。

本版沿用已完成的本機部署、必要業務情境、資料保持、簽署及回復證據。完整來源覆蓋率持續量測，80%為改善目標；必要情境缺證、失敗或未處置重大風險仍會阻擋就緒。正式多主機容量、高可用、正式網路隔離與正式備份資格保留原範圍，不能由本機驗收推論通過。

## 專案結構與開發

```text
frontend/                 Next.js UI、同源代理與多語系
backend/                  FastAPI、模型／目錄整合與背景工作
sql/migrations/           B054 基線及向前移轉歷史（目前056）
deploy/docker/            Compose 設定範例、入口與Secret工具
deploy/helm/nomosmart/     Helm Chart、ConfigMap／Secret引用與probes
deploy/installer/          協定安裝與初始化工具
deploy/release/            組包、簽署及完整性驗證
docs/                     操作指南與保留的歷史紀錄
```

原始碼開發需連接真正的非正式服務，使用[Backend](backend/.env.example)與[Frontend](frontend/.env.example)設定範例。依變更選擇最窄的 harness 檢查；設定語法檢查不等於登入或業務驗收，已通過且未受影響的結果應沿用。

授權條款見 [LICENSE](LICENSE)。

# NomoSmart

[English](README.md) | 繁體中文

NomoSmart 是企業知識管理平台，將文件與外部資料整理為可審核、搜尋、引用與問答的知識內容。

版本：**0.4.1**。支援 Docker Compose 與 Kubernetes／Helm；前後端提供繁體中文與英文介面。

## 0.4.1 更新重點

- **審核路徑**：送審前就會顯示由誰審核（送審者的主管，或在開啟「Owner 備援」設定時由專案 Owner 審核）；主管代理人功能已移除：使用者編輯畫面不再設定代理人，使用者 API 也不再接受或回傳代理人欄位（送出時回 422）；沒有人能審核時直接拒絕送審，不會一直卡住。新增「審核管理」頁面，有權限的管理者可以改派主管階段的審核，或在任何階段退回送審；這個頁面不能核准。送審者即使是專案 Owner，也不能審核自己的送審。
- **修正**：用戶端在回答串流剛開始時離開，現在會記錄為取消（同一個 Idempotency-Key 重送會重播取消結果）；軟刪除殘留清理工具在 0.4.0 的資料結構下恢復可用，殘留資料還有引用時會停止；應用程式金鑰輪替也涵蓋追問改寫與公開回答的重播紀錄；Next.js 升級到 16.4.5。

0.4.1 新增資料庫遷移 V068，請見[從舊版升級](#從舊版升級)。

## 0.4.0 更新重點

- **四站式知識萃取**：每個文件版本依序經過「內容確認、切片、標籤與引用、索引與測試」四站，每一站都要編輯者確認才往下走；可以回到前一站修改，沒變動的切片保留原本成果；可以選取文字手動切片。第 4 站完成後才能送審。文件可以改名，全站名稱不重複。
- **引用與取代關係**：第 3 站會找出引用其他文件的文字，以及「本辦法取代 X」這類取代說明，對應到專案文件並可人工修正。已發布的關係會在專案圖譜顯示連線；問答會帶入題目問到的相關文件；被取代的文件會顯示由哪一份新文件取代。目標文件刪除時，指向它的引用會釋放並重新對應；既有資料可用 `python -m app.deployment.backfill_relations` 修復。
- **跨文件問答更完整**：問「哪些文件引用或取代某文件」時會改走引用資料；一題同時問好幾件事時，會拆成子問題分別搜尋。這些功能與上限在「系統設定 → 問答」管理。
- **審核與文件生命週期更安全**：送審中的文件要先取消送審才能刪除；已刪除文件的已核准版本不能發布；刪除排隊中的文件不會再卡住萃取佇列。外部問答遇到暫時性的模型錯誤會重試，錯誤訊息也更清楚。
- **介面**：處理狀態與設定更新者以文字顯示；輸入框、按鈕與對話框統一樣式；產品內 API 說明新增快速開始。

0.4.0 曾新增資料庫遷移 V064–V067，請見[從舊版升級](#從舊版升級)，特別是已有 0.3.0 文件的資料庫。0.3.0 的內容：[GitHub Release v0.3.0](https://github.com/crispkid/Nomosmart/releases/tag/v0.3.0)。

## 核心功能

- 匯入 PDF、UTF-8 TXT、Markdown，以及 S3 與 HTTP API 資料來源（FTP、FTPS、SFTP 來源已在 0.3.0 移除）。
- PDF 原檔直接交給已設定的 LLM 產生 Markdown；TXT／Markdown 直接讀取。
- 以四站確認流程建立知識切片、標籤、文件間引用與 Embedding，保存原始文件、版本及來源引用。
- 依專案權限送審、退審及發布；保留已完成成果與審核歷程。
- 提供關鍵字、向量與混合搜尋、知識圖譜，以及附來源引用的問答。
- 以單輪或多輪對話測試回答，並以 CSV 批次驗證多輪情境，含 Judge 評分與情境通過率。
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

Backend 處理認證、授權、設定與工作派送；Worker 執行匯入及知識處理，Beat 負責排程。Chat、Embedding、PDF 辨識與 Judge 使用組織設定的模型服務。API Client 可透過獨立的對外 API 存取授權專案；格式相容 Open Responses，產品內的對話測試也透過 `/api/v1/responses` 使用同一份格式。

| 元件 | 技術／用途 |
| --- | --- |
| 前端 | Next.js 16.4.1、React 19.2.3、TypeScript；同源 Backend Proxy |
| 後端 | Python 3.12、FastAPI、SQLAlchemy、Pydantic |
| 背景工作 | Celery、Redis；匯入、目錄同步及排程 |
| 權威資料 | PostgreSQL 18.4；Flyway 管理只能向前套用的移轉 |
| 檔案儲存 | S3 相容服務；內建部署使用 RustFS |
| 搜尋／圖譜 | OpenSearch 2.19、Neo4j 5.26 Community |
| 部署 | Docker Compose v2、Helm Chart 0.4.1 |

## PDF 與模型設定

所有新 PDF 都以原檔送至組織明確設定、支援 `openai_responses` 的原生文件模型，包含已有文字的 PDF。新處理路徑不再使用本機 OCR、抽文字、轉圖、拆頁或自動備援。

- 在系統管理中設定服務、模型、價格與實際的 `native_pdf` 能力；系統不依模型名稱猜測容量。
- 每個專案都需要啟用中、具原生 PDF 能力的 OCR 模型：沒有時，建立專案或修改其 Chat、Embedding、OCR 模型會被拒絕（`project_model_configuration_required`）；既有未設定 OCR 的專案照常使用，直到修改模型時才需補上。
- OpenAI 的 Chat 與 Judge 模型使用 Responses API；連線測試會送出極小的實際請求，分別回報模型不存在、認證失敗或呼叫格式被拒。
- 輸入計數會把文件送至模型供應商，計數與生成都可能產生費用；後續標註及 Embedding 依專案設定處理。
- 超過模型或部署上限、無可信輸入計數、回應截斷或不完整時停止，不自動拆檔，也不發布部分成果。
- 新結果追溯至原始文件與版本；無可信實體頁碼時顯示「未知」，不讓模型猜頁碼。
- 已送出的付費請求若結果不明，不自動重送；先核對原收據及用量。取消工作仍保留已確認的帳務。
- 文件處理仍在背景收尾時送審，會回 `409 document_processing_finalizing`，幾秒後再送即可。

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

已簽署的版本包可用打包工具產生平台 Secret／TLS 檔並帶入清單指定的映像。工具會先驗證版本包，請提供同一個從獨立可信管道取得的簽署指紋，可用參數或環境變數 `NOMOSMART_TRUSTED_FINGERPRINT`（兩者都有時以參數為準）：

```sh
./deploy/package/nomosmart-package init --target compose --profile factory_acceptance --app-env development \
  --no-display --random-initial-credentials --public-host nomosmart.local \
  --trusted-release-fingerprint "$NOMOSMART_TRUSTED_FINGERPRINT"
```

全新安裝時 `./nomosmart up --trusted-release-fingerprint …` 也接受同樣的輸入。指紋缺少、錯誤或版本包檔案被改過時，工具會在寫入任何設定或憑證前停止。

不使用打包工具時，依[部署操作指南](deploy/README.md#docker-compose)準備設定所引用的 Secret／TLS 檔，填入已檢視的映像、真實服務及[目錄 bootstrap 設定](deploy/docker/auth-bootstrap.example.json)。使用原始碼時才建置應用映像；版本包應使用其清單指定的映像。

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
4. 讓正常 migration 流程將既有資料庫依序升到 **068**；全新資料庫使用 B054 基線後套 V055–V068。舊版建立的 Compose 安裝在 `deploy/docker/nomosmart.env` 固定了舊目標：啟動 0.4.1 前請改為 `MIGRATION_REQUIRED_VERSION=068`、`MIGRATION_REQUIRED_CHECKSUM=-1307752697`，否則 bootstrap 會以 `database_migration_version_unexpected` 停止（資料不受影響）。不可重寫舊 SQL 或手動刪除歷史欄位。[Migration 契約](deploy/migrations/release-contract.json)提供目標與 checksum。
5. 從 0.3.0 帶既有文件升級：V064 要求所有專案中未刪除的文件名稱不重複（不分大小寫、忽略前後空白；從其他專案引用的文件不計），升級前請先把同名文件改名（否則遷移會停止，資料不變）。0.4.0 之前萃取的文件仍可問答，但沒有站別與引用資料，重新萃取後才會有。升級後在 backend 容器執行一次 `python -m app.deployment.backfill_relations`（可重複執行）。送審中的文件不能刪除；送審已不能取消，需由審核人先退回。從 0.4.0 升級時，V068 只新增審核路徑欄位、「Owner 備援」設定（預設關閉），以及內建 system-admin 角色的「審核管理」權限；既有送審保留原本的審核人。問答相關功能（引用路由、引用擴展、子問題）改在系統設定管理，不使用環境變數。
6. 從 0.3.0 以前的版本升級時，另需依 0.3.0 API 更新整合程式（破壞性變更）：改用 `POST /api/public/v1/responses` 並以 `model: "nomosmart:project/<project_id>"` 指定專案，取代 `/projects/{id}/chat` 與 `/chat/stream`；回饋改送 `/responses/resp_<id>/feedback`；回應與錯誤改為 Open Responses 格式。`Idempotency-Key` 改為選填。移除 Helm 的 `ftpsCa` 與 `sftpKnownHosts`（values schema 已不接受）。可選的新設定（皆有預設值）：`CHAT_HISTORY_MAX_TURNS`（5）、`CHAT_HISTORY_MAX_CHARACTERS`（12000）、`VALIDATION_SCENARIO_MAX_TURNS`（20）。
7. 為新的 PDF 工作選定相容的原生文件模型，填入能力、價格及輸出預算。舊 OCR 模型、頁面結果、收據與用量保留歷史；舊未完成工作需明確檢視，不會自動改成新請求。
8. 完成 bootstrap／一般管理員登入／finalize，再確認服務就緒、登入及既有資料可讀。舊瀏覽器工作階段需重新登入。

移轉與版本回復是不同操作。不要以刪新表降版，或直接讓舊 Worker 寫入新版政策；依既有快照及相容版本做協調回復。[認證升級指南](docs/AUTHENTICATION.zh-TW.md)與[PDF 操作指南](docs/NATIVE-PDF-OCR-OPERATIONS.md)保留具體限制。發布版本不會自動更新既有部署。

## API、維運與驗收範圍

| 入口 | 用途 |
| --- | --- |
| `/api/v1` | Backend 內部 API；工作階段與後端權限檢查；對話測試透過 `POST /api/v1/responses` 提問 |
| `/api/public/v1` | 整合 API；相容 Open Responses 的 `POST /responses`（一般或 `stream: true`，以 `previous_response_id` 支援多輪）與 `POST /responses/{response_id}/feedback`；獨立 API Key 與專案 scope |
| `/openapi.json`、`/docs` | Backend OpenAPI／Swagger |
| `/api-docs` | 產品內 API 說明 |
| `/api/v1/health`、`/api/v1/ready` | 程序健康與依賴／初始化就緒狀態 |

日常檢查最後成功同步、失敗工作、佇列、稽核日誌及 readiness。目錄同步失敗保留最後成功快照；付費請求結果不明時先核對收據。工作程式中途消失、新文件停止處理時，以 `app.deployment.document_execution_recovery` 救援卡住的處理紀錄（步驟見 [deploy/README.md](deploy/README.md#recovering-a-stuck-document-execution-025)）。日誌不應包含密碼、token、cookie 或文件正文。

0.4.1 以本版原始碼與映像驗證：39 項必要情境（含四站萃取、引用與取代、子問題、審核中禁止刪除與審核路徑）與 19 項發佈關卡全部實跑，安裝包完成簽署與驗包（含竄改、錯誤指紋負向測試及實際 `init`）。證據與完整分母覆蓋率附在 [GitHub Release v0.4.1](https://github.com/crispkid/Nomosmart/releases/tag/v0.4.1)；80% 覆蓋率為改善目標，不決定是否就緒。FTP 程式已移除，不再需要 FTP 風險接受。正式多主機容量、高可用、正式網路隔離與正式備份未取得資格（`production_ready=false`），不能由本機驗收推論通過。

## 專案結構與開發

```text
frontend/                 Next.js UI、同源代理與多語系
backend/                  FastAPI、模型／目錄整合與背景工作
sql/migrations/           B054 基線及向前移轉歷史（目前 063）
deploy/docker/            Compose 設定範例、入口與Secret工具
deploy/helm/nomosmart/     Helm Chart、ConfigMap／Secret引用與probes
deploy/installer/          協定安裝與初始化工具
deploy/release/            組包、簽署及完整性驗證
docs/                     操作指南與保留的歷史紀錄
```

原始碼開發需連接真正的非正式服務，使用[Backend](backend/.env.example)與[Frontend](frontend/.env.example)設定範例。依變更選擇最窄的 harness 檢查；設定語法檢查不等於登入或業務驗收，已通過且未受影響的結果應沿用。

授權條款見 [LICENSE](LICENSE)。

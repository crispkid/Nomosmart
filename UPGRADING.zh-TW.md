# NomoSmart 升級指南

[English](UPGRADING.md) | 繁體中文

這份指南說明如何升級既有的 NomoSmart 部署。請先讀[通用步驟](#通用步驟)，再讀**從目前版本到
目標版本之間每一版**的注意事項（最新版在最上面）。每一版改了什麼請見
[CHANGELOG.zh-TW.md](CHANGELOG.zh-TW.md)。

發佈新版本不會自動升級既有部署。請一次升級一個部署，升級前先讀該版的 GitHub Release
與安裝包內附的升級說明。

## 通用步驟

1. **驗證安裝包。** 核對公佈的 SHA-256、OpenPGP 簽章與映像摘要，並用經由獨立可信管道取得
   的簽署者指紋驗包（見[驗證安裝包](README.zh-TW.md#安裝前準備)）。
2. **保留復原所需的資料。** 保留既有資料、設定、加密金鑰與 TLS／CA 材料，並檢查目前與目標
   部署的差異。
3. **停止舊的寫入程序。** 暫停舊的匯入與目錄同步 producer，停止舊的 Worker 與 Beat。
   Frontend、Backend、Worker 與 Beat 一起更新，避免兩個版本同時寫入。
4. **資料庫向前移轉。** 用正常的移轉流程升到目標版本；全新資料庫從基線開始套用之後所有移轉。
   不可修改歷史 SQL，也不可手動刪除歷史欄位。
   - 目前的目標版本與 checksum 以[移轉契約](deploy/migrations/release-contract.json)為準。
   - **Compose：** 舊版建立的安裝會在 `deploy/docker/nomosmart.env` 固定舊目標。啟動新版前，
     請把 `MIGRATION_REQUIRED_VERSION` 與 `MIGRATION_REQUIRED_CHECKSUM` 改成目標版本的值
     （見[移轉目標](#移轉目標)），否則 bootstrap 會以 `database_migration_version_unexpected`
     停止（資料不受影響）。
   - **Helm：** 每一版的 chart 預設就是該版的目標。請用檢視過的完整 values 搭配
     `--reset-values`，不要用 `--reuse-values`。
5. **完成並確認。** 完成 bootstrap、一般管理員登入與 finalize，再確認服務就緒、可以登入、
   既有資料可以讀取。

**版本回復。** 應用程式回復與資料庫結構回復是兩件不同的事。不要用刪表的方式降版，也不要讓
舊的 Worker 寫入新格式的資料。請用保留的快照與相容的版本復原。

## 移轉目標

| 版本 | 移轉目標 | Checksum（Flyway） | 新增的移轉 |
| --- | --- | --- | --- |
| 0.4.2 | 069 | `-1562058873` | V069 |
| 0.4.1 | 068 | `-1307752697` | V068 |
| 0.4.0 | 067 | `1913543487` | V064–V067 |
| 0.3.0 | 063 | `1135291166` | V062–V063 |
| 0.2.5 | 061 | `1514288448` | V058–V061 |
| 0.2.4 | 057 | `-398616135` | V057 |
| 0.2.3 | 056 | `99561060` | V054–V056；全新資料庫改由 B054 基線開始 |
| 0.2.0–0.2.2 | 053 | — | V052–V053 |
| 0.1.0–0.1.2 | 051 | — | B051 基線；既有資料庫保留 V001–V051 |

「—」表示該版的移轉契約對基線與一般移轉各列一組 checksum，請以該版安裝包內的移轉契約為準。

## 各版注意事項

### 升級到 0.4.2（從 0.4.1）

- V069 只新增 5 個問答設定（Top K 5、Top P 1.0、最低分數 0、重排關閉、未選模型）、專案
  重排開關（關閉）、兩個檢索追蹤欄位，並允許「重排模型」類型。不新增資料表。既有專案的
  重排開關都是關閉。
- 子問題改取 K 段（預設 5），之前固定 2 段，回答模型收到的內容可能變多。
- `/responses` 沒帶 `nomosmart:top_k` 時，改用系統設定 `retrieval_top_k`（預設 5，與之前相同）。
- 重排服務不包含在安裝程式內；要開啟重排時請另外部署。

### 升級到 0.4.1（從 0.4.0）

- 主管代理人已移除。`PUT /api/v1/users/{id}` 帶 `manager_delegate_*` 欄位會回 `422`，請從
  外部系統移除這些欄位。已經派給代理人的案件仍由該代理人處理。
- 送審人自己是專案唯一的 Project Owner 時，Owner 關沒有人能審核：新的送審會被拒絕
  （`no_other_project_owner`），請先加上第二位 Project Owner。已經走到 Owner 關的這類案件，
  可以在「審核案件管理」用「無人可處理」篩選後退回。
- V068 只新增審核路徑欄位、Owner 備援設定（預設關閉）與內建 `system-admin` 角色的審核案件
  管理權限。不新增資料表，既有案件保留原審核人。

### 升級到 0.4.0（從 0.3.0）

- **文件名稱全站不重複。** V064 要求現存文件名稱在所有專案中不重複（比對前去除前後空白、
  做 NFKC 正規化並轉小寫；已刪除的文件與專案引用文件不算）。有同名文件時 V064 會失敗並整筆
  回復，資料庫停在 063（Flyway 訊息為 `could not create unique index "uq_documents_title_key_live"`，
  SQL State 23505）。0.3.0 沒有改名畫面：請在 0.3.0 刪除多餘的同名文件，或請資料庫管理員
  改名後再升級。該版的升級說明附有升級前檢查用的 SQL。
- **既有文件**仍可問答，但沒有站別與引用資料。升級後在 Backend 容器執行一次
  `python -m app.deployment.backfill_relations` 補上取代關係（可以重複執行）。一般引用要
  重新萃取（建立新版本）後才會出現。升級前已退回的版本不能直接修改，請建立修訂。
- **審核。** 送出的案件不能取消，只能由審核人退回。審核中的文件不能刪除。
- 問答選項（引用路由、引用擴展、子問題）是系統設定，不是環境變數。

### 升級到 0.3.0（從 0.2.5）— 破壞性變更

- **資料服務。** FTP、FTPS、SFTP 資料服務已移除。升級前請改用 S3 或 HTTP API。既有的仍可
  看到，但會以 `unsupported_protocol` 失敗。
- **API。** 舊問答端點改回 404，請改用 Open Responses 端點：

  | 0.3.0 之前 | 0.3.0 起 |
  | --- | --- |
  | `POST /api/public/v1/projects/{id}/chat` | `POST /api/public/v1/responses`（`model: "nomosmart:project/{id}"`） |
  | `POST /api/public/v1/projects/{id}/chat/stream` | 同上，加 `"stream": true` |
  | `POST /api/public/v1/chat/responses/{id}/feedback` | `POST /api/public/v1/responses/resp_{id}/feedback` |
  | `POST /api/v1/projects/{id}/chat/query`（對話測試） | `POST /api/v1/responses` |

  `Idempotency-Key` 改為選填；回應與錯誤使用 Open Responses 格式。
- **Helm：** 刪除 values 中的 `ftpsCa` 與 `sftpKnownHosts`（values schema 已不接受）。
  **Compose：** 刪除 `FTPS_CA_CERT_PATH`、`FTPS_CA_DIRECTORY`、`SFTP_KNOWN_HOSTS_PATH`、
  `SFTP_KNOWN_HOSTS_FILE` 與對應掛載。
- 新的選用設定（皆有預設值）：`CHAT_HISTORY_MAX_TURNS`（5）、`CHAT_HISTORY_MAX_CHARACTERS`
  （12000）、`VALIDATION_SCENARIO_MAX_TURNS`（20）。
- V062、V063 只新增欄位。

### 升級到 0.2.5（從 0.2.4）

- V061 把既有的 OpenAI Chat 與 Judge 模型改用 Responses API，在 `config.api_mode_migrated_from`
  記下原本的模式、清除已存的連線測試結果，並為每個模型寫一筆 `ai_model.api_mode_migrated` 稽核紀錄。
  它的 NOTICE 輸出會標出 base URL 不是 `api.openai.com` 的模型：若該模型指向只支援 Chat Completions
  的代理，請把供應商改為 vLLM 或 Custom。升級後請重新測試每個被遷移的模型。
- V059 只移除已退役的 Keycloak 欄位預設值。V060 為沒有建立者的文件版本寫入已記錄的建立者，並標記
  `version_created_by_source = "V060"`。
- 每個專案都需要一個具備原生 PDF 能力、啟用中的 OCR 模型。沒有的話，建立專案或修改專案的
  Chat、Embedding、OCR 模型會被拒絕（`project_model_configuration_required`）。
- V058 只新增索引；建立索引時，寫入相關資料表會等待，請在正常的升級時段執行。

### 升級到 0.2.4（從 0.2.3）

- 管理 API 客戶端必須帶設定版本條件，否則會收到 `428`，請更新這類客戶端。

### 升級到 0.2.3（從 0.2.2）

- **PDF 處理。** 本機 OCR、抽文字、轉圖、拆頁與自動備援已退役。所有新 PDF（包含已有文字的
  PDF）都需要相容的原生文件模型；請設定它的能力、價格與輸出預算，輸入計數與生成可能產生
  費用。舊的 OCR 模型、收據、用量與政策保留為歷史，舊的未完成工作不會自動變成新的付費請求。
  詳見 [PDF 辨識維運](docs/NATIVE-PDF-OCR-OPERATIONS.md)。
- **登入。** 認證契約 2：選擇外部 OIDC 或 LDAP／AD，並補齊目錄同步與管理員群組設定。使用者、
  內部 UUID、角色與歷史都會保留，不再需要 Keycloak Admin API。請移除已退役的 `keycloak.*`
  Helm values。舊的瀏覽器工作階段需要重新登入。詳見[認證指南](docs/AUTHENTICATION.zh-TW.md)。
- 使用 GHCR 私有映像時，需要具讀取權限的登錄帳號或 `imagePullSecret`。

### 升級到 0.2.2（從 0.2.1）

- 套用新版 NGINX 代理模板。自訂代理需同步 CSV 路徑的 HTTP/1.1 串流設定；使用內部 OIDC
  Token 端點時，依新版範本設定 `OIDC_TOKEN_URL`。
- 簽核 API 建議使用 `submitter_id`，`editor_id` 保留為相容別名。
- 安裝包採 schema 5，請用包內驗證器與獨立可信的簽署者指紋驗包。

### 升級到 0.2.1（從 0.2.0）

- 知識文件上傳只接受 PDF、UTF-8 TXT 與 Markdown，其他檔案請先轉換。
- FTPS 需使用主機名稱相符的有效憑證。

### 升級到 0.2.0 與 0.1.x

- 除了[通用步驟](#通用步驟)之外沒有特別的步驟。保留現有設定、秘密、TLS／CA 與持久資料卷，
  不要執行重設或解除安裝步驟。

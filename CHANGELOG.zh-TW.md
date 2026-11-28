# 更新紀錄

[English](CHANGELOG.md) | 繁體中文

這份文件列出 NomoSmart 每一版的重要變更，最新版在最上面。格式參考
[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循
[語意化版本](https://semver.org/lang/zh-TW/)。日期為台北時間的發佈日。

版本之間怎麼升級（含資料庫移轉目標）請見 [UPGRADING.zh-TW.md](UPGRADING.zh-TW.md)。
每一版的 GitHub Release 另外列出安裝包、映像摘要、驗收結果與已知限制。

## [未發佈]

## [0.5.0]

資料庫移轉目標：**070**。發佈日期請見 GitHub Release。

### 新增

- 全新介面：淺色與深色主題、側邊欄與手機版分頁導覽、內建字型與新標誌。首頁顯示指標
  與待處理清單；專案可依狀態篩選；簽核工作台有分頁、寬螢幕預覽，並可與上一個已發佈
  版本比對；報表有快速日期範圍、總覽與簽核統計；知識圖譜顯示總數與節點類型篩選。
- 簽核到期日：待簽核項目在送出後 48 小時到期。簽核工作台與首頁標示「已逾期」、
  「今天到期」或到期日，工作台可改為最早到期先列。
- 系統管理的使用者清單顯示最後登入時間（只有系統管理看得到）。
- 報表顯示外部 API 回答的使用者回饋正面比例（每筆回答取最新一次回饋，依報表期間）。
- 上傳前相同內容預檢：專案內已有相同內容的檔案預設略過，也可以選擇仍要上傳。
- API（只新增）：`GET /api/v1/approvals/pending` 的 `due_at` 與 `sort=due`；系統管理
  使用者清單與使用者詳情的 `last_login_at`；
  `POST /api/v1/projects/{id}/documents/duplicate-check`；
  `GET /api/v1/reports/approval-stats`；`GET /api/v1/approvals/{id}/changes`；
  `GET /api/v1/projects/status-counts`；報表摘要新卡片、專案負責人與統計數、圖譜總數，
  以及 `/api/v1/auth/me` 的 `department`。細節請見各端點的 API 說明。

### 變更

- 介面用語依統一的文案指南：「簽核」、「專案負責人」、「系統管理員」。
- 首頁的退回件，在文件重新送出後就不再列入待處理。
- 簽核詳情不再顯示固定的「送審原因」；產品沒有這個欄位。
- README 不再隨每次發佈修改。版本紀錄移到這份文件，升級步驟移到
  [UPGRADING.zh-TW.md](UPGRADING.zh-TW.md)，資安回報方式移到 [SECURITY.md](SECURITY.md)。

### 修正

- 對話測試的對話紀錄時間改為依介面語系顯示，不再跟隨瀏覽器語系。
- 已取消的批次驗證項目在對話測試顯示「已取消」，不再顯示錯誤或「排隊中」。
- OIDC 候選設定完成外部登入驗證後，系統設定會顯示「套用已驗證設定」按鈕。
- 在一個分頁登出時，同一工作階段的其他分頁顯示「已登出」，不再顯示「工作階段已過期」。
- 簽核統計接受沒有時區的日期（視為 UTC）。

## [0.4.2] - 2026-11-26

資料庫移轉目標：**069**。

### 新增

- 檢索深度與廣度（Top K／Top P），在「系統設定 → 問答」設定：Top K（每題取回的切片數，
  1–20，預設 5）、Top P（開啟重排時保留的重排分數累計佔比，0.1–1.0，預設 1.0）、
  最低分數門檻（0–1，預設 0）。子問題繼承同一組 K 與 P。對話、批次驗證與外部 API
  （`nomosmart:top_k`、新增的 `nomosmart:top_p`）可以逐題指定。
- 對話紀錄與驗證項目保存檢索追蹤，含各階段耗時。
- 可選的重排模型：登錄「重排模型」（提供 `/rerank` 端點的服務，例如載入
  bge-reranker-v2-m3 的 TEI；不包含在安裝程式內），在系統設定開啟後，再由各專案的
  Project Owner 開啟。重排服務失敗或逾時時，改用一般排序回答。
- 專案設定管理：管理者可以檢視所有專案，單一或批次設定問答、向量與 OCR 模型、成員與
  角色（含 Owner 交接）以及重排開關。
- API：`GET/PATCH /api/v1/projects/{id}/retrieval-settings`、
  `GET /api/v1/system/project-settings`、`GET /api/v1/system/project-settings/{id}`、
  `POST /api/v1/system/project-settings/batch`；`POST /api/v1/models` 接受
  `model_type: "Reranker"`。

### 變更

- 每個子問題改取 K 段（預設 5），之前固定 2 段。
- `/responses` 沒帶 `nomosmart:top_k` 時，改用系統設定 `retrieval_top_k`（預設 5，與之前相同）。

### 修正

- 單檔上傳後，對話框會直接開啟文件等待確認的那一站，不再停在對話框。
- Judge 評分與引用卡片會帶上切片所屬章節，關鍵句被辨識成標題時不再誤判引用不足。
- 審核路徑說明文字不再提到已移除的主管代理人。

## [0.4.1] - 2026-11-23

資料庫移轉目標：**068**。

### 新增

- 送審前先顯示由誰審核：送審人的主管；或在「改送 Project Owner 審核」設定開啟時，
  由其他 Project Owner 審核。沒有人能審核時直接拒絕送審（`409 review_route_unavailable`）。
- 審核案件管理（系統管理 → 審核）：有權限的管理者可以改派主管審核關、退回任何階段的
  案件、篩選無人可處理的案件，但不能核准。權限 `Approval.ApprovalAdministration`
  預設給內建 `system-admin` 角色。

### 變更

- 送審人即使是 Project Owner，也不能核准或退回自己的案件（`403 approval_self_review_forbidden`）。
- Next.js 16.4.5。

### 移除

- 主管代理人：編輯使用者不再設定代理人；使用者 API 不再回傳 `manager_delegate_*`
  欄位，帶這些欄位會回 `422`。資料庫保留原本的欄位與資料。

### 修正

- 用戶端在回答串流剛開始時離開，會記錄為「已取消」；同一個 `Idempotency-Key` 重送會重播取消結果。
- 軟刪除殘留清理工具在 0.4.0 資料結構下恢復可用，殘留資料還有切片引用時會停下來。
- 應用程式金鑰輪替補上追問改寫紀錄與公開回答的重播紀錄。
- `nomosmart-install finalize` 在滾動更新期間只選用運作中的 Backend pod，中斷時改用另一個 pod 重試一次。

### 安全性

- 0.4.0 前端映像來自 Next.js 16.4.1 的 7 項 Medium 弱點已全部消失。

## [0.4.0] - 2026-11-21

資料庫移轉目標：**067**。

### 新增

- 四站式知識萃取：全文、切片、標籤與引用、向量與送審。每站完成後等編輯確認；可以回到
  前面的站修改，內容沒變的切片保留原有成果；可以選取文字建立切片。所有萃取入口都走四站。
- 文件名稱可以編輯，而且全站不能重複。
- 引用與取代關係：第 3 站找出文件中提到的其他文件，以及「原《X》廢止」這類取代關係，
  都可以手動修正。圖譜顯示引用線與取代線，被取代的文件會提醒由哪份新文件取代。
- 問答會判斷問題是否在問引用或取代關係並帶入相關文件；一題多問時拆成子問題分別搜尋。
  問答設定移到「系統設定 → 問答」，改了就生效，不需重新部署。
- 送審證據新增引用數、未對應引用數與重疊切片組數。
- 系統內 API 說明頁新增「快速開始」與「限制」章節。
- 外部問答帶 `Idempotency-Key` 時，若失敗發生在呼叫模型之前，可以用同一個 key 重試；
  所有 API 日誌加上 `error_code`。
- `python -m app.deployment.backfill_relations` 為既有文件補上取代關係。

### 變更

- 送出的審核案件不能取消，只能由審核人退回
  （`POST /api/v1/approval-requests/{id}/cancel` 回 `409 approval_cancel_removed`）。
  審核人帳號停用或不存在時，Project Owner 可以代為退回，但不能核准。
- 審核中的文件不能刪除（`409 document_review_pending`）。
- 處理狀態與設定更新者以文字顯示；全站對話框與按鈕統一樣式。

### 修正

- 刪除切片不再一律回 409，切片的引用紀錄會一起刪除。
- 文件在排隊萃取時被刪除，不再讓派送佇列停住。
- 審核中的文件被刪除後不再留下待審任務，已刪除文件的已核准版本不能再發布。
- 複製萃取的文件不再停在第 3 站。
- 問答設定頁不再整頁錯誤。
- 刪除被引用的文件後，引用改回「未對應」，可以重新對應。
- 模型回傳的向量含 `-0.0` 時，第 4 站不再一直失敗。
- Helm values 與 Compose 環境檔範例預設移轉目標為 067。

## [0.3.0] - 2026-11-16

資料庫移轉目標：**063**。本版含 API、資料服務與 Helm values 的破壞性變更。

### 新增

- 統一的 Open Responses 問答 API：外部系統（`POST /api/public/v1/responses`，API Key）
  與系統內對話測試（`POST /api/v1/responses`，登入連線）共用同一核心，支援 JSON 與
  SSE 串流，引用以 `url_citation` 回傳。`Idempotency-Key` 改為選填。回饋改送
  `POST /api/public/v1/responses/{resp_id}/feedback`。
- 多輪對話：帶 `previous_response_id` 接續前文，限同一個 API Key、員工與專案；追問會先
  改寫再搜尋。上限：`CHAT_HISTORY_MAX_TURNS`（5）、`CHAT_HISTORY_MAX_CHARACTERS`（12000）。
- 對話測試可以選單輪或多輪。
- CSV 批次驗證支援多輪情境（`conversation_key` 與 `turn` 欄位、
  `VALIDATION_SCENARIO_MAX_TURNS` 預設 20），並顯示情境通過率。

### 移除

- FTP、FTPS、SFTP 資料服務。既有的仍可看到，但連線測試與同步以 `unsupported_protocol`
  失敗；建立會回 422。Helm values `ftpsCa`、`sftpKnownHosts` 與對應環境變數一併移除。
- 舊問答端點（`/api/public/v1/projects/{id}/chat`、`.../chat/stream`、
  `/api/public/v1/chat/responses/{id}/feedback`、`/api/v1/projects/{id}/chat/query`）改回 404。
- 確認未使用的程式碼。

## [0.2.5] - 2026-11-15

資料庫移轉目標：**061**。

### 新增

- `python -m app.deployment.document_execution_recovery preview|commit`：工作程式中途
  消失時，一次救援一筆卡住的文件處理紀錄；成功與拒絕都寫入稽核。
- 工作程式內發生未預期錯誤時，文件會標為「失敗、可重試」，不再暫停整個部署的文件處理。
- `nomosmart-package init` 與 `./nomosmart up` 支援已簽署的 v5 安裝包，以可信指紋驗包後
  寫入安裝包的映像摘要。

### 變更

- OpenAI Chat／Judge 模型改用 Responses API，既有模型由 V061 自動遷移。連線測試實際送出
  極小請求，分別回報模型不存在、認證失敗與格式被拒。專案需設定 OCR 模型。

### 修正

- 文件仍在背景收尾時送審，改回 `409 document_processing_finalizing`，不再讓所有文件卡住。
- OCR 單次輸出上限改取系統參數與模型能力中較小的值。
- 兩份文件同時產生同名新標籤時，不再有一份永久卡住。
- `nomosmart-package init` 恢復可以初始化已簽署的 v5 安裝包。

## [0.2.4] - 2026-11-10

資料庫移轉目標：**057**。

### 新增

- 系統設定分為七大類（人員與權限、身分與目錄、AI 模型、文件與知識、API Key、一般設定、
  系統狀態），提供搜尋定位、草稿保護與必要的身分再次確認。
- API Key 獨立管理。
- 各設定區有獨立版本條件，避免不同管理者互相覆蓋。
- 退回文件的暫存保留期限依當時設定保存，到期由正常背景流程清理。

### 變更

- 管理 API 客戶端缺少設定版本條件時會收到 `428`。

### 修正

- 登入或再次確認時密碼錯誤，不再顯示成 502。
- HTTP 遠端檔案會在下載前或串流讀取中檢查大小上限。
- 封存未完成的文件版本時不再因外鍵錯誤失敗。

## [0.2.3] - 2026-11-07

資料庫移轉目標：**056**。全新資料庫改由 B054 基線開始。

### 新增

- PDF 原檔直接送到已設定的 LLM 文件模型產生 Markdown；TXT／Markdown 直接讀取。新增 PDF
  能力設定、輸入計數、文件預算與辨識收據。
- 支援通用 OIDC，或直接用 LDAP／Windows AD 登入；使用者與群組直接從目錄同步，可設定每日
  同步時間與時區，並在網頁管理連線設定。
- 伺服器工作階段：閒置 30 分鐘登出。
- 新版登入頁、語系選單、響應式 Header 與下拉選單。

### 變更

- 認證契約 2：選擇外部 OIDC 或 LDAP／AD。不再需要 Keycloak Admin API，舊的瀏覽器工作階段需重新登入。

### 移除

- 本機 OCR、抽文字、轉圖、拆頁與自動備援。所有新 PDF 都需要相容的原生文件模型。
- Compose／Helm 內建的 Keycloak 服務相依與殘留的 Keycloak 字樣。

### 修正

- 複製萃取時新舊分詞格式的相容問題。
- 取消送審後流程不再停在待審。
- Judge 用量記錄真實文件版本，刪除判斷保留用量、帳務與稽核。
- 維護清理工具接受 LDAP 共用工作階段。
- 主標題、瀏覽器頁標與 PDF 狀態文字跟著語系切換。

### 安全性

- 更新本版掃描確認的高風險相依套件。

## [0.2.2] - 2026-10-25

資料庫移轉目標：**053**。

### 新增

- 簽核清單新增專案、文件名稱、送審者、階段、結果與日期篩選。
- 登入頁可以切換繁體中文／英文。
- 可讀的瀏覽器分頁標題、錯誤復原畫面，以及 API 範例逐段複製。
- 安裝包附 OpenPGP 簽章、SHA256 與軟體物料清單（SBOM）。

### 變更

- 簽核 API 建議使用 `submitter_id`，`editor_id` 保留為相容別名。

### 移除

- 頁首的全站搜尋入口；各模組保留原有的局部查找。

### 修正

- 簽核與待發布清單超過 100 筆、總筆數與續載的問題。
- 載入失敗被顯示成空資料，以及報表的舊請求覆蓋目前結果。
- CSV 匯出中斷仍被當成下載成功。
- 模型驗證在執行前檢查失敗後停在排隊狀態。
- OIDC 重新驗證改用已設定的內部 Token／JWKS 端點。
- 視窗焦點與鍵盤操作、圖譜縮放與拖曳邊界、窄螢幕版面、表單錯誤、通知語言、按鈕對比與觸控尺寸。

### 安全性

- 更新 Next.js、certifi 與開發工具的相依套件。

## [0.2.1] - 2026-10-17

資料庫移轉目標：**053**。

### 新增

- 統一系統通知與視窗提示，知識萃取改用精簡圖示工具列。
- 知識圖譜加入背景排版、初始位置快取與重複計算抑制。
- FTPS 支援企業 CA；新增清理已軟刪除文件過期衍生資料的獨立維護指令。

### 變更

- 知識文件上傳只接受 PDF、UTF-8 TXT 與 Markdown。

### 修正

- 重複送出、查詢失敗被當成空資料，以及文件更新提示不正確。
- 模型管理檢查、API 金鑰有效期、清單與搜尋完整性、角色更新與資料來源憑證參照。
- 開發模式登入卡住、Docker 建置排除不完整與本機舊快取干擾建置。
- FTPS 憑證與主機名驗證，以及 FTP／FTPS 把無法存取誤報為檔案不存在。
- OCR 內容調整後，舊切片、向量、標籤、索引與圖譜資料的取代。

## [0.2.0] - 2026-10-11

資料庫移轉目標：**053**。

### 新增

- OCR 後可以調整整份文件，並同步更新切片、標籤、向量、索引與圖譜。
- OCR 改用轉圖片流程，輸出上限可在資料庫設定（預設每頁 10,000 tokens、整份 1,000,000 tokens）。

### 變更

- 改善重試操作、處理資訊、數字格式、連續閱讀與切片來源高亮；切片優先保留完整段落、句子與表格。

### 修正

- 清理被取代的衍生資料；後續查詢失敗時保留已產生的模型用量紀錄。

## [0.1.2] - 2026-10-03

資料庫移轉目標：**051**。

### 新增

- `./nomosmart up`、`status`、`logs`、`down`：一個指令準備隨機密碼、TLS、設定、完整服務、
  移轉與 bootstrap，並等待 HTTPS 就緒。支援 localhost、自訂埠號與 `./nomosmart up --build`。

### 移除

- 確認未使用的程式碼與相依套件。

### 修正

- 簽核與引用 API 的存取範圍，以及簽核載入失敗時的錯誤顯示。
- OIDC 回呼重複交換與過期回應；依登入流程隔離暫存 Cookie，中英文登入介面一致。

## [0.1.1] - 2026-10-01

資料庫移轉目標：**051**。

### 新增

- 通用靜態 PV 與外部服務設定契約；Docker Desktop 指南含專用 Ingress、容量檢查與清除流程。

### 修正

- Compose PostgreSQL Secret 檔案權限與初始化，分開管理、移轉、應用程式與 Keycloak 資料庫身分。
- Redis／Sentinel 認證、內部 TLS 主機名稱、CA 逐檔唯讀掛載，以及私有 HTTPS Keycloak 的信任與 discovery。
- 清除範例中的個人名稱與內網位址；安裝密碼改以受保護檔案產生與保存。

### 安全性

- Next.js 16.3.8、PyJWT 2.15.0。

## [0.1.0] - 2026-09-30

資料庫移轉目標：**051**。第一個版本。

### 新增

- 匯入文件與連線資料來源；解析、OCR、Markdown 轉換與向量化。
- 文件版本、審核與發布、搜尋、關聯圖譜，以及附來源引用的問答。
- Keycloak OIDC、LDAP 與 Windows AD，搭配專案權限與本機角色。
- 以 Docker Compose 或 Kubernetes 安裝，可使用內建或既有的外部服務。
- 全新資料庫使用 B051 基線；既有資料庫保留 V001–V051 歷史。

[未發佈]: https://github.com/crispkid/Nomosmart/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.5.0
[0.4.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.2
[0.4.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.1
[0.4.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.0
[0.3.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.3.0
[0.2.5]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.5
[0.2.4]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.4
[0.2.3]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.3
[0.2.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.2
[0.2.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.1
[0.2.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.0
[0.1.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.2
[0.1.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.1
[0.1.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.0

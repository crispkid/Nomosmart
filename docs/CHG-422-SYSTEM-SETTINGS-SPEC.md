# NomoSmart 系統管理介面與設定生效規格

本規格用於後續系統管理介面的資訊架構、表單與操作流程優化。目標是讓管理者依任務找到設定，理解作用範圍，並安全完成修改。範圍涵蓋現有九個管理區塊的重新分組，不新增另一套人員、模型、認證或對外授權系統。

| 項目 | 內容 |
| --- | --- |
| 變更編號 | CHG-389 |
| 文件版本 | 1.0 |
| 日期 | 2026-11-08 |
| 狀態 | Peter 已確認規格與範圍，2026-11-08 核准開發計畫 |
| 文件負責人 | Codex |
| 規格審閱與驗收 | Peter |
| 開發授權 | Peter「執行這份計劃」；Gate 2 CONFIRMED、Gate 4 APPROVED |

使用者已明確要求：保留現行框架、使用淺色側欄、大分類在左側、小分類為依序向下排列的大卡片、標題與內容明確區隔、獨立設定不並排、真實父子項採一致縮排且最多兩層，以及 API Key 獨立分類。七個分類、定位與分區儲存、版本檢查及相容升級均由 Peter「全部採用建議」確認；另選 B 納入實際生效修正。

本規格已取得 Peter 的本變更獨立核准，依下列範圍修訂 SYS-001、SYS-004 與系統參數契約；尚不代表已部署或驗收完成，也不沿用 CHG-388 或其他變更的核准。PROTAUTH、ROLE、PERM、MODEL、PROMPT、APIKEY、FEEDBACK 與 TEST-002 等既有業務和安全規則繼續適用。

## 1 使用者與工作情境

### SYSUX-001 範圍與權限

適用角色為具有有效 `SystemManagement.view` 的管理者，以及具有個別 create、edit、delete、execute 權限的操作者。唯讀管理者可瀏覽實際可見資料；修改、建立、同步、測試與撤銷仍按既有後端逐操作授權。分類名稱不建立新的角色或權限點，Project Owner 不取代系統角色。

主要情境為：管理人員與角色、調整登入或目錄來源、設定模型與提示詞、調整文件規則、管理外部系統 API Key，以及診斷系統狀態。由現有 `/system` 工作台進入，不另建第二套管理入口。

不在範圍內的事項包括：改變簽核或專案治理、增加本機註冊或登入模式、變更金鑰保存政策、開放基礎服務連線的 Web 編輯、增加付費模型呼叫，以及藉介面優化執行資料清理、遷移、正式部署或發布。

驗收：Given 管理者只有 view，When 開啟任一分類及直接呼叫修改 API，Then 可檢視被授權資料，但不可操作修改入口，後端拒絕寫入；新增分類不增加其有效權限。

## 2 大分類與小分類

### SYSUX-002 左側分類與排序

左側只顯示下列七個大分類，順序固定，不再保留「整合與維運」或其他重複入口。沒有指定有效定位時，預設進入「人員與權限」的使用者管理，延續目前的預設工作情境。

| 順序 | 大分類 | URL section | 依序呈現的小分類卡片與 panel |
| --- | --- | --- | --- |
| 1 | 人員與權限 | people | 使用者管理 users；角色與外部群組 roles；權限矩陣 permissions |
| 2 | 登入與目錄 | identity | 登入方式 login；目錄來源 directory；連線密碼與密鑰 credentials；同步排程 sync；最近同步紀錄 sync-history；緊急管理者資訊 emergency |
| 3 | AI 模型與提示詞 | ai | AI 模型 models；系統提示詞 prompts |
| 4 | 文件處理 | documents | 檔案上傳 upload；退回文件暫存 retention；OCR 輸出預算 ocr |
| 5 | 對外 API Key | apiKeys | 串接用戶端 clients |
| 6 | 一般設定 | general | 系統預設時區 time；登入到期表單暫存 drafts |
| 7 | 系統狀態 | status | 背景工作與檢索 runtime；依賴服務 dependencies；AI Providers providers；最近錯誤摘要 errors |

OIDC 的手動身分連結只在既有適用條件下，作為登入方式卡片的操作區呈現；不建立常駐大分類。目錄篩選與進階欄位可在目錄來源卡片內展開，不構成第三層分類。

排序將人員與登入相鄰、模型與文件規則相鄰，對外授權獨立，跨功能一般參數與唯讀診斷置後。左側不再加入小分類子選單；右側是當前大分類的連續卡片，而非互斥的第二列 Tab。

驗收：Given 具 view 權限且沒有定位的管理者，When 進入 `/system`，Then 七個項目依上述順序呈現，第一個分類及 users 卡片為目前位置。

### SYSUX-003 項目歸屬與憑證邊界

| 現行項目 | 新位置 | 保留的操作界線 |
| --- | --- | --- |
| 使用者、Local 角色、外部群組映射、權限矩陣 | 人員與權限 | 同一授權工作流程；目錄資料仍為唯讀 |
| 登入、LDAP／AD／OIDC、連線憑證、同步、緊急管理者 | 登入與目錄 | 受保護設定共用重新驗證與候選啟用流程 |
| Chat／Embedding／OCR／Judge 模型、Provider 金鑰、提示詞 | AI 模型與提示詞 | Provider 金鑰隸屬所選模型；提示詞依全域或模型範圍管理 |
| 上傳大小、退回暫存、OCR 每頁及整份輸出預算 | 文件處理 | 四個文件規則在本分類更新 |
| Integration Client、授權專案、有效期、速率與金鑰生命週期 | 對外 API Key | 設定必須隸屬選定用戶端，不拆成全域期限或全域撤銷卡片 |
| 系統預設時區、登入到期表單暫存 | 一般設定 | 兩個跨功能參數；不是目錄同步的執行時區 |
| Worker、queue、retrieval/index、依賴、Provider 健康與錯誤摘要 | 系統狀態 | 唯讀檢視，不夾帶對外授權或服務連線編輯 |

部署加密金鑰、資料庫、Redis、S3 及其他基礎服務憑證仍由部署管理。登入與目錄的 write-only 連線秘密依 PROTAUTH-009 為明列例外，不與模型或對外 API Key 混用。

驗收：Given 管理者尋找 OCR 預算、Provider 金鑰或對外授權，When 使用分類或設定搜尋，Then 分別定位至 documents/ocr、ai/models、apiKeys/clients；有效欄位不在另一分類重複可編輯。

## 3 畫面與表單

### SYSUX-004 框架與視覺層次

保留現行單列 Header：品牌回首頁、知識專案、簽核工作台、更多，以及語系、通知與帳號。沿 HEADER-001 至 HEADER-006 的路由、權限與響應式規則，不重新展開全站主導覽。

側欄使用 Fresh Mint `#EAF7F1`，選中項目為柔和 Sage，搭配 Deep Action Green `#2F7D57` 的文字或左側指示線。主要文字為 Slate `#2E3A42`，卡片為 Cloud White，邊框為 Cool Gray；圓角不超過 8px。使用 Noto Sans TC 與現行字體 fallback、regular／medium／bold 字重及 lucide-react 圖示。

每張小分類卡片有三個可辨識區域：淺中性灰綠標題區、白底表單內容區、必要時的操作區。標題區以底線與留白和內容分隔，不使用高飽和大面積綠色橫條或巨大圖示。操作區僅出現該卡片或分類真正支援的動作，不為每張卡片虛構獨立儲存。

驗收：Given 桌面繁中與英文畫面，When 開啟任一分類，Then Header 不改組，側欄不呈深色，所有卡片垂直排列，標題和內容有可見的表面及分隔差異。

### SYSUX-005 一列一設定與兩層縮排

獨立設定各占一列。同一設定的名稱與說明可以置左、其輸入控制置右；不得因此把兩個不同設定放在同一列。一般畫面的時區與草稿暫存、上傳與退回保留、OCR 每頁與整份預算皆為同層設定；後兩者有驗證關係不表示父子關係。

只有真實的選擇或啟用條件才使用父子縮排，例如 OIDC 登入方式與其專屬欄位、每日同步開關與時間／時區／範圍。父項縮排 0，子項統一增加 28px；不同卡片中相同層級的標籤及控制起點一致。最多兩層，不再對子項增加孫項；必要時將進階群組提升至卡片的基準層。細導引線可輔助關係，不另巢狀包卡片。

表格可依資料語意有多個欄位，權限矩陣也可有多個動作欄；此規則不要求把紀錄表格拆成一列一欄。

驗收：Given 一般欄位與三組父子欄位，When 桌面或窄螢幕呈現，Then 獨立設定不並排，子項只縮排一格，所有同層項目對齊，DOM 與閱讀順序沒有第三層。

### SYSUX-006 網址定位與舊入口

新定位格式為 `/system?section=<section>&panel=<panel>`，兩者只能取第 2 節的列舉值。切換大分類只在同一工作台更新內容；小分類定位是捲動及焦點移至卡片，不是隱藏其餘卡片的 Tab。使用 replace 更新網址，不 reload 或逐次新增 history entry；重新載入與直接貼上網址的第一個 render 即保留位置，不先閃回 users。

有效 section 搭配無效、重複或跨分類 panel 時，使用該分類的第一張卡片；沒有有效新定位時，依下表接受舊 tab。沒有任何有效定位則回 people/users。對同時存在的有效新定位與普通舊 tab，以新定位優先並移除舊 tab。

| 舊 tab | 新 section/panel |
| --- | --- |
| users | people/users |
| roles | people/roles |
| permissions | people/permissions |
| models | ai/models |
| prompts | ai/prompts |
| apiKeys | apiKeys/clients |
| identity | identity/login |
| status | status/runtime |
| parameters | general/time，並提供前往文件處理的清楚連結 |

認證重新驗證返回是明列例外：現有 identity callback 的 tab、reauth 及受控流程參數先交原認證流程處理，完成伺服器端檢查後才正規化至 identity 對應卡片。網址成功標記不代表已解鎖，不因新路由遺失 candidate purpose、一次性流程或失敗結果。不可將欄位內容、secret、token、搜尋人員條件或自由 return URL 放進定位網址。

驗收：Given 九種舊書籤、合法新定位、錯誤或重複參數，以及合法認證返回，When 開啟或 reload，Then 依規則定位，認證返回仍須由後端確認身分，且無不安全 redirect 或解鎖捷徑。

### SYSUX-007 設定搜尋與資料清單搜尋

「搜尋系統設定」只搜尋當前語系的分類名、卡片名、欄位名稱與用途說明；索引僅含已授權可見的設定描述。結果包含大分類與卡片名稱，選取後定位到該卡片／欄位；不新增全站文件、專案、人員或金鑰內容搜尋。搜尋文字保留在當前記憶體，不寫入網址或持久化 storage。

使用者、角色、模型與用戶端的資料清單搜尋、類型篩選及分頁各自保留原範圍，不與設定名稱搜尋混用。設定無匹配、清單空資料、沒有權限與讀取失敗必須區分。

驗收：Given 搜尋 OCR、同步、API Key 或不存在的名稱，When 選取結果或清除搜尋，Then 可定位正確欄位或得到可理解的無匹配訊息；不呼叫業務全文檢索或洩漏不可見資料。

## 4 分類內的業務操作

### SYSUX-008 人員與權限

使用者姓名、部門、主管、目錄狀態與目錄群組仍由 LDAP／AD 維護；本地停用、角色、knowledge owner、主管代理與 system notes 等依既有欄位及權限管理。不得新增一般人員註冊、直接編輯目錄或刪除目錄成員。

Local 角色與外部群組分開呈現；映射遵守一對一、lock_version 與 manual／external_sync／break_glass 來源聯集。`system-admin` 保持不可停用或刪除；停用與軟刪除不同，歷史資料保留。

權限矩陣保留五種動作欄，並依現行 allowlist 決定哪些格子可用：KnowledgeProjects 的 view/create、Reports 的 view、SystemManagement 的 view/create/edit/delete、ProjectArchive 的 execute、ModelReport 的 view。不可用動作顯示不可操作標記，不能做成可勾選的 false。切換角色前保護未儲存草稿。

驗收：Given 唯讀使用者、受保護角色及含多來源的角色，When 查看、映射或變更手動成員，Then 既有後端授權與來源保護仍成立，矩陣完整呈現五個功能列與允許動作。

### SYSUX-009 登入與目錄

保留 PROTAUTH-001 至 PROTAUTH-012：一次只啟用 LDAP 或 OIDC 之一，兩模式共用直接 LDAP／AD 目錄與服務端 session；不要求特定 OIDC 產品。有效模式、來源、排程及秘密 configured 狀態由後端取得，不硬編碼示意的 LDAP、AD 或 OIDC 值。

預設鎖定。具 edit 的同一管理者完成依當前模式的 fresh authentication，才取得綁定 user/session/scope、固定 10 分鐘的解鎖；離開此大分類、取消、儲存、登出、逾時或失權後撤銷。分類內卡片定位不視為離開 identity，亦不延長解鎖期限。未確認撤銷前不能把舊解鎖狀態套入返回頁。

所有 identity 卡片共用既有候選驗證、必要候選登入驗證、原子套用與 last-known-good 規則，不因拆卡片變成各自直接儲存。LDAP／AD 來源類型與 ID 依原初始化固定規則；OIDC 專屬欄位只在選用 OIDC 時呈現。保持每日時間、IANA 時區與 people/groups/people_and_groups，不增加每幾分鐘輪詢設定。

「立即同步」仍需 edit，但不以 fresh-auth 解鎖作額外條件；同一 active run 不可重複送出，回傳及輪詢 queued/running/succeeded/failed。緊急管理者是部署程序限時啟用的唯讀資訊，不提供 Web enable/reset。

驗收：Given view-only、已鎖定、已解鎖、候選失敗或返回不同帳號，When 操作任一卡片或離開分類，Then 編輯、候選、鎖定、同步與資料保留均符合上述既有契約，不以本地狀態偽造成功。

### SYSUX-010 AI 模型與提示詞

保留 Chat、Embedding、OCR、Judge、Provider-specific 欄位、Chat/Embedding 配對、預設模型、真實連線測試及後端分頁。測試必須是管理者明確操作，不因進頁、搜尋或切換分類自動呼叫模型。Provider 憑證留在對應模型的管理視窗。

停用與軟刪除保持不同操作；依賴阻擋、名稱輸入確認、歷史關聯與憑證撤除沿 MODEL-002。模型列表預設每頁 20，可選 20/50/100，包含 active/inactive 並排除 deleted。

提示詞保留 Chat/Judge 的全域、模型專屬範圍、版本與啟停狀態；既有編輯視窗與版本紀錄不得省略。既有 Runtime 疊加順序不因畫面分組而改變，不另設未經規格化的 prompt 優先權控制。

驗收：Given 各模型類型、被引用模型及既有提示詞，When 篩選、編輯、停用、刪除或檢視版本，Then 所有既有欄位、限制與後端授權保持，且進入畫面本身沒有 Provider attempt。

### SYSUX-011 對外 API Key

此大分類只管理外部系統存取 NomoSmart 的 Integration Client 與其 API Key，不顯示 Worker 或基礎服務狀態，也不管理 AI Provider 或認證連線秘密。

預設畫面為清單、已授權摘要、搜尋／分頁、建立入口與各筆管理按鈕。沿 APIKEY-001 的清單與詳情資訊；目前實作缺少的基線能力需在開發計畫明列，不可因重畫示意圖宣稱已有。建立、編輯、授權專案、有效期、每分鐘上限、聯絡窗口及啟停／輪替／撤銷在所選用戶端的 Modal 完成；頁面不預先展開大型建立表單，不把這些欄位拆成無用戶端範圍的全域卡片。

保留 active/inactive/expired/revoked 語意、過期或撤銷限制、project allowlist、後端產生及一次性明文顯示、複製提示、關閉確認與稽核。撤銷與軟刪除保留歷史，不提供一般恢復。清單與 API 不回傳既有明文。

驗收：Given 具不同操作權限、過期或已撤銷的用戶端，When 開啟與操作此分類，Then 只對所選用戶端授權範圍執行動作，前後端各自拒絕越權，金鑰明文不能從清單或重新開啟的詳情取得。

### SYSUX-012 系統狀態

唯讀呈現 operations API 的 Worker、queue、retrieval/index、依賴服務、Provider 角色與最近錯誤安全摘要。服務名稱由實際回應取得，不將歷史 Keycloak、Vault 或 Milvus 列成必備元件。只顯示有來源的狀態、計數及檢查時間。

未讀取、空資料、失敗、未知與健康是不同狀態；沒有回應不得顯示零錯誤或綠色健康。保留重新整理及適當狀態說明，不在此編輯資料庫、儲存或加密金鑰。

驗收：Given API 不可用、部分未知或正常回應，When 檢視分類，Then 畫面依真實 evidence 區分狀態，不暴露原始 stack trace、token、prompt 或文件內容。

## 5 系統參數與資料契約

### SYSUX-013 一般設定與文件處理的欄位

| 分類與卡片 | API 欄位 | 型別與草案驗證規則 |
| --- | --- | --- |
| general/time 系統預設時區 | default_timezone | 非空字串，合法 IANA timezone，由後端 ZoneInfo 等正式時區資料驗證 |
| general/drafts 登入到期表單暫存 | session_expired_form_draft_ttl_minutes | 整數 0 或 5–120 分鐘；0 為停用該表單暫存 |
| documents/upload 單檔上傳大小上限 | max_upload_size_mb | 正整數，1–10240 MB，且不得超過部署硬上限 |
| documents/retention 退回文件暫存索引保留 | staging_index_ttl_days | 正整數，1–3650 天 |
| documents/ocr 每頁輸出上限 | ocr_page_max_output_tokens | 嚴格正整數，1–2147483647 tokens |
| documents/ocr 整份文件輸出預算 | ocr_document_max_tokens | 嚴格正整數，1–2147483647，且不小於每頁上限 |

布林、空字串、null、非整數與帶單位字串不得當成合法整數；清空欄位不能轉成 0 或自動帶入預設。MB 的 bytes 換算沿既有 1024² 規則。範圍、單位、錯誤原因與有效值均以後端契約為準，不在兩個分類各存另一套參數。

登入到期表單暫存不是一般 session 的閒置期限；PROTAUTH-007 的 1800 秒滑動閒置及無固定最長期限不變。系統預設時區也不會默默修改 identity 的同步時區。

「還原本頁預設值」只把該分類的後端預設帶入本地草稿；需管理者另按儲存才寫入。未取得有效值、預設或 revision 時，不提供可提交操作。歷史資料沒有修改者或時間時顯示未知，不補造日期。既存超出最終核定範圍的值不得因載入、初始化或其他分類儲存而被重置。

更新成功後，相關讀取端與新工作使用相同的有效值，執行中工作的既有 snapshot 保持。尤其單檔限制的讀取／上傳預檢與儲存值需一致，不能只有設定頁顯示新值。不得藉本次移動欄位自動重新 OCR、Embedding 或重建既有文件。

驗收：Given 合法、空白、布林、越界、無效時區及 OCR 預算交叉不合法輸入，When 儲存，Then 對應欄位明確提示且非法請求零寫入；成功後真實新工作與相關設定讀取一致，其他分類及既有工作不變。

### SYSUX-014 分區更新 API 草案

本節為已核准並已實作的分區契約，完整端對端驗收仍依案例追蹤。沿用 PostgreSQL `system_parameters` 作為有效值與預設值的來源，不要求為畫面分類複製資料或重設既有設定。本規格的「零寫入」指目標業務資料及設定值不變；既有合法安全稽核、request log 與 session 活動另依原契約記錄，且不得包含秘密。

`GET /api/v1/system/parameters` 保留現有六個平面欄位、`ocr_token_defaults` 與 `ocr_token_settings_hash`，另增加：

| 回應欄位 | 規則 |
| --- | --- |
| section_revisions | 含 general 與 documents 的不透明 revision 字串，各為 64 位小寫十六進位 |
| parameter_defaults | 六個欄位的後端預設值；沿用現有 OCR 預設，前端不得另造預設 |
| parameter_metadata | 以參數名為鍵，包含可取得的 updated_at 與 updated_by；歷史缺值為 null，時間有明確 offset |
| deployment_max_upload_size_mb | 目前部署單檔硬上限，只讀能力資訊，不是另一組Web參數 |

新增 `PATCH /api/v1/system/parameters`，只更新 `section` 所屬欄位。請求需有效內部 session、CSRF／Origin、最新 `SystemManagement.edit` 與必要 revision；GET 仍需 view。

```json
{
  "section": "documents",
  "expected_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "values": {
    "max_upload_size_mb": 200
  }
}
```

`section` 只接受 general 或 documents，`values` 必須是非空物件，只能包含本節欄位歸屬表的鍵。只送出改變的值；其他分類鍵、未知鍵、重複 JSON 鍵、缺 revision 與空 values 皆拒絕。禁止將任意 JSON 或秘密透過參數端點寫入。

成功回應只包含本次分類，避免呼叫端誤覆寫另一分類的草稿：

```json
{
  "section": "documents",
  "revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "changed": true,
  "values": {
    "max_upload_size_mb": 200,
    "staging_index_ttl_days": 7,
    "ocr_page_max_output_tokens": 10000,
    "ocr_document_max_tokens": 100000
  },
  "defaults": {
    "max_upload_size_mb": 100,
    "staging_index_ttl_days": 7,
    "ocr_page_max_output_tokens": 10000,
    "ocr_document_max_tokens": 100000
  },
  "parameter_metadata": {}
}
```

上述數值、revision 與空 metadata 僅示範資料形狀。正式回應必須使用實際值與可取得的逐欄 metadata，缺歷史值為 null；不得把此範例作執行成功路徑。general 回應只含其兩個欄位。

| HTTP 與安全代碼 | 條件與 UI 行為 |
| --- | --- |
| 200 | 已成功提交或相同值 no-op；changed=false 不新增參數異動稽核 |
| 401 authentication_required | Session 無效，沿原登入到期流程，不假裝已儲存 |
| 403 permission_denied | 無目前有效 edit／CSRF 或 Origin 不符，零寫入；實際錯誤封套沿共用安全格式 |
| 409 system_parameters_conflict | 同分類 revision 過期，保留草稿並提供重新載入與人工比對 |
| 422 invalid_system_parameters | 型別、分類、鍵或欄位驗證不合法，回傳安全逐欄原因，零寫入 |
| 428 system_parameters_revision_required | 缺少必要版本前提，要求重新取得設定，不自動以舊 PUT 重送 |
| 503 system_parameters_unavailable | 無法取得完整有效設定或儲存前提，不能以預設值假成功 |

既有共用錯誤封套或 CSRF 專用安全代碼若不同，須在核准開發計畫的 API 對照表明列映射；本功能的 conflict、revision-required 與 field errors 必須保持可辨識，不能全部降為通用失敗。

### SYSUX-015 原子性與舊寫入相容

general revision 綁其兩個有效值及該分類持久化異動版本，documents revision 綁其四個有效值、持久化異動版本及 OCR 交叉驗證所需完整狀態。revision 由後端以固定格式、具型別的分類值及持久化版本身份產生；前端不可自行猜 revision。每次實際異動均改變版本，包括值由 A 改為 B 再還原 A，不能只 hash 當前值而漏掉中間異動；同值 no-op 不更動版本。預設值另有來源，不能拿目前畫面字串當版本。版本持久化及必要 migration 須在核准計畫中具體列明，不能採單一程序的記憶體版本。

後端在同一資料庫交易中按共同固定順序鎖定所需參數及版本、核對分類 revision、合併指定鍵、驗證完整分類不變量、更新指定值、版本及 metadata、記錄稽核後提交。任何一項失敗整次回滾。不得由前端先 GET 六項、合併本分類、再 PUT 全部六項來冒充分區更新。

不同分類的並行修改可各自成功，不因另一分類的合法更新產生偽衝突；同分類由兩位管理者使用相同 revision 更新時，後提交者須收到 409，不能 last-write-wins。每頁與整份 OCR 預算必須以同一交易中的合併結果共同驗證，沿用既有 OCR hash 的拒絕過期意圖。

既有 `PUT /api/v1/system/parameters` 會寫入多個 core 欄位，只有 OCR hash 不足以防止一般／文件跨分類覆寫。採用以下已確認的升級政策：

1. 保留 GET 的既有欄位與 PUT 路徑，PUT 原參數欄位保留，但完整寫入增加必填 `expected_section_revisions`，需同時提供 general、documents revision；OCR 欄位仍維持原 hash 驗證。
2. 缺上述前提的舊 PUT 自協調升級起回 428，不能默默接受不安全完整覆寫。帶有效前提的相容 PUT 在同交易驗兩組 revision，任一過期皆零寫入。
3. 新管理頁只用 PATCH；版本化完整 PUT 僅供明列的相容呼叫者，不再作新 UI 儲存方式。至少保留一個相容版本，移除需另行變更管理。
4. 前後端須協調更新；新 Backend 搭配舊 Frontend 可能只能讀取、不能儲存。不可宣稱完全無破壞相容，也不能只回復舊 Frontend 就當安全回復完成。

兩種寫入路徑使用同一組交易／驗證規則，不能讓相容路徑繞過新版本檢查。系統參數儲存沿 `system.parameters.update` 稽核，包含 section、實際異動鍵、允許的舊／新值、actor、時間、request ID 與結果；只記本次異動，不引入其他分類秘密。

驗收：Given 兩位管理者、不同分類、同分類 A→B→A 與舊 PUT 呼叫者，When 交錯送出更新，Then 分區更新互不覆寫、同分類舊版本即使值還原也拒絕、無版本舊 PUT 拒絕、驗證失敗原值完整保留，且 GET 與真正 DB／consumer 讀回一致。

## 6 編輯狀態與非功能需求

### SYSUX-016 草稿與非同步狀態

每個分類的讀取狀態與編輯草稿各自隔離，快取綁定目前使用者與授權範圍。只載入當前分類及其必要相依資料，不因進入系統管理就啟動所有分類的完整查詢、同步、連線測試或模型呼叫。過期 request 不得覆蓋後切換分類、身分或範圍的資料。

| 狀態 | 可見內容與操作 |
| --- | --- |
| loading | 載入提示或與內容對應的 skeleton，未取得有效前提的儲存／建立停用 |
| ready | 以實際資料顯示，操作依權限、鎖定及依賴狀態決定 |
| empty | 已成功讀取且真的無資料，才顯示空狀態與可用建立入口 |
| forbidden | 說明權限不足，不顯示或洩漏未授權資料 |
| read_failed | 顯示安全錯誤與重讀，不把失敗當成空清單或零數量 |
| dirty | 以文字及圖示提示變更，顯示作用範圍、取消與分類儲存 |
| saving | loading 與防重送，不允許重複寫入 |
| conflict | 保留本地草稿，提供重新載入及人工比對，不自動合併後重送 |
| outcome_unknown | 說明結果待確認，允許安全讀取／查詢結果，不自動重播寫入 |

一般與文件分類各有一組保存動作；該分類各卡片不虛構獨立 API。「取消變更」恢復目前基線；背景重讀不覆寫 dirty 欄位。成功回應只更新本次分類基線及 revision，不覆寫另一分類或 Modal 的草稿。還原預設值後同樣須經儲存。

切換大分類、權限角色、選定用戶端或離開有草稿的 Modal 前，依相應範圍顯示「繼續編輯／放棄變更並繼續」。取消離開保留原分類、URL、草稿與焦點；放棄只清除該編輯範圍。identity 的離頁鎖定依 SYSUX-009 執行，不能沿用一般參數保存流程。

網路 timeout 或回應遺失不等於失敗，也不等於成功；目前值恰與送出相同，仍不能單憑相等就宣稱該次 request 成功。沿 FEEDBACK／既有 operation guard 查詢可證的結果；未知完成前不重試寫入，不重播輪替、撤銷、同步或模型測試。

草稿只在當前記憶體中管理；不新增 localStorage、IndexedDB、可讀 cookie 或 sessionStorage 表單內容保存。既有明確 opt-in 的登入到期、後端加密、同使用者／路徑／一次性流程草稿恢復規則保持，secret 永不列入；不能因拆分類擴張恢復範圍。

驗收：Given 草稿、慢回應、timeout、409、權限撤回及快速分類切換，When 回應抵達或要求離開，Then 基線、草稿、目前位置與真實結果保持一致，沒有重複寫入或跨分類污染。

### SYSUX-017 語言與可及性

所有新增名稱、欄位說明、狀態、確認、錯誤、空狀態與可及名稱同時維護 `zh.json` 與 `en.json`。切換語系保留 section/panel、草稿及型別化訊息，不以翻譯字串相等判定成功或錯誤。

分類使用有名稱的導覽連結／按鈕與目前位置語意；定位後捲動不被 sticky Header 遮住，焦點移至目的卡片標題或適當欄位，不搶走正在輸入的焦點。搜尋與 disclosure 可用鍵盤、Enter、Escape、可見 focus；欄位具 label、單位與錯誤的 aria-describedby，狀態不只用顏色。Modal 保留焦點限制、關閉後回觸發點及未儲存保護。

桌面內容仍是一列一設定；窄螢幕讓單一設定的標籤、說明與控制依序堆疊。側欄在既有手機斷點改為可開關抽屜，保留相同順序、目前分類、Escape／遮罩關閉及背景焦點管理，不改成第二套分類。控制至少 40px；表格可在自身容器水平捲動，整頁不得溢出；長網址／DN／中英文標籤不截斷主要操作。維持可讀文字與對比，不靠縮小字體塞入畫面。

驗收涵蓋 1440、1024、768、767、390、320px，繁中與英文、長名稱、錯誤訊息、兩層縮排、Modal 及表格；prefers-reduced-motion 停用非必要平滑捲動與動態。

### SYSUX-018 安全與部署

保留服務端 session、CSRF、最新權限、fresh-auth、revision、憑證去敏、soft delete 與既有稽核。分類調整不授權讀取 secrets、任意服務 URL、原始 provider exception、文件內容或其他使用者設定。參數更新可稽核安全值；連線秘密與金鑰只稽核 configured／版本／動作與安全結果，不記原文或密文。

本優化不新增執行環境、必要外部服務、明文設定或 Web 加密主金鑰管理。不以畫面整理修改 Compose／Helm 的既有值或原資料。新增分區契約若獲准，交付需明列前後端相容版本、升級及回復方式；同源 Next 代理、edge 與 CSRF 寫入方法處理需一致支援 PATCH，不可為接通而放寬 Origin 或移除保護。有 schema／migration 需要時，必須在實作前另列契約與核准，不能自動補建或覆寫資料。範例值與示意圖不得當成部署輸入。

驗收：Given 正常或惡意跨分類 payload、權限撤除、缺 CSRF、過期解鎖及舊客戶端，When 嘗試修改，Then 後端拒絕越權或缺前提寫入，DB、log、audit 與瀏覽器持久化均無新增 secret。

## 7 驗收與規格確認

### SYSUX-019 需求與案例

以下為未執行的驗收定義。正向流程使用真實、隔離、已設定的服務與正式程式，不以 mock／stub／fake Provider 或固定成功回應驗收。純函式原生輸入可驗型別／選單映射，但不能代替真登入、寫入與業務整合證據。缺少前提應列 BLOCKED，不改 PASS。

| 案例 | 最低證明與可觀察結果 | 需求 |
| --- | --- | --- |
| S389-T01 | 真管理頁七分類順序、people/users 預設、九模組完整歸位與設定搜尋定位 | SYSUX-001、002、003、007 |
| S389-T02 | 所有舊 tab、新 section/panel、非法／重複參數、reload、合法認證返回各依定位表處理 | SYSUX-006、009 |
| S389-T03 | 獨立欄位全垂直；至少三組父子關係同層同縮排且無第三層；標題區可辨識 | SYSUX-004、005 |
| S389-T04 | 真 DB 驗 general 的兩欄與 documents 四欄 allowlist、型別／邊界／IANA／OCR 交叉驗證，錯誤零寫入 | SYSUX-013、014 |
| S389-T05 | 真並行不同分類互不覆寫、同分類過期及 A→B→A 舊版本 409、版本化舊 PUT 與缺前提 428、交易失敗完整回滾 | SYSUX-014、015 |
| S389-T06 | 還原預設僅改本地；取消／切換保護；舊回應不污染；真傳輸結果不明時無自動寫入重播 | SYSUX-016 |
| S389-T07 | 真只讀／可編輯角色、來源聯集、system-admin 保護與五列矩陣；拒絕操作不改資料 | SYSUX-001、008、018 |
| S389-T08 | 真當前認證模式、10 分鐘解鎖、候選檢查／必要登入／套用、離頁鎖定、鎖定下合法立即同步與真 run 狀態 | SYSUX-009、016、018 |
| S389-T09 | 真模型清單／分頁／依賴限制、提示詞作用範圍與版本；進頁及切換不產生 Provider attempt | SYSUX-010 |
| S389-T10 | 真用戶端 Modal、project allowlist、有效期與速率、啟停／輪替／撤銷、一次性明文與去敏；僅本輪自有資源 | SYSUX-011、018 |
| S389-T11 | 真 operations 回應／服務不可用／未知與空資料各可辨識，無偽健康與敏感內容 | SYSUX-012、016 |
| S389-T12 | 六種寬度、兩語系、鍵盤與焦點、長字串、錯誤及 Modal；頁面無水平溢出 | SYSUX-004、005、017 |
| S389-T13 | 真儲存後 DB、GET、上傳預檢與新工作設定一致，原執行 snapshot／其他參數保持 | SYSUX-013、015、018 |

功能測試只在本變更開發計畫獲准後開始。認證、授權、並行更新、秘密及一次性操作為必驗，不以畫面快照取代；真付費模型測試另需具體額度，不因產生示意圖而取得呼叫授權。保留前後端各 80% 與完整來源分母門檻，沿用既有全案發布、安全與部署規則，不將本功能文件或局部測試當成整案達標。

文件階段可執行 `spec:doctor`、`spec:trace`、`test:plan` 等靜態守門；開發啟動前須把 CHG-389 登記為執行中變更，新增經確認的 `DEVELOPMENT_PLAN.md` 區段及人類 Gate 4，再執行本範圍的 `plan:approved`。目前其他 active change 的通過不得借作 CHG-389 核准。實作後依影響執行 lint/build、真正 API／E2E／coverage；涉及部署交付再跑 Compose、Helm 與 config-policy。各命令、來源、結果與缺前提需記錄，不宣稱尚未執行的驗收完成。

### SYSUX-020 已確認決策與完成條件

| 決策 | Peter確認的結果 |
| --- | --- |
| D1 | A：七分類依第2節排序，預設people/users；API Key清單及所選用戶端Modal |
| D2a | A：section/panel卡片定位，保留九舊入口；parameters導general並連往documents |
| D2b | A：一般兩項、文件四項，各分類一組儲存；其他業務沿原流程 |
| D3 | A：分類版本與PATCH；完整PUT缺兩組revision回428，協調升級 |
| D4a | B：上傳1–10240 MB，仍受部署硬上限約束，不自動改目前值 |
| D4b | B：退回暫存1–3650天，不自動改目前值 |
| 實際生效範圍 | B：納入上傳、暫存到期與參數實際讀取一致性 |
| 期限變更 | 只影響後續退回；原期限固定，升級前退回資料保留另盤點 |
| 計畫核准 | 2026-11-08 Peter「執行這份計劃」，Gate2 CONFIRMED、Gate4 APPROVED |

規格及計畫核准見CHG-389-APPROVAL.json；實作／驗收狀態見CHG-389-RESULT.md。功能完成仍須真服務、安全與完整驗收證據；原各80%門檻不變，示意圖、元件排版、SQL語法或局部案例不能代替發布驗收。

## 8 設計參考與來源

| 參考 | 用途 |
| --- | --- |
| [新版側欄與文件處理示意](design/chg389-settings-document-processing.png) | 七分類、獨立設定一列一項、文件四參數及分類保存位置 |
| [獨立對外 API Key 示意](design/chg389-settings-external-api-key.png) | 對外授權入口、清單優先與 Modal 管理關係 |
| [主規格](../SPECIFICATION.md) | SYS、PROTAUTH、ROLE、PERM、MODEL、PROMPT、APIKEY、FEEDBACK、TEST-002 等基線 |
| [API 相容紀錄](../API_COMPATIBILITY.md) | 新分區契約與舊入口的待核准變更登記 |
| [測試計畫](../TEST_PLAN.md) | S389-T01 至 S389-T13 的階段與前提 |
| [需求追溯](../TRACEABILITY.md) | SYSUX-001 至 SYSUX-020 的實作目標與驗收對應 |

示意圖使用非即時資料，只作版型參考；圖中舊範圍文字由D4已確認結果及平台能力取代。文字契約優先於圖片，既有功能中未顯示於截圖的欄位或狀態不可因此刪除。

實作對照來源為 `SystemManagementWorkspace.tsx`、`ProtocolIdentityPanel.tsx`、`systemRouteState.ts`、`systemManagement.ts`、`frontend/src/lib/api.ts`、`backend/app/api/routes/system.py`、`backend/app/api/schemas.py` 及 `backend/app/domain/system_parameters.py`。這些來源用於識別差異，主規格仍是產品決策依據。


## 9 已確認的執行補充（2026-11-08）

Peter確認D1=A、D2a=A、D2b=A、D3=A、D4a=B、D4b=B，選B同時修正實際生效功能；退回期限選「只影響之後退回的文件」。本節取代前文待確認及較小範圍的草案文字，原稿狀態保留作歷史。Peter以「執行這份計劃」核准上一則完整計畫，非借用CHG-388核准。

### SYSUX-021 上傳有效限額

資料庫max_upload_size_mb控制新上傳、替換檔案及每次遠端擷取；部署Settings保留request、scratch、inflight及單檔硬上限。取得授權後、讀取body前讀取不可變限額快照，同次streaming及最終驗證共用；GET upload-config回有效值及deployment_max_upload_size_mb。高於部署能力的寫入422，既有DB不合法／缺失或超能力回503，不clamp、不假預設。既有文件下載、來源重讀與處理中工作保持原安全限制。Given限額改變，When開始新intake，Then新限額生效，原請求快照和舊文件保持。

實作決策422：HTTP遠端擷取必須使用串流，同一次快照的max_bytes在讀取前檢查有效Content-Length並在逐塊讀取時累計，超限回既有sync_file_too_large 413並關閉回應，禁止完整讀取後才拒絕。成功回傳的內容與metadata、TLS／SSRF／redirect和其他錯誤契約不變。測試使用真HTTP服務的已知長度與chunked同一合成檔，以及正常小檔。

### SYSUX-022 退回暫存搜尋到期

新退回在同一交易保存UTC rejected_at、ttl_days、expires_at及持久工作，1天=24小時；Outbox available_at=expires_at。變更TTL只影響後續退回；升級前退回資料不補到期工作，先保留另盤點。到期後新暫存檢索拒絕並顯示staging_retention_expired，既存內容／歷史可讀。Worker僅精確刪project/document/version所屬OpenSearch staging文件，支援共用index，禁止整個共用index刪除。PG原文、切片、向量、S3原檔、審核歷史、Neo4j與published保持。重新檢查版本、scope、Active Manifest及活動工作／其他版本引用，受保護則延後並記安全原因。刪後count=0才完成；失敗／未知可冪等重試，租約防舊工作覆寫。Given新退回自然到期，When清理，Then只有精確staging scope消失，其他資料完整；舊資料不受新TTL影響。

既有專案封存政策優先於TTL工作：封存交易取消該專案未完成TTL工作及待派送事件，保留取消稽核；recovery只掃active專案，執行器於外部I/O前再次確認active。封存原有的未完成版本清理成功後，同交易移除這些版本的TTL工作／事件，再依既有政策移除版本及審核資料，留下專案清理稽核；不宣稱TTL工作完成。此相容處理不擴大封存刪除範圍，也不影響一般TTL清理保留內容／歷史的規則。

### SYSUX-023 預設時區生效

default_timezone作新資料服務排程的初始值及API省略timezone時的預設；connection-options透過原專案權限只回安全預設。操作者明選timezone優先，已存資料服務及目錄排程保持；簽核日期、API Key日期輸入沿原瀏覽器時區。Given預設改變，When新建排程且未覆寫，Then保存新預設，既存排程不變。

### 持久化與操作契約

V055新增system_parameter_section_revisions（general/documents、正bigint版本）及staging_retention_jobs（scope、approval、TTL、期限、狀態、租約、checkpoint、安全錯誤），不重設舊值。GET取得一致值／版本；PATCH及PUT固定先鎖分類版本再按key鎖參數；真變更遞增版本，SHA256綁型別值及計數，可拒絕A→B→A；no-op不變metadata。缺必要初始化回503；重複JSON key、未知key、null、bool及不合法型別422。CSRF沿csrf_invalid=403；共用封套維持code/message/details/request_id。到期狀態以獨立job回應，不改immutable審核證據。

新增驗收：S389-T14（新上傳／替換／遠端、部署能力、處理中快照及舊讀取），S389-T15（自然到期、未到期、舊資料與期限快照），S389-T16（共用索引、發布及新修訂保護、重送／中斷恢復與去敏），S389-T17（新排程預設、明選優先與舊排程保持）。最低一天的自然到期案例未到期不得當PASS；不偽造時鐘、Provider或外部成功。


2026-11-08實作決策：Worker復原週期、claim租約、重試間隔與批次大小分別以STAGING_RETENTION_RECOVERY_SECONDS／LEASE_SECONDS／RETRY_SECONDS／BATCH_SIZE外部化，預設60秒／300秒／300秒／100筆，沿typed config與Compose env_file／Helm backend.env傳入。這些是部署操作參數，不增加Web設定分類。前端衝突提供只讀目前值比對及明確放棄輸入入口；查詢不解除未知寫入結果的重送守門。

部署啟動檢查需驗證兩個新表、兩個分類正版本及六個參數；缺失不可宣稱ready。表單恢復保留原同使用者／路徑加密流程與秘密排除規則；本頁非敏感草稿保留空白字串，不將清空數值轉為0。暫存清理的獨立SQL／OpenSearch原生刪除測試只證明範圍及冪等，不替代自然到期驗收。

分區與相容PUT以同一worker thread完成同步SQLAlchemy交易；HTTP body以非同步方式限16KiB讀取，等待資料庫鎖不可阻塞ASGI事件迴圈。

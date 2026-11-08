## CHG-422 — NativeOCR與設定改版配套升級

本次以已發布0.2.3為底，V057新增設定分類版本及保留工作兩表，既有V001..V056不改。下方CHG-389為先前設定規格紀錄；其中V055設定移轉改由V057承接，現行可編輯OCR欄為ocr_request_max_output_tokens及ocr_document_max_tokens。ocr_page_max_output_tokens沿已發布版保留歷史讀值，企圖改值仍422 ocr_page_token_setting_retired。GET保留既有原生policy/hash/default欄並新增分區metadata；PATCH為分區CAS，PUT須兩區revision及既有OCR hash。缺前提428、同區舊版本409、非法422、缺資料503。舊無revision writer必須配套升級；不宣稱任意舊版可寫回退。既有對外API Key不需輪替。詳CHG-422計畫及設定伴隨規格。

## CHG-389 — 已核准的系統設定契約

2026-11-08 Gate4 APPROVED；程式已接線，驗收與部署狀態見docs/CHG-389-RESULT.md。正式companion第5、9節優先於下方保留的草案。

- GET parameters保留舊欄位，新增section_revisions、parameter_defaults、parameter_metadata與deployment_max_upload_size_mb。
- PATCH只允許general/documents本分類欄位，需expected_revision；相容PUT需expected_section_revisions兩區版本，OCR仍需原hash。無版本428、過期409、非法422；body16KiB且拒絕重複JSON鍵。
- GET upload-config回DB有效單檔限額及部署硬上限；新intake固定快照，舊來源讀取保持部署限制。
- connection-options新增default_timezone，沿專案授權；新建排程省略timezone取目前預設，既存排程保持。
- knowledge detail新增可選staging_retention期限／清理狀態；到期暫存檢索409 staging_retention_expired，歷史與內容仍可讀。
- 前後端／Worker需配套升級至V055；舊無版本writer必須升級，不影響既有對外問答API或要求API Key輪替。

## 既有相容紀錄

## CHG-363 — 現行協定認證與統一session契約

2026-10-26文件同步。PROTAUTH-001..012及已核准P6的契約已在目前來源實作；實際驗證仍為PARTIAL，AD、完整套件／80%及其他缺口見[驗證紀錄](docs/AUTHENTICATION-STATUS.zh-TW.md)。本文件不宣稱所有產品能力或實機部署已驗收。一般session只有1800秒滑動閒置期限、無固定最長時數；有效配置以Backend current revision為準，前端傳mode不構成授權。

| Contract | Current behavior | Compatibility / permission |
| --- | --- | --- |
| GET /api/v1/auth/config | mode、顯示名稱、idle_timeout_seconds=1800、absolute_timeout_seconds=null及OIDC能力狀態 | 公開去敏metadata，不含內部endpoint／DN／secret／人員。新Frontend用此決定唯一登入模式 |
| GET /api/v1/auth/session | authenticated、csrf_token、idle_expires_at及有效模式；只讀取、不延長登入 | HttpOnly cookie對應的去敏狀態；CSRF proof不是身分／編輯授權，不可放URL或持久化browser storage |
| POST /api/v1/auth/login | LDAP username/password只用當次TLS user bind；成功發HttpOnly session，不回token | mode不符409 auth_mode_unavailable；驗證失敗安全401、限流429、上游不可用503；不提供一般本機帳號 |
| POST /api/v1/auth/oidc/start；GET /api/v1/auth/oidc/callback | Backend-owned code/PKCE/state/nonce／5分鐘一次性flow，callback public URI=/api/backend/auth/oidc/callback | mode不符409；operator需註冊精確URI，不調產品Admin API；Next /api/auth/start導入Backend流程 |
| GET /api/v1/auth/me | 以內部session解析，回傳user_id／subject等平面人員欄位、permissions／visible_project_ids及同步groups；另有mode／csrf_token／idle_expires_at | 401無session／idle expired／revoked；有效session但無准入回403；停用或安全撤銷可使session失效，權限不足不延長登入 |
| POST /api/v1/auth/activity | 真使用者操作回報；有效session＋CSRF／Origin，server更新last_activity_at並回idle_expires_at | 背景request不得保活；client timestamp不可信；expired回401不能復活，15秒有界合併 |
| POST /api/v1/auth/logout | 原子撤銷本session／unlock、清cookie、安全audit；目前upstream_logout=false，本地登出仍立即有效 | local撤銷不依上游成功；保留其他裝置session，管理員停用／敏感切換按規格撤全部受影響session |
| identity-settings GET／validate／PUT／lock | 擴充mode／OIDC／directory／每日schedule、revision及write-only secrets。secrets未傳保留，明確replace／clear；GET僅configured／version | GET需view；修改需edit＋當次reauth的10分鐘unlock＋CSRF＋revision。current／candidate及secrets原子一致；secret value／ciphertext不回傳 |
| identity-settings reauth/start／complete及共享auth/oidc/callback | 依當前mode作fresh OIDC／LDAP，emergency僅在activation窗口；purpose=candidate只能證明候選可登入，不核發新權限 | 不信任query success／client auth_time；同一user／session／scope綁定，TTL／replay／失權拒絕；候選啟用需fresh current授權及5分鐘candidate evidence |
| POST /api/v1/system/identity-settings/identity-bindings | 明確提供source／issuer／subject／directory object／內部user與設定revision，持久綁定已同步人員 | edit＋unlock＋CSRF；只允許唯一對應，衝突409，不以email猜測或JIT；無新角色授權 |
| identity-sync run／runs與external-groups | queue methods／run ID／原scope保留，直接LDAP／AD phase／來源識別；每日02:00 Asia/Taipei預設，可手動 | SystemManagement.edit才觸發；讀取view；同步失敗保留快照，無5分鐘poll或30分鐘快照封鎖 |
| roles／users及group mapping | group來源支援LDAP與AD，保留一對一／lock_version／manual聯集；user payload補中立識別及兩種啟用狀態 | 不刪既有UUID／FK；舊keycloak_user_id先作nullable legacy輸出，相容期內不拿它作新認證依據 |
| 舊 /auth/oidc/config、/auth/callback及external Bearer | config保留一release的去敏OIDC相容資料，LDAP mode回409；舊callback回安全重新登入，不交換舊code；舊Bearer／flow升級後失效 | 是明列coordinated auth contract migration，需Frontend／Backend／worker／bootstrap一致升級與重新登入；對外API Key契約不變 |

目前公開能力為refresh=false、silent_sso=false、upstream_logout=false。舊Next `/api/auth/exchange`及`/api/auth/refresh`回410；通用OIDC在Backend完成code exchange，瀏覽器不再持有上游access／ID／refresh token。對外Public Integration API的API Key Bearer契約保持，不與內部session混用。

認證／目錄connection secret採資料庫加密是本次明列政策例外；其他商業integration secret-reference-only規則不改。部署key仍外部化，沒有新未認證Web初始化／emergency啟用API。原版本回復不得只換image或刪除新schema，具體migration及last-known-good流程見開發計畫。

以下保留各變更的原始相容紀錄；其中舊Keycloak／Bearer／Theme認證敘述若與上方契約2衝突，以契約2為準。

## CHG-354 — 待發布分頁的新增相容契約

2026-10-20。Gate 2 CONFIRMED by Peter with「Ok」；Gate 3 WRITTEN；Gate 4 APPROVED by Peter on 2026-10-20 with「同意」。以下契約已實作，真API3案例及UI3組主要驗證通過，分層缺口見CHG-354-RESULT.md，依SPECIFICATION.md之PUBLIST-001..004及docs/CHG-354-PENDING-PUBLISH-PLAN.md。

| Contract | Planned behavior | Compatibility / permission |
| --- | --- | --- |
| GET /api/v1/approvals/pending-publish/page | 新增limit20／1–100、opaque cursor；items／has_more／next_cursor／精確total | items沿既有ApprovalPendingPublishResponse，先有效actor／可見專案／Owner及待發布資格裁切；version去重，同statement計數，穩定keyset與scope-bound cursor；401／403／安全422不洩漏其他資料 |
| GET /api/v1/approvals/pending-publish | 保留舊陣列與既有最多100筆 | 舊caller相容；現行工作台遷移新page，第101筆後由新端點提供，不能宣稱舊API已無上限 |
| POST發布及四個簽核tab的GET | 保持既有契約與授權／busy／冪等／證據 | 此獨立待發布清單不套四tab條件；發布成功後只GET重讀第一頁，讀取失敗不重送寫入 |

沒有DDL／migration／依賴／新產品env／部署模板變更。新API／舊陣列相容已透過真服務驗證；既有產品修改精確記錄於CHG-354-PRODUCT-MANIFEST.json，雙端80%／模型後測界線保持。不宣稱原部署已更新。

## CHG-351 — 簽核查找與登入語言的相容性設計

2026-10-19。Gate 2 CONFIRMED；Gate 3 WRITTEN；Gate 4 APPROVED by Peter on 2026-10-19 with「Ok」，以下均為尚未實作契約。正式條件與測試見 SPECIFICATION.md 及 docs/CHG-351-P2-IMPLEMENTATION-PLAN.md。

| Contract | Planned behavior | Compatibility / permission |
| --- | --- | --- |
| GET /api/v1/approvals/pending、history、rejected | 新增文件名稱 q（trim／100／literal substring）；submitter_id 為正式人物條件 | 原 envelope、limit、排序／actor／project scope 保持；editor_id deprecated alias，同值接受、異值安全 422；新條件綁 cursor，不默認延用舊條件 cursor |
| GET /api/v1/approvals/my-submissions | 新增 q 與 stage（目前有效 task）；本人條件不開放換人 | 保留原本人／專案範圍，完成且無 current task 不命中指定審核階段，status/result 與 stage 分開 |
| GET /api/v1/approvals/filter-options | 新唯讀候選：kind=project 或 submitter、tab 四種，可選 project_id／q／cursor，limit20/max100；items:[{id,label}]、next_cursor、has_more | 先套原 tab actor／project／關係範圍取 distinct，再搜尋／排序／分頁；不可列全站人員、無權限名稱／數量；不額外要求 SystemManagement 權限 |
| date_from／date_to | 保留 inclusive datetime；UI 結束日含整天且標示本機時區，轉 UTC 保留時間精度 | 保留各 endpoint task/request submitted_at；不改為 completed_at、updated_at；新增條件驗證安全 422 |
| GET /api/auth/start → Keycloak authorize | allowlist ui_locales=zh-TW/en，無偏好以產品繁中預設 | 只新增標準語言提示；state／nonce／PKCE／flow cookie／TTL／token storage／returnTo 不變；直接 Keycloak 規則保持 |
| Header 全站搜尋 | 移除未接行為的入口，不新增全站搜尋端點 | 專案／簽核／文件選取的局部查找保留；既有 serving／public retrieval API 不刪除 |

無 schema／migration／新產品 env／依賴／角色或審核、發布寫入契約變更。API 行為與 cursor 相容性須真服務驗證；未實作狀態不得宣稱部署完成。

## 先前工作紀錄（歷史）

2026-10-19 CHG-350：P2第一批11項提案只改前端可用性／可及性與兩份Keycloak CSS；沿既有DTO／API／授權與首頁請求集合，無API欄位、端點、狀態或錯誤碼變更，無DDL／migration／runtime配置鍵。Gate4 APPROVED by Peter；11項前端修正已依核准範圍實作；任何後端契約需求須另明列規格與追溯再核准。

## CHG-330 — 計畫中的四項修正相容邊界

Gate 2 CONFIRMED；Gate 4 APPROVED，尚未實作或執行功能測試。

| Contract | Planned behavior | Compatibility / permission |
| --- | --- | --- |
| 跨視窗未知操作 | 同登入同分頁記憶體保護，先真斷線驗證；GET200不能證明原mutation成功 | 預期不加API/DDL，不改原role/version/idempotency/授權；若證據需擴大backend持久合約，先補計畫核准 |
| 模型憑證解析錯誤 | 兩個合法legacy context均解密失敗統一model_credential_invalid503 | Probe原碼保持；Chat/Embedding/OCR原invalid_encrypted_value422在model resolver邊界改503。一般EnvelopeCipher仍422，Secret deny/unavailable、production legacy禁止與各業務缺值檢查保持；前端安全mapping及consumer回歸 |
| FeedbackMessage | 明確tone/code/state決定狀態與ARIA，翻譯文字不改tone | 無API body／權限變更；caller在錯誤邊界明確傳unknown warning，原single announcement／scope保護保持 |
| Installer HTTPS | redirect及final URL核對scheme/hostname/effective port，同來源443預設等價 | 原同host跨埠跳轉將安全拒絕，需配置正確原始endpoint；CA/hostname及directory max_redirects=0保持，不新增allowlist例外 |

2026-10-13 CHG-330有限交付：OPSAFE-001..004實作、修前真斷線確認duplicate version、修後4Browser／3keyboard-API-key UI、13nativeCipher/mount/HTTPS、28既有security契約、完整147Browser/294contracts PASS；formal FE各80%仍FAIL（lines22.22／statements21.17／functions21.78／branches20.88），fullBE/E2E/production未完成。最終2image HIGH/CRITICAL0／secret0／SPDX、當次publicDB；npm0／可稽核pip無已知漏洞，2local forks缺口保留。manual4應用／11healthy／真LDAP/PKCE/TLS/ready200；當前同步後部署前後14表全一致，143chunks／usage207。isolate原14表完全一致，16chunks／usage71，owned控制撤除/audit保留、9服務停止保留卷。manual測試期間原LDAP02:00排程同步重建2role_users關係，原before漂移及audit保留，不能冒稱原14表全相同。0Provider／原modelkey／backup，不改BE-004／0.2.0或發布。詳docs/CHG-330-IMPLEMENTATION-RESULT.md/json；原失敗歷史保留。

## CHG-329 — 計畫中的三項API相容修正

Gate2 CONFIRMED；Gate4 APPROVED；尚未實作。

| Contract | Planned behavior | Compatibility / permission |
| --- | --- | --- |
| GET /api/v1/users、/roles | optional q最大100；filter前置／原排序／offset/limit；X-Total-Count | 原array body/default50/max200保持；users scope與system view保持，不把所有users當可見候選 |
| GET /api/v1/users/{id}、/roles/{id} | 既有安全summary／role DTO、404不存在/刪除 | additive read endpoint，SystemManagement.view必需，no secret／新權限 |
| GET /api/v1/projects、/integration-clients | 原project q/total/offset及client name/cursor/has_more接前端 | 既有body/visibility/cursor/filterbinding不改，不新增假的Client total pages |
| role users／external-group-mapping讀寫 | frontend消費最新正式read snapshot及lock，draft分離 | API原契約不改，GET不重播PUT，不猜unknown成功 |
| GET /api/v1/projects/{id}/data-sources/connection-options | credential_modes=[secret_reference]，原nonproduction policy可加inline | additive、安全project editor/configuration scope；不列Secret names/values/host paths |
| data-source validate/test/create | Wizard credential_secret_ref接既有schema；validate使用runtime Settings | 原payload/type/path保持；production仍禁止plaintext，invalid/missing refs安全拒；configuration_valid不是network success |
| model update | 無變動 | BE-004已由Peter排除；不加expected-version或row-lock設計 |

無DDL／新產品env／依賴；只source-bound manual4應用有限交付，不修改已發佈0.2.0資產。合成測試Secret及控制metadata在隔離／未提交環境，existing modelkey讀取0。

2026-10-12 ADMINFIX-001實作決策：保留現有來源／啟停篩選，users增加可選auth_source/is_active、roles增加可選is_active，均先filter再count/page；這是完整後端查詢所需的additive參數，不擴充權限。正式表格與候選頁分開，ID快照cache供已選項目解析，不以cache當完整資料庫。

2026-10-12 ADMINFIX-003真Docker根因及必要修復：backend compose entrypoint無條件將COMPOSE_SECRET_MOUNT_ROOT覆寫為只含平台檔的private/secrets，新掛載business Secret因此runtime_secret_unavailable。沿既有外置COMPOSE_SECRET_MOUNT_ROOT，平台_FILE私有tmpfs準備不變，business/model credential只讀operator掛載、不複製值。Source validate/create增加既有resolver的mount metadata檢查（regular/nonempty/readable／production0400或0600／root containment，不讀值），避免缺檔仍建立半成品。依既有SECRET-002的明確Secret/key白名單，production runtime reference僅允許既有RUNTIME_SECRET_ALLOWED_REFS中的精確canonical條目，不讓wildcard授權任何整份平台Secret；Compose亦使用同一既有設定。此為第三項能在真Docker運作且不誤取平台秘密的必要consumer／部署修復，無新env／DDL／新resolver、無model PUT或並行版本設計。Helm的既有allowlist設定改由非敏感values提供、預設空，operator需明確設定business Secret/key；舊wildcard需配置精確條目，資料庫參照不自動改寫。先用本輪新合成Secret與非法/平台名稱ref驗拒絕，不讀原秘密。實作區域追加app.security.secrets、deploy/docker/compose-secret-entrypoint.sh與同來源Helm資產／configmap/values；AF-T06/08追加啟動root保留、metadata無讀值、production精確白名單與缺檔create零資料。維持已核准三項範圍；BE-004仍排除。

2026-10-12 CHG-329有限範圍交付：ADMINFIX-001..003已實作，人工Docker四應用更新／11healthy、真LDAP/PKCE/可信TLS及/ready200。13真API分頁＋8管理Browser assertions、12真SourceAPI/HTTP/S3sync及nativeproductionpolicy、5真SourceModal中英/三寬度、5mounted安全native、完整145Browser/288contracts PASS。formal FE仍因完整lines22.30%、statements21.19%、functions21.61%、branches20.98%<各80%FAIL；fullBE/completeE2E/nonlocalproductionstartup/Source正式parentproject-ready及4其他protocol保持OPEN/NOT_RUN，無fake成功。backend mounted-deployment契約PASS，另secretpackaging factory-init預期帳號測試1FAIL，來源工作不掩飾此缺口。兩映像HIGH/CRITICAL0/secret0、SPDX及config/spec/trace/approval/lint/build/syntax PASS。原兩環境14表完整一致、143/16 chunks及207/71usage保持；所有精確owned清單/role/client/project/nativegroup/sourceDoc/S3/outbox移除，新Secret卷及HTTP來源移除，真audit保留、隔離停止保留原卷，LDAP/權限不變。0Provider/模型key讀取/backup，不發布新版或做BE-004。全部失敗歷史（接線/selector/原測試前提/首清理HEAD404解讀）保留，成功不覆寫成初次PASS；詳docs/CHG-329-IMPLEMENTATION-RESULT.json。

## 先前紀錄

2026-10-12 Peter以「同意」核准CHG-328開發計畫；Gate 4 APPROVED，四項實作與零Provider驗證可開始。此前待核准／尚未實作說明為歷史，當前核准以本記錄為準。

# API Compatibility Inventory

## CHG-328 — 計畫中的四項相容性補齊

Gate2 CONFIRMED；Gate4 APPROVED，尚未實作。

- Models POST/PUT／DTO形狀保持；inactive-default、無效最終active/default配置与必要name/provider/config/is_active/is_default明確null改為安全422，拒絕前不清原default或改row。停用取消default、原nullable endpoint／credential三態保持，不新增expected-version契約或DDL。
- IntegrationClient PUT日期本來即可省略；前端改為只改才送，nullable明確清除才null。UTC aware datetime／lock_version／scope／一次性key契約不改；不回填歷史有效期。
- 系統區域GET的失敗／forbidden／unknown僅前端投影，不改後端body／pagination。成員未知不可假0，AuthProvider原准入處理保持。
- Knowledge content_update既有status DTO不改，typed提示投影與單一主呈現，不新增retry／force／state API、不改內容或下游資料。
- 無產品runtime env、依賴、schema／migration；雙語新增安全key按既有i18n，原發布0.2.0資產保持。


## CHG-327 計畫中的優先修復相容性

Gate2已確認六項；Gate4 APPROVED，未改API實作。

- UserSummary additive optional nullable manager_delegate_user_id/start_at/end_at（完整欄位名manager_delegate_start_at/manager_delegate_end_at）；既有PUT省略=保持、明確null=清除語義。舊DTO缺資料不得當空值寫回，後端權限不擴張。
- ApprovalTaskResponse additive optional nullable original_manager_user_id；ORM對應V001/B053已存在SQL欄位，預期無DDL。新任務與approve/reject使用當次snapshot，歷史不改写／不臨時自動重派。
- KnowledgeDetailResponse additive nullable chunk_artifact_error_code、optional chunk_artifact_retry_allowed，原chunk_artifact_status值集合保留。unknown／usage unconfirmed不可重播；新安全warning/error文案，沒有force-replay API。
- existing JSONB artifact metadata新增安全UUID intent／結果狀態與fingerprint；usage UUID PK與status success/failed保持，未知Token/cost仍NULL。獨立usage writer新增共用底層必須保留query wrapper及Chat parent/FK規則。
- 正式FE/BE測試工具與evidence契約改動不改服務API；完整命令／manifest／源碼／80%保護不放寬。0.2.0已發佈source／image／assets保持。

2026-10-12 Peter以「核准 CHG-327 開發計畫（建議）」核准本計畫；Gate 4 APPROVED，六項實作與零付費驗證可開始。

2026-10-12 AUDPRIO-001驗收前置缺口：HTTP Wizard在第一步做URL連線測試、第二步才輸入檔名，但目前共享payload提前要求file_name。只對validate/test-connection增加HTTP測試payload允許空檔名（URL的真HEAD/test fetch不需檔名），其他協定仍按原規則要求檔名；create仍使用原必填schema。這是本項真TLS測試能到達client所必需的修復，不捏造預覽檔名／成功，不新增來源建立模式。

## CHG-325 已實作的通知呈現相容性

狀態：Gate2設計確認，Gate4 PENDING；目前API尚未修改。GETnotifications/POSTread/read-all/POSTresolve與signedcursorenvelope保留；計畫為NotificationResponse增加optional can_resolve_manual與resolution_block_reason，舊client可忽略，新client缺flag採不可手動結案。POSTresolve會在既有scope授權後拒绝未解除critical／managed業務待辦，安全409 notification_business_action_required且不改read/resolved；合法非managed資訊確認保持，resolved timestamp重送冪等。這是既有read≠businessresolved要求的必要修復，不擴權或新增schema。前後端有限同source交付驗舊client409與新copy；published0.2.0契約／資產不覆寫，真businesshistory保持。



2026-10-11 Peter 以「核准 CHG-325 開發計畫」核准 Gate 4；本案開始實作與零模型驗證。原資料、金鑰不讀取、無備份與有限人工測試環境交付範圍保持。先前 PENDING 說明為核准前歷史。


2026-10-11 驗證與交付：CHG-325 已完成本次介面與必要通知守門實作，狹窄驗收通過，人工測試 https://localhost:18443 的四個應用與登入主題已更新。273 契約／原生案例、8 真 Chromium 元件案例、8 真 PG/HTTP 通知案例及真 Worker 消費通過；三寬度中英、Modal保留輸入／單層確認／跨頁 Toast／真5秒與Modal暫停、近期刷新清除已觀察。Model0/key-read0/backup0；原121chunks/12table指紋不變、isolate ledger71→71，63控制通知／2原生事件／2outbox／2失敗控制專案精確撤除，真audit保留。完整FE suite／各80%、complete多角色E2E與每畫面a11y仍 OPEN，不以此 scoped PASS 當全案DoD。詳 docs/CHG-325-IMPLEMENTATION-RESULT.json。

## CHG-315 content-edit contracts（Gate 2 confirmed；Gate 4 APPROVED；未實作）

Peter2026-10-04「全部採A」確認全文Modal入口、切片文字共用入口及same-source下一extraction_revision。SPECIFICATION.md CHG-315技術設計與DEVELOPMENT_PLAN.md為本次待核准方案，以下不是已存在的router／migration。

| Planned canonical method / path | Current status | Planned compatibility behavior |
| --- | --- | --- |
| GET `/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/content-editor` | required-gap | Scoped full canonical／revision／locks／limits／mode與可選exact chunk ranges；readonly不授予write。 |
| POST `/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/content-updates` | required-gap | OIDC／edit與Idempotency-Key；200 no-op／202 queued；後端決定overwrite或同major新修訂，原Active保留。 |
| GET `/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/content-updates/{update_id}` | required-gap | Scoped job／revision／安全status；不回pending全文或Secret，queued不當ready。 |
| POST `/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/content-updates/{update_id}/retry` | required-gap | 最新revision、edit／idempotency守門，retry相同job與未完成步驟，不建立第二版本或重播unknown provider。 |
| PATCH `/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{chunk_id}` | implemented；CHG-315 change planned | 路徑／既有payload與KnowledgeDetail envelope保留；content寫入以可靠exact range轉完整canonical並共用content-update，無對應409 `chunk_content_source_unresolved`。前端文字操作改用全文API；metadata-only／review-history限制及lineage保留，不能獨立寫chunk body。 |

正式scope與錯誤／DTO見SPECIFICATION.md CHG-315；新API不移除既有public integration路由或增加身份header。schema V052規劃additive、原sourcehash與原artifact保留，historical data不回填。未執行API／provider／migration驗收；新actor／工作／scope回讀與相容adapter需隨本案真服務驗證。

## CHG-304 additive repair contracts (candidate, 2026-09-19)

Specification 10.61 / approved repair plan apply. No routes, envelopes, existing
payload fields, PostgreSQL columns or index mappings are removed or renamed.

- Document summaries add nullable `created_by_name`; version summaries add
  nullable `active_chunk_count`, `created_by`, `created_by_name`. Null remains
  unknown, never an invented zero or the requester's identity.
- Knowledge detail adds optional `chat_access` with mode (`staging`, `published`,
  `history_only`, `unavailable`), exact version ID, query_enabled and safe reason.
  This hint is not authorization; query rechecks scope/readiness. Existing
  staging and published conversation identities remain distinct.
- Manual selection retains existing fields; exact Unicode canonical ranges may
  span AST blocks. Invalid/stale/unmapped ranges still fail, never fuzzy-match.
- Multipart request shapes are unchanged. File payload bytes are preserved.
- Unready staging gives 409 `chunk_artifacts_not_ready` before Provider work.
  Partially attempted physical-page OCR rejects blanket retries with 409
  `ocr_partial_retry_requires_review`; no silent full-document replay.
- No existing-row backfill or index rewrite. Results and incomplete acceptance:
  `docs/CHG-304-DEFECT-REPAIR-RESULT.md`.

## CHG-293 additive contract clarification (2026-09-10)

No route, envelope or database column is removed or renamed. Specification 10.50
is authoritative for the following approved authorization changes:

- Project `capabilities` adds default-false `can_archive_project` and
  `can_retry_archive_cleanup`. `can_manage_lifecycle` covers Owner/Editor document
  management, not Project governance. Editors cannot archive even with execute.
- Chat conversation list/detail share reads only within the authorized Project,
  surface and exact staging version. Requester-bound cursors remain enforced.
  Add `created_by_user_id`, `created_by_display_name`, `is_mine`, `can_delete`,
  `can_evaluate`, `can_export`, `read_only_reason`; `can_continue` is actor-aware.
  Missing capability metadata is never interpreted as write permission.
- Query, feedback, delete and export remain creator-only. An unused client UUID
  may create its first turn; a used/deleted/legacy/conflicting UUID is not new.
  Same-identity concurrent writes return retryable 409 `conversation_busy` before
  any Provider work. Foreign visible continuation returns 403
  `conversation_read_only`; existing feedback's non-owner 404 remains unchanged.
- Validation items retain independent identities. Public Integration API, RAG,
  persisted content, roles and schema remain unchanged; no V049 or backfill.

Evidence and limitations: `docs/CHG-293-VERIFICATION.md`. These notes describe
repository code, not deployment or a completed end-to-end release acceptance.

## Canonical route inventory

This inventory implements `API-COMPAT-001` for the canonical API list in
`SPECIFICATION.md` section 12. CHG-247 supersedes the former global graph route
decision: only explicit Project/Document scoped graph routes are canonical, and
the unscoped aliases must be removed. CHG-260 removes the former external
secret-server and upload-scanner deployment behavior; it adds no public API route.

Status meanings:

- `implemented`: the canonical path exists in the current FastAPI router.
- `documented-equivalent`: the behavior exists under a scoped/nested route or
  payload and CHG-216 selected that authorization-preserving route as canonical.
- `required-gap`: required behavior has no complete current route and must be
  implemented in the named governed change.
- `required-removal`: a current route violates the approved security/scope
  contract and must be removed without a weaker alias.
- `deferred`: intentionally outside the current delivery, with explicit owner
  and milestone. Deferred entries do not count as complete.
- `removed`: the former route is no longer registered and returns standard 404
  without an alias or replacement endpoint.

All paths below are relative to the application origin. Internal endpoints use
the `/api/v1` prefix unless the canonical path begins with `/api/public/v1`.

| Canonical path | Current route or evidence | Status | Governed action | Owner / milestone |
|---|---|---|---|---|
| `/api/v1/auth/oidc/config` | `/api/v1/auth/oidc/config` | implemented | Retain; cover runtime identity activation in `OIDC-REAUTH-001`. | Identity / Batch B |
| `/api/v1/auth/me` | `/api/v1/auth/me` | implemented | Retain and regression-test empty-grant users. | Authorization / Batch B |
| `/api/v1/system-initialization/status` | Removed by CHG-231; standard 404 | removed | No runtime state access or replacement endpoint. | CHG-231 / DEPLOY-006 |
| `/api/v1/system-initialization/validate` | Removed by CHG-231; standard 404 | removed | Deployment configuration is validated by Compose/Helm jobs. | CHG-231 / DEPLOY-006 |
| `/api/v1/system-initialization/apply` | Removed by CHG-231; standard 404 | removed | Deployment provisioning uses migration/bootstrap jobs only. | CHG-231 / DEPLOY-006 |
| `/api/v1/system-initialization/unlock/start` | Removed by CHG-231; standard 404 | removed | Identity Settings reauthentication remains a separate contract. | CHG-231 / DEPLOY-006 |
| `/api/v1/system-initialization/unlock/complete` | Removed by CHG-231; standard 404 | removed | No initialization completion/unlock state or cookie remains. | CHG-231 / DEPLOY-006 |
| `/api/v1/system-initialization/lock` | Removed by CHG-231; standard 404 | removed | Legacy initialization tables are never mutated by runtime code. | CHG-231 / DEPLOY-006 |
| `GET /api/v1/projects` | Same path now returns the fixed Backend-computed `PERM-005` capability object per item. | implemented | Retain Backend-authoritative capabilities; clients must not infer missing keys. | Authorization / CHG-247 |
| `GET /api/v1/projects/{project_id}` | Same exact path returns the fixed Backend-computed `PERM-005` capability vocabulary. | implemented | Retain exact Project detail scope and mutation-time reauthorization. | Authorization / CHG-247 |
| `/api/v1/projects/{project_id}/members` | Same path | implemented | Retain. | Projects / regression |
| `/api/v1/projects/{project_id}/members/{user_id}` | Same path | implemented | Retain. | Projects / regression |
| `/api/v1/identity-sync/run` | Same path | implemented | Retain. | Identity / regression |
| `GET /api/v1/identity-sync/runs` | Same path returns a signed stable cursor envelope with status-bound cursor identity. | implemented | Retain the opaque cursor contract. | Identity / CHG-247 `API-PAGE-001` |
| `/api/v1/identity-sync/runs/{run_id}` | Same path | implemented | Retain. | Identity / regression |
| `/api/v1/external-groups` | Same path | implemented | Retain. | Identity / regression |
| `GET /api/v1/external-group-role-mappings` | Same path | implemented | Retain read-only one-to-one mapping inventory under ROLE-002. | Identity / CHG-233 |
| `PUT /api/v1/external-group-role-mappings` | Removed by CHG-233; method is no longer registered | removed | Replace bulk lost-update-prone writes with the role-scoped optimistic mapping contract. | Identity / CHG-233 |
| `PUT /api/v1/roles/{role_id}/external-group-mapping` | Same path | implemented | Canonical map/remap/unmap operation with role `lock_version`, strict LDAP origin, one-to-one uniqueness and immediate derived-membership reconciliation. | Identity / CHG-233 |
| `GET /api/v1/roles` | Same path currently returns every active/inactive row because no role tombstone exists | implemented; CHG-237 contract change planned | Preserve the array body and view permission, return undeleted active/inactive roles in stable order, and exclude tombstones from every normal management selector/count. | Roles / CHG-237 |
| `PUT /api/v1/roles/{role_id}` | Same path currently edits active/inactive role fields and changes `is_active` without lifecycle reconciliation | implemented; CHG-237 contract change planned | Keep name/description edits for active roles. Require standalone edit-permission `is_active` transitions; make disabled roles otherwise read-only, retain LDAP mapping, remove/rebuild current derived members atomically and reject every transition for `system-admin`. | Roles / CHG-237 |
| `DELETE /api/v1/roles/{role_id}?lock_version={n}&confirmation_name={urlencoded_name}` | Same base path currently deactivates the row, releases its mapping and accepts only `lock_version` | breaking semantic correction planned | Change Delete to delete-permission soft delete with both query parameters required and an exact case-sensitive name; tombstone and hide the role, release mapping, remove derived members, preserve history and permit a new UUID to reuse the name. No compatibility alias may keep DELETE-as-disable. | Roles / CHG-237 |
| `/api/v1/projects/{project_id}/owners` | Owner role is represented through project members; no canonical owners route. | documented-equivalent | Decide specification update versus compatibility alias; preserve last-owner rules. | Projects / Batch A inventory decision |
| `/api/v1/projects/{project_id}/owners/{user_id}` | Owner mutation is represented through project-member role mutation. | documented-equivalent | Decide specification update versus compatibility alias. | Projects / Batch A inventory decision |
| `/api/v1/projects/{project_id}/embedding-settings` | Same path; active tested Embedding Model and Owner update guard. | implemented | Retain GET/PUT and audit. | Models / Batch E implemented |
| `/api/v1/system-prompts` | Same path | implemented | Retain list/create. | Prompts / regression |
| `/api/v1/system-prompts/{prompt_id}/versions` | Same path | implemented | Retain GET/POST. | Prompts / regression |
| `/api/v1/system-prompts/{prompt_id}/activate` | Same path | implemented | Retain. | Prompts / regression |
| `/api/v1/system-prompts/{prompt_id}/deactivate` | Same path | implemented | Retain. | Prompts / regression |
| `/api/v1/models/{model_id}/system-prompt` | Same path | implemented | Retain GET/PUT. | Prompts / regression |
| `GET /api/v1/integration-clients` | Same route implements authorized status/project/name/expiry filtering and a signed stable cursor; no plaintext field is present. | implemented | Retain filters/cursor and hash/prefix-only persisted/list responses. | Public API / CHG-247 |
| `POST /api/v1/integration-clients` | Same route returns `201`; plaintext `api_key` appears only in this one-time create response and the Frontend keeps it in modal memory. | implemented | Retain one-time reveal, explicit copy/close and hash-only persistence. | Public API / CHG-247 |
| `/api/v1/integration-clients/{client_id}` | Same path | implemented | Correct DELETE to require delete permission. | Authorization / Batch B |
| `POST /api/v1/integration-clients/{client_id}/keys/rotate` | Same route returns the replacement key once with `200`, persists only its verifier/prefix and immediately replaces the prior verifier. | implemented | Retain one-time response and no retrieval path; live old-key invalidation remains a release acceptance case. | Public API / CHG-247 |
| `/api/v1/integration-clients/{client_id}/activate` | Same path | implemented | Retain. | Public API / regression |
| `/api/v1/integration-clients/{client_id}/deactivate` | Same path | implemented | Retain. | Public API / regression |
| `/api/v1/integration-clients/{client_id}/revoke` | Same path | implemented | Define revoke/edit versus delete permission explicitly. | Authorization / Batch B |
| `/api/v1/integration-clients/{client_id}/project-scopes` | Same path | implemented | Retain. | Public API / regression |
| `/api/v1/integration-clients/{client_id}/usage-summary` | Same path | implemented | Retain with atomic accounting. | Public API / Batch E |
| `GET /api/v1/projects/{project_id}/documents` | Same path returns Backend-computed `PERM-005` capabilities with each authorized item. | implemented | Retain list/upload boundary and mutation-time reauthorization. | Authorization / CHG-247 |
| `GET /api/v1/projects/{project_id}/documents/{document_id}` | Exact Project-scoped Document detail route exists with `PERM-005` capabilities. | implemented | Retain mandatory Project scope; no unscoped alias. | Documents / CHG-247 |
| `GET /api/v1/projects/{project_id}/documents/{document_id}/knowledge` | Same path returns capability, append-only lineage, source mapping and artifact reconciliation evidence. | implemented | Retain the authorized Knowledge Detail contract. | Documents / CHG-247 |
| `POST /api/v1/projects/{project_id}/documents/upload` | Same multipart route returns ordered `200 {request_id,success_count,failed_count,results}` with mandatory request key and per-file transaction/idempotency/compensation. | implemented | Retain `4xx` only for request-level failure and ordered partial results. | Documents / CHG-247 `IMPORT-002` |
| `/api/v1/documents/{document_id}/versions` | Same path with project authorization and pagination. | implemented | Retain. | Documents / Batch E implemented |
| `POST /api/v1/projects/{project_id}/documents/{document_id}/re-extract` | Dedicated same-source command requires `Idempotency-Key`, lock/source fingerprint and atomically creates the revision, Pipeline and outbox result with `201`. | implemented | Retain independent revision identity and unchanged active serving. | Documents / CHG-247 |
| `GET /api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/submission-evidence` | Exact route returns Backend-owned readiness, evidence revision/lock and exact graph/conversation/validation projection. | implemented | Retain exact Project/Document/version scope. | Review / CHG-247 |
| `POST /api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/submit-review` | Scoped route consumes `evidence_revision` + `lock_version`, revalidates under row locks and stores an immutable manifest in the same transaction. | implemented | Retain fail-closed stale-evidence behavior. | Review / CHG-247 |
| `/api/v1/document-versions/{version_id}/publish` | Same path | implemented | Retain. | Review / regression |
| `POST /api/v1/document-versions/{version_id}/switch-active` | Same path requires `Idempotency-Key` and persists/replays one durable command result and terminal effect. | implemented | Retain durable replay and mutation-time authorization. | Review / CHG-247 `IDEMP-001` |
| `/api/v1/documents/{document_id}/status` | Project-scoped `PATCH .../documents/{document_id}/lifecycle` | documented-equivalent | Update canonical contract to lifecycle semantics or add alias. | Documents / Batch A inventory decision |
| `/api/v1/documents/{document_id}/soft-delete` | Project-scoped lifecycle mutation performs soft delete. | documented-equivalent | Document canonical mapping and retain no-hard-delete rule. | Documents / Batch A inventory decision |
| `/api/v1/documents/{document_id}/references` | Project-scoped document-reference list/create routes | documented-equivalent | Document scoped route mapping; add alias only if external clients require it. | References / Batch A inventory decision |
| `/api/v1/document-references` | `/api/v1/projects/{project_id}/document-references` | documented-equivalent | Preserve project scope and update canonical specification. | References / Batch A inventory decision |
| `/api/v1/document-references/{reference_id}/sync` | Same path | implemented | Retain. | References / regression |
| `/api/v1/document-references/{reference_id}/detach` | Same path | implemented | Retain. | References / regression |
| `/api/v1/document-reference-events` | Same path | implemented | Retain. | References / regression |
| `/api/v1/document-reference-events/impacted-projects` | Same path | implemented | Retain. | References / regression |
| `/api/v1/document-reference-events/{event_id}/resolve` | Same path | implemented | Retain. | References / regression |
| `/api/v1/documents/{document_id}/chunks` | `GET /api/v1/projects/{project_id}/documents/{document_id}/knowledge` is the scoped Knowledge/chunk read contract. | documented-equivalent | Keep the exact scoped Knowledge route canonical; do not add a weaker unscoped chunk alias. | Documents / CHG-247 |
| `DELETE /api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{chunk_id}` | Same path; requires `lock_version`, Owner/Editor candidate state and returns updated Knowledge Detail readiness. | implemented | Retain exact nested scope; permanent deletion is the approved CHG-217 exception and must not be flattened into an unscoped alias. | Documents / CHG-217 implemented |
| `PATCH /api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{chunk_id}` | Exact route performs an append-only lineage edit under version lock and queues artifact reconciliation before returning updated Knowledge Detail. | implemented | Retain candidate-only edit and fail-closed reconciliation. | Documents / CHG-247 |
| `/api/v1/chunks/{chunk_id}/tags` | Project/document/version-scoped tag routes | documented-equivalent | Preserve authorization context; document canonical nested contract. | Documents / Batch A inventory decision |
| `/api/v1/import-sources` | `/api/v1/projects/{project_id}/data-sources` | documented-equivalent | Standardize terminology on data sources and update specification. | Data sources / Batch D |
| `/api/v1/import-sources/{source_id}/test` | `/api/v1/projects/{project_id}/data-sources/{data_source_id}/test`; candidate `/test-connection` | documented-equivalent | Project-scoped saved and candidate routes now execute real bounded probes and return fingerprint evidence. | Data sources / Batch D implemented; live acceptance blocked |
| `/api/v1/import-sources/{source_id}/trigger` | `/api/v1/projects/{project_id}/data-sources/{data_source_id}/sync` | documented-equivalent | Update canonical terminology/path mapping. | Data sources / Batch D |
| `GET /api/v1/pipeline-runs` | Same path uses visible-Project filtering plus a signed stable cursor envelope. | implemented | Retain cursor filter binding and deterministic created-at/id order. | Pipeline / CHG-247 `API-PAGE-001` |
| `/api/v1/pipeline-runs/{run_id}` | Nested document/version/pipeline detail route | documented-equivalent | Document nested canonical route or add authorized alias. | Pipeline / Batch C |
| `/api/v1/pipeline-runs/{run_id}/steps` | Steps are included in nested pipeline detail payload. | documented-equivalent | Document payload equivalence; add route only if independent pagination is needed. | Pipeline / Batch C |
| `/api/v1/pipeline-runs/{run_id}/retry-step` | Nested pipeline retry route | documented-equivalent | Align path/action naming while preserving retry limits. | Pipeline / Batch C |
| `/api/v1/approval-requests` | Same path | implemented | Add pagination. | Review / Batch E |
| `/api/v1/approval-requests/{approval_request_id}` | Same path; CHG-310 shared actor/read-only audit scope, safe 403 approval_read_denied | implemented | Retain path/payload; deny unrelated project members. | Review / CHG-310 AUDITFIX-001 |
| `/api/v1/approval-requests/{approval_request_id}/cancel` | Same path; submitter/Owner pending-state cancellation with task/version transition and audit. | implemented | Retain. | Review / Batch E implemented |
| `/api/v1/approvals` | Specialized summary/pending/history/my-submissions routes exist; no base route. | documented-equivalent | Update spec to specialized views or add paginated canonical list. | Review / Batch A inventory decision |
| `/api/v1/approvals/summary` | Same path | implemented | Retain. | Review / regression |
| `GET /api/v1/approvals/my-submissions` | Same path uses submitter scope, server filters and signed stable cursor over immutable evidence metadata. | implemented | Retain submitter-only workspace scope. | Review / CHG-247 `REVIEW-023` |
| `GET /api/v1/approvals/pending` | Same path uses real assignee/stage/priority filters and a signed stable cursor. | implemented | Retain manager assignment and Owner-stage separation. | Review / CHG-247 `REVIEW-023` |
| `GET /api/v1/approvals/history` | Same path implements stable cursor plus project/document/editor/time/priority/source/stage/result filters; `result=rejected` powers the Rejected tab. | implemented | Retain actor scope and immutable evidence metadata. | Review / CHG-247 `REVIEW-023` |
| `/api/v1/approvals/{approval_task_id}` | Same path; CHG-310 shared read scope before evidence resolution; read_only reflects decision authority, document.capabilities.can_publish reflects current Owner authority | implemented | Retain existing fields; audit permission never authorizes decisions or file endpoints. | Review / CHG-310 AUDITFIX-001 |
| `/api/v1/approvals/{approval_task_id}/approve` | Same path | implemented | Retain. | Review / regression |
| `/api/v1/approvals/{approval_task_id}/reject` | Same path | implemented | Retain. | Review / regression |
| `/api/v1/review-records` | Same path with visible-project and document/version filters. | implemented | Retain. | Review / Batch E implemented |
| `GET /api/v1/notifications` | Same path reads durable notification rows with type/severity/read/resolution filters and a signed stable cursor envelope. | implemented | Retain durable outbox, dedupe and terminal resolution behavior; live event-matrix acceptance remains open. | Notifications / CHG-247 |
| `/api/v1/notifications/{notification_id}/read` | Same path | implemented | Retain. | Notifications / regression |
| `/api/v1/notifications/{notification_id}/resolve` | Same path | implemented | Retain. | Notifications / regression |
| `/api/v1/chat` | Project-scoped chat routes exist; no generic route. | documented-equivalent | Keep the CHG-247 exact scoped query/conversation routes below; do not add a generic alias. | Serving / CHG-247 |
| `POST /api/v1/projects/{project_id}/chat/query` | Same route requires `scope_mode`, exact Document version identity and reauthorizes persisted continuation identity. | implemented | Retain fail-closed surface/version locking and live provider/readiness behavior. | Serving / CHG-247 `RAG-019` |
| `GET /api/v1/projects/{project_id}/chat/conversations` | Same route requires scope, requires exact version for Document mode and returns a signed stable cursor envelope. | implemented | Retain actor/surface/version filter binding. | Serving / CHG-247 `RAG-019` |
| `GET /api/v1/projects/{project_id}/chat/conversations/{conversation_id}` | Same route requires matching scope/version identity for Project and exact-version Document conversations. | implemented | Retain not-found behavior for mismatched identity. | Serving / CHG-247 `RAG-019` |
| `DELETE /api/v1/projects/{project_id}/chat/conversations/{conversation_id}` | Same route requires matching scope/version identity and soft-deletes only that actor's matching records. | implemented | Retain audit and cross-surface/version isolation. | Serving / CHG-247 `RAG-019` |
| `GET /api/v1/projects/{project_id}/chat/conversations/{conversation_id}/export.csv` | Exact Backend route authorizes the same identity and streams complete persisted conversation evidence with UTF-8 BOM. | implemented | Retain Backend-owned export; Frontend does not assemble the file. | Serving / CHG-247 `RAG-019` |
| `/api/v1/chat/rag` | Exact replacement is `POST /api/v1/projects/{project_id}/chat/query`. | documented-equivalent | Preserve explicit Project scope; no generic alias is needed. | Serving / CHG-247 |
| `/api/v1/chat-records` | Exact replacements are the scoped conversation list/detail/delete/export routes above. | documented-equivalent | Use those canonical routes and never flatten Project/Document/version histories. | Serving / CHG-247 |
| `/api/public/v1/projects/{project_id}/chat` | Same path | implemented | Atomic Redis rate limiting, durable idempotency and encrypted retention controls implemented. | Public API / Batch E implemented |
| `/api/public/v1/projects/{project_id}/chat/stream` | Same path | implemented | True asynchronous provider-delta SSE implemented; live provider timing waits for operator configuration. | Public API / Batch E implemented |
| `/api/public/v1/chat/responses/{response_id}/feedback` | Same path | implemented | Original client/project/end-user binding and durable idempotency implemented. | Public API / Batch E implemented |
| `/api/v1/validation-questions` | Same path; project-scoped list/create with Editor/Owner mutation guard. | implemented | Retain. | Validation / Batch E implemented |
| `POST /api/v1/projects/{project_id}/chat/validation-runs` | Same scoped route returns `201`, assigns immutable input identity/order/content hashes, persists a hashed execution manifest with exact surface/version/model/prompt/retry settings and exposes only its safe projection. | implemented | Retain additive request compatibility, exact manifest execution and `legacy_manifest_unavailable` classification. | Validation / CHG-247 `RAG-019` |
| `GET /api/v1/validation-runs` | Canonical authorized history inventory uses actor/project scope, filters and a signed stable cursor. | implemented | Retain scoped create and bounded nested compatibility route during client migration. | Validation / CHG-247 `RAG-019` / `API-PAGE-001` |
| `GET /api/v1/validation-runs/{run_id}` | Canonical metadata route derives and reauthorizes Project/surface/version from the run without embedding all items. | implemented | Retain non-disclosing not-found behavior. | Validation / CHG-247 `RAG-019` |
| `GET /api/v1/validation-runs/{run_id}/items` | Canonical item route provides status/category/priority/current-attempt filters, signed stable cursor and persisted answer/citation/judge/attempt/error evidence. | implemented | Retain immutable prior attempts and current-attempt filter. | Validation / CHG-247 `RAG-019` / `API-PAGE-001` |
| `GET /api/v1/validation-runs/{run_id}/export.csv` | Canonical route streams UTF-8 BOM result/evidence CSV in stable input-ordinal/attempt/id order, including immutable input identity, manifest hash, attempt lineage and error codes. | implemented | Live large-run bounded-memory acceptance remains open. | Validation / CHG-247 `RAG-019` |
| `POST /api/v1/validation-runs/{run_id}/cancel` | Same path locks the run, reauthorizes Project/surface/actor, cancels only current pending/running attempts and outbox work, and replays the same terminal result. | implemented | Retain one terminal cancellation result and first-transition audit. | Validation / CHG-247 `RAG-019` |
| `POST /api/v1/validation-runs/{run_id}/retry-failed` | Canonical route reauthorizes the run and creates immutable new attempts only for current eligible failed items. | implemented | Retain successful siblings and prior attempt history. | Validation / CHG-247 `RAG-019` |
| `GET /api/v1/projects/{project_id}/graph?node_limit={10..500}` | Same authorized path/default 120 returns the fixed scoped graph envelope. | implemented | Retain Project authorization before graph read/truncation. | Graph / CHG-247 |
| `GET /api/v1/projects/{project_id}/graph/neighbors?node_id={id}&node_limit={10..200}` | Scoped route exists with default 80 and filters from an already-authorized Project graph. | implemented | Retain safe not-found behavior and both-end omission. | Graph / CHG-247 |
| `GET /api/v1/projects/{project_id}/graph/paths?source_id={id}&target_id={id}&max_depth={1..8}&node_limit={10..500}` | Scoped route exists with defaults depth 4/limit 120 and traverses only the authorized Project graph. | implemented | Retain no cross-scope traversal disclosure. | Graph / CHG-247 |
| `GET /api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/graph` | Exact version-scoped graph evidence route applies Project/Document/version authorization and the fixed graph envelope. | implemented | Retain candidate-version scope. | Graph / CHG-247 |
| Former `/api/v1/knowledge-graph` | No longer registered; standard 404 and no replacement global UI/API. | removed | Never restore an unscoped or administrator bypass alias. | Graph / CHG-247 `GRAPH-008` |
| Former `/api/v1/knowledge-graph/neighbors` | No longer registered; standard 404. | removed | Never restore an unscoped compatibility alias. | Graph / CHG-247 `GRAPH-008` |
| Former `/api/v1/knowledge-graph/paths` | No longer registered; standard 404. | removed | Never restore an unscoped compatibility alias. | Graph / CHG-247 `GRAPH-008` |
| `GET /api/v1/graph-sync-jobs` | Same path returns only authorized operational metadata through a signed stable cursor; it returns no graph content. | implemented | Retain Project filter binding. | Graph / CHG-247 |
| `POST /api/v1/graph-sync-jobs/{job_id}/retry` | Same path requires `Idempotency-Key` and atomically creates a durable retry attempt/outbox for Worker execution. | implemented | Retain asynchronous claimed Worker execution. | Graph / CHG-247 `IDEMP-001` |
| `GET /api/v1/reports/summary` | Same path applies shared topic/scope/field policy and independent ModelReport authorization, then executes stable datastore `COUNT` plus bounded SQL page queries instead of materializing all topic rows. | implemented | Retain topic query-adapter parity and verify plans against live production-scale PostgreSQL. | Reports / CHG-247 `REPORT-014` |
| `GET /api/v1/reports/filter-options` | Same path derives scopes, Projects and optional Integration Client prefixes from the shared `ReportScopePolicy`. | implemented | Retain policy parity; summary/export datastore lifecycle remains open below. | Reports / CHG-247 |
| `GET /api/v1/reports/export.csv` | Same path validates policy/query shape before headers, prefetches one bounded batch, streams remaining rows through a typed PostgreSQL server cursor, enforces statement/wall timeout and disconnect cancellation, and records started/completed/cancelled/failed audit lifecycle with actual row count. | implemented | Retain native partial-download rejection; no background job API exists in v1. | Reports / CHG-247 `REPORT-014` |
| `GET /api/v1/audit-logs` | Canonical System Management-authorized route returns redacted audit metadata through a filter-bound signed stable cursor. | implemented | Retain deny-by-default scope and recursive sensitive-field redaction. | Operations / CHG-247 |

## Additional Backlog Contract

Cron scheduling is represented in data-source configuration. `WEBHOOK-001`
general webhook trigger behavior is explicitly `deferred/non-v1` and has no
current or canonical route. Owner: Integrations. Target milestone: post-v1.0
companion specification. That future specification must define HMAC or other
authentication, timestamp/replay protection, idempotency, supported events and
Project authorization before implementation or API documentation may advertise
the capability.

## Decision Record

CHG-216 Batch E selected project-scoped routes where they preserve
authorization context. CHG-247 strengthens that rule for graph data: a
documented equivalent is acceptable only when the Project/Document identity is
mandatory and Backend-authorized; global graph aliases are forbidden rather
than retained for compatibility. `WEBHOOK-001` remains deferred/non-v1 and does
not count as implemented or accepted.

CHG-260 is a deployment/configuration and ingestion contract, not a NomoSmart
public API addition. Runtime secret references resolve from mounted Kubernetes
or Docker Secrets, and upload routes proceed directly to canonical storage and
extraction without exposing a scanner API or compatibility alias.

CHG-247 rollout is not a blanket same-version deployment. Additive
idempotency/capability/evidence/cursor changes use explicit expand/contract
identities: Backend first supports the secure new contract plus a bounded old
mode, clients switch under compatibility telemetry, and a later contract phase
removes the old mode. Compatible endpoints must continue under mixed replicas,
and one identity cannot emit replica-dependent schemas.

The former `/api/v1/knowledge-graph*` routes are a deliberate security-breaking
removal and never receive a compatibility alias. They use a blue-green
coordinated cutover with the old stack isolated after traffic switches, or a
Backend-first 404 explicitly excluded from compatible-endpoint continuity.
Rollback images that would re-register those routes or bypass mandatory
idempotency/authorization/evidence rules fail preflight; operators roll forward.

## CHG-312 OIDC transient cookie compatibility

Approved by Peter on2026-10-02 with「核准 CHG-312」. Exchange POST `{code,state}`, success DTO, fixed400/401/503 and existing auth paths remain. Per-state `nomosmart_oidc_v2_<SHA256(state)>` replaces shared PKCE/state/nonce/flow/return validation; only the matching flow is expired. Optional internal recovery `flow` digest selects cleanup, never authenticates a caller; final URL remains exact `/login`. Flash notices remain short-lived Browser-wide hints and cannot override a created flow's state or destination.

Legacy inflight callbacks must start fresh, without dual-read; frontend rollout/rollback requires a coordinated version switch or drain. No SQL/dependency/runtime environment change. Bound return hints over512 UTF-8 bytes fall back home. Snapshot admission permits four observed active flow cookies, not an atomic cross-worker cap. Non-sensitive zh/en locale cookie mirrors existing localStorage; legacy preference resolves after first hydration. Actual current-source verification is recorded in the CHG-312 result, without relabeling historical evidence.

## CHG-310 current security compatibility

Approval list/detail/task reads share the relationship SQL policy before pagination/evidence access. Unauthorized existing IDs now return safe403 approval_read_denied; unknown IDs keep404. Protected active system-admin plus effective SystemManagement.view is an active-project read-only audit exception; existing assignee/Owner/lock publish rules remain. Existing document.capabilities adds can_publish to control the Owner publication button independently of decision read_only. All five reference APIs require KnowledgeProjects.view plus current project/active/write relationships. UI403/service errors have safe messages/requestID/retry; no response top-level field, public path, Pydantic schema or SQL migration is retired.

Actual source/API/SQL checks and focused24API/13Browser outcomes: docs/CHG-310-AUTHORIZATION-AND-CLEANUP-RESULT.md/.json. Complete integration/coverage/production acceptance remains blocked.

## CHG-335 test infrastructure contract

No product HTTP API, DDL or permission contract changed. Test:e2e defaults to full and now reports explicit scope/full_acceptance; genuine unavailable prerequisites return exit2/BLOCKED, test/cleanup failure exit1. Authentication scope passes independently of generation and never implies full acceptance. Source-bound v4 browser context adds run/service/DB/application-source bindings, with secrets supplied by anonymous pipes; v3 legacy remains intact. A separately created valid generation journal can be passed via E2E_GOVERNANCE_MANIFEST within the current owned root, plus E2E_GENERATION_RECEIPT; the helper verifies source, canonical revision/hash, exact version artifact URIs, native build/vector checksums and actual service evidence, never adopts old rows. This positive producer/governance path has not been accepted in CHG-335 A.
# CHG-336 測試工具相容性補正（2026-10-14）

產品API method/path/payload、cookie／TTL、JWT/PKCE/nonce與記憶體token、權限及資料schema保持，原frontend/identity部署不修改。正式E2E準備器的CLI預設維持；新owned client登出白名單只精確origin/login，edge轉送實際Upgrade/101及frames並處理真取消/撤除。

新增e2e_dev_login test-only phase與mode（baseline/verify/regression；custom-dev/webpack-dev/cli-dev/production）、anonymous stdin真身份與安全報告。legacy-edge／純觀測只能baseline；scope結果不當全E2E/80%PASS。當次application依賴copy只是隔離compiler root前提，不更改package/lock或原依賴。正式frontend/後端/auth API無遷移需求。


2026-10-25 Gate 4：Peter明確回覆「核准計畫」，核准凍結計畫SHA256=b6c050cde5ab02a00fa9f008cfa8f67de88d1b4ea2108c8ebe3c242dc1d2c807。開始核准範圍實作與隔離驗證；規劃期PENDING與禁止實作文字為歷史，本次實際結果另記，不修改原計畫雜湊或歷史測試結果。


CHG-363 browser session discovery: `GET /auth/session` returns `{authenticated, csrf_token, idle_expires_at, mode}` for the HttpOnly cookie without a profile or activity extension. Client-side token exchange/refresh endpoints return HTTP 410 after upgrade; active clients must reload. The server OIDC callback and LDAP login establish the same server-owned session.

## CHG-389 — 系統設定優化相容契約草案

狀態：待規格審閱，尚未實作；目前生效API保持。完整請求、回應、錯誤、交易與升級條件見[規格SYSUX-006及SYSUX-014至015](docs/CHG-389-SYSTEM-SETTINGS-SPEC.md)。本提案未取得開發計畫核准。

| Contract | Proposed behavior | Compatibility / permission |
| --- | --- | --- |
| /system?section=...&panel=... | 七分類列舉定位；小分類為卡片捲動；沿replace與reload首屏定位 | 九個舊tab持續映射；parameters預設general/time並連往documents；identity認證返回先按原流程消耗，不能把query當解鎖 |
| GET /api/v1/system/parameters | 保留六個現有平面參數、OCR defaults/hash，新增section_revisions、parameter_defaults與逐欄metadata | 原view要求；無secret；缺歷史metadata為null；舊GET呼叫者仍可讀既有欄位 |
| PATCH /api/v1/system/parameters | section=general或documents、expected_revision、非空values；只允許該分類鍵，成功回該分類values/revision/defaults/metadata | session＋CSRF/Origin＋edit；交易內CAS及交叉驗證；409衝突、422非法、428缺版本前提；不以GET合併全量PUT代替 |
| PUT /api/v1/system/parameters | 路徑與原參數欄位保留，提議完整寫入需expected_section_revisions的兩組版本；OCR hash仍保留 | 此為D3待確認的寫入相容改變：不帶版本舊caller回428；前後端需協調升級，不能宣稱完全向後相容 |
| identity / models / prompts / users / roles / integration-clients / operations | 保留既有業務端點、角色語意、scope、Modal生命週期與安全規則 | 分類不授予新權限；identity原子候選流程、API Key一次性顯示、model/role軟刪除及未知結果保護保持 |

D4尚未確認前，不因前端1–1024 MB／1–90天與後端10240 MB／3650天差異，逕自收窄或放寬任一路徑。此草案不增加Web基礎服務秘密管理、資料遷移或實際設定更新。


CHG-389 2026-11-08確認／Gate4核准：採分區PATCH及嚴格PUT版本前提；上傳1–10240MB、TTL1–3650天。upload-config增加deployment_max_upload_size_mb；connection-options增加default_timezone；document version增加可選staging_retention安全狀態。新退回產生期限快照；既存退回不補清理。完整核准companion第9節取代前草案待定文字。

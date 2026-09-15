# CHG-293 實作與驗證紀錄

日期：2026-09-10（Asia/Taipei）。需求：SPECIFICATION.md 10.50，PROJECT-013、
PROJECT-014、CHAT-SHARE-001、CHAT-OWNER-001、CHAT-AUTHOR-001、CHAT-COMPAT-001。

Peter 核准：`Peter approves CHG-293 Project Editor Content Authority And Shared Read-only Chat History`。
狀態：**程式已實作，局部／回歸及限定範圍真實瀏覽器驗收通過；完整 coverage／全流程 E2E／release 尚未通過。**
後續另經核准完成 Backend／Frontend image build、isolated smoke、revision-37 dry-run
與 SBOM；**Frontend image scan 為 4 Critical／8 High，不能進入部署**。
尚未部署、未變更目前環境資料或角色、未呼叫 Provider。詳見
`docs/CHG-293-REVISION37-BUILD-DRYRUN.md`；下方較早「未建置」為當時階段紀錄。

後續已完成另行承接的部署前唯讀相容性盤點：revision 36、11 輪／2 個
document_staging identities 無歧義，user02 canonical Editor＋Menu view 可用；
7 輪屬已刪除文件仍限制存取，4 輪屬未刪除文件。保留舊 Editor+Viewer rows、
V048／未套 V049，兩次限定 metadata/count 一致。完整證據與限制見
`docs/CHG-293-READONLY-INVENTORY.md`；不是新版 live API 或完整 release 驗收。

## 最新補測：Editor 內容 CRUD（2026-09-10）

在原核准的 PROJECT-013／T01..T03 隔離範圍繼續測試，本輪新增 **18** 個案例，
CHG-293 suite 由 30 擴充為 **48 PASS**（7 個純政策組合，41 個真實 DB／OIDC/API
案例）。只使用 internal Docker network 的 PostgreSQL／Keycloak 與唯讀掛載的目前
程式碼，沒有啟動 worker、連外 Provider、Neo4j 或 OpenSearch。

補測找出並修正兩個可重現、會阻擋內容操作的實際缺陷：

1. `Chunk.heading_path` 的 Python None 原本會序列化成 JSON `null`，違反 V046 的
   SQL NULL-or-array CHECK。改成 `JSONB(none_as_null=True)`，保留 None／空陣列／
   非空陣列的既有契約；真實 DB 測試也確認 JSON `null` 仍被 CHECK 拒絕。
2. `documents.edit_chunk` 原本在插入 replacement 前更新舊片的 `superseded_by_id`，
   觸發即時 self-FK。改為同一交易依序 flush 舊片 superseded、插入 replacement、
   再設定 back-pointer；不移除／延後 unique 或 FK，不提前 commit。

兩項修正皆先記錄到 SPECIFICATION 10.50、SPEC_CHANGELOG、開發計畫及 trace。
只有 ORM 綁定及既有 API 的交易內順序變更，**沒有 SQL Migration／回填／新權限**。

| 補測內容 | 真實結果 |
| --- | --- |
| Editor manual create → edit Owner 原片 → delete replacement | 200；正確 edited_by、parent／lineage／revision，舊內容保留並 superseded；原始 Markdown artifact 不變 |
| Retrieval/display | Markdown 粗體保留於 display_markdown，retrieval_text 已正規化；來源 offsets 正確、embedding hash 分離 |
| Outbox | 3 個 pending／attempts=0 的 chunk.artifacts.reconcile，revision 2/3/4；UI response queued、next_stage_allowed=false，未冒稱已完成 embedding/index |
| Document/Chunk tags | Editor 以既有 remove/add 契約替換 Owner 的標籤；真實 assignment author、PostgreSQL staging preview digest／revision／edges 更新；不是 Neo4j 同步驗收 |
| 6 種無權寫入狀態 × 7 條 API | Viewer／範圍外／移除 membership／停用 actor／缺 Menu view 回 403，archived Project 回 409；資料、版本、outbox、chat、usage hashes 不變 |
| 5 種不可編輯版本 × 7 條 API | pending_manager_review、pending_owner_review、approved、active、inactive 均回 409，資料 hashes 不變 |
| SQL NULL／array 與 invalid JSON null | 原欄位約束完整保留；None 更新為真正 SQL NULL，空／非空陣列原樣保存 |
| 真實 DB 寫入失敗回滾 | 僅在隨機隔離 schema 加一個 test-only CHECK，讓 replacement INSERT 真正失敗；正常 Editor PATCH 回滾所有 prior flush，原片仍 active、無 back-pointer、outbox／內容 hashes 不變；finally 移除精確 CHECK |

上述資料為明示已儲存的 candidate Markdown fixture，不是 OCR 成功或 Provider 回覆。
正向 CRUD 前後的 chat／usage、pipeline artifact hashes 均一致；模型數為零。
測試工具另修正每個 scoped_data Session 載入獨立 User ORM instance，避免
expire/rollback 造成後續測試 DetachedInstanceError；未更動正式身分驗證。

未隱藏初輪失敗：先有 heading_path CHECK failure 與 fixture session errors；修正後
曝露 self-FK failure。另修正新測試對既有 scope 403／archive 409 及獨立 lineage UUID
的錯誤預期，未放寬產品 guard。最終 **48 PASS, 1 deprecation warning**。

本輪命令：

```bash
bash backend/scripts/chg293_isolated_tests.sh
env PYTHONPATH=backend backend/.venv/bin/python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider --tb=short -q backend/tests/test_chg247_contract_baseline.py backend/tests/test_chg281_structure_pipeline.py backend/tests/test_chg283_retrieval_only_embedding.py backend/tests/test_chg284_original_chunk_parity.py
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh security:static
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh coverage:check
git diff --check
```

結果：CHG-293 **48 PASS**、4 個相關回歸檔合計 **50 PASS**（含原 12 個契約案例，
不可重複加總）；Frontend **146 contract＋95 component PASS**，但 command 因
原 80% coverage gate **exit 1**（lines 12.72%、statements 11.56%、branches 9.57%、
functions 12.23%）。coverage:check 仍 exit 1，不偽造 passing-suite receipt；其餘
本輪列出的檢查 PASS。security:static High=0，仍有既有 Low=61／Medium=31。
下文 Backend 30-case＋browser coverage 為先前輪次紀錄，**不是這次 48-case／更新後
source fingerprint 的 coverage 證明**；全套 Backend coverage 尚未補齊。

清理已驗證：所有 `chg293_%` test schemas 為 0（包含 test-only rollback CHECK）；
fixture 正常刪除自己的 Keycloak realm。確認 ID/label 後只刪除 PG
`d61e5eaed022…`、Keycloak `382252ee54f2…`、internal network `0c58c18b2a47…`。
以 `nomosmart.change=CHG-293` 篩選 container/network 均零筆。測試資料已丟棄、可由
fixture 重建；目前 MAAS／Kubernetes／roles／indexes 皆未操作。

## 修正結果

1. Editor 的一般文件 lifecycle capability/API 改為一致允許，包含其他成員建立的
   文件。仍保留 lock_version、impact confirmation、啟用所需 Manifest、審核鎖與
   soft-delete；其他匯入／切片／標籤／送審既有 Editor 路徑不擴張成治理權。
2. 專案封存／刪除、impact 與 cleanup retry 對 canonical Editor 明確拒絕，即使有
   execute grant。前端依 Backend 的 archive/retry capabilities 控制，不自行 OR grant。
3. 文件與專案 Chat history 共享授權範圍內的 list/get。保留 Project、surface、精確
   staging version、deleted/legacy 與 requester-bound cursor 邊界。
4. 新增全域 conversation identity 檢查與 PostgreSQL transaction advisory try-lock。
   同 UUID 競爭立即 409 `conversation_busy`；他人續問在 Embedding/LLM 之前 403。
   已刪除、legacy、跨 scope 或多作者 ID 不作為新對話；不猜測修復舊資料。
5. 歷史卡片及氣泡顯示真正建立者姓名，使用 UUID／Backend 能力判斷本人。
   他人為唯讀，不可續問／評價／刪除／匯出；提供「新增自己的對話」。UI/UX skill
   僅用於沿用既有緊湊版型、可及姓名、文字唯讀提示與安全的非同步狀態。
6. 分頁、切換路由／登入者／對話使用 request generation 保護；晚到回應只更新
   原對話，撤銷 scope 時清除內容。批次 item 保持獨立 Backend identity，預覽不
   被誤當為目前互動對話的後續 turns。唯讀提示放在 thread 內，維持原三列布局。
7. 真實頁面驗證發現大量 Document history 會撐高頁面，已補有界、鍵盤可捲動的
   history region；使用自然列高，避免卡片文字互相重疊。本人因 scope 過期不能
   續問時只標「不可續問」，不誤稱仍可匯出／評價的本人紀錄為完全唯讀。
   撤銷存取時同步清除 history cursor／busy，不能留下可操作的舊分頁狀態。

## 修改位置

| 檔案／模組 | 目的 |
| --- | --- |
| backend/app/domain/project_access.py | archive_authority、Editor lifecycle capability 與 Project response projection |
| backend/app/api/routes/projects.py、documents.py | archive guard/capability 與文件 lifecycle 的當下授權；人工編輯 replacement 的同交易寫入順序 |
| backend/app/db/models.py | Chunk.heading_path None → SQL NULL，符合原 V046 nullable-array constraint；不變更 DB schema |
| backend/app/core/contracts.py、api/schemas.py | 新 archive 能力、Chat 作者與 default-false mutation 能力 |
| backend/app/domain/chat_conversations.py | creator/scope/deleted/legacy identity 與 durable try-lock |
| backend/app/api/routes/serving.py | scoped shared list/get、creator-only query/feedback/delete/export、批次姓名 join |
| backend/app/domain/validation_runner.py | validation 寫入前的獨立 identity 檢查 |
| frontend/src/lib/api.ts、chatConversationAccess.ts | 相容 API 欄位、page wrapper、UUID 能力、merge／request generation |
| frontend/src/components/ChatHistoryAuthor.tsx | 真實姓名、缺值、「我」與唯讀提示 |
| frontend/src/components/ProjectChatTest.tsx | 共用歷史、本人操作、晚到回應／batch 狀態隔離 |
| frontend/src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx | 多歷史選取、姓名／唯讀、分頁與固定版本 |
| frontend/src/app/projects/page.tsx、app/globals.css、lib/operationalMessages.ts、i18n/locales/{zh,en}.json | Backend archive capability、局部樣式及雙語錯誤提示 |
| backend/tests/test_chg293_project_content_and_chat_history.py、backend/scripts/chg293_isolated_tests.sh、backend/scripts/chg293_browser_fixture.py | 隔離 DB/OIDC/API/競爭測試、runner 及真實瀏覽器資料 setup/teardown；長時間驗證後重新取得 test-admin token 清理 realm |
| frontend/tests/chg293ChatHistory.component.test.tsx | direct component／state／作者與缺值測試 |
| backend/tests/test_chg247_contract_baseline.py、frontend/tests/{chg241ProjectArchivePermissionUx,chg275ChatCitation,liveApi}.test.mjs | 將既有 assertion 對齊核准的新能力、分頁、穩定刪除與輪數契約；未刪測試 |
| SPECIFICATION.md、SPEC_CHANGELOG.md、DEVELOPMENT_PLAN.md、TEST_PLAN.md、TRACEABILITY.md、API_COMPATIBILITY.md、docs/CHG-293-PLAN.md | 規格／決策／實作／測試可追溯性；既有 ignore 規則不變 |

無資料庫、Index、Embedding 或圖譜 schema 變更；不需 reindex。Backend/Frontend
宜成對部署。舊 frontend 不能作為安全邊界，Backend 始終重驗證；新 frontend 缺少
能力 metadata 時 fail closed。V049、歷史 identity 清理、現有角色變更不在此範圍。

## 驗證

| 命令 | 結果及範圍 |
| --- | --- |
| bash backend/scripts/chg293_isolated_tests.sh | 初輪 26、前輪 30；本輪擴充為 **48 PASS**，不是相加 |
| 隔離 CHG293_DATABASE_URL / CHG293_KEYCLOAK_URL + coverage run -m pytest … backend/tests/test_chg293_project_content_and_chat_history.py（完整命令見下） | 最終 **30 PASS**；含 7 項純政策組合、23 項真實 PostgreSQL 或 PostgreSQL/Keycloak/JWT/API 測試；不使用 Provider 或 dependency override |
| PYTHONPATH=backend backend/.venv/bin/python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider --tb=short -q backend/tests/test_chg247_contract_baseline.py | **12 PASS**；保留的直接契約／靜態回歸 |
| cd frontend && npx vitest run tests/chg293ChatHistory.component.test.tsx | 最終完整 suite 包含 **10 PASS**；純資料變換及實際小元件，不代表整頁瀏覽器操作 |
| ./HARNESS/harness.sh test:frontend | **146 contract + 95 component PASS**，但 **exit 1**：完整 Frontend coverage 低於既有 80% |
| ./HARNESS/harness.sh coverage:check | **exit 1**：缺完整 passing-suite coverage evidence；不以局部結果製作通過憑證 |
| ./HARNESS/harness.sh test:e2e | 通用全流程 harness 仍 **BLOCKED / exit 1**：缺其專用七項 URL／帳號設定；不把後述 CLI 限定驗收冒充此 harness 通過 |
| Playwright CLI：三個隔離帳號正常 OIDC 登入 + 真實 HTTP/API/DB | **限定範圍 PASS**；文件／專案雙模式、權限、作者、分頁、切換、鍵盤及窄螢幕，逐項見下 |
| ./HARNESS/harness.sh backend:syntax | PASS |
| ./HARNESS/harness.sh frontend:lint | PASS |
| ./HARNESS/harness.sh frontend:build | PASS；本機 Next.js 編譯，不是容器映像建置 |
| ./HARNESS/harness.sh i18n:ast | PASS；另 4 項 i18n guard tests PASS |
| ./HARNESS/harness.sh docker:config | PASS；只驗證 safe committed configuration |
| ./HARNESS/harness.sh helm:lint | PASS；無 install/upgrade/dry-run 或 cluster write |
| ./HARNESS/harness.sh deploy:config-policy | PASS |
| ./HARNESS/harness.sh security:static | PASS 高信心／高嚴重度 gate，High 0；全庫仍報 Low 61／Medium 31，不宣稱零風險 |
| ./HARNESS/harness.sh spec:doctor / spec:trace / plan:doctor / plan:approved / test:plan（分別執行） | 全部 PASS；六項需求映射完整，Gate 2／4 均具明確核准 |
| git diff --check | PASS |

Frontend 全範圍 coverage：statements **11.56% (906/7834)**、branches **9.57%
(749/7820)**、functions **12.23% (280/2288)**、lines **12.72% (771/6057)**。
這份 Vitest 報表未合併外部瀏覽器 coverage，不能把手動操作折算成通過率。
Backend `--branch --source=backend/app` 的限定 API suite + 真實瀏覽器請求合併：
statements **33.12% (6489/19590)**、branches **4.07% (211/5182)**，合計
**27.05%**。其中新增 `chat_conversations.py` **72/72 statements、30/30 branches，
100%**。這不是全套 Backend 測試或 passing-suite receipt。80% 門檻、測試
排除設定均未降低。初輪 source-contract assertions 還要求舊 OR-grant、舊 list wrapper
與單一歷史局部計數；已更新為核准契約並保留其餘回歸，不是忽略失敗。

Backend warnings：Starlette 現行 TestClient/httpx 相容性 deprecation 一項；最終
30 項測試通過。初輪 loopback 不可連線，改 internal test network；後續真實瀏覽器
另建僅 publish loopback 的 bridge。未改應用網路或用 fake service 代替。

## 真實瀏覽器驗收（本輪新增）

以實際 FastAPI、Next.js production build、PostgreSQL 17.10、Keycloak 26.0.8
執行；Owner／Editor／Viewer 都走正常 OIDC/PKCE。兩個 Project、兩份 Owner 建立的
文件；各 55 組 Document conversations、3 組 published-surface history，合計
118 筆已儲存 ChatRecord。所有答案明示為 stored test history，不是生成答案。
沒有 active manifest／AI model／外部 index，不聲稱已驗證正向 RAG。

| 驗證 | 結果 |
| --- | --- |
| Editor 內容與治理分離 | list/detail 顯示 Editor，文件 lifecycle 可操作，即使另具 archive execute grant 仍無專案治理／封存控制；Viewer 文件 lifecycle 停用 |
| Editor 操作他人文件 | UI impact → confirm，成功軟刪除第二份 Owner 建立的測試文件；DB is_deleted=true、status=deleted，created_by 仍是 Owner |
| 文件及專案共享歷史 | 三位真實作者皆可見；卡片／訊息顯示建立者，不使用目前登入者冒充；Owner 兩筆問答顯示 2 輪 |
| 他人對話不可延續 | Editor、Owner、Viewer 檢視他人紀錄，composer、Enter、upload、export、evaluation 均不能寫；專案歷史只有本人顯示刪除控制 |
| 本人已失效 scope | 無 active manifest 的本人 Project history 標「不可續問」，本人匯出／評價仍依 Backend 能力可用 |
| 50＋5 分頁 | 55 個唯一 conversation，52 paging cases + 3 actors；末頁沒有下一頁，不丟掉先前卡片 |
| 快速切換與路由隔離 | 真實網路增加 250 ms latency 後連續切換 Owner/Viewer/Editor，最後仍顯示 Editor 紀錄；換第二 Project/version 不混入第一份文件。未攔截／偽造 response |
| 新增自己的對話 | 清除他人訊息、啟用本人草稿，不變更已存歷史；未送出 query |
| 桌面／鍵盤／窄螢幕 | 1440×1000 region 高 480、scrollHeight 6402；390×844 高 320、scrollHeight 5639；55 卡片無文字溢出重疊，keyboard 可到最後一項 |
| 語系 | 實際繁中／英文姓名、「我」、readonly、2 輪及新增自己對話文案；兩份 locale guard 通過 |
| runtime revoke | 精確移除 disposable Viewer membership，下一次載入回 403：history buttons=0、load-more=0、messages=0、composer disabled；預期 403 console error 不是無錯誤宣稱 |

瀏覽器操作前後 `chat_records` count **118**、內容 MD5
**773fd668089a3d21871394d10277d55d** 不變；`ai_model_usage_events=0`、`ai_models=0`。
只有 disposable 文件軟刪除與 Viewer membership revoke/restore/revoke；沒有現有
MAAS、角色、索引或 Provider 操作。Viewer 仍可能看到既有匯入入口，本輪沒有把所有
舊 UI 入口都宣稱已禁用；實際內容寫入仍由 Backend 重驗證。

已檢視的截圖：`output/playwright/chg293-document-readonly-desktop.png`、
`chg293-document-narrow.png`、`chg293-project-own-scope.png`；初輪對照為
`chg293-document-readonly-before.png`。coverage 原始檔與 JSON 同置 output/playwright。
UI/UX skill 促成有界捲動、自然列高及精確不可續問提示，保留 NomoSmart 既有風格。

## 隔離服務與重現

使用既有依賴映像 `nomosmart/backend:0.1.0-chg292`，唯讀掛載目前 source/tests/SQL
及本機 pytest 純 Python 相依，不建新映像。執行空間為新的 internal Docker network
`chg293-test-20260910`；只建立 `chg293-postgres-20260910`（PostgreSQL
17.10-bookworm、tmpfs）與 `chg293-keycloak-20260910`（26.0.8、dev ephemeral）。
兩者皆標記 `nomosmart.change=CHG-293`，測試執行容器 `chg293-test-runner` 用 `--rm`。

每次測試以隨機 `chg293_<uuid>` schema 和隨機 Keycloak realm 隔離；套用 ≤V048
既有遷移，略過 CloudNativePG-specific V042，不套 V049。fixture 結束刪除精確
schema/realm。寫入的 ChatRecords 明確只是 stored-history test data，不冒充模型回答。
網路與容器沒有目前應用資料、Secrets 或 Provider 設定。

重現需先另行建立上述名稱的可丟棄服務（同名存在時應停止，不覆蓋）：

```bash
docker network create --internal --label nomosmart.change=CHG-293 chg293-test-20260910
docker run -d --name chg293-postgres-20260910 --label nomosmart.change=CHG-293 --network chg293-test-20260910 --tmpfs /var/lib/postgresql/data -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=chg293_test postgres:17.10-bookworm
docker run -d --name chg293-keycloak-20260910 --label nomosmart.change=CHG-293 --network chg293-test-20260910 -e KC_BOOTSTRAP_ADMIN_USERNAME=chg293-test -e KC_BOOTSTRAP_ADMIN_PASSWORD=chg293-disposable-only nomosmart/keycloak:26.0.8 start-dev
bash backend/scripts/chg293_isolated_tests.sh
```

以上 test-only 密碼不可套用到應用環境。先確認 DB／OIDC ready 再執行 runner。
交付前已依精確容器 ID 與 `nomosmart.change=CHG-293` 標籤確認，移除上述兩個
測試容器及空的測試 network；最後同標籤 container/network 查詢皆為零筆。
臨時 DB／realm 資料已丟棄，可從測試重新建立；沒有刪除應用容器、PVC 或既有資料。

### 後續 loopback 瀏覽器重現

使用另建的 `chg293-e2e-loopback-20260910` bridge、
`nomosmart.change=CHG-293-e2e` 標籤，只 publish PostgreSQL
`127.0.0.1:15493:5432`、Keycloak `127.0.0.1:18093:8080`。
PostgreSQL 用 tmpfs 與 test-only trust；Keycloak hostname 設為
`http://127.0.0.1:18093`。沿用前述既有映像，不 build、不掛應用 volumes。
DB 名稱為 `chg293_test`（browser）及 `chg293_api_test`（parallel pytest）；
分開 DB 避免 pgcrypto extension/search_path 在並行 schema migration 間互相干擾。
同名容器／連接埠已占用時停止，不覆蓋或重用不明服務。

從沒有 `.env` 的 `/private/tmp` 執行，以下是實際使用的 API suite 命令：

```bash
env PYTHONPATH=/Users/peter/Documents/GitHub/Nomosmart/backend \
  CHG293_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:15493/chg293_api_test \
  CHG293_KEYCLOAK_URL=http://127.0.0.1:18093 \
  CHG293_KEYCLOAK_ADMIN=chg293-test CHG293_KEYCLOAK_PASSWORD=chg293-disposable-only \
  /Users/peter/Documents/GitHub/Nomosmart/backend/.venv/bin/python -m coverage run --branch \
  --source=/Users/peter/Documents/GitHub/Nomosmart/backend/app \
  --data-file=/Users/peter/Documents/GitHub/Nomosmart/output/playwright/chg293-api.coverage \
  -m pytest -c /dev/null --rootdir=/Users/peter/Documents/GitHub/Nomosmart \
  -p no:cacheprovider --tb=short -q \
  /Users/peter/Documents/GitHub/Nomosmart/backend/tests/test_chg293_project_content_and_chat_history.py
```

Browser setup 使用相同 env，但 DB 改 `chg293_test`、coverage file 改
`chg293-backend.coverage`，將 `-m pytest ...` 換成
`/Users/peter/Documents/GitHub/Nomosmart/backend/scripts/chg293_browser_fixture.py`。
其 stdout `ready` 提供本次隨機 issuer／IDs，HTTP bind `127.0.0.1:18094`；
不使用 auth override，不暴露 Provider keys。瀏覽器帳號 owner/editor/viewer、密碼
`chg293-browser-disposable-only` 僅存在這個可丟棄 realm。

`frontend` 先跑 `npm run build`，再以 `node_modules/.bin/next start
--hostname 127.0.0.1 --port 13093` 啟動，明確設定：

```text
FRONTEND_APP_ORIGIN=http://127.0.0.1:13093
FRONTEND_PUBLIC_API_BASE_URL=/api/backend
BACKEND_INTERNAL_API_BASE_URL=http://127.0.0.1:18094/api/v1
FRONTEND_OIDC_ISSUER_URL=<本次 ready.issuer>
FRONTEND_OIDC_INTERNAL_ISSUER_URL=<本次 ready.issuer>
FRONTEND_OIDC_CLIENT_ID=chg293-test
FRONTEND_OIDC_AUDIENCE=chg293-test
```

CLI wrapper 為 `/Users/peter/.codex/skills/playwright/scripts/playwright_cli.sh`；
三個獨立 session `chg293-e2e`、`chg293-owner`、`chg293-viewer`，由正常登入頁操作。
snapshot 後操作實際 refs；run-code 僅做真實 DOM/幾何 assertion、連續選取及 CDP
latency，沒有 route mocking。結束時只 close 這三個 session。

本輪曾有 setup/teardown 問題，均不隱藏：並行使用 browser DB 跑 pytest 導致
19 項 setup errors（pgcrypto search_path），改獨立 API DB 後最終 30 PASS；browser
fixture 初期 SQLAlchemy session ownership/name 初始化已修正。長時間 browser
驗證後 test-admin token 過期，使最初 teardown 回 401；DB schema 已由 ExitStack
清除，精確 realm 以 fresh test-admin login 刪除並確認 404。fixture 現在於 teardown
重新取得 token，最終 30 項測試包含正常清理，未延長 token TTL 或放寬身分驗證。

交付清理：確認 browser schema 數為 0、realm 404；關閉三個 browser session、
本機 13093/18094 listeners。經 ID/標籤核對後只移除 PG
`5757e71d69d4…`、Keycloak `01c090b89b9e…`、空 bridge `312bf04ca25c…`
與初建但未使用的空 internal network `f8b446482a50…`。
`docker ps -a`／`docker network ls` 以 `nomosmart.change=CHG-293-e2e`
篩選均零筆。臨時測試資料已丟棄，可重建；現有應用資源未刪除。

## 尚未完成／下一個門檻

- T01..T03 已補切片 create/edit/delete、標籤 replace、DB/outbox/projection 及鎖／拒絕
  矩陣；完整匯入／OCR、非空切片 artifact reconciliation、送審／發布回歸仍需隔離
  storage/index/worker／Provider。不能把 pending outbox 當成功向量重建。
- T13/T14/T16 的上述限定雙模式頁面、切換／鍵盤／窄螢幕及 revoke 驗收已完成；
  通用全流程 E2E harness 仍未通過，正向 Provider/batch/active-manifest 回歸不在
  此次無 Provider 的 stored-history 驗證內。
- 完整 Backend/Frontend 80% coverage、依賴／映像掃描及 release evidence 仍待補。
  本次只跑 static security gate，未建立新映像或執行其漏洞掃描。
- 正向 Provider 生成（新對話／續問／批次）沒有授權，未執行。授權前拒絕測試及
  真實 identity policy 通過，並不等於已測到 LLM 生成品質或成功帳務寫入。
- 部署前需另行唯讀盤點既有 conversation UUID/creator/scope 衝突、Editor+execute
  及現有角色重疊。遇歧義停止，不重寫歷史，不將 V049 混入本次。

負責人：CHG-293 implementation owner 與 Peter 確認後安排的隔離驗證／release 工作。
下一步補齊全流程隔離服務／coverage 缺口，再另行核准 Backend+Frontend 映像與部署範圍。

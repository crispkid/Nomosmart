# CHG-293 — Editor 內容權限與共享唯讀對話紀錄

日期：2026-09-10。Gate 2：Peter 回覆 `OK` 確認範圍。
**Gate 4 已由 Peter 於 2026-09-10 核准**；repository 實作及局部驗證已記錄，
限定雙模式真實瀏覽器驗收通過；完整 coverage／全流程 E2E／release 尚未通過，見 `docs/CHG-293-VERIFICATION.md`。

完整規格：`SPECIFICATION.md` 10.50；完整開發計畫：`DEVELOPMENT_PLAN.md`
CHG-293；測試：`TEST_PLAN.md` T01..T16；六項需求映射：`TRACEABILITY.md`。
五份既有治理檔受 repository ignore 規則排除，本文件提供可追蹤的審閱摘要，
不修改 ignore 設定或代替完整規格。

## 已確認的範圍

| 項目 | 預期結果 |
| --- | --- |
| Editor 內容管理 | 可新增／修改／刪除允許編輯的專案文件、切片與標籤，包含其他成員建立的內容；文件啟停／刪除 capability 與 API 一致。 |
| Editor 治理限制 | 不可管理專案設定／模型配置、成員／權限、整個專案刪除／封存或 Owner 正式發布；版本／審核鎖不變。 |
| 獨立封存權限 | 即使 Editor 另有 `ProjectArchive.execute`，仍拒絕該專案 archive-impact、封存與失敗清理重試；不修改其角色或其他專案授權。 |
| 共用對話讀取 | 文件與專案兩種測試均顯示各使用者的歷史；仍隔離 Project、staging/published surface 與文件精確版本。 |
| 本人修改 | 他人對話可看但不可續問、改評價或刪除；下載仍保持既有本人限制，執行批次測試須先建立自己的對話。 |
| 真實作者 | 卡片與訊息顯示 `users.display_name`，同名以 UUID 辨識；他人標示唯讀，姓名不可用則誠實顯示缺值。 |

## 根因與修正方向

- `project_access.project_capabilities` 把一般文件 lifecycle 設為 `is_owner`，
  `documents.update_document_lifecycle` 同樣僅限 Owner。改以共用 Editor content
  policy 產生能力與 API 判斷，不新增本地角色權限或 user02 特例。
- `projects._require_project_archive_authority` 及 Projects 卡片僅採 Owner OR
  execute；加入 canonical Editor explicit deny，前端改讀 Backend archive 能力。
- `serving` 的 history list/get 只篩本人；read selector 與 mutation selector 分開。
  建立者資料以授權後批次 User join 取得，不輸出完整身分資料。
- 續問目前查不到本人紀錄便放行，無法保護別人的既有 conversation ID。需在
  Embedding／LLM／usage 前檢查真實 creator 與 scope，並以 PostgreSQL transaction
  lock 序列化相同 UUID 的首筆建立；不能只加 UI disabled。
- Document Chat 目前只取第一筆歷史並畫一張卡，Project Chat 也丟棄 `can_continue`。
  兩端需保留多筆歷史、作者與能力，隔離切換中的 draft、loading、feedback 與延遲回應。

## 工作順序與資料影響

取得 Gate 4 後：先建立精確的權限／身份失敗案例，再修 Backend policy 與 API，
接著修兩種前端歷史與作者呈現，最後執行真實隔離服務／瀏覽器驗證與回歸。

預期只需 Backend／Frontend 邏輯、相容 response 欄位與 zh/en 字串。
重用現有 ChatRecord.created_by、User、membership、交易鎖；**不預設新增 migration**。
不套用待另行核准的 V049、不更改角色／成員、不回填作者、不改對話內容或圖譜／索引。
若有舊 UUID 跨作者或 scope 衝突，需另行盤點與核准處理，不自動猜測歸屬。

## 驗證與風險

- T01..T05：真實 Editor CRUD、Viewer／失效身分拒絕、審核與 Owner 保護、
  Editor+execute 封存拒絕與其他有效授權回歸。
- T06..T12：共享讀取與作者、scope/cursor、創建者專屬寫入、同 UUID 競爭、
  legacy／deleted／同名作者與零副作用。
- T13..T16：兩種 UI 多歷史、唯讀／新增自己的對話、非同步切換、作者顯示、
  長姓名、鍵盤、窄螢幕、zh/en 與相容回歸。
- 使用真正隔離 PostgreSQL／OIDC 及被測路徑所需服務；不以 fake Provider 或
  fixture adapter 冒充通過。全程不授權 Provider 呼叫；完整生成案例必要時回報 blocked。
- Frontend／Backend 各自 80% 完整 coverage 門檻保留。局部測試通過不等於完整 release。

影響需明確接受：共享歷史會讓目前具範圍的成員看到原先僅作者可見的測試對話；
不擴及其他專案、版本、公開 API 或身分 profile。Editor 的 execute grant 在該專案
被 explicit deny，但 grant 本身不被刪除。發布與 Provider 品質升級不是此次範圍。

## 已核准（2026-09-10，Peter）

`Peter approves CHG-293 Project Editor Content Authority And Shared Read-only Chat History`

這只核准 repository 實作與隔離驗證。映像建置、deployment dry-run、Helm/Kubernetes
部署、目前資料／權限變更、文件送審／發布與 Provider 均需另行核准。

## Gate 3 靜態檢查

2026-09-10：`spec:doctor`、`spec:trace`（六項需求）、`plan:doctor`、`test:plan`
及 `git diff --check` 均 PASS。`plan:approved` 依預期 exit 1，明確指出 CHG-293
Gate 4 pending；不能把本次 `OK` 記為尚未呈交之開發計畫的核准。
上述只有靜態治理檢查，不代表功能測試、coverage 或部署驗收。

## Gate 5 更新

後續 Peter 以「下一步」承接已提出的部署前唯讀 inventory 範圍；已完成 revision 36
對話身份／scope、建立者及 Editor grant 相容性盤點，無 identity 衝突或資料修復需要。
保留已刪除文件的歷史存取限制與舊 Editor+Viewer rows，不套 V049。範圍、證據及尚待
核准的 image build/dry-run preparation 見 `docs/CHG-293-READONLY-INVENTORY.md`。
這不是映像／部署核准或全 coverage／release 豁免。

下一輪 Peter 已針對明確提出的 Backend／Frontend build + revision-37 dry-run
回覆「核准」。Stage A 的執行／驗證邊界與結果見
`docs/CHG-293-REVISION37-BUILD-DRYRUN.md`；未核准 Stage B 實際部署或資料寫入。

Stage A 已完成 build／smoke／兩次 dry-run／SBOM，但 Frontend security scan 失敗
（4 Critical、8 High），不能將 Stage A 全部標為 PASS，也不進入部署。詳細產物及
風險見同份報告；依賴修補、risk exception、完整 release 缺口均未擅自處理／豁免。

最新 T01..T03 補測：48 項隔離政策／DB/OIDC/API 測試與 50 項相關回歸通過。
補正 heading_path 空值寫入及人工編輯 replacement 外鍵順序兩項實際缺陷；保持
V046、unique/FK、原始 Markdown、交易回滾與工作佇列狀態。切片／標籤正向 CRUD
及拒絕／鎖定矩陣已驗證；未執行 worker、Provider、向量／外部圖譜重建或部署。
以下 30 項結果為前輪紀錄，完整 coverage／全流程門檻仍未通過。

真實瀏覽器後續修正（CHAT-AUTHOR-001 範圍內）：多筆 Document history 改為可及的
有界內部捲動；本人 scope 不能續問時只標「不可續問」，避免與仍可用的本人匯出／
評價／刪除矛盾。沿用既有版型與能力，不新增授權、資料或部署行為。補元件測試及
真實 50＋5 分頁、鍵盤、桌面／窄螢幕驗證。

30 項政策／真實 PostgreSQL/OIDC 測試與 12 項 Backend 契約回歸通過；Frontend 146 項
contract、95 項 component（含 CHG-293 十項）通過。真實雙模式 browser 已驗證三位
使用者姓名／唯讀、50＋5 分頁、快速切換、窄螢幕、權限撤銷及 Editor 軟刪除他人文件。
全庫 Frontend／Backend 限定套件的 coverage 仍低於 80%，通用 E2E harness 未通過；
局部通過不能代替完整 DoD。未建置映像或部署，沒有修改現有
應用資料、角色、圖譜／索引，也沒有呼叫 Provider。逐項證據與限制見驗證紀錄。

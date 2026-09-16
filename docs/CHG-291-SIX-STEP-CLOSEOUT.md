# CHG-291 六項部署收尾進度

## 2026-09-13 最新覆蓋狀態：已部署，驗收部分完成

Peter後續「核准」已批准CHG-300精確scope，實際V049→應用部署完成，
Helm revision37 deployed。第1項PASS、第2項FAIL與第3項NOT CLOSED不變；
第4項APPROVED/EXECUTED、第5項DEPLOYED，第6項PARTIAL：外部HTTPS、OIDC、
四應用健康與業務/索引保護通過；Backend直連Frontend受既有NetworkPolicy
阻擋，逐Secret resourceVersion前後證據不完整，登入後UI未驗。
沒有透過降低安全或修改失敗紀錄宣告全過。詳見
[CHG-300部署報告](CHG-300-REVISION37-DEPLOY-RESULT.md)。
以下表格/段落保留歷史，不代表目前仍未部署或需要重複核准。

## 2026-09-13 歷史：精確方案待核准時

Peter要求直接V049＋應用部署後，以最新「接受」确认無合格備份、全套測試/
coverage缺口、新image未掃描風險及短暫停寫；僅本次Docker Desktop例外。
第2項仍FAIL、第3項仍NOT CLOSED，不能改成PASS；不再讓相同風險重複待核准。
第4項Gate3已完成：CHG-300-REVISION37-DEPLOY-SCOPE.md，兩次dry-run/hash
及image/source綁定PASS。唯一待Gate4是新migration先建、完整Helm接管策略。
第5、6項NOT RUN。以下保留原歷史進度，不表示最新風險接受尚未收到。

2026-09-13，Peter 要求「一次性依序完成這6項工作」。固定追蹤以下六項，
不另增功能、不掃描、不把局部通過當成整體發布資格。此文件是進度帳，
不是未界定操作的空白授權。R1 書面計畫作為第 1 項已獲此執行指示核准。

| 順序 | 工作 | 目前狀態 / 完成條件 |
| --- | --- | --- |
| 1 | 備份工具資格驗證 | PASS：R7原254PASS與三種whole coverage>=80%證據有效；另經Peter核准，真正現行readonly qualifier exit0/PASS，revision36/V048/PG18.4/protected baselines一致。已建立並獨立重驗qualified.json；沒有把合成演練當現行備份 |
| 2 | 現行備份與隔離還原 | FAIL/未完成；Peter後續Ok核准一次新備份，fresh binding PASS，新62表/1341列archive匯出後，隔離還原member_comments_state_differs於precheck失敗，具體類別未留存、根因待查。新partial保留、claim已用；精確清理及現行基線PASS，不重試/重播或升格為可用備份 |
| 3 | 剩餘測試與完整驗收缺口 | NOT CLOSED；兩項未結案測試問題、三項模型正向測試、全套 setup/prerequisites 與雙端完整 coverage；禁止假 PASS/放寬門檻 |
| 4 | 完整部署方案/精確範圍 | NOT READY；fresh protected baseline、writers/維護窗口、候選來源與 images、dry-run/hash、bootstrap 寫入與回退；新必要權限集中說明 |
| 5 | V049 後更新 Backend/Frontend/Migration | NOT RUN；必須依第 4 項核准的精確執行方案與第 1–3 項證據；不任意挑一套 live mutation 機制 |
| 6 | 部署後驗收 | NOT RUN；資料/基線保留、health/內部連線/HTTPS/OIDC/角色/主要功能，寫資料或模型驗收須在已界定範圍 |

原規格、R1/A–E/整合發布計畫仍約束實作、測試、資料、額度、備份保管和
外部呼叫。已完成且同源的 image/SQL/角色證據沿用；改源才重跑受影響證據。
已有一份未通過還原比對的私有partial；沒有可用備份、V049、deployment PASS。
原失敗保護界線仍有效；3–6尚未完成。R2診斷範圍已完成，詳見
docs/CHG-291-V049-R2-DIAGNOSTIC-RESULT.md。真實差異沒有支持合成案例的
plpgsql推測；COMMENT物件差異與extension owner語意仍需精確分析。
不能重播已消耗的單次重驗、重新匯出、把完整比對改鬆或直接部署。

2026-09-13 R3：Peter核准連續完成準備、部署前再確認（Gate4 approved）。
已完成逐物件SchemaEvidence、same-snapshot sidecar、篡改／替換防護與真實隔離
測試；沒有重複停在已核准的規劃gate。T15定位43個owner／41個ACL差異，
這是合成案例，不是R2真實archive根因證明；不重跑已消耗的真實archive。
結果見 docs/CHG-291-V049-R3-RESULT.md，私有run x3yKqn0T，清理與原Docker基線PASS。

R3結案時需要的新範圍是隔離還原的初始化／extension身分保留策略；R3原計畫
明確禁止改restore owner／ACL策略或新增還原SUPERUSER。尚不能安全進入第5項
請求實際部署，亦未藉「連續執行」跳過資料／權限界線或把2–4項當成完成。

2026-09-13 Peter以`Ok`確認只在隔離環境修正還原策略（R4 Gate2）。
具體single-bootstrap／bounded plpgsql初始化方案已寫入
docs/CHG-291-V049-R4-PLAN.md（Gate3），Peter後續以`Ok`核准Gate4。
已實作新合成profile／single-bootstrap／RESTRICT-only初始化策略；原T15與
41項窄測試PASS；最終全套133PASS、同源真實報告補驗後三種whole coverage
均達80%，原T15的owner/ACL/raw schema/catalog真正一致。
結果與限制見R4-RESULT/EVIDENCE；沒有current-source資格檢查或qualified.json。
現行系統及歷史證據不動，
不以合成成功宣稱第2–4項已完成或第5項可執行。

2026-09-13 Peter後續`Ok`核准「現行環境唯讀備份相容性盤點；不匯出／
不改資料／不部署」。盤點完成：revision36／PG18.4／V048及必要基線穩定，
image、extension version/schema/member inventory吻合R4；但pgcrypto套件屬於
非superuser DB owner，37個內部函式屬於PG管理帳號，是合法trusted mixed-owner
模式，R4目前明確不支援。這是新的實際相容性缺口，不藉改現行owner消除。
詳見CHG-291-V049-CURRENT-COMPATIBILITY-INVENTORY.md及EVIDENCE.json。
本輪沒有新備份、R2重播、qualification、V049或部署；下一個實作範圍須討論
如何在隔離還原忠實保留A/B身分，不降低完整比對。

2026-09-13最新`Ok`確認上述混合owner修正範圍（R5 Gate2）。具體
v2 profile／唯一bootstrap B／受限installer A／target-only pgcrypto預建
計畫已寫入docs/CHG-291-V049-R5-PLAN.md（Gate3），Gate4仍pending。
本輪僅規劃、不改Python、不建立容器、不讀現行服務；R5成功亦不代表
第2–4項或實際部署已完成。原R2 claim及失敗archive仍不讀、不重播、不改寫。

以上為R5規劃輪歷史狀態。Peter後續`Ok`已核准並執行隔離實作/回歸：
166PASS/2FAIL、三種whole coverage達80%。一般A/B與原133案例PASS，兩個
member自訂註解案例FAIL；cleanup/基線PASS，現行不動。依禁止自動COMMENT
界線停止策略擴張，待討論獨立註解保存/還原；不宣告第1項或部署完成。

2026-09-13 Peter以`好`確認新增獨立註解保存/隔離還原範圍（R6 Gate2）。
具體計畫已寫入docs/CHG-291-V049-R6-PLAN.md（Gate3），Gate4待核准。
計畫為同snapshot私有正文證據、固定member typed identity及完整archive後
受限COMMENT transaction，再以原六類/raw/catalog驗證；不刪除原兩個FAIL。
本輪僅文件/規劃檢查，不改Python或操作環境。R5證據與第2–6項狀態不變。

以上為R6 Gate3規劃輪歷史狀態。Peter後續`Ok`核准具體計畫（Gate4），
現已完成隔離實作/真實全套驗證：212PASS，0FAIL/ERROR/SKIP，1 human-GPG
deselected；三種whole-tool coverage皆超過82%。原兩個R5 comment場景保留，
接顯式R6模式後六類/raw/catalog完整相等；舊模式仍拒絕。中途安裝/COMMENT
取消、SQL/statement/lock timeout撤回與不可重用均有真實證據；精確清理、
final Docker baseline及獨立audit通過，零owned PG。R6-RESULT/EVIDENCE記錄
所有輪次，沒有覆寫R5或早期FAIL。

R6沒有授權或實作LiveSource/現行qualification入口整合；不能把合成成功
當成現行可用備份。下一步需界定並核准這項整合與新備份/還原範圍，仍不能
讀/重播R2 archive、使用消耗過的claim、宣告第3–6項完成或直接部署。

2026-09-13最新`Ok`確認R7「整合備份入口，先不讀取現行資料、不部署」
理解（Gate2）。具體來源/新版綁定/共用還原/CLI及T48..T53已寫入
docs/CHG-291-V049-R7-PLAN.md（Gate3），Gate4 PENDING。
本輪只規劃，Python及R6歷史結果不變。核准後連續完成有界整合及真實
隔離驗證；新現行唯讀資格/新一次backup與第2–6項仍不在本輪執行範圍。

以上R7 Gate3為歷史規劃狀態。Peter後續「核准」同意Gate4，已完成工具
入口整合及全套254PASS（原212/新42）。pytest-only與真正CLI+pytest的
三種whole-tool coverage皆>=80%；5個新入口完整還原、取消/rollback/
consumed target、獨立audit及真正CLI SIGINT後自動清理均PASS，零owned PG。
首次full run的createdb/清理未抵達連鎖失敗保留；只修新fixture逐項精確
清理，沒有放大容量或略過guard。詳見R7-RESULT/EVIDENCE。

目前有同源SYNTHETIC_PASS_NOT_QUALIFIED，沒有現行qualified.json。下一個
權限界線是新版現行唯讀資格檢查；未授權自動匯出、R2重播、V049或部署。

以上為R7隔離結案時狀態。Peter接著以「同意」核准提出的現行唯讀資格
檢查，2026-09-13 19:54完成：真正CLI exit0/PASS，revision36、V048、PG18.4、
7組PVC/PV及37個受保護資源/Secret metadata前後一致，A/B/member相容。
已建立qualified.json並獨立重驗來源/claim/報告/custody；原254PASS報告未變。
詳見R7-READONLY-QUALIFICATION/READONLY-EVIDENCE。第1項完成；第2項新備份
仍未開始，其餘不升格。沒有新export/source-binding/restore/Job/Provider/V049/
部署，未讀歷史R2archive；下一個授權範圍為新一次不加密備份與隔離還原。

Peter隨後`Ok`核准上述第2項，已執行一次：prepare-source PASS，完整新
archive 1,213,458bytes/來源62表1,341列，還原precheck回報
member_comments_state_differs，CLI exit1。完整六類比對未完成，差異類別
未保存，不能假設是註解或沿用R2根因。新run
`run-20260913T120543Z-da508f9c7bd2591a`的partial/sidecar/FAIL全部保留。
精確tmpfs容器已清除、零owned PG、Docker及現行readonly基線PASS，仍是
revision36/V048、V049=0。詳見R7-CURRENT-BACKUP-RESULT/EVIDENCE。
第2項未合格，3–6不變；不重設claim、不重試匯出/還原、不直接部署。

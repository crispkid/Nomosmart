# CHG-291 R7 Backup Entry Integration

2026-09-13。Peter以最新`Ok`確認R6結案後的下一步：「整合備份入口，先不
讀取現行資料，也不部署」（Gate 2 confirmed）。本文件是確認後新寫的
Gate 3計畫。**Gate 4 approval: APPROVED**。Peter於2026-09-13以後續「核准」
回答此書面計畫的核准問題，授權有界整合與隔離驗證；現行資料及部署仍排除。
文末規劃輪紀錄保留為歷史事實，不代表執行結果。

## 1. 目的與目前缺口

R6已完成212項隔離測試，原R5兩個註解案例修復，三種whole-tool coverage
均超過82%，真正的取消/rollback/精確清理亦通過。保留
[R6結果](CHG-291-V049-R6-RESULT.md)與原始報告；這不是現行備份資格。

目前程式有三個尚未接通的地方：

1. `live_backup()`仍呼叫舊`export_database()`及`restore_isolated()`預設模式，
   不會保存/使用R5身分及R6套件內部註解證據，不能直接執行後期待成功。
2. `self_test_plain()`完成合成測試後仍呼叫必須存在現行唯讀證據的
   `qualification_reports()`；而R6新增測試的私有目錄限制也尚未接入此CLI。
   合成測試成功應回報「隔離通過、尚未具現行資格」，不是假完整PASS或
   因未執行本來就未授權的現行檢查而混淆成測試失敗。
3. `finish_backup()`目前只強制驗證schema sidecar，沒有專供新版入口的
   source provenance、profile、member comments、一次性匯出claim及postflight
   證據鏈。不能只增加兩個boolean就把synthetic限制解除。

需求：`SPECIFICATION.md` §10.57 `V49-U012`，承接U001..U011。不改應用API、
schema、SQL migration、產品權限或其他功能。

## 2. 整合設計

### 2.1 共用核心，分開來源與資格

只在原備份工具內整理有界核心，不新增任意遠端備份框架。引入明確的
`BackupSourceEvidence`及固定來源adapter（名稱可按既有風格微調）：

- `owned-postgresql-rehearsal-v1`：必須是本run實際建立的`MemoryPostgres`，
  exact container/image/receipt/database/run經驗證；資料為本run新建合成資料。
- `docker-desktop-live-v1`：保留唯一`LiveSource`的context/namespace/release/
  Pod/container/database限制；只能在完整現行資格、fresh source binding與
  一次性export claim驗證後取得。此分支本輪寫入整合邏輯，**不得實際執行**。

共用核心接受已驗證來源物件，不接受任意URL、command callback、SQL、
外部source-kind字串或使用者提供的JSON冒充已驗證來源。磁碟證據的hash只是
綁定，不是獨立授權；每個入口仍要核對來源、custody、freshness與原claim。
隔離測試不得將LiveSource換成fake/mock後宣稱現行分支PASS。

新增入口用versioned profile v3及member-comments v2 envelope，明確區分兩種
source-kind；保存source evidence/binding/claim摘要、snapshot/archive/
完整catalog/image/tool/test SHA及export-time inode/內容綁定。語意收集、
typed identity、上限、R5 A/B判斷、target preparation及R6 COMMENT核心共用，
不得複製一套較鬆的實作。v3僅支援已驗證的PG18.4固定A/B模式及41個members，
未知或改成uniform等其他模式先拒絕，不自動猜測替代策略。

R4 v1、R5 v2、R6 comment v1與其synthetic-only限制/負向測試仍保留；新入口
不回填或自動升級舊sidecar/R2 archive。新format不接受舊format冒充。R6私有
測試根目錄前綴可繼續用於原測試：新self-test runner明確建立其接受的
`/private/tmp/v049-backup-plain-r6-*`新run；R7演練另有`r7-entry-*`child及
version/source-kind證據。路徑前綴不當成「已獲現行核准」或collector版本。

### 2.2 單次完整資料流

1. 固定入口驗證來源及private root/custody；新provenance與archive物件綁定。
2. 同一readonly exported snapshot收集原六類、schema evidence、A/B profile、
   完整41筆member comment正文/typed identity與完整原custom-format dump。
   匯出後檢查原DDL/sequence/catalog/profile/comment/tool drift；不另讀取
   第二份正文來補第一份dump，也不從舊R6/R2證據拼裝新備份。
3. 演練來源先精確清理，再建立fresh target；未來現行備份只讀既有來源，
   **絕不清除/重啟現行PG**。任何時刻最多一個本工具新建PG容器。
4. 共用R5 sole bootstrap B/restricted A/有界trusted precreation，完整原archive
   single-transaction/exit-on-error還原，再共用R6 target-only COMMENT流程。
   不重排/過濾TOC、CASCADE、改system catalog、額外SUPERUSER或ACL補丁。
5. 原六類/raw schema hash/完整catalog、所有sidecar/custody/來源綁定必須
   完整相等；任何非bound member-comment差異仍在COMMENT前拒絕。
   SQL/取消/逾時rollback與target不可重用不變；失敗保留private partial。
6. `finish_bound_backup()`（或等價窄入口）在精確cleanup後重新核對archive、
   snapshot/schema/profile/comments/source/claim/postflight與restore proof的
   exact digest。缺件、替換、cross-run或不完整比較拒絕，不只檢查truthy PASS。
   演練僅輸出`ENTRY_REHEARSAL_PASS_NOT_QUALIFIED`、`usable_backup=false`、
   `current_data_export=false`；不得產生現行`qualified.json`或現行備份PASS。
   未來現行成功結果才可finalize，並保存全部綁定；不能把測試環境的資源
   保留證據當成現行`protected_resources_unchanged=true`。

完整archive及COMMENT為分開transaction，不宣稱跨步驟原子性；target失敗
整體丟棄，source及保留的檔案不變。備份正文永遠是敏感資料，不進repo/log。

### 2.3 CLI與狀態界線

保留原CLI、加密模式及retained diagnostic契約；只新增互斥
`--rehearse-backup-entry`，由程式建立本run合成A/B來源及已知測試內容，
不接受source/host/SQL/archive override，也不接受qualification、binding或
任何live opt-in旗標。先驗證參數再建立資源，與其他模式混用立即拒絕。
其實際roundtrip是共同核心的正向證據，不是現行執行的替身。

`--self-test-unencrypted`使用真實pytest child及CLI coverage：完成同源全套、
清理、report custody與whole-tool三種80%後，保存新版synthetic proof，exit0
並明確顯示`SYNTHETIC_PASS_NOT_QUALIFIED`。不得自動呼叫現行唯讀、建立
正式backup root或`qualified.json`；任何測試/清理/coverage失敗仍非零。
外層CLI驗收放在suite完成後真實檢查，不能讓pytest再遞迴呼叫完整self-test。

新proof至少驗證原212個非human-GPG案例仍存在/通過，並核對新增重要case
清單與實際JUnit、coverage及cleanup；不得只依目前`tests>=49`放行。
保留pytest-only及CLI+pytest兩份coverage來源與數字，同源才可合併。
本輪整合驗收三種whole-tool覆蓋各>=80%，不得靠現行讀取補足，也不能
合併R6舊coverage或縮小分母。R1歷史低coverage預備狀態不升格為新入口PASS。

`--qualify-source-readonly`、`--prepare-source`及`--backup-unencrypted`仍為
分開的明確操作，不自動串接。新現行source binding須核對固定PG/image、
已知release/V048/member baseline、protected resources以及受支援extension
版本/角色/member metadata；readonly階段不取得註解正文/應用資料、dump或
全資料hash，註解尺寸只作有界aggregate檢查。新資格必須綁定新版synthetic
proof及真正現行唯讀結果；來源/程式/時間漂移、缺證據或已用claim拒絕。
仍保留qualification24h、source binding15m、readonly300s等既有上限，
不把過去盤點當成目前仍有效。本輪不執行任何這些現行操作。

## 3. 工作順序、檔案與相容性

1. 原檔SHA基線與新spec/plan通過後，整理共用policy/provenance核心；不改
   原legacy成功/拒絕語意或固定PG支援範圍。
2. 接上新版export/restore/finalization evidence chain及owned rehearsal CLI。
3. 修正synthetic self-test的root/proof/exit state；只將未來LiveSource入口
   接到相同核心及更明確的資格檢查，不執行現行分支。
4. 先窄測試，再原212項與新增實例全套、整體coverage、真實CLI及獨立
   report/cleanup/source audit；結果分開記錄，不能用局部PASS代替全套。
5. 更新R7-RESULT/EVIDENCE、trace與六步狀態；保留所有失敗輪次。

修改限`backend/scripts/chg291_v049_live_backup.py`、其同名tests及規格/
追溯/結果文件。可共用同檔內小型helper，不新增外部服務或通用備份SDK。
不修改V001–V049、應用程式、Helm/Compose、image、密碼、資料或index。

起點script SHA：`763548e8d0f910e3765540baff1fdd508cfdc0e496a831af76efb696db1529b3`。
起點test SHA：`dc3c0253002c2efa1223a3bf4f3950e9e5f89cba7b21a17c28f666832ab9454f`。
R6已保存結果不覆寫；schema-evidence-v1與舊profile/comment契約不回填。

## 4. 真實測試與完成條件

| Case | 可觀察結果 |
| --- | --- |
| V49-U-T48 | 實際self-test CLI執行完整pytest後exit0，產生同源synthetic proof及全量reports；明確NOT_QUALIFIED，沒有readonly result/qualified.json/正式backup root；有界取消仍清理 |
| V49-U-T49 | 新rehearsal CLI實際建立A/B PG、同snapshot dump及新版證據、清理source再fresh還原；一般/自訂/刪除member comment案例六類/raw/catalog全等，sole B與受限A保留；只產演練結果 |
| V49-U-T50 | 以真實新檔案/來源錯配、mode混用、stale/cross-run/替換/custody/hash/version/claim負向案例驗證；合成proof不能進現行qualify/finalize，拒絕發生在現行操作前；不造假現行成功結果 |
| V49-U-T51 | 真實archive/sidecar/source/profile/comment/postflight digest完整綁定，漏任一證據/全比較/cleanup即拒絕；修改hash不能替代export-time binding；legacy/R2不自動轉新版 |
| V49-U-T52 | 真實source漂移、unsupported owner/member、SQL/lock/statement/cancel失敗有安全報告、rollback、consumed target與exact cleanup；原R6中途取消/原R5兩案例全部保留 |
| V49-U-T53 | 原212非human-GPG及新案例全PASS、無意外skip/xfail/error；whole-tool statements/branches/combined各>=80%，無舊coverage/exclusions，實際CLI及獨立報告audit、最終Docker baseline相等/零owned PG |

所有正向資料流用真實固定PG、pg_dump/pg_restore、程序、私有檔案。共享lab
案例放在原final cleanup前；獨立rehearsal CLI與source→target案例放其後。
必要負向驗證可損壞本run合成證據，但不能mock/stub/fake LiveSource成功，
偽造current identity/readonly PASS、手填合格proof或跳過protected check。

未執行的現行Kubernetes/DB資格、source binding、真正export與postflight正向
明確列NOT RUN，不能把共用核心演練寫成現行acceptance已完成。human-GPG
仍是非互動未加密範圍外唯一預期deselected，非其驗收通過。

## 5. 資源、敏感資料與排除範圍

沿用desktop-linux已安裝PG image
`sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
pull never；最多一個exact-owned新PG；network none、無ports/host mount/
existing volume/docker socket；2CPU、4GiB memory/swap、pids256、log none、
core off；PG tmpfs2GiB、tmp128MiB、run16MiB、空initializer ro tmpfs1MiB。
snapshot300s、restore+compare600s、self-test child600s、SQL10s/lock2s；
source256MiB/archive512MiB/metadata4MiB/schema32MiB、member body每筆64KiB/
合計1MiB均不放寬。0700目錄/0600檔、EXCL/no-follow/owner/ACL/nlink/inode/
hash守門、exact receipt清理不變；超限停止並記真實結果。

不讀現行Kubernetes/DB/支援服務、不讀/重播R2 archive或重設已消耗claim，
不新現行backup/readonly qualification/qualified.json、不建置/掃描/pull/
Job/Helm/V049/部署/Provider；不使用對話密碼。不得將明文註解/SQL/row/
secret/credential或子程序raw stderr輸出一般log、repo或人類摘要。

Gate4後在此已界定範圍內連續完成，不逐案例索取核准。新來源、資源、
權限、策略改變仍需說明；尤其「執行新版現行唯讀資格與新一次備份」不在
本計畫，完成隔離整合後須集中列出精確操作再請核准。部署亦仍需確認。

## 6. 驗證命令與交付

規劃輪只執行`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check`及source SHA；`plan:approved`應因Gate4 pending拒絕。
Gate4後才執行`plan:approved`、`backend:syntax`、真實窄pytest及完整
`--self-test-unencrypted`/`--rehearse-backup-entry`，採umask077、private reports。
直接pytest檢查沿用R6命令與來源完整coverage，不以其部分結果替代CLI驗收。

交付R7實際修改/測試/coverage/來源hash/私有report hashes/精確清理、
已知限制與六步進度；明確區分「工具整合通過」「現行備份合格」「部署
已完成」。本計畫只以第一項為隔離完成界線，不宣稱其餘五步已做完。

### 規劃輪驗證紀錄

`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`及`git diff --check`
均exit0。`plan:approved`為預期exit1，明確拒絕active Gate4 pending。
script/test SHA仍與第3節R6起點完全一致；沒有feature test、容器、現行
資料或部署操作。只更新本計畫、SPECIFICATION/SPEC_CHANGELOG/
DEVELOPMENT_PLAN/TEST_PLAN/TRACEABILITY與六步狀態文件。

### 核准後執行結果

Peter後續「核准」同意本計畫Gate4。現已完成R7隔離整合及驗證，見
[RESULT](CHG-291-V049-R7-RESULT.md)/[EVIDENCE](CHG-291-V049-R7-EVIDENCE.json)：
254PASS、0FAIL/ERROR/SKIP、1human-GPG deselected；原212/新42保留；兩份
whole-tool coverage三指標皆>=80%；5次完整new-entry roundtrip、獨立audit
及真正CLI取消/自動清理PASS。首次全套FAIL保留；新增fixture逐項精確清理
自己的DB/role，維持一容器/2GiB等全部界線。現行positive仍NOT RUN，
沒有qualified.json/新現行備份/V049/部署。本文規劃輪紀錄不覆寫為成功。

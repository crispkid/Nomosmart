# CHG-291 R2：既有備份一次性隔離重驗與差異診斷

2026-09-13。Peter 以 `Ok` 確認「只使用已保留備份，在隔離環境重驗一次並
記錄差異，不再次匯出、不修改現行資料」的範圍，**Gate 2 confirmed**。
本文件及 DEVELOPMENT_PLAN.md 為 Gate 3；Peter 隨後以 `Ok` 核准此書面
計畫，2026-09-13 **Gate 4 approval: APPROVED**。
這是診斷計畫，不是修改還原語意、接受不完整備份或繼續部署的計畫。

## 1. 已確認理解

- 六項收尾仍停在第2項；不另增產品需求。
- 原55測試版本通過資格後，唯一匯出已完成，pg_restore成功退出，但全量
  比對為 `restored_state_differs`。原partial與FAILED紀錄必須保留。
- 新增純合成回歸重現schema dump差異；其餘五類相同。這不能證明真實
  備份的差異也是plpgsql，不預設結論，也不刪除該失敗測試。
- 此次只判斷既有archive還原後，與匯出時snapshot有哪些差異；不查詢
  現行資料庫，所以不能證明現在環境未變、也不是新鮮的遷移復原點。
- 範圍、隱私界線與本書面實作／執行計畫已核准，不再詢問密碼。

## 2. 唯一輸入與不可變基線

輸入根目錄固定為：

`/Users/peter/NomoSmartBackups/V049/run-20260913T050023Z-0fab208e7f354a1e`

| 輸入 | Bytes | SHA-256 |
| --- | ---: | --- |
| database.partial.dump | 1,213,458 | a1b2395fb8d0778319d18303fbc678f5a06b2551abe34fa8b5a8a453c33b139a |
| snapshot.json | 10,484 | 54bfb213b84444e945e78709406d723f2618da51db8d72e3b4172bd0a5ac703b |
| source-binding.json | 8,763 | 9c566cf7c62afe876dfbc2ac5b6d4c94739f3e248c474eefcc4660d08a612bc7 |
| failed.json | 131 | 731702a15de37b7bc3e6082061a437c26e5e19a4793ab9fc89d6d6cbf469305a |

2026-09-13規劃唯讀核對：根目錄0700、四檔0600、uid501、檔案hardlink count1，
archive大小／SHA與上一輪報告一致。執行前後仍須重新核對，不把本次靜態
核對當作ACL、所有parent custody或實際還原驗證已完成。

原source binding canonical hash：
`23e4f42aba57cae3894403195e04a35db282782a296b7f22b7d2083f870bf9bc`。
它是2026-09-13原匯出來源證據，不將它刷新成現行來源或重用匯出權限。

## 3. 實作範圍

只修改 `backend/scripts/chg291_v049_live_backup.py`、對應test檔與
SPECIFICATION.md §10.57、SPEC_CHANGELOG.md、DEVELOPMENT_PLAN.md、
TEST_PLAN.md、TRACEABILITY.md及本次結果／六項進度文件。

1. 增加明確opt-in、與現有模式互斥的retained-archive diagnostic入口。
   正式入口只能使用上列四個固定檔案及其雜湊；不接受任意path、DB、SQL、
   context、container或output target。新CLI於實作後才記錄可執行命令。
2. 實作真正的readonly archive reader：`O_RDONLY | O_NOFOLLOW`、owner／
   mode／ACL／regular-file／hardlink／inode／size／SHA核對；不使用會建立
   新partial的PlainArchive constructor，不以手填物件欄位繞過constructor。
   重用或抽出既有讀取、串流、還原guard，不提供export／finalize／write方法。
3. 在輸入目錄下唯一 `r2-diagnostic/` 建立0700診斷目錄；檔案0600。
   exclusive claim在任何容器建立／真實還原前完成，綁定四檔SHA、image、
   tool/test SHA及時間。目錄／claim已存在就停止，不刪除claim以重播。
   原archive、snapshot、binding、failed、原container receipts一律不修改。
4. 使用既有MemoryPostgres限制建立一個新空白隔離DB；保留既有還原設定及
   NOLOGIN／NOSUPERUSER角色、owner／ACL語意。不增加privilege、不用
   --no-owner／--no-acl、不改SQL／extension、不手改catalog來消除差異。
5. 真實執行pg_restore一次，之後以原DatabaseState收集與比較完整六類：
   properties、roles、schema、tables、sequences、large_objects。
   在assertion／退出前保存差異類別；不能再只有一個籠統錯誤而丟失證據。
6. 若需辨識schema差異，可在相同時限內對既有archive唯讀取得TOC／schema
   表示，及對該隔離DB讀catalog／schema。內容只在記憶體分析，不執行產生的
   SQL，不另建第二個DB／第二次還原。archive重建的SQL文字未必與原pg_dump
   格式相同，不能把字面diff當成已證明資料損壞或等價。
7. 最後核對四輸入位元组／身分不變、exact-owned容器清理、既有Docker
   baseline相等。成功／失敗皆保留診斷與原partial，停止本輪。

## 4. 診斷輸出與隱私

診斷結果與備份資格分開：可用 `MATCH`、`DIFFERENT`、`ERROR` 表示實際
比較結果，但所有情況都保持 `backup_qualified=false`、
`migration_applied=false`、`deployment=false`。差異不是診斷工具假PASS；
比較不同或作業失敗仍回非零exit，保存結果後清理。

輸出限來源檔整體digest／bytes、安全的category equality、table／object
counts與bounded結構差異分類、role／extension等必要catalog識別。業務表
識別可用aggregate／hash；不输出逐列值、逐列hash、文件、對話、模型憑證、
完整SQL、comments、function bodies或未經篩選的stderr。完整SQL分析若有
敏感值只留記憶體，不持久化原始diff；無法安全分類就回報未判定。

repo僅收安全摘要和artifact SHA；必要私有證據留在r2-diagnostic內。
不生成qualified.json／restore-proof.json／成功backup result，不改名
database.partial.dump、不刪failed.json。之後是否修工具、如何修、重新
資格驗證與備份可用性，必須依實際差異另議，不能預先答應備份會合格。

## 5. 隔離與上限

- 只用已安裝映像
  `sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`；
  Docker context `desktop-linux`；不build、pull、push或prune。
- 合成安全測試與真實archive診斷序列執行；任何時間最多一個自建PG。
- 每容器2CPU、4GiB memory／memory-swap、pids256，PG tmpfs2GiB、
  /tmp128MiB、run16MiB及隔離initializer空tmpfs，log-driver none、禁core。
  network none、無published port、無Docker socket／現有volume／host dump mount。
- archive透過既有readonly FD／stdin傳給pg_restore，不複製到repo、一般
  tmp或持久container layer；fresh隨機測試憑證，不讀取／沿用現行Secret。
- 真實restore＋全部比較／schema診斷共用總deadline10分鐘，SQL statement
  10秒、lock2秒；safe metadata單次最多4MiB，archive限固定bytes／SHA，
  記憶體schema輸入上限32MiB。超限不截斷冒充完整比較，不重設deadline重試。
- exact receipts／label／image／baseline清理；清理失敗不宣稱作業完成。

禁止任何kubectl／Helm／現行DB或其他現行服務存取、重新匯出、V049／Flyway、
writer freeze、角色／群組／會員／index修改、Provider／billing呼叫、scanner、
網路分享、憑證解密、完整平台還原或原備份刪除。此次不是current preflight。

## 6. 測試與執行先決條件

新增V49-U007及V49-U-T16..T20，保留所有原測試與T15失敗證據：

- 真實檔案拒絕錯誤hash／mode／symlink／hardlink／替換／任意目標；readonly
  FD不能寫入，原檔／原FAILED不被改名／覆寫。
- 真實合成PG的相同和實際差異輸入，證明六類比較與安全報告忠實呈現；
  流程／restore失敗也在清理前保存安全原因，不預先手填通過結果。
- 真實CLI／exclusive claim測試：第二次呼叫在建立容器／還原前拒絕。
- 新增診斷路徑和共用安全邏輯須經自動coverage量測、至少80%；保留整個
  工具的coverage／未覆蓋路徑。R2不產生完整backup qualification；完整工具
  行／分支／合併各80%及原全套合格要求，仍是日後備份資格的必要條件。
- 原T15仍紅燈時，可作已知差異的診斷案例，但不得刪掉、xfail／skip或改成
  通過。此階段准許的是有界診斷，不以預備證明或本計畫冒充qualification。
  任一新增安全測試／input custody／cleanup／binding不通過，不碰真實archive。

Gate4後先跑spec:doctor、spec:trace、plan:approved、test:plan、backend:syntax、
git diff --check及上述真實隔離安全測試。新路徑證據／source hash完整後，
才執行一次真實archive診斷。缺工具或安全範圍不成立就停止，不臨時換方法。

## 7. 完成條件與本輪狀態

交付：真實六類結果、能證明與不能證明的差異、檔案不變／清理證據，以及
根據證據提出後續修復建議。不更改備份判定規則，不繼續六項中的3–6。

Gate4核准時只完成來源檔mode／owner／大小／SHA唯讀核對與本計畫；
Python實作、feature tests及唯一archive重驗結果須以下一輪真實證據記錄。

2026-09-13本輪文件檢查：`spec:doctor`、`spec:trace`、`plan:doctor`、
`test:plan`及`git diff --check`均PASS；各harness項目獨立執行。
`plan:approved` exit 1，原因為本R2計畫Gate4仍PENDING，屬必要停止點，
不是已核准或測試通過。Python工具及測試檔SHA與本輪開始時相同；
上述文件檢查不代表備份重驗或部署驗收完成。

## 8. Gate4後執行收尾

2026-09-13已完成核准範圍，詳見
`docs/CHG-291-V049-R2-DIAGNOSTIC-RESULT.md`及同名EVIDENCE.json。
新增七項隔離安全案例PASS且診斷／共用安全coverage超過80%；原T15仍FAIL。
保留archive真實還原僅一次，結果DIFFERENT：五類一致、schema不同。
62表／1341列完整資料比對一致；COMMENT區塊11/12僅為結構線索，並非
唯一原因／等價性證明。原輸入與FAILED不變，精確清理與Docker基線PASS。
本計畫單次claim已消耗，不重播；未qualified、未重新匯出、未部署。

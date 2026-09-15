# CHG-291 R4 Isolated Restore Identity Preservation

2026-09-13。Peter以`Ok`確認「只在隔離測試環境修正還原策略，現行系統維持
不動，部署前再確認」的理解（Gate2 confirmed）。本文件為具體Gate3計畫；
**Gate4 APPROVED**：Peter於2026-09-13以後續`Ok`核准本書面計畫。
僅開始此隔離修正與測試，不授權部署或現行資料／歷史archive操作。

## 1. 目標與已知事實

修正R3合成T15中43個owner／41個ACL差異，仍須通過原六類／raw schema hash
及逐物件完整比對。這不代表R2真實archive也有相同原因；不讀取、重播或升格
那份歷史archive，不存取目前DB以補造缺失證據。

PostgreSQL的extension本身與其內部物件不一定屬於同一身分。由superuser安裝
時通常屬於執行者；trusted extension由非superuser安裝時，內部物件可能屬於
bootstrap superuser。因此不能只ALTER普通table owner或比較role names。
來源：[CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html)、
[Extension packaging](https://www.postgresql.org/docs/18/extend-extensions.html)。

pg_restore還原會執行來源提供的程式；本輪只用我們新建的合成archive與固定
已安裝image，不能把這項操作擴到未信任dump或現行系統。
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)。

## 2. 允許的最小策略

1. 從同snapshot、完整且hash-bound SchemaEvidence建立`RestoreIdentityProfile`：
   extension／language／member identities、owners、版本、schema及必要初始
   權限證據。分清extension安裝身分與member owner，不能猜測或從DB owner代推。
2. 本輪先支援「受覆蓋extension及其member／language可由同一個初始化身分
   忠實建立」的profile。無法取得初始化身分profile時拒絕；owner不完整、mixed
   owners、缺版本、未知member或需要額外權限策略，先fail closed。
   這不是把混合ownership偷偷映射成同一人，也不承諾支援所有extension。
3. source container精確清理後，另建全新restore container。沿用唯一原本就有的
   bootstrap superuser，但其**名稱由已驗證profile決定**，不固定成backup_verify。
   使用全新合成憑證，絕不複製來源密碼／角色密碼／登入設定。
   initdb支援指定bootstrap身分；這是待真實測試驗證的方案，不是已PASS。
   [initdb](https://www.postgresql.org/docs/18/app-initdb.html)。
4. 不另外建立或提升SUPERUSER，不自動複製來源角色的LOGIN／CREATEROLE／
   REPLICATION／BYPASSRLS能力。非bootstrap來源角色維持NOLOGIN/NOSUPERUSER
   等現有受限設定。既有role碰撞檢查改為精確綁定本次bootstrap與固定image
   的既有內建角色，不以任意`pg_`字首當成新增身分的通行證。
5. 可檢查自己新建archive的完整pg_restore TOC。若完整來源證據及TOC都明確
   表示plpgsql必須由archive建立，可在**本次全新空白target DB**先移除
   initializer提供的plpgsql（RESTRICT、不得CASCADE），再執行完整archive。
   僅允許這一個事先盤點的初始化物件；不刪public schema／其他現行物件。
   TOC只供檢查，**不使用過濾／重排清單還原**，不改dump bytes，不執行重寫SQL。
   若PG固定版本對預設plpgsql的行為與假設不同，保留證據，不按總數猜測修補。
6. 整份archive仍走單一transaction、exit-on-error，保留owner／ACL／comments／
   RLS／constraints／triggers；禁止no-owner、no-acl、no-comments、停用triggers、
   UPDATE system catalog、忽略錯誤或為吻合hash自動COMMENT。
7. 同snapshot比對所有原有資料與metadata；六類、raw hash、逐物件、source drift、
   artifact custody及cleanup全都必須合格，才可宣稱此合成還原PASS。

### 初始化身分的安全界線

來源名稱只是資料，不是shell片段。只接收單一有效PG identifier，限制長度及
控制字元、保留名稱；SQL使用既有quote_ident/literal，argv/env值獨立傳入。
profile選擇、container intent/receipt、runtime guard、command/create_db及cleanup
全部綁定同一身分；不得只更改POSTGRES_USER而留下檢查仍固定backup_verify。
名稱／角色／catalog identities只留私有證據，一般報告使用hash與分類。

2026-09-13實作判定：固定image實測pgcrypto為1.4、plpgsql為1.0；初版profile
僅允許這些已證實版本。該image對含引號／shell符號的bootstrap initializer
不能可靠啟動，故初始化名稱先限制ASCII字母／數字／底線（不得數字開頭），
其他名稱在建立容器前拒絕，不改名映射、不更換image或修改entrypoint。
原T15來源名稱在支援範圍，仍要求成功；危險名稱保留負向拒絕測試。
擴充套件初版另綁定固定image實測之member identity清單digest（plpgsql /
pg_catalog與pgcrypto / public），避免只有class相同的未知member通行。
digest是支援範圍的拒絕條件，不取代逐物件定義、owner、ACL、initial privileges
或raw schema／資料比較；額外member及未支援schema須拒絕。

新增策略只能從帶完整新profile且來源標示為本輪合成測試的顯式入口啟動；
現行CLI、R2固定reader/claim與舊snapshot不能自動套用。若新增必要證據欄位，
使用新collector/profile版本及source binding；R3 sidecar可讀，但不能補值
後當成新策略的完整來源。`snapshot.json`原六欄契約不改。

## 3. 程式與測試調整

僅修改backup工具及其tests、規格／change／plan／test／trace／結果文件：

- `SchemaEvidence`：補足profile必要的同snapshot證據、版本／完整性。
- `RestoreIdentityProfile`概念：純驗證及選擇，缺證據拒絕，不查現行服務。
- `MemoryPostgres`：顯式bootstrap參數、intent/receipt/runtime guards一致；
  default保持原路徑，不能影響R2或現行來源操作。
- `DatabaseState.provision_restore`、`verify_restore`、`restore_isolated`：
  僅新合成模式採用新profile／允許的空白target初始化動作；沒有通用SQL修復接口。
- 原T15可改接真實source→cleanup→fresh restore測試流程並移到共享PG清理後，
  仍保留原合成情境與`actual == state`嚴格成功斷言，再要求catalog equality。
  不能改成「預期失敗」或刪除；之前失敗報告保持不變。
- 原正向／負向測試、限制、80%整體分母保留；新增策略不得讓旧路徑被假造PASS。

## 4. 固定資源、順序與命令

任何時刻最多一個自建PG；不得在module fixture尚存時另起第二個。
使用原已安裝image
`sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
Docker context desktop-linux，pull never，network none，無ports／host mount／
existing volumes／docker socket。2CPU、4GiB memory/swap、pids256，PG tmpfs2GiB、
tmp128MiB、run16MiB、empty initializer tmpfs、log none、core off。
原source256MiB／stream512MiB／metadata4MiB／schema32MiB、SQL10s／lock2s、
snapshot300s／restore-and-compare600s上限不提高；profile及TOC也共用限額／deadline。
新私有目錄`/private/tmp/v049-backup-plain-r4-*`0700、檔案0600；精確receipt清理，
原Docker inventory一致，報告和來源hash可追溯。合成資料隨tmpfs清除，保留報告。

Gate4後：profile/spec/test設計→code→窄真實測試→原T15→完整回歸／coverage→
記錄結果及精確清理。過程不重複要求已核准範圍；只有新的權限／資料／restore
策略擴張才停下，不宣稱本計畫已包含未界定的進階owner重建。

分別執行：`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、`test:plan`、
`backend:syntax`、`git diff --check`；真實pytest/coverage沿用原檔、
`-k 'not human_gpg'`、`--branch`、private XML/JSON。不執行現行readonly
qualification CLI，不為coverage創造現行存取或qualified.json。

## 5. 測試矩陣與完成條件

| ID | 真實驗收 |
| --- | --- |
| V49-U-T28 | profile來自完整同snapshot證據；mixed/missing/unknown/version/hash/custody錯誤在target操作前拒絕；不同安裝owner/member owner不能混同 |
| V49-U-T29 | source與fresh target bootstrap不同名稱情境仍完整還原；保留原T15，43owner/41ACL差異真正消失，不是改expected；另保留原default成功案例 |
| V49-U-T30 | 真實TOC與catalog決定預設plpgsql保留／重建；完整archive不過濾，raw schema及catalog同時一致；有依賴時RESTRICT失敗且不改用CASCADE |
| V49-U-T31 | 唯一bootstrap、其他角色仍NOLOGIN/NOSUPERUSER；錯誤runtime identity、危險名稱、碰撞、未知image／版本拒絕，無外部指令執行 |
| V49-U-T32 | 中斷／真實錯誤保留安全診斷、exact cleanup／baseline；新模式不進入LiveSource、R2或現行匯出／部署路徑 |
| V49-U-T33 | 全套原測試和新案例、coverage、source/report integrity；三種whole-tool coverage各80%，不得刪除分母／skip原FAIL／以局部coverage替代 |

T15通過只是解除一項阻擋，不等於現行備份合格。既有真實資料備份、完整應用
驗收、fresh protected baseline／維護窗口／dry-run/hash／精確部署核准仍需各自
證據與授權。遇不能忠實還原者保留FAIL，禁止以「快部署」降低門檻。

## 6. 排除與本輪狀態

不讀現行Kubernetes／DB／其他服務、不讀或重驗R2 archive、不新匯出現行資料、
不改舊claim/FAILED、不掃描／build/pull image／建Job／改權限會員／改索引／
Provider／V049／部署。不得複製對話密碼、現行憑證或source角色密碼。

本輪只完成理解、官方文件核對、規格與書面計畫；尚未改Python或執行feature tests。
以上為規劃輪紀錄；Peter已以後續`Ok`核准具體Gate4計畫，接續實作與測試。

規劃輪檢查：spec:doctor、spec:trace、plan:doctor、test:plan、git diff --check
PASS；plan:approved exit1，原因為R4 Gate4 pending。tool/test SHA與R3最終
595f3cb45fa4bce488da5dc14a515fea9bb06fafc84dee41ba3b67a69713681f /
14ba2087afa58f66e50660c574d8f80830cea08592d86467005459b92ef74608相同。
以上是規劃檢查，不代表新策略或備份已驗證通過。

Gate4後最終結果：133PASS含原T15；真實報告防護補驗合併後whole
statements80.26%／branches80.66%／combined80.31%，cleanup/baseline PASS。
詳見CHG-291-V049-R4-RESULT.md及EVIDENCE.json。僅隔離修正驗證完成；
沒有現行服務存取、qualified.json、真實備份重驗或部署。

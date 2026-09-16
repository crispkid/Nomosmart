# CHG-291 V049：本機不加密備份與隔離還原修訂計畫

## R1：資格驗證順序修訂（已核准執行）

2026-09-13，Peter 以「好」同意把現行來源唯讀檢查提前納入資格測試：
**R1 Gate 2 confirmed；Gate 3 complete；Gate 4 approval: APPROVED。**
Peter approved Gate 4 on 2026-09-13，以「一次性依序完成這6項工作」要求依序
執行，包含已寫明的第 1 項 R1；可開始此計畫工具/測試與符合條件後唯讀檢查。
不把核准當 PASS，不追認未界定的高風險變更；六項進度合併記錄於
`CHG-291-SIX-STEP-CLOSEOUT.md`，舊 pending/失敗紀錄仍保留為歷史。

### R1.1 目標與不變邊界

解除「完整 coverage 達標才能做來源檢查，但來源檢查也是待測程式」的順序
問題。保留整個工具分母、行/分支/合併各 >=80%、真實服務、不偽造通過結果。
不是降低門檻，也不保證只補唯讀檢查就能達標。

本次 Gate 4 請求只涵蓋：本工具/對應測試修訂、真實隔離合成測試重跑、
符合先決條件後一次有界現行來源唯讀驗證、真實 coverage 合併與結果報告。
**本次 R1 執行止於資格結果，不自動串接正式匯出。** 原核准一次 current DB
備份的數量/來源/保管/還原界線不變；不能用預備證明啟動 `--backup-unencrypted`。
不建正式備份目錄，不執行現行來源 pg_dump/還原到現行 DB、V049、停寫、Helm/Kubernetes
write、Job、映像 build/pull/push、掃描、Provider、資料/index/membership 變更。
合成測試仍可沿用原核准的唯一 tmpfs PG；現行唯讀階段不建立任何容器/Job。

### R1.2 新順序與資格證明

1. **先修工具並重跑合成測試。** 改動範圍只限
   `backend/scripts/chg291_v049_live_backup.py`、對應測試與本計畫文件。
   保留所有既有案例，原 49 項已測行為必須持續通過；人工 GPG 仍 NOT RUN，
   不假造 TTY/密碼、不把它的分母排除。self-test 仍不得連線 Kubernetes。
2. **新增預備證明，不能當正式資格。** 僅在實際 pytest exit 0、所有選定
   合成案例無 failure/error/未說明 skip、source/test SHA 前後一致、實際
   容器清理/既有 Docker 基線比較成功後，產生私有 `synthetic-proof.json`。
   狀態明列 `SYNTHETIC_PASS_NOT_QUALIFIED`；包括 source/test/image IDs、
   真實 JUnit/coverage/cleanup 檔案雜湊與時間。coverage 未達標可取得此
   預備證明，但不能產生 `qualified.json`，原完整資格命令仍回傳未合格。
3. **獨立唯讀資格入口。** 只接受同一來源版本、完整私有證據及有效時間
   <=24h 的預備證明；重新檢查真實報告，不僅相信狀態字串。與匯出 mode
   互斥、明確 opt-in，不能接任意 SQL/namespace/DB/輸出目錄，也不能呼叫
   `PlainArchive`、`create_backup_directory` 或 `export_database`。
   以 exclusive 本地 claim 防止同一 run 自動重播來源檢查；失敗停止並保留
   證據。程式異動使先前 proof 失效，須重新測試；不手改舊 proof 成功。
4. **執行下一節限定的真實檢查。** 在 coverage 下執行實際來源保護函式及
   assertions；完整記錄開始/結束、exit code、檢查結果與 SHA，不模擬
   Kubernetes/DB 回傳。唯讀成功證明只表示檢查通過，不表示有備份。
5. **最後一次完整資格判定。** 只合併同一 tool/test SHA、同一 qualification
   run 的實際 `.coverage` 資料；保留原始與合併報告。重新驗證所有執行碼、
   測試、cleanup、唯讀檢查、來源/證據完整性，再檢查行/分支/合併各 >=80%。
   不把歷史不同版本或失敗執行的 coverage 混入。任何一項失敗就不建立
   `qualified.json`；達標仍須通過來源安全檢查，不能用 coverage 取代驗收。
6. **報告並停止。** 回報實際資格結果、未覆蓋路徑、來源狀態與未執行項目。
   不承諾必然達標；如仍失敗，只修核准工具範圍或討論缺口，不自動備份。

### R1.3 現行來源唯讀 allowlist

- 固定 context `docker-desktop`、namespace `nomosmart`、release
  `nomosmart-local`、Pod `nomosmart-local-postgresql-0`、container `postgresql`、
  DB `nomosmart`；不切換至其他 context 或 DB。
- 預期 deployed revision 36、Pod Running/Ready、映像
  `nomosmart/postgresql:18.4`；唯讀核對並綁定 Pod UID/runtime image ID。
  不以舊紀錄假設目前仍健康。相關 deployment/statefulset/daemonset readiness、
  Service/Ingress/PVC/PV 身分與 spec 安全摘要、七組 Bound PVC/PV、Secret
  metadata 只讀取必要欄位，資料均不輸出成原始 YAML/JSON。
- Secret 必須使用伺服器 metadata-only representation 並驗證回應類型；
  不可用「取回完整 Secret 後再 jsonpath 過濾」冒充 metadata-only。
  只用目前 context 已設定的認證，不能抽取/複製 key/token/password 到
  新檔案、argv 或 log；無法安全取得 metadata 就停止，不改 RBAC/憑證。
- DB 僅使用既有 Pod 本機認證及 readonly transaction。查詢清單限 DB
  identity/read-only 狀態、Flyway 最新版本/checksum/success/failed counts、
  1 Project/1 Owner/3 memberships、MAAS user01 Owner 與 user02 Editor+Viewer
  預期匹配數、DB size/恢復狀態、extension/tablespace/FDW/publication/
  subscription/DB properties 的支援性 catalog。
- 預期 V048 checksum `1657807790`，無 V049/failed migration。只回傳必要
  counts、布林、安全 catalog 識別/摘要，不回傳文件、對話、模型密鑰、
  完整人員資料或逐列業務內容。不執行 schema/data dump、table-data hash、
  Flyway、應用/ORM 初始化、DML/DDL 或負向 live 故障注入。
- 命令只允許已界定的查詢；現行 preflight 的 SQL 不由外部任意傳入。
  維持總上限 5 分鐘、SQL statement 10 秒、lock 2 秒、metadata 每次最多
  4 MiB、來源 DB <=256 MiB；超限、權限/連線失敗、健康惡化、來源/成員/
  版本漂移即停止，不改 expected 值繼續、不修環境、不自動重試其他來源。
- 正常連線/access audit/DB metrics 可能由平台記錄，不宣稱「零系統紀錄」。
  僅本地私有 run 目錄保存必要識別/雜湊/檢查結果，不保存敏感 payload。

### R1.4 測試、檔案與交付

新增需求 `V49-U006` 與 `V49-U-T11..T14`：預備 proof 不可用於匯出、
proof/CLI 失效拒絕、真實唯讀來源 assertion/metadata-only、同源 coverage
合併與完整 gate；保留 `V49-U001..U005`、`V49-U-T01..T10`。
source readonly negative cases用工具輸入拒絕與實際可安全構造的隔離情境，
不更動現行環境製造負向案例，也不把無法執行的分支冒充通過。

只改上述 Python 工具/對應測試、SPECIFICATION.md §10.57、SPEC_CHANGELOG.md、
DEVELOPMENT_PLAN.md、TEST_PLAN.md、TRACEABILITY.md 與此計畫/結果文件。
既有 RESULT/EVIDENCE 原始測試數值/檔案雜湊不覆寫；新 run 獨立追加紀錄。
沒有產品/API/schema/chart/image 改動，無需部署本工具才能驗證。

Gate 4 後跑 `spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、
`backend:syntax`、`git diff --check`，再依序真實合成測試、source-readonly
qualification 與完整 coverage gate。新 CLI 名稱/可執行命令在實作並通過
輸入 guard 測試後記錄；本規劃文件不提供尚未實作的假成功指令。

本次交付為驗證結果，不是備份/遷移完成；任何後續正式備份仍須最新來源
binding（<=15 分鐘）與現有一次匯出 guard。V049/停寫/部署仍須各自授權。

核准問題：是否核准 R1 工具/測試修訂、真實隔離合成測試、符合預備條件後
的精確現行來源唯讀驗證及完整資格判定，不含正式匯出、V049 或部署？

### R1.5 本輪文件驗證

2026-09-13：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check` PASS。`plan:approved` exit 1，明確顯示 R1 Gate 4 pending，
符合規劃階段預期。工具及對應測試 SHA 與上一輪 RESULT/EVIDENCE 相同。
未改 Python、未跑 feature tests、未存取現行 Kubernetes/DB、未匯出/部署。
文件檢查不是資格通過證明；目前仍無本次 current DB 備份。

## 原 A–E 計畫與核准紀錄（歷史，其他邊界沿用）

2026-09-13。Gate 2 confirmed：Peter 以「接受」確認不加密資料風險與本機
保存／隔離還原界線。Gate 3 完成；**Gate 4 approval: APPROVED**。
Peter approved Gate 4 on 2026-09-13，以「核准」直接同意本 A–E 修訂計畫。
允許工具與資格驗證先行，只有通過後才執行一次核准的現行 DB 備份；不是
把核准當作驗收成功，亦不包含 V049、停服務或部署。下方核准前狀態為歷史。
這是既有加密備份計畫的窄範圍修訂，不是已執行備份或部署的證明。

執行狀態（2026-09-13）：A 已實作並跑真實測試；最新 49 項通過，但整體
79.43% / 分支 73.72% 未達 80%，因此 B–E 未執行，沒有正式備份。
完整結果：[資格驗證結果](CHG-291-V049-UNENCRYPTED-BACKUP-RESULT.md)。
其中提出的先後順序已由 Peter 以「好」確認 Gate 2；上方 R1 為 Gate 3，
尚待新 Gate 4，不把舊計畫核准誤當作新順序可執行。

## 1. 已確認與本次核准範圍

依 [已確認理解](CHG-291-V049-UNENCRYPTED-BACKUP-UNDERSTANDING.md)，本次
不使用 GPG、Pinentry、聊天密碼或新加密金鑰；Peter 不需要接觸電腦。
改為單機未加密 PostgreSQL custom-format dump；格式／壓縮不是加密。
明文保管風險已接受，但不降低 production 政策、應用憑證加密或還原驗證要求。

核准此修訂計畫，將一併授權下列 A–E：工具修改、真實合成資料安全測試、
精確來源的唯讀盤點、**一次現行資料庫完整不加密匯出**、隔離還原／比對及
精確自有容器清理。合成資料測試可在上限內修正重跑，各次證據保留；真實
匯出若失敗就停止，不自動建立另一份現行備份或重試其他來源。

不含部署／Helm write、Kubernetes 資源或 Job 建立、writer freeze／縮放、
V049 或其他 live DDL/DML、目前 DB 還原、映像 build/pull/push、掃描／SBOM
外傳、Provider、reprocess、re-embed、reindex 或 manifest switch。
原 V001–V049、產品 API、角色規則與累積程式碼不變。

## 2. 來源、保存與風險

| 項目 | 精確界線 |
| --- | --- |
| 來源 | context `docker-desktop`，namespace `nomosmart`，release `nomosmart-local`，Pod `nomosmart-local-postgresql-0`／container `postgresql`，僅 DB `nomosmart` |
| 預期版本 | deployed revision 36、成功 Flyway V048／checksum 1657807790、無 V049／failed history；UID、映像與 Owner/member 基線須先重新唯讀綁定 |
| 現行認證 | 僅 Pod 既有本機連線；不擷取、顯示或複製 Secret／連線密碼到主機或還原容器，不繼承任意 DATABASE_URL |
| 內容 | 全部非系統 schema、資料、large objects、sequence、owner／ACL、constraint／index／comment／extension 與 Flyway；不只備份 membership |
| 正式檔案 | `/Users/peter/NomoSmartBackups/V049/` 下全新唯一 run 子目錄；`.partial.dump`、私有 manifest，驗證後才封存成 `.dump` |
| 權限 | 目錄 0700、檔案 0600，核對 owner、ACL、路徑各元件；不覆寫、不循 symlink，不擅改既有父目錄權限 |
| 保留 | 成功檔／失敗 partial 都不自動刪除；至少保留至後續部署驗收完成後七天，刪除須 exact-path 核准 |

不放 repo、一般暫存目錄或已知雲端同步根目錄，不上傳、不建立下載連結。
只允許合成測試資料／非敏感測試報告位於私有 `/private/tmp/v049-backup-*`。
備份根目錄不存在時，可在核准位置逐層建立新的私有目錄；建立仍須通過環境
權限審核。已存在而權限／ACL 不安全就停止，不修改它來繞過檢查。

明文備份可能含文件、個資、對話、角色／成員、模型設定。取得檔案副本者、
Peter 帳號或本機管理員不需備份密碼即可讀取原本未加密的內容。限制檔案
權限不能取代加密；不宣稱已確認 FileVault、未知同步軟體或硬體零殘留。
資料庫既有加密憑證欄位保持不透明，不解密、不使用、不輸出。

不包含 `pg_authid`／cluster 角色密碼、Kubernetes Secret、應用加密金鑰、
Keycloak DB、LDAP、S3 檔案、Neo4j、OpenSearch、Redis 或 PVC/PV 快照。
因此不是全平台 DR；原加密金鑰及外部服務仍依各自保管／復原安排。

## 3. 工具改動與執行順序

### A. 工具與真實合成資料驗證

只改 `backend/scripts/chg291_v049_live_backup.py`、其對應測試及本計畫相關
spec／plan／test／trace／結果文件。沿用 Snapshot、MemoryPostgres、串流／
程序退出與 exact-receipt 清理；補齊未完成的完整 DB 指紋、來源 guard、私有
檔案串流、還原角色／ACL 與 live orchestration，不直接刪除 GPG 呼叫就匯出。

新增明確 opt-in 的非互動自測及不加密備份入口，預設不匯出真實資料；self-test
不連線 Kubernetes。live 入口須核對本次來源 binding 與已通過的同一份工具／
測試 source hash，不接受任意來源、任意輸出目錄或掃過整個 cluster。
未完成實作與資格驗證前，不交付假裝可執行的 live 指令。

保留既有人工 GPG 路徑／測試和歷史失敗，不用 fake TTY 或假密碼測試它。
新不加密路徑無須 GPG 通過；未執行的 GPG 案例明列未執行，不算 PASS。
不刪測試、不新增 coverage omit／pragma 或降低門檻；新增及共用工具邏輯
必須有自動量測的 statement／branch coverage >=80%。同時保留整個工具
量測與未覆蓋行，不能透過搬移程式排除既有分母來湊過門檻。

使用真實自建 PostgreSQL 與真正 pg_dump／pg_restore，不用 mocks、stubs、
fixture adapter、偽造 migration history 或預設成功。先測正常與失敗路徑，
完成資格驗證才進 B；測試失敗只修本工具範圍，產品缺陷／需求擴大須另議。

### B. 精確唯讀盤點與資源界線

- 重新確認來源版本／Pod UID／映像、DB identity、既有 Owner/member 結構。
  依原盤點預期 MAAS user01 Owner、user02 Editor+Viewer；版本／來源／此
  結構變動就停止。其他業務表以此次快照內容為基準，不刪除合法新增資料。
- 盤點既有 Docker 容器、volumes、images、networks 及相關 Kubernetes
  保護資源的 identity／安全摘要；不把 Secret payload 或整份容器 env 輸出。
- 來源 DB size <=256 MiB，未加密 custom dump 串流 <=512 MiB；確認目的地
  可用空間至少 1 GiB。快照持有 <=5 分鐘，還原與比對合計 <=10 分鐘。
  source lock wait <=2 秒、每次 SQL statement <=10 秒；整體限時不得因子
  程序重試而重置。超限／權限不足／健康惡化／基線漂移都停止。
- 只用已安裝 PostgreSQL image
  `sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`。
  每輪最多一個隔離 PG 同時存在；合成測試與真實還原序列執行。
  每容器 2 CPU、4 GiB memory／memory-swap、PG tmpfs 2 GiB，沿用 pids256、
  log-driver none、core dump disabled、空 tmpfs 隔離應用 initializer。

### C. 唯讀快照匯出與私有檔案完整性

以來源唯讀 repeatable-read exported snapshot 同時供 full pg_dump 及資料／
結構摘要使用。只收集列數、雜湊、安全 catalog metadata；不輸出原始列值、
文件、敏感 SQL error 或明文 dump 到工具回應／一般 log。
完整 schema 定義、comments／函式內容即使包含業務文字亦只在記憶體比較／
雜湊，不另存 repo 或一般暫存檔；必要私有 manifest 只留安全摘要。

pg_dump → 有大小／時間上限的串流 → 事先 exclusive、no-follow 建立的
0600 `.partial.dump`；不經一般暫存檔、不交給會記錄 stdout 的 command
capture。所有程序 exit code、非空／格式、實際檔案 bytes、fsync 與 SHA-256
都需核對。保留同一私有檔案的 identity，拒絕替換、symlink、hardlink／ACL
風險或不安全權限；封存須原子且不得取代現有檔案。

一般／分區／繼承表、large objects、sequence 及結構均需完整比較，不任意
跳過。各比較使用穩定、完整而非抽樣的表示；不回傳單筆敏感資料雜湊。
sequence 不受 MVCC snapshot 保證，source 前後 sequence／DDL 差異即停止
一致性驗收。無法忠實備份／還原的 extension、tablespace、外部資料連線或
其他不支援物件也停止，不繞過或省略。

### D. 無網路、tmpfs 隔離還原與比對

用全新 exact-run-owned PG／空白 DB，`--network none`、無 published port、
無 Docker socket、無 host dump／現有 volume mount；所有 data／WAL／temp
均須核對 tmpfs。私有 dump 經 pipe／docker exec stdin 送入 pg_restore，
single transaction、exit-on-error，不把真實 dump 複製到持久容器儲存。

只產生新的測試憑證；必要的 source owner／ACL 角色識別在隔離 DB 建為
NOLOGIN／NOSUPERUSER，不複製角色密碼或 cluster 登入權限。保留物件 owner／
ACL 的語意，不能用 --no-owner／--no-acl 掩蓋缺漏。遇到名稱衝突或無法忠實
還原就停止；這不是完整 cluster 權限或應用登入驗證。

完整還原後比對所有資料、物件結構、large objects、sequence、owner／ACL、
constraint／index／comment／extension、Flyway V048。user02 的 Editor+Viewer
必須原樣保留，不套 V049，不啟動任何應用／bootstrap／Flyway／外部連線。
檔案 digest／size 在匯出後與還原前後核對；digest 不是加密或數位簽章。

### E. 清理、封存與報告

成功／失敗都以 receipt 綁定的 exact ID／label 清理新容器及 tmpfs；檢查
preexisting Docker／Kubernetes 保護資源未由工具修改。不做 prune，不刪
備份／partial，不自動修環境。清理失敗也不得標示整體 PASS。

只有匯出／完整還原／全量比對／清理全部成功，才以 no-replace 原子操作
將該 run 的 partial 封存，並寫出與 digest、source／tool／image 綁定的
成功 manifest。失敗維持 partial／FAILED，不宣稱可用復原點；報告不含內容。
SHA-256 不能抵抗同時有權修改備份與 manifest 的人，已接受風險不擴張。

新增 `docs/CHG-291-V049-UNENCRYPTED-BACKUP-RESULT.md` 及 `-EVIDENCE.json`，
保留原加密資格驗證報告。Private manifest 記錄必要完整摘要；repo 只記
整體檔案 digest／大小／時間、source／image／tool hashes、測試與清理結果。
正式路徑回報可作本機檔案參照，但不讀取／展示 dump 內容或建立網路分享。

## 4. 測試、相容性與驗收

穩定需求 `V49-U001..U005` 對應前次理解的 `V49-U01..U05`；內容不變。
TEST_PLAN.md 使用 `V49-U-T01..T10`，TRACEABILITY.md 分開記錄新方案與
原 `V49-B01..B08` 加密方案；不把未執行的加密測試改列已通過。

Gate 4 後依序跑 `spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、
`backend:syntax`、`git diff --check`，再執行真實合成資料正常／負向測試、
80% coverage 與來源綁定驗證，最後才允許本次 live 唯讀備份及隔離還原。
本輪只規劃，不跑 feature tests；文件檢查不代替備份驗收。

保留全產品 frontend／backend 80%、完整 E2E／release 缺口；不掃描指示仍
維持，不能把未執行的安全檢查標示通過。Docker Compose／Helm 模板、app
config／image、產品／DB schema 不改；不需要因本次工具計畫建置或部署。

## 5. 明確停止點與後續

本次在線備份不是遷移前停寫窗口的最終復原點。正式 V049 前仍需 fresh
baseline、已界定的 writer freeze、最新已驗證備份、精確候選／render 綁定、
migration-before-app 順序及可用回退；本計畫不一併授權這些 live writes。
不用加密不代表可跳過備份驗證或把失敗測試當成完成。

核准問題：是否核准本計畫 A–E，包含工具／真實合成資料測試、一次精確現行
DB 的不加密本機備份與隔離還原／清理，不含 V049、停服務或部署？

## 6. 本輪文件驗證

2026-09-13：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan` 及
`git diff --check` 通過。Active change 已切回本次 CHG-291 修訂；
`plan:approved` exit 1，原因是 Gate 4 PENDING，符合預期，未繞過 gate。
未修改任何備份工具／測試程式，未執行 feature tests、current DB 查詢／
匯出、建立備份目錄／還原容器或部署；不把文件檢查當成功備份證明。

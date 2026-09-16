# CHG-291 V049 — 現行資料加密備份與隔離還原計畫

日期：2026-09-12。Gate 2 已確認；Gate 3 完成；**Gate 4 已由整合準備階段 C 核准**。
本文件不是已完成的備份、還原或部署證明。

2026-09-13 最新變更要求：Peter 無法操作電腦，要求改為不加密備份。
本文件保留原加密計畫與核准歷史，不默默移除其安全限制；新例外的理解與
明文風險見 `CHG-291-V049-UNENCRYPTED-BACKUP-UNDERSTANDING.md`。Peter 已以
「接受」確認 Gate 2；新計畫為 `CHG-291-V049-UNENCRYPTED-BACKUP-PLAN.md`，
Gate 4 待核准。現在不要求 Pinentry，也未執行明文匯出或使用對話密碼。

Peter 隨後於 2026-09-12 以「同意」直接核准書面整合準備計畫 A–C，涵蓋本計畫，
不擴大任何來源、密碼、隔離、保留及 live mutation 排除範圍。以下原待核准文字
及當時檢查結果為歷史紀錄；實際加密仍需 Peter 在自己的 Terminal 輸入密碼。

後續 Peter 以「Ok，往這個方向執行」確認三映像與 V049 整合發布方向。
本備份計畫已納入 `CHG-291-INTEGRATED-RELEASE-PLAN.md` 準備階段 C；
所有資料／密碼／隔離／保留限制保持不變。該整合準備計畫 Gate 4 仍待核准，
方向確認不當作真實資料匯出或部署核准。

## 1. 本次要做什麼

將現行 NomoSmart PostgreSQL 資料庫備份成加密檔，並在全新、無網路的
本機 PostgreSQL 測試容器中確認能還原、內容一致，之後清除該測試容器。
不停止目前服務，不修改目前資料，不套用 V049，也不部署任何映像。

Peter 已以本次 `Ok` 確認：

- 備份位置為 `/Users/peter/NomoSmartBackups/V049/`，不放 Git 或雲端同步目錄。
- 使用加密備份；密碼由 Peter 在自己的本機終端輸入及保管，不放進對話。
- 至少保留至後續部署驗收完成後七天；刪除仍須 Peter 另行核准。

本 Gate 4 將另外授權：在以下界線內實作備份工具、執行驗證，以及把
**真實資料庫的完整邏輯內容**寫成該位置的加密備份。不是只有測試資料。
密碼輸入需要 Peter 在執行時參與；代理不接收、代填或擷取密碼。

## 2. 規格與前置證據

產品規格不變：SPECIFICATION.md 10.48 PROJECT-012、PROJECT-010，
MIGRATE-001、9.5 DEPLOY-004、DEPLOY-006 及 TEST-002。
原始 `sql/migrations/V049__exclusive_project_member_role.sql` 不變，SHA-256：
`b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`。

- 唯讀盤點：`CHG-291-V049-READONLY-INVENTORY.md` 及其 evidence JSON。
- 已通過的自建資料演練：`CHG-291-V049-REHEARSAL-RESULT.md`。
- 該演練證明原 V049 及 CHG-292／目前原始碼的受測相容性；不證明現行資料已有備份。

最近盤點為 revision 36、Flyway V048，V049 尚未套用；MAAS 的 user01 為 Owner，
user02 同時有 Editor 與 Viewer。V049 預期只移除後者的一筆多餘 Viewer 關係。
這是歷史基線，執行前必須重新唯讀確認，不能直接當成目前狀態。

## 3. 精確來源與排除範圍

允許的來源只有：

| 項目 | 範圍 |
| --- | --- |
| Kubernetes context | `docker-desktop` |
| Namespace / release | `nomosmart` / `nomosmart-local` |
| PostgreSQL Pod / container | `nomosmart-local-postgresql-0` / `postgresql`；執行前綁定實際 UID 與 image ID |
| Database | `nomosmart`，不得繼承任意 DATABASE_URL 或改成其他資料庫 |
| 讀取方式 | Pod 既有本機連線及既有認證；唯讀 SQL、同一快照的 pg_dump |
| 備份內容 | 單一資料庫全部非系統 schema、資料、large objects、sequence、物件 owner/ACL、Flyway 歷史；不任意過濾表格 |

資料可能包含文件文字、個資、對話、成員／角色、模型設定及其加密憑證欄位。
這些欄位只作為不透明備份資料，不解密、不使用、不顯示、不傳至外部服務。
不讀取 `pg_authid` 密碼，不匯出 cluster 角色密碼，不擷取 Kubernetes Secret
或應用程式加密金鑰。現有來源憑證不得複製到測試容器或主機設定。

不包括 Keycloak 資料庫、LDAP、S3 原始檔、Neo4j、OpenSearch、Redis、PVC/PV
快照或其他資料庫。因此這不是全平台災難復原備份；加密欄位的業務復原仍依賴
原有、另行保護的應用程式加密金鑰。本計畫不改變該金鑰的保管方式。

禁止 Helm write、Kubernetes Job／資源變更、維護停機／縮放、live DDL/DML、
V049 apply、模型／Provider 呼叫、reprocess、re-embed、reindex、manifest switch，
以及將備份還原回目前的資料庫。隔離還原副本也不執行 V049 或任何應用程式。

## 4. 執行順序與停止條件

### A. 先完成工具及自建資料安全檢查

核准後才新增 `backend/scripts/chg291_v049_live_backup.py`、對應真實服務測試
`backend/tests/test_chg291_v049_live_backup.py`，及本機 Terminal 操作指引。
不更動產品程式、原 V049、既有演練工具或其他累積變更。

先以自行建立的資料驗證串流加密／解密／還原、錯誤傳遞、截斷檔、取消及隔離
清理，不用 mock 或預設成功路徑。不能直接沿用會把測試 dump 寫成明文的舊
演練程式來處理真實資料。所有步驟均保留子程序失敗狀態，不能只看最後一段成功。

### B. 唯讀新基線與資源上限

1. 確認 context、release revision 36、V048／無 V049、來源 Pod UID／映像，
   並重跑既有成員／Owner 安全盤點。版本、來源、成員／Owner 結構與上述基線
   不符即停止，回報差異；不自動修資料。其他表格使用此次快照的實際內容作基線，
   不把正常業務新資料誤認為必須刪除的差異。
2. 確認已安裝的 pg_dump／pg_restore 版本相容、GPG／Pinentry 可用、Docker
   可用、備份路徑非 symlink，且沒有落入已知雲端同步根目錄。其他同步軟體設定
   仍依 Peter 已確認的本機保管安排；不能僅由路徑宣稱絕無同步。
3. 僅允許目前已安裝的 `nomosmart/postgresql:18.4`，image ID：
   `sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`。
   不 pull、build 或換用其他映像；映像不符則停止。
4. 先盤點所有既有 Docker 資源。新 PostgreSQL 容器最多一個同時存在，
   自建資料檢查與真實資料還原分開使用、最多兩個依序建立；每個上限
   2 CPU、4 GiB memory，memory-swap 設為相同上限，PG tmpfs 上限 2 GiB。
5. 本輪來源 database size 上限 256 MiB、未加密 dump 串流上限 512 MiB、
   來源快照持有時間上限五分鐘、隔離還原及比對上限十分鐘。
   超限、鎖衝突、空間不足、服務健康惡化或權限不足都停止，不自動放寬。

### C. 加密備份，不產生明文 dump 檔

- 在來源保持有上限的唯讀 repeatable-read transaction，匯出 snapshot；
  pg_dump custom format 與資料摘要比對使用該快照。pg_dump 等鎖上限兩秒，
  來源查詢設 statement／idle transaction timeout。禁止以寫入鎖或停服務換取成功。
- 資料經 `pg_dump → pipe → GPG → 唯一名稱.partial.gpg`；明文僅流經記憶體／pipe。
  不寫入 repo、一般暫存檔、日誌或持久 Docker volume。不啟用 shell tracing。
- 資料摘要只回傳表格筆數、雜湊及結構摘要；明文列值／敏感 SQL 錯誤不輸出。
  本機私有中繼資料記錄必要的 owner／ACL 角色識別、來源 identity、時間、
  schema／extension／sequence 狀態及比對雜湊，不含帳密、列內容或完整 SQL dump。
  不輸出單筆敏感欄位雜湊；repo evidence 只保留整體結果／必要聚合摘要。
- Sequence 非一般資料列快照保證的範圍：前後讀取 sequence／DDL 摘要，
  有變動即標為尚未完成一致性驗收、停止本輪，不宣稱完全一致。
- 選用 GPG symmetric AES-256、強制 Pinentry、停用 symmetric key cache。
  使用該 run 專屬 GPG home／agent，不讀寫 Peter 的既有 keyring／agent 設定。
  不使用 passphrase 引數、環境變數、檔案或 loopback 傳密碼。
- 實際執行由 Peter 在自己的本機 Terminal 啟動經檢查的工具，Pinentry 不回顯
  密碼。現機有終端 Pinentry，未確認 GUI Pinentry，故不承諾 GUI 密碼視窗。
  解密驗證時須再次輸入密碼；代理不控制或擷取密碼提示畫面。
- 建立備份 run 子目錄權限 0700、檔案 0600，不覆寫既有檔案／修改父目錄權限。
  路徑在 repo 外，實際建立時仍須遵守執行環境權限審核，不繞過限制。

### D. 只在無網路、記憶體儲存的 PostgreSQL 還原

- 新容器使用 `--network none`，不 publish port、不 mount Docker socket、
  不 mount 現有 volume／資料／主機 dump。所有 PG data／WAL／暫存檔必須落在
  驗證過的 tmpfs；PostgreSQL 18 的資料目錄及 image VOLUME 都需檢查。
  發現匿名持久 volume 或不符儲存設定，須在導入真實資料前停止並清理。
- 只建立新測試 DB／新憑證。為還原 owner／ACL 而需要的來源角色識別可在隔離
  DB 建為 NOLOGIN、NOSUPERUSER 的角色；不複製其密碼、cluster 權限或登入能力。
  此處不測試應用程式登入／授權，也不改現行角色。
- 若有不支援的 extension、tablespace、外部資料連接或無法忠實還原的物件，
  停止並說明；不跳過物件、開網路、掛現有磁碟或改 live schema 來湊成功。
- 用 `GPG 解密 → pipe → docker exec -i → pg_restore` 還原到唯一 run-owned
  空白 DB，single transaction、exit-on-error。禁止 inherited connection URL，
  操作前核對 container ID／label、DB identity、空白 target 及儲存／網路限制。
- 解密完整性、所有程序 exit code、還原及後續比對都通過才能判定成功。
  比對所有非系統 schema 的表格筆數與資料雜湊、large objects、sequence、
  schema／constraint／index／comment／owner／ACL 及 Flyway V048 歷史。
  不只抽查 project_members，且必須保留原本 Editor+Viewer 資料，不能出現 V049。
- 不啟動 Backend、Worker、Beat、bootstrap、Flyway、OIDC 或其他讀取該副本的
  應用程式。即使備份帶有服務設定或憑證欄位，也不使用它們連線。
- 成功或失敗均清除精確 run-owned 容器及其 tmpfs；核對 ID／label，不做全域
  prune 或刪除既有資源。確認目前 Docker／Kubernetes 保護基線未被工具改動。

### E. 封存與保留

只有解密、還原、比對及隔離清理皆完成，才把 `.partial.gpg` 原子更名為
`.dump.gpg`，記錄 ciphertext SHA-256、大小、來源時間、工具／映像綁定及驗證結果。
不改寫任何既有備份。若失敗，保留加密 partial 並標示 FAILED，不當作可用備份，
也不自行刪除；後續是否重試或移除由 Peter 決定。

停止本 run 專用 GPG agent；只清除已核對的 run-owned 暫存設定及新測試憑證。
不停止既有 agent，不刪除加密備份或 Peter 的密碼。所有清理結果必須有證據。

加密備份至少保留至**後續部署驗收完成後七天**；若部署尚未完成，保留期不開始
倒數。沒有自動刪除、排程或雲端上傳。刪除備份一律需另行核准 exact path。

## 5. 驗收、輸出與風險

測試案例見 TEST_PLAN.md V49-B01..B08；requirement trace 見 TRACEABILITY.md。
核准後先執行 `spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、
`backend:syntax`、`git diff --check` 及新增工具的真實 GPG／PG 安全測試。
工具尚未實作，因此不提供假裝已可執行的 live 備份指令；完成檢查後才交付
精確、已綁定來源與映像、需要 Peter 本機輸入密碼的操作指令。

輸出：私有加密備份／私有安全 manifest、repo 的
`docs/CHG-291-V049-LIVE-BACKUP-RESULT.md` 與 `-EVIDENCE.json`。
PASS 必須同時具備資料／結構比對、密碼重新解密、還原及清理證據；未執行、
取消、資源超限或部分完成不得算 PASS。一般日誌不含原文、密碼或連線字串。

限制與後續界線：

- 本次是不中斷服務的備份與可還原性驗證，不是正式遷移前最後復原點。
  正式 V049 前仍須另訂維護窗口／writer freeze、取得新基線及新備份並驗證。
- 記憶體／tmpfs 降低明文落盤風險，但不能保證 macOS／Docker VM 的主機級
  swap、休眠映像、crash dump 或具有本機管理權者完全無法接觸記憶體。
  這是本機驗證風險，不得宣稱硬體層零殘留或完整 DR。
- 資料庫 owner／ACL 的還原不等於 cluster 密碼／權限及外部服務的完整復原。
  底層加密金鑰、其他 stores 與後續真正還原 live DB 均需另外的復原計畫。
- 本計畫不豁免 whole Backend／Frontend 80% coverage、安全掃描、累積變更
  E2E、候選 image 綁定、Helm dry-run／部署或真實維護備份的後續 gates。

技術依據：PostgreSQL 的 custom-format dump 可配合 pg_restore；指定 snapshot
可讓 dump 與其他查詢使用同一資料視野，但 pg_dump 並非 cluster globals 備份。
參考 [PostgreSQL 18 pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)。
密碼加密／解密、Pinentry 與停用 symmetric cache 的選項依
[GnuPG operations](https://www.gnupg.org/documentation/manuals/gnupg/Operational-GPG-Commands.html)
及 [GnuPG options](https://www.gnupg.org/documentation/manuals/gnupg/GPG-Esoteric-Options.html)。

## 6. 核准範圍

待 Peter 核准：**V049 現行資料加密備份與隔離還原驗證**，包含上述必要工具／
真實自建資料檢查、唯一來源的唯讀匯出、加密檔保存，以及有界限的暫存副本與
精確清理；不含部署、套用 V049、現行資料修改、目前資料庫還原或 Provider 呼叫。
核准後仍須完成工具安全檢查及本機密碼輸入，不能把核准當作驗證成功。

### 本次計畫文件檢查

2026-09-12：`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`test:plan` 與
`git diff --check` 通過。`./HARNESS/harness.sh plan:approved` exit 1，原因為
本計畫 Gate 4 PENDING，符合預期。這些只檢查文件與核准狀態；
V49-B01..B08 全部尚未執行，沒有建立備份目錄、工具或還原容器。

# CHG-291 V049 不加密備份資格驗證結果

2026-09-13。Peter 的 `核准` 已完成 A–E 計畫 Gate 4。
**目前為 PARTIAL / QUALIFICATION BLOCKED，不是備份成功。**

後續狀態：Peter 以「好」確認文末順序調整（R1 Gate 2）；R1 Gate 3 已寫入
原 PLAN.md 上方，Gate 4 PENDING。下列原始數值/報告保持不變，未新增
feature/source 執行或正式備份，也不將 Gate 2 同意視為資格通過。

## 結果

- 最新真實測試：49 passed、0 failed、0 error；原人工 GPG 案例 1 件
  deselected / NOT RUN，不列為通過，也未刪除。
- 整個工具行覆蓋率：692/860 = **80.46511627906976%**。
- 分支覆蓋率：115/156 = **73.71794871794872%**。
- 合併覆蓋率：**79.42913385826772%**，不足 80%；沒有四捨五入當通過、
  沒有 omit/pragma、沒有排除舊 GPG 分母、沒有降低測試門檻。
- 新 CLI 正確回傳 exit 1 / `qualification_coverage_below_80`；沒有產生
  `qualified.json`，沒有執行 `--prepare-source` 或 `--backup-unencrypted`。
- **本次現行 DB 查詢/匯出 0 次；正式 backup 目錄未由本工具建立；沒有可用
  現行備份。沒有 V049、停寫、Helm/Kubernetes write、Job、映像建置/拉取、
  掃描、Provider 或應用資料/index 變更。**
- 各輪只用自建合成 PG；精確自有容器及 tmpfs 已清理，既有 Docker inventory
  比對一致。最終按自有 label 查詢 `docker ps -a` 回傳空集合。
  未重新盤點現行 Kubernetes，因此不宣稱外部環境沒有自行變動。

## 已實作（未取得正式備份驗收）

僅工具 `backend/scripts/chg291_v049_live_backup.py`、對應 real-service tests
及本計畫文件；產品功能、原 V001–V049、應用/config/chart/image 未修改。

| 區域 | 內容 | 證據 / 未完成部分 |
| --- | --- | --- |
| PlainArchive / custody | 私有 0700/0600、ACL/no-follow/no-overwrite、單檔串流、限時/上限、SHA256/fsync、原子封存 | 合成真實檔案正常/失敗測試；正式目錄/資料未操作 |
| Snapshot / DatabaseState | readonly exported snapshot、全表/LO/sequence/結構/owner/ACL 指紋、DDL/sequence 漂移拒絕 | 真實 PG 比對；不偽造 Flyway history，現行 V048 尚未本輪驗證 |
| MemoryPostgres / restore_isolated | 固定本機 image、network none、單一 PG、tmpfs、無 port/host mount、NOLOGIN 還原角色、全量比對 | 真實自建來源匯出後，移除來源，再在全新 PG 還原並比對 |
| cleanup / process limits | 精確 intent/receipt/registry 綁定清理、子程序錯誤/阻塞/中斷、保留失敗 partial | 先檢查全部 registry 再清理；已驗證錯誤輸入不提前移除測試 PG |
| qualification / LiveSource | 來源/測試 SHA 綁定、不可跳過的資格門檻、once-only export claim、來源身分與保護檢查 | 真實 CLI 負向路徑已測；現行 Kubernetes/DB 正向 preflight 與正式匯出 **未執行** |

已修復測試揭露的問題：PostgreSQL boolean JSON 表示不相容、system tablespace
誤計入使用者資料、部分資料庫屬性無法忠實還原時未明確拒絕、原 coverage
rounded/pytest exit code 不足以表示 gate 通過、registry 後段錯誤造成提前
清理，以及 Snapshot 同伴先斷線時 BrokenPipe 使清理再失敗。所有修正都保留
真實失敗報告；未透過假資料庫/假回傳/預設成功取代真實驗證。

## 各輪歷史保留

下列每個 suffix 都位於私有 `/private/tmp/v049-backup-plain-<suffix>/`。
測試使用 synthetic-only 檔案；檔案與失敗 partial 保留，容器已清理。
各輪工具分母不同，不能沿用先前 coverage 或拿舊 PASS 代表新工具。

| Run suffix | 測試 passed / failed | 合併 coverage | 整體資格 |
| --- | --- | --- | --- |
| m4NI0X | 23 / 7 | 69.02017291066282% | FAIL |
| Fz5nIm | 30 / 0 | 79.62697274031564% | FAIL；顯示 rounded 80 不是合格 |
| kstyg614 | 36 / 0 | 70.81967213114754% | FAIL |
| h4nvmjp9 | 39 / 0 | 73.24973876698014% | FAIL |
| jca3ngia | 39 / 2 | 72.15064420218037% | FAIL；registry 清理順序問題 |
| 8zngp2o0 | 41 / 0 | 75.98425196850394% | FAIL；coverage |
| x5pea048 | 47 / 1 | 78.23529411764706% | FAIL；BrokenPipe cleanup |
| 7wejptt4 | 49 / 0 | 79.42913385826772% | FAIL；coverage |

舊加密驗證歷史仍在 `CHG-291-V049-BACKUP-QUALIFICATION.md` 與其 evidence；
不改為 PASS，不使用聊天密碼，也沒有要求人員操作 Pinentry。

## 2026-09-13 R1 最終資格：PASS

Peter 以「一次性依序完成這6項工作」核准執行已寫好的 R1。最終 run
`/private/tmp/v049-backup-plain-ma9flk8v`：55 項真實測試通過、0 failure/error；
人工 GPG 1 項仍明列 NOT RUN。行 81.11545988258317%、分支
80.72289156626506%、合併 81.06060606060606%，沒有排除行或降低門檻。
實際 fixed-source readonly assertions 通過，`qualified.json` 已產生，exit 0。
這是備份工具資格，不是整個產品 coverage 或正式備份／部署驗收。

機器證據：`CHG-291-V049-R1-QUALIFICATION-EVIDENCE.json`。原始行/分支資料與
JUnit、cleanup、synthetic proof、readonly claim/result 全部保留、SHA 綁定；
不把不同版本或失敗來源檢查混入 final coverage。來源仍 revision 36、V048、
1 Project/1 Owner/3 memberships；Secret 以 server-side metadata-only 取得。
合成容器已精確清理，既有 Docker inventory 不變，沒有 Provider 呼叫。

本輪修正：獨立 synthetic prerequisite／最終資格狀態、明確 opt-in readonly
入口、exclusive claim、同源報告驗證，以及不中斷私有證據保存的錯誤處理。
TLS 使用現有 context 認證，PEM 僅經記憶體／匿名 pipe 使用，不存新憑證檔、
不放 argv/log、不啟動 proxy。未讀完整 Secret，未改 RBAC。

保留的中間失敗：2bqhpniw 的 readonly coverage 檔模式過寬（位於0700私有
目錄，未含憑證/文件），錯誤遮住原 HTTP failure；修正 umask 與安全 error code。
ajwzjozv 明確回 HTTP406；查明 list 需 `PartialObjectMetadataList`，不能用
單筆的 `PartialObjectMetadata`。依[官方 API 文件](https://kubernetes.io/docs/reference/using-api/api-concepts/#metadata-only-fetches)
修正 Accept，沒有改成完整 Secret fallback。uaih9jxp 的 readonly 通過，
但 branch 79.51807228915662% 仍 FAIL；補真實未啟動資源清理／重複關閉安全
測試後重跑同源完整流程，才得到最終 PASS。以上失敗沒有覆寫或追認成功。

新增五項安全測試涵蓋預備資格不能匯出、metadata 完整物件拒絕、真實 TLS
記憶體憑證／錯誤清理、真實子程序 bounded JSON、report 檔案保管；再補
一項實際資源生命週期／Docker baseline 比對。原49項受測行為皆保留。
當前未覆盖舊 human-GPG、其他 OS、部分失敗／final orchestration 路徑仍
列在原始 coverage，不隱藏。正式匯出依原 A–E 授權於資格通過後另行執行。

實際 readonly 命令（本 run 已 claim，不能重播）：

```text
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py --qualify-source-readonly --qualification /private/tmp/v049-backup-plain-ma9flk8v --accept-source-readonly
```

## 2026-09-13 第2項：一次 current DB 匯出完成，還原比對 FAILED

工具資格通過後，沿用原 A–E 核准與六項順序指示執行來源 preflight：PASS。
Binding SHA256：`23e4f42aba57cae3894403195e04a35db282782a296b7f22b7d2083f870bf9bc`。
唯一正式來源匯出已執行，沒有重播 claim／第二次匯出。

保留檔案：`/Users/peter/NomoSmartBackups/V049/run-20260913T050023Z-0fab208e7f354a1e/database.partial.dump`。
大小1,213,458 bytes；SHA256
`a1b2395fb8d0778319d18303fbc678f5a06b2551abe34fa8b5a8a453c33b139a`。
目錄0700、檔案0600。`snapshot.json`涵蓋62個關聯資料物件；既有應用加密欄位
保持不透明，沒有輸出dump／文件／對話內容。這份檔案未封存為database.dump。

實際 pg_restore 程序通過，後續完整 `actual == state` 比對失敗，錯誤為
`restored_state_differs`，整個命令exit1。finally執行精確自有容器清理與
Docker baseline核對；若清理失敗會覆蓋錯誤，實際回傳仍為比對失敗。
`failed.json`明列usable_backup=false、partial_retained=true、migration_applied=false。
沒有restore-proof.json或成功result.json，沒有把它当可用復原點。沒有重匯出、
重做這份真實資料還原、現行DB還原、V049、Helm/Kubernetes write或Provider呼叫。
失敗後未執行工具的postflight資源比對，不能把preflight冒充完整postflight PASS。

先用新合成資料診斷，不讀取或重驗上述真實dump。新增真實回歸
`test_extension_owner_is_preserved_by_full_restore`，在不同來源/還原登入的
extension情境，兩輪均重現FAIL。最新純合成run：
`/private/tmp/v049-backup-plain-diagnostic-grRU7Eof`，1 failed／56 deselected。
差異只在schema；properties、roles、tables、sequences、large_objects五類相同。
合成schema diff顯示還原後pg_dump省略原先重新建立的plpgsql之CREATE/COMMENT
段落。這是dump表示／extension情境的具體驗證缺口，**尚不能證明真實備份
失敗也是這個原因，也不能宣稱真實資料損壞或擅自忽略schema差異**。
合成資料容器清理及既有Docker inventory相等通過；沒有碰真實備份內容。

新增回歸使tests source hash改變且測試尚未通過。前述55版本資格作為當時
匯出依據保留，但不適用修改後測試集。需診斷與修復、重驗後才有新資格。
目前依原「失敗即停止」規則停在第2項，3–6尚未執行。下一步需確認是否允許
只使用既有partial，在同等隔離限制下再還原一次，保存不含內容的分類差異；
不重新匯出、不改現行資料，也不以降低比對條件換取PASS。

## 驗證命令

```text
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py --self-test-unencrypted
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
git diff --check
```

最後一輪 feature command exit 1（coverage gate）；文件/語法 harness checks PASS。
未跑全產品 frontend/backend coverage、完整 E2E、掃描或 deploy harness；
本次不改 Docker/Helm/application，不能以本工具測試作全產品 release 驗收。

## 順序調整理解（已確認 Gate 2；R1 計畫待 Gate 4，未實作）

目前順序是「先達到完整工具 coverage → 才能檢查現行來源」，但工具也包含
那些尚未允許執行的來源 preflight 路徑。仍有其他未覆蓋路徑（舊 GPG、
不同 OS、部分 failure/CLI 收尾），不能聲稱唯讀盤點一定足夠通過門檻。

建議只調整資格驗證先後：

1. 保留合成真實測試全部通過、精確清理與 source SHA 綁定作先決條件。
2. 將 **exact-source 唯讀 preflight** 納入資格測試：僅 revision、來源 Pod
   身分/健康、安全 resource metadata、DB identity/Flyway/owner-member
   counts 與可還原性 catalog；不讀出文件/對話內容、不輸出或複製憑證，
   Secret 只允許 metadata 表示。不得建立備份、容器/Job或修改 Kubernetes/DB。
3. 收集該唯讀檢查的真實 coverage/evidence，重新執行完整資格門檻；不降低
   行/分支/合併 80%，不偽造 PASS。未達標仍不匯出。
4. 同一來源與工具資格通過後，才依既有 A–E 範圍執行一次正式不加密備份。

以上 understanding 已由 Peter 以「好」確認；R1 計畫/trace/test contract
已更新供 Gate 4 核准，尚未取得 R1 執行核准。原始失敗 evidence 保留。

仍需另行核准 V049 停寫窗口、最新已驗證備份、exact render/images、遷移與
回退/部署。此工具工作不是已完成 V049，也不是全平台災難復原驗證。

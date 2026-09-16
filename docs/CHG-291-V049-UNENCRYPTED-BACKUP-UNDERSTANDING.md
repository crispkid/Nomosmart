# CHG-291 V049：不加密本機備份的規格理解

日期：2026-09-13。Peter 明確提出「我沒辦法接觸電腦，請改用不加密備份」。
不再要求 Peter 現在使用 Terminal／Pinentry，也不使用對話中曾提供的密碼。

2026-09-13 Peter 以「接受」確認下列明文風險與保管界線，Gate 2 confirmed。
本文件是對既有加密備份計畫的已確認理解，不是執行核准。Gate 3 已整理於
`CHG-291-V049-UNENCRYPTED-BACKUP-PLAN.md`。Peter 隨後以「核准」同意其
A–E 執行範圍（2026-09-13 Gate 4 approved）；未通過資格驗證前仍不匯出。
未執行現行資料匯出、資料庫修改、V049、Helm／Kubernetes 寫入或部署。

## 理解與安全例外

- 僅本次 Docker Desktop V049 備份準備改為不加密的 PostgreSQL custom-format
  邏輯備份；custom-format／壓縮並不是加密。不改變 production 備份政策、
  應用內憑證加密、其他資料庫或平台 Secret 的保管方式。
- 唯一來源仍為 `docker-desktop`／`nomosmart`／`nomosmart-local` 下既有
  `nomosmart-local-postgresql-0` 的 `nomosmart` DB。執行前重新綁定 Pod UID、
  映像、revision 36／V048 與 Owner／member 結構；歷史基線不是目前證明。
- 目的地仍為 `/Users/peter/NomoSmartBackups/V049/` 的唯一 run 子目錄；不放
  repo、一般暫存目錄或雲端同步目錄，不上傳、不建立下載連結、不覆寫舊備份。
  私有目錄 0700、檔案 0600；拒絕 symlink、不安全 owner／ACL 或未知路徑。
  不修改既有父目錄權限以強行通過；實際建立仍受執行環境權限審核。
- 備份可能含個資、文件文字、對話、角色／成員及模型設定。任何取得檔案副本、
  或能以 Peter 帳號／本機管理權限讀取它的人，都不需要備份密碼即可還原並
  讀取其中原本未加密的內容。0600、壓縮及本機路徑不能取代加密，亦不代表
  已確認 FileVault、同步軟體或系統快照的狀態。
- 資料庫內原有加密憑證欄位保持不透明，不解密、不使用、不輸出；不匯出
  `pg_authid` 密碼、Kubernetes Secret、應用加密金鑰或其他 DB。
- 保留原先完整、唯讀、同 snapshot 匯出及全量還原比對要求，不以只備份
  membership 表格替代全 DB。原資源／時間上限、sequence／DDL 漂移停止、
  無網路 tmpfs PostgreSQL 還原與精確自有容器清理限制保持不變。
- 只有匯出、完整性檢查、全量隔離還原比對、清理均通過，才可把唯一 partial
  標成可用備份。SHA-256 用於追蹤及完整性核對，不提供保密性或抵抗有權
  同時修改檔案與 manifest 者的保證。失敗不得當作備份成功。
- 備份／失敗 partial 都是敏感明文，不把它們寫到工具輸出、repo 或一般 log。
  沿用不自動刪除的安排；至少保留至後續部署驗收完成七天，移除仍須 exact-path
  核准。資料在未刪除前持續承擔不加密的風險，不能宣稱工具清理已清除備份。

## 驗收理解

- `V49-U01`：無人為密碼步驟的本機備份；不接收／注入密碼，不另行產生或
  保存加密金鑰，也不假稱有加密。
- `V49-U02`：只在核准的私有位置建立不覆寫、非 symlink、owner-only 檔案，
  不輸出敏感內容；路徑、權限、空間、串流大小、時間或 source identity 不符
  必須停止。失敗 partial 亦受相同保護及保留規則約束。
- `V49-U03`：保留 snapshot／sequence／DDL、完整資料與結構、owner／ACL、
  large objects、Flyway 歷史的還原驗證，不執行還原副本內的應用或 V049。
- `V49-U04`：修改後以真實合成資料及隔離 PostgreSQL 重新測試匯出、還原、
  檔案截斷／竄改、程序失敗、非空目標、權限與精確清理；工具 coverage 80%
  不降低。不把原加密工具 17 PASS／73.47% 或未執行的 GPG 測試當新方案通過。
- `V49-U05`：正式遷移前仍需受控停寫及新鮮復原點；本次在線備份準備不是
  維護窗口的最終備份，也不是 V049／部署、掃描或 Provider 呼叫核准。

## 確認結果

Peter 已接受：本次備份檔不加密，取得檔案者可能讀取其中敏感資料；採上述
私有本機保存與隔離還原限制。不再次詢問相同風險或要求 Peter 操作密碼提示。
原正式環境及其他發布驗收門檻不自動豁免；新版計畫另列執行範圍供 Gate 4。
後續穩定需求 ID `V49-U001..U005` 分別對應本文件的 `V49-U01..U05`。

本次只做規格理解與文件更新。產品、SQL、備份工具及測試程式均未更動；
沒有建立備份目錄、還原容器，沒有查詢現行 DB 或使用對話中的密碼。

前次理解階段的歷史文件檢查：`spec:doctor`、`spec:trace`、`plan:approved`、`git diff --check`
通過。Harness 的 active change 仍是 CHG-300，`plan:approved` 只驗證它的
既有核准，不代表本次不加密例外已核准。TEST_PLAN.md／TRACEABILITY.md
既有狀態不改成 PASS；本例外確認後才更新其計畫與對應測試／trace。
本次「接受」後已更新上述文件；active change 為 CHG-291，新的
`plan:approved` 因 Gate 4 待核准而 exit 1，詳見修訂計畫的本輪文件驗證。

參照：SPECIFICATION.md §10.57 MIGSAFE-001、MIGRATE-001、DEPLOY-004/006、
[原核准計畫](CHG-291-V049-LIVE-BACKUP-PLAN.md)、
[現有工具驗證結果](CHG-291-V049-BACKUP-QUALIFICATION.md)。

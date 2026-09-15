# V049 加密備份工具資格驗證：需本機 Pinentry

2026-09-13，依已核准 CHG-291 整合準備階段 C／加密備份計畫繼續。
Peter 已確認 V049 先於應用更新，並明確要求不掃描。

**本輪不是現行資料已備份或可部署的證明。** 新工具目前只提供合成資料
自測及 exact-receipt 清理；刻意沒有現行匯出／還原／Migration／部署入口。
產品程式、SQL、角色、API 及映像未更動。

## 結果

- 最終非互動執行：17 passed、0 failed/error；1 個需要人為 Pinentry 的測試
  未選入此次子集，不是 skip/xfail 或 PASS。
- 工具 statement＋branch coverage **73.47%**，低於80%；命令 exit 1。
  沒有降低門檻或排除程式碼；完整人為測試後仍須重新確認門檻。
- 真實 PostgreSQL：唯讀 exported snapshot、custom-format pg_dump 串流→
  pg_restore single transaction、資料／constraint／註解／large object 比對。
- 同時插入時，rows遵循 snapshot，但 sequence會前進；測試刻意檢出此差異。
  未來 live 匯出需檢查並拒絕漂移，不能宣稱在線備份的sequence天然一致。
- 真實子程序：兩端失敗、空串流、超限、逾時、忽略 SIGTERM、SQL失敗、非空
  目標、非自有DB、symlink／覆寫及偽造清理紀錄拒絕。清理後Docker基線相同。
- 一個固定PG映像，無網路／port，2 CPU／4GiB，PG tmpfs 2GiB；無host／既有
  volume，log driver=none、core dump disabled。空tmpfs隔離其應用初始化目錄，
  避免執行 NomoSmart／Keycloak provisioning；仍用真正PG initializer/dump/restore。
- GPG2.5.21及所需選項存在；**加密／解密／人為取消尚未執行**。

## 請 Peter 在自己的 Terminal 執行

這不是再次核准，而是密碼必須由你自己輸入。請用測試密碼，不用現行帳號密碼，
也不要把任何密碼貼到對話。

```sh
/Users/peter/Documents/GitHub/Nomosmart/backend/.venv/bin/python -B \
  /Users/peter/Documents/GitHub/Nomosmart/backend/scripts/chg291_v049_live_backup.py --self-test
```

程式會提示四階段：設定測試密碼加密、再次輸入解密還原、輸入相同密碼測試
截斷密文必須失敗、最後在下一個 Pinentry 按「取消」。不用代理代填。
使用私有GPG home／agent、AES256、Pinentry ask、停用密碼cache；不讀既有
keyring，不用passphrase引數／env／檔案／loopback；明文dump只過pipe。

成功或失敗都清理自建資料庫及該agent；合成資料密文與報告保留在畫面顯示的
`/private/tmp/v049-backup-qualification-*` 私有目錄。完整測試與80%工具coverage
皆通過才算qualification PASS；目前沒有此結果。

請勿直接關閉終端。Ctrl-C會先嘗試清理；若程序被強制結束，保留該次報告目錄，
可用相同程式的 `--cleanup-test <該次完整目錄>` 回收receipt綁定的容器／agent。
它不刪加密檔、不接受廣泛目錄、不操作現行服務。

## 歷史失敗與界線

第一輪PG未就緒：映像應用初始化需要憑證，沙箱不應借用現行憑證，故改用
空tmpfs隔離該目錄。第二／三輪為測試SQL把sequence直接當composite row，
改為先選出真實last_value/is_called再比對。這是新工具／測試問題，不是MAAS
產品故障。各輪XML、coverage與清理證據保留，不覆寫或把失敗改列PASS。
後續加入清理與失敗路徑使coverage分母增加；比例下降不代表門檻降低。

下一步仍須完成：人為GPG測試、live匯出／全庫摘要／owner-ACL／封存入口與安全
驗證，才可執行現行資料備份。V49-B01..B08、真實備份／還原、維護窗口復原點、
V049及應用rollout皆尚未完成；全產品coverage／E2E缺口仍保留。

規格：MIGRATE-001、DEPLOY-004、TEST-002；[核准計畫](CHG-291-V049-LIVE-BACKUP-PLAN.md)。
技術依據：[PostgreSQL pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)、
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)、
[GnuPG Pinentry/cache](https://www.gnupg.org/documentation/manuals/gnupg/GPG-Esoteric-Options.html)。

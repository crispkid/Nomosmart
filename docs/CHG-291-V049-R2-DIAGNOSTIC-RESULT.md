# CHG-291 R2 既有備份一次性重驗結果

2026-09-13。Peter 在書面 R2 計畫後以 `Ok` 核准 Gate 4。
需求：SPECIFICATION.md §10.57 `V49-U007`；本輪範圍已執行完畢，
**診斷結果 DIFFERENT，備份仍未合格，未部署**。

## 白話結論

1. 同一份保留備份已成功完成一次 pg_restore；不是還原程式執行失敗。
2. 62 張資料表、1,341 筆資料的完整內容比對一致，不只比筆數。
3. 差異在 schema 匯出文字。備份內重建的 schema 有 11 個 COMMENT 區塊，
   還原後 pg_dump 有 12 個。其他已分類物件數相同。
4. 本次兩邊 CREATE EXTENSION 均只有 pgcrypto，沒有先前純合成案例的
   plpgsql CREATE 區塊差異。不能套用那個案例作為真實備份的根因。
5. 多一個 COMMENT 是線索，不是唯一根因或「無害」的證明；不能據此忽略
   schema 檢查、放寬權限或把備份改判合格。

## 六類完整比較

| 類別 | 結果 | 證據範圍 |
| --- | --- | --- |
| Database properties | 一致 | 既有完整 properties、DB owner／ACL 契約 |
| Referenced roles | 一致 | 既有參照角色集合；不是所有叢集角色屬性的完整 DR |
| Schema | 不一致 | 原匯出 snapshot 的 schema hash 與還原後 schema hash 不同 |
| Tables | 一致 | 62 表、1,341 列；完整表格 multiset SHA 比對，未輸出列內容 |
| Sequences | 一致 | 0 個 |
| Large objects | 一致 | 0 個；metadata／data 比較仍執行 |

schema 進一步診斷只在記憶體讀取既有 archive 重建 SQL 與隔離 DB 的 SQL，
未執行重建 SQL、未保存完整 SQL／comments／function bodies。
archive 重建文字不等同原始 pg_dump schema 表示，不能用其字面差異宣告
等價或損壞。安全摘要中 SCHEMA=1、EXTENSION=1、TABLE=62、CONSTRAINT=91、
INDEX=77、FK CONSTRAINT=185、DEFAULT ACL=2 均相同；COMMENT=11／12。
還原後 pgcrypto 與 plpgsql owner 均為隔離帳號 backup_verify，但原 snapshot
沒有獨立的 extension-owner baseline，**不能證明原 extension owner 相同**。

本輪不能回答多出的 COMMENT 究竟屬於哪個物件、其內容是否相同，或是否
還有同樣物件數下的其他定義差異。完整文字未持久化，隔離容器已清理；
不為追查此細節重播唯一授權的還原。

## 實作與測試

- `backend/scripts/chg291_v049_live_backup.py`：BoundInput 真正 O_RDONLY／
  O_NOFOLLOW 輸入；RetainedInputs 四檔綁定與 exclusive claim；
  diagnostic_comparison 六類結果；diagnostic_schema 只讀、安全結構摘要；
  diagnose_retained 先保存比較、再清理；固定參數 CLI。
- `backend/tests/test_chg291_v049_live_backup.py`：新增七個實際測試執行案例，
  包含 mode／ACL／symlink／hardlink／inode／hash／readonly、CLI 邊界、
  敏感文字不回顯，以及真正 PG 的 MATCH／DIFFERENT／ERROR 與 once-only 清理。
- Snapshot 支援共用 deadline；read_process 支援既有 readonly FD stdin，
  不更動正式匯出或還原語意、不移除任何比對類別。
- 無產品 API、資料模型、Migration、image、Helm 或應用行為變更。

同源最終隔離測試 run：`/private/tmp/v049-backup-plain-r2-A56GONwx`。
**62 passed、1 failed、1 human-GPG deselected、0 setup errors**。
新增 7 項全通過；原 T15 `test_extension_owner_is_preserved_by_full_restore`
仍為真實 FAIL，沒有刪除、skip、xfail 或轉為 PASS。

| 自動 coverage 範圍 | Statements | Branches | Combined |
| --- | ---: | ---: | ---: |
| 新診斷 classes/functions 與新增 CLI 分支 | 143/152，94.08% | 14/16，87.50% | 93.45% |
| 共用安全／還原／清理邏輯 | 360/368，97.83% | 61/68，89.71% | 96.56% |
| 整個備份工具 | 892/1177，75.79% | 141/182，77.47% | 76.01% |

coverage 由真實 coverage.py 資料及 AST function／新增 CLI 範圍交集计算；
原始完整報告與未覆蓋路徑保留，excluded lines=0。R2 安全門檻通過不等於
完整工具資格；原全套／行分支各80%資格門檻仍未關閉。未呼叫現行來源
補 coverage，未沿用不同原始碼的舊 PASS。
初輪 `VCtKCeoQ` 為61 passed／原T15 failed；補上不可信 schema 標頭
不回顯的 guard/test 後，使用上列新 run 重新驗證，原證據均保留。

執行命令（測試使用唯一私有 `V49_BACKUP_ARTIFACTS`、`COVERAGE_FILE`）：

```text
backend/.venv/bin/python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' -m pytest -c /dev/null -q -s -p no:cacheprovider backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' --junitxml=<private-run>/tests.xml
```

安全報告、source/test/image SHA 與 coverage 門檻驗證後，真實 CLI **僅執行一次**：

```text
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py --diagnose-retained-archive --accept-retained-diagnostic
```

exit 1，`retained_diagnostic_not_match`；它忠實代表 DIFFERENT，不是成功備份。
不得重跑此命令；exclusive claim 已消耗且保留。

`spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、`backend:syntax`、
`git diff --check` 通過。測試與真實診斷的 exact-owned 清理／Docker baseline
核對均通過；最後另做一次唯讀收尾確認，未再次建立容器或還原。

## 保護與留存

真實私有結果位於原備份目錄的 `r2-diagnostic/`；四個原輸入的 SHA／大小／
inode／mode／owner／ACL 前後核對一致，原 FAILED 與 partial 未改名或覆寫。
一次全新無網路 tmpfs PG，固定已安裝映像、資源上限、共用時限；已清理。
未重新匯出、未讀現行 Kubernetes／DB、未建立 Job、未套用 V049、未部署、
未改 indexes／memberships／角色、未呼叫 Provider、未掃描或讀取對話密碼。
沒有 qualified.json、成功 backup result 或 restore-proof 被建立在真實目錄。

## 下一步建議（本輪未執行）

根據這次證據，應先設計可精確區分「物件定義、註解、extension owner／ACL」
的結構診斷與還原驗證，保留 schema 完整性要求，不是直接忽略 COMMENT 或
只比資料筆數。原 snapshot 只有 schema hash，無法離線推出哪個物件不同；
任何追加真實來源盤點／重新還原／新備份仍需界定範圍並核准。
確認根因後才修還原或比較流程、重跑完整資格；六項部署工作仍停在第2項。

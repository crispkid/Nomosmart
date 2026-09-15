# V049 成員權限唯讀盤點

盤點時間：2026-09-12 19:27:36（Asia/Taipei）。
Peter 在討論「列出修改前後名單、正常重複角色保留較高角色、Owner 矛盾先交由人工確認」
後回覆 `Ok`。本次只執行唯讀查詢，未執行 Migration 或資料修補。

## 現況與預計變更

docker-desktop / nomosmart / nomosmart-local 仍為 revision36、deployed。
資料庫目前 Flyway V048；V049 history=0、V049 audit=0，新的 unique constraint 尚不存在。

| 專案 | 使用者 | 目前 Project roles | V049 預計保留 | 預計調整 |
| --- | --- | --- | --- | --- |
| MAAS | user01@nomosmart.test（Peter Chu） | Owner | Owner | 不變 |
| MAAS | user02@nomosmart.test（Justin Wu） | 編輯者＋檢視者 | 編輯者 | 移除多餘檢視者紀錄1筆 |

共1個專案、2名不同成員、3筆 membership。V049 的資料整理預計變為2筆 membership，
不是刪除使用者帳號，也不是把 user02 移出專案。

- Owner governance 與 membership 都指向 user01，矛盾配對0。
- 無法證明有Owner的專案0；停用Owner0；非法角色列0。
- 預計新增Owner membership=0，新增Owner governance=0。
- 預計刪除較低角色列=1，精確目標為 MAAS/user02/viewer。
- 隨V049還會新增 `(project_id,user_id)` unique constraint、constraint comment、
  migration audit 1筆，以及Flyway執行時的history紀錄；均未執行。

依此快照，未發現需先人工裁決的Owner矛盾，也沒有證據顯示須為這份資料改寫V049。
這不是完整migration、混合版本、鎖定時間、備份還原或回退相容性驗收。
真正執行前必須重取資料快照並停止於任何差異，不能把本次名單永久當作固定基線。

## 方式與安全邊界

查詢腳本：`CHG-291-V049-READONLY-INVENTORY.sql`。
用 PostgreSQL Pod 原有 POSTGRES_USER/NOMOSMART_DB 設定，執行
`BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`，statement_timeout=10s、lock_timeout=2s。
伺服器回報 transaction_read_only=on、transaction_isolation=repeatable read。
只SELECT必要成員識別、角色、Owner一致性、schema與migration紀錄；未讀取或輸出憑證。
完整計數不截斷；成員明細最多200筆，本次只有2筆，無遺漏。

```sh
kubectl --context docker-desktop -n nomosmart exec -i \
  nomosmart-local-postgresql-0 -c postgresql -- /bin/sh -c \
  'exec psql -X --no-password --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align --username "$POSTGRES_USER" --dbname "$NOMOSMART_DB"' \
  < docs/CHG-291-V049-READONLY-INVENTORY.sql
```

除本地盤點文件外，沒有SQL寫入、DDL、備份、Job建立、映像建置、Helm write、
Kubernetes resource mutation、角色/成員變更、Provider呼叫或文件/索引操作。
證據與V049/查詢腳本SHA-256：`CHG-291-V049-READONLY-INVENTORY-EVIDENCE.json`。

## 後續討論

V049的角色保留規則不需重訂。接下來應界定備份與還原驗證、現行CHG-292/候選映像
對V049的相容性、維護窗口與新核准範圍。不得把Helm回退當作資料回復；
亦不得憑這次唯讀結果直接套用V049、備份或恢復現行資料庫。

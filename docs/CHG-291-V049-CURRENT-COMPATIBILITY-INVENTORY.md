# CHG-291 現行備份相容性唯讀盤點

2026-09-13。Peter在「可否核准下一步現行環境唯讀備份相容性盤點？
不匯出、不改資料、不部署」後回覆`Ok`，授權本次唯讀診斷。
這不是新的功能實作／feature test／備份／部署Gate4，也不擴張R4合成還原入口。

## 本次操作界線

- 僅docker-desktop / nomosmart / nomosmart-local及既有PostgreSQL Pod內的nomosmart DB。
- 先核對revision36/deployed、PG Pod UID、image與Ready；漂移即停止，不擅自修復。
- 使用既有Pod本地驗證，不讀出密碼、Secret body、角色密碼或聊天提供的密碼。
- READ ONLY / REPEATABLE READ；SQL 10s、lock 2s、總deadline300s、metadata每次4MiB。
- 讀取PG版本、migration版本／必要baseline counts、database properties、catalog
  definitions的server-side hashes、extension versions/owners/members及初始ACL。
- 使用既有SchemaEvidence.collect與RestoreIdentityProfile.select做唯讀相容性
  判定，並讀取固定既有Docker image的ID作比對，不建立或啟動容器。
- 不使用DatabaseState.collect/schema_hash、pg_dump/pg_restore、備份／restore入口、
  資格CLI、現行資料內容／全表hash、舊archive或claim；不產生qualified.json。
- 操作前後核對來源身分、catalog及必要baseline，結果僅代表這次快照相容性，
  不是已完成實際備份還原或完整發布資格。
- 詳細metadata留於新private temp目錄0700／0600；repo只記分類、數量與hash。
  程式／測試沿用R4來源SHA，產品、schema、權限、索引、Job、Helm、Provider均不動。

## 結果

**唯讀盤點完成；現行來源不符合R4「單一擁有者」限制。不是現行資料損壞，
也不是已完成備份／部署資格。**

時間：2026-09-13 15:19（Asia/Taipei）。私有目錄：
`/private/tmp/v049-current-compatibility-7ydlQKjw`。

### 已確認

- Helm revision36、deployed；PostgreSQL Pod Running/Ready，來源Pod UID前後相同。
- PG18.4（180004），runtime image digest與R4固定還原image完全相同。
- 最新Flyway V048成功，V049紀錄0、failed migration0；1個專案、1筆Owner、
  3筆membership符合既有必要基線。未更改成員／角色或套用V049。
- DB約15.89MiB（16,660,159 bytes），低於工具256MiB限制。
- catalog collector為complete，未覆蓋物件0。共有pgcrypto1.4/public、
  plpgsql1.0/pg_catalog；版本、schema與member identity digest皆吻合R4支援範圍。
- 兩次完整catalog／properties／profile／必要baseline與來源身分相同；
  另一次trusted/owner旗標補查後catalog及來源身分仍相同。
- SQL回報`transaction_read_only=on`、`repeatable read`；未執行pg_dump、
  pg_restore、全表資料hash、app內容讀取、Secret body、角色密碼或資料修改。

以上不是全應用健康檢查或所有application rows完全未變的雜湊證明；本輪未做
那些讀取，不能將metadata穩定延伸成完整發布驗收。

### 關鍵差異：混合擁有者

為避免在repo記錄不必要的帳號，以下以A/B表示；實際識別與catalog留在私有證據。

| 物件 | 套件擁有者 | 內部物件擁有者 |
| --- | --- | --- |
| pgcrypto 1.4 | A：資料庫擁有者，非SUPERUSER，具DB CREATE權限 | B：PG管理帳號；37個函式全部屬於B |
| plpgsql 1.0 | B | 3個函式與1個language全部屬於B |

`pg_available_extension_versions`確認pgcrypto為trusted。PostgreSQL允許具有
DB CREATE權限的非superuser安裝trusted extension：套件由呼叫帳號擁有，
內部物件可由bootstrap superuser擁有。現行A/B分工符合此規則；不能反推當時
實際安裝命令，但不是僅因owner不同就判為錯誤或需要提升A權限。
[PostgreSQL 18 CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html)。

R4 `RestoreIdentityProfile.select`回報`restore_profile_mixed_owners`，因此
**正確拒絕超出其支援範圍的來源**。上一輪的133 PASS證明已涵蓋情境，
不代表已涵蓋這個現行mixed-owner情境；R4報告也明列此限制。

pg_dump不逐一輸出extension member的建立內容，主要透過CREATE EXTENSION
重建，因此只把一般資料表owner還原，或把所有套件都交給同一帳號建立，
不能保證A/B分工忠實保留。
[PostgreSQL extension packaging](https://www.postgresql.org/docs/18/extend-extensions.html)。

### 舊備份與下一步

這次只看現行catalog，**沒有讀取／重播R2舊archive**。新發現不能據此宣稱
已證明舊archive schema hash差異的唯一原因，也沒有讓舊FAILED變為可用備份。

建議下一個討論範圍：只修正隔離還原工具，使其可忠實保留此受限的trusted
mixed-owner模式；保留現行A/B owner與權限，不修改現行資料庫、不提升應用
帳號為SUPERUSER、不略過owner/ACL/raw schema比較。

在具體實作前仍需確認擴充的策略及計畫：extension安裝帳號與唯一bootstrap
分開、來源同snapshot證據、trusted/version/member allowlist、目標端最小權限、
完整archive／初始extension協調與失敗清理。不能直接把R4的單一owner檢查
刪掉，也不能直接將新的合成入口用於現行匯出。

本次只完成唯讀診斷與上述理解，不撰寫新開發計畫、不實作新還原策略、不做
新備份或部署。真正新備份、隔離還原、current-source完整qualification及後續
發布驗收仍各需其證據與相應授權；部署前保持停下確認的界線。

## 驗證及追溯

規格依據：§10.57 `V49-U006`（有界現行唯讀）、`V49-U008`（catalog證據）、
`V49-U009`（R4支援範圍及mixed owners拒絕）。產品規格／程式／測試不變，
本次`Ok`只授權唯讀盤點，不是mixed-owner實作核准。

執行命令：

```text
backend/.venv/bin/python -B /private/tmp/v049-current-compatibility-7ydlQKjw/inventory.py
backend/.venv/bin/python -B /private/tmp/v049-current-compatibility-7ydlQKjw/owner-facts.py
```

兩者exit0，僅metadata查詢與本機private報告。source/tool/test hashes與R4
證據一致；未啟動測試容器、未跑feature tests或將本次盤點計入coverage。
詳細摘要及私有報告hash見同名`-EVIDENCE.json`。
文件檢查`./HARNESS/harness.sh spec:doctor`、`spec:trace`與`git diff --check`
均PASS；這些不是新mixed-owner策略的實作核准或功能驗收。

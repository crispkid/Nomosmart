# CHG-291 R4 隔離還原修正結果

2026-09-13。Peter後續`Ok`核准書面R4 Gate4。規格：§10.57
`V49-U009`，沿用`V49-U003/U008`完整比較及`V49-U004`覆蓋率要求。

## 結論

**隔離修正與本輪驗證完成；不是現行備份合格或部署完成。**

- 完整pytest：133 PASS、0 FAIL、0 ERROR、0 SKIP；另1項human-GPG未選取，
  沿用核准的unencrypted測試範圍，不宣稱加密流程已重驗。
- 原T15保留成功斷言`actual == state`，現在六類全相等、raw schema全相等、
  catalog `EQUAL`、0個差異。R3的43個owner／41個ACL差異真正消失。
- 新39項R4案例；加原T15及原fresh-default案例的窄測試共41 PASS。
- Docker測試前後完整inventory一致、0個owned PG剩餘；只清除本次合成tmpfs
  容器，合成資料可由測試重建，私有報告保留。
- 沒有存取現行Kubernetes／資料庫、重播R2 archive、重新匯出現行資料、
  image build/pull、掃描、Provider、V049或部署。

## 根因與修正

原T15在source以不同owner重建plpgsql／pgcrypto，但restore一律由
`backup_verify`初始化。extension內部物件不會由pg_dump逐一重建，故只建普通
NOLOGIN角色或ALTER一般table owner，不能保留extension member owner及ACL。

新流程只由`export_synthetic_database`明確啟用：

1. 同snapshot收集原SchemaEvidence與新的`pg18-restore-identity-v1`。
2. 綁定archive、snapshot、tool/test hashes、固定image及sidecar inode/digest。
3. 驗證受支援extension與member只有單一初始化owner；不得從DB owner猜測。
4. source精確清除後，以該名稱建立fresh target的唯一bootstrap；不新增第二個
   SUPERUSER，不複製來源LOGIN、密碼或其他高權限。其他來源角色維持受限。
5. 完整TOC確認archive明確要重建plpgsql時，僅在新空白DB執行
   `DROP EXTENSION plpgsql RESTRICT`。default plpgsql不在TOC時保留初始化物件。
6. 原完整archive單一transaction還原，原六類/raw hash/catalog嚴格比對，
   前後profile/custody/source binding驗證及exact cleanup。

不使用CASCADE、archive filter/reorder、no-owner/no-acl/no-comments，
不修改dump、系統catalog或為了hash一致而補COMMENT。

## 變更範圍

| 檔案／模組 | 用途 |
| --- | --- |
| backend/scripts/chg291_v049_live_backup.py / RestoreIdentityProfile | 同源profile收集、固定image支援範圍、身分選擇、custody、完整TOC與RESTRICT初始化 |
| 同檔 / MemoryPostgres | bootstrap參數貫穿intent/receipt/guard/commands/cleanup；同時最多一個owned PG；真實初始built-in角色清單，非任意pg_字首 |
| 同檔 / export_synthetic_database、export_database、verify_restore、restore_isolated | 顯式合成入口、source drift及profile前後binding；legacy/current/R2不自動啟用 |
| 同檔 / DatabaseState.provision_restore | 精確角色碰撞檢查，非bootstrap維持NOLOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS |
| backend/tests/test_chg291_v049_live_backup.py | 保留原T15情境與正向斷言，移至共享PG清理後；39項新負向/真實roundtrip/cleanup案例 |
| spec/change/plan/test/trace/六項進度帳、R4 plan/result/evidence | 核准、決策、驗收及未完成事項可追溯 |

原`snapshot.json`六欄與R3`schema-evidence-v1.json`契約未改；新profile為獨立
sidecar，不為舊證據補造欄位。未改產品API、app DB/schema、部署或應用程式。

## 驗證、覆蓋率與證據

最終同源run：`/private/tmp/v049-backup-plain-r4-rdz0MHgj`。
來源及各報告SHA-256見`CHG-291-V049-R4-EVIDENCE.json`。

| 量測 | Statements | Branches | Combined |
| --- | --- | --- | --- |
| 原完整pytest＋R4（133 PASS） | 1098/1383 = 79.39% | 170/212 = 80.19% | 79.50% |
| 再合併真實報告資格防護驗證 | 1110/1383 = 80.26% | 171/212 = 80.66% | 80.31% |

pytest-only不足80%的原報告保留，沒有改數字。補驗使用**這次真實產生且來源
一致的133項XML、coverage、cleanup與工具hash**：`synthetic_reports`正確讀取，
`qualification_reports`確實拒絕原不足80%的結果；報告前後hash不變，
沒有生成qualified.json。不是假造通過的XML/coverage或使用mock。
量測檔分開保留，再用coverage工具`combine --keep`合併，沒有刪分母或加exclude。
最後以真正合併totals呼叫既有`coverage_gate`，三門檻PASS。
這不是應用程式全套coverage，也不替代current-source readonly qualification。

R4 profile＋integration局部敘述149/150（99.33%）、分支22/24（91.67%）；
僅作診斷，不作whole-tool門檻替代。

命令（各harness命令獨立執行）：

```text
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
git diff --check
```

以上PASS。真實服務回歸：

```text
V49_BACKUP_ARTIFACTS=<fresh private r4 directory>
COVERAGE_FILE=<directory>/.coverage.tests
python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' \
  -m pytest -c /dev/null -q -s -p no:cacheprovider \
  backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' \
  --junitxml=<directory>/tests.xml
python -B -m coverage json -o <directory>/coverage.json
```

Python使用`backend/.venv/bin/python`。補驗檔`verify-report-guards.py`及其SHA
保留在最終私有run；以另一`.coverage.report-validation`量測，與`.coverage.tests`
合併成`.coverage.combined`，產生`coverage-combined.json`。
不得對任意新/舊目錄直接執行補驗或把來源不同的測量合併。

`V49-U-T28..T33`覆蓋profile完整性/版本/未知member/mixed owner、custody、
default與nondefault fresh restore、原T15、危險名稱、真實runtime身分、角色
碰撞與受限屬性、RESTRICT依賴拒絕、真實中斷回收、單容器限制、來源和報告防護。

早期探索失敗保留：fD1JVAEj為34 PASS/4 FAIL，原因是pgcrypto版本誤假設1.3
（固定image實際1.4）、default plpgsql沒有該initial ACL測試預期資料、
以及特殊字元bootstrap在該image無法初始化。已改用真實存在的initial ACL
情境及明確name拒絕規則，不將原T15改為expected failure。
後續窄run uiRBHbIL為41 PASS；最終結果以rdz0MHgj及其來源hash為準。

## 限制與下一個權限界線

- 此版只支援固定image下plpgsql1.0/pg_catalog及pgcrypto1.4/public的已驗證
  member inventory、單一owner及ASCII identifier bootstrap。其他版本/schema/
  members/mixed owner拒絕；不得默默改映射。
- member inventory digest只是拒絕未知支援範圍的防護；定義、ACL、initial
  privileges、comment、資料與raw schema仍完整比較。改過extension內部定義
  但無法忠實還原者仍FAIL。
- R2真實archive的schema差異**仍未證明與T15相同**；舊claim/FAILED不變，
  不因本次成功就把舊備份標為可用，也不重播已消耗的單次重驗。
- 現行backup qualification尚缺current-source限定檢查/實際合格新備份；
  完整應用驗收、fresh protected baseline/維護窗口/dry-run/hash與精確部署
  仍未完成。六項進度帳不把它們誤標完成。
- R4明確排除現行服務/新實際匯出；進入這些操作前須界定並取得新範圍授權，
  並遵守使用者要求在真正部署前停下確認。

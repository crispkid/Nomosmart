# CHG-291 R6 註解保存與隔離還原結果

2026-09-13。Peter以`Ok`核准R6書面計畫，按§10.57 `V49-U011`執行。
**本輪隔離修復與測試PASS；不代表現行備份、全應用驗收或部署已完成。**

## 結果

- 原兩個R5失敗場景已通過；只接上顯式新模式，原來源內容與完整成功斷言
  保留，沒有刪除/xfail/放寬比對。六類、raw schema hash及逐物件catalog全等。
- 全套 **212 PASS、0 FAIL、0 ERROR、0 SKIP**；原168例與新R6 44例全部通過。
  1個human-GPG測試按既有未加密/非互動範圍deselected，不冒稱已執行。
- Whole-tool pytest-only coverage：statements1350/1635=**82.5688%**，
  branches198/240=**82.5%**，combined1548/1875=**82.56%**。excluded0；
  沒有舊coverage合併、手動補分母或report補驗coverage灌入。
- 獨立post-test audit確認source SHA、原始報告私有0600、完整還原比較、
  真實取消/rollback證據、Docker final inventory等於開始，**零owned PG**。
- 所有本run隔離容器已精確清理；合成archive與原始報告保留於私有run。
  未讀寫現行資料、未新備份、未讀取/重播R2 archive、未qualified.json、
  未build/pull/scan/Job/Helm/V049/Provider/部署。

## 根因與修正

R5已證實一般dump不含extension member自訂comment，原catalog比較正確
回報不同；hash不能重建正文。本次不動archive或縮減檢查，新增獨立的
同snapshot註解正文證據，只有經完整身分比對的隔離target可補回註解。
原R5失敗及初步PG來源分析保持於[R5結果](CHG-291-V049-R5-RESULT.md)。

| 檔案 / 區域 | 目的 |
| --- | --- |
| backend/scripts/chg291_v049_live_backup.py — ExtensionMemberComments | collect/validate/bind/read固定41個member的typed identity、正文/state/hash；來源/版本/role/profile/custody有界驗證；正文僅私有sidecar |
| 同檔 — target_sql、begin_write、apply_rows、precheck、replay | schema-qualified識別/安全字串；完整archive後只允許bound member comment差異；transaction內COMMENT及commit前驗證，最後仍重新完整比較 |
| 同檔 — PlainArchive / MemoryPostgres | 獨立export-time正文sidecar綁定；已完成完整restore的run-owned target一次性授權，不重用失敗目標 |
| 同檔 — export_synthetic_database/export_database/verify_restore/restore_isolated | 顯式member_comments模式需mixed_identity且限定新R6合成來源；舊v1/v2/SchemaEvidence/預設入口不自動切換 |
| 同檔 — MixedRestoreIdentityProfile.prepare | 增加安全的transaction-local application_name，供精確識別該run安裝階段；無owner/ACL/資料或初始化策略變更 |
| backend/tests/test_chg291_v049_live_backup.py | 44個新真實PG/檔案/程序案例，原兩場景僅顯式新模式，所有舊測試保留 |
| 規格、changelog、plan、test、trace、六步進度與本報告/JSON | V49-U011至T41..T47、來源、原始證據及剩餘發布界線 |

資料契約：新增私有`extension-member-comments-v1.json`（非應用資料表），
內含41筆完整member集合（pgcrypto37函式、plpgsql3函式+1language）及
source/run/image/tool/test/archive/snapshot/catalog/profile綁定。UTF-8單筆64KiB、
合計正文1MiB、metadata4MiB上限；不截斷正文。原schema/SQL/API/index/Helm
沒有改動，不需為這次工具修復重建應用索引或執行migration。

## 測試對應

| Case | 實際驗證 |
| --- | --- |
| T41 | 真實PG預設/移除註解、Unicode、單筆64KiB邊界/超限、合計超限、完整41筆與catalog一致 |
| T42 | 原R5兩個comment場景、一般baseline、plpgsql keep/recreate、table/sequence/large-object/ACL/六類/raw/catalog與原T15/default |
| T43 | overload識別、language/default/NULL、換行/引號/反斜線與包含SQL字樣的純文字完整往返，原資料仍一致 |
| T44 | 實際missing/replacement/mode/hardlink/symlink/body/version/source/identity/profile綁定修改拒絕，建立target前攔截；原來源drift與v1/v2 guards保留 |
| T45 | 真實owner/ACL/definition/額外table/外層註解/identity差異拒絕；舊mode讀同archive仍回報catalog不同，不自動補註解 |
| T46 | 同production transaction primitive的SQL錯誤、10秒statement timeout、2秒lock timeout後原catalog一致；完整流程內安裝及COMMENT實際write-XID交易被取消後rollback、target不可重用，R5 T39缺口補齊 |
| T47 | 全套212PASS、三種whole80%達標、來源與報告綁定/私有custody、exact cleanup與Docker基線相等 |

SQL錯誤/timeout使用真實隔離PG與正式begin/apply primitive，不捏造成功；
中途取消另以完整restore流程驗證。觀察連線在同lab的另一個owned DB，只
對已識別階段、已取得write XID的同一target PID取消，不停用pristine/role/
external-client guards。取消後實查沒有部分註解提交、沒有半成品重試。

## 保留的執行輪次

| run後綴 | 結果 | 說明 |
| --- | --- | --- |
| b2cLZ6 | 原2案例PASS | 初步註解修復；不是完整coverage證據 |
| SY02Jc | 44PASS/1FAIL | 第一次取消observer僅發單次訊號，落在idle空檔，未真的中斷；預期錯誤沒發生，測試如實FAIL |
| QOlYst | 2PASS | 修正observer只觀察active write transaction、對同PID有界重複取消；安裝/COMMENT中途取消皆真實通過 |
| y8GMvd | 212PASS | 最終同源全套，1 human-GPG deselected |

所有目錄均為`/private/tmp/v049-backup-plain-r6-<後綴>`。沒有修改SY02Jc
FAIL結果；observer修正不放寬斷言，也未修改還原成功標準。

最終run始於**2026-09-13T17:20:55.137914+08:00**，288.641秒。
script SHA：`763548e8d0f910e3765540baff1fdd508cfdc0e496a831af76efb696db1529b3`。
test SHA：`dc3c0253002c2efa1223a3bf4f3950e9e5f89cba7b21a17c28f666832ab9454f`。

實際完整命令（umask077，V49_BACKUP_ARTIFACTS/COVERAGE_FILE指向此run）：

```text
backend/.venv/bin/python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' \
  -m pytest -c /dev/null -q -s -p no:cacheprovider \
  backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' \
  --junitxml=/private/tmp/v049-backup-plain-r6-y8GMvd/tests.xml
backend/.venv/bin/python -B -m coverage json -o /private/tmp/v049-backup-plain-r6-y8GMvd/coverage.json
backend/.venv/bin/python -B -m coverage xml -o /private/tmp/v049-backup-plain-r6-y8GMvd/coverage.xml
backend/.venv/bin/python -B /private/tmp/v049-backup-plain-r6-y8GMvd/audit-results.py
```

pytest/coverage/audit皆exit0。獨立audit只讀本run報告、code SHA及Docker metadata，
不呼叫DB/archive restore/qualification。其source SHA
`efa3bacef1f2d1a6c7022a96b44eb032f257f54cdbab69be9ac29d7a6d1a2794`，
結果SHA`6e015a5f177acf94000ab9a2ab349c15f26078a51f657c9147047e5010b0b4bf`。
詳見[機器可讀證據](CHG-291-V049-R6-EVIDENCE.json)。

## 未完成範圍與下一步

- 此模式仍明確只接受新合成來源，**尚未接入現行LiveSource/qualification入口**。
  下一步需另行核准這項整合及新現行備份/完整還原範圍；不能把這份合成
  測試報告當成現行可用備份，也不能重新使用R2消耗過的claim。
- 固定PG18.4、兩個extension、41個members與A/B owner形狀的相容性界線不變；
  其他版本/extension/member/initial ACL或無法COMMENT重建的異常狀態仍拒絕。
- Archive與COMMENT是不同transaction；隔離target失敗整體丟棄，不宣稱
  可對既有現行DB直接原子修復。正文證據為未加密私有檔，須按原保管界線使用。
- 全應用剩餘驗收/雙端coverage、fresh protected baseline/dry-run/維護窗口，
  V049及實際部署仍按[六步進度](CHG-291-SIX-STEP-CLOSEOUT.md)另行完成。

Harness已跑`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、
`test:plan`、`backend:syntax`及`git diff --check`，皆PASS；不是部署驗收替代品。

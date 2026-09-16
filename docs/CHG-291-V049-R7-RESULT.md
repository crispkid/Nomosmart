# CHG-291 R7 Backup Entry Integration — 執行紀錄

2026-09-13。需求`SPECIFICATION.md` §10.57 `V49-U012`；Peter以「核准」
同意[R7計畫](CHG-291-V049-R7-PLAN.md)Gate4。此文件只記有界工具整合與
新建真實PG隔離驗證，不代表現行備份、V049或部署已完成。

結果：**R7工具整合與隔離驗證PASS**。完整CLI 254PASS、0FAIL/ERROR/SKIP，
1human-GPG依範圍deselected；原212及新42全部通過。獨立audit及真實CLI
取消/自動清理亦PASS。沒有current-source資格、qualified.json、現行備份或部署。
精確來源與全部報告hash見[R7證據](CHG-291-V049-R7-EVIDENCE.json)。

上述及下文為隔離驗證輪結案狀態。後續Peter另以「同意」核准現行唯讀資格
檢查，已PASS並新增qualified.json；獨立結果見
[現行唯讀資格紀錄](CHG-291-V049-R7-READONLY-QUALIFICATION.md)。未新匯出或部署。

## 1. 整合內容

| 檔案 / 模組 | 調整 |
| --- | --- |
| backend/scripts/chg291_v049_live_backup.py / BackupSourceEvidence | 固定owned/live來源、單次claim與來源物件、export-time證據檔綁定；私有JSON不能自行重建現行授權 |
| 同檔 / BoundRestoreIdentityProfile、BoundMemberComments | 新v3/v2 envelope；共用R5/R6收集、typed identity、target-only還原與完整比較，legacy版本不自動升級 |
| 同檔 / export_database、verify_restore、restore_isolated、finish_bound_backup | 同snapshot完整archive/schema/profile/comment/source證據鏈；完整比較及cleanup/postflight後才能收尾，失敗不finalize |
| 同檔 / self_test_plain、synthetic_reports、main | 自我測試只回報SYNTHETIC_PASS_NOT_QUALIFIED；驗證原212案例清單與新關鍵案例；新增真正owned rehearsal CLI，無自動現行呼叫 |
| 同檔 / entry_compatibility、prepare_source、live_backup | 未來現行入口連至同核心；固定image與版本/角色/member有界metadata資格；此輪不執行現行正向操作 |
| backend/tests/test_chg291_v049_live_backup.py | 42個新案例、原212保留；共用真正取消observer；新增測試用完只刪除自己的暫存DB/角色，不放寬2GiB限制 |

沒有修改應用API、前後端產品功能、V001–V049 SQL、Helm/Compose、映像、
現行資料/權限/索引；沒有Provider、Kubernetes、現行資格/匯出或歷史R2重播。

## 2. 歷史執行輪次（保留，不覆寫）

### A. 首次窄驗證

- 私有run：`/private/tmp/v049-backup-plain-r6-vs4eoa`。
- 真實pytest：43PASS、0FAIL/ERROR，212deselected，146.60秒。
- 包含新42例及原shared-lab final cleanup例；不是完整回歸通過。
- Script SHA `3b26c09444bee57e8b10bbbde27170420c0ad893dabc562788c8aa642a49cdd1`。
- Test SHA `8706acfb71369f5557cb4eb6acee6f06d9144bdf21efba2a7c4332cb5ce74902`。
- 修改來源前已保存同源coverage JSON/XML及原始JUnit/log。

### B. 首次完整CLI驗證 — FAIL

- 私有run：`/private/tmp/v049-backup-plain-r6-i67m_0s9`。
- CLI log：`/private/tmp/v049-r7-cli-audit-HNQTg6/full-cli-output.log`。
- 實際219PASS、24FAIL、11ERROR，1human-GPG deselected，224.80秒；CLI exit1。
- Script SHA `e42eeb866dfd7fd8db13a5051c699d2b2660352e2663443a04706418a16a56c9`。
- Test SHA `8706acfb71369f5557cb4eb6acee6f06d9144bdf21efba2a7c4332cb5ce74902`。
- 最先兩例在新增shared-lab測試的`createdb`失敗，其後原final cleanup例也
  在建立DB時失敗，尚未到清理動作；後續standalone真實一容器guard正確
  拒絕，形成連鎖失敗。不能把後續拒絕當成可關閉guard的理由。
- 新增案例原先額外累積約20個來源DB，與全套共用的有限tmpfs不相容。
  原子程序錯誤正文未輸出/保存，故不把「磁碟已滿」列為有直接stderr證據
  的結論；已觀察的事實是createdb失敗及清理未抵達造成的連鎖拒絕。
- 修正僅為新R7 fixture在每案finally精確drop本案新建DB/role；不動原212
  資料及斷言，不增加資源或放鬆guard。後續全套需新證據，不能沿用本輪。
- CLI parent最後完成exact recovery；另以Docker metadata唯讀確認原baseline
  相等、零owned PG。無synthetic PASS proof、qualified.json或現行操作。
- 此輪預先寫的audit.py未執行成功；不把其預期數字當實際驗收。

### C. 修正新增測試生命週期後的完整CLI — PASS

- 私有run：`/private/tmp/v049-backup-plain-r6-dbi2mr3c`。
- Audit目錄：`/private/tmp/v049-r7-cli-audit-wfS9RB`。
- 真正執行`backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py
  --self-test-unencrypted`：exit0，254PASS、0FAIL/ERROR/SKIP、1deselected，472.72秒。
- Script SHA `e42eeb866dfd7fd8db13a5051c699d2b2660352e2663443a04706418a16a56c9`。
- Test SHA `dd9d88d0f5c8c8c15986b8579731a09e5bd2d794fb567b5f14c244161c086152`。
- 原212個完整JUnit case identity的排序digest保持
  `65cd3e543d091047478f6a01f307902098ecb8d6509bd6ae773ea8a3709e169c`；未刪改
  失敗斷言、xfail、skip或縮小coverage分母。

| 同源whole-tool報告 | Statements | Branches | Combined |
| --- | --- | --- | --- |
| pytest-only | 1532/1878 = 81.5761% | 214/266 = 80.4511% | 81.4366% |
| 真實CLI + pytest | 1548/1878 = 82.4281% | 214/266 = 80.4511% | 82.1828% |

兩者三種指標均>=80%；excluded lines=0，不合併舊輪coverage。CLI最後回報
`SYNTHETIC_PASS_NOT_QUALIFIED`，只建立新版synthetic proof；未呼叫現行
唯讀資格或產生qualified.json。上述是本備份工具coverage，不是全產品coverage。

### D. 獨立audit與真正CLI取消 — PASS

- `audit.py`使用實際JUnit、coverage、5個新入口完整roundtrip結果，逐一
  核對archive/snapshot/schema/profile/member/source/claim/postflight/restore
  digest及六類/raw/catalog全等；沒有把預期資料當真實結果。
- 明確驗證owned evidence不能當現行qualification；現行protected flag為
  null、usable_backup=false。最終Docker metadata等於起點、零owned PG。
- R7的install及COMMENT兩個取消案例，都有真實write XID、cancel、整批
  rollback及consumed target證據；原R6同案例與SQL/timeout回歸亦全部保留。
- 另以`cancel_cli.py`啟動全新真正self-test，在觀察到owned PG與測試進度後
  只對本次父程序送SIGINT；exit -2，4.0116秒完成。父程序自行清理完畢，
  沒有使用fallback清理；Docker baseline相等、零owned PG、無synthetic PASS/
  qualified/readonly result。新取消run為`/private/tmp/v049-backup-plain-r6-clh5133z`。
- Audit與取消驗證不納入coverage補分；來源SHA與完整CLI保持相同。

## 3. 驗證與追溯

滿足U012/T48..T53的工具整合及隔離部分，以及原U001..U011回歸；現行
專屬正向路徑明確NOT RUN。已執行`spec:doctor`、`spec:trace`、`plan:approved`
（含plan:doctor）、`test:plan`、`backend:syntax`及`git diff --check`，均PASS。
完整CLI、窄pytest及獨立audit命令/原始報告在上文與EVIDENCE保留。
新測試DB/role及本run容器已精確清理；私有合成archive/失敗與成功報告保留。

## 4. 仍需分清的界線

1. 工具與owned來源演練，不等於現行Kubernetes/DB的qualification、source
   binding、實際匯出與postflight正向驗收；這些此輪NOT RUN。
2. 固定PG18.4、pgcrypto1.4/plpgsql1.0、受支援A/B與41個members；其他模式
   fail closed。大資料在既有時間/容量上限可能拒絕，不能默默擴容或截斷。
3. 未加密私有測試證據仍0700/0600；原human-GPG保持範圍外，不稱已驗證加密。
4. 六步中的現行合格備份、全應用驗收、fresh部署範圍/V049/部署仍未完成。

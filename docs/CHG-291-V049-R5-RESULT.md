# CHG-291 R5 混合擁有者還原結果

2026-09-13。Peter以後續`Ok`核准R5書面計畫，依§10.57 V49-U010執行隔離
修正/測試。**PARTIAL，尚未完成；不具備備份或部署資格。**

## 已確認結果

- 一般trusted A/B還原成功：pgcrypto套件owner A及37個member owner B正確
  保留；plpgsql預設保留與重建兩種情境都通過。table/sequence/large object、
  ACL、table與extension外層comment、六類/raw hash/catalog全等。
- 原133個測試全部PASS，包含原T15、default及R4 mixed-owner拒絕。
- 新R5共35例：33 PASS、2 FAIL。全套166 PASS、2 FAIL、0 ERROR、0 SKIP；
  1個human-GPG按未加密範圍deselected。未刪除或xfail失敗案例。
- 三種whole-tool coverage皆>=80%，但測試FAIL仍禁止qualification。
- Docker最終inventory等於起點，零殘留自建PG；現行Kubernetes/DB不動，
  沒有R2重播、新備份、qualified.json、V049、部署或Provider。

## 程式調整

只改`backend/scripts/chg291_v049_live_backup.py`、同名tests與追溯文件：

- `MixedRestoreIdentityProfile`：獨立v2、同snapshot可信版本/控制資訊、A/B
  owner、DB CREATE、完整member及custody；不回填v1或猜測member owner。
- `prepare`：固定image/空白target檢查，受限A預建唯一pgcrypto，唯一bootstrap
  B執行完整archive；保留plpgsql RESTRICT及前後完整比較。
- synthetic export/restore入口：新增顯式mixed模式；原預設不變，不接現行
  CLI/LiveSource/R2。v1測試可於新R5私有目錄執行，mixed-owner仍拒絕。
- `RestoreIdentityProfile.read_toc`抽出完整TOC防護共用，不過濾archive。
- tests新增真實來源、profile/custody負向、髒target/權限/逾時、source drift、
  A/B fresh還原；沒有mock/stub/fake成功。無產品/API/schema/遷移SQL/前端/
  image/Helm改動，使用者其他既有變更保留。

## 兩個FAIL，同一個原因

`test_r5_trusted_mixed_owner_fresh_roundtrip[False]`及`[True]`只差plpgsql為
初始保留或需重新建立。兩者刻意對pgcrypto內部`digest(text,text)`新增合成
自訂COMMENT；還原後六類（含raw schema hash）全部相等，但逐物件catalog
有**1個routine的comment不同**，owner/ACL/其他欄位未列差異。
驗證器回報`restored_schema_evidence_differs`、保留FAIL並清理。

PostgreSQL 18.4的`checkExtensionMembership`在非binary-upgrade匯出時，僅
選取extension member的ACL部分，不選取其自訂comment。因此完整archive
沒有該內部註解，raw schema dump也沒它；僅比raw hash會漏掉。
[PostgreSQL REL_18_4 pg_dump source](https://github.com/postgres/postgres/blob/REL_18_4/src/bin/pg_dump/pg_dump.c)。
這符合本次真實結果，不代表現行文件/資料遺失，也未證明R2唯一失敗原因。
外層extension與一般table註解正常；兩個未改member comment的額外baseline
完整比對PASS，沒有替換原兩個FAIL案例。

## 待討論的邊界

R5禁止額外自動COMMENT或改dump；現有sidecar只存comment狀態/hash，不能
從hash重建正文。依計畫遇完整還原不相容停止策略擴張，完成不受影響回歸
與清理，不把FAIL改成PASS。

建議另行討論「extension member自訂註解的獨立完整保存與受限還原」，仍
只用自建隔離資料驗證、不碰現行系統。這會新增私有正文保管及target-only
metadata還原邊界，須先確認，再寫計畫；目前未授權、未實作。
較小的替代範圍是明確拒絕這類來源，但不等於能完整還原它。不建議忽略
comment差異，也不採用binary-upgrade繞過原策略。

## 驗證及證據

最終run：`/private/tmp/v049-backup-plain-r5-gc9vv6`，0700/reports0600。
2026-09-13 16:09:34起（Asia/Taipei），183.94秒。

| 輪次 | 結果 | 原因 |
| --- | --- | --- |
| WiLC5J | 29 PASS/3 FAIL，窄測試 | 新布林查詢回傳PG文字t/f而非JSON，已修正to_json |
| xySD5l | 2 FAIL，fresh roundtrip | 六類/raw相等，member自訂comment不同；原FAIL保留 |
| gc9vv6 | 166 PASS/2 FAIL，全套 | 原133 PASS；新33 PASS/2 FAIL；上述comment未解 |

最終pytest-only coverage：statements1192/1477=80.7041%，branches174/216=
80.5556%，combined80.6852%，excluded0。沒有合併R4舊資料或補填報告。
T34/profile、T36既有target guards、T38/custody及drift已有真實驗證；
T35一般baseline通過，T37含comment仍不滿足；T39前置逾時/failed-restore
清理/role檢查有證據，但安裝transaction中途取消尚未專屬驗證；T40全套
通過條件未滿足。不得宣告所有驗收已完成。

實際命令（V49_BACKUP_ARTIFACTS與COVERAGE_FILE指向上述private run）：

```text
backend/.venv/bin/python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' \
  -m pytest -c /dev/null -q -s -p no:cacheprovider \
  backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' \
  --junitxml=/private/tmp/v049-backup-plain-r5-gc9vv6/tests.xml
backend/.venv/bin/python -B -m coverage json -o /private/tmp/v049-backup-plain-r5-gc9vv6/coverage.json
backend/.venv/bin/python -B -m coverage xml -o /private/tmp/v049-backup-plain-r5-gc9vv6/coverage.xml
backend/.venv/bin/python -B /private/tmp/v049-backup-plain-r5-gc9vv6/audit-results.py
```

pytest exit1；coverage與post-test audit exit0。Audit只核對本run報告/SHA/
私有模式及Docker metadata基線，不讀DB或archive正文，不是qualification。
`spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、`backend:syntax`及
`git diff --check` PASS；不能替代失敗的功能測試。
詳見同名EVIDENCE.json及私有audit-results.json。

六步部署收尾仍未通過完整備份工具資格。現行備份、完整應用驗收、fresh
protected baseline/dry-run/維護窗口及實際V049/部署均不因局部PASS完成。

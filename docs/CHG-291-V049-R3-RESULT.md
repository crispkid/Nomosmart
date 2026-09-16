# CHG-291 R3：逐物件備份證據修正結果

2026-09-13。Peter要求連續完成已核准準備、部署前再確認，R3 Gate4 approved。
本輪工具與隔離測試已執行；**尚不具備正式備份／部署資格，未部署**。
不是再次等待相同Gate4批准，也沒有把剩餘阻擋事項改列成功。

## 1. 已完成

- 同一個唯讀snapshot收集原六類DatabaseState及逐物件SchemaEvidence。
- 私有`schema-evidence-v1.json`綁定tool/test/image、PostgreSQL版本、snapshot與
  archive。匯出當下另在archive handle保留sidecar digest與inode，不能只修改
  自含hash就偽造證據；缺件、換檔、未知版本／類別／格式均拒絕。
- definitions與註解原文在資料庫端計算SHA；private sidecar保留必要identity，
  一般差異報告只含物件鍵hash、類型、改變欄位及digest，不輸出SQL／文件／註解。
- 依穩定身分比較schema、relation／column、types、routine、constraint、trigger、
  rule、policy、default ACL、extension與language。OID只在原snapshot解析，
  不跨叢集直接比較數字OID；owner、ACL、grantor、grant option、initial ACL及
  dependencies分別保留。
- 保留原資料、六類、raw schema hash、source drift與清理門檻。catalog相同但
  raw hash不同仍失敗；新增`representation_difference_candidate`只作診斷。
- 還原失敗與物件差異報告在容器清理前落地；finish_backup需要原始sidecar證據。
- 私有JSON reader增加nonblocking open，真正FIFO會立即被拒絕，不先卡在open。

修改：`backend/scripts/chg291_v049_live_backup.py`中的`SchemaEvidence`、
`export_database`、`verify_restore`、`finish_backup`及`read_private_json`；
測試位於`backend/tests/test_chg291_v049_live_backup.py`。規格§10.57 V49-U008、
plan/test/trace/changelog同步更新。不改產品API、SQL migration、Frontend、image或chart。

## 2. 真實測試結果

最終同源run：`/private/tmp/v049-backup-plain-r3-x3yKqn0T`。
**93 PASS、1 FAIL、0 ERROR、0 SKIP；另1個原human-GPG案例依既定方式未執行**。
新增31個R3案例全PASS；原失敗T15未刪除、skip、xfail或改成預期成功。

| 驗收 | 結果 |
| --- | --- |
| T21 物件inventory／穩定身分／定義差異 | PASS；真實DDL變更column/default/index/constraint/routine/policy可定位 |
| T22 註解狀態 | PASS；schema/table/column/extension。PG將COMMENT空字串視為移除，依實際catalog記錄，未捏造empty row |
| T23 Owner與ACL | 新診斷及拒絕案例PASS；原完整還原正向T15仍FAIL，見下節 |
| T24 綁定／custody／未知證據 | PASS；含重新計算自含hash、相同內容inode置換、symlink、FIFO、損壞JSON與boolean version |
| T25 安全／bounded操作 | PASS；原process／SQL timeout、大小與清理案例保留，惡意identifier／comment／function body只作資料 |
| T26 原門檻／失敗證據 | PASS；真實pg_dump兩種表示同catalog仍拒絕；post-snapshot language owner drift拒絕；真實pg_restore損壞輸入保留ERROR |
| T27 全套資格 | FAIL；T15未通過，完整coverage未達80%，未讀現行來源，沒有qualified.json |

原orchestration的「錯誤expected schema」負向案例仍在，因新binding gate而在
restore之前拒絕，斷言改驗`schema_evidence_binding`；不是取消schema完整比對。
損壞archive案例刻意改動自己新建的負向測試資料以到達真實pg_restore錯誤路徑，
不構造成功回應，也不放行正式備份。

自動coverage.py結果（沒有excluded lines、沒有降低分母或門檻）：

| 範圍 | Statements | Branches | Combined |
| --- | ---: | ---: | ---: |
| 整個備份工具 | 77.52% | 78.13% | 77.60% |
| R3 collector及整合路徑 | 100.00% | 91.67% | 99.38% |
| 共用Snapshot／stream／archive／PG／DatabaseState | 97.35% | 87.93% | 95.98% |

局部coverage不是整個工具合格，也不是Backend／Frontend全來源coverage。
本輪不為補coverage存取現行來源，亦不製造readonly proof。先前55測試版本
資格不能挪用到新來源。機器來源hash及私有報告hash見
[R3 evidence](CHG-291-V049-R3-EVIDENCE.json)。

## 3. 原T15：現在知道什麼

合成source刻意以不同初始化／extension擁有者建立物件；原還原流程沿用
`backup_verify`作隔離bootstrap，來源角色依既有策略重建為NOLOGIN／NOSUPERUSER。
真實還原後六類中仍只有raw schema不一致；新增證據進一步定位：

- **43個物件owner不同**：40個routines、2個extensions、1個language。
- **41個物件的ACL證據不同**，包含由owner決定的有效預設grants。
- 因此這個合成案例不是純空白或無害註解差異，不可用no-owner／no-acl或
  刪掉schema gate解決。

這只證明T15合成案例。**沒有證明R2真實archive的差異也是相同原因**。
R2只留下安全摘要、缺乏原始逐物件owner/comment證據；本輪沒有讀取或重播
已消耗的R2 archive，也沒有用目前資料補造舊來源證據。

原還原策略尚未修好。需要討論的精確範圍是「來源初始化／extension身分如何
在新隔離資料庫中忠實保留」。現行R3計畫明確禁止直接改還原owner／ACL策略、
增加還原SUPERUSER、UPDATE system catalog或自動COMMENT修補，因此沒有越界執行。
這不是要求再核准已完成的工具修正，也不是可以直接按部署的狀態。

## 4. 保護與限制

每次測試使用原核准的已安裝PG image、network-none／tmpfs、相同CPU／memory／
pids／deadline上限；最多一個自建PG，source／fresh restore循序執行。
自建測試容器及其中合成資料已按receipt精確清理；完整Docker inventory baseline
一致。合成資料隨tmpfs容器刪除，不是現行應用資料；私有測試報告與合成dump保留。
cleanup proof、coverage、XML與程式／測試hash一致。

v1只對已覆蓋catalog類別作完整聲明。自訂collation、operators／opclass等
尚未實作的類別與security labels拒絕，並保留unsupported key hashes。
extension在既有allowlist中，不代表其所有member類別自動受支援；不能宣稱
任意PostgreSQL extension／複雜schema都已完整備份驗證。
metadata仍受4MiB讀取、3MiB evidence與原SQL／snapshot時間上限保護。

未讀現行Kubernetes／DB／其他服務，未重驗原archive、未新匯出現行資料，
未改原FAILED／claim、未掃描／建image／建Job／套用V049／部署／呼叫Provider。
fresh-cluster測試的`result.json PASS`只屬自建合成fixture，不是MAAS可用備份。

## 5. 執行與剩餘部署條件

```sh
V49_BACKUP_ARTIFACTS=/private/tmp/v049-backup-plain-r3-x3yKqn0T \
COVERAGE_FILE=/private/tmp/v049-backup-plain-r3-x3yKqn0T/.coverage.tests \
backend/.venv/bin/python -B -m coverage run --branch \
  --include='*/chg291_v049_live_backup.py' -m pytest -c /dev/null -q -s \
  -p no:cacheprovider backend/tests/test_chg291_v049_live_backup.py \
  -k 'not human_gpg' --junitxml=/private/tmp/v049-backup-plain-r3-x3yKqn0T/tests.xml
```

上為已執行命令紀錄，不可重用既有run目錄重跑；新測試必須mktemp取得全新私有目錄。
pytest exit1（上述T15）；coverage JSON正常產生。
`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、`test:plan`、
`backend:syntax`及`git diff --check`均PASS。這些文件／語法檢查不抵銷T15。

部署阻擋事項仍包括：還原身分策略及完整工具資格、可用新鮮備份、其餘發布測試與
雙端完整coverage缺口、fresh protected baseline／維護窗口／精確render及回退範圍。
不掃描指示不變，不把舊CVE狀態說成已清除。既有候選image與V049矩陣結果維持
各自來源界線；本輪未重驗，亦不以歷史revision斷言現在環境狀態。
六項總表見[部署收尾](CHG-291-SIX-STEP-CLOSEOUT.md)。

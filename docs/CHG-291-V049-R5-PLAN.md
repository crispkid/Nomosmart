# CHG-291 R5 Trusted Mixed-owner Isolated Restore

2026-09-13。Peter在現行唯讀盤點結果與「補混合擁有者隔離還原支援、現行
權限不變、完整比較不放寬」的範圍確認問題後回覆`Ok`，確認Gate 2。
本文件為其後才寫出的Gate 3具體計畫。**Gate 4 approval: APPROVED**。
Peter於2026-09-13以後續`Ok`回答這份書面計畫的核准問題，核准隔離實作與
feature tests；不授權現行服務/歷史archive/備份/部署。歷史規劃狀態保留於文末。

## 1. 目標及證據界線

R4已完成133 PASS及原T15修復，但明確只支援單一owner。另行核准的唯讀
盤點發現現行pgcrypto為合法的不同owner：套件屬於非SUPERUSER資料庫擁有者
A，37個函式屬於管理帳號B；plpgsql套件與4個member亦屬於B。
詳見[現行相容性盤點](CHG-291-V049-CURRENT-COMPATIBILITY-INVENTORY.md)。
這不證明R2歷史archive的唯一失敗原因；本輪不讀取它，也不重新盤點現行系統。

PostgreSQL的trusted extension可由具DB CREATE權限的非superuser安裝，
安裝腳本以bootstrap身分執行；因此外層owner與member owner可以不同。
[CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html)、
[Extension packaging](https://www.postgresql.org/docs/18/extend-extensions.html)。
`SET LOCAL ROLE`可在transaction中改以指定角色檢查權限；這不需要把A升為
superuser。[SET ROLE](https://www.postgresql.org/docs/18/sql-set-role.html)。

以下是需用固定image真實驗證的方案，不宣稱已成功。驗收目標為保留A/B
分工並完整還原，不是直接刪掉R4的mixed-owner拒絕條件。

## 2. 支援模式與同snapshot證據

- 保留R4 v1 uniform-owner入口、預設行為與原負向mixed-owner測試。
- 新增顯式R5合成模式與獨立v2 profile/collector及sidecar；只允許本輪
  新建、exact-owned來源的完整archive。R3 SchemaEvidence v1及snapshot六欄
  保持原契約；不回填舊profile、不從目前盤點JSON冒充新來源證據。
- 新模式只支援PG18.4固定image中的plpgsql1.0/pg_catalog與pgcrypto1.4/public。
  必須同snapshot記錄版本、schema、trusted/superuser/requires控制資訊、完整
  member identity/owner/initial ACL、DB owner、必要role屬性與DB CREATE判定。
  不取得角色密碼、登入祕密或來源function/comment正文；實際身分留私有證據。
- 支援形狀限於：A不等於B；A是DB owner且非SUPERUSER、具DB CREATE；
  pgcrypto extension owner=A、所有37個members owner=B；plpgsql extension
  及全部4個members owner=B；B須有來源superuser證據。B作為新target唯一
  bootstrap，並非據此宣稱已證明來源歷史initdb身分。
- extension/member清單仍綁定R4固定image已驗證digest；缺件、未知member、
  第三個member owner、未知extension/version/schema、非trusted、未支援依賴
  或非空initial ACL一律拒絕。這是初版界線，不把initial ACL忽略為空；一般
  現有ACL變更仍須由完整archive還原並比較。
- 新profile與archive bytes/hash、snapshot、完整catalog、tool/test SHA、
  固定image、source-kind及export時inode/私有custody綁定；前後metadata/profile
  drift拒絕。讀取證據與開始target前都驗證，不用僅有同名JSON代替來源證明。

## 3. 有界還原策略

1. 在自建合成來源以非SUPERUSER A安裝trusted pgcrypto，觀察實際A/B owner，
   匯出完整archive與證據；先精確清除source容器，再建立全新target容器。
2. target的唯一bootstrap名稱為B；沿用R4 identifier/intent/receipt/runtime
   guards。A及其他必要角色沿用NOLOGIN、NOSUPERUSER、NOCREATEDB、
   NOCREATEROLE、NOREPLICATION、NOBYPASSRLS。只還原原有DB owner/ACL，
   不新增超級使用者、不複製角色密碼/LOGIN、不用額外GRANT ALL解決安裝問題。
3. target必須是本run新建、未用過的空白DB。安裝前檢查固定image/version、
   初始catalog/唯一plpgsql、public schema、無額外使用者物件/函式/運算子、
   無非本run使用者連線及exact-owned限制。使用完整TOC核對extension inventory；
   TOC只供防護，不提供`-L`或過濾/重排還原。
4. 依R4規則，來源TOC要求重建plpgsql時，可於此target使用DROP EXTENSION
   plpgsql RESTRICT；不使用CASCADE，不刪public或其他schema。
5. 在有界target準備transaction中，以`SET LOCAL ROLE A`、明確schema/version，
   **只預先CREATE EXTENSION pgcrypto WITH SCHEMA public VERSION '1.4'**。
   預先確認套件不存在及固定控制資訊，不用IF NOT EXISTS掩蓋非預期物件。
   使用固定SQL模板與identifier/literal quoting，安全search_path；不允許通用
   安裝SQL、自動安裝依賴、讀取/改寫extension檔案或改system catalog。
   A不能正常安裝即FAIL，不自動提升權限。transaction結束及新連線須確認
   回到B；失敗rollback，整個target隨run精確清除，不重用半成品。
6. 完成後立即驗證target pgcrypto的版本/schema、member清單/owner/定義/初始
   權限及唯一bootstrap，並保存有界準備證據。此時尚未還原來源後加的ACL/comment，
   不把準備證據當成來源完整相等；有未支援定義差異須拒絕，不按source重寫函式。
7. 以B執行**整份原archive**，保留原single-transaction/exit-on-error。
   pg_dump通常輸出CREATE EXTENSION IF NOT EXISTS，但該語法不保證已存在
   物件一致；因此必須驗證archive在固定image的實際行為及上述前後catalog，
   不能只看restore exit0。[CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html)。
   不改dump/SQL、不使用全域`pg_restore --role A`替代方案、no-owner/no-acl/
   no-comments，不忽略錯誤、不停用triggers、不自動COMMENT或ALTER member owner。
8. 原六類(properties/roles/schema/tables/sequences/large objects)、raw schema
   hash、完整逐物件catalog、profile/source drift、archive custody及cleanup
   **全部**通過才算合成還原PASS；不以A/B正確替代其他比對。

初始catalog檢查與預建僅作用於封閉新target、來源archive執行之前；不將來源
任意SQL當成可信安裝模板。若完整archive與預建策略不相容，保存FAIL並停止，
不擴張為重排archive/修權限/改初始化檔案。準備transaction與archive restore
是兩個階段，不宣稱兩者共用同一transaction；失敗由丟棄exact-owned target收尾。

## 4. 修改檔案與任務

僅`backend/scripts/chg291_v049_live_backup.py`、其同名tests及規格/追溯文件：

1. 擴充版本化profile收集/選擇/驗證，明確區分v1與v2；保留既有reader契約。
2. 新R5顯式合成export/restore選項與私有目錄source-kind限制；不能由LiveSource、
   R2診斷或現行qualification CLI自動啟用。必要token/receipt狀態沿用既有模式。
3. 在`provision_restore`之後增加受限target準備；維持MemoryPostgres的一容器、
   固定image、角色、runtime、恢復/清理防護，不增加通用SQL修復介面。
4. 先跑窄真實案例，再跑原T15/default與全套回歸、whole-tool coverage。
5. 建立R5 RESULT/EVIDENCE，保留所有失敗輪次、原報告與source hashes；更新
   六步進度，不產生qualified.json或把隔離成功當現行備份成功。

無產品/API/前端/資料庫schema/遷移SQL/index/Helm/env/image內容變更。
目前起點script SHA為
`ceefb6c0de67a80684fc571a9815087fc02a46e838b877f47abd654ec2fb454f`，
test SHA為`b6db9ea71de78c53e30f0aa1d11ed7cf65e9cb9756a6116ef2699c256d851269`。
來源修改後不得沿用R4 coverage或current-readonly資格作為同源通過證據。

## 5. 隔離、資源與排除

- Docker context desktop-linux，唯一已安裝PG image
  `sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
  pull never；任何時刻最多1個本工具容器，source→cleanup→fresh restore。
- network none、無ports/host mount/existing volumes/docker socket；2CPU、
  4GiB memory/swap、pids256、PG tmpfs2GiB、tmp128MiB、run16MiB、空initializer
  tmpfs1MiB、log none、core off。沿用R4完整runtime guard與exact receipt清理。
- source256MiB、archive512MiB、metadata4MiB、schema32MiB，SQL10s/lock2s、
  snapshot300s/restore+compare600s；profile/TOC/新準備共用既有上限，不提高。
- 新私有`/private/tmp/v049-backup-plain-r5-*`目錄0700、檔案0600；只保留合成
  archive及安全報告，不覆寫R2/R3/R4 artifacts。結束Docker inventory須與開始一致。
- 不存取現行Kubernetes/DB/支援服務；不新匯出現行資料、不讀/重播/改寫R2
  archive或claim、不備份資格CLI/qualified.json、不scan/build/pull/Job/Helm/
  V049/部署，不改會員/權限/索引，不Provider，不使用對話密碼。
- Gate4批准後在上述範圍連續完成，不為每個測試重問；新增資料存取/權限/
  策略/資源邊界或無法忠實還原才停止說明。實際部署仍須另行確認。

## 6. 真實測試矩陣

| ID | Observable acceptance |
| --- | --- |
| V49-U-T34 | 真實非SUPERUSER A安裝pgcrypto得到A/B分工；同snapshot完整v2 profile及綁定正確；缺資料/錯版本/第三owner/不可信控制資訊拒絕；不修改v1原mixed-owner拒絕斷言 |
| V49-U-T35 | A/B合成source→cleanup→fresh target；資料、六類、raw hash、catalog全等；pgcrypto A/37個B、plpgsql B/4個B，target恰好唯一B SUPERUSER，A受限且無複製密碼 |
| V49-U-T36 | 真實target準備/完整TOC/固定version檢查；預存在pgcrypto、髒schema/額外物件、不足CREATE、未知dependency或錯誤bootstrap拒絕；不得CASCADE/額外GRANT/過濾archive |
| V49-U-T37 | 實際來源包含table、sequence、large object及owner/ACL/comment變化，原全量比較仍有效；準備後已有一致身分不掩蓋資料/定義差異；原T15/default及R4所有正負向不退化 |
| V49-U-T38 | 真實檔案替換/權限/inode/hash/source/profile drift、legacy混用及錯誤source-kind拒絕；舊archive/現行入口不可使用新模式，報告無祕密/正文 |
| V49-U-T39 | 真實SQL失敗/中斷後ROLE不殘留、target不重用、錯誤有分類、原archive不變、exact-owned清理與Docker前後基線相等、零殘留PG |
| V49-U-T40 | 同source全套回歸及whole-tool statements/branches/combined各>=80%；不減分母/刪除原測試/xfail舊錯誤，以真實PG/process/file/reports驗證，無mock/stub/fake成功 |

保留原human_gpg測試但仍不在本輪非互動未加密範圍執行，明確列deselected。
新增共享PG案例放在原final共享PG cleanup之前；獨立fresh roundtrip在其後，
不可為了-k選測破壞一容器上限。若有真實report-guard補驗，只能使用本輪同源
實際報告，分別保留原pytest-only和補驗coverage，由工具合併，不能重用舊PASS。

## 7. 命令、完成及剩餘風險

規劃輪：`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:doctor`、
`test:plan`、`git diff --check`；`plan:approved`預期因R5 pending拒絕。
Gate4後才執行`plan:approved`、`backend:syntax`及真實pytest/coverage。使用
既有backend/.venv，設定V49_BACKUP_ARTIFACTS為新private R5目錄、COVERAGE_FILE
為該目錄的`.coverage.tests`，例如以下命令（XML路徑亦須由本run具體化）：

```text
backend/.venv/bin/python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' \
  -m pytest -c /dev/null -q -s -p no:cacheprovider \
  backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' \
  --junitxml=<private-r5-run>/tests.xml
```

將coverage XML/JSON也放本run私有目錄；實際命令與結果須寫入RESULT，不把
計畫命令當已跑。窄案例選取依測試順序保持單一容器；全套保留所有原案例。

完成條件為T34..T40/原套件、完整比對、三種80%、custody/cleanup/source-bound
報告全部合格。若有未知extension、modified member definition、不同initial ACL、
或不同版本/owner模式，記UNSUPPORTED，不宣稱一般化支援所有PG備份。

本計畫不包含現行profile qualification整合、新備份、完整應用驗收缺口、
部署前新基線/維護窗口/dry-run或V049；它只修現行盤點指出的一項工具相容性。
下一階段必須用新source證據證明，不以合成結果把六步其餘項目標成PASS。

本輪狀態：Gate2理解確認、Gate3書面計畫；尚未修改Python、建立容器或跑feature tests。

規劃輪驗證：spec:doctor、spec:trace、plan:doctor、test:plan、git diff --check
均exit0。plan:approved為預期exit1，明確拒絕R5 Gate4 pending，並非功能測試
失敗。工具及測試SHA仍與第4節R4起點完全一致。沒有現行服務查詢、實際archive
讀取/重播、新匯出、qualified.json、image/Job/V049/部署或Provider操作。

Gate4後結果見R5-RESULT/EVIDENCE：166PASS/2FAIL，whole coverage三種達80%，
一般mixed-owner與原133案例PASS。member自訂comment兩案例仍FAIL，未完整
完成；沒有略過差異或新增COMMENT replay。清理與基線PASS，停止新策略擴張
並討論註解保存邊界。現行資料/歷史archive/qualification/V049/部署仍未執行。

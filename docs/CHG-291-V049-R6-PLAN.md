# CHG-291 R6 Extension Member Comment Preservation

2026-09-13。Peter回答R5結果後的「獨立保存/還原套件內部註解，僅隔離測試」
範圍問題，以`好`確認Gate 2。本文件是確認後新寫的Gate 3具體計畫。
**Gate 4 approval: APPROVED**。Peter於2026-09-13以後續`Ok`回答此書面計畫
核准問題，核准有界隔離實作與測試；現行服務/歷史archive/部署仍排除。
文末規劃輪結果為核准前歷史狀態，不代表新增功能已通過。

## 1. 目的、已知原因與範圍

R5全套166PASS/2FAIL，原133例與一般A/B mixed-owner還原通過；兩個FAIL均為
自訂`digest(text,text)`註解沒有還原。六類及raw schema hash相等，完整catalog
仍正確攔住差異。R5失敗報告保留，不改為PASS，不據此推論R2歷史archive的
唯一根因，也不宣稱現行文件遺失。詳見[原結果](CHG-291-V049-R5-RESULT.md)。

PostgreSQL18.4一般dump對extension member只選取ACL，不匯出其個別註解；
因此只補比較邏輯或重跑原archive不能重建正文。
[PG18.4 pg_dump checkExtensionMembership](https://github.com/postgres/postgres/blob/REL_18_4/src/bin/pg_dump/pg_dump.c)。
本方案新增「同snapshot註解正文證據 → 完整archive還原 → 有界COMMENT還原
→ 原完整比對」，不改archive、不忽略差異、不使用binary-upgrade。

僅支援既有固定PG18.4 image的pgcrypto1.4/public（37函式）與
plpgsql1.0/pg_catalog（3函式及1language），共41個既有allowlisted members。
使用R5受支援A/B owner模式；不擴大extension/version/schema/member/initial ACL
支援範圍，不修定義/owner/ACL，不增SUPERUSER。產品/API/前端/schema SQL、
image與Helm不變。這是隔離工具測試，不是現行備份資格或部署授權。

## 2. 明確模式及註解資料契約

- 新增顯式`member_comments=True`合成export/restore選項，必須同時使用
  `mixed_identity=True`；只接受本輪exact-owned新來源與新R6私有目錄。
  v1 uniform、v2 mixed profile及SchemaEvidence v1格式與預設行為保持；
  R6另加`extension-member-comments-v1.json`，不改舊profile或自動補舊證據。
  v2的歷史source-kind仍是既有mixed collector契約；新comment sidecar另有
  `r6-owned-synthetic` source-kind，並綁定此次新匯出的完整v2 profile與來源。
- `ExtensionMemberComments`負責collect/bind/read/target guard/replay；沿用
  Snapshot、PlainArchive、private_json/read_private_json及既有catalog比較。
  不提供通用SQL、任意物件選取或現行CLI自動啟用入口。
- 與完整archive、六類state、SchemaEvidence、v2 profile使用**同一readonly
  exported snapshot**。取得完整41筆member inventory，即使沒有註解也有紀錄。
  每筆包含extension/version/schema、catalog identity/key、結構化target、
  comment state、UTF-8正文或null、byte長度及SHA-256；保留換行/引號/反斜線/
  Unicode，不改寫或normalize內容。不收集函式definition正文或role密碼。
- 身分以namespace/name及有序input argument type namespace/name表示函式；
  language以name表示。`pg_proc.proargtypes`供input signature；不把來源OID
  當跨cluster身分，不把`pg_identify_object`顯示字串當可直接執行SQL。
  [pg_proc](https://www.postgresql.org/docs/18/catalog-pg-proc.html)、
  [pg_description](https://www.postgresql.org/docs/18/catalog-pg-description.html)。
- SQL先查數量及octet_length，單筆正文上限64KiB、全部正文合計1MiB，JSON
  序列化仍受既有4MiB metadata限制；超限拒絕，不先取無界正文或截斷。
  每次檢查共享snapshot300秒/SQL10秒上限。匯出後重新檢查catalog/profile/
  comment inventory無drift，來源程式SHA也必須相同。
- 真實PG的`COMMENT ... IS NULL`或空字串均移除註解；還原無註解使用NULL，
  不捏造一個可存留的空字串狀態。若出現SQL COMMENT無法忠實建立的異常
  catalog空值狀態，判UNSUPPORTED，不寫system catalog來模擬。
  [COMMENT](https://www.postgresql.org/docs/18/sql-comment.html)。

## 3. 私有正文保管與綁定

新sidecar是敏感正文，不可進git或一般log。只放新的
`/private/tmp/v049-backup-plain-r6-*`目錄（0700）、檔案0600；沿用EXCL/fsync、
owner/ACL/nlink/inode、NOFOLLOW/NONBLOCK及有界reader。存export-time
device/inode/內容hash綁定於PlainArchive，不接受僅重新計算JSON hash的替代檔。

Sidecar格式/version/collector/source-kind及exact container/database/run，必須
與archive bytes/hash、snapshot、完整catalog、v2 profile、image、tool/test SHA
一致；正文hash/state必須逐筆吻合原SchemaEvidence。完整41筆set/數量/typed
identity亦須與固定member digest及來源profile吻合。缺檔、替換、重複、錯物件、
錯版本、正文/證據不一致或逾界，在建立target或COMMENT之前拒絕。

不從目前DB、歷史R2/R5檔或hash猜回正文，不從另一次export混入證據；不得
回填舊archive。報告只列數量、狀態、object/field hash及固定error code；不得
將正文、完整SQL、raw stderr、secret或憑證輸出至一般log/test失敗訊息。
正向測試使用明確合成文字，仍按私有正文保管。

## 4. Target-only有界還原

1. 來源是本run新建隔離PG；先完整匯出並驗證所有綁定，再精確清除source，
   然後新建fresh target，任何時刻最多一個本工具容器。
2. 沿用R5唯一bootstrap B、受限A、target空白檢查及transaction-local A預建
   pgcrypto；保留原plpgsql RESTRICT準備。以B執行完整原archive，仍為
   single-transaction/exit-on-error；不改dump、不過濾/重排TOC、不加no-comments。
3. 完整archive還原後，COMMENT前重新讀取綁定並收集完整target catalog及六類。
   此階段唯一允許的catalog差異為上述41個已綁定member的comment。
   missing/extra object、其他物件comment、任何definition/owner/ACL/initial ACL/
   dependencies、版本或六類差異均拒絕，不能先COMMENT來掩蓋其他問題。
   逐一解析typed identity至target實際member及extension membership；不靠同名
   函式或跨DB OID對上即接受。確認B身分與無非本run連線，target不可重用。
4. 同一有界transaction內只執行兩種固定模板：`COMMENT ON FUNCTION`與
   `COMMENT ON LANGUAGE`。逐段quote identifier，函式每個參數型別必須完整
   schema-qualified；正文使用既有安全literal quoting並固定
   `standard_conforming_strings=on`、安全search_path。NULL明確表示移除。
   正文永遠當資料，不接受sidecar提供SQL片段、可執行模板或callback。
   只對實際差異的allowlisted members寫入，完整41筆仍驗證。沿用B，不新增
   superuser/GRANT，不ALTER定義/owner、不直接更新pg_description。
5. 全批次COMMIT前在同連線驗證目標身分與註解state/hash；SQL失敗或取消必須
   rollback整批。COMMENT步驟分享原restore+compare600秒、statement10秒/
   lock2秒限制，不另增加時間配額。安全報告區分archive/precheck/comment/
   full-comparison階段；失敗丟棄exact-owned target，不重試半成品或偷換來源。
6. COMMIT後新readonly snapshot重做原六類、raw schema hash、完整catalog、
   profile/sidecar/archive custody/source checks；**全部相等**及精確cleanup才
   PASS。不把註解修復成功當全量相等，也不在最後比較排除comment欄位。

archive restore與comment replay是不同transaction；不宣稱跨兩階段原子性。
隔離target整體失敗時以丟棄target收尾。專屬取消測試可使用同一owned lab的
第二條受限測試連線，只針對本run target PID施加真實lock/cancel，不碰外部
連線/容器；正常restore不得容忍未知連線。

## 5. 修改、測試及驗收

僅`backend/scripts/chg291_v049_live_backup.py`、同名tests及規格/追溯/結果文件。
任務順序：新增有界collector/custody → 顯式入口 → target-only模板/transaction
→ 真實窄案例 → 原全套及coverage → RESULT/EVIDENCE與六步狀態。

起點script SHA：`41913e710cf307f66be154d9d36d30fc41f0d8c67d137791ae45c8389eec5b42`。
起點test SHA：`59b20dd4804a2be2ea4f847b7c0c7786f1d3aae1e1c9dfb20bf876e17dc71c30`。
不沿用R5 coverage作新程式證據。

| Case | 真實可觀察驗收 |
| --- | --- |
| V49-U-T41 | 同snapshot完整41筆typed member/comment state/body/hash及bound sidecar；實際PG移除/非空、多byte/長度邊界與總量超限拒絕；無截斷/正文log |
| V49-U-T42 | 原兩個R5自訂member-comment場景只顯式改用新模式，保留來源與完整成功斷言；plpgsql keep/recreate、table/sequence/large-object/ACL、六類/raw/catalog全等；原一般baseline/T15/default不退化 |
| V49-U-T43 | 真實函式overload、language、原預設註解/刪除註解、Unicode/換行/引號/反斜線/SQL-looking純文字往返；沒有SQL注入副作用，不改正文或跨物件套用 |
| V49-U-T44 | 真實私有檔案替換/權限/inode/hash/正文漂移、錯typed identity/membership/綁定、legacy/LiveSource模式混用拒絕；重新計算不可信payload hash不能取代export-time binding |
| V49-U-T45 | 真實target非comment差異、非member註解、缺少/額外物件/owner/definition/ACL錯誤在COMMENT前拒絕；修復後全catalog仍完整比較，舊R5未啟用模式仍嚴格拒絕自訂member註解缺失 |
| V49-U-T46 | 真實COMMENT批次中途SQL失敗/取消/逾時，驗證rollback、不可重用及exact cleanup；補R5 T39安裝transaction中途取消的專屬驗證，不用前置拒絕替代；原archive/所有綁定保持 |
| V49-U-T47 | 完整原套件加新案例PASS、zero意外skip/error；whole-tool statements/branches/combined各>=80%，同源原始報告/失敗輪次保留，Docker final inventory等於開始、零owned PG |

不得刪除/xfail原兩個FAIL，不能換成無comment的baseline取代；原source場景與
完整equal斷言不變，僅接上本次明確授權的新模式。另增舊模式負向保護，證明
不會默默使用COMMENT還原。保留human_gpg按非互動未加密範圍deselected。
不得mock/stub/fake passing behavior或放寬80%分母；使用真實PG、程序、私有
檔案及工具報告。共享PG案例須放原final cleanup前，standalone其後；窄選測
不得導致兩個容器同時存在。T46若因前置guard無法真的觸發中途取消，記未完成，
不能關掉production guard或假造通過。

## 6. 隔離與排除

Docker context desktop-linux，只使用已安裝固定PG image
`sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
pull never。沿用一容器、network none、無ports/host mounts/existing volumes/
docker socket；2CPU、4GiB memory/swap、pids256、PG tmpfs2GiB、tmp128MiB、
run16MiB、空initializer tmpfs1MiB、log none、core off。source256MiB/
archive512MiB/metadata4MiB/schema32MiB及R5時間上限不變。exact receipt清理。

不讀取現行Kubernetes/DB/支援服務；不新備份、qualification/qualified.json、
R2歷史archive或消耗過的claim；不scan/build/pull、Job/Helm/V049/部署、索引/
權限/會員/現行資料修改、Provider或使用對話密碼。R5歷史結果/證據不覆寫。
Gate4核准後，在此範圍連續完成，不為每個測試再問；碰到新增資料/權限/
策略/資源界線才停止。實際部署與現行備份仍需另行精確核准。

## 7. 命令與完成界線

本輪僅`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`及
`git diff --check`；`plan:approved`應因本R6 Gate4 pending拒絕。
Gate4後才跑`plan:approved`、`backend:syntax`及真實pytest/coverage：

```text
backend/.venv/bin/python -B -m coverage run --branch --include='*/chg291_v049_live_backup.py' \
  -m pytest -c /dev/null -q -s -p no:cacheprovider \
  backend/tests/test_chg291_v049_live_backup.py -k 'not human_gpg' \
  --junitxml=<private-r6-run>/tests.xml
```

`V49_BACKUP_ARTIFACTS`及`COVERAGE_FILE`設為新R6私有run及`.coverage.tests`；
XML/JSON/stdout同run0600，umask077。窄測試先跑，最終全套須同source；
code再改需重跑受影響與完整證據。若另作真實report guard補驗，只能使用本輪
同源實際報告，保留pytest-only數字與合併依據，不改舊artifact。

完整完成需T41..T47及原回歸/三種80%/嚴格比較/custody/cleanup均PASS。
這不能完成六步中的現行備份、全應用驗收、fresh部署基線/dry-run/V049或部署。
目前僅Gate3新計畫；feature tests NOT RUN、程式未改、現行環境未操作。

規劃輪實測：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`及
`git diff --check`皆exit0；`plan:approved`為預期exit1，明確回報active Gate4
pending，沒有以歷史核准代替。script/test SHA仍等於第5節起點。
只修改本計畫與SPECIFICATION/SPEC_CHANGELOG/DEVELOPMENT_PLAN/TEST_PLAN/
TRACEABILITY/六步進度文件；無feature test、容器、現行服務、備份或部署操作。

以上為核准前規劃輪紀錄。Peter後續`Ok`已核准本計畫並完成隔離實作/測試：
212PASS、0FAIL/ERROR/SKIP，1 human-GPG deselected；三種whole-tool coverage
82.5688%/82.5%/82.56%，原R5兩個場景完整相等，真實取消/timeout rollback及
清理/獨立audit PASS。中間44PASS/1FAIL的取消observer輪次完整保留。
詳見R6-RESULT/EVIDENCE。沒有接入現行資格入口、新備份、R2重播或部署。

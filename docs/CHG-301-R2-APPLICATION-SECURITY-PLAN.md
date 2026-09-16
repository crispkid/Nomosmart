# CHG-301 R2 Backend／Frontend 高風險修補與驗證計畫

2026-09-17 Asia/Taipei。規格§10.58 CMPAPP-001–004。
Peter以「對」完成Gate2。**Gate3 written；Gate4 approval: APPROVED。**
Peter於2026-09-17明確核准「核准 CHG-301 R2 Backend／Frontend 高風險修補與驗證計畫」。
核准前計畫SHA256：`fbdebef468750e575c532c3ac2fbd442ba497d4858288602b58437e1ccf21ae0`。
僅依本計畫界線執行；舊廣泛計畫不可代替本輪限縮範圍。

## 1. 目標與界線

只處理Backend／Frontend自身程式、套件、隨附runtime/OS/原生工具、所有實際
建置階段及最終映像的High/Critical。未修復／適用性未定仍阻擋；既有精確有效
接受明列，不自動展延。Medium/Low/Unspecified保留raw但不擴修。
同一Backend image用於Worker/Beat/bootstrap/readiness時共用精確artifact證據。

Redis、PostgreSQL、Neo4j、OpenSearch、RustFS、身分服務、edge Nginx、
Migration/Flyway、operator、Kubernetes等獨立週邊不新增掃描升級修補。
其既有告警與Sentinel失敗標DEFERRED_PERIPHERAL_BY_USER，不再阻擋本輪PR。
不撤銷原先已核准的RustFS修補，不把週邊改標安全；應用自身相同套件不排除。
不新增產品功能、native binary打包形式、改API/權限/SQL、部署或呼叫Provider。

## 2. 起點與驗收

[前轮收據](CHG-301-R2-FORMAL-DEPENDENCY-EVIDENCE.json) SHA256：
`810c580bfdecd3b356bba283e763ce89e1d4db1e328ecc17fe9cd38abfb9840b`。
ARM64 Frontend runner/builder全severity0；Backend runner High0/Critical0，
builder剩127High/5Critical，關聯linux source package及linux-libc-dev標頭。
這些是既有掃描，不推論全部可利用或全部不適用。既有3個FTP SAST High接受
只在其artifact/source/用途/期限仍相符時沿用。CLI實測未完成；12個暫存映像未清。

通過條件：應用範圍來源/平台/階段帳列完整，High/Critical修復或具精確有效
接受，必要同來源真實驗證與清理通過。報告限定「本次證據範圍內無未處理
High/Critical」，不承諾絕對零風險、全系統安全、發布完成或其他平台已驗。
正式宣告的平台逐一盤點；ARM64與AMD64的builder/final分開綁定，不借另一
平台結果通過。既有報告只有hash/來源/platform一致才標歷史重用；缺證據未完成。

## 3. 三組工作

### A. 安全修復驗證工具與建立新基線

- 新scope runner與新0700證據目錄；不重設旧run期限或修改舊raw/XML/manifest。
  先以唯讀檢查現有source/merge/image/container/network及可用資源。
- 診斷前次資源保護及`os.killpg`權限失敗：記錄真實RSS、執行時間、child生命
  週期與signal target。不能先假定拒絕是誤報，不能sudo／調整系統權限重試。
- 輕量manifest只保存報告路徑/hash/摘要，完整raw另外保存；逐檔處理與有界
  記憶體，避免反覆複製大量locations。改善資料流，不提高8GiB上限或丟掉告警。
- 只對已驗證仍存活且屬本次啟動的child執行合法終止；退出race保留原錯誤。
  不重播舊PID/process-group signal、不殺未知程序。以真實短命本地程序測試
  正常退出/timeout/cleanup，不建立假的外部服務。重遇permission denial即停。

### B. Backend／Frontend 最小修補

- 先查Backend builder實際套件用途、鎖定依賴的安裝紀錄及官方wheel材料。
  只有證明`build-essential`／`libpq-dev`等不被該鎖定建置需要時，才從現有
  Dockerfile移除未使用工具；需在各交付平台做無編譯器的clean frozen install、
  真實import/CLI及必要回歸，SBOM證實相依閉包，不僅為降低掃描數而藏套件。
- 必要建置相依則保留，優先官方同系列／同OS安全patch，固定材料hash；不
  換distro、盲目升major或改應用鎖檔。若確須改鎖檔，先提出具體缺口討論。
- 如果只能提出「header-only不適用」，保留逐artifact/package/path/advisory
  證據，集中送人類核准；此計畫不是新NOT_AFFECTED或風險接受。
- Frontend已修npm、Backend已修uv與base pins先保持；新實物發現應用High/
  Critical時，只准必要官方相容patch與同來源回歸。無合格材料便停止該組。

### C. 必要驗證、精確清理與原PR

- 沿用公開npm/PyPI名稱/版本稽核同意，僅傳公開套件metadata，不傳source、
  文件、Secret或私有套件；SAST、secret hygiene、完整severity SARIF/SBOM與
  builder/final scan綁定本次來源。建置只送本機Docker最小allowlist context。
- 安全門檻通過才做非root、network-none、readonly、drop-all、no-new-privileges
  CLI/import測試（Node/Next/crypto、Python/FastAPI/uvicorn/OpenSSL及受影響工具）。
  不import會連資料庫的main、不啟動正式服務、不以CLI宣稱整個問答流程通過。
  需真實額外服務的必要測試標阻擋再議，不用mock、fake Provider或正式帳密代替。
- 保留前輪302個artifact/policy案例及10個部署契約案例的檢查目的和所有舊失敗
  XML；只調整歷史／current scope與新receipt定位，新增scope/工具/修補回歸。
  不重跑已排除週邊live tests，不刪歷史失敗、降低coverage或硬編成功。
- Cleanup先列exact ID/tag/label/owner，再刪本輪新資源；並限於前輪收據
  明列的12個遺留映像做跨run清理。每個均核實不在原基線、沒有任何現有容器
  使用、未增加他人tag/ref；無完整ownership證明不刪。只`image rm --no-prune`
  exact identity，不force/prune/down-v/reset；保留raw證據與既有BuildKit cache。
- 全部應用安全與必要回歸／精確清理通過後，才條件式更新
  [PR #1](https://github.com/crispkid/Nomosmart/pull/1)。讀取最新remote/head/main/
  CI/merge；維持原`fix/compose-method1-installer`分支，逐檔核對累積已核准
  變更及Secret/大檔/私人資料，普通commit/push、更新原PR說明。不force/main
  push、merge、release或deploy。未知變更、遠端漂移、不可分離部署觸發即停。
  既有週邊變更保留其原核准/未驗狀態，不新增週邊修改或宣稱完整週邊驗收。

## 4. 不變的執行保護

Gate4後新6h window，最後10min不接新工作；command≤20min/build≤30min，
同原因最多2次retry，一次一個build/scan。新run不修改／延長舊run或舊接受。
host/VM分開核實可用量；VM作業合計≤4CPU/8GiB、保留≥4CPU及max(8GiB,20%RAM)。
Buildx限制按per-step加總，不把per-step當整體。不能核實資源就停止重作業。
host執行樹RSS≤8GiB、scanner可降低Go soft heap/parallelism，不取消hard guard。
run≤40GiB、歷史artifacts≤80GiB、free≥100GiB；新診斷含實際peak與停止原因。

不改現有docker-desktop Kubernetes/Helm/daemon配置、不建立cluster或K8s Job，
不碰應用資料/PVC/Secret/identity/index/model/manifest、不呼叫Provider。
不privileged、host network、Docker socket mount、正式Secret或全域cleanup。
新建映像只唯一tag，不覆蓋現有tag、不push registry。新scope核准只允許安全
工具診斷修復，不繞過原權限拒絕；需要新增權限／major變更／新接受則停止討論。

## 5. 檔案、測試與交付

範圍：必要的`backend/Dockerfile`／`frontend/Dockerfile`、最小新增app-scope
驗證工具（`backend/scripts/chg301_r2_application_*.py`或等價既有工具補充）、
相應`backend/tests/test_chg301_r2_application_*.py`、既有CHG301契約測試、
`deploy/README.md`、本計畫RESULT/EVIDENCE及五份治理文件。
舊執行器的scope拒絕／deadline不繞過；任何設計變更先更新spec/change record。

測試CMPAPP-T01..T08見TEST_PLAN；保留80%全應用門檻，但本次review仍延期
完整coverage/E2E/Kubernetes，逐項寫NOTRUN／BLOCKED，不冒充release acceptance。
命令：`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、`test:plan`、
`backend:syntax`、`helm:lint`、`deploy:config-policy`；Compose只安全example／
`COMPOSE_DISABLE_ENV_FILE=1`與`config --no-env-resolution --quiet`；必要隔離pytest
使用`--noconftest -c /dev/null`，不得連現行服務。前端受影響build/lint與
實際artifact/runtime命令在run內固定、記hash/exit/time/resource/cleanup。

交付：應用已修／未解清單、stage/platform安全證據、真實驗證結果、清理收據、
明確週邊排除及既有例外、PR是否達標。不把「排除週邊」寫成「全系統無漏洞」。

建議核准文字：**核准 CHG-301 R2 Backend／Frontend 高風險修補與驗證計畫**。
核准涵蓋上述必要應用修補、隔離build/scan/CLI、工具安全修復、exact-owned
清理及條件式原PR更新；不涵蓋新風險接受、現行部署或Provider呼叫。

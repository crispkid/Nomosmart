# CHG-301 R2 正式安裝依賴修補結果

2026-09-17 Asia/Taipei。**部分完成；剩餘項目阻擋，PR／現行部署尚未更新。**
規格 §10.58 CMPUPG-001–004；[核准計畫](CHG-301-R2-FORMAL-DEPENDENCY-REMEDIATION-PLAN.md)。
完整收據索引：[EVIDENCE.json](CHG-301-R2-FORMAL-DEPENDENCY-EVIDENCE.json)。
本輪24份完整映像掃描、11次建置；各次重跑分列，不當作24種不同產品。

## 已實作的修補

`deploy/rustfs/Dockerfile` 保留 RustFS `1.0.0-beta.10`、原 Secret helpers、
UID10001、ENTRYPOINT/CMD；固定官方多架構 base index，僅更新四個已安裝
Alpine3.24 套件：curl/libcurl `8.22.0-r0`、libssl3/libcrypto3 `3.5.8-r0`。
原有 su-exec 固定 `0.3-r0`。沒有升級 RustFS 產品線、改 API／SQL／正式資料。

最終 ARM64 image：
`sha256:6fa28038084883dc8dcffac55991101f8e11e74e309be88b3abf6541815a53d0`。
同來源最終 scan **High0/Critical0**（Medium2/Low1/Unspecified1 保留）。
對照本輪同一官方 base 的18筆 High/Critical image-advisory rows 均不再命中；
不是宣稱整體正式安裝路徑已無漏洞，也不是拿不同用途的總數作相減。

真實私有服務驗證：缺 Secret 退出66、非 root UID10001、受信任 TLS 成功、
錯 hostname 拒絕、匿名 S3 403、簽章上傳/讀取/刪除 object 與 bucket。
`final-live.xml` 2 PASS（另含 Redis Compose ACL/queue）。未呼叫 Provider。
AMD64 的 RustFS final build/runtime，以及 Compose root-preparation 路徑尚未驗；
本次不以非 root helper 測試冒充完整 Compose／Helm 安裝。

Frontend Dockerfile 將官方 npm 建置工具 `11.19.0 → 11.19.1`，固定官方
tarball SHA256、核對 SHA512，停用 install scripts。其 bundled
brace-expansion/tar/ip-address 四筆 High 消除；應用 package-lock、Node24 與
Alpine3.24 不變。最終 ARM64 runner 與 builder 都是 **所有嚴重度0筆**：

- runner：`sha256:dcb458bcb1b84eb32b7ff27285cac4a64c8865fef9c413a4d000972dbe57197c`
- builder：`sha256:019596ae2e98a84afd281205d0b49200802ffe6211fe5b8d863ed2dbb68a3ed9`

Backend Dockerfile 固定既有 Ubuntu24.04 的官方 index；僅將建置用
`uv 0.11.8 → 0.11.33`，ARM64/AMD64 wheel 的官方 SHA256 allowlist 由
pip `--require-hashes` 強制核對，保留 `uv sync --frozen`。應用 uv.lock 不變。
原 uv binary 的五筆 High advisory IDs 已消除，不等於五個不同可利用漏洞。

- runner：`sha256:9ce90da4eaba0d28d1cf86cf051f661848ecccdc40f72780ed7de5aa7f421896`
  ，**High0/Critical0**，Medium50/Low9 保留。
- builder：`sha256:310661513e43be3aa36942aaa6ebf6626965a0b68dc49b71706beee95403beb8`
  ，**High127/Critical5 尚未解**；均關聯 Ubuntu linux source package，
  實際位置在 linux-libc-dev 標頭／套件紀錄。這不是證明容器含可執行的 Linux
  kernel，也不是已核准 NOT_AFFECTED。未移除 compiler/header 以隱藏告警。

以上是本輪三個 recipe 的精確變更；其餘328份追蹤來源、49份 SQL migration、
應用鎖檔與現有服務設定維持本輪開始時的內容。建置、靜態安全通過不等於
完成應用啟動驗證；最後的 CLI 驗證被工具層阻擋，詳下節。

## 官方候選盤點

各列是官方 ARM64 精確 child digest 的完整 SARIF/SPDX；非高風險保留但不修。
下表除 RustFS recipe 外，候選**未採用**，不修改版本宣告來冒充已通過。

| 候選 | High | Critical | 結果／阻擋 |
| --- | ---: | ---: | --- |
| Redis 7.4.11-alpine | 0 | 0 | ARM64／AMD64 靜態門檻通過；基本 ACL/queue PASS，多 Sentinel failover FAIL |
| Nginx 1.30.5-alpine | 1 | 0 | libxml2 CVE-2026-86140，scanner 無已修版本 |
| Keycloak 26.7.3 | 11 | 2 | Red Hat OS、Netty/JDBC 仍有告警；未自行接受 suffix 誤判假設 |
| Neo4j 5.26.30 | 5 | 0 | PCRE2/SQLite/zlib；官方候選仍非全數已修 |
| Flyway 13.7.0-alpine | 12 | 2 | OS/HttpCore/JDBC；不任意替換 vendor jar |
| PostgreSQL 18.4-alpine | 40 | 6 | OS/內附 Go 工具；相容 OS patch 無法單獨消除全部告警 |
| RustFS 原官方 base | 14 | 4 | 已用現有 Dockerfile 修補；最終映像0/0 |
| socat 1.8.0.1 | 11 | 1 | 官方映像未修；原交付無自有 recipe，不擅增衍生產品 |
| OpenSearch 2.19.6 base | 19 | 2 | Java 相依仍未解；不等同 Helm repository-s3 最終映像 |
| CNPG PostgreSQL 18.4 | 15 | 6 | Debian／內附相依；與 standalone 分開保留 |
| CNPG operator 1.30.0 | 8 | 1 | Go/gRPC；未自行 fork/rebuild operator |
| Barman plugin 0.14.0 | 12 | 1 | 內附 Go/gRPC；未套用新 manifest |
| Barman sidecar 0.14.0 | 8 | 1 | 分開掃描；不能借 plugin 結果通過 |

以上13個 base 候選共有182筆 High/Critical image-advisory rows，並非182個
已證實可利用的不同漏洞。RustFS修補後，其他11個候選仍有164筆；沒有新風險
豁免或新 NOT_AFFECTED 判定。未解組別只完成靜態分析，未啟動其服務。
舊16映像帳列、Helm客製映像、builder、其他平台及私有registry交付責任仍保留，
不能把本表當全部交付 artifact 的安全總帳。

## Redis 必要回歸發現

- Compose 原始啟動 command：缺 Secret 拒絕、驗證 PONG、匿名 NOAUTH、
  CONFIG/ACL NOPERM、SET/GET、LPUSH/BRPOP/DEL 通過。
- Helm 實際 render 的 data 與 Sentinel scripts：TLS、主從同步與資料複製通過；
  兩個 Sentinel 的故障切換未通過。第一次失敗與補齊副本探索前提後的重測皆保留。
- 日誌同時顯示 Docker 停容器後 DNS alias 消失，解析等待觸發 Sentinel TILT。
  因此不能把全部 timeout 單獨歸因於產品。
- 但 chart 確實關閉 `default` user，且缺少 Sentinel 彼此連線用的
  `sentinel sentinel-user`／`sentinel sentinel-pass`。已設定的
  `sentinel auth-user/auth-pass` 只負責連到 Redis data nodes，不是 peer 登入。
  這是待修／待獨立證實的既有設定缺口，沒有在本輪擅改身份契約。
  [Redis 官方說明](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/#sentinel-access-control-list-authentication)。

下一輪應先固定隔離 DNS／故障注入條件，验证 peer 認證、quorum、多 Sentinel
選舉及 failover；保留 TLS、既有最小權限及正式環境不變，不能以降低 quorum
或關閉 authentication 取得 PASS。Redis 版本宣告目前維持原值。

## 測試與執行限制

Run：`/private/tmp/chg301-r2-formal-ytnv04nm`；原 deadline不重設。
所有 stage 的 raw findings、失敗 XML、唯一 image IDs、source/context hashes、
capacity 與 cleanup receipts 均保留。最終 machine-readable receipt：
`/private/tmp/chg301-r2-formal-ytnv04nm/analysis/final-evidence.json`。

已保留的中間失敗：歷史 approval test 271/272、SBOM 命名差異造成的293/294、
Redis failover兩次、RustFS唯讀rootfs缺少`/logs`兩次。修正測試前提／判讀後不抹除。
Registry SBOM 列 installed APK 名稱，local Scout另外列 source-package aliases；
套件相依閉包以建置中的實際 apk-info diff 驗證，不誤把 aliases 當新增套件。

最終 artifact/policy 回歸：**301 PASS / 1 FAIL**（`regression-final.xml`）。
原272個案例完整保留；唯一失敗是 application CLI receipt 缺少，不是已證實
應用功能故障，但仍不能算通過。另10個現有部署契約測試全部通過
（`deployment-contract.xml`）；RustFS 非 root assertion 更新為精確安全套件版本，
沒有刪測試或放寬權限要求。實際服務 `final-live.xml` 為2PASS；不與重跑案例
相加宣稱不同功能覆蓋，也不把檢查失敗證據的 PASS 當原失敗服務已修好。

Backend builder 的首次新版 SARIF 掃描被原資源保護中止；保留零位元未完成
report。一次 bounded retry 使用 Go soft heap2GiB/GOGC50/GOMAXPROCS2，仍有
原8GiB/20min硬保護，已完整產出 scan/SBOM；沒有提高上限或重設期限。
後續 application CLI 工具在唯讀 baseline 階段再次觸發資源保護，終止子程序
收到 `PermissionError: Operation not permitted`。**未重試或繞過拒絕，尚未
建立任何 application CLI 容器**。工具保留待診斷；完整錯誤與缺少結果的
測試失敗皆明列，沒有製造通過 receipt。

獨立唯讀收尾確認：14個原 Docker 容器的 ID/狀態/啟動時間/restart count、
所有原網路與原映像都不變。先前真實服務測試容器、internal networks、
capacity probes 與19個早期遺留的本輪測試憑證均已按 exact-owned receipts 清理。
**12個本輪新建／拉取映像尚保留**；因工具權限阻擋，最終 image cleanup 未執行。
不能宣稱 Docker images 完全回復基線。未 prune BuildKit cache、未碰既有備份。

新增工具 Bandit High0；非高風險 Medium/Low 原始結果保留，依核准範圍不擴修。
九項 harness 均通過：`spec:doctor`、`spec:trace`、`plan:doctor`、
`plan:approved`、`test:plan`、`backend:syntax`、`helm:lint`、
`deploy:config-policy`、`docker:config`。Compose 禁止載入操作員 env 並使用
`--no-env-resolution --quiet`。732份 tracked files 加本輪補充檔案的既有
source hygiene 規則檢查通過；不是宣稱完整機密掃描或全應用80% coverage通過。

第一個 Frontend 建置使用每 step2CPU/4GiB，未完整證明平行 steps 的合計保留量；
這項資源證據缺口保留，不當作 resource acceptance PASS。後續使用每步1CPU/2GiB，
按 source-bound Dockerfile DAG 的最大平行步驟數預留合計資源，沒有修改 daemon。
參考 [Docker Buildx resource 說明](https://docs.docker.com/reference/cli/docker/buildx/build/#resource)。

完整应用80% coverage、E2E、Kubernetes實測仍延期且不是PASS。未套用Helm、
未建立Kubernetes Job、未修改SQL或應用資料，未呼叫Provider。正式用途的未解
High/Critical與必要回歸缺口仍阻擋原PR更新；不是發布、合併或部署核准。

## 剩餘決策（集中處理）

1. 先診斷驗證工具資源／程序終止錯誤，確認允許的執行方式後，補 CLI 與
   本輪12個精確映像清理；不可用取消限制、全域 prune 或偽造 receipt 代替。
2. 另定 Redis Sentinel peer authentication 與忠實故障注入的修補範圍，
   不降低 quorum、TLS 或權限；目前版本不先升。
3. 其餘官方元件及 Backend headers 的告警做精確適用性審查；無合格官方材料
   或需新接受時集中提案，不能擅自替換 vendor jar、fork operator 或忽略 finding。
4. 缺少的其他平台／final artifacts／必要整合證據仍阻擋；本輪不啟用延期的
   Kubernetes、全應用 coverage/E2E，也不更新 PR／部署。

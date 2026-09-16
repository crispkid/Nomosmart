# CHG-301：PR #1 安裝修正整合計畫

2026-09-15。Gate2方向確認：Peter「好，根據你的建議做」。
**Gate3完成；Peter於2026-09-15以「核准 CHG-301 實作與隔離測試計畫」核准Gate4。**
以下計畫範圍不變；底部NOT RUN/PENDING為核准前歷史，實際結果另記verification。
規格：SPECIFICATION.md §10.58 CMPSTART-001..005。

2026-09-15後續：Peter要求完整coverage、Kubernetes實測、資安檢查後才更新PR，
並確認獨立叢集/現行部署不變/付費模型另核准（R2 Gate2）。
[R2完整驗證計畫](CHG-301-R2-FULL-VERIFICATION-PLAN.md)已寫妥，R2 Gate4待核准。
本文件保留為先前已執行範圍的紀錄；不能以本文件原Gate4提前執行新叢集/掃描，
也不能再依本文件「有完整發布缺口仍可更新PR」選項提前推送。

2026-09-15補充：Peter以「允許」核准下載既有Compose指定的
`opensearchproject/opensearch:2.19.1`，僅用於上述隔離測試，並繼續原計畫。
隔離完整啟動測試保留真實service命令、初始化/健康依赖與TLS；不啟動無關
Frontend/edge/finalize/debug服務、不開host ports。為明確限制測試資料量，
只在隔離副本將stateful data volumes改為有size上限的tmpfs（總和小於10GiB）；
這不修改交付Compose，亦不冒充持久volume復原測試。PG持久volume重啟已由
前一批獨立測試驗證。完整服務memory/cpu limits總和低於16GiB/8CPU。

## 1. 已核對的來源與問題

- GitHub PR #1：`Fix/compose method1 installer`，同repo分支
  `fix/compose-method1-installer`，head
  `c261a494283835af57c0e0678afc7ee7e2c0dcc8`。
- 最新main：`5f1a0a2505dee9c85ee621bd2c8680b92d397a45`；共同祖先
  `bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3`。PR有5個獨有提交，落後main1個。
- PR有9檔/231新增/22刪除，沒有GitHub check-run或review通過紀錄。
  這些是查詢當下結果，不是永久基線；執行/推送前需重查。
- 五項修正方向保留：缺minikube不阻擋Compose；OpenSearch強密碼；
  owner-only Secret可讀性；Worker/Backend循環等待；wrapper保留CMD/umask。
- 阻擋直接採用的問題：PR共用Migration image全域設定NOMOSMART_RUN_AS，
  wrapper卻要求root；現有Helm強制UID10001，因此會走非root拒絕路徑。
  PR也把部分Secret副本設0444，並使用任意copy mapping/完整printenv，不能照搬。
- 最新main含Flyway13.6.0 pinned digest與V049 version/checksum gate，不能用
  PR的舊檔案整份取代。DEPLOY-019固定密碼與DEPLOY-020僅Docker Desktop例外，
  需明訂本次只擴充Compose fresh generation，不改其他Helm profile。
- PR的fake subprocess/monkeypatch成功測試不符合TEST-002，需真實替代。

## 2. 精確範圍與設計

### A. Git 整合

Gate4後fetch精確remote main/PR，確認SHA無漂移、local source未被他人修改。
在PR分支的本機工作分支整合最新main，保留作者與原提交；不reset、不rebase
他人歷史、不force-push、不在main實作。每個重疊檔逐段處理，保留CHG-300設定。
本計畫允許通過相關驗證後，以一般fast-forward push更新**原PR分支**及安全
測試說明；若remote新增提交、protected workflow或權限拒絕則停止，不能繞過。
不批准合併PR、close PR、直接push main、GitHub Release或部署。

### B. Preflight / 新套件 Secret

只針對minikube executable不存在作正常「未啟動」判定；其他檢查仍實際執行，
不得停用互斥runtime/host/port安全檢查。既有其他return/error行為若需擴充先列明。
新Compose套件OpenSearch admin/service用既有strong generator產生不同值；
不改其他周邊帳密、其他Helm profile或operator值。已存在package第二次init
保持bytes/hash，不自動輪替舊弱密碼；若需rotation，報告而非執行。
調整對應非敏感credential描述與runbook，不將Secret輸出給一般log/receipt。

### C. Compose 與 Kubernetes 分開啟動

新增明確Compose-only preparation wrapper；由Compose設定user/entrypoint啟用，
共用映像預設仍非root，不加入全域必須root的ENV。共用secret-env entrypoint
仍能直接在UID10001下執行；Helm的securityContext/capabilities/Secret方式不改。

Compose root階段只複製該service已掛載且列於allowlist的Secret/TLS至固定
container-private tmpfs；Secret0400、目錄限制、指定目標UID/GID。來源必須是
普通檔案，不跟隨symlink/跨來源，不放寬host0600、不寫回readonly mount。
不使用任意mapping、任意recursive chown/rm、完整printenv或env dump。
只重映射明列欄位，包含應用COMPOSE_SECRET_MOUNT_ROOT，確保runtime resolver
也能讀到副本，不只是某一個啟動程式可讀。只複製必要Secret，不擴張admin權限。
降權失敗就停止，禁止改成root服務或chmod0444。實際private-key/CA權限分開。

PostgreSQL使用其image內已存在的postgres UID/GID，讓上游entrypoint照原契約
初始化/降權；明確保留postgres CMD與原umask，既有PGDATA不chown成application
UID。RustFS保留真正entrypoint/CMD並僅在Compose準備其TLS。依映像實際工具
選用既有setpriv或加入必要su-exec，缺工具fail closed；不降級Flyway/依賴。

### D. 啟動順序

Worker/Beat改為直接依賴migration與必要bootstrap成功、broker可用；移除
依賴Backend已healthy的循環。Backend readiness仍確認真實Worker心跳，不
取消health gate。不能只改service_started而繞過初始化或V049 gate。
保留UVicorn/PostgreSQL/Worker/Beat/Flyway/RustFS的真實command、signal/exit。
不改SQL、schema、角色、業務API或現行資料。

## 3. 預計修改檔案

| 範圍 | 檔案/目的 |
| --- | --- |
| Package | deploy/package/nomosmart_package.py：preflight、新Compose credential條件與冪等 |
| Entry point | deploy/docker/secret-env-entrypoint.sh及新Compose-only helper：預設非root與窄權限準備 |
| Compose | docker-compose.yml：private tmpfs、明列remap、UID/CMD、無循環依賴 |
| Images | deploy/migrations/Dockerfile、deploy/postgresql/Dockerfile、deploy/rustfs/Dockerfile；backend/Dockerfile只限必要降權工具，保留default USER與base |
| Tests | test_chg229_full_stack_deployment.py、test_chg231_deployment_initialization.py、test_chg242_secret_packaging.py；新增CHG-301真實entrypoint/隔離驗證與精確清理測試 |
| Docs | deploy/README.md及本計畫/verification；本機spec/changelog/plan/test/trace |

不修改Frontend、V001–V049、現行Helm安全template或應用功能。若需要超出以上
範圍、不同依賴版本或新發布機制，先說明而非擅自吸收。

## 4. 隔離驗證與資源界線（核准後才執行）

2026-09-15完整Compose驗證發現：override entrypoint會清除image預設CMD，
單獨docker run的PostgreSQL測試未涵蓋此差異。依既有CMPSTART-003/004
「保留postgres最終CMD」要求，在Compose明列command: [postgres]，並以
實際Compose新裝與重跑回歸；不放寬wrapper command allowlist或安全限制。

實作細節（2026-09-15，既有核准範圍內）：private tmpfs及其子目錄由root
持有、service群組僅有0710穿越權，0400副本由目標service持有；service不能
替換目錄/檔案路徑。再次準備時只更新固定allowlist、單一link的普通檔案，
拒絕symlink或不符owner，以支援重啟且不任意刪除。加入兩個Dockerfile專屬
.dockerignore與root allowlist，避免deploy build context包含生成Secret；
只准所需Dockerfile、init SQL/shell及兩個entrypoint進入測試建置context。

CMPSTART-T01..T09詳見TEST_PLAN。先真實檔案/程序，再容器/服務，最後回歸。
不使用fake command、monkeypatch成功路徑、mock API或手填migration成功紀錄。

- 自建臨時目錄0700、合成且隨機的測試Secret0600；不讀取目前generated/env/
  kubeconfig正文/備份或任何current service credential；不使用現行資料庫/身分。
- 允許本機**測試用途**候選映像build，使用獨立CHG-301 test tags，不能覆蓋
  已部署tag/ID，不push registry。保持既有pinned基底；若缺必要映像/套件或
  需新版本/受限網路權限，標示blocked再處理，不以舊映像冒充新程式驗證。
- Docker測試只建立run-owned容器/network/volumes，逐一記錄ID/label；最多一套
  隔離stack，同時不超過8CPU/16GiB RAM、測試磁碟上限10GiB，每case20分鐘、
  整批90分鐘。只容器內部網路，不佔用host80/443、不裝Docker socket進容器。
  預檢不足就停止，不回收/停止目前Docker Desktop Kubernetes或其他服務騰空間。
- 真實package/Secret/Process UID、PostgreSQL新裝與同volume重啟、OpenSearch
  實際密碼admission、Compose真實初始化/Worker readiness與失敗gate測試。
  初始化測試只建立隔離realm/bucket/index等，不能連外部identity或Provider。
- 候選Migration在真實UID10001、cap-drop、no-new-privileges與可行read-only
  rootfs下跑；Helm lint/render保留原securityContext。此非root容器證據
  **不是完整Kubernetes live安裝**。本計畫不建立/寫入現行或新叢集；需要完整
  Helm live驗收時列明缺口，不能借用docker-desktop現行namespace。
- 精確ID cleanup僅處理本run建立的資源；不docker system prune、不刪本機
  source/runtime package、不廣泛down -v。失敗保留不含Secret摘要，private
  Secret依短暫測試保管/清理；輸出不包含值/整份環境、token或文件內容。
- 保留測試失敗與security/coverage未完成項；新套件不可沿用CHG-300一次性
  部署風險豁免。沒有重新掃描/正式映像發布/現行部署授權。

驗證命令：治理spec:doctor/spec:trace/plan:doctor/plan:approved/test:plan；
核准後backend:syntax、docker:config、helm:lint、deploy:config-policy，
真實pytest/isolated runner與coverage。先檢查既有harness不會讀現行secret；
需要服務的命令必須提供隔離設定，不直接拿目前Compose env跑。
量測受影響Python/application與helper行為，維持既有80% gate；未達/缺完整
coverage如實回報，不靠純字串assertion或既有mock案例抵銷。

## 5. 成功、失敗與交付

交付包含：最終commit/source hashes、五項修正的真實驗證、原本非root失敗
路徑的修正前/後結果、Secret與初始化保護、來源及資源清理、未完成Kubernetes
live/完整coverage/security項；不宣稱測試全過或可直接正式部署。
相關驗證未通過不得push「修復完成」或合併。驗證通過但完整發布門檻仍缺，
可只更新原PR分支並明列缺口，PR維持open待審，不觸發自動合併。
任何GitHub branch/protected rule拒絕即停止，不force、不另開branch繞過。
現行main、revision37、V049、PVC/Secret/Ingress/identity/data/index均不動。

本輪已做：readonly repo/PR/spec核對及計畫/規格/測試設計。尚未做：程式修改、
branch integration、建置、功能測試、GitHub寫入、合併或部署。
下一必要停點是本精確計畫的Gate4，不重問已接受的修正方向。

治理驗證：spec:doctor、spec:trace（5條requirements）、plan:doctor、test:plan
與git diff --check通過；plan:approved因Gate4仍PENDING而拒絕，符合停點。
首次檢查另指出Gate4標題缺空白而未識別canonical格式，已只修正文書格式；
沒有偽造核准或因此執行功能測試。

# CHG-301 R2：完整測試、獨立 Kubernetes 與資安驗證計畫

日期：2026-09-15。Gate 2 confirmed：Peter 已確認「同意使用獨立測試叢集、不動目前部署；若需要付費模型呼叫，另外確認」。
Gate 3：本計畫已寫妥。**Gate 4 approval: APPROVED**。
Peter approved Gate 4 on 2026-09-15 with「核准 CHG-301 R2 完整驗證計畫」。
核准前計畫SHA-256：344f06b167b072959ad90a73a8439a271fcd3607675e3d979f00f7cf0ccc2a85。
既有 CHG-301 核准與測試結果保留；不能拿原計畫核准代替本次 Gate 4。

### 2026-09-15 入口相容性附註（方向確認，執行待核准）

退休 NGINX 候選的安全停點仍保留。Peter 以「同意」確認只在獨立測試環境
評估 Traefik NGINX 相容模式；具體新增範圍見
[Traefik 隔離驗證計畫](CHG-301-R2-TRAEFIK-PLAN.md)。Peter 隨後於2026-09-15
以「OK」核准該書面附註的新 Gate4，僅於原隔離／資源界線內取代 §C.6 的候選
選型，其餘 R2 gates 及原始失敗證據不變。不是現行環境遷移或漏洞豁免。

### 2026-09-15 安全修正附註（已核准既有最小方案）

Peter以「同意升級pytest，接收明文風險」核准上一輪已說明的pytest9.0.3
最小修正與FTP保留／明文風險接受，解除該兩項停點。此附註只覆寫以下範圍：

1. `backend/pyproject.toml` dev pytest固定9.0.3；由uv僅針對pytest更新lock，
   結構化核對其他套件記錄與production frozen export不變。新venv驗證
   pytest-cov6.3.0／原81套件回歸及新安全分類測試；不改原venv或80%門檻。
2. `remote_sources.py` SHA256=338c6ae58c299e7f9bdb60b9f79d8234446d864cbaa18de1cf8d162da418c3a5
   的B402第4行、B321第86/111行是已核准FTP風險。原因：保留既有FTP相容性；
   後果：帳密/檔案無加密，可遭流量觀察或竄改。只限定CHG-301 R2候選來源，
   不擴及新增FTP功能、其他漏洞、Provider、其他版本或現行環境操作。
3. 在去敏感JSON記錄核准原文、日期、規格、位置及hash。仍完整掃描、不新增nosec；
   分開記raw High與ACCEPTED_RISK。任何新High/Critical、hash/位置變動都需重新討論。
   用純政策輸入及真實本機來源檔測試精確匹配／拒絕擴張，不mock外部行為。
4. 新掃描與舊FAIL分開保留，更新traceability；其餘完整suite、coverage、Kubernetes、
   image/SBOM與PR gates沿用原核准計畫。這不是上述未完成項目的豁免。

此附註記錄對已呈現方案的核准，不增加未經討論的產品或環境範圍。

## 1. 目標、來源與完成界線

先完成同一候選來源的完整 Frontend/Backend 測試及覆蓋率、獨立 Kubernetes
實測與資安檢查，全部符合以下條件後，才更新原 GitHub PR #1。
不合併 PR、不直接更新 main、不發布映像或 Release、不更新目前部署。

- 規格：SPECIFICATION §10.58 CMPSTART-001..005、CMPVERIFY-001..006，
  以及既有 TEST-002/004、DEPSEC-002。
- 本機分支：`fix/compose-method1-installer`；HEAD
  `c261a494283835af57c0e0678afc7ee7e2c0dcc8`，正在整合 main
  `5f1a0a2505dee9c85ee621bd2c8680b92d397a45`，尚未提交/推送。
- 原本81套件測試、19容器案例、3個 Compose 流程及套件86.56%結果保持原範圍，
  不能當作全系統覆蓋率。原始失敗保留於 CHG-301-VERIFICATION.md。
- Kubernetes 實測限定本機獨立測試叢集的安裝/升級/重啟/初始化/安全性；
  不是正式多機房 HA、Longhorn、效能或真實現行環境的驗收。

## 2. 本次核准涵蓋及不涵蓋的工作

Gate 4 後可建立測試工具、補足真實測試、修正測試隔離/來源綁定/量測方式，
建置本機候選映像、下載必要已鎖定版本的測試依賴/映像/漏洞資料庫，
建立及清除唯一 run-owned 叢集與合成資料，執行以下全部非 Provider 驗證。
允許合成帳號、角色、專案、文件及測試寫入，但只能發生在本次獨立服務內。

不授權修改產品行為、API/權限規則、SQL V001–V049、production Helm 安全模板、
依賴版本/基底升級、既有資料、現行 Secret、現行 runtime/CNI、主機 DNS/hosts/
信任庫/防火牆/核心參數或 Docker Desktop 設定。若驗證發現需要這些修正，
先交付可重現問題、影響與方案，由 Peter 決定；不得默默吸收為測試修補。
不讀取現行 `.env`、generated package、備份、模型 credential 或私人 keyring。
不使用過去 Provider/部署/風險豁免作為本次授權。

## 3. 一次性執行順序

### A. 來源、工具與隔離預檢

1. 綁定 HEAD、merge parent、dirty diff、完整測試清單、鎖檔、chart、SQL、
   工具版本及 SHA-256；有其他作者的新修改時不得覆蓋。
2. 唯讀確認 Docker daemon/資源容量及既有容器 ID、啟動時間、重啟計數、
   網路 ID、映像 tag→ID。只取非敏感 inventory，不讀容器 Env 或 Secret。
3. 原始碼副本只用明確 allowlist，保留測試需要的 repo 結構及來源綁定；
   排除 `.env`、generated、backup、credential、node_modules、venv 和舊報告。
   程式在隔離副本中自行產生測試設定，不能複製任何現行設定/身分。
4. 確認完整 suite 的服務/Provider 依賴，再執行。Backend 現有 live suite 在
   import 階段會讀 `.env`/取得 Keycloak token，禁止先在原工作目錄盲跑 collection。
5. 本機有 kind v0.32.0、kubectl、Helm、Docker、Node/npm、uv/uvx；可用性、
   Docker 容量與 scanner 帳戶權限仍以執行時預檢為準，現在未建立叢集。

### B. 補足完整測試與覆蓋率

- 使用真實 PostgreSQL、Redis/Celery、Keycloak、LDAP、OpenSearch、Neo4j、
  RustFS/S3；需要 remote-source 行為的案例使用本 run 的 HTTP/SFTP/FTP(S)
  測試服務。保留完整案例清單，不因缺服務而刪除、排除或改成假成功。
- 完整 Frontend 含 contract、component、實際 Browser geometry 與 live E2E；
  完整 Backend 使用既有全 suite 與真實整合測試，必要時新增缺少的測試。
- 現有 `componentSetup.ts` 有 no-op ResizeObserver/matchMedia/scrollTo，部分
  component 測試有 spy/mock。只做靜態 pattern guard 不足以證明符合 TEST-002：
  改成真實 Browser API/真實服務或真實純函式輸入；保留原 assertions 的語意。
  不以 no-op API 驗證幾何、權限或網路行為。無法真實執行的案例記 BLOCKED。
- 完整量測範圍是 `frontend/src/**/*.{ts,tsx}`、`backend/app`。現有排除
  `frontend/src/app/api/**` 與 `backend/app/db/models.py` 在 R2 完整量測中取消，
  不新增 exclusions、不縮小分母、不降低80%。type-only/工具無法插樁的檔案
  要列明原因，不能把可執行業務檔案藏起來。
- Frontend lines/statements/functions/branches、Backend lines/branches 各>=80%；
  原套件全模組80% gate保留且重跑。達到百分比不能抵銷 critical-flow 失敗。
- 補足 Auth/OIDC、disabled user、權限 union/Owner/Editor、review、import、
  chat ownership、Secret/config、migration/rollback 等 critical-flow 覆蓋。
- 使用 canonical harness 與 machine-generated source/test manifest。隔離執行
  的來源、量測報告、完整案例結果要可驗證回本機 exact bytes；不能手填成功
  manifest 或把局部/舊報告放到全 suite 的路徑。只有完整 run 成功才記 full-suite
  evidence；來源改變後受影響證據失效，最終兩端均須同一候選來源。
- 允許調整測試設定與量測 orchestration 來執行真實 Browser/跨程序 coverage；
  必須有固定完整清單、未執行案例檢查、來源 hash 和失敗範例，不放寬 evidence guard。

### C. 獨立 Kubernetes 實測

1. 建立一套 `chg301-r2-<run-id>` kind 叢集，1 control-plane、2 workers。
   專用0700目錄、0600 kubeconfig、唯一 network/namespace/release，API只監聽
   `127.0.0.1`高位隨機埠。每個 kubectl/Helm 命令都顯式指定此 kubeconfig/context；
   變更前比對 API server、cluster/kube-system UID 與 namespace UID。
   不寫使用者預設 kubeconfig，不切換其 current-context。
2. kind node 是 privileged container，與 Docker Desktop VM 共用資源/核心；
   不是物理隔離或零影響保證。使用唯一 Docker bridge，禁止接上現有叢集網路。
   kind 的 network override 為 experimental：先核對已安裝版本行為與 identity，
   若不能證明獨立網路則停止，不回退到共用 network、不修改 daemon 設定。
3. 使用能實際強制 NetworkPolicy 的 Cilium（候選官方1.20.1），只安裝於測試
   叢集；保留 kube-proxy，不要求修改宿主 kernel/sysctl。執行前綁定版本、
   官方來源、chart/image digest及相容性，失配/容量不足即停止。
   kind node映像使用 kind v0.32.0 官方相容版本，下載前記錄 immutable digest。
4. 以 checked-in chart 的 bundled 單實例服務組態驗證，保留 TLS、nonroot、
   capabilities、readiness、migration/checksum/bootstrap gate及 NetworkPolicy。
   不拿縮小版冒充 production HA。候選 PG/Redis/RustFS/OpenSearch/Neo4j/Keycloak
   全是真實服務；附加 LDAP/remote-source 也只能是測試資源。
5. 允許 run-owned local storage class、PV/PVC、Secrets、ConfigMaps、ServiceAccount/
   RBAC、NetworkPolicy、Ingress/controller、Jobs、Deployments、StatefulSets。
   只為測試調整 release/host、映像、storage class、小型容量、排程與資源值，
   每個 overlay 均列入 render/diff evidence；不移除產品安全 gate。
6. chart要求的 nginx相容 ingress/controller 必須固定來源/版本/digest並掃描；
   無安全可用版本時記阻擋，不擅自換成不同 ingress 技術或停用 TLS。只開
   loopback 高位 port-forward，使用合成 hostname 與每次測試的 CA；只在 run-owned
   Browser profile 信任該 CA，禁止 ignore-certificate-errors 或全域信任庫變更。
7. 真實驗收：fresh Helm install與V049實際執行、Jobs成功、readiness/Worker heartbeat、
   OIDC登入/拒絕、Frontend→Backend→服務跨節點請求、Secret最小權限及實際程序UID。
   候選應用映像使用完整建置內容，不用挂載修改後程式冒充該映像驗收。
8. 真實 upgrade/repeated-up、單一測試 Pod重建、同PVC資料保存；以第二個測試
   namespace/release依序驗證 migration credential failure、bootstrap checksum
   failure及依賴阻擋。注入失敗的只能是測試設定，不修改SQL或寫假的成功紀錄。
   rollback只回到本 run 中已驗證、相容同schema的release；不使用Helm回退假裝DB可逆。
9. NetworkPolicy要有真實 allowed/denied雙向證據，TLS要有信任與拒絕證據；
   不刪policy讓ready變綠。預期拒絕案例必須核對拒絕原因，不把任意失敗算成功。

### D. 候選映像、資安與 SBOM

- 將來源建置為唯一 `chg301-r2-<run-id>`本機tag。涵蓋Backend、Frontend、Migration，
  及納入當前helper/chart的PG、RustFS、Keycloak、OpenSearch自建映像。
  Worker/Beat使用同Backend。不得覆寫現有tag或push registry。
- 所有實測映像（含第三方Redis、Neo4j與測試叢集node/CNI/controller）登錄
  image ID/digest/architecture/來源並掃描；自建應用用 exact local image ID驗收。
  Dockerfile/lock既有版本不因掃描自動升降級。未固定tag先解析並綁定digest，
  同一run中漂移則失效重查，不以新base冒充舊候選的結果。
- 相依檢查：npm audit production及含dev完整集合、uv frozen export＋pip-audit；
  記錄npm/uv/Python/Node/scanner版本，不用audit fix或自動改lock。
- 靜態檢查：既有Bandit backend/installer/release gate，補查package/helper相關
  shell與Secret/權限風險。檢查source/build-context/映像中的敏感資料只記路徑、
  類型和redacted發現，不輸出值；不掃描operator目錄或現行容器filesystem。
- 容器：Docker Scout local analysis及SPDX SBOM，保存all-severity結果並獨立
  enforce High/Critical gate。包含OS、Python/npm、Java及Node內嵌OpenSSL等
  runtime構件；工具辨识不到的項目另查官方公告，不以「沒有命中」當作無風險。
- npm/pip audit需向漏洞服務傳送套件名稱/版本；Scout local analysis會傳PURLs
  和layer digests。只允許本候選的依賴metadata查詢，不啟用repository/runtime
  integration、不上傳來源/完整映像/文件/Secret，不付費購買scanner額度。
- 漏洞資料須記錄查詢時間/資料庫版本；不可用、逾期、scanner失敗與掃描不支援
  皆記BLOCKED，不當PASS。不自動使用過去豁免；任何High/Critical都先列CVE、
  命中構件、可利用条件、修正版/補償措施供討論，沒有另行修復或風險核准不更新PR。

### E. 結果與原 PR 更新

交付同來源的全suite分母/案例清單/PASS-FAIL-BLOCKED-SKIP、coverage、
Kubernetes run/cluster/render/image證據、掃描與SBOM、原始失敗/重測對照及cleanup。
建立 `docs/CHG-301-R2-VERIFICATION.md` 與去敏感化 machine evidence。

只有完整 suite/critical flows、coverage、Kubernetes與資安全數符合條件且清理
通過，才重新唯讀確認remote main/PR head，保留他人變更，再一般提交/push原
PR分支及測試說明。未完成Provider案例或任何其他缺口都暫不更新PR。
remote漂移、protected workflow或權限拒絕即停止，不force-push、不合併、不部署。

## 4. 資源、時限、網路與清理界線

- 同時最多一套測試服務stack；三節點合計目標上限12CPU/24GiB，測試與build
  依序執行，不另啟完整Compose並行。預檢須在既有使用量之外保留至少4CPU/
  8GiB及20% RAM餘裕，否則停止。不可重設/擴大Docker VM或停現行服務。
- kind初始節點建立可能先於容器limit設定，不能宣稱全程硬限制；建立時監測，
  節點建立後立即對精確owned IDs設定limit，確認後才安裝workload。資源壓力
  超限時只停止/清理測試run。ResourceQuota及每Pod requests/limits亦須具備。
- 測試資料PVC總請求<=20GiB；新增映像/容器/測試資料磁碟增量監控上限80GiB，
  預留至少100GiB可用Docker磁碟。PVC容量不等於local-path硬quota，報告要如實
  區分宣告容量、實際占用與監控停止值，不把監測說成硬隔離。
- 叢集建立20分鐘、每次Helm/恢復20分鐘、每完整suite90分鐘、單映像build30分鐘、
  單scanner20分鐘；整批主動執行最多6小時、同原因最多2次修正重試。
  超時先保存去敏感摘要、精確清理並報告，不無限重試/靜默加資源。
- 工作流可以正常進度更新；只在Provider、新產品/依賴修正、權限拒絕、來源/資源
  安全條件失效或期限達到時停止討論，不逐項重問已核准的測試步驟。
- 專用0700 root保存0600測試Secret/kubeconfig及run manifest。開始時以實際
  ID/UID記錄容器、網路、叢集、namespace、release、PV/PVC、暫存檔及相關PID。
  所有資源必須能追溯到本run，僅靠名稱prefix不足以刪除。
- 數據清理先列exact-owned dry-run，依FK/外部reference清理合成資料；批准本
  計畫即批准這些manifest內測試資源的cleanup apply。再刪自己的release、namespace、
  叢集、空network與短期Secret，檢查Docker既有ID/重啟基線未受操作影響。
  kind自帶delete前也必須核對完整node ID集合，禁止down -v或system prune。
  若其他程序造成基線漂移，停止並報告，不能刪別人的新增資源來恢復相等。
- 只保留去敏感證據與明列本機test images；Secret/PVC合成資料可永久清除，
  不承諾可復原。失敗同樣執行cleanup；清理失敗本身就是驗收失敗。

## 5. Provider 的必要停點

完整 ingestion/chat/embedding/E2E可能需要真實模型，現階段預算是**零呼叫**。
執行前關閉未核准Provider網路出口，不複製現行模型或API key到新叢集。
需要時一次列出測試案例、模型/endpoint、測試資料、最多request/token/OCR頁數、
最高費用與credential使用/保管/清理方式供Peter核准。若不足以估算就先說明。
只有已核准範圍才能開必要egress；無credential/核准時可完成其餘測試，整體
狀態仍BLOCKED，不省略該案例、不改用假的OCR/向量/LLM。

## 6. 檔案與驗證對照

| 區域 | 預計改動/目的 |
| --- | --- |
| backend/scripts/chg301_r2_*.py | 新增受控preflight/source/cluster/test/image/security/evidence/cleanup orchestration；不依賴歷史tmp腳本或credential |
| backend/tests、frontend/tests | 既有真實完整suite、補缺critical/coverage案例、移除行為假替身，保留原契約與斷言 |
| backend/pyproject.toml、frontend/vitest.config.ts、frontend/package.json | 只限完整source量測、真實Browser與canonical suite接線；不改runtime dependency版本 |
| HARNESS/scripts及test notes | 必要時強化跨程序/Browser完整案例與source binding；不降低門檻或偽造manifest |
| docs/CHG-301-R2-*、本機治理檔 | Gate狀態、需求→測試、每run結果與風險 |
| run-owned temp root | 私密設定、render、測試cluster配套；去敏感allowlist後才可進報告 |

核准前只執行治理：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check`；`plan:approved`應拒絕目前PENDING狀態。
核准後執行：`test:frontend`、`test:backend`、`test:e2e`、`coverage:check`、
`frontend:lint`、`frontend:build`、`backend:syntax`、`docker:config`、`helm:lint`、
`deploy:config-policy`、`security:dependencies`、`security:static`、
`security:containers`、`security:sbom`及固定範圍R2 runner。
所有會連線/建置的既有命令必須先注入隔離環境/唯一tag，不能盲用default目標。

## 7. 參考與未執行聲明

- [kind配置](https://kind.sigs.k8s.io/docs/user/configuration/)：loopback API、多節點與共享主機限制。
- [kind Docker provider](https://github.com/kubernetes-sigs/kind/blob/main/pkg/cluster/internal/providers/docker/provider.go)：獨立network override的experimental警告；執行時要核對固定版本，不以main作不變基線。
- [Cilium kind安裝](https://docs.cilium.io/en/stable/installation/kind/)：停用預設CNI、NetworkPolicy相關真實網路驗收。
- [Scout資料處理](https://docs.docker.com/scout/deep-dive/data-handling/)：local analysis的metadata傳輸界線。

核准前只讀取程式、工具版本及官方文件並寫計畫。當時R2測試、下載、建置、掃描、
新叢集、任何Kubernetes/資料/Provider/GitHub寫入均 **NOT RUN**。

規劃驗證：`spec:doctor`、`spec:trace`（11條active需求映射）、`plan:doctor`、
`test:plan`及`git diff --check`通過；當時`plan:approved`因R2 Gate4 PENDING而拒絕，
符合停止界線。這些是文件/治理檢查，不是產品或部署測試。

# CHG-301 R2：獨立測試環境 Traefik 相容性計畫

2026-09-15。Gate 2 confirmed：Peter 以「同意」接受上一輪建議的
「Traefik 相容模式、僅限獨立測試環境」。Gate 3：本計畫已寫妥。
**Gate 4 approval: APPROVED**。Peter 於2026-09-15對書面計畫核准請求回覆「OK」。
核准前計畫 SHA256：`11a36a1c5ee3e5ec664cb628b2d088d69ce072b47aadec0de155e791d18733aa`。
下方保留規劃時的未執行紀錄；核准後依計畫界線開始執行，結果另外記錄。

本文件補充[原 R2 計畫](CHG-301-R2-FULL-VERIFICATION-PLAN.md)的 §C.6 入口選型，
並沿用其隔離／資源／測試／資安／清理限制；未明列變更的範圍全部不變。
原計畫及 pytest／FTP 的核准不視為新 controller 或新漏洞的核准。

## 1. 目標與不做的事

目標：以受維護的 Traefik NGINX 相容 provider，驗證 **同一份 NomoSmart chart**
的真實路由、TLS、IP 限制、OIDC、BFF 與 NetworkPolicy。需求為 §10.58
CMPING-001..005，測試為 TEST_PLAN 的 CMPING-T01..T08。

不做：

- 不切換／改動目前 docker-desktop 叢集、Ingress/CNI/Secret/PVC/資料及 Helm release。
- 不改產品 API、UI、身份權限、SQL V001–V049、正式 chart 或 Installer 預設。
- 不把 Backend 直接公開、不換 OIDC 實作、不改為 Gateway API、不放寬 allowlist。
- 不為研究而執行退休的 NGINX image；保留其原始 74 個 High/Critical 告警與判讀限制。
- 不修改 host DNS/hosts/全域信任庫/防火牆、Docker Desktop 容量或現行 kubeconfig。
- 不呼叫 Provider，不讀取現行模型、服務帳密、備份或 generated package。
- 本附註不直接更新 PR、發布映像或部署正式環境。原 R2 全套 gate 未完成仍不得更新 PR。

## 2. 已核准的一次性操作範圍

Gate4 後，可在原 R2 界線內依序完成下列工作，不逐項重問同一核准步驟：

1. 實作有限範圍的測試 runner、真實 Browser／整合測試與去敏感證據。
2. 讀取官方 chart／image metadata，下載／registry-only 掃描固定候選及必要測試構件；
   只傳送公開依賴 metadata，不上傳私有來源、文件、Secret 或完整應用映像。
3. 候選安全 gate／容量 gate 通過後，在原 R2 **唯一一套** run-owned kind 叢集
   安裝候選入口，並用原 R2 已核准的真實應用映像／服務／合成資料驗收。
4. 建立該 run 所需 namespace、IngressClass、限定 RBAC、ServiceAccount、Secret、
   Service、ConfigMap、Deployment、NetworkPolicy、測試 Ingress 與測試 client Pod。
   應用 Jobs／PV/PVC／V049 仍只在原 R2 合成環境內，不增加正式部署權限。
5. 保存結果與原始失敗，精確清理本 run 資源；若原 R2 後續驗證可使用同套環境，
   僅在其原有時間／資源預算內續用，不無限保留或另啟第二套完整 stack。

共享主機的 privileged kind nodes/Cilium 風險沿用原 R2，而非物理隔離。
本計畫核准不免除工具層權限／安全審查；遭拒須停止該操作、說明風險及請求指示。

## 3. 固定候選與測試設定

### 候選來源

- 僅以官方 Traefik **3.7.13、linux/arm64** 為本次候選，不使用 latest／自建退休 fork。
- Gate4 後先查官方 Helm chart metadata，選出明確對應該 appVersion 及相容 provider
  的固定 chart 版本；保存來源 URL、chart archive SHA、image index／ARM64 digest。
  目前尚未下載／解析，不編造 chart 版本或 digest。找不到相符官方組合即停止。
- 安裝與驗收使用同一份已雜湊的 render、image digest；記錄實際 Pod imageID。
  chart image override、隱含 sidecar／hook images 也必須納入；不能只掃 controller。
- 先產生完整 severity 報告／SBOM、記錄工具／查詢時間／DB 可取得資訊。未知、
  scanner 失敗、新 High/Critical 或版本漂移均不執行映像；先回報再決定。
- 不自動升級應用依賴、CNI／kind／Traefik patch 或套用舊安全例外。

### Provider 與路由

- 只啟用 `kubernetesIngressNGINX`。一般 Kubernetes Ingress／CRD／Gateway／Docker
  providers、dashboard 公開入口、plugins、全域外部 auth 保持關閉。
- 使用本 run 唯一 class 名稱及唯一 controllerClass；指定精確 watchNamespace。
  `watchIngressWithoutClass=false`、`ingressClassByName=false`，避免增加接管路徑。
- 不用 namespaceSelector 來擴大發現範圍；RBAC 的 namespaced 資源限本 run，
  IngressClass 等必要 cluster read 明列；不得用 cluster-admin 運行 controller。
- 不允許 snippets、跨 namespace 資源引用及 ExternalName 後端；保留嚴格 path
  validation。核對固定版本的實際設定鍵，不直接複製官方示例中的寬鬆設定。
- 應用 chart 的 Ingress 模板與 annotations 原樣使用。只透過既有 values 欄位指定
  合成 host、class、TLS Secret、controller namespace/pod selectors、測試來源 CIDR。
  每個覆寫列入 allowlist/diff；不 post-render 刪除不支援的 security annotation。
- 保留 `/`→Frontend、`/api/backend`→既有 BFF、`/identity`→Keycloak，以及
  `/identity/admin`、`/identity/realms/master` 的獨立管理限制。
  登入仍由 app／Keycloak 負責，不新增 ingress 認證服務。

設定依據：[3.7 provider](https://doc.traefik.io/traefik/v3.7/reference/install-configuration/providers/kubernetes/kubernetes-ingress-nginx/)、
[3.7 annotation 相容表](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/ingress-nginx/)。
相容性以實測而非文件承諾判定。[固定候選 release](https://github.com/traefik/traefik/releases/tag/v3.7.13)
提供版本依據，不代替映像安全證據。

## 4. 執行順序與停止條件

### A. 來源與容量

綁定 HEAD、merge parent、dirty source manifest、鎖檔、SQL、chart SHA 與工具版本。
使用明確 allowlist 副本和清理過的環境變數；不盲跑會讀 `.env` 的 suite collection。
重測原 R2 容量及既有容器／網路／tag 非敏感基線；單一歷史快照不能證明現在有空間。

原上限全部保留：一套 stack、三節點合計目標上限 12 CPU/24 GiB，且必須在
既有負載外保留 4 CPU、至少 8 GiB／20% RAM，PVC 宣告總量至多 20 GiB、磁碟
增量監控 80 GiB／可用至少 100 GiB；不是把 12 CPU 當作此主機必定可配置。
預檢、render requests/limits 與實際需求無法落在餘裕內即停止，不關閉現行服務。
原每階段及整批 6 小時、同原因最多 2 次修正重試限制不變。

### B. 候選安全檢查

先按 §3 固定及掃描 artifacts；未通過不建新入口、不借用退休 image 先跑。
各項掃描保留 raw findings，誤報疑慮不能直接改成 PASS。只批准方向不代表接受漏洞。

### C. Runner、render 與失敗保護

建立有限 phase runner（介面見 §6），每次變更都核對 run manifest、明確 kubeconfig、
API server、cluster/kube-system/namespace UID 及精確 resource identity。
預覽 render／必要 RBAC／CIDR／安全差異；未知差異阻擋。
以真實檔案、程序及本 run cluster 做身分失配／設定錯誤的拒絕驗證，不 fake subprocess。

### D. 真實環境與驗收

沿用原 R2 的專用 bridge、1 control-plane＋2 worker、真正強制 NetworkPolicy 的
CNI、唯一 kubeconfig／release 與完整真實服務。禁止接現行 Docker network。
應用用 source-bound 真實 image；不能掛載臨時改動程式冒充候選。

核對實際 controller UID、nonroot、capabilities、no privilege escalation、限定 RBAC。
應用及 controller 均有 readiness／資源限制。固定 image 不支援時停止，不回退 root。

| 驗收面向 | 成功與拒絕證據 |
| --- | --- |
| 發現隔離 | 只有本 run 正確 class 的 Ingress 被處理一次；wrong-class／no-class／其他測試 namespace 的規則沒有被採納。 |
| 路徑 | 真實 Frontend／BFF／Keycloak 回應與身分符合；管理 prefix、尾斜線、大小寫／編碼等變體不得掉回較寬鬆路由。記錄拒絕原因，不將所有 404 視為成功。 |
| TLS／redirect | 客戶端以 run CA 驗證；錯誤 CA／host 必須真正拒絕。HTTP→HTTPS location/query/status 與既有契約一致，需保留 method 的情境不得靜默變成 GET。 |
| OIDC | 全新測試身分完成 app/Keycloak 登入登出、callback、issuer/cookies；未登入／停用身分仍拒絕。不能用假 token 或關 JWT 驗證。 |
| 來源 IP | 同一 real app 路徑有允許／拒絕 client；onboarding 與 operational 分別測主入口及較嚴格管理路徑。偽造 X-Forwarded-For／Forwarded／X-Real-IP 仍不能取得管理存取。 |
| NetworkPolicy | 正確 controller namespace AND pod labels 才可達 Frontend/Keycloak；錯 namespace 或錯 labels client 不能到達。Frontend→Backend 仍正常，無關 Pod→Backend 被拒絕；跨 node 真實連線。 |
| 檔案／API | 使用合成小文件和無 Provider API，比對內容／授權／body size／buffering／timeout；上傳不可觸發 OCR/embedding job。若流程無法避免 Provider，該案例保持 BLOCKED。 |

來源 IP 的正反例以真實測試 client Pod→Service/入口連線為主，先記錄實際 remote
address 與 SNAT 行為。host 僅 loopback 高位 port-forward 供 UI 使用；**不能用
port-forward 成功代替 allowlist/CNI 證明**。預設不信任 client forwarded headers；
若固定拓樸需要可信代理 hop，須先證明對端身分／最小 CIDR，不將全 Pod CIDR 當管理者。

拒絕案例同時具有正常 control request、預期 HTTP policy 回應或 CNI flow/drop 證據；
任意 DNS錯誤、connection refused、500 或 timeout 不能冒充安全政策有效。
日誌只保留 request correlation、規則／路由識別與合成 IP，不保留 token/cookie/內容。

Browser 使用本 run 私有 profile、合成 hostname 對應與 CA，禁止
`ignore-certificate-errors`、全域 hosts／信任庫修改。所用 Browser 無法達到私有信任
時回報 BLOCKED，不透過忽略 TLS 接受登入驗收。

### E. 失敗、清理與銜接

任何新產品／chart 問題先記錄可重現內容，再討論修正，不降低 NetworkPolicy 或移除
annotations。容量／來源漂移／權限拒絕停止，保留失敗，不進入自動換方案循環。

僅本 run manifest 裡的 exact IDs/UIDs 可以清理：先列 dry-run，再清合成資料／
release／測試 namespace／class／RBAC／cluster／空 network、暫存 CA 與帳密。
部分安裝失敗亦清理；操作前重核擁有關係。禁止 prefix 批量刪除、system prune、
共用根目錄遞迴刪除或動現行資源。合成資料永久清除，去敏感證據及明列 test images 可保留。
核對既有基線；如其他人造成漂移，記錄而非刪他人資源以恢復相等。

相容性通過後，仍須完成原 R2 全套／兩端全來源80%／critical flows／所有 image
安全／cleanup，才可依原授權評估 PR。若需付費模型，先列用途／模型／最高呼叫與
費用請求核准。Traefik PASS 不是舊 NGINX 修復，也不是現行 ingress 遷移許可。

## 5. 檔案、設定與證據

| 檔案／區域 | 核准後的有限改動 |
| --- | --- |
| `backend/scripts/chg301_r2_ingress.py` | 計畫新增 phase runner：source/candidate/identity/容量/render/真實驗收/cleanup guards；沿用可驗證既有 R2 工具。 |
| `backend/tests/test_chg301_r2_ingress.py` | 計畫新增真實來源／檔案／程序、候選 gate 與隔離 guard 回歸，不 fake cluster/Provider。 |
| `frontend/tests/chg301R2Ingress.browser.mjs` | 計畫新增或接線真實隔離 app/Keycloak Browser 驗收，不改產品／UI。 |
| `docs/CHG-301-R2-*`、治理文件 | 計畫／來源／案例／raw失敗／未測／清理的 trace。 |
| run-owned 0700 root | 0600 kubeconfig／CA／Secret、candidate-lock、render、test-only values、resource IDs；不提交 credential。 |
| 原 Helm／Installer／API／SQL／依賴 | 確認不改。若相容性要求修改，先報告並另核准。 |

Machine evidence 至少含 source SHA、候選來源／digest／platform／scan／SBOM SHA、
工具版本、cluster/namespace IDs、render SHA、測試分母及逐項狀態、實際路由／安全
判斷依據、資源峰值／停止值、cleanup／基線比對。新增憑證僅記指紋，不印 key。
完整來源及 Secret 不進一般 application log／報告。

## 6. 驗證命令與 Gate 4

本輪可跑的只是文件治理：

```bash
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh plan:approved
git diff --check
```

規劃時 `plan:approved` 必須因新附註 PENDING 拒絕；Peter 核准後才應通過。
其他治理 PASS 不是 feature PASS。

Gate4 後才實作以下**計畫介面**，目前腳本未建立，不能聲稱已執行：

```text
CHG301_R2_ISOLATED=1 <isolated-python> backend/scripts/chg301_r2_ingress.py
  --phase preflight|candidate|prepare|install|accept|cleanup|evidence
  --run-manifest <exact-owned-private-manifest>
```

runner 不得自動把缺少 Gate4、candidate gate、UID 或 manifest 當預設成功；prepare
與 install 分開，先審核去敏感差異才自動依已核准 allowlist 套用，不需逐項重問。
測試命令必須在乾淨隔離副本／環境執行，明確關聯該 run；不能在 repo 盲跑 live pytest。
原 R2 的 canonical harness、coverage、Docker/Helm、安全及完整 suite 命令不變。

核准本計畫即核准 §2 的有界測試工作與 exact-owned cleanup，**不核准現行部署
變更、漏洞豁免、放寬資源限制、付費模型或超出原 R2 gate 的 PR 操作**。
可回覆：`核准 CHG-301 R2 Traefik 隔離驗證計畫`。

## 7. 本輪規劃檢查結果

2026-09-15：`spec:doctor`、`spec:trace`（17 條 active requirement mappings）、
`plan:doctor`、`test:plan`、`git diff --check` 通過。
`plan:approved` 因本附註 Gate4 PENDING 回 exit1，符合停止界線，不是測試失敗。
原 Ingress security evidence SHA 仍為
`11220b08475e24df8dc1b4698652fe314519b72f38db70674853c76fe81f3431`。
本輪只改規格／計畫／測試設計／追蹤及進度文件，所有新 feature／image／cluster
操作 NOT RUN。未變更現行環境、原始掃描證據、Git index、PR 或已存在的使用者修改。

# Docker Desktop 安裝驗證

[English 與完整指令](README.md)

使用 `v0.1.2` 原始碼或已驗證的 `nomosmart-0.1.2` 安裝包；本目錄包含本機 PV、Helm 設定及 Ingress 準備工具。設定與機密存放在安裝包外，保持套件完整性。正式環境依原套件驗證與 onboarding 流程安裝。

四種方式必須依序安裝、檢查、清除，才開始下一種。Compose 與原始碼開發分別依根目錄 README 的方法一與方法四；方法二、三使用本指南的本機 Kubernetes 路徑。所有依賴服務都是真實服務，Ingress 模擬使用官方控制器、實際 HTTPS 與路由，不需要執行登入、模型呼叫或產品操作。

## 環境與映像

先確認 `docker-desktop` context、Node 名稱／taint、現有 namespace／PV／StorageClass／IngressClass，以及本機 80、443 port。執行時明確指定 context，使用每輪專用且不存在的 namespace 與控制器名稱。保留 OpenLDAP、原始碼、主機設定與無關物件。

本次環境為三個 kind Node，共享一個 8 CPU、約 32 GB RAM 的 Docker Desktop VM。容量必須依實際 requests、其他 Pod 與 chart reserve 計算，不能把 VM 額度乘以三。Redis 需要三個不同 Node；只有 Redis 明確容忍 control-plane taint，PostgreSQL、RustFS、OpenSearch、Neo4j 應放在未 taint 的 worker。Local PV 適用於可刪除的本機資料，不提供儲存 HA。

依方法一產生 Compose 設定並建置本次原始碼的 Frontend／Backend 映像；此步驟只建置，不啟動 Compose。記錄各自的 `repository:tag@sha256:<digest>`，並讓每個 Kubernetes Node 都能使用這個**確切 digest reference**。本環境使用 `kind load docker-image ... --name desktop`；CRI 可能把名稱正規化為 `docker.io/<repository>@sha256:<digest>`，只匯入 tag 不一定足夠，必須檢查 Node runtime。周邊服務繼續使用 lock file 中的官方映像。

英文指南提供本次實際使用的 package、PV、Ingress、Helm foundation/application 分階段安裝指令。執行前替換映像 digest、Node／路徑與實際管理端 CIDR。私密輸入目錄使用 `0700`，Secret／私鑰使用 `0600`；`nomosmart.local` 必須能解析到 loopback。本次沿用既有映射，沒有修改 `/etc/hosts` 或主機信任庫。

## 方法二：明確設定 PV

1. 產生 `factory_acceptance`／`development` 套件，使用 `--random-initial-credentials --postgresql-standalone`。`prepare-helm.py` 只寫出本機 `values.json` 與私密 `secrets.json`，不套用資源。PostgreSQL 的 admin、migration、application 與 Keycloak 帳號分開；首次密碼隨機產生並保存在受保護檔案。
2. 用實際 chart／values render 並擷取 `capacity-plan.json`。本機需求為 PostgreSQL `5Gi`、Redis `2Gi` × 3、RustFS `10Gi`、OpenSearch `10Gi`、Neo4j `5Gi`，共七個 PVC。
3. 在 `placement.json` 明確列出每個 claim 的唯一 PV 名稱、實際 hostname 與全新絕對 Node 資料路徑。Redis 分配到三個不同 Node。只為這一輪建立 Node 目錄，服務 UID/GID 為 PostgreSQL／Redis `999`、RustFS `10001`、OpenSearch `1000`、Neo4j `7474`，權限 `0700`。先核對 Docker container 與 Kubernetes Node 的對應，不可把任意 macOS 目錄當成 Node 路徑。
4. 執行 `prepare-static-pvs.py`，檢查每個 PV 的 claimRef、容量、ReadWriteOnce、Filesystem、Retain、local path 與 nodeAffinity。工具不會建立／修改資料目錄，也不會套用資源。
5. 建立這輪專用 StorageClass，使用 `kubernetes.io/no-provisioner`、`WaitForFirstConsumer` 與 `Retain`，再套用 PV。依 storage reserve 核對實際磁碟容量。不使用預設動態儲存，也不安裝額外儲存產品。
6. 以 `prepare-ingress.py` 產生並套用 namespace／class 專用的官方 Traefik 控制器。它支援 chart 使用的 NGINX 相容註解，不安裝 CRD，也不給跨 namespace 的 Secret 權限。使用 loopback port-forward；macOS 無法直接綁定 80／443 時，依英文指令使用官方 socat 容器轉送至高埠，TLS 仍由真正的 Ingress 終止。
7. 套用 Secret，再執行 Helm `foundation`。等所有依賴 workload Ready、七組 PVC Bound，才升級為 `application`，執行 migration／bootstrap 並啟動四個應用 workload。
8. 確認初始化 Job 完成、workload Ready、前端 HTTPS 與 `/api/backend/ready` 成功。新資料庫執行 B051，重跑 migration 應為 no-op。用暫存 marker／Pod 重建確認 PV 資料仍在，讀回後移除 marker；這項測試不刪 PVC。

型別化設定使用 `platform_profile = "docker-desktop"`、`storage_mode = "static-pv"`、專用 StorageClass 與 `static_pv_manifest_file`；PV 檔案納入 configuration digest。Production 使用相同綁定契約，但保留自身的容量／可用性要求，儲存產品由 operator 選定。

本機 values 的 `dnsOverTcp` 使用真實 TCP DNS，解決本次觀察到的 UDP 查詢逾時，不修改共享 CoreDNS。Production 預設不啟用。

## 方法三：外部服務

清除方法二後，使用新的 application／controller namespace。六種外部依賴必須先存在，具有真實 TLS endpoint 與 operator 管理的帳密／權限／備份／生命週期。本次另建全新測試依賴 namespace 與靜態 PV，沒有借用 OpenLDAP 或前一輪資料。

沿用真實 Ingress 流程，先套 `values-docker-desktop.yaml`，再套 `values-external-services.example.yaml` 與自己的非機密覆寫。選擇 `deploymentProfile: external-services`、六個 component 的 `mode: external`、`storageValidation.mode: external`，停用應用 chart 內的 PostgreSQL operator／backup，並設定實際 Redis topology。應用 namespace 必須是 **零 PVC**；型別化設定使用 `storage_mode = "external"`、空白 `storage_class`，不提供 static PV manifest。

Runtime Secret 要與 operator 的真實服務帳密一致。PostgreSQL 使用 verify-full；standalone Redis 的三組 Redis／Celery URL 使用 `rediss://`、`ssl_cert_reqs=required`、`ssl_check_hostname=true` 與 CA 路徑；S3／OpenSearch 使用驗證憑證的 HTTPS；Neo4j 使用 `neo4j+s://` 與 CA。

私有 HTTPS Keycloak 使用 `keycloak.external.caSecretName/caKey` 指向包含所有必要根憑證的 operator **CA bundle**。Chart 會為 Backend／Frontend 掛載並設定 `SSL_CERT_FILE`／`NODE_EXTRA_CA_CERTS`；公有 CA 可維持原有系統信任。CA 逐檔唯讀 `subPath` 掛載，保留一般檔案檢查；**輪替 CA 後重建受影響 Pod**，因為 subPath 不會自動更新。大型 CA bundle 使用 server-side apply，避免 client-side annotation 超過 Kubernetes 限制。

Operator 已準備 realm／clients 時，使用 `bootstrap.keycloakMode: verify`。執行應用 migration／bootstrap 後，確認四個 workload Ready、前端 HTTPS、`/api/backend/ready`，以及**設定的外部 issuer**之 discovery。私有 cluster DNS 可從真實 Backend Pod 驗證 HTTPS，不可假設應用 Ingress 的 `/identity` 就是外部 Keycloak。安裝驗證不執行登入。

## 每輪清除

先保存建立物件的確切名稱、UID、label、digest、Node 資料路徑與 PID。停止該輪原始碼程序及 port-forward，再依英文指南的指令移除專用 Helm release、namespace、PV／StorageClass、IngressClass／RBAC 與 TCP forwarder。

External-services 應用本身沒有 PV／StorageClass，不可照 bundled 清理共用外部資料。另建的測試依賴只有在確定屬於本輪時才移除。Retain 不會抹除資料；Pod／PVC 移除後，若本輪資料已核准永久刪除，逐一刪除七個專用 Node 目錄。Compose 使用確切測試 project 執行 `down --volumes --remove-orphans`。只刪除本輪映像／cache alias 與生成的私密檔案，不使用全域 prune、namespace 萬用匹配，或刪除共用 StorageClass／CRD。確認資源不存在並比對保護盤點後，才開始下一種。

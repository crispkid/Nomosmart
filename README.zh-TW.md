# NomoSmart

[English](README.md) | 繁體中文

NomoSmart 是企業知識管理平台，可將文件與外部資料整理成容易管理、搜尋及引用的知識內容。

## 1. 專案概述

NomoSmart 會讀取檔案與已連接的資料來源，必要時執行 OCR，再將內容轉成 Markdown，並切成適合搜尋的段落。團隊可以審核及發布不同版本、搜尋內容、查看資料之間的關係，也可以透過對話取得附有來源引用的回答。

平台適合知識負責人、編輯者、審核者、系統管理員、整合開發者與一般使用者。PostgreSQL 保存應用程式資料；Redis 與 Celery 處理背景工作；S3 相容儲存空間保存原始檔與產出內容；OpenSearch 負責搜尋；Neo4j 保存知識關係；Keycloak 提供登入與企業目錄整合。

`0.1.0` 包含 NomoSmart 應用程式、安裝工具、SQL、設定範本與文件。本專案發布 Frontend 與 Backend 映像，Worker 和 Beat 共用 Backend 映像；周邊服務與外掛依 [external-dependencies.lock.json](deploy/release/external-dependencies.lock.json) 向官方來源下載。完整安裝驗收尚待完成，請先準備隔離環境使用本版。

## 2. 核心功能

- **從常見來源匯入資料** — 支援 PDF、DOCX、TXT、Markdown，以及 FTP、FTPS、SFTP、S3 與 HTTP API。
- **整理文件內容** — 執行文件解析與 OCR、產生標準 Markdown、切分段落、加入標籤並建立 Embedding。
- **管理文件版本** — 保存來源檔、文件版本、顯示內容、段落、標籤、引用關係與目前發布版本。
- **審核與發布** — 讓內容依照既定流程完成審核，再發布核准的版本。
- **搜尋與問答** — 提供關鍵字、向量及混合搜尋，回答會標示來源文件、版本與段落。
- **查看知識關係** — 透過圖譜頁面與 API 查看專案、文件、段落及標籤之間的關係。
- **確認回答品質** — 收集單筆回饋、執行 CSV 批次檢查、保留重試歷程並匯出結果。
- **管理平台** — 管理專案、使用者、角色、權限、企業目錄映射、模型服務、System Prompt、API Client、報表與稽核日誌。
- **切換介面語言** — 提供繁體中文與英文介面。

## 3. 系統架構

```text
Browser / API Client
        |
        v
HTTPS Edge / Kubernetes Ingress
        |
        +---------------------> Keycloak OIDC
        |
        v
Next.js Frontend -----------> FastAPI Backend
                                  |
                                  +--> PostgreSQL
                                  +--> Redis <--> Celery Worker / Beat
                                  +--> S3-compatible Storage / RustFS
                                  +--> OpenSearch
                                  +--> Neo4j
                                  +--> Chat / Embedding / OCR / Judge Service
```

應用程式進入 Ready 狀態前，Migration 與 Bootstrap 工作會先更新資料庫並準備必要服務。Readiness Endpoint 會檢查 PostgreSQL、Redis、Object Storage、OpenSearch、Neo4j、Database Migration 與初始化狀態。

## 4. 技術架構

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | Next.js 16.3.3、React 19.2.3、TypeScript 5 | Web Application、OIDC Flow 與 Backend Proxy |
| Backend | Python 3.12、FastAPI、SQLAlchemy、Pydantic | REST API、設定、Domain Logic 與 Persistence |
| Background Processing | Celery 5.5+、Redis 7.4 | 匯入、同步、驗證與排程工作 |
| Database | PostgreSQL 18.4、Flyway 13.6 | 權威資料與 Forward-only Migration |
| Object Storage | S3 相容儲存；Bundled 部署使用 RustFS | 原始文件與產出物 |
| Search | OpenSearch 2.19 | Keyword、Vector、Hybrid 與 Staging Index |
| Graph | Neo4j 5.26 Community | 知識關係與 Traversal |
| Identity | Keycloak 26.0.8、OIDC、LDAP/AD Federation | 認證、目錄同步與角色映射 |
| Deployment | Docker Compose v2、Helm Chart 0.1.0 | 單機與 Kubernetes 部署 |

## 5. 專案結構

```text
Nomosmart/
├── frontend/                  Next.js 應用程式、UI 元件與多語系內容
├── backend/                   FastAPI API、背景工作與應用程式服務
├── sql/migrations/            B051 首次安裝基線及 V001–V051 升級歷史
├── deploy/docker/             Docker Compose Runtime 設定
├── deploy/helm/nomosmart/     Helm Chart 與各環境 Values
├── deploy/installer/          支援 Profile 的 Kubernetes Installer
├── deploy/package/            Secret 與 TLS Package 生命週期工具
├── deploy/release/            發布打包與完整性檢查工具
├── docs/                      技術決策與操作文件
└── docker-compose.yml         單機 Deployment Model
```

## 6. 開始使用

### 6.1 選擇安裝方法

依照目標環境選擇一種方法，再從該章節的第一步依序執行到最後。

| 方法 | 適用環境 | 安裝元件 |
| --- | --- | --- |
| [方法一：Docker Compose](#method-1-docker-compose) | 開發電腦或單一伺服器 | NomoSmart 與所有必要服務 |
| [方法二：Kubernetes bundled](#method-2-kubernetes-bundled) | 由 NomoSmart 管理周邊服務的 Kubernetes | NomoSmart、PostgreSQL、Redis、RustFS、OpenSearch、Neo4j 與 Keycloak |
| [方法三：Kubernetes external services](#method-3-kubernetes-external-services) | 已有共用服務的 Kubernetes | 只安裝 NomoSmart Workload 與初始化 Job |
| [方法四：Source Development](#method-4-source-development) | 開發者電腦 | Frontend、Backend、Worker 與 Beat，並連接既有服務 |

新的 Kubernetes 安裝須明確選擇 `bundled` 或 `external-services` Profile。Helm 的 `auto` 值保留供既有部署相容使用。

### 6.2 前置條件

只有儲存庫已明確指定版本的工具，才會列出版本號。

| 工具或條件 | 版本 | 適用方法 | 檢查指令 |
| --- | --- | --- | --- |
| Git | 與 Repository 相容的版本 | Docker Compose、Source Development | `git --version` |
| GitHub CLI | 可用的 CLI | 私有 Repository 與 Release 下載 | `gh --version` |
| Docker Engine 或 Docker Desktop | 支援 Compose 的安裝版本 | Docker Compose、本機 Flyway | `docker version` |
| Docker Compose | v2 | Docker Compose | `docker compose version` |
| Python | 安裝器使用 Python 3.11 以上；Backend Development 固定 Python 3.12 | Package Tool、Installer、Backend | `python3 --version` |
| Node.js 與 npm | Container Baseline 為 Node.js 24 | Frontend Development | `node --version` 與 `npm --version` |
| uv | 可使用 Lockfile 的版本 | Backend Development | `uv --version` |
| kubectl | 1.28 以上 | Kubernetes | `kubectl version --client` |
| Helm | v3 或 v4 | Kubernetes | `helm version` |
| OpenSSL | 可用的 CLI | TLS Package、Kubernetes Installer | `openssl version` |
| curl | 支援 HTTPS | Runtime 驗證 | `curl --version` |
| lsof 與 `/etc/hosts` 存取權限 | Unix-like 主機工具 | Docker Compose Preflight | `lsof -v` |

依選定方法，使用各工具的作業系統安裝指南：[Git](https://git-scm.com/downloads/)、[GitHub CLI](https://github.com/cli/cli#installation)、[Docker](https://docs.docker.com/engine/install/)、[Python](https://www.python.org/downloads/)、[Node.js](https://nodejs.org/en/download)、[uv](https://docs.astral.sh/uv/getting-started/installation/)、[kubectl](https://kubernetes.io/docs/tasks/tools/) 與 [Helm](https://helm.sh/docs/intro/install/)。選擇表列版本，安裝完成後開啟新的終端機，逐項執行適用的檢查指令再繼續。

Kubernetes Production 安裝需要至少三個 Ready 且可排程的 Node、符合 Production Plan 的容量、IngressClass、核准的 Longhorn StorageClass、Public DNS、可信任 TLS Material、Registry 存取權限，以及企業目錄或已設定完成的 Keycloak Identity Provider。

Repository 為私有。Clone 與下載 Release 需要具備存取權限的 GitHub 帳號，拉取映像也需要 NomoSmart GHCR Package 的存取權限。Git 認證請使用 Credential Manager；Token 保存在受保護的認證工具中，不填入設定範例或命令參數。

使用 Kubernetes 安裝時，先安裝 GitHub CLI，再下載 0.1.0 Release 安裝包：

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth status
install -d -m 0700 "$HOME/nomosmart-downloads/0.1.0"
gh release download v0.1.0 --repo crispkid/Nomosmart \
  --pattern nomosmart-0.1.0.tar.gz \
  --dir "$HOME/nomosmart-downloads/0.1.0"
tar -xzf "$HOME/nomosmart-downloads/0.1.0/nomosmart-0.1.0.tar.gz" \
  -C "$HOME/nomosmart-downloads/0.1.0"
export NOMOSMART_RELEASE_DIR="$HOME/nomosmart-downloads/0.1.0/nomosmart-0.1.0"
```

每個版本使用新的下載目錄，解壓後依第 8.2 節檢查完整性。GitHub Repository 與 GHCR 拉取權限分開管理；安裝器的 `registry_pull_secret` 應指向具有 Package 讀取權限的 Registry Credential。整包模式也需要連線至 Docker Hub、Quay、GHCR、OpenSearch artifacts，以及 lock 檔列出的 CloudNativePG／Barman 官方下載位置。

### 6.3 Port 與 Endpoint

| Mode | Port 或 URL | 用途 |
| --- | --- | --- |
| Docker Compose | `127.0.0.1:80` | HTTP Redirect 與 Edge Health |
| Docker Compose | `127.0.0.1:443` | HTTPS Application 入口 |
| Source Frontend | `127.0.0.1:3000` | Next.js Development Server |
| Source Backend | `127.0.0.1:8000` | FastAPI、OpenAPI 與 Swagger UI |
| Source Dependencies | `5432`、`6379`、`9000`、`9200`、`7687`、`8080` | PostgreSQL、Redis、S3、OpenSearch、Neo4j 與 Keycloak |
| Kubernetes | `https://<public-host>` | 由 Ingress 管理的 Application 與 OIDC 入口 |

Compose 預設將 Dependency Port 保留在私有 Network 內。`debug` Profile 可將指定 Dependency Port 發布到 Loopback，供工程診斷使用。

<a id="method-1-docker-compose"></a>

## 7. 方法一：Docker Compose

Docker Compose 是在單一電腦上啟動完整平台最直接的方法。它會建立應用程式映像、啟動所有必要服務、更新資料庫、完成初始化，並提供單一 HTTPS 網址。

### 7.1 取得 Source Code

Clone Repository 並進入根目錄：

```bash
git clone --branch v0.1.0 --single-branch https://github.com/crispkid/Nomosmart.git
cd Nomosmart
git status --short
```

確認取得的 Tag 與 Commit：

```bash
git describe --tags --exact-match
git rev-parse HEAD
```

Tag 應為 `v0.1.0`，Commit SHA 應與該 Release 的來源一致。

### 7.2 驗證主機工具

```bash
docker version
docker compose version
python3 --version
openssl version
lsof -v
```

`docker version` 應顯示 Client 與 Server 資訊。Server 區段尚未顯示時，啟動 Docker Engine 或 Docker Desktop 後重新執行。

### 7.3 準備本機 Hostname 與 Port

本機安裝使用 `https://nomosmart.local`。先檢查 Host Mapping：

```bash
grep -n "nomosmart.local" /etc/hosts
```

找不到對應項目時，新增一筆：

```bash
echo "127.0.0.1 nomosmart.local" | sudo tee -a /etc/hosts
```

保留唯一一筆設定：

```text
127.0.0.1 nomosmart.local
```

確認 Public Port 可使用：

```bash
lsof -nP -iTCP:80 -sTCP:LISTEN
lsof -nP -iTCP:443 -sTCP:LISTEN
```

沒有輸出表示 Port 可使用。出現 Process 時，停止該 Process 後重新檢查。

### 7.4 產生本機設定、Secret 與 TLS Package

下列指令會建立 `deploy/docker/nomosmart.env`，並在 `deploy/docker/generated/current/` 產生本機 Secret 與 TLS 檔案。Git 會忽略這些產生的檔案，敏感檔案只允許擁有者讀取。

```bash
./deploy/package/nomosmart-package init \
  --target compose \
  --profile factory_acceptance \
  --app-env development \
  --public-host nomosmart.local \
  --no-display
```

驗證 Package：

```bash
./deploy/package/nomosmart-package status --target compose
test -f deploy/docker/nomosmart.env
test -f deploy/docker/generated/current/manifest.json
test -f deploy/docker/generated/current/tls/active/edge-ca.crt
```

每個指令都應回傳狀態 `0`。Production Package 使用 `--profile production`、核准的 Public Hostname、企業 TLS Input，以及必要的 Break-glass Runbook 與 Alerting Evidence。

### 7.5 執行 Preflight 與設定檢查

```bash
./deploy/package/nomosmart-package preflight --runtime compose
docker compose --env-file deploy/docker/nomosmart.env config --quiet
docker compose --env-file deploy/docker/nomosmart.env config --services
```

Preflight 會檢查 Host Mapping、80 與 443 Port，以及本機執行設定。兩個 Compose 指令應順利完成，並列出服務名稱。

### 7.6 Build 並啟動平台

首次使用 Compose 安裝，且預計透過 Keycloak 管理介面設定 LDAP 或 Windows AD 時，先準備專用的身分管理帳號，再啟動應用程式：

1. 在 `deploy/docker/nomosmart.env` 設定 `KEYCLOAK_ADMIN_ALLOW_CIDR`，填入 Edge Proxy 實際看到的管理端來源 IP／CIDR，將存取範圍限定在管理網段。
2. 先啟動身分服務與 HTTPS 入口：

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d postgresql keycloak
docker compose --env-file deploy/docker/nomosmart.env up -d --no-deps edge
docker compose --env-file deploy/docker/nomosmart.env ps postgresql keycloak edge
```

3. 將 `deploy/docker/generated/current/tls/active/edge-ca.crt` 加入瀏覽器信任清單，開啟 `https://nomosmart.local/identity/admin/master/console/`。初始 Keycloak 管理帳號為 `nomosmart`，密碼位於受保護的 `deploy/docker/generated/current/keycloak_bootstrap_admin_password`。
4. 在 `master` Realm 建立另一個具名管理帳號，安全地設定密碼並指派 `admin` Realm Role。使用另一個瀏覽器工作階段確認新帳號可以登入，再將認證資料存入組織的密碼保管工具。

應用程式初始化完成 NomoSmart Realm 與服務帳號設定後，會停用初始 Keycloak 管理帳號。新建的具名帳號供後續目錄管理使用。NomoSmart 應用程式管理員與 Keycloak 管理員是不同的權限角色。

啟動完整平台：

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d --build
docker compose --env-file deploy/docker/nomosmart.env ps
```

這個步驟會啟動 PostgreSQL、Redis、RustFS、OpenSearch、Neo4j、Keycloak、Frontend、Backend、背景工作與初始化工作。持續執行的服務應顯示 `running` 或 `healthy`；Migration 與 Bootstrap Job 可以顯示成功完成。

### 7.7 驗證 HTTPS、Health 與 Readiness

```bash
curl --fail --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/edge-health
curl --fail --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/api/backend/health
curl --fail --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/api/backend/ready
```

Edge 與 Process Health 的預期結果：

```text
ready
{"status":"healthy"}
```

Readiness 成功時，Response 會包含 `"status":"ready"` 與 Healthy Dependency。Readiness 尚在準備時，保留已產生的設定，並從第一個未完成的 Dependency 開始檢查。

### 7.8 完成首次設定

將 `deploy/docker/generated/current/tls/active/edge-ca.crt` 匯入 Workstation 或 Browser Trust Store，然後開啟：

```text
https://nomosmart.local
```

Factory Profile 會建立首次使用的暫時管理帳號 `nomosmart`，密碼為 `nomosmart`。登入後完成必要的密碼更新，再重新登入。

進入 **系統管理 → 模型**：

1. 建立並測試 Active Embedding Model。
2. 建立並測試 Active Chat Model。
3. 將 Chat Model 連結到至少一個 Active Embedding Model。
4. 使用對應流程時，設定 OCR 與 Judge Model。
5. 設定必要的 Default Model。

首次匯入前，先依第 11.6 節初始化文件處理政策。企業帳號登入依第 11.7–11.10 節設定。接著建立專案、匯入支援的文件、執行擷取、送審並發布版本，最後確認對話結果包含來源引用。

### 7.9 操作與停止部署

```bash
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 backend
docker compose --env-file deploy/docker/nomosmart.env restart backend celery-worker celery-beat
docker compose --env-file deploy/docker/nomosmart.env down
```

`down` 會停止 Container 並移除 Compose Network，同時保留 Named Volume。

<a id="method-2-kubernetes-bundled"></a>

## 8. 方法二：Kubernetes `bundled`

`bundled` Profile 會在同一個 Release 中安裝 NomoSmart 與所有支援的周邊服務。開始前，管理人員需先準備 Kubernetes Cluster、IngressClass、StorageClass、DNS、Image Registry 存取權限、TLS 檔案、足夠容量與企業目錄服務。

### 8.1 定義安裝值

使用 Release Package 或 Installer 前，先定義所有值：

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SECURE_ROOT="/secure/nomosmart"
export NOMOSMART_INSTALL_CONFIG="$NOMOSMART_SECURE_ROOT/install.toml"
export NOMOSMART_KUBE_CONTEXT="<approved-kube-context>"
export NOMOSMART_NAMESPACE="nomosmart"
export NOMOSMART_PUBLIC_URL="https://<public-host>"
```

從本 Repository 的 GitHub Release 下載安裝包。安裝完成前，保持解壓後的內容與絕對路徑不變。

### 8.2 檢查安裝包完整性

```bash
"$NOMOSMART_RELEASE_DIR/deploy/release/nomosmart-release" verify-package \
  --package "$NOMOSMART_RELEASE_DIR" \
  --purpose installation-validation
```

成功時結束碼為 `0`，並回傳 `status: verified`。指令會檢查檔案雜湊、完整檔案清單、相依服務參照及版本資料。0.1.0 請先使用隔離的安裝環境；完整安裝驗收尚待完成。

### 8.3 驗證工具與 Target Identity

```bash
kubectl version --client
helm version
python3 --version
openssl version
kubectl --context "$NOMOSMART_KUBE_CONTEXT" config view --minify \
  -o jsonpath='{.clusters[0].cluster.server}'
kubectl --context "$NOMOSMART_KUBE_CONTEXT" get namespace kube-system \
  -o jsonpath='{.metadata.uid}'
```

將 API Server 位址與 `kube-system` Namespace UID 填入 Installer TOML，並確認兩個值都指向預定安裝的 Cluster。

### 8.4 準備受保護目錄與 TLS Material

建立 Mode `0700` 的 Operator-owned Directory：

```bash
install -d -m 0700 "$NOMOSMART_SECURE_ROOT"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/package"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/installer-state"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/tls"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/inputs"
```

Bundled TLS Directory 需包含核准的 Edge、PostgreSQL Server 與 Replication、Redis、RustFS、OpenSearch HTTP 與 OpenSearch Transport Certificate Set。Private Key 使用 Mode `0600`。Certificate SAN 必須符合 Release、Namespace 與產生的 Service Name。

向環境的憑證管理員取得以下憑證，使用指定檔名存放於 `NOMOSMART_SECURE_ROOT/tls`：

| 服務 | 檔案 |
| --- | --- |
| Edge | `edge.crt`, `edge.key`, `edge-ca.crt` |
| PostgreSQL | `postgresql.crt`, `postgresql.key`, `postgresql-replication.crt`, `postgresql-replication.key`, `postgresql-ca.crt` |
| Redis | `redis.crt`, `redis.key`, `redis-ca.crt` |
| RustFS | `rustfs.crt`, `rustfs.key`, `rustfs-ca.crt` |
| OpenSearch | `opensearch.crt`, `opensearch.key`, `opensearch-transport.crt`, `opensearch-transport.key`, `opensearch-ca.crt` |

PostgreSQL Replication 憑證的 CN 須為 `streaming_replica`，用途包含 Client Authentication。服務憑證須涵蓋實際 Kubernetes DNS 名稱，並在安裝期間有效。Production 容量設定要求每個 Node 至少有 `7000m` 可分配 CPU 及 `28Gi` 可分配記憶體；安裝器也會檢查工作負載配置及保留容量。

核准安裝 Plan 前，先依第 11.7–11.9 節完成目錄準備與欄位對照。

### 8.5 初始化並完成 Bundled 設定

```bash
cd "$NOMOSMART_RELEASE_DIR"
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --init-config
```

指令會建立 Mode `0600` 的 TOML 檔案，不會覆寫既有檔案，並把 Chart 與 Values 寫成已驗證 Package 內的絕對路徑。

編輯檔案並完成下列區段：

| TOML Group | 必要設定 |
| --- | --- |
| Root 與 `release` | `api_version = "install.nomosmart.io/v1alpha2"`、安裝包路徑、`purpose = "installation-validation"`，以及明確確認隔離環境 |
| `target` | Exact Context、API Server、Cluster UID、Namespace 與 Helm Release |
| `application` | Public Host、Ingress Identity、StorageClass、受保護目錄、Secret 名稱、Onboarding CIDR、Runbook URI 與 Alerting Evidence |
| `images` | 九個 Image，格式固定為 `repository:tag@sha256:<digest>` |
| `identity` | Directory Mode、Realm、Provider、Mapper、Administrator、External Group、Local Role、LDAPS 欄位、Bind Secret 與 CA Secret |

從解壓後的 Release 執行初始化時，指令會自動填入安裝包路徑與映像參照。確認 `target` 指向隔離環境後，將 `[release]` 的 `isolated_environment_acknowledged` 設為 `true`：

```toml
[release]
package_dir = "/absolute/path/to/extracted-nomosmart-release"
purpose = "installation-validation"
isolated_environment_acknowledged = true
```

將範例路徑換成 `NOMOSMART_RELEASE_DIR`，並保留指令依發布清單產生的應用映像參照。確認受保護檔案權限：

```bash
stat "$NOMOSMART_INSTALL_CONFIG"
```

### 8.6 準備 Namespace 與 Operator Input

先檢查 Namespace：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" get namespace "$NOMOSMART_NAMESPACE"
```

Namespace 尚未建立時執行：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" create namespace "$NOMOSMART_NAMESPACE"
```

`freeipa`、`ldap` 或 `active-directory` Identity Mode 需從受保護檔案建立 Bind Password 與 Directory CA Secret：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-directory-bind \
  --from-file=bind-password="$NOMOSMART_SECURE_ROOT/inputs/directory-bind-password"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-directory-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/directory-ca.crt"
```

Image 位於 Private Registry 時，建立對應的 Pull Secret：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-registry \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="$NOMOSMART_SECURE_ROOT/inputs/registry-config.json"
```

既有 Keycloak Provider 與 Mapper 使用 `identity.mode = "preconfigured"`。此模式的 Directory Bind 與 CA Input 依既有 Identity Operator 契約提供。

### 8.7 執行並核准 Read-only Plan

```bash
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --plan-only
```

確認目標 Cluster、Namespace Ownership、至少三個 Ready 且可排程的 Node、容量、IngressClass、StorageClass、DNS、HTTPS 連線、TLS 與 Secret Fingerprint、Chart，以及已固定 Digest 的 Image。保存並核准畫面顯示的 `config_digest`。

完成必要條件後，使用相同 Package 與設定重新執行 Plan。Plan 階段只執行唯讀檢查。

### 8.8 安裝、Resume 並完成 Identity Checkpoint

Digest 核准後執行：

```bash
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG"
```

Wrapper 會先檢查目前狀態，再開始新安裝或接續先前進度。它會取得 Installer Lease、完成十個階段，最後檢查安裝結果。

Installer 顯示 `action-required` 時，開啟 `$NOMOSMART_PUBLIC_URL/login`，完成指定 Federated Administrator 與 Break-glass 首次登入、必要的密碼更新、Directory Synchronization 與 `system-admin` Mapping Check。再次執行同一指令，即可從已保存的 Checkpoint 繼續。

已核准的 Non-interactive 執行可綁定確切 Plan Digest：

```bash
export NOMOSMART_CONFIG_DIGEST="replace-with-the-approved-config-digest"
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --confirm-digest "$NOMOSMART_CONFIG_DIGEST"
```

### 8.9 驗證已安裝的 Release

```bash
./deploy/installer/nomosmart-install status \
  --config "$NOMOSMART_INSTALL_CONFIG"
./deploy/installer/nomosmart-install verify \
  --config "$NOMOSMART_INSTALL_CONFIG"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get pods
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get jobs
curl --fail --silent --show-error "$NOMOSMART_PUBLIC_URL/api/backend/health"
curl --fail --silent --show-error "$NOMOSMART_PUBLIC_URL/api/backend/ready"
```

驗證指令會檢查 HTTPS、Frontend、Backend Readiness、OIDC、Directory Mapping、Kubernetes Workload、Job、儲存空間、Secret Mount、Database Migration、平台初始化、Worker 與 Beat。

最後完成第 7.8 節的 Model Service 與 Project 驗證。

<a id="method-3-kubernetes-external-services"></a>

## 9. 方法三：Kubernetes `external-services`

`external-services` Profile 只安裝 NomoSmart 應用程式與初始化 Job。PostgreSQL、Redis、S3 相容儲存空間、OpenSearch、Neo4j 與 Keycloak 必須先準備完成，並繼續由原本的管理單位維護。

### 9.1 定義並驗證安裝 Input

定義本次安裝使用的受保護路徑與參數：

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SECURE_ROOT="/secure/nomosmart"
export NOMOSMART_INSTALL_CONFIG="$NOMOSMART_SECURE_ROOT/install.toml"
export NOMOSMART_KUBE_CONTEXT="<approved-kube-context>"
export NOMOSMART_NAMESPACE="nomosmart"
export NOMOSMART_PUBLIC_URL="https://<public-host>"
```

驗證 Package 與工具：

```bash
"$NOMOSMART_RELEASE_DIR/deploy/release/nomosmart-release" verify-package \
  --package "$NOMOSMART_RELEASE_DIR" \
  --purpose installation-validation
kubectl version --client
helm version
python3 --version
openssl version
```

所有指令成功後即可準備 Target。

### 9.2 準備 External Service Contract

準備 Kubernetes Cluster 可以連線且已啟用 TLS 的服務。NomoSmart 帳號只授予必要權限，並明確指定 Backup、Restore、Availability 與 Lifecycle 的負責人。

| Service | 必要 Connection Contract |
| --- | --- |
| PostgreSQL | SQLAlchemy URL、Migration Identity、Flyway JDBC URL 與 CA Secret |
| Redis | TLS URL、使用時的 Sentinel 設定、Celery Broker/Result URL 與 CA Secret |
| S3-compatible Storage | HTTPS Endpoint、Region、Bucket、Access Key、Secret Key 與 CA Secret |
| OpenSearch | HTTPS Endpoint、Service Credential、Index Prefix 與 CA Secret |
| Neo4j | TLS URI、Database、Service Credential 與 CA Secret |
| Keycloak | HTTPS Issuer、Discovery、JWKS、Admin API、Backend/Frontend Client、Sync Client、Realm 與 CA Trust |

執行 Installer 前，使用核准的 Client 與 CA 從安裝環境驗證每個 Endpoint。

### 9.3 準備受保護目錄

```bash
install -d -m 0700 "$NOMOSMART_SECURE_ROOT"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/package"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/installer-state"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/tls"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/inputs"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/runtime"
```

External Profile 的 TLS Directory 只需放置 `edge.crt`、`edge.key` 與 `edge-ca.crt`。External Service CA Certificate 透過 Kubernetes Secret 提供。

### 9.4 初始化並完成 External-services 設定

```bash
cd "$NOMOSMART_RELEASE_DIR"
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --init-config
```

編輯產生的 TOML：

- 保留 `api_version = "install.nomosmart.io/v1alpha2"` 與產生的 `release` 設定。確認隔離目標後，依第 8.5 節將 `release.isolated_environment_acknowledged` 設為 `true`。
- 保留 `deployment_profile = "external-services"`。
- 保留 `application.runtime_secret_mode = "existing"`。
- 替換 Target Identity、Public Host、Ingress、StorageClass、Secret 名稱與 Identity 設定，並保留依發布清單產生的映像參照。
- 在 External-services Helm Values Overlay 填入實際 Service Endpoint 與 CA Secret 名稱。
- Secret Value 保存在受保護檔案與 Kubernetes Secret。

將可編輯的 Overlay 複製到安裝包外：

```bash
cp "$NOMOSMART_RELEASE_DIR/deploy/helm/nomosmart/values-external-services.example.yaml" \
  "$NOMOSMART_SECURE_ROOT/inputs/values-external-services.yaml"
chmod 0600 "$NOMOSMART_SECURE_ROOT/inputs/values-external-services.yaml"
```

在 TOML 的 `application.values` 陣列中，第一項保留產生的 `values-prod.yaml` 絕對路徑，第二項改為上述副本的絕對路徑。在副本填入 Endpoint 與 Secret 名稱，並維持 `NOMOSMART_RELEASE_DIR` 內所有檔案不變，讓後續完整性檢查可以持續通過。

### 9.5 建立 Namespace、Runtime Secret 與 CA Secret

Namespace 尚未建立時先建立，再從 Mode `0600` 檔案建立 `nomosmart-runtime-secrets`。Fresh Install 需要以下 Key：

```text
APP_ENCRYPTION_KEY
DATABASE_URL
DATABASE_MIGRATION_USER
DATABASE_MIGRATION_PASSWORD
REDIS_URL
REDIS_SENTINEL_PASSWORD
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
OPENSEARCH_ADMIN_PASSWORD
OPENSEARCH_PASSWORD
NEO4J_ADMIN_PASSWORD
NEO4J_PASSWORD
OIDC_CLIENT_SECRET
KEYCLOAK_SYNC_CLIENT_SECRET
BREAK_GLASS_INITIAL_PASSWORD
```

從檔案建立 Secret，使 Value 保持在 Shell Argument 之外：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" create namespace "$NOMOSMART_NAMESPACE"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-runtime-secrets \
  --from-file=APP_ENCRYPTION_KEY="$NOMOSMART_SECURE_ROOT/runtime/APP_ENCRYPTION_KEY" \
  --from-file=DATABASE_URL="$NOMOSMART_SECURE_ROOT/runtime/DATABASE_URL" \
  --from-file=DATABASE_MIGRATION_USER="$NOMOSMART_SECURE_ROOT/runtime/DATABASE_MIGRATION_USER" \
  --from-file=DATABASE_MIGRATION_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/DATABASE_MIGRATION_PASSWORD" \
  --from-file=REDIS_URL="$NOMOSMART_SECURE_ROOT/runtime/REDIS_URL" \
  --from-file=REDIS_SENTINEL_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/REDIS_SENTINEL_PASSWORD" \
  --from-file=CELERY_BROKER_URL="$NOMOSMART_SECURE_ROOT/runtime/CELERY_BROKER_URL" \
  --from-file=CELERY_RESULT_BACKEND="$NOMOSMART_SECURE_ROOT/runtime/CELERY_RESULT_BACKEND" \
  --from-file=S3_ACCESS_KEY_ID="$NOMOSMART_SECURE_ROOT/runtime/S3_ACCESS_KEY_ID" \
  --from-file=S3_SECRET_ACCESS_KEY="$NOMOSMART_SECURE_ROOT/runtime/S3_SECRET_ACCESS_KEY" \
  --from-file=OPENSEARCH_ADMIN_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/OPENSEARCH_ADMIN_PASSWORD" \
  --from-file=OPENSEARCH_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/OPENSEARCH_PASSWORD" \
  --from-file=NEO4J_ADMIN_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/NEO4J_ADMIN_PASSWORD" \
  --from-file=NEO4J_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/NEO4J_PASSWORD" \
  --from-file=OIDC_CLIENT_SECRET="$NOMOSMART_SECURE_ROOT/runtime/OIDC_CLIENT_SECRET" \
  --from-file=KEYCLOAK_SYNC_CLIENT_SECRET="$NOMOSMART_SECURE_ROOT/runtime/KEYCLOAK_SYNC_CLIENT_SECRET" \
  --from-file=BREAK_GLASS_INITIAL_PASSWORD="$NOMOSMART_SECURE_ROOT/runtime/BREAK_GLASS_INITIAL_PASSWORD"
```

Namespace 已存在時，先檢查 Ownership，再只執行 Secret 指令。依 Values Overlay 的名稱建立 External PostgreSQL、Redis、S3、OpenSearch 與 Neo4j CA Secret：

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  create secret generic external-postgresql-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/postgresql-ca.crt"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  create secret generic external-redis-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/redis-ca.crt"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  create secret generic external-rustfs-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/s3-ca.crt"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  create secret generic external-opensearch-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/opensearch-ca.crt"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  create secret generic external-neo4j-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/neo4j-ca.crt"
```

已設定 Registry 與 Directory Reference 時，使用第 8.6 節的指令建立對應 Input。

### 9.6 執行並核准 Read-only Plan

```bash
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --plan-only
```

Plan 會檢查目標 Cluster、Package、所選 Profile、服務連線、TLS Trust、既有 Runtime 與 CA Secret、Image Digest、容量，以及 Helm 產生的資源。保存並核准畫面顯示的 `config_digest`。

### 9.7 安裝、Resume 並驗證

```bash
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG"
```

收到提示時，在 `$NOMOSMART_PUBLIC_URL/login` 完成受保護的 Identity Checkpoint，然後再次執行相同指令繼續。

驗證結果：

```bash
./deploy/installer/nomosmart-install status \
  --config "$NOMOSMART_INSTALL_CONFIG"
./deploy/installer/nomosmart-install verify \
  --config "$NOMOSMART_INSTALL_CONFIG"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get pods,jobs
curl --fail --silent --show-error "$NOMOSMART_PUBLIC_URL/api/backend/health"
curl --fail --silent --show-error "$NOMOSMART_PUBLIC_URL/api/backend/ready"
```

完整 Verification 會確認 NomoSmart Workload、Migration 與 Bootstrap Job、OIDC，以及所有已設定 External Service 的連線。最後完成第 7.8 節的 Model Service 與 Project 驗證。

<a id="method-4-source-development"></a>

## 10. 方法四：Source Development

Source Development 會直接在開發者電腦上執行 Frontend、Backend、Worker 與 Beat，並連接已經啟動的 PostgreSQL、Redis、S3 相容儲存空間、OpenSearch、Neo4j 與 Keycloak。

### 10.1 安裝 Source Dependency

```bash
git clone --branch v0.1.0 --single-branch https://github.com/crispkid/Nomosmart.git
cd Nomosmart/backend
uv sync --locked --all-extras
cd ../frontend
npm ci
cd ..
```

Python 必須為 3.12。`uv sync --locked` 會依 `backend/uv.lock` 安裝且不修改 Lockfile，`npm ci` 使用 `frontend/package-lock.json`。

### 10.2 準備 Live Dependency

準備可連線的 PostgreSQL、Redis、S3 相容儲存空間、OpenSearch、Neo4j 與 Keycloak，並整理好 Endpoint、Credential、CA Path、Database Name、Bucket、Search Index Prefix、OIDC Issuer、Client ID 與 Audience。

Backend Readiness 會驗證這些 Dependency；Development 與 Deployment 使用相同的 Connection Boundary。

### 10.3 建立本機設定

```bash
cp -i backend/.env.example backend/.env
cp -i frontend/.env.example frontend/.env.local
```

替換 `backend/.env` 與 `frontend/.env.local` 的所有 Placeholder，並維持兩個檔案不進入版本控制。至少設定 Database、Redis/Celery、S3、OpenSearch、Neo4j、OIDC、Keycloak Synchronization、Encryption Key、Frontend Origin、Backend Proxy 與 OIDC Client。

### 10.4 套用 Database Migration

從 Repository 根目錄執行。先填入 Flyway Container 可連線的資料庫主機、Migration 帳號及 PostgreSQL CA 路徑。資料庫與帳號需事先建立，該帳號須有建立應用程式 Schema 物件的權限；密碼在隱藏輸入提示中輸入：

```bash
export FLYWAY_URL="jdbc:postgresql://<database-host-reachable-from-container>:5432/nomosmart?sslmode=verify-full&sslrootcert=/run/nomosmart/postgresql-ca.crt"
export FLYWAY_USER="<migration-user>"
export NOMOSMART_POSTGRES_CA="/absolute/path/to/postgresql-ca.crt"
export FLYWAY_PASSWORD="$(python3 -c 'import getpass; print(getpass.getpass("Database migration password: "))')"
export NOMOSMART_FLYWAY_IMAGE="$(python3 -c 'import json; print(json.load(open("deploy/release/external-dependencies.lock.json"))["images"]["migration"]["reference"])')"
docker run --rm \
  -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD \
  -e FLYWAY_BASELINE_ON_MIGRATE=false \
  -v "$PWD/sql/migrations:/flyway/sql:ro" \
  -v "$NOMOSMART_POSTGRES_CA:/run/nomosmart/postgresql-ca.crt:ro" \
  "$NOMOSMART_FLYWAY_IMAGE" migrate
unset FLYWAY_PASSWORD
```

全新的空白資料庫只執行一次 `B051__nomosmart_0_1_0.sql`。已有 Flyway 歷史的資料庫沿原 `V001`–`V051` 檔案升級，原始 Checksum 保持不變。請保留完整 Migration 目錄。成功時 Flyway 顯示完成訊息且結束碼為 `0`；重跑時會顯示結構已是目前版本。

啟動 Backend、Worker 或 Beat 前，將以下設定填入 `backend/.env`。數值來自 [release-contract.json](deploy/migrations/release-contract.json)；Compose 與 Kubernetes 安裝器會自動產生：

```dotenv
MIGRATION_REQUIRED_VERSION=051
MIGRATION_REQUIRED_CHECKSUM=1782483375
MIGRATION_BASELINE_CHECKSUM=1904638595
```

### 10.5 執行 Deployment Bootstrap

```bash
cd backend
uv run python -m app.deployment.bootstrap --mode ensure
cd ..
```

Bootstrap 會依照設定檢查或建立必要的 S3 Bucket、OpenSearch Resource、Neo4j Constraint、Keycloak Realm、Client 與平台初始化狀態。

### 10.6 啟動 Application Process

在不同 Terminal 執行各項指令。

Backend：

```bash
cd backend
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

Worker：

```bash
cd backend
uv run celery -A app.worker:celery_app worker --concurrency 2 --loglevel INFO
```

Beat：

```bash
cd backend
uv run celery -A app.worker:celery_app beat --loglevel INFO
```

Frontend：

```bash
cd frontend
npm run dev
```

### 10.7 驗證 Development Runtime

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/ready
curl --fail --silent --show-error http://127.0.0.1:3000/login
```

Backend Process Health 的預期結果為 `{"status":"healthy"}`，Readiness 應回報 `"status":"ready"`。開啟 `http://127.0.0.1:3000`，完成 OIDC Login，並執行第 7.8 節的 Model 與 Project 驗證。

## 11. 設定參考

### 11.1 設定位置與優先順序

| Runtime | 非機密設定 | Secret 來源 | 優先順序 |
| --- | --- | --- | --- |
| Backend Development | 從 `backend/.env.example` 複製的 `backend/.env` | Environment 或 Allowlist 內的 `<SETTING>_FILE` | Programmatic Value → Environment → `.env` → Allowlisted Secret File → Framework File Secret |
| Frontend Development | 從 `frontend/.env.example` 複製的 `frontend/.env.local` | OIDC Client Secret 保留於 Server-side | Next.js Environment Loading 與 Server Runtime Value |
| Docker Compose | 產生的 `deploy/docker/nomosmart.env` | `deploy/docker/generated/current/` 下的 Owner-only File，掛載至 `/run/secrets` | 明確 `--env-file` → Compose Default → Mounted Secret File |
| Kubernetes bundled | Installer TOML 與依序套用的 Helm Values | Installer 管理或引用的 Kubernetes Secret | 後面的 Values 覆寫前面的 Values；Secret 提供敏感值 |
| Kubernetes external | Installer TOML、Production Values 與 External Overlay | 既有 Runtime 與 CA Secret | 後面的 Values 覆寫前面的 Values；Existing Secret 提供敏感值 |

Process 或 Pod 會在啟動時讀取設定。修改後，請重新啟動受影響的 Backend、Worker、Beat 或 Frontend。Database Migration 與平台初始化則透過對應的 Job 或 Command 執行。

### 11.2 Backend 核心設定

| 類別 | 設定 | 必填或預設值 | 用途 |
| --- | --- | --- | --- |
| 應用程式 | `APP_ENV` | `development`；可用值為 `development`、`test`、`production` | 選擇開發、測試或正式環境規則 |
| 應用程式 | `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Backend 監聽位址與 Port |
| 應用程式 | `DEPLOYMENT_BOOTSTRAP_RELEASE` | 平台初始化時必填 | 標示目前初始化的 Release |
| Log | `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json`；格式可用 `json` 或 `text` | 控制 Log 詳細程度與格式 |
| 網路 | `CORS_ALLOWED_ORIGINS` | Development 預設為本機 Frontend Origin | 允許 Browser 存取的 Origin，以逗號分隔 |
| 網路 | `FRONTEND_APP_ORIGIN` | `http://127.0.0.1:3000` | Frontend 的標準 Origin |
| Database | `DATABASE_URL` | 必填 | PostgreSQL 連線字串 |
| Queue | `REDIS_URL` | 必填 | 應用程式使用的 Redis 連線 |
| Queue | `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | 必填 | Celery 工作佇列與結果儲存位置 |
| Storage | `S3_ENDPOINT_URL` / `S3_REGION` / `S3_BUCKET` | Endpoint 必填；`us-east-1` / `nomosmart` | S3 相容 Storage 位置 |
| Storage | `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | 必填 Secret | S3 存取帳號與密碼 |
| Storage | `S3_USE_SSL` / `S3_VERIFY_TLS` / `S3_PATH_STYLE_ACCESS` | 本機預設為 `false` / `false` / `true` | 控制 S3 TLS 與 URL 格式 |
| Storage | `S3_CA_CERT_PATH` | 使用 Private CA 時必填 | S3 CA Certificate 路徑 |
| Search | `OPENSEARCH_URL` / `OPENSEARCH_INDEX_PREFIX` | URL 必填；`nomosmart-dev` | Search Endpoint 與 Index Namespace |
| Search | `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | 必填 | OpenSearch 帳號與密碼 |
| Search | `OPENSEARCH_VERIFY_TLS` / `OPENSEARCH_CA_CERT_PATH` | Production 必須驗證 TLS | OpenSearch TLS 與 CA Certificate |
| Graph | `NEO4J_URI` / `NEO4J_DATABASE` | `bolt://127.0.0.1:7687` / `neo4j` | Graph Endpoint 與 Database |
| Graph | `NEO4J_USERNAME` / `NEO4J_PASSWORD` | 必填 | Neo4j 帳號與密碼 |
| Authentication | `OIDC_ISSUER_URL` / `OIDC_CLIENT_ID` / `OIDC_AUDIENCE` | 必填 | JWT Issuer、Backend Client 與 Audience |
| Authentication | `OIDC_DISCOVERY_URL` / `OIDC_JWKS_URL` | 空白時依 Issuer 自動產生 | OIDC Metadata 與 Signing Key Endpoint |
| Authentication | `OIDC_CLIENT_SECRET` | Confidential Flow 必填 | Backend OIDC Client Secret |
| Identity | `KEYCLOAK_ADMIN_API_URL` / `KEYCLOAK_ADMIN_INTERNAL_URL` | Public URL 必填 | Keycloak 管理 API 位址 |
| Identity | `KEYCLOAK_SYNC_CLIENT_ID` / `KEYCLOAK_SYNC_CLIENT_SECRET` | 必填 | 企業目錄同步使用的 Client |
| Identity | `IDENTITY_SYNC_SCHEDULE` / `IDENTITY_SYNC_TIMEZONE` | `0 2 * * *` / `Asia/Taipei` | 同步排程與時區 |
| Identity | `IDENTITY_SYNC_ENABLED` / `IDENTITY_SYNC_SCOPE` | `true` / `people_and_groups` | 是否啟用排程同步，以及同步範圍 |
| Security | `APP_ENCRYPTION_KEY` | 必填的 64 字元十六進位 Secret | 加密受保護的應用程式欄位 |
| Security | `BREAK_GLASS_USERNAME` / `BREAK_GLASS_RUNBOOK_URI` / `BREAK_GLASS_ALERTING_EVIDENCE` | 依部署環境設定 | 緊急管理帳號、操作手冊與告警路由參考 |
| Ingestion | `NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB` | `100`；範圍 1–10240 | 單一文件大小上限 |
| Upload | `DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB` | 未設定時為單檔上限加 1 MiB；範圍 2–10241 | 整個 multipart request 的大小上限 |
| Upload | `NOMOSMART_UPLOAD_MAX_INFLIGHT` / `NOMOSMART_UPLOAD_IO_CHUNK_KIB` | `2` / `64` | 同時處理的上傳數量與串流區塊大小 |
| Upload | `NOMOSMART_UPLOAD_METADATA_MAX_KIB` / `NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB` | `1024` / `16` | Multipart metadata 與每個 part header 的上限 |
| Upload | `NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS` / `NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS` | `60` / `600` | 上傳閒置與總時間上限 |
| Upload | `NOMOSMART_UPLOAD_SCRATCH_DIR` / `NOMOSMART_UPLOAD_SCRATCH_MAX_MIB` | `/tmp/nomosmart-upload` / `256` | 上傳暫存目錄與容量 |
| Ingestion | `TARGET_CHUNK_TOKENS` / `MAX_CHUNK_TOKENS` / `MIN_CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `500` / `700` / `80` / `60` | Structure-aware Chunk Size |
| Ingestion | `PANDOC_COMMAND` / `TESSERACT_COMMAND` / `TESSERACT_PDF_COMMAND` | `pandoc` / `tesseract` / `pdftoppm` | 文件轉換與 OCR Executable |
| Remote Sources | `HTTP_SOURCE_ALLOWED_HOSTS` / `HTTP_SOURCE_ALLOWED_CIDRS` | 空白 Allowlist | 核准的 HTTP/API Destination |
| Remote Sources | `SFTP_KNOWN_HOSTS_PATH` | `/etc/nomosmart/ssh_known_hosts` | SFTP Host-key Trust File |
| Public API | `PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit Window |
| Public API | `PUBLIC_API_INVALID_AUTH_REQUESTS_PER_MINUTE` | `20` | Invalid-auth Request Limit |
| Public API | `PUBLIC_API_IDEMPOTENCY_TTL_HOURS` | `24` | Idempotency Record Lifetime |
| Public API | `PUBLIC_API_CONTENT_RETENTION_DAYS` / `PUBLIC_API_RECORD_RETENTION_DAYS` | `30` / `365` | Encrypted Content 與 Request Record Retention |

整個 Upload Request 的上限至少要比單檔上限多 1 MiB。Total Timeout 不可短於 Idle Timeout，Part Header 上限不可大於 Metadata 上限。Scratch 容量必須足以容納所有同時上傳的檔案，再加 16 MiB。Source Development 預設使用 `/tmp/nomosmart-upload`；Compose 與 Helm 使用 `/var/lib/nomosmart-upload/private`。

Production 必須使用 HTTPS、驗證 S3 與 OpenSearch TLS、替換所有 Placeholder Credential，並設定非零的 64 字元十六進位 Encryption Key 及完整的 Release 資訊。

### 11.3 Frontend 與 Edge 設定

| Setting | Default 或 Example | 用途 |
| --- | --- | --- |
| `NEXT_PUBLIC_APP_ORIGIN` | `http://127.0.0.1:3000` | Browser 可見的 Application Origin |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/backend` | Browser Backend Proxy Path |
| `BACKEND_INTERNAL_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | Server-side Backend Upstream |
| `NEXT_PUBLIC_OIDC_ISSUER_URL` | `http://127.0.0.1:8080/realms/nomosmart` | Browser OIDC Issuer |
| `NEXT_PUBLIC_OIDC_CLIENT_ID` | `nomosmart-frontend` | OIDC Public Client |
| `NEXT_PUBLIC_OIDC_AUDIENCE` | `nomosmart-backend` | Access Token 的預期 Audience |
| `BACKEND_EDGE_UPSTREAM` | Compose 預設為 `http://backend:8000` | Edge Proxy 連線 Backend 使用的內部 Origin |
| `PUBLIC_API_READ_TIMEOUT_SECONDS` | `600`；範圍 1–3600 | Public JSON 與 SSE Proxy 的閒置讀取逾時 |

### 11.4 Secret 與文件處理設定

Backend 支援以 `<SETTING>_FILE` 提供 Allowlist 內的敏感設定，包括 Encryption Key、Database、Redis/Celery、S3 Credential、OpenSearch Password、Neo4j Password、OIDC Client Secret、Keycloak Sync Secret、Bootstrap Credential 與 Break-glass Value。

Secret File 必須是 Regular File。Production 中位於 `/run/secrets/` 之外的檔案不可提供 Group 或 Other 權限。Direct Environment Value 與 File Value 不一致時，Production Configuration Loading 會停止並回報設定衝突。

Neo4j 使用 `bolt://` 或 `neo4j://` 時，會在管理人員控制的內部網路上建立需要帳號密碼的連線。使用 `bolt+s://` 或 `neo4j+s://` 時，必須驗證 Certificate 與 Hostname；可以使用系統 Trust Store，或設定 `NEO4J_CA_CERT_PATH`。對應的 Helm 設定是 `neo4j.external.caSecretName`。TLS 連線失敗時不會改用明文連線，也不接受 `+ssc`。

DOCX 由現有 Worker 呼叫 Pandoc 處理，並固定使用 Pandoc 內建的 `--sandbox`。`PANDOC_COMMAND` 只能填一個執行檔名稱，不可加入其他參數。Timeout、Memory 與 Cache Limit 可透過設定調整；`PANDOC_SANDBOX_COMMAND` 會被忽略。DOCX 引用的外部資源會被拒絕，一般 HTTP、HTTPS 與 Email 連結只保留為文字連結，不會下載內容。

### 11.5 本機設定範例

```dotenv
APP_ENV=development
DEPLOYMENT_BOOTSTRAP_RELEASE=engineering-local
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=json
CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000
FRONTEND_APP_ORIGIN=http://127.0.0.1:3000

DATABASE_URL=postgresql+psycopg2://nomosmart:<database-password>@127.0.0.1:5432/nomosmart
REDIS_URL=redis://:<redis-password>@127.0.0.1:6379/0
CELERY_BROKER_URL=redis://:<redis-password>@127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://:<redis-password>@127.0.0.1:6379/1

S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_REGION=us-east-1
S3_BUCKET=nomosmart
S3_ACCESS_KEY_ID=<s3-access-key>
S3_SECRET_ACCESS_KEY=<s3-secret-key>
S3_USE_SSL=false
S3_VERIFY_TLS=false
S3_PATH_STYLE_ACCESS=true

OPENSEARCH_URL=https://127.0.0.1:9200
OPENSEARCH_USERNAME=nomosmart
OPENSEARCH_PASSWORD=<opensearch-password>
OPENSEARCH_VERIFY_TLS=false
OPENSEARCH_INDEX_PREFIX=nomosmart-dev

NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_DATABASE=neo4j
NEO4J_USERNAME=nomosmart
NEO4J_PASSWORD=<neo4j-password>

OIDC_ISSUER_URL=https://nomosmart.local/identity/realms/nomosmart
OIDC_CLIENT_ID=nomosmart-backend
OIDC_CLIENT_SECRET=<oidc-client-secret>
OIDC_AUDIENCE=nomosmart-backend
KEYCLOAK_ADMIN_API_URL=https://nomosmart.local/identity
KEYCLOAK_SYNC_CLIENT_ID=nomosmart-sync
KEYCLOAK_SYNC_CLIENT_SECRET=<keycloak-sync-client-secret>

APP_ENCRYPTION_KEY=<64-character-hex-key>
DEFAULT_TIMEZONE=Asia/Taipei
NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB=100
DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB=101
NOMOSMART_UPLOAD_MAX_INFLIGHT=2
NOMOSMART_UPLOAD_IO_CHUNK_KIB=64
NOMOSMART_UPLOAD_METADATA_MAX_KIB=1024
NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB=16
NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS=60
NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS=600
NOMOSMART_UPLOAD_SCRATCH_DIR=/tmp/nomosmart-upload
NOMOSMART_UPLOAD_SCRATCH_MAX_MIB=256
```

完整 Variable Inventory 由 [backend/.env.example](backend/.env.example)、[frontend/.env.example](frontend/.env.example) 與 [deploy/docker/nomosmart.env.example](deploy/docker/nomosmart.env.example) 維護。

### 11.6 初始化文件處理政策

執行前，先完成資料庫 Migration、平台初始化、管理員首次登入與角色同步。維護指令需要有效的 OIDC Access Token；帳號須已啟用，並具有「系統管理」的「檢視、編輯」權限。首次匯入文件前完成此步驟。

1. 產生一個部署 UUID，與受保護的安裝設定一併保存。重跑初始化時使用同一個 UUID；另一套獨立安裝才使用新的 UUID。

```bash
export NOMOSMART_DEPLOYMENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
printf '%s\n' "$NOMOSMART_DEPLOYMENT_ID"
```

2. 使用具備上述權限的管理員登入 NomoSmart。在瀏覽器開發者工具中，查看一筆成功且已認證的 `/api/backend/` 請求，複製 `Authorization: Bearer …` 標頭中的 Token，去除 `Bearer ` 前綴。使用 Access Token，不是 ID Token 或 Integration API Key。Token 僅輸入下方的隱藏提示，妥善保密；過期後重新取得。
3. 依安裝方法執行下列一組指令。第一個指令初始化缺少的設定，第二個讀取已保存的政策。

**Docker Compose**：在 Source Checkout 根目錄執行：

```bash
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  docker compose --env-file deploy/docker/nomosmart.env exec -T backend \
  /opt/nomosmart/compose-secret-entrypoint.sh backend \
  python -m app.deployment.file_processing_policy initialize \
  --expected-revision 0 --deployment-id "$NOMOSMART_DEPLOYMENT_ID"
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  docker compose --env-file deploy/docker/nomosmart.env exec -T backend \
  /opt/nomosmart/compose-secret-entrypoint.sh backend \
  python -m app.deployment.file_processing_policy read
```

Compose 包裝指令會套用與 Backend 程序相同的受保護 Secret 路徑及非 Root 執行身分。

**Kubernetes**：將 Deployment 名稱替換為第一個指令列出的實際名稱，例如 `nomosmart-backend`。

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  get deployments -l app.kubernetes.io/component=backend
export NOMOSMART_BACKEND_DEPLOYMENT="<backend-deployment-name>"
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  exec -i "deployment/$NOMOSMART_BACKEND_DEPLOYMENT" -c backend -- \
  python -m app.deployment.file_processing_policy initialize \
  --expected-revision 0 --deployment-id "$NOMOSMART_DEPLOYMENT_ID"
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  kubectl --context "$NOMOSMART_KUBE_CONTEXT" --namespace "$NOMOSMART_NAMESPACE" \
  exec -i "deployment/$NOMOSMART_BACKEND_DEPLOYMENT" -c backend -- \
  python -m app.deployment.file_processing_policy read
```

**Source Development**：先完成 `backend/.env` 設定：

```bash
cd backend
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  uv run python -m app.deployment.file_processing_policy initialize \
  --expected-revision 0 --deployment-id "$NOMOSMART_DEPLOYMENT_ID"
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  uv run python -m app.deployment.file_processing_policy read
cd ..
```

新政策會回傳包含 `revision: 1`、`content_hash` 與 `values` 的 JSON。讀取結果的 Revision 與 Hash 應相同。使用相同部署 UUID 重跑初始化會保留既有設定；後續調整透過獨立的維護操作檢查 Revision 後更新。將回傳的政策資訊與安裝設定一併保存。

### 11.7 準備 LDAP 或 Windows AD 連線

Keycloak 負責驗證目錄帳號；NomoSmart 同步使用者及群組，再透過本機角色授予應用程式權限。

請與目錄管理員確認下列資料：

| 項目 | 必要內容 |
| --- | --- |
| 目錄位址 | `ldaps://<certificate-hostname>:636`，Keycloak 與安裝環境均可連線 |
| 憑證信任 | PEM 格式的簽發 CA Chain，憑證 SAN 包含目錄主機名稱 |
| 唯讀 Bind 帳號 | Bind DN 與密碼，具有指定使用者、群組、屬性及成員關係的讀取權限 |
| 搜尋範圍 | 涵蓋指定帳號及群組的 Users DN、Groups DN |
| 身分欄位 | 登入欄位、穩定 UUID 欄位、RDN、Object Class 與群組成員格式 |
| 應用程式管理員 | 既有目錄帳號，且屬於既有 `nomosmart-admins` 群組或組織指定的管理群組 |
| 身分管理權限 | 手動設定使用授權的 Keycloak 管理員；Kubernetes 安裝器使用設定的服務帳號 |

確認相關網路的 DNS 與 TCP 636 連線。從安裝環境檢查 CA 與主機名稱：

```bash
export NOMOSMART_DIRECTORY_HOST="<directory-certificate-hostname>"
export NOMOSMART_DIRECTORY_CA="/absolute/path/to/directory-ca.crt"
openssl s_client -connect "$NOMOSMART_DIRECTORY_HOST:636" \
  -servername "$NOMOSMART_DIRECTORY_HOST" -CAfile "$NOMOSMART_DIRECTORY_CA" \
  -verify_hostname "$NOMOSMART_DIRECTORY_HOST" -verify_return_error </dev/null
```

憑證驗證應成功。此指令只確認目前這條連線，Keycloak 本身也須信任相同 CA 並能連線到該位址。

**Kubernetes bundled**：在 `[identity]` 填入目錄 Secret 名稱，依第 8.6 節建立 Secret；Chart 會將 CA 掛載到 Keycloak Truststore。**外部 Keycloak**：由其管理員安裝 CA，並依需要重新啟動服務。只在 NomoSmart Namespace 建立 Secret，不會改動另一套獨立管理的 Keycloak。

**Docker Compose**：在 Source Checkout 建立已被 Git 忽略的 `docker-compose.override.yml`。將絕對路徑替換為公開 CA 檔案位置，以唯讀方式掛載，再重新建立 Keycloak Container：

```yaml
services:
  keycloak:
    environment:
      KC_TRUSTSTORE_PATHS: /opt/keycloak/conf/truststores
    volumes:
      - /absolute/path/to/directory-ca.crt:/opt/keycloak/conf/truststores/directory-ca.pem:ro
```

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d keycloak
```

CA 檔案須可由 Keycloak Container 的執行身分讀取。目錄信任設定使用 [Keycloak Truststore](https://www.keycloak.org/server/keycloak-truststore)，CA 私鑰由原管理者保管。

### 11.8 設定目錄 Provider

**Kubernetes 安裝器**

執行方法二或方法三的 Plan 前，編輯已產生 TOML 的 `[identity]` 區段，保留原有 Release、Chart 與映像參照。以下使用 OpenLDAP 與 DN 格式的群組成員資料；主機名稱、DN 及帳號須替換為實際值：

```toml
[identity]
mode = "ldap"
realm = "nomosmart"
provider_name = "corporate-directory"
mapper_name = "corporate-groups"
admin_username = "<directory-administrator-login>"
external_group_name = "nomosmart-admins"
local_role_name = "system-admin"
server_url = "ldaps://ldap.example.com:636"
users_dn = "ou=People,dc=example,dc=com"
groups_dn = "ou=Groups,dc=example,dc=com"
bind_dn = "cn=nomosmart-bind,ou=ServiceAccounts,dc=example,dc=com"
bind_secret_name = "nomosmart-directory-bind"
bind_secret_key = "bind-password"
ca_secret_name = "nomosmart-directory-ca"
ca_secret_key = "ca.crt"
username_attribute = "uid"
rdn_attribute = "cn"
uuid_attribute = "entryUUID"
user_object_classes = ["inetOrgPerson"]
group_object_classes = ["groupOfNames"]
group_name_attribute = "cn"
membership_attribute = "member"
membership_attribute_type = "DN"
membership_user_attribute = "uid"
user_search_scope = "subtree"
preserve_group_inheritance = true
custom_user_filter = "(objectClass=inetOrgPerson)"
group_path = "/ldap"
```

Windows AD 使用相同欄位，並調整下列目錄設定：

| 設定 | Windows AD 範例 |
| --- | --- |
| `mode` | `"active-directory"` |
| `server_url` | `"ldaps://dc01.example.com:636"` |
| `users_dn` / `groups_dn` | `"OU=Users,DC=example,DC=com"` / `"OU=Groups,DC=example,DC=com"` |
| `bind_dn` | 服務帳號實際的 Distinguished Name |
| `username_attribute` / `membership_user_attribute` | `"sAMAccountName"` / `"sAMAccountName"` |
| `rdn_attribute` / `uuid_attribute` | `"cn"` / `"objectGUID"` |
| `user_object_classes` | `["person", "organizationalPerson", "user"]` |
| `group_object_classes` | `["group"]` |
| `custom_user_filter` | `"(objectClass=user)"` |
| `user_search_scope` | `"subtree"` |

使用搜尋範圍及 Filter 選出需要的人員。既有的 `CN=Users` Container 與自建 `OU=Users` 是不同 DN。兩種目錄的 RDN 與成員欄位均須符合實際 Schema，套用範例前應先確認。

安裝器會在指定 Realm 建立或核對一個 LDAP Provider 與一個 Group Mapper，使用唯讀目錄連線、匯入使用者、將群組同步到 `/ldap`，並把指定管理群組對應到 NomoSmart 的 `system-admin` 角色。目錄物件由目錄管理員維護。使用 `mode = "preconfigured"` 時，須事先備妥相符的 Provider 與 Mapper；安裝器仍會執行同步與應用程式角色對應。

**手動設定 Keycloak，包含 Docker Compose**

1. 使用第 7.6 節準備的具名管理員，或既有身分服務提供的管理員，登入 Keycloak 管理介面。
2. 選擇 `nomosmart` Realm。平台初始化會準備 `nomosmart-frontend` Public Client、`nomosmart-backend` Confidential Client 及 `nomosmart-sync` 服務帳號。Redirect URL、Audience 與 Client Secret 維持與 NomoSmart 設定一致。
3. 開啟 **User federation → Add LDAP provider**。OpenLDAP 使用一般 LDAP Vendor，AD 選擇 **Active Directory**。依上述資料填入連線位址、Users DN、Bind DN、Bind 密碼、登入／RDN／UUID 欄位、Object Class、Filter 與搜尋範圍。
4. 設定 **Edit mode = READ_ONLY**、**Import users = ON**、**Sync registrations = OFF**，啟用分頁查詢與 CA 驗證的 LDAPS。測試連線及認證成功後儲存。
5. 在 Provider 的 **Mappers** 建立一個 **group-ldap-mapper**，填入 LDAP Groups DN、群組名稱欄位 `cn`、群組 Object Class、成員欄位 `member`、成員型別 `DN` 與對應的使用者成員欄位。選擇唯讀模式，Group Path 設為 `/ldap`，並設定所需的群組繼承方式。
6. 將 LDAP 群組同步到 Keycloak，再同步所有使用者。確認指定群組與使用者均出現在此 Realm 後繼續。

`KEYCLOAK_LDAP_GROUP_PATH` 須與群組路徑相同。目錄帳號的密碼異動依目錄管理流程辦理。Provider 控制項可參考 [Keycloak LDAP 管理指南](https://www.keycloak.org/docs/latest/server_admin/#_ldap)。

### 11.9 對應使用者欄位與應用程式角色

先檢查 Provider 既有的 Attribute Mapper，再依組織需要新增或調整欄位：

| 目錄欄位 | Keycloak 目的欄位 | NomoSmart 用途 |
| --- | --- | --- |
| `givenName` | User Property `firstName` | 名 |
| `sn` | User Property `lastName` | 姓 |
| `mail` | User Property `email` | 電子郵件 |
| LDAP `employeeNumber` 或 AD `employeeID` | User Attribute `employee_id` | 選用的唯一員工編號 |
| `department` | User Attribute `department` | 部門 |
| `title` | User Attribute `title` | 職稱 |
| `manager` | User Attribute `manager` | 主管的目錄 DN |

使用唯讀 LDAP Attribute Mapper。啟用選用欄位前，先確認來源欄位名稱及員工編號的唯一性。若目錄提供主管的員工編號，應用程式也接受 `manager_employee_id`。

在 NomoSmart 完成以下設定：

1. Keycloak 匯入完成後，開啟「使用者管理 → 身分同步」，執行「立即同步」。
2. 確認同步完成，並能看到使用者與 LDAP 群組。
3. 在「角色與外部群組」選擇本機角色，設定 LDAP 群組映射。手動設定時，將管理群組對應到 `system-admin`；安裝器會為其指定管理群組完成此對應。
4. 依所需選單及專案權限，將其他目錄群組對應到適當角色。角色與外部群組採一對一映射；使用者屬於多個已映射群組時，權限取各角色的聯集。
5. 分別使用指定目錄管理員與一般目錄使用者重新登入，確認各帳號取得正確權限。

### 11.10 驗證目錄登入與同步

確認以下項目：

- Keycloak 可連線至 LDAPS，且 CA 與主機名稱驗證成功。
- 指定 Provider 已匯入預期的使用者、群組及成員關係。
- 指定目錄管理員可透過 NomoSmart 的 OIDC 流程登入。
- NomoSmart 身分同步完成，管理群組已對應到 `system-admin`。
- 一般目錄使用者可操作角色授權的功能。
- 首次使用的密碼操作已依對應帳號或目錄流程完成。

此步驟使用目錄帳號驗證；本機緊急帳號屬於另一條登入流程。

| 現象 | 檢查項目 |
| --- | --- |
| Keycloak 管理介面回傳 HTTP 403 | Edge 或 Ingress 管理 CIDR，以及 Proxy 實際看到的來源 IP |
| LDAPS 連線或憑證驗證失敗 | DNS、TCP 636、憑證 SAN、CA Chain，以及 Keycloak 掛載的 CA |
| Bind 認證失敗 | Bind DN、受保護的 Bind 密碼、帳號狀態與目錄讀取權限 |
| 找不到使用者或群組 | Users DN、Groups DN、搜尋範圍、Filter、Object Class 與成員欄位 |
| 可登入但沒有應用程式權限 | 身分同步是否完成、本機帳號狀態、群組成員關係及角色映射 |
| 員工資料不完整 | LDAP Attribute Mapper 與目錄內實際的屬性值 |

## 12. API 與使用方式

### 12.1 API 位置與認證

| Interface | Location | Authentication |
| --- | --- | --- |
| Internal API | `/api/v1` | 驗證 Issuer、Audience、Signature、Lifetime 與 Subject 的 OIDC Access Token |
| Public Integration API | `/api/public/v1` | `Authorization: Bearer <api-key>` 或 `X-NomoSmart-API-Key` |
| OpenAPI Document | `/openapi.json` | Backend Origin |
| Swagger UI | `/docs` | Backend Origin |
| 產品內 API Guide | `/api-docs` | 已登入的 NomoSmart 頁面 |
| Process Health | `/api/v1/health` | 回傳 `{"status":"healthy"}` |
| Dependency Readiness | `/api/v1/ready` | 回傳 `ready` Detail 或 HTTP 503 |

FastAPI 應用程式版本為 `0.1.0`，API 路徑保留 `/v1`。Backend Authorization 會合併 Local Role Permission 與 Project-scope Owner、Editor、Viewer Governance。

### 12.2 Public Chat 範例

將 Placeholder 替換為 Active Integration API Key、允許存取的 Project UUID 與 End-user Identity。

```bash
export NOMOSMART_API_ORIGIN="<backend-api-origin>"
export NOMOSMART_API_KEY="<api-key>"
export NOMOSMART_PROJECT_ID="<project-uuid>"
export NOMOSMART_IDEMPOTENCY_KEY="replace-with-a-unique-request-key"
curl --fail --silent --show-error \
  --request POST \
  --url "$NOMOSMART_API_ORIGIN/api/public/v1/projects/$NOMOSMART_PROJECT_ID/chat" \
  --header "Authorization: Bearer $NOMOSMART_API_KEY" \
  --header "Idempotency-Key: $NOMOSMART_IDEMPOTENCY_KEY" \
  --header "Content-Type: application/json" \
  --data '{
    "question": "How does this policy apply to onboarding?",
    "end_user": {
      "employee_id": "E12345",
      "employee_name": "Alex Chen",
      "department": "Legal"
    },
    "top_k": 5
  }'
```

成功的 Response 包含 `response_id`、`answer`、`citations`、`status`、選取的 Document/Version Identifier 與 `request_id`。Streaming 使用 `POST /api/public/v1/projects/{project_id}/chat/stream`；Feedback 使用 `POST /api/public/v1/chat/responses/{response_id}/feedback`。

## 13. 開發指令

### 13.1 Frontend 指令

```bash
cd frontend
npm ci
npm run dev
npm run lint
npm run build
```

### 13.2 Backend 與部署指令

```bash
cd backend
uv sync --locked --all-extras
cd ..
docker compose config --no-env-resolution --quiet
helm lint deploy/helm/nomosmart
```

## 14. 部署與維運

- **Docker Compose** 使用 [docker-compose.yml](docker-compose.yml)、產生的環境設定檔、受保護的 Secret、Health Check、Named Volume 與單一本機 HTTPS 入口。
- **Kubernetes** 使用 [Helm Chart](deploy/helm/nomosmart)、各 Profile 的 Values、ConfigMap、Secret、Probe、Service、Ingress、NetworkPolicy、Job、資源限制與 Persistent Storage。
- **安裝包完整性**透過 [deploy/release/nomosmart-release](deploy/release/nomosmart-release) 在安裝前檢查。
- **Database Migration** 使用 [sql/migrations](sql/migrations) 內只能往前套用的檔案。Compose 與 Helm 會在應用程式進入 Ready 狀態前完成套用。
- **平台初始化** 透過 Command 或 Kubernetes Job 準備 Storage、Search、Graph 與 Identity Service。

第 19 節提供部署與正式環境操作文件。

## 15. 可觀測性

- `GET /api/v1/health` 顯示 Backend Process 是否正常執行。
- `GET /api/v1/ready` 顯示必要服務與初始化步驟是否已準備完成。
- `LOG_FORMAT` 與 `LOG_LEVEL` 控制 JSON 或文字格式，以及 Log 詳細程度。
- `docker compose ps` 與各 Service Log 可查看 Compose 部署狀態。
- Kubernetes Workload 包含 Readiness 與 Liveness Probe。
- Installer 的 `status`、`verify` 與 `doctor` 指令會隱藏敏感值。
- System Management 顯示服務狀態與稽核日誌。

## 16. 安全性

- Browser 與 Internal API 使用 Keycloak OIDC Authorization Code with PKCE 和 Signed JWT。
- Backend 會在每個受保護的操作中檢查本機角色與專案角色權限。
- LDAP、Active Directory、FreeIPA 或既有 Directory 設定可將外部群組映射到本機角色。
- 敏感設定保存在 Owner-only File、Docker Secret 或 Kubernetes Secret。
- 部署採用 HTTPS、可信任 CA、固定 Digest 的映像與安裝包完整性檢查。
- 稽核日誌涵蓋登入、權限、匯入、審核、發布、模型與設定變更。

## 17. 故障排除

### 17.1 Compose Preflight 回報 Hostname 或 Port 問題

```bash
grep -n "nomosmart.local" /etc/hosts
lsof -nP -iTCP:80 -sTCP:LISTEN
lsof -nP -iTCP:443 -sTCP:LISTEN
./deploy/package/nomosmart-package preflight --runtime compose
```

保留一筆 `127.0.0.1 nomosmart.local` Mapping，並釋放 80 與 443 Port。主機準備完成後重新執行 Preflight。

### 17.2 Compose Service 仍在準備

```bash
export NOMOSMART_DIAGNOSTIC_SERVICE="backend"
docker compose --env-file deploy/docker/nomosmart.env ps
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 "$NOMOSMART_DIAGNOSTIC_SERVICE"
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 migration deployment-bootstrap
```

從第一個未達預期狀態的 Dependency 或 Job 開始檢查。產生的設定與 Named Volume 會保留，完成修正後可安全重試。

### 17.3 Health 成功且 Readiness 回傳 HTTP 503

```bash
curl --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/api/backend/ready
```

讀取 `dependencies` Object，並檢查對應的 PostgreSQL、Redis、S3/RustFS、OpenSearch、Neo4j、Migration 或 Bootstrap Service。

### 17.4 OIDC Login 持續重新導向

```bash
curl --fail --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/identity/realms/nomosmart/.well-known/openid-configuration
```

確認 Browser Trust、Issuer URL、Client ID、Audience、Hostname 與 HTTPS Origin 均指向同一個 Realm 與 Public URL。

### 17.5 Kubernetes 安裝暫停

```bash
./deploy/installer/nomosmart-install status \
  --config "$NOMOSMART_INSTALL_CONFIG"
./deploy/installer/nomosmart-install doctor \
  --config "$NOMOSMART_INSTALL_CONFIG"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get pods,jobs
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" get events --sort-by=.lastTimestamp
```

完成回報的前置條件或 Identity Checkpoint，再執行相同的 Explicit-profile 指令。設定變更會產生新的 Digest，並回到 Read-only Plan 核准流程。

### 17.6 Source Backend 無法連線 Dependency

```bash
cd backend
uv run python -c "from app.core.config import get_settings; print(get_settings().app_env)"
curl --silent --show-error http://127.0.0.1:8000/api/v1/ready
```

依 Readiness 顯示的 Dependency，檢查 `backend/.env` 的 Endpoint、Credential Source、TLS Mode 與 CA Path。

## 18. 安裝驗證清單

依所選方法完成下列檢查：

- Frontend、Backend、Worker 與 Beat 正常執行。
- `/api/v1/health` 回報 `healthy`。
- `/api/v1/ready` 回報 `ready`。
- PostgreSQL、Redis、Object Storage、OpenSearch、Neo4j 與 Keycloak 可透過已設定的 Connection 存取。
- 新資料庫已完成 `B051`；既有資料庫已依原歷史升級至 `V051`，且 Bootstrap 已完成。
- 管理員已完成文件處理政策初始化。
- HTTPS 與 OIDC Login 可透過設定的 Public Hostname 使用。
- First-use Administrator Password 已更新，Role Mapping 提供預期的存取權限。
- 必要 Model Service 已通過 Connection Test，且預期的 Default Model 已啟用。
- Project 可以匯入、處理、審核、發布及查詢支援的文件。
- Answer 包含 Source Citation。

## 19. 相關文件

- [部署指南](deploy/README.md)
- [Docker 設定範例](deploy/docker/nomosmart.env.example)
- [Kubernetes 安裝器範例](deploy/installer/nomosmart-install.example.toml)
- [外部服務範例](deploy/installer/nomosmart-install.external-services.example.toml)
- [Migration 發布契約](deploy/migrations/release-contract.json)

## 20. 授權

NomoSmart 採用 [Apache License 2.0](LICENSE)。

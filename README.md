# NomoSmart

English | [繁體中文](README.zh-TW.md)

NomoSmart helps organizations turn documents and connected data into managed, searchable knowledge.

## 1. Overview

NomoSmart reads files and connected data sources, runs OCR when needed, converts content to Markdown, and splits it into searchable sections. Teams can review and publish each version, search the content, explore relationships, and ask questions with source citations.

The platform is designed for knowledge owners, editors, reviewers, administrators, integration developers, and business users. PostgreSQL stores application data. Redis and Celery run background work. S3-compatible storage keeps source files and generated content. OpenSearch handles search, Neo4j stores graph relationships, and Keycloak provides login and directory integration.

Release `0.1.1` includes installation fixes, tools, SQL, configuration templates, and documentation. Frontend and Backend images are published by this project; Worker and Beat use the Backend image. Supporting services and plugins are downloaded from their official publishers using [external-dependencies.lock.json](deploy/release/external-dependencies.lock.json). Prepare an isolated environment following the selected installation method.

## 2. Key Features

- **Import from common sources** — Accepts PDF, DOCX, TXT, and Markdown files, and connects to FTP, FTPS, SFTP, S3, and HTTP APIs.
- **Process documents** — Runs parsing and OCR, creates standard Markdown, splits content into useful sections, adds tags, and creates embeddings.
- **Manage versions** — Keeps source files, document versions, displayed content, sections, tags, references, and the currently published version.
- **Review and publish** — Sends content through review steps and publishes approved versions.
- **Search and ask questions** — Provides keyword, vector, and hybrid search, with citations that point back to the source document and section.
- **Explore relationships** — Shows links between projects, documents, sections, and tags in graph views and APIs.
- **Check answer quality** — Collects feedback, runs CSV-based checks, keeps retry history, and exports results.
- **Manage the platform** — Manages projects, users, roles, permissions, directory mappings, model services, system prompts, API clients, reports, and audit logs.
- **Use either interface language** — Provides Traditional Chinese and English interfaces.

## 3. Architecture

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
                                  +--> Chat / Embedding / OCR / Judge Services
```

Before the application reports that it is ready, setup jobs create or update the database and prepare the required services. The readiness endpoint checks PostgreSQL, Redis, object storage, OpenSearch, Neo4j, database migrations, and setup status.

## 4. Technology Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | Next.js 16.3.3, React 19.2.3, TypeScript 5 | Web application, OIDC flow, and Backend proxy |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic | REST API, configuration, domain logic, and persistence |
| Background processing | Celery 5.5+, Redis 7.4 | Ingestion, synchronization, validation, and scheduled work |
| Database | PostgreSQL 18.4, Flyway 13.6 | Authoritative state and forward-only migrations |
| Object storage | S3-compatible storage; RustFS in bundled deployments | Source documents and generated artifacts |
| Search | OpenSearch 2.19 | Keyword, vector, hybrid, and staging indexes |
| Graph | Neo4j 5.26 Community | Knowledge relationships and traversal |
| Identity | Keycloak 26.0.8, OIDC, LDAP/AD federation | Authentication, directory synchronization, and role mapping |
| Deployment | Docker Compose v2, Helm chart 0.1.1 | Single-host and Kubernetes deployment |

## 5. Project Structure

```text
Nomosmart/
├── frontend/                  Next.js application, UI components, and translations
├── backend/                   FastAPI API, workers, and application services
├── sql/migrations/            B051 initial schema and V001–V051 upgrade history
├── deploy/docker/             Docker Compose runtime configuration
├── deploy/helm/nomosmart/     Helm chart and environment values
├── deploy/installer/          Profile-aware Kubernetes installer
├── deploy/package/            Secret and TLS package lifecycle tool
├── deploy/release/            Release packaging and integrity checks
├── docs/                      Technical decisions and operating guides
└── docker-compose.yml         Single-host deployment model
```

## 6. Getting Started

Release `0.1.1` includes the Docker Desktop installation fixes for Compose, bundled Helm, external-services Helm and Source Development. Local Kubernetes Methods 2 and 3 use the [Docker Desktop/static PV guide](deploy/local/README.md), explicit PVs and a dedicated local ingress controller. Select the appropriate local or production profile, verify the package, and complete the required initialization steps.

### 6.1 Select an installation method

Choose the method that matches the target environment, then follow that section from start to finish.

| Method | Environment | Installed components |
| --- | --- | --- |
| [Method 1: Docker Compose](#method-1-docker-compose) | Workstation or single server | NomoSmart and all required supporting services |
| [Method 2: Kubernetes bundled](#method-2-kubernetes-bundled) | Kubernetes where NomoSmart manages its supporting services | NomoSmart, PostgreSQL, Redis, RustFS, OpenSearch, Neo4j, and Keycloak |
| [Method 3: Kubernetes external services](#method-3-kubernetes-external-services) | Kubernetes with existing shared services | NomoSmart workloads and setup jobs only |
| [Method 4: Source development](#method-4-source-development) | Developer workstation | Frontend, Backend, Worker, and Beat connected to existing services |

New Kubernetes installations use an explicit `bundled` or `external-services` profile. The Helm `auto` value remains available for existing deployment compatibility.

### 6.2 Prerequisites

The table lists a version only when the Repository sets one.

| Tool or requirement | Version | Used by | Check command |
| --- | --- | --- | --- |
| Git | Repository-compatible version | Compose and source development | `git --version` |
| GitHub CLI | Available CLI | Private repository and Release download | `gh --version` |
| Docker Engine or Docker Desktop | Compose-capable installation | Docker Compose and local Flyway | `docker version` |
| Docker Compose | v2 | Docker Compose | `docker compose version` |
| Python | Python 3.11+ for the installer; exactly 3.12 for Backend development | Package tool, installer, Backend | `python3 --version` |
| Node.js and npm | Node.js 24 container baseline | Frontend development | `node --version` and `npm --version` |
| uv | Lockfile-capable installation | Backend development | `uv --version` |
| kubectl | 1.28 or newer | Kubernetes methods | `kubectl version --client` |
| Helm | v3 or v4 | Kubernetes methods | `helm version` |
| OpenSSL | Available CLI | TLS package and Kubernetes installer | `openssl version` |
| curl | HTTPS-capable installation | Runtime verification | `curl --version` |
| lsof and `/etc/hosts` access | Unix-like host utilities | Compose preflight | `lsof -v` |

Install the tools for the selected method using the platform-specific guides: [Git](https://git-scm.com/downloads/), [GitHub CLI](https://github.com/cli/cli#installation), [Docker](https://docs.docker.com/engine/install/), [Python](https://www.python.org/downloads/), [Node.js](https://nodejs.org/en/download), [uv](https://docs.astral.sh/uv/getting-started/installation/), [kubectl](https://kubernetes.io/docs/tasks/tools/), and [Helm](https://helm.sh/docs/intro/install/). Select the versions in the table, open a new terminal, and run each applicable check command before continuing.

Kubernetes production installation requires at least three Ready schedulable nodes, the capacity defined by the rendered production plan, an IngressClass, an operator-selected StorageClass with explicit PV/CSI capacity evidence, public DNS, trusted TLS material, registry access, and an enterprise directory or preconfigured Keycloak identity provider.

The repository is private. A GitHub account with repository access is required for cloning and downloading the Release; image pulls also need access to the NomoSmart GHCR packages. Authenticate Git with your credential manager. Keep access tokens out of configuration examples and command-line arguments.

For Kubernetes installation, install the GitHub CLI and download the installation archive from the 0.1.1 Release:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth status
install -d -m 0700 "$HOME/nomosmart-downloads/0.1.1"
gh release download v0.1.1 --repo crispkid/Nomosmart \
  --pattern nomosmart-0.1.1.tar.gz \
  --dir "$HOME/nomosmart-downloads/0.1.1"
tar -xzf "$HOME/nomosmart-downloads/0.1.1/nomosmart-0.1.1.tar.gz" \
  -C "$HOME/nomosmart-downloads/0.1.1"
export NOMOSMART_RELEASE_DIR="$HOME/nomosmart-downloads/0.1.1/nomosmart-0.1.1"
```

Use a new download directory for each release. Follow Section 8.2 to check the extracted package before use. GitHub access and GHCR pull access are separate: provide a registry credential with package-read permission through the installer’s `registry_pull_secret`. The full profile also needs network access to Docker Hub, Quay, GHCR, OpenSearch artifacts, and the upstream CloudNativePG/Barman download locations listed in the lock file.

### 6.3 Ports and endpoints

| Mode | Port or URL | Purpose |
| --- | --- | --- |
| Docker Compose | `127.0.0.1:80` | HTTP redirect and edge health |
| Docker Compose | `127.0.0.1:443` | HTTPS application entry point |
| Source Frontend | `127.0.0.1:3000` | Next.js development server |
| Source Backend | `127.0.0.1:8000` | FastAPI, OpenAPI, and Swagger UI |
| Source dependencies | `5432`, `6379`, `9000`, `9200`, `7687`, `8080` | PostgreSQL, Redis, S3, OpenSearch, Neo4j, and Keycloak |
| Kubernetes | `https://<public-host>` | Ingress-managed application and OIDC entry point |

Compose keeps dependency ports inside its private network. The `debug` profile exposes selected dependency ports on loopback for engineering diagnostics.

<a id="method-1-docker-compose"></a>

## 7. Method 1: Docker Compose

Docker Compose is the simplest way to run the complete platform on one machine. It builds the application, starts every required service, updates the database, prepares the platform, and provides one HTTPS address.

### 7.1 Obtain the source

Clone the Repository and enter its root directory:

```bash
git clone --branch v0.1.1 --depth 1 https://github.com/crispkid/Nomosmart.git
cd Nomosmart
git status --short
```

Record the reviewed source revision containing the installation fixes:

```bash
git rev-parse HEAD
```

Keep the exact commit SHA with the installation record. Use the `v0.1.1` source tag to reproduce this release.

### 7.2 Verify host tools

```bash
docker version
docker compose version
python3 --version
openssl version
lsof -v
```

`docker version` must display both Client and Server information. Start Docker Engine or Docker Desktop when the Server section is unavailable.

### 7.3 Prepare the local hostname and ports

The local package uses `https://nomosmart.local`. Inspect the host mapping:

```bash
grep -n "nomosmart.local" /etc/hosts
```

When no mapping exists, add one:

```bash
echo "127.0.0.1 nomosmart.local" | sudo tee -a /etc/hosts
```

Keep exactly one entry:

```text
127.0.0.1 nomosmart.local
```

Confirm that the public ports are available:

```bash
lsof -nP -iTCP:80 -sTCP:LISTEN
lsof -nP -iTCP:443 -sTCP:LISTEN
```

No output means the port is available. When a process is listed, stop that specific process and repeat the check.

### 7.4 Generate the local configuration, Secret, and TLS package

The following command creates `deploy/docker/nomosmart.env` and the local Secret and TLS files under `deploy/docker/generated/current/`. Git ignores these generated files, and only the file owner can read the sensitive files.

```bash
./deploy/package/nomosmart-package init \
  --target compose \
  --random-initial-credentials \
  --profile factory_acceptance \
  --app-env development \
  --public-host nomosmart.local \
  --no-display
```

Verify the package:

```bash
./deploy/package/nomosmart-package status --target compose
test -f deploy/docker/nomosmart.env
test -f deploy/docker/generated/current/manifest.json
test -f deploy/docker/generated/current/tls/active/edge-ca.crt
```

Each command must return status `0`. Production package creation uses `--profile production`, an approved public hostname, enterprise TLS input, and the required break-glass runbook and alerting evidence.

### 7.5 Run preflight and configuration checks

```bash
./deploy/package/nomosmart-package preflight --runtime compose
docker compose --env-file deploy/docker/nomosmart.env config --quiet
docker compose --env-file deploy/docker/nomosmart.env config --services
```

Preflight checks the hostname, ports 80 and 443, and the local runtime settings. The two Compose commands should finish without errors and print the service list.

### 7.6 Build and start the platform

For an initial Compose installation that will use the Keycloak Admin Console to configure LDAP or Windows AD, prepare a permanent identity administrator before starting the application:

1. In `deploy/docker/nomosmart.env`, set `KEYCLOAK_ADMIN_ALLOW_CIDR` to the administrator's actual source IP/CIDR as seen by the edge proxy. Keep access limited to the administration network.
2. Start the identity service and HTTPS edge:

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d postgresql keycloak
docker compose --env-file deploy/docker/nomosmart.env up -d --no-deps edge
docker compose --env-file deploy/docker/nomosmart.env ps postgresql keycloak edge
```

3. Trust `deploy/docker/generated/current/tls/active/edge-ca.crt` in the browser. Open `https://nomosmart.local/identity/admin/master/console/`. Use the initial Keycloak administrator `nomosmart` and the password in the protected file `deploy/docker/generated/current/keycloak_bootstrap_admin_password`.
4. In the `master` realm, create a separate named administrator, set its password securely, and assign the `admin` realm role. Confirm that this account can sign in from a separate browser session. Keep its credentials in the organization's credential vault.

Application bootstrap disables the initial Keycloak administrator after preparing the NomoSmart realm and service accounts. The separate administrator remains available for directory administration. The NomoSmart application administrator and the Keycloak administrator have different roles.

Start the complete platform:

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d --build
docker compose --env-file deploy/docker/nomosmart.env ps
```

This starts PostgreSQL, Redis, RustFS, OpenSearch, Neo4j, Keycloak, the Frontend, the Backend, the background workers, and the setup jobs. Services that keep running should show `running` or `healthy`. Migration and bootstrap jobs can show a successful completed state.

### 7.7 Verify HTTPS, health, and readiness

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

Expected edge and process-health responses:

```text
ready
{"status":"healthy"}
```

Readiness succeeds when the response contains `"status":"ready"` and healthy dependency entries. If readiness is still preparing, keep the generated configuration and inspect the first dependency that reports an incomplete state.

### 7.8 Complete first-use configuration

Import `deploy/docker/generated/current/tls/active/edge-ca.crt` into the workstation or browser trust store, then open:

```text
https://nomosmart.local
```

With the command above, the temporary first-use administrator is `nomosmart`; its random password is in the mode-0600 file `deploy/docker/generated/current/break_glass_initial_password`. Complete the required password change when performing first-use onboarding. Installation validation ends at successful health/readiness; the product/model steps below are separate functional acceptance.

In **System Management → Models**:

1. Create and test an active Embedding model.
2. Create and test an active Chat model.
3. Associate the Chat model with at least one active Embedding model.
4. Configure OCR and Judge models when the corresponding workflows are used.
5. Set the required default models.

Initialize the document-processing policy in Section 11.6 before the first import. For enterprise login, complete Sections 11.7–11.10. Then create a project, import a supported document, run extraction, submit and publish the version, and verify that a conversation returns source citations.

### 7.9 Operate and stop the deployment

```bash
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 backend
docker compose --env-file deploy/docker/nomosmart.env restart backend celery-worker celery-beat
docker compose --env-file deploy/docker/nomosmart.env down
```

`down` stops containers and removes the Compose network while retaining named volumes.

<a id="method-2-kubernetes-bundled"></a>

## 8. Method 2: Kubernetes `bundled`

For isolated Docker Desktop validation, follow the [local PV/ingress and staged Helm guide](deploy/local/README.md). The released-package procedure below remains specific to that published release.

The `bundled` profile installs NomoSmart and all supported services in one release. Before starting, the operator prepares the Kubernetes cluster, IngressClass, StorageClass, DNS, image registry access, TLS files, capacity, and directory service.

### 8.1 Define installation values

Define every value before using the package or installer:

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SECURE_ROOT="/secure/nomosmart"
export NOMOSMART_INSTALL_CONFIG="$NOMOSMART_SECURE_ROOT/install.toml"
export NOMOSMART_KUBE_CONTEXT="<approved-kube-context>"
export NOMOSMART_NAMESPACE="nomosmart"
export NOMOSMART_PUBLIC_URL="https://<public-host>"
```

Download the package from this repository's GitHub Release. Keep the extracted package unchanged and at the same absolute path until installation is complete.

### 8.2 Verify package integrity

```bash
"$NOMOSMART_RELEASE_DIR/deploy/release/nomosmart-release" verify-package \
  --package "$NOMOSMART_RELEASE_DIR" \
  --purpose installation-validation
```

Success returns exit code `0` and `status: verified`. The command checks file hashes, the complete file list, dependency references, and release metadata. Prepare an isolated installation environment and select the installation-validation purpose explicitly.

### 8.3 Verify tools and target identity

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

Copy the API server address and the `kube-system` Namespace UID into the installer TOML. Confirm that both values identify the intended cluster.

### 8.4 Prepare protected directories and TLS material

Create operator-owned directories with mode `0700`:

```bash
install -d -m 0700 "$NOMOSMART_SECURE_ROOT"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/package"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/installer-state"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/tls"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/inputs"
```

The bundled TLS directory contains the approved edge, PostgreSQL server and replication, Redis, RustFS, OpenSearch HTTP, and OpenSearch transport certificate sets. Private keys use mode `0600`. Certificate SANs must match the release, Namespace, and generated service names.

Obtain these certificates from the environment's certificate administrator and store them under `NOMOSMART_SECURE_ROOT/tls` using the exact filenames:

| Service | Files |
| --- | --- |
| Edge | `edge.crt`, `edge.key`, `edge-ca.crt` |
| PostgreSQL | `postgresql.crt`, `postgresql.key`, `postgresql-replication.crt`, `postgresql-replication.key`, `postgresql-ca.crt` |
| Redis | `redis.crt`, `redis.key`, `redis-ca.crt` |
| RustFS | `rustfs.crt`, `rustfs.key`, `rustfs-ca.crt` |
| OpenSearch | `opensearch.crt`, `opensearch.key`, `opensearch-transport.crt`, `opensearch-transport.key`, `opensearch-ca.crt` |

The PostgreSQL replication certificate needs CN `streaming_replica` and client-auth usage. Service certificates must cover the actual Kubernetes DNS names and be valid for the installation period. The production capacity settings require at least `7000m` allocatable CPU and `28Gi` allocatable memory per node; the installer also checks workload placement and capacity reserves.

Complete the directory preparation and field mapping in Sections 11.7–11.9 before approving the installation plan.

### 8.5 Initialize and complete the bundled configuration

```bash
cd "$NOMOSMART_RELEASE_DIR"
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --init-config
```

The command creates a new TOML file with mode `0600`. It does not overwrite an existing file and writes absolute paths to the verified chart and values files.

Edit the file and complete these groups:

| TOML group | Required values |
| --- | --- |
| Root and `release` | `api_version = "install.nomosmart.io/v1alpha2"`, package path, `purpose = "installation-validation"`, and explicit isolated-environment acknowledgement |
| `target` | Exact context, API server, cluster UID, Namespace, and Helm release |
| `application` | Public host, Ingress identity, StorageClass, secure directories, Secret names, onboarding CIDR, runbook URI, and alerting evidence |
| `images` | All nine images pinned as `repository:tag@sha256:<digest>` |
| `identity` | Directory mode, realm, provider, mapper, administrator, external group, local role, LDAPS fields, bind Secret, and CA Secret |

The extracted release initializes the package path and image references automatically. After confirming that `target` identifies an isolated environment, set `isolated_environment_acknowledged = true` in `[release]`:

```toml
[release]
package_dir = "/absolute/path/to/extracted-nomosmart-release"
purpose = "installation-validation"
isolated_environment_acknowledged = true
```

Replace the example path with `NOMOSMART_RELEASE_DIR`. Keep the application image references generated from the release. Confirm the protected file mode:

```bash
stat "$NOMOSMART_INSTALL_CONFIG"
```

### 8.6 Prepare the Namespace and operator inputs

Inspect the Namespace first:

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" get namespace "$NOMOSMART_NAMESPACE"
```

Create it when it is absent:

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" create namespace "$NOMOSMART_NAMESPACE"
```

For `freeipa`, `ldap`, or `active-directory` identity mode, create the bind-password and directory-CA Secrets from protected files:

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-directory-bind \
  --from-file=bind-password="$NOMOSMART_SECURE_ROOT/inputs/directory-bind-password"
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-directory-ca \
  --from-file=ca.crt="$NOMOSMART_SECURE_ROOT/inputs/directory-ca.crt"
```

When images use a private registry, create the referenced pull Secret:

```bash
kubectl --context "$NOMOSMART_KUBE_CONTEXT" \
  --namespace "$NOMOSMART_NAMESPACE" create secret generic nomosmart-registry \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="$NOMOSMART_SECURE_ROOT/inputs/registry-config.json"
```

Use `identity.mode = "preconfigured"` for an existing Keycloak provider and mapper. In that mode, the directory bind and CA inputs follow the external identity operator's established contract.

### 8.7 Run and approve the read-only plan

```bash
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --plan-only
```

Check the target cluster, Namespace ownership, at least three Ready schedulable nodes, capacity, IngressClass, StorageClass, DNS, HTTPS access, TLS and Secret fingerprints, chart, and digest-pinned images. Save and approve the displayed `config_digest`.

Correct any reported prerequisite, preserve the same package and configuration, and run the plan again. Planning performs no installation mutation.

### 8.8 Install, resume, and complete the identity checkpoint

After the digest is approved:

```bash
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG"
```

The wrapper checks the current state, starts a new installation or continues the existing one, acquires the installer Lease, runs all ten stages, and finishes by checking the result.

When the installer reports `action-required`, open `$NOMOSMART_PUBLIC_URL/login` and complete the designated federated administrator and break-glass first login, required password updates, directory synchronization, and `system-admin` mapping check. Run the same command again to resume from the saved checkpoint.

For an approved non-interactive execution, bind the run to the exact plan digest:

```bash
export NOMOSMART_CONFIG_DIGEST="replace-with-the-approved-config-digest"
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --confirm-digest "$NOMOSMART_CONFIG_DIGEST"
```

### 8.9 Verify the installed release

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

The verification command checks HTTPS, the Frontend, Backend readiness, OIDC, directory mapping, Kubernetes workloads, jobs, storage, mounted Secrets, database migration, platform setup, Worker, and Beat.

Complete the model-service and project validation described in Section 7.8.

<a id="method-3-kubernetes-external-services"></a>

## 9. Method 3: Kubernetes `external-services`

For isolated Docker Desktop validation, follow the [local PV/ingress and staged Helm guide](deploy/local/README.md). The released-package procedure below remains specific to that published release.

The `external-services` profile installs only the NomoSmart application and setup jobs. PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak must already be available and remain managed by their existing operators.

### 9.1 Define and verify installation inputs

Define the same protected values with paths for this installation:

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SECURE_ROOT="/secure/nomosmart"
export NOMOSMART_INSTALL_CONFIG="$NOMOSMART_SECURE_ROOT/install.toml"
export NOMOSMART_KUBE_CONTEXT="<approved-kube-context>"
export NOMOSMART_NAMESPACE="nomosmart"
export NOMOSMART_PUBLIC_URL="https://<public-host>"
```

Verify the package and tools:

```bash
"$NOMOSMART_RELEASE_DIR/deploy/release/nomosmart-release" verify-package \
  --package "$NOMOSMART_RELEASE_DIR" \
  --purpose installation-validation
kubectl version --client
helm version
python3 --version
openssl version
```

All commands must succeed before preparing the target.

### 9.2 Prepare external service contracts

Prepare TLS-enabled services that the Kubernetes cluster can reach. Give NomoSmart only the permissions it needs, and assign owners for backup, restore, availability, and lifecycle management.

| Service | Required connection contract |
| --- | --- |
| PostgreSQL | SQLAlchemy URL, migration identity, Flyway JDBC URL, and CA Secret |
| Redis | TLS URL, Sentinel settings when used, Celery broker/result URLs, and CA Secret |
| S3-compatible storage | HTTPS endpoint, region, bucket, access key, secret key, and CA Secret |
| OpenSearch | HTTPS endpoint, service credential, index prefix, and CA Secret |
| Neo4j | Explicit transport URI, database, service credential; optional custom CA Secret for TLS |
| Keycloak | HTTPS issuer, discovery, JWKS, admin API, Backend/Frontend clients, sync client, realm, and CA trust |

Verify each endpoint from the installation environment with the approved client and CA before running the installer.

### 9.3 Prepare protected directories

```bash
install -d -m 0700 "$NOMOSMART_SECURE_ROOT"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/package"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/installer-state"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/tls"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/inputs"
install -d -m 0700 "$NOMOSMART_SECURE_ROOT/runtime"
```

Place only `edge.crt`, `edge.key`, and `edge-ca.crt` in the external-profile TLS directory. External service CA certificates are supplied through Kubernetes Secrets.

### 9.4 Initialize and complete the external-services configuration

```bash
cd "$NOMOSMART_RELEASE_DIR"
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --init-config
```

Edit the generated TOML:

- Keep `api_version = "install.nomosmart.io/v1alpha2"` and the generated `release` values. After confirming the isolated target, set `release.isolated_environment_acknowledged = true` as in Section 8.5.
- Keep `deployment_profile = "external-services"`.
- Keep `application.runtime_secret_mode = "existing"`.
- Replace target identity, public host, Ingress, StorageClass, Secret names, and identity values. Keep the image references generated from the release.
- Update the external-services Helm values overlay with the real service endpoints and CA Secret names.
- Keep Secret values in protected files and Kubernetes Secrets.

Create an editable overlay outside the extracted package:

```bash
cp "$NOMOSMART_RELEASE_DIR/deploy/helm/nomosmart/values-external-services.example.yaml" \
  "$NOMOSMART_SECURE_ROOT/inputs/values-external-services.yaml"
chmod 0600 "$NOMOSMART_SECURE_ROOT/inputs/values-external-services.yaml"
```

In the TOML `application.values` array, keep the generated absolute path to `values-prod.yaml` first and replace the second path with the absolute path to this copy. Edit endpoints and Secret names in the copy. Keep all files inside `NOMOSMART_RELEASE_DIR` unchanged so package verification continues to succeed.

### 9.5 Create the Namespace, runtime Secret, and CA Secrets

Create the Namespace when it is absent, then create `nomosmart-runtime-secrets` from mode-`0600` files. The required fresh-install keys are:

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

Create the Secret without placing values in shell arguments:

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

If the Namespace already exists, inspect its ownership and run only the Secret commands. Create the external PostgreSQL, Redis, S3, OpenSearch, and Neo4j CA Secrets named by the values overlay:

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

Create the registry and directory inputs from Section 8.6 when those references are configured.

For private HTTPS Keycloak, configure `keycloak.external.caSecretName/caKey` with a CA bundle containing all required roots. Check discovery at the actual external issuer, without assuming /identity on the application host. CA files use read-only subPath mounts; recreate Pods after rotation. Use server-side apply for large bundles to avoid annotation limits. The external-services application chart owns no PVCs: select `storage_mode = "external"`, `storage_class = ""` and omit the PV manifest.

### 9.6 Run and approve the read-only plan

```bash
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --plan-only
```

The plan checks the target cluster, package, selected profile, service connections, TLS trust, existing runtime and CA Secrets, image digests, capacity, and rendered Helm resources. Save and approve the displayed `config_digest`.

### 9.7 Install, resume, and verify

```bash
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG"
```

Complete the protected identity checkpoint at `$NOMOSMART_PUBLIC_URL/login` when requested, then run the same command to resume.

Verify the result:

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

A complete verification confirms the NomoSmart workloads, migration and bootstrap jobs, OIDC, and connectivity to all configured external services. Complete the model-service and project validation described in Section 7.8.

<a id="method-4-source-development"></a>

## 10. Method 4: Source Development

Source development runs the Frontend, Backend, Worker, and Beat directly on a developer workstation. These processes connect to PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak services that are already running.

### 10.1 Install source dependencies

```bash
git clone --branch v0.1.1 --depth 1 https://github.com/crispkid/Nomosmart.git
cd Nomosmart/backend
uv sync --locked --all-extras
cd ../frontend
npm ci
cd ..
```

Python must report 3.12. `uv sync --locked` uses `backend/uv.lock` without changing the lockfile, and `npm ci` uses `frontend/package-lock.json`.

### 10.2 Prepare live dependencies

Prepare reachable PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak services. Gather their endpoints, credentials, CA paths, database names, bucket, search index prefix, OIDC issuer, client IDs, and audience.

The Backend readiness check validates these dependencies; development uses the same connection boundaries as deployment.

### 10.3 Create local configuration

```bash
cp -i backend/.env.example backend/.env
cp -i frontend/.env.example frontend/.env.local
```

Replace every placeholder in `backend/.env` and `frontend/.env.local`. Keep both files outside version control. At minimum, configure database, Redis/Celery, S3, OpenSearch, Neo4j, OIDC, Keycloak synchronization, encryption key, Frontend origin, Backend proxy, and OIDC client values.



Python commands use `uv run --env-file .env` so SSL_CERT_FILE also reaches the real process environment. Replace all placeholders, match certificate SANs to actual endpoints, and retain PostgreSQL verify-full, Redis rediss, and verified S3/OpenSearch/Neo4j TLS. The source template includes factory_acceptance setup, random initial credentials and the migration contract. Set DEPLOYMENT_KEYCLOAK_MODE=verify for operator-preconfigured Keycloak; otherwise provide separate bootstrap administrator credentials. For private Node CA trust, set `export NODE_EXTRA_CA_CERTS="/absolute/path/to/identity-ca-bundle.crt"` before startup; placing it only in .env.local does not initialize Node TLS trust. [Node.js documentation](https://nodejs.org/api/cli.html#node_extra_ca_certsfile).

When using Kubernetes port-forward to live local dependencies, restart a disconnected tunnel. If connection resets repeatedly end port-forward, use a real TCP passthrough proxy in the dedicated test namespace before forwarding. Keep host settings and TLS verification intact. Use the tested [TCP tunnel example](deploy/local/source-tunnel.example.json): replace the dedicated dependency namespace and six actual Service/Redis primary Pod IPs, apply the ConfigMap/Deployment, then forward deployment/source-tcp-gateway on loopback ports 15432, 16379, 19000, 19200, 17687 and 18443. Configure the native endpoints to use those ports and certificates whose SANs cover the loopback connection names, plus host.docker.internal when Flyway runs in Docker. This proxy passes TCP to the original services without terminating or skipping TLS.

### 10.4 Apply database migrations

From the Repository root, set the database hostname reachable from the Flyway container, migration account, and trusted PostgreSQL CA. The database and account must already exist, and the account must have permission to create the application's schema objects. Enter the password at the hidden prompt:

```bash
export FLYWAY_URL="jdbc:postgresql://<database-host-reachable-from-container>:5432/nomosmart?sslmode=verify-full&sslrootcert=/run/nomosmart/postgresql-ca.crt"
export FLYWAY_USER="<migration-user>"
export NOMOSMART_POSTGRES_CA="/absolute/path/to/postgresql-ca.crt"
export FLYWAY_PASSWORD="$(python3 -c 'import getpass; print(getpass.getpass("Database migration password: "))')"
export NOMOSMART_FLYWAY_IMAGE="$(python3 -c 'import json; print(json.load(open("deploy/release/external-dependencies.lock.json"))["images"]["migration"]["reference"])')"
docker run --rm \
  -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD \
  -e FLYWAY_BASELINE_ON_MIGRATE=false -e FLYWAY_CONNECT_RETRIES=10 \
  -v "$PWD/sql/migrations:/flyway/sql:ro" \
  -v "$NOMOSMART_POSTGRES_CA:/run/nomosmart/postgresql-ca.crt:ro" \
  "$NOMOSMART_FLYWAY_IMAGE" migrate
unset FLYWAY_PASSWORD
```

A new empty database executes `B051__nomosmart_0_1_0.sql` once. A database with existing Flyway history continues through the original `V001`–`V051` files; their checksums remain unchanged. Keep the entire migration directory. Success ends with Flyway's successful migration summary and exit code `0`; a repeat run reports that the schema is current.

Set these values in `backend/.env` before starting Backend, Worker, or Beat. They come from [release-contract.json](deploy/migrations/release-contract.json); Compose and the Kubernetes installer generate them automatically:

```dotenv
MIGRATION_REQUIRED_VERSION=051
MIGRATION_REQUIRED_CHECKSUM=1782483375
MIGRATION_BASELINE_CHECKSUM=1904638595
```

### 10.5 Run deployment bootstrap

```bash
cd backend
uv run --locked --all-extras --env-file .env python -m app.deployment.bootstrap --mode ensure --wait-seconds 180
cd ..
```

Bootstrap checks or creates the required S3 bucket, OpenSearch resources, Neo4j constraints, Keycloak realm and clients, and the platform setup state.

### 10.6 Start the application processes

Run each command in a separate terminal.

Backend:

```bash
cd backend
uv run --locked --all-extras --env-file .env uvicorn main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
cd backend
uv run --locked --all-extras --env-file .env celery -A app.worker:celery_app worker --concurrency 2 --loglevel INFO
```

Beat:

```bash
cd backend
uv run --locked --all-extras --env-file .env celery -A app.worker:celery_app beat --loglevel INFO
```

Frontend:

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1
```

### 10.7 Verify the development runtime

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/ready
curl --fail --silent --show-error http://127.0.0.1:3000/
curl --fail --silent --show-error http://127.0.0.1:3000/api/backend/ready
```

Expected Backend process health is `{"status":"healthy"}`. Readiness must report `"status":"ready"`. Frontend and its `/api/backend/ready` proxy must also respond successfully. Check Worker with `uv run --locked --all-extras --env-file .env celery -A app.worker:celery_app inspect ping` from backend/. Product login/model/project acceptance is separate from these installation checks. Stop all four terminals after each disposable validation round.

## 11. Configuration Reference

### 11.1 Configuration locations and precedence

| Runtime | Non-secret configuration | Secret source | Precedence |
| --- | --- | --- | --- |
| Backend development | `backend/.env` copied from `backend/.env.example` | Environment or allowlisted `<SETTING>_FILE` | Programmatic values → Environment → `.env` → allowlisted Secret file → framework file Secret |
| Frontend development | `frontend/.env.local` copied from `frontend/.env.example` | OIDC client Secret remains server-side | Next.js environment loading and server runtime values |
| Docker Compose | Generated `deploy/docker/nomosmart.env` | Owner-only files under `deploy/docker/generated/current/` mounted at `/run/secrets` | Explicit `--env-file` → Compose default → mounted Secret file |
| Kubernetes bundled | Installer TOML and ordered Helm values | Installer-managed or referenced Kubernetes Secrets | Later values files override earlier files; Secrets supply sensitive values |
| Kubernetes external | Installer TOML, production values, and external overlay | Existing runtime and CA Secrets | Later values files override earlier files; existing Secrets supply sensitive values |

Runtime settings are read when the process or Pod starts. Restart the affected Backend, Worker, Beat, or Frontend workload after changing runtime configuration. Apply migration and bootstrap changes through their job or command.

### 11.2 Core Backend settings

| Category | Setting | Requirement or default | Purpose |
| --- | --- | --- | --- |
| Application | `APP_ENV` | `development`; `development`, `test`, or `production` | Selects environment validation |
| Application | `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Backend bind address and port |
| Application | `DEPLOYMENT_BOOTSTRAP_RELEASE` | Required during platform setup | Identifies the release being prepared |
| Logging | `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json`; format is `json` or `text` | Controls runtime logging |
| Network | `CORS_ALLOWED_ORIGINS` | Local Frontend origins in development | Comma-separated browser origins |
| Network | `FRONTEND_APP_ORIGIN` | `http://127.0.0.1:3000` | Canonical Frontend origin |
| Database | `DATABASE_URL` | Required | SQLAlchemy PostgreSQL connection |
| Queue | `REDIS_URL` | Required | Application Redis connection |
| Queue | `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Required | Celery broker and result storage |
| Storage | `S3_ENDPOINT_URL` / `S3_REGION` / `S3_BUCKET` | Endpoint required; `us-east-1` / `nomosmart` | S3-compatible storage location |
| Storage | `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | Required Secret | Storage identity |
| Storage | `S3_USE_SSL` / `S3_VERIFY_TLS` / `S3_PATH_STYLE_ACCESS` | `false` / `false` / `true` in local defaults | S3 transport and addressing |
| Storage | `S3_CA_CERT_PATH` | Required for a private CA | S3 trust bundle |
| Search | `OPENSEARCH_URL` / `OPENSEARCH_INDEX_PREFIX` | URL required; `nomosmart-dev` | Search endpoint and index namespace |
| Search | `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | Required credential | Search identity |
| Search | `OPENSEARCH_VERIFY_TLS` / `OPENSEARCH_CA_CERT_PATH` | Verification required in production | OpenSearch trust |
| Graph | `NEO4J_URI` / `NEO4J_DATABASE` | `bolt://127.0.0.1:7687` / `neo4j` | Graph endpoint and database |
| Graph | `NEO4J_USERNAME` / `NEO4J_PASSWORD` | Required credential | Graph identity |
| Authentication | `OIDC_ISSUER_URL` / `OIDC_CLIENT_ID` / `OIDC_AUDIENCE` | Required | JWT issuer, Backend client, and audience |
| Authentication | `OIDC_DISCOVERY_URL` / `OIDC_JWKS_URL` | Derived when blank | Explicit OIDC metadata and key endpoints |
| Authentication | `OIDC_CLIENT_SECRET` | Required for confidential flow | Backend OIDC client Secret |
| Identity | `KEYCLOAK_ADMIN_API_URL` / `KEYCLOAK_ADMIN_INTERNAL_URL` | Public URL required | Identity administration endpoints |
| Identity | `KEYCLOAK_SYNC_CLIENT_ID` / `KEYCLOAK_SYNC_CLIENT_SECRET` | Required | Directory synchronization client |
| Identity | `IDENTITY_SYNC_SCHEDULE` / `IDENTITY_SYNC_TIMEZONE` | `0 2 * * *` / `Asia/Taipei` | Five-field synchronization schedule |
| Identity | `IDENTITY_SYNC_ENABLED` / `IDENTITY_SYNC_SCOPE` | `true` / `people_and_groups` | Scheduled sync and scope |
| Security | `APP_ENCRYPTION_KEY` | Required 64-character hexadecimal Secret | Encrypts protected application fields |
| Security | `BREAK_GLASS_USERNAME` / `BREAK_GLASS_RUNBOOK_URI` / `BREAK_GLASS_ALERTING_EVIDENCE` | Deployment-specific | Emergency account, runbook, and alert reference |
| Ingestion | `NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB` | `100`; range 1–10240 | Upload-size limit |
| Upload | `DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB` | File limit + 1 MiB when omitted; range 2–10241 | Maximum size of the complete multipart request |
| Upload | `NOMOSMART_UPLOAD_MAX_INFLIGHT` / `NOMOSMART_UPLOAD_IO_CHUNK_KIB` | `2` / `64` | Number of uploads handled at once and stream chunk size |
| Upload | `NOMOSMART_UPLOAD_METADATA_MAX_KIB` / `NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB` | `1024` / `16` | Multipart metadata and part-header limits |
| Upload | `NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS` / `NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS` | `60` / `600` | Idle and total upload time limits |
| Upload | `NOMOSMART_UPLOAD_SCRATCH_DIR` / `NOMOSMART_UPLOAD_SCRATCH_MAX_MIB` | `/tmp/nomosmart-upload` / `256` | Temporary upload directory and capacity |
| Ingestion | `TARGET_CHUNK_TOKENS` / `MAX_CHUNK_TOKENS` / `MIN_CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `500` / `700` / `80` / `60` | Structure-aware chunk sizing |
| Ingestion | `PANDOC_COMMAND` / `TESSERACT_COMMAND` / `TESSERACT_PDF_COMMAND` | `pandoc` / `tesseract` / `pdftoppm` | Document conversion and OCR executables |
| Remote sources | `HTTP_SOURCE_ALLOWED_HOSTS` / `HTTP_SOURCE_ALLOWED_CIDRS` | Empty allowlist | Approved HTTP/API destinations |
| Remote sources | `SFTP_KNOWN_HOSTS_PATH` | `/etc/nomosmart/ssh_known_hosts` | SFTP host-key trust file |
| Public API | `PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window |
| Public API | `PUBLIC_API_INVALID_AUTH_REQUESTS_PER_MINUTE` | `20` | Invalid-auth request limit |
| Public API | `PUBLIC_API_IDEMPOTENCY_TTL_HOURS` | `24` | Idempotency record lifetime |
| Public API | `PUBLIC_API_CONTENT_RETENTION_DAYS` / `PUBLIC_API_RECORD_RETENTION_DAYS` | `30` / `365` | Encrypted content and request-record retention |

The complete upload request limit must be at least 1 MiB larger than the single-file limit. The total timeout must not be shorter than the idle timeout, and the part-header limit must not exceed the metadata limit. Scratch capacity must cover every upload slot plus 16 MiB. Source development defaults to `/tmp/nomosmart-upload`; Compose and Helm use `/var/lib/nomosmart-upload/private`.

Production requires HTTPS public endpoints, verified S3 and OpenSearch TLS, real credentials instead of placeholders, a nonzero 64-character hexadecimal encryption key, and complete release and emergency-access information.

### 11.3 Frontend and edge settings

| Setting | Default or example | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_APP_ORIGIN` | `http://127.0.0.1:3000` | Browser-visible application origin |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/backend` | Browser Backend proxy path |
| `BACKEND_INTERNAL_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | Server-side Backend upstream |
| `NEXT_PUBLIC_OIDC_ISSUER_URL` | `http://127.0.0.1:8080/realms/nomosmart` | Browser OIDC issuer |
| `NEXT_PUBLIC_OIDC_CLIENT_ID` | `nomosmart-frontend` | OIDC public client |
| `NEXT_PUBLIC_OIDC_AUDIENCE` | `nomosmart-backend` | Expected access-token audience |
| `BACKEND_EDGE_UPSTREAM` | `http://backend:8000` in Compose | Internal Backend origin used by the edge proxy |
| `PUBLIC_API_READ_TIMEOUT_SECONDS` | `600`; range 1–3600 | Idle read timeout for the public JSON and SSE proxy |

### 11.4 Secret and document-processing settings

The Backend supports `<SETTING>_FILE` for the allowlisted sensitive settings: encryption key, database, Redis/Celery, S3 credentials, OpenSearch passwords, Neo4j passwords, OIDC client Secret, Keycloak sync Secret, bootstrap credentials, and break-glass value.

Secret files must be regular files. Production files outside `/run/secrets/` grant no group or other permissions. A conflicting direct environment value and file value stops production configuration loading.

For Neo4j, `bolt://` and `neo4j://` use an authenticated connection on an operator-controlled internal network. `bolt+s://` and `neo4j+s://` require certificate and hostname verification. Use the system trust store or set `NEO4J_CA_CERT_PATH`; the matching Helm setting is `neo4j.external.caSecretName`. A TLS connection never falls back to plaintext, and `+ssc` is not accepted.

DOCX files are processed by the existing Worker through Pandoc with its built-in `--sandbox`. `PANDOC_COMMAND` must contain one executable name without extra arguments. Timeout, memory, and cache limits remain configurable. `PANDOC_SANDBOX_COMMAND` is ignored. External resources referenced by a DOCX file are rejected, while normal HTTP, HTTPS, and email links remain text links and are not downloaded.

### 11.5 Local configuration example

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

The complete variable inventories are maintained in [backend/.env.example](backend/.env.example), [frontend/.env.example](frontend/.env.example), and [deploy/docker/nomosmart.env.example](deploy/docker/nomosmart.env.example).

### 11.6 Initialize the document-processing policy

Complete database migration, platform bootstrap, the administrator's first login, and role synchronization before this step. The maintenance command requires a current OIDC access token belonging to an enabled NomoSmart user with **System Management: View and Edit** permission. Run it before the first document import.

1. Generate one deployment UUID and record it with the protected installation configuration. Reuse this UUID when repeating initialization; generate a new UUID only for a separate installation.

```bash
export NOMOSMART_DEPLOYMENT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
printf '%s\n' "$NOMOSMART_DEPLOYMENT_ID"
```

2. Sign in to NomoSmart as the authorized administrator. In the browser's developer tools, inspect a successful authenticated request to `/api/backend/`. Copy the value of its `Authorization: Bearer …` header without the `Bearer ` prefix. Use the access token, not an ID token or Integration API key. Keep it private and enter it only at the hidden prompt below; obtain a fresh token if it expires.
3. Run the pair of commands for the selected installation method. The first initializes missing settings; the second reads the stored policy.

**Docker Compose**, from the source checkout root:

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

The Compose wrapper applies the same protected Secret paths and non-root identity as the Backend process.

**Kubernetes**: replace the Deployment placeholder with the name printed by the first command, for example `nomosmart-backend`.

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

**Source development**, with `backend/.env` prepared:

```bash
cd backend
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  uv run python -m app.deployment.file_processing_policy initialize \
  --expected-revision 0 --deployment-id "$NOMOSMART_DEPLOYMENT_ID"
python3 -c 'import getpass,json; print(json.dumps({"access_token":getpass.getpass("OIDC access token: ")}))' | \
  uv run python -m app.deployment.file_processing_policy read
cd ..
```

A new policy returns JSON containing `revision: 1`, `content_hash`, and `values`. The read command must return the same revision and hash. Repeating initialization with the same deployment UUID preserves existing settings; updates use the separate revision-checked maintenance operation. Keep the returned policy information with the installation configuration.

### 11.7 Prepare LDAP or Windows AD connectivity

Keycloak authenticates directory users. NomoSmart synchronizes those users and groups, then grants application permissions through local roles.

Prepare the following with the directory administrator:

| Item | Required value |
| --- | --- |
| Directory endpoint | `ldaps://<certificate-hostname>:636`, reachable from Keycloak and the installation environment |
| Certificate trust | The issuing CA chain in PEM format; the certificate SAN includes the directory hostname |
| Read-only bind account | Bind DN and password with permission to read the selected users, groups, attributes, and memberships |
| Search bases | Users DN and Groups DN that cover the intended accounts and groups |
| Identity attributes | Login attribute, stable UUID attribute, RDN, object classes, and group membership format |
| Application administrators | An existing directory user in the existing `nomosmart-admins` group, or the organization's chosen group |
| Identity administration | An authorized Keycloak administrator for manual setup; the Kubernetes installer uses its configured service account |

Verify DNS and TCP 636 access from the relevant networks. Check the CA and hostname from the installation environment:

```bash
export NOMOSMART_DIRECTORY_HOST="<directory-certificate-hostname>"
export NOMOSMART_DIRECTORY_CA="/absolute/path/to/directory-ca.crt"
openssl s_client -connect "$NOMOSMART_DIRECTORY_HOST:636" \
  -servername "$NOMOSMART_DIRECTORY_HOST" -CAfile "$NOMOSMART_DIRECTORY_CA" \
  -verify_hostname "$NOMOSMART_DIRECTORY_HOST" -verify_return_error </dev/null
```

The certificate verification must succeed. This checks that connection only; Keycloak must also trust the same CA and reach the endpoint.

For **Kubernetes bundled**, set the directory Secret names in `[identity]` and create them as shown in Section 8.6. The chart mounts the CA into Keycloak's truststore. For **external Keycloak**, its operator installs the CA and restarts the service as required. A Secret in NomoSmart's Namespace alone does not configure an independently managed Keycloak.

For **Docker Compose**, create the ignored `docker-compose.override.yml` in the source checkout. Replace the absolute path with the public CA file, mount it read-only, and recreate Keycloak:

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

Keep CA files readable by the Keycloak container user. Directory trust uses the [Keycloak truststore configuration](https://www.keycloak.org/server/keycloak-truststore); private CA keys stay with their owner.

### 11.8 Configure the directory provider

**Kubernetes installer**

Before the plan step in Method 2 or Method 3, edit only the `[identity]` section in the generated TOML. Keep the generated release, chart, and image references. The following example uses OpenLDAP with DN-based group membership; replace hostnames, DNs, and account names with the directory's actual values:

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

For Windows AD, use the same fields and replace the directory-specific values:

| Setting | Windows AD example |
| --- | --- |
| `mode` | `"active-directory"` |
| `server_url` | `"ldaps://dc01.example.com:636"` |
| `users_dn` / `groups_dn` | `"OU=Users,DC=example,DC=com"` / `"OU=Groups,DC=example,DC=com"` |
| `bind_dn` | The service account's actual distinguished name |
| `username_attribute` / `membership_user_attribute` | `"sAMAccountName"` / `"sAMAccountName"` |
| `rdn_attribute` / `uuid_attribute` | `"cn"` / `"objectGUID"` |
| `user_object_classes` | `["person", "organizationalPerson", "user"]` |
| `group_object_classes` | `["group"]` |
| `custom_user_filter` | `"(objectClass=user)"` |
| `user_search_scope` | `"subtree"` |

Choose search bases and filters that select the intended people. An existing `CN=Users` container and a custom `OU=Users` are different DNs. In either directory, the RDN and membership fields must match the actual schema; the examples are not substitutes for checking it.

The installer creates or verifies one LDAP provider and one group mapper in the selected realm. It uses read-only directory access, imports users, synchronizes groups under `/ldap`, and maps the designated administration group to the NomoSmart `system-admin` role. Directory objects remain managed by the directory administrator. With `mode = "preconfigured"`, an existing matching provider and mapper are required; the installer still performs synchronization and application-role reconciliation.

**Manual Keycloak setup, including Docker Compose**

1. Sign in to the Keycloak Admin Console using the permanent administrator prepared in Section 7.6, or the administrator supplied by the existing identity service.
2. Select the `nomosmart` realm. Bootstrap prepares the `nomosmart-frontend` public client, `nomosmart-backend` confidential client, and `nomosmart-sync` service account. Keep their configured redirect URLs, audience, and client Secrets aligned with NomoSmart.
3. Open **User federation → Add LDAP provider**. Use the generic LDAP vendor for OpenLDAP or **Active Directory** for AD. Set the connection URL, Users DN, Bind DN, bind password, login/RDN/UUID attributes, object classes, filter, and search scope from the values above.
4. Set **Edit mode = READ_ONLY**, **Import users = ON**, and **Sync registrations = OFF**. Enable pagination and CA-verified LDAPS. Test the connection and authentication, then save.
5. Under the provider's **Mappers**, create one **group-ldap-mapper**. Set LDAP Groups DN, group name attribute `cn`, group object classes, membership attribute `member`, membership type `DN`, and the appropriate membership-user attribute. Select read-only mode, group path `/ldap`, and the required group-inheritance behavior.
6. Synchronize LDAP groups into Keycloak, then synchronize all users. Confirm that the intended groups and users appear in this realm before continuing.

Keep `KEYCLOAK_LDAP_GROUP_PATH` aligned with the configured group path. Directory password changes are handled through the directory's approved password process. The [Keycloak LDAP administration guide](https://www.keycloak.org/docs/latest/server_admin/#_ldap) describes the provider controls.

### 11.9 Map user attributes and application roles

Review the provider's existing attribute mappers. Add or adjust only the attributes used by the organization:

| Directory attribute | Keycloak destination | NomoSmart use |
| --- | --- | --- |
| `givenName` | User property `firstName` | Given name |
| `sn` | User property `lastName` | Family name |
| `mail` | User property `email` | Email |
| LDAP `employeeNumber` or AD `employeeID` | User attribute `employee_id` | Optional unique employee identifier |
| `department` | User attribute `department` | Department |
| `title` | User attribute `title` | Job title |
| `manager` | User attribute `manager` | Manager's directory DN |

Use read-only LDAP attribute mappers. Confirm the actual source attribute names and employee-ID uniqueness before enabling these optional fields. The application also accepts `manager_employee_id` when the directory supplies that identifier.

In NomoSmart:

1. Open **User Management → Identity Sync** and run synchronization after the Keycloak import completes.
2. Confirm that the users and LDAP groups are visible and the synchronization completes.
3. Open **Roles and External Groups**, select the required local role, and configure its LDAP group mapping. For manual setup, map the administration group to `system-admin`. The installer performs this administration mapping for its designated group.
4. Map other directory groups to roles with the required menu and project permissions. A role/group mapping is one-to-one; users in several mapped groups receive the union of those roles' permissions.
5. Sign in again with the designated directory administrator and a regular directory user to check each account's assigned permissions.

### 11.10 Verify directory login and synchronization

Confirm all of the following:

- Keycloak reaches the LDAPS endpoint with valid CA and hostname checks.
- The selected provider imports the intended users, groups, and memberships.
- The designated directory administrator can sign in through NomoSmart's OIDC login.
- NomoSmart identity synchronization completes and the administration group maps to `system-admin`.
- A regular directory user can use the features granted by their mapped roles.
- First-use password actions are completed through the correct account or directory process.

Use a directory account for this verification; the local emergency account verifies a different login path.

| Symptom | Check |
| --- | --- |
| Keycloak Admin Console returns HTTP 403 | The edge or Ingress administration CIDR and the actual source IP seen by that proxy |
| LDAPS connection or certificate check fails | DNS, TCP 636, certificate SAN, CA chain, and the CA mounted in Keycloak |
| Bind authentication fails | Bind DN, protected bind password, account state, and directory read permissions |
| Users or groups are absent | Users DN, Groups DN, search scope, filters, object classes, and membership attributes |
| Login works but application access is missing | Completed identity sync, local user state, group membership, and local role mapping |
| Employee information is incomplete | LDAP attribute mappers and the directory's actual attribute values |

## 12. API and Usage

### 12.1 API locations and authentication

| Interface | Location | Authentication |
| --- | --- | --- |
| Internal API | `/api/v1` | OIDC access token with issuer, audience, signature, lifetime, and subject validation |
| Public Integration API | `/api/public/v1` | `Authorization: Bearer <api-key>` or `X-NomoSmart-API-Key` |
| OpenAPI document | `/openapi.json` | Backend origin |
| Swagger UI | `/docs` | Backend origin |
| Product API guide | `/api-docs` | Authenticated NomoSmart page |
| Process health | `/api/v1/health` | Returns `{"status":"healthy"}` |
| Dependency readiness | `/api/v1/ready` | Returns `ready` details or HTTP 503 |

The FastAPI application version is `0.1.1`; API paths retain `/v1`. Backend authorization combines local role permissions and project-scoped Owner, Editor, and Viewer governance.

### 12.2 Public chat example

Replace every placeholder with an active Integration API key, an allowed Project UUID, and the end-user identity.

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

A successful response contains `response_id`, `answer`, `citations`, `status`, selected document/version identifiers, and `request_id`. Streaming uses `POST /api/public/v1/projects/{project_id}/chat/stream`. Feedback uses `POST /api/public/v1/chat/responses/{response_id}/feedback`.

## 13. Development Commands

### 13.1 Frontend commands

```bash
cd frontend
npm ci
npm run dev -- --hostname 127.0.0.1
npm run lint
npm run build
```

### 13.2 Backend and deployment commands

```bash
cd backend
uv sync --locked --all-extras
cd ..
docker compose config --no-env-resolution --quiet
helm lint deploy/helm/nomosmart
```

## 14. Deployment and Operations

- **Docker Compose** uses [docker-compose.yml](docker-compose.yml), a generated environment file, protected Secret files, health checks, named volumes, and one local HTTPS entry point.
- **Kubernetes** uses the [Helm chart](deploy/helm/nomosmart), profile-specific values, ConfigMaps, Secrets, probes, Services, Ingress, NetworkPolicy, jobs, resource limits, and persistent storage.
- **Release package integrity** is checked with [deploy/release/nomosmart-release](deploy/release/nomosmart-release) before installation.
- **Database updates** use the forward-only files in [sql/migrations](sql/migrations). Compose and Helm apply them before the application becomes ready.
- **Platform setup** runs as a command or Kubernetes Job and prepares storage, search, graph, and identity services.

Section 19 links to the deployment and production operating guides.

## 15. Observability

- `GET /api/v1/health` shows whether the Backend process is running.
- `GET /api/v1/ready` shows whether required services and setup steps are ready.
- `LOG_FORMAT` and `LOG_LEVEL` control JSON or text logs and their detail level.
- `docker compose ps` and service logs show the state of a Compose deployment.
- Kubernetes workloads include readiness and liveness probes.
- Installer `status`, `verify`, and `doctor` commands hide sensitive values in their output.
- System Management shows service status and audit logs.

## 16. Security

- Browser and Internal API sessions use Keycloak OIDC Authorization Code with PKCE and signed JWTs.
- The Backend checks local role permissions and project roles for every protected operation.
- LDAP, Active Directory, FreeIPA, or an existing directory setup maps external groups to local roles.
- Sensitive settings are stored in owner-only files, Docker Secrets, or Kubernetes Secrets.
- Deployments use HTTPS, trusted CA certificates, digest-pinned images, and package integrity checks.
- Audit logs cover login, permissions, imports, reviews, publishing, models, and configuration changes.

## 17. Troubleshooting

### 17.1 Compose preflight reports a hostname or port issue

```bash
grep -n "nomosmart.local" /etc/hosts
lsof -nP -iTCP:80 -sTCP:LISTEN
lsof -nP -iTCP:443 -sTCP:LISTEN
./deploy/package/nomosmart-package preflight --runtime compose
```

Keep one `127.0.0.1 nomosmart.local` mapping and release ports 80 and 443. Repeat preflight after the host is ready.

### 17.2 A Compose service is still preparing

```bash
export NOMOSMART_DIAGNOSTIC_SERVICE="backend"
docker compose --env-file deploy/docker/nomosmart.env ps
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 "$NOMOSMART_DIAGNOSTIC_SERVICE"
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 migration deployment-bootstrap
```

Start with the first dependency or job that does not report its expected state. The generated configuration and named volumes remain available for a safe retry.

### 17.3 Health succeeds and readiness returns HTTP 503

```bash
curl --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/api/backend/ready
```

Read the `dependencies` object and inspect the corresponding PostgreSQL, Redis, S3/RustFS, OpenSearch, Neo4j, migration, or bootstrap service.

### 17.4 OIDC login redirects repeatedly

```bash
curl --fail --silent --show-error \
  --cacert deploy/docker/generated/current/tls/active/edge-ca.crt \
  https://nomosmart.local/identity/realms/nomosmart/.well-known/openid-configuration
```

Confirm browser trust, issuer URLs, client IDs, audience, hostname, and HTTPS origin against the same realm and public URL.

### 17.5 A Kubernetes installation pauses

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

Complete the reported prerequisite or identity checkpoint and rerun the same explicit-profile command. A changed configuration produces a new digest and returns to read-only plan approval.

### 17.6 A source Backend cannot connect to a dependency

```bash
cd backend
uv run python -c "from app.core.config import get_settings; print(get_settings().app_env)"
curl --silent --show-error http://127.0.0.1:8000/api/v1/ready
```

Check `backend/.env` endpoint, credential source, TLS mode, and CA path for the dependency named in readiness.

## 18. Installation Verification Checklist

Complete the following checks for the selected method:

- Frontend, Backend, Worker, and Beat are running.
- `/api/v1/health` reports `healthy`.
- `/api/v1/ready` reports `ready`.
- PostgreSQL, Redis, object storage, OpenSearch, Neo4j, and Keycloak are reachable through the configured connections.
- Flyway has completed `B051` on a new database, or the original upgrade chain through `V051` on an existing database, and bootstrap is complete.
- The document-processing policy has been initialized by an authorized administrator.
- HTTPS and OIDC login work through the configured public hostname.
- The first-use administrator password is updated and role mapping grants the intended access.
- Required model services pass their connection tests and the intended defaults are active.
- A project can import, process, review, publish, and query a supported document.
- Answers include source citations.

## 19. Documentation

- [Deployment guide](deploy/README.md)
- [Docker configuration example](deploy/docker/nomosmart.env.example)
- [Kubernetes installer examples](deploy/installer/nomosmart-install.example.toml)
- [External-services example](deploy/installer/nomosmart-install.external-services.example.toml)
- [Migration release contract](deploy/migrations/release-contract.json)

## 20. License

NomoSmart is licensed under the [Apache License 2.0](LICENSE).

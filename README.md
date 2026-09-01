# NomoSmart

English | [繁體中文](README.zh-TW.md)

NomoSmart is an enterprise knowledge management platform for importing, governing, publishing, searching, and verifying organizational knowledge.

## 1. Overview

NomoSmart converts files and connected data sources into versioned knowledge. Content moves through parsing, OCR, Markdown normalization, structure-aware chunking, tagging, embedding, review, publication, search, graph exploration, and source-cited conversation workflows.

The platform serves knowledge owners, editors, reviewers, system administrators, integration developers, and business users. PostgreSQL is the authoritative application store. Redis and Celery coordinate background work. S3-compatible storage retains source and generated artifacts. OpenSearch provides keyword, vector, and hybrid retrieval. Neo4j stores graph relationships. Keycloak provides OIDC identity and directory integration.

## 2. Key Features

- **Multi-source knowledge ingestion** — Imports PDF, DOCX, TXT, and Markdown files and connects to FTP, FTPS, SFTP, S3, and HTTP API sources.
- **Document processing** — Parses documents, performs OCR when configured, produces canonical Markdown, creates structure-aware chunks, assigns tags, and builds embeddings.
- **Versioned knowledge management** — Maintains source files, document versions, rendered content, chunks, tags, references, and active publication state.
- **Governed review and publication** — Routes knowledge through staged review, records immutable approval evidence, and publishes approved versions.
- **Search and source-cited answers** — Supports keyword, vector, and hybrid retrieval with document, version, and chunk citations.
- **Knowledge graph** — Presents project, document, chunk, and tag relationships through scoped graph views and APIs.
- **Quality verification** — Supports individual answer feedback, CSV validation runs, retry history, and result export.
- **Administration and integration** — Manages projects, users, local roles, permission matrices, directory mappings, model services, system prompts, integration clients, reports, and audit records.
- **Bilingual interface** — Provides Traditional Chinese and English user interfaces.

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

Migration and deployment-bootstrap jobs initialize the database schema and required runtime records before the application becomes ready. The readiness endpoint checks PostgreSQL, Redis, object storage, OpenSearch, Neo4j, migration state, and bootstrap evidence.

## 4. Technology Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | Next.js 16.2.12, React 19.2.3, TypeScript 5 | Web application, OIDC flow, and Backend proxy |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic | REST API, configuration, domain logic, and persistence |
| Background processing | Celery 5.5+, Redis 7.4 | Ingestion, synchronization, validation, and scheduled work |
| Database | PostgreSQL 18.4, Flyway 13.0.0 | Authoritative state and forward-only migrations |
| Object storage | S3-compatible storage; RustFS in bundled deployments | Source documents and generated artifacts |
| Search | OpenSearch 2.19 | Keyword, vector, hybrid, and staging indexes |
| Graph | Neo4j 5.26 Community | Knowledge relationships and traversal |
| Identity | Keycloak 26.0.8, OIDC, LDAP/AD federation | Authentication, directory synchronization, and role mapping |
| Deployment | Docker Compose v2, Helm chart 0.8.0 | Single-host and Kubernetes deployment |
| Verification | Pytest, Vitest, Playwright, Docker Compose, Helm | Application, integration, end-to-end, and deployment checks |

## 5. Project Structure

```text
Nomosmart/
├── frontend/                  Next.js application, UI components, i18n, and tests
├── backend/                   FastAPI API, workers, domain services, and tests
├── sql/migrations/            Flyway migrations V001 through V047
├── deploy/docker/             Docker Compose runtime configuration
├── deploy/helm/nomosmart/     Helm chart and environment values
├── deploy/installer/          Profile-aware Kubernetes installer
├── deploy/package/            Secret and TLS package lifecycle tool
├── deploy/release/            Signed release-package tooling
├── docs/                      Decisions, release baselines, and runbooks
└── docker-compose.yml         Single-host deployment model
```

## 6. Getting Started

### 6.1 Select an installation method

Choose one method and complete it from prerequisites through verification.

| Method | Environment | Installed components |
| --- | --- | --- |
| [Method 1: Docker Compose](#method-1-docker-compose) | Workstation or single host | NomoSmart, PostgreSQL, Redis, RustFS, OpenSearch, Neo4j, and Keycloak |
| [Method 2: Kubernetes bundled](#method-2-kubernetes-bundled) | Kubernetes with NomoSmart-managed dependencies | NomoSmart and supported peripheral services |
| [Method 3: Kubernetes external services](#method-3-kubernetes-external-services) | Kubernetes with operator-managed dependencies | NomoSmart application workloads and initialization jobs |
| [Method 4: Source development](#method-4-source-development) | Engineering workstation | Frontend, Backend, Worker, and Beat against configured services |

New Kubernetes installations use an explicit `bundled` or `external-services` profile. The Helm `auto` value remains available for existing deployment compatibility.

### 6.2 Prerequisites

Versions appear only where the Repository defines a baseline.

| Requirement | Version or baseline | Required for | Verification |
| --- | --- | --- | --- |
| Git | Repository-compatible version | Compose and source development | `git --version` |
| Docker Engine or Docker Desktop | Compose-capable installation | Docker Compose and local Flyway | `docker version` |
| Docker Compose | v2 | Docker Compose | `docker compose version` |
| Python | Python 3 for deployment tools; exactly 3.12 for Backend development | Package tool, installer, Backend | `python3 --version` |
| Node.js and npm | Node.js 24 container baseline | Frontend development | `node --version` and `npm --version` |
| uv | Lockfile-capable installation | Backend development | `uv --version` |
| kubectl | 1.28 or newer | Kubernetes methods | `kubectl version --client` |
| Helm | v3 or v4 | Kubernetes methods | `helm version` |
| OpenSSL | Available CLI | TLS package and Kubernetes installer | `openssl version` |
| GnuPG | Available CLI | Signed release verification | `gpg --version` |
| curl | HTTPS-capable installation | Runtime verification | `curl --version` |
| lsof and `/etc/hosts` access | Unix-like host utilities | Compose preflight | `lsof -v` |

Kubernetes production installation requires at least three Ready schedulable nodes, the capacity defined by the rendered production plan, an IngressClass, the approved Longhorn StorageClass, public DNS, trusted TLS material, registry access, and an enterprise directory or preconfigured Keycloak identity provider.

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

Docker Compose provides the complete single-host experience. It builds the application images, starts the bundled services, applies migrations, performs deployment bootstrap, and exposes one HTTPS origin.

### 7.1 Obtain the source

Clone the Repository and enter its root directory:

```bash
git clone https://github.com/crispkid/Nomosmart.git
cd Nomosmart
git status --short
```

For a controlled installation, select the approved full commit SHA:

```bash
git fetch --tags
git checkout --detach "<approved-git-commit>"
git rev-parse HEAD
```

The final SHA must match the approved revision.

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

The package command creates the ignored `deploy/docker/nomosmart.env` file and owner-only files under `deploy/docker/generated/current/`. The local factory profile provides a reproducible first-use environment.

```bash
./deploy/package/nomosmart-package init \
  --target compose \
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

Preflight confirms the host mapping, ports 80 and 443, and the local runtime boundary. Compose validation must complete without an error and list the application services.

### 7.6 Build and start the platform

```bash
docker compose --env-file deploy/docker/nomosmart.env up -d --build
docker compose --env-file deploy/docker/nomosmart.env ps
```

The deployment starts PostgreSQL, migration, RustFS, Redis, Neo4j, OpenSearch, Keycloak, deployment bootstrap, Backend, Worker, Beat, Frontend, and the HTTPS edge. Long-running services should report `running` or `healthy`. Migration and bootstrap services may report a successful completed state.

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

The factory profile creates the temporary first-use administrator `nomosmart` with password `nomosmart`. Sign in, complete the required password update, and sign in again.

In **System Management → Models**:

1. Create and test an active Embedding model.
2. Create and test an active Chat model.
3. Associate the Chat model with at least one active Embedding model.
4. Configure OCR and Judge models when the corresponding workflows are used.
5. Set the required default models.

Create a project, import a supported document, run extraction, submit and publish the version, then verify that a conversation returns source citations.

### 7.9 Operate and stop the deployment

```bash
docker compose --env-file deploy/docker/nomosmart.env logs --tail=200 backend
docker compose --env-file deploy/docker/nomosmart.env restart backend celery-worker celery-beat
docker compose --env-file deploy/docker/nomosmart.env down
```

`down` stops containers and removes the Compose network while retaining named volumes.

<a id="method-2-kubernetes-bundled"></a>

## 8. Method 2: Kubernetes `bundled`

The `bundled` profile installs NomoSmart, PostgreSQL, Redis, RustFS, OpenSearch, Neo4j, and Keycloak in one managed release. The platform operator supplies the cluster, IngressClass, StorageClass, DNS, registry access, TLS material, capacity, and directory service.

### 8.1 Define installation values

Define every value before using the package or installer:

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SIGNER_FINGERPRINT="<trusted-40-to-64-character-openpgp-fingerprint>"
export NOMOSMART_SECURE_ROOT="/secure/nomosmart"
export NOMOSMART_INSTALL_CONFIG="$NOMOSMART_SECURE_ROOT/install.toml"
export NOMOSMART_KUBE_CONTEXT="<approved-kube-context>"
export NOMOSMART_NAMESPACE="nomosmart"
export NOMOSMART_PUBLIC_URL="https://<public-host>"
```

Obtain the signer fingerprint through an independent trusted channel. Keep the extracted release package immutable at the same absolute path throughout installation and resume operations.

### 8.2 Verify the signed release package

```bash
"$NOMOSMART_RELEASE_DIR/deploy/release/nomosmart-release" verify-package \
  --package "$NOMOSMART_RELEASE_DIR" \
  --trusted-fingerprint "$NOMOSMART_SIGNER_FINGERPRINT"
```

A successful verification exits with status `0` and confirms the signed closed inventory before the installer contacts Kubernetes.

### 8.3 Verify tools and target identity

```bash
kubectl version --client
helm version
python3 --version
openssl version
gpg --version
kubectl --context "$NOMOSMART_KUBE_CONTEXT" config view --minify \
  -o jsonpath='{.clusters[0].cluster.server}'
kubectl --context "$NOMOSMART_KUBE_CONTEXT" get namespace kube-system \
  -o jsonpath='{.metadata.uid}'
```

Record the API server and `kube-system` Namespace UID. They must match the approved target inventory and the installer TOML.

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

### 8.5 Initialize and complete the bundled configuration

```bash
cd "$NOMOSMART_RELEASE_DIR"
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --init-config
```

The command creates a new mode-`0600` TOML, preserves existing paths, and pins chart and values paths to the verified package.

Edit the file and complete these groups:

| TOML group | Required values |
| --- | --- |
| Root and `release` | `api_version = "install.nomosmart.io/v1alpha2"`, immutable package path, and independently obtained signer fingerprint |
| `target` | Exact context, API server, cluster UID, Namespace, and Helm release |
| `application` | Public host, Ingress identity, StorageClass, secure directories, Secret names, onboarding CIDR, runbook URI, and alerting evidence |
| `images` | All nine images pinned as `repository:tag@sha256:<digest>` |
| `identity` | Directory mode, realm, provider, mapper, administrator, external group, local role, LDAPS fields, bind Secret, and CA Secret |

Confirm the protected file mode:

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

Review the target identity, Namespace ownership, at least three Ready schedulable nodes, capacity, IngressClass, StorageClass, DNS and HTTPS reachability, TLS fingerprints, input Secret fingerprints, chart identity, and digest-pinned image inventory. Record and approve the displayed `config_digest`.

Correct any reported prerequisite, preserve the same package and configuration, and run the plan again. Planning performs no installation mutation.

### 8.8 Install, resume, and complete the identity checkpoint

After the digest is approved:

```bash
./deploy/installer/nomosmart-one-click \
  --profile bundled \
  --config "$NOMOSMART_INSTALL_CONFIG"
```

The wrapper selects install or resume from current state, acquires the installer Lease, completes the ten recorded stages, and finishes with status and verification.

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

Verification covers HTTPS, Frontend, Backend readiness, OIDC discovery and JWKS, identity evidence, directory mapping, workloads, jobs, PDBs, PVCs, Secret mounts, migration, bootstrap, Worker, and Beat.

Complete the model-service and project validation described in Section 7.8.

<a id="method-3-kubernetes-external-services"></a>

## 9. Method 3: Kubernetes `external-services`

The `external-services` profile installs the NomoSmart Frontend, Backend, Worker, Beat, migration, bootstrap, and finalization jobs. PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak remain under their enterprise service operators.

### 9.1 Define and verify installation inputs

Define the same protected values with paths for this installation:

```bash
export NOMOSMART_RELEASE_DIR="/absolute/path/to/extracted-nomosmart-release"
export NOMOSMART_SIGNER_FINGERPRINT="<trusted-40-to-64-character-openpgp-fingerprint>"
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
  --trusted-fingerprint "$NOMOSMART_SIGNER_FINGERPRINT"
kubectl version --client
helm version
python3 --version
openssl version
gpg --version
```

All commands must succeed before preparing the target.

### 9.2 Prepare external service contracts

Provide reachable TLS-enabled services with least-privilege NomoSmart identities and assigned backup, restore, availability, and lifecycle owners.

| Service | Required connection contract |
| --- | --- |
| PostgreSQL | SQLAlchemy URL, migration identity, Flyway JDBC URL, and CA Secret |
| Redis | TLS URL, Sentinel settings when used, Celery broker/result URLs, and CA Secret |
| S3-compatible storage | HTTPS endpoint, region, bucket, access key, secret key, and CA Secret |
| OpenSearch | HTTPS endpoint, service credential, index prefix, and CA Secret |
| Neo4j | TLS URI, database, service credential, and CA Secret |
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

- Set `api_version = "install.nomosmart.io/v1alpha2"` and complete the `release` identity.
- Keep `deployment_profile = "external-services"`.
- Keep `application.runtime_secret_mode = "existing"`.
- Replace target identity, public host, Ingress, StorageClass, image digests, Secret names, and identity values.
- Update the external-services Helm values overlay with the real service endpoints and CA Secret names.
- Keep Secret values in protected files and Kubernetes Secrets.

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

### 9.6 Run and approve the read-only plan

```bash
./deploy/installer/nomosmart-one-click \
  --profile external-services \
  --config "$NOMOSMART_INSTALL_CONFIG" \
  --plan-only
```

The plan validates target identity, package identity, profile consistency, endpoint reachability, TLS trust, existing runtime and CA Secrets, image digests, capacity, and application-only Helm rendering. Record and approve the `config_digest`.

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

Source development runs Frontend, Backend, Worker, and Beat directly from the Repository. It connects to configured live PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak services.

### 10.1 Install source dependencies

```bash
git clone https://github.com/crispkid/Nomosmart.git
cd Nomosmart/backend
uv sync --locked --all-extras
cd ../frontend
npm ci
cd ..
```

Python must report 3.12. `uv sync --locked` uses `backend/uv.lock` without changing the lockfile, and `npm ci` uses `frontend/package-lock.json`.

### 10.2 Prepare live dependencies

Provide reachable services for PostgreSQL, Redis, S3-compatible storage, OpenSearch, Neo4j, and Keycloak. Record their endpoints, credentials, CA paths, database names, bucket, search index prefix, OIDC issuer, client IDs, and audience.

The Backend readiness check validates these dependencies; development uses the same connection boundaries as deployment.

### 10.3 Create local configuration

```bash
cp -i backend/.env.example backend/.env
cp -i frontend/.env.example frontend/.env.local
```

Replace every placeholder in `backend/.env` and `frontend/.env.local`. Keep both files outside version control. At minimum, configure database, Redis/Celery, S3, OpenSearch, Neo4j, OIDC, Keycloak synchronization, encryption key, Frontend origin, Backend proxy, and OIDC client values.

### 10.4 Apply database migrations

From the Repository root:

```bash
export FLYWAY_URL="jdbc:postgresql://127.0.0.1:5432/nomosmart"
export FLYWAY_USER="<migration-user>"
export FLYWAY_PASSWORD="<migration-password>"
docker run --rm \
  -v "$PWD/sql/migrations:/flyway/sql:ro" \
  flyway/flyway:13.0.0 \
  -url="$FLYWAY_URL" \
  -user="$FLYWAY_USER" \
  -password="$FLYWAY_PASSWORD" \
  migrate
```

Flyway applies `V001` through `V047` and records the checksums in the target database. Confirm the command exits with status `0`.

### 10.5 Run deployment bootstrap

```bash
cd backend
uv run python -m app.deployment.bootstrap --mode ensure
cd ..
```

Bootstrap verifies or creates the required S3 bucket, OpenSearch resources, Neo4j constraints, Keycloak realm/client state, and durable deployment evidence according to the configured mode.

### 10.6 Start the application processes

Run each command in a separate terminal.

Backend:

```bash
cd backend
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
cd backend
uv run celery -A app.worker:celery_app worker --concurrency 2 --loglevel INFO
```

Beat:

```bash
cd backend
uv run celery -A app.worker:celery_app beat --loglevel INFO
```

Frontend:

```bash
cd frontend
npm run dev
```

### 10.7 Verify the development runtime

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/ready
curl --fail --silent --show-error http://127.0.0.1:3000/login
```

Expected Backend process health is `{"status":"healthy"}`. Readiness must report `"status":"ready"`. Open `http://127.0.0.1:3000`, complete OIDC login, and perform the model and project validation from Section 7.8.

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
| Application | `DEPLOYMENT_BOOTSTRAP_RELEASE` | Required for deployment evidence | Identifies the bootstrapped release |
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
| Security | `BREAK_GLASS_USERNAME` / `BREAK_GLASS_RUNBOOK_URI` / `BREAK_GLASS_ALERTING_EVIDENCE` | Deployment-specific | Emergency-access identity and evidence |
| Ingestion | `NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB` | `100`; range 1–10240 | Upload-size limit |
| Ingestion | `TARGET_CHUNK_TOKENS` / `MAX_CHUNK_TOKENS` / `MIN_CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `500` / `700` / `80` / `60` | Structure-aware chunk sizing |
| Ingestion | `PANDOC_COMMAND` / `TESSERACT_COMMAND` / `TESSERACT_PDF_COMMAND` | `pandoc` / `tesseract` / `pdftoppm` | Document conversion and OCR executables |
| Remote sources | `HTTP_SOURCE_ALLOWED_HOSTS` / `HTTP_SOURCE_ALLOWED_CIDRS` | Empty allowlist | Approved HTTP/API destinations |
| Remote sources | `SFTP_KNOWN_HOSTS_PATH` | `/etc/nomosmart/ssh_known_hosts` | SFTP host-key trust file |
| Public API | `PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window |
| Public API | `PUBLIC_API_INVALID_AUTH_REQUESTS_PER_MINUTE` | `20` | Invalid-auth request limit |
| Public API | `PUBLIC_API_IDEMPOTENCY_TTL_HOURS` | `24` | Idempotency record lifetime |
| Public API | `PUBLIC_API_CONTENT_RETENTION_DAYS` / `PUBLIC_API_RECORD_RETENTION_DAYS` | `30` / `365` | Encrypted content and request-record retention |

Production validation requires HTTPS public endpoints, verified S3 and OpenSearch TLS, non-placeholder credentials, a nonzero 64-character hexadecimal encryption key, and complete deployment evidence.

### 11.3 Frontend settings

| Setting | Default or example | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_APP_ORIGIN` | `http://127.0.0.1:3000` | Browser-visible application origin |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/backend` | Browser Backend proxy path |
| `BACKEND_INTERNAL_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | Server-side Backend upstream |
| `NEXT_PUBLIC_OIDC_ISSUER_URL` | `http://127.0.0.1:8080/realms/nomosmart` | Browser OIDC issuer |
| `NEXT_PUBLIC_OIDC_CLIENT_ID` | `nomosmart-frontend` | OIDC public client |
| `NEXT_PUBLIC_OIDC_AUDIENCE` | `nomosmart-backend` | Expected access-token audience |

### 11.4 Secret files

The Backend supports `<SETTING>_FILE` for the allowlisted sensitive settings: encryption key, database, Redis/Celery, S3 credentials, OpenSearch passwords, Neo4j passwords, OIDC client Secret, Keycloak sync Secret, bootstrap credentials, and break-glass value.

Secret files must be regular files. Production files outside `/run/secrets/` grant no group or other permissions. A conflicting direct environment value and file value stops production configuration loading.

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
```

The complete variable inventories are maintained in [backend/.env.example](backend/.env.example), [frontend/.env.example](frontend/.env.example), and [deploy/docker/nomosmart.env.example](deploy/docker/nomosmart.env.example).

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

The FastAPI application version is `1.0.0`. Backend authorization combines local role permissions and project-scoped Owner, Editor, and Viewer governance.

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

## 13. Development and Testing

### 13.1 Frontend commands

```bash
cd frontend
npm ci
npm run dev
npm run lint
npm run test
npm run test:coverage
npm run test:e2e
npm run build
```

### 13.2 Backend and repository commands

```bash
cd backend
uv sync --locked --all-extras
uv run pytest
cd ..
python3 -m unittest discover -s deploy/installer/tests -p 'test_*.py'
docker compose config --no-env-resolution --quiet
helm lint deploy/helm/nomosmart
```

Backend integration tests and browser E2E tests use configured live services. Frontend and Backend coverage are measured separately against the Repository's 80% release gate.

## 14. Deployment and Operations

- **Docker Compose** uses the root [docker-compose.yml](docker-compose.yml), generated non-secret environment file, mounted owner-only Secret files, health checks, named volumes, and one loopback HTTPS edge.
- **Kubernetes** uses the [Helm chart](deploy/helm/nomosmart), an explicit profile overlay, ConfigMaps, Secrets, probes, Services, Ingress, NetworkPolicy, jobs, resource requests/limits, and persistent storage.
- **Signed release packages** are verified with [deploy/release/nomosmart-release](deploy/release/nomosmart-release) before the Kubernetes installer contacts the target cluster.
- **Migrations** use the forward-only files in [sql/migrations](sql/migrations). Compose and Helm run migration before application readiness.
- **Bootstrap** uses a non-HTTP command or job to initialize storage, search, graph, identity, and durable release evidence.

Production capacity, release custody, backup, restore, and factory procedures are recorded in the deployment documents linked in Section 19.

## 15. Observability

- `GET /api/v1/health` reports Backend process health.
- `GET /api/v1/ready` reports dependency, migration, and bootstrap readiness.
- `LOG_FORMAT` and `LOG_LEVEL` provide structured JSON or text logs.
- Docker Compose health checks integrate with `docker compose ps` and per-service logs.
- Kubernetes workloads define readiness and liveness probes.
- The installer provides redacted `status`, `verify`, and `doctor` output.
- System Management presents operational status and audit records.

## 16. Security

- Browser and Internal API sessions use Keycloak OIDC Authorization Code with PKCE and signed JWT validation.
- Backend authorization enforces local role permissions and project-scoped governance.
- LDAP, Active Directory, FreeIPA, or preconfigured directory integration maps external groups to local roles.
- Sensitive runtime values use owner-only files, Docker Secrets, or Kubernetes Secrets.
- Production validation requires HTTPS, trusted CA verification, immutable image digests, and signed release identity.
- Audit records cover identity, permission, import, review, publication, model, configuration, and other governed operations.

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
- Flyway migrations `V001` through `V047` and deployment bootstrap are complete.
- HTTPS and OIDC login work through the configured public hostname.
- The first-use administrator password is updated and role mapping grants the intended access.
- Required model services pass their connection tests and the intended defaults are active.
- A project can import, process, review, publish, and query a supported document.
- Answers include source citations.

## 19. Documentation

- [Release readiness](deploy/RELEASE_READINESS.md)
- [Guided installer live test](docs/CHG-248-OPENLDAP-INSTALLER-LIVE-TEST.md)
- [Release and installer hardening](docs/CHG-249-SCRIPT-DRIVEN-RELEASE-AND-INSTALLER-HARDENING.md)
- [OpenSearch image and migration evidence](docs/CHG-251-OPENSEARCH-IMAGE-AND-MIGRATION-EVIDENCE.md)
- [Production HA factory runbook](docs/CHG-252-PRODUCTION-HA-FACTORY-RUNBOOK.md)
- [Release baseline](docs/CHG-252-RELEASE-BASELINE.md)
- [Supply-chain evidence](docs/CHG-252-SUPPLY-CHAIN-EVIDENCE.md)

## 20. License

NomoSmart is licensed under the [Apache License 2.0](LICENSE).

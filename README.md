CHG-419 current release quality: required critical normal, denial, error and data-preservation scenarios need qualified evidence. Complete frontend/backend coverage measurement remains required; 80% is an advisory improvement target. `coverage:check` reads an explicit source-bound review (`NOMOSMART_QUALITY_REVIEW`); `coverage:strict` preserves historical full-suite/80% checks. `release:readiness` reports actual unresolved risks and evidence. Explicit signed v5 uses `local-risk-reviewed-release` / `assemble-reviewed-local`; v4 and unverified schema5 test candidates retain their original meanings. This source change performs no package assembly, installation, production qualification, 8443 cutover or publication.

# NomoSmart

CHG-376 (2026-10-30): the system heading and browser title now follow the selected language on 8443, including one English reload. One Frontend build and offline scan passed with no High/Critical findings; only Frontend was replaced. Earlier title-gap observations below are retained as historical evidence. [Verified correction](docs/CHG-376-RESULT.md).

CHG-375 (2026-10-29): installer cleanup and the 8443 application update are complete; temporary 19443/19444 entries are retired. One real LDAP login and authenticated users/groups/identity reads passed. The 390px view has no page overflow. English navigation and content translate, while the system heading/browser title still use Chinese; this presentation gap is recorded and not fixed. [Scoped browser results](docs/CHG-375-8443-LDAP-UI-RESULT.md).

Current CHG-374: cleaned candidates are deployed on the existing LDAP environment using their qualified builds/scans. Normal LDAP sign-in passed; the English page-title gap remains open. Temporary OIDC sign-in remains unverified after Peter retired its test entry. [Original evidence and supplements](docs/CHG-374-RESULT.md).

認證契約 2（CHG-363）：[繁中操作指南](docs/AUTHENTICATION.zh-TW.md) · [English guide](docs/AUTHENTICATION.en.md) · [當次驗證及未完成項目](docs/AUTHENTICATION-STATUS.md)。目前未達正式發布門檻。

Historical CHG-370 snapshot (2026-10-28; current quality policy is CHG-419): real browser review/publish and a 31-minute active/idle session pair passed scoped verification. After Peter's approval, 12 original service-password families passed rotation and consumer checks; 3 were blocked before writes, and ordinary browser login remains pending. The original 13 running containers are healthy, with the same IDs/images/volumes and no database upgrade. Peter accepted the 3 source-bound FTP High findings through November 27. Complete suites, each 80% coverage gate, the remaining credential families and a signed release are still incomplete. See [rotation results](docs/CHG-370-ORIGINAL-ROTATION-RESULT.json), [test gaps](docs/CHG-370-REMAINING-TEST-GAPS.json) and [coverage status](docs/CHG-370-COVERAGE-PROGRESS.json). Earlier [CHG-369 results](docs/CHG-369-RESULT.md) retain their recorded scope.

Latest scoped verification (2026-10-27): real Windows Server 2025 AD over strict LDAPS passed sign-in, user/group sync, nested/primary groups, rename/move identity stability, disable/revocation and a 1501-member ranged group. The AD VM is retained; temporary apps, installation media and the failed-install snapshot are cleaned after Peter approved option A. [AD results and limits](docs/CHG-368-RESULT.md). Earlier [Helm results](docs/CHG-367-RESULT.md) remain scoped to a single-node topology; Compose/Helm were not rerun for AD.

English | [繁體中文](README.zh-TW.md)

NomoSmart helps organizations turn documents and connected data into managed, searchable knowledge.

## 1. Overview

NomoSmart reads files and connected data sources, runs OCR when needed, converts content to Markdown, and splits it into searchable sections. Teams can review and publish each version, search the content, explore relationships, and ask questions with source citations.

The platform is designed for knowledge owners, editors, reviewers, administrators, integration developers, and business users. PostgreSQL stores application data. Redis and Celery run background work. S3-compatible storage keeps source files and generated content. OpenSearch handles search, Neo4j stores graph relationships, and protocol-based authentication supports external OIDC or direct LDAP/Windows AD.


## 2. Key Features

- **Import from common sources** — Accepts PDF, UTF-8 TXT, and Markdown (.md/.markdown) files, and connects to FTP, FTPS, SFTP, S3, and HTTP APIs.
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
        v
Next.js Frontend -----------> FastAPI Backend
                                  |
                                  +--> External OIDC / LDAP / Windows AD
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
| Frontend | Next.js 16.4.1, React 19.2.3, TypeScript 5 | Web application, internal session and same-origin Backend proxy |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic | REST API, configuration, domain logic, and persistence |
| Background processing | Celery 5.5+, Redis 7.4 | Ingestion, synchronization, validation, and scheduled work |
| Database | PostgreSQL 18.4, Flyway 13.6 | Authoritative state and forward-only migrations |
| Object storage | S3-compatible storage; RustFS in bundled deployments | Source documents and generated artifacts |
| Search | OpenSearch 2.19 | Keyword, vector, hybrid, and staging indexes |
| Graph | Neo4j 5.26 Community | Knowledge relationships and traversal |
| Identity | External OIDC or direct LDAP/Windows AD | Authentication, directory synchronization, and role mapping |
| Deployment | Docker Compose v2, Helm chart 0.2.0 | Single-host and Kubernetes deployment |

## 5. Project Structure

```text
Nomosmart/
├── frontend/                  Next.js application, UI components, and translations
├── backend/                   FastAPI API, workers, and application services
├── sql/migrations/            B054 initial schema and V001–V056 upgrade history
├── deploy/docker/             Docker Compose runtime configuration
├── deploy/helm/nomosmart/     Helm chart and environment values
├── deploy/installer/          Profile-aware Kubernetes installer
├── deploy/package/            Secret and TLS package lifecycle tool
├── deploy/release/            Release packaging and integrity checks
├── docs/                      Technical decisions and operating guides
└── docker-compose.yml         Single-host deployment model
```

## 6. Getting started

Current authentication contract: **2**. Select external OIDC or direct LDAP/Windows AD sign-in for each deployment. Both modes synchronize users and groups directly from one directory. Compose and Helm include no identity-provider workload.

| Need | Start here |
| --- | --- |
| Docker Compose | [Deployment operations](deploy/README.md#docker-compose) and the [environment example](deploy/docker/nomosmart.env.example) |
| Kubernetes with existing services | [Protocol installer](deploy/README.md#helm-installation), [target example](deploy/installer/nomosmart-install.protocol.example.toml), [values example](deploy/installer/protocol-values.example.json) |
| Kubernetes bundled datastores | [Helm operations](deploy/README.md#helm-installation); the directory and optional OIDC service remain operator-managed |
| Local Kubernetes | [Local guide](deploy/local/README.md) |
| Authentication, migration and recovery | [Authentication guide](docs/AUTHENTICATION.en.md) |

Before starting, prepare trusted HTTPS, PostgreSQL, Redis, S3/RustFS, OpenSearch, Neo4j, a read-only directory account, and the immutable ID of the initial administrator group. OIDC mode also needs an externally registered client and exact callback. Keep passwords, encryption keys and private certificates outside Git.

The public hostname must resolve to the intended edge/Ingress and its certificate must be trusted. Compose defaults to loopback80/443; datastore ports stay private unless an explicitly chosen diagnostic profile exposes them on loopback.

Current source remains **not release-ready**: required scenario evidence and versioned delivery qualification remain open. The 80% target is advisory under CHG-419; previously accepted platform deferrals remain separate. The scoped Windows AD result is retained and does not qualify a complete release. See [verification](docs/AUTHENTICATION-STATUS.md) and [release readiness](deploy/RELEASE_READINESS.md).

## 7. Docker Compose

For a fresh installation, copy the public configuration without overwriting an existing operator file:

```sh
cp -n deploy/docker/nomosmart.env.example deploy/docker/nomosmart.env
chmod 600 deploy/docker/nomosmart.env
```

Prepare the referenced platform Secret/TLS files before startup. The package tool's `init --help` describes generation options; generation does not create an enterprise directory account or its password. Provide a real `DIRECTORY_BIND_PASSWORD_FILE`, public directory CA, and a non-secret bootstrap JSON based on the [LDAP](deploy/docker/auth-bootstrap.example.json), [AD](deploy/docker/auth-bootstrap.ad.example.json) or [OIDC](deploy/docker/auth-bootstrap.oidc.example.json) example. Replace every example endpoint, source UUID, search base and `admin_group_id` with verified values. OIDC client credentials must match the external client registration.

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
# Build the reviewed current source, or configure compatible reviewed images.
docker compose --env-file deploy/docker/nomosmart.env build frontend backend
docker compose --env-file deploy/docker/nomosmart.env up -d
docker compose --env-file deploy/docker/nomosmart.env ps
```

The profiles are `postgresql,redis,rustfs,opensearch,neo4j`. Disable a datastore profile only when its external endpoint, credentials and TLS trust are configured. Only the edge publishes ordinary application ports; datastore debug ports remain loopback-only.

Migration and bootstrap must succeed before normal use. In onboarding, sign in as a synchronized administrator; OIDC administrators also verify their identity in system settings. Then finalize:

```sh
docker compose --env-file deploy/docker/nomosmart.env run --rm --no-deps deployment-finalize
```

After finalization succeeds, set `DEPLOYMENT_PHASE=operational` in the operator configuration and recreate the application services with the same Compose invocation. Verify readiness. There is no fixed initial application password. See [detailed operations](deploy/README.md) for prerequisites, Secret custody and safe shutdown.

## 8. Kubernetes with Helm

The protocol installer currently expects `deploymentProfile=external-services`, existing runtime/TLS Secrets and explicitly managed infrastructure. Datastores may be in the same cluster; external ownership does not mean public Internet access.

Copy the [target TOML](deploy/installer/nomosmart-install.protocol.example.toml) and [non-secret values JSON](deploy/installer/protocol-values.example.json) to an operator directory. Replace the context, namespace, release, installation UUID, absolute chart path, image references, service endpoints, Secret names and directory bootstrap values. Paths in the target are relative to that TOML. Keep `secrets.data` empty and use `secrets.existingSecret`.

```sh
./deploy/installer/nomosmart-install plan --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install install --protocol-config /operator/path/target.toml
```

The target example uses `values_file="protocol-values.json"`; save the copied JSON under that name, or update the target to its actual filename.

The operator path is a placeholder. `install` exits 10 when normal-administrator sign-in is required. Complete that sign-in before `finalize`; inspect `status` after an interruption before deciding to `resume`.

```sh
./deploy/installer/nomosmart-install finalize --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install verify --protocol-config /operator/path/target.toml
```

A bundled datastore deployment uses the chart directly with reviewed operator values and the same bootstrap/sign-in/finalize sequence; the protocol installer does not accept the bundled profile. The [deployment guide](deploy/README.md#helm-installation) explains both paths. The current one-click wrapper uses `--protocol-config` and external-services only. Original factory/authentication-contract-1 examples are explicitly archived and excluded from current packages.

Current one-click operation (create new files in an existing private directory, then edit real settings):

```sh
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --init-config
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --plan-only
./deploy/installer/nomosmart-one-click --protocol-config /operator/private/target.toml --confirm-digest REVIEWED_PLAN_DIGEST
```

Create the parent directory with mode700 first. Initialization never overwrites files or creates credentials/services. Confirmation binds the target, values and chart; changed inputs require a new plan. Exit10 means normal administrator sign-in and explicit finalization are still required.


## 9. Authentication and directory management

| Setting | Current behavior |
| --- | --- |
| Ordinary sign-in | OIDC **or** LDAP/Windows AD; no automatic fallback |
| Directory sync | Both modes read LDAP/AD directly; default daily 02:00 `Asia/Taipei`, editable daily time/timezone and manual sync |
| Identity | Stable directory ID and internal UUID; no email/name guessing or automatic user creation |
| Authorization | Internal roles and project governance; effective role permissions are the union |
| Session | Server-side HttpOnly/Secure cookie; foreground actions extend a 30-minute idle deadline; no fixed maximum ordinary lifetime |
| Connection settings | Web-editable after fresh authentication; LDAP Bind and OIDC client secrets encrypted in PostgreSQL; encryption keys stay in deployment Secrets |
| Emergency access | Deployment CLI only, normally disabled, random credential with a fixed 15-minute activation window |

Register this exact OIDC callback, replacing the application origin:

```text
https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback
```

The Backend owns Discovery, code exchange, PKCE, state/nonce and token validation. Browser code receives no upstream bearer token. Local logout revokes the internal session. See the [authentication guide](docs/AUTHENTICATION.en.md) for field mapping, fresh authentication, key rotation and recovery.

## 10. Upgrade and source development

Current migration target is `056`: [V056](sql/migrations/V056__native_pdf_cleanup.sql) separates immutable PDF receipts from removable content and versions the document policy. A fresh database uses the unchanged [B054](sql/migrations/B054__protocol_authentication_and_sessions.sql) baseline, then V055 and V056; existing databases follow their published upgrade chain. No new baseline or rewritten historical SQL is introduced. Exact checksums are in the [migration contract](deploy/migrations/release-contract.json). Stop old Workers before migration; recovery uses a retained pre-upgrade snapshot with old API read-only, not a destructive schema downgrade.

Pause old auth/sync producers during the coordinated frontend/backend/worker upgrade. Preserve internal UUIDs, role relationships and history. Existing browser sessions must sign in again. Remove retired `keycloak.*`, `global.keycloakPath`, `bootstrap.keycloak*`, product Secrets and `/identity` routes from old values; review complete values with `--reset-values` instead of carrying them forward with `--reuse-values`.

An actual Helm upgrade will remove old release-owned identity workloads, routes and product Secrets. Independently manage any IdP, data and credentials that must remain. Existing databases/PVCs are not automatically cleared by this documentation update.

Source development uses the [Backend](backend/.env.example) and [Frontend](frontend/.env.example) examples with real non-production services. Fill Backend `AUTH_BOOTSTRAP_CONFIGURATION`, `AUTH_TRUST_ROOT`, endpoint allowlists, private credentials and current migration settings. Route browser traffic through trusted HTTPS so Secure cookie and callback rules are exercised. The Frontend only needs its public origin and same-origin Backend proxy; OIDC credentials belong to the Backend.

## 11. Operations, verification and documentation history

Monitor last successful directory sync, failed runs, authentication audit, worker health and readiness. Failed directory reads retain the last committed snapshot; use manual sync when an update cannot wait until the next daily run. Activity-free background requests do not keep users signed in.

Run focused checks from the repository root:

```sh
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
python3 -m unittest discover -s backend/tests -p test_protocol_deployment.py -v
```

Configuration checks do not prove runtime login or production readiness. Read the [E2E guide](docs/E2E-ENVIRONMENT-GUIDE.md), [deployment removal results](docs/AUTHENTICATION-STATUS.md#deployment-file-checks) and [current gaps](docs/AUTHENTICATION-STATUS.md).

Old 0.2.0 installation instructions are preserved in the [documentation archive](docs/archive/authentication-contract-1/README.md). Use the current guides above for this checkout.

## 12. API and Usage

### 12.1 API locations and authentication

| Interface | Location | Authentication |
| --- | --- | --- |
| Internal API | `/api/v1` | Server-side session cookie; state-changing requests require CSRF and Origin checks |
| Public Integration API | `/api/public/v1` | `Authorization: Bearer <api-key>` or `X-NomoSmart-API-Key` |
| OpenAPI document | `/openapi.json` | Backend origin |
| Swagger UI | `/docs` | Backend origin |
| Product API guide | `/api-docs` | Authenticated NomoSmart page |
| Process health | `/api/v1/health` | Returns `{"status":"healthy"}` |
| Dependency readiness | `/api/v1/ready` | Returns `ready` details or HTTP 503 |

The FastAPI application version is `0.2.0`; API paths retain `/v1`. Backend authorization combines local role permissions and project-scoped Owner, Editor, and Viewer governance.

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
- **Platform setup** runs as a command or Kubernetes Job and prepares storage, search, graph, authentication configuration and direct directory synchronization; it does not provision an external IdP.

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

- External OIDC or direct LDAP/AD issues the same HttpOnly/Secure internal session cookie. State-changing requests require CSRF and Origin checks.
- Backend authorization evaluates internal roles and project scope; caller-supplied identity headers do not authenticate a user.
- Directory Bind/OIDC client secrets are encrypted in the database. Encryption keys and other platform/business credentials retain their deployment Secret policy.
- Ordinary sessions have a 30-minute sliding idle deadline; background polling does not extend it. The ten-minute settings unlock and fifteen-minute emergency window are separate.
- Preserve CA/hostname verification and audit. Do not log passwords, tokens, cookies or callback query strings.

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

### 17.4 Sign-in or directory synchronization fails

Check `/api/backend/auth/config` for the configured mode, then inspect safe error codes and last successful sync. For LDAP, check the read-only account, search bases and CA. For OIDC, check Discovery at the actual issuer, client registration and exact callback. Unsynchronized/disabled/conflicting identities are not automatically created or merged. Preserve TLS and the configured sign-in mode.

### 17.5 A Kubernetes installation pauses

```bash
./deploy/installer/nomosmart-install status \
  --protocol-config "$NOMOSMART_INSTALL_CONFIG"
./deploy/installer/nomosmart-install doctor \
  --protocol-config "$NOMOSMART_INSTALL_CONFIG"
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

## 18. Installation verification checklist

- Migration056/bootstrap succeed; application, Worker and Beat are healthy and readiness is ready.
- Direct directory sync, administrator-group mapping, normal sign-in through the selected mode and finalization have real evidence.
- Verify authorization,30-minute idle/foreground renewal, logout, disabled users and CSRF with real services.
- OIDC uses the actual external issuer and exact callback; the OIDC service is needed only for that selected mode.
- Separately verify model/document import, review, publishing, queries and citations as real business workflows.
- Reuse the scoped Windows AD result; record unverified AD modes and actual critical-flow/delivery gaps separately. Coverage is measured with an advisory 80% target; configuration checks do not prove runtime behavior.

## 19. Documentation

- [Deployment guide](deploy/README.md)
- [Docker configuration example](deploy/docker/nomosmart.env.example)
- [Kubernetes installer examples](deploy/installer/nomosmart-install.protocol.example.toml)
- [External-services example](deploy/installer/protocol-values.example.json)
- [Migration release contract](deploy/migrations/release-contract.json)

## 20. License

NomoSmart is licensed under the [Apache License 2.0](LICENSE).

### Native PDF document recognition (CHG-410)

New PDF extraction sends the original PDF directly to an explicitly configured
OpenAI Responses document model, including PDFs with selectable text. TXT and
Markdown are read directly and do not need an OCR model. Local Tesseract, Poppler,
bubblewrap, page rasterization and per-page scratch mounts are retired from the
current application deployment. Historical artifacts and recovery records remain.

Configure the model’s explicitly declared `native_pdf` capabilities using the PDF capability form, input/output token
prices, and database-owned request/document output budgets before new PDF work.
Unknown capabilities, unavailable token counts, oversize inputs, and incomplete
responses stop processing without automatic splitting or provider fallback.
Token counting sends the PDF to the provider and may incur charges. New sources
are document-level: physical page numbers remain unknown rather than inferred.
See [document-recognition operations](docs/NATIVE-PDF-OCR-OPERATIONS.md) for setup,
limits and recovery. This source change does not upgrade the 8443 environment.

新版 PDF 萃取一律把原始 PDF 交給明確設定的 OpenAI Responses 文件模型，包含已有
文字的 PDF；TXT／Markdown 直接讀取。新部署不再需要本機 OCR 工具或逐頁暫存空間。
請先設定模型能力、輸入／輸出 token 價格及每次請求／整份文件預算。超限或結果不完整
會停止，不會自動切割或改用其他供應商。來源標示為整份文件，不推測實體頁碼。

### PDF simplification and compatibility (CHG-412)

Chat and Embedding constitute basic project model configuration; PDF recognition
is shown separately and requires an eligible native-PDF model. Model activation,
default selection, project binding and dispatch share the same qualification.
The capability form is the single editor for native PDF limits; conflicting
advanced JSON is rejected, and connection probes do not claim PDF acceptance.

The versioned document policy contains concurrency, document timeout, dispatch
yield delay and foreground/background polling. Legacy parser resource keys and
old policy hashes remain history-only. New reports show document counts and real
tokens/cost; unknown page counts do not become zero. Archive cleanup proves work
stopped and checks unresolved paid calls before deleting content. Content-free
receipts retain original IDs and accounting after eligible content is removed.

This change requires coordinated new application/Worker code and V056. It does
not upgrade8443 or certify the full release. See the operations guide for safe
migration, scope-qualified verification and rollback limits.

# NomoSmart

English | [繁體中文](README.zh-TW.md)

NomoSmart is an enterprise knowledge management platform for turning documents and connected data into reviewed, searchable knowledge with traceable answers.

Version: **0.3.0** (in development, not yet released; the latest release is 0.2.5). Deploy with Docker Compose or Kubernetes/Helm. The application supports Traditional Chinese and English.

## What's new in 0.3.0 (not yet released)

- **One question-answering API (Open Responses)**: the in-product chat test and integration clients use the same Open Responses compatible `POST …/responses` contract (JSON, or SSE with `stream: true`). The chat test streams answers as they arrive. The previous `/chat`, `/chat/stream`, `/chat/responses/{id}/feedback` and `/chat/query` endpoints are removed.
- **Multi-turn conversations**: each question chooses single- or multi-turn with `previous_response_id`. Earlier turns come only from stored answers of the same API key and employee (or the same chat-test user), follow-ups are rewritten into a standalone search question, and answers cite only passages found for that turn. The chat test picks single- or multi-turn when a conversation starts.
- **Multi-turn CSV validation**: rows sharing a `conversation_key` run in `turn` order as one conversation; the Judge sees the earlier turns, a failed turn skips the rest of its scenario, and results report a scenario pass rate.
- **FTP, FTPS and SFTP removed**: data services support S3 and HTTP API only; the `paramiko` dependency and the related Compose/Helm settings are gone.
- **Clean-up**: unused frontend and backend code and translation keys were removed.

0.3.0 contains breaking API and Helm changes; see [Upgrading](#upgrading-from-an-older-version). Changes in 0.2.5: [GitHub Release v0.2.5](https://github.com/crispkid/Nomosmart/releases/tag/v0.2.5).

## Features

- Import PDF, UTF-8 TXT and Markdown files, plus S3 and HTTP API sources (FTP, FTPS and SFTP sources were removed after 0.2.5).
- Send original PDFs directly to a configured LLM for Markdown output; read TXT/Markdown directly.
- Create knowledge chunks, tags and embeddings while preserving original documents, versions and citations.
- Submit, reject and publish content under project permissions, retaining completed work and review history.
- Use keyword, vector and hybrid search, knowledge graphs and answers with source citations.
- Test answers in single- or multi-turn conversations, and run CSV validation with multi-turn scenarios, Judge scoring and a scenario pass rate.
- Manage directories, roles, models, usage, API clients, reports and audit records.

## Architecture

```text
Browser -- HTTPS -- Next.js Frontend / Same-origin Proxy -- FastAPI Backend
                                                                |
                         +--------------------------------------+----------------+
                         |                                      |                |
                 External OIDC or LDAP/AD                   PostgreSQL          Redis
                 Sign-in and directory sync             Settings/versions    Task queue
                                                                                 |
                                                                      Celery Worker/Beat
                                                                                 |
                                    +--------------------------------------------+
                                    |                                            |
                           Native PDF document model                   S3/OpenSearch/Neo4j
                              PDF -> Markdown                         Files/search/relations
```

The Backend owns authentication, authorization, configuration and dispatch. Workers run imports and knowledge processing; Beat schedules tasks. Chat, Embedding, PDF recognition and Judge use organization-configured model services. Integration clients use the separate public API within their authorized project scope; it follows the Open Responses format, and the in-product chat test uses the same contract through `/api/v1/responses`.

| Component | Technology and purpose |
| --- | --- |
| Frontend | Next.js 16.4.1, React 19.2.3, TypeScript; same-origin Backend proxy |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic |
| Background processing | Celery and Redis; imports, directory sync and scheduling |
| Authoritative data | PostgreSQL 18.4; forward-only Flyway migrations |
| Object storage | S3-compatible storage; RustFS for bundled deployments |
| Search and graph | OpenSearch 2.19 and Neo4j 5.26 Community |
| Deployment | Docker Compose v2 and Helm Chart 0.2.5 |

## PDF and model configuration

Every new PDF, including PDFs with selectable text, is sent intact to an explicitly configured native document model supporting `openai_responses`. The current path no longer uses local OCR, local text extraction, rasterization, page splitting or automatic fallback.

- Configure the service, model, prices and actual `native_pdf` capabilities in system management. Capacity is never inferred from a model name.
- Every project needs an active OCR model with native PDF capability: creating a project, or changing its Chat, Embedding or OCR model, is rejected without one (`project_model_configuration_required`). Existing projects without OCR keep working until their models are changed.
- OpenAI Chat and Judge models use the Responses API. The connection test sends a minimal real request and reports an unknown model, failed authentication or a rejected call format separately.
- Input counting sends the document to the provider; counting and generation may incur charges. Later tagging and embeddings follow the project configuration.
- Oversized documents, unavailable trustworthy input counts, truncated or incomplete responses stop processing. Documents are not automatically split, and partial output is not published.
- New results trace to the original document and version. Physical page numbers remain unknown unless trustworthy; the model does not guess them.
- A paid request with an unknown result is not automatically replayed. Reconcile its receipt and usage first. Cancellation retains confirmed accounting.
- Submitting a version for review while its processing is still finalizing returns `409 document_processing_finalizing`; submit again after a few seconds.

See [PDF recognition operations](docs/NATIVE-PDF-OCR-OPERATIONS.md) for capability fields, transport ceilings, document budgets and recovery.

## Authentication, directories and permissions

Each deployment selects **external OIDC** or **direct LDAP/Windows AD** sign-in, without automatic mode fallback. Both modes synchronize users and groups directly from LDAP/AD. Internal NomoSmart roles and project governance determine access.

| Area | Behavior |
| --- | --- |
| OIDC | Provider-neutral protocol; Backend validates issuer, signature, audience, state, nonce and PKCE |
| LDAP/AD | Organization directory authentication over trusted encrypted connections and CA verification |
| Directory synchronization | Daily at 02:00, `Asia/Taipei`, by default; configurable daily time/time zone and manual sync |
| Identity | Stable directory IDs and internal UUIDs; no guessed name or email matching |
| Roles | Permission unions across roles; view/create/edit/delete remain independent |
| Session | Shared server session and HttpOnly/Secure cookie; 30-minute sliding idle timeout, extended by foreground activity, not background polling |
| Settings | Fresh authentication unlocks important web connection settings; Bind/client secrets are encrypted in the database, with keys supplied through deployment Secrets |

Compose/Helm do not deploy Keycloak or require its Admin API. The organization independently manages its OIDC provider and directory. There is no fixed initial application username/password.

Register the exact OIDC callback: `https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback`. See the [authentication guide](docs/AUTHENTICATION.en.md) for mapping, initial administrators, emergency access and recovery.

## Prerequisites and package verification

Prepare trusted HTTPS, the required data services, a read-only directory account, its CA and a stable initial administrator group ID. OIDC also needs a registered client and callback. Keep credentials and private keys outside Git in protected files or Secret references.

After downloading and extracting a version package, check its published SHA-256 and verify against a signer fingerprint obtained through an independent trusted channel. A key included in a download does not establish trust by itself:

```sh
python3 deploy/release/nomosmart-release verify-package \
  --package . \
  --purpose local-risk-reviewed-release \
  --trusted-fingerprint "$NOMOSMART_TRUSTED_FINGERPRINT"
```

Python and GPG are required. This version uses the signed local risk-reviewed format. Existing unverified test candidates and older package formats cannot be renamed into this release.

## Docker Compose

Run the following from the version package or reviewed source root. Copy the public example without overwriting existing operator settings:

```sh
cp -n deploy/docker/nomosmart.env.example deploy/docker/nomosmart.env
chmod 600 deploy/docker/nomosmart.env
```

In a signed version package, the package tool can generate the platform Secret/TLS inputs and pin the manifest images. It verifies the package first, so supply the same independently trusted fingerprint as an argument or through `NOMOSMART_TRUSTED_FINGERPRINT` (the argument wins):

```sh
./deploy/package/nomosmart-package init --target compose --profile factory_acceptance --app-env development \
  --no-display --random-initial-credentials --public-host nomosmart.local \
  --trusted-release-fingerprint "$NOMOSMART_TRUSTED_FINGERPRINT"
```

`./nomosmart up --trusted-release-fingerprint …` accepts the same input for a fresh install. A missing, wrong or untrusted fingerprint, or a changed package file, stops before any configuration or credential is written.

Otherwise prepare the referenced Secret/TLS files following the [deployment guide](deploy/README.md#docker-compose), then provide reviewed images, real services and [directory bootstrap configuration](deploy/docker/auth-bootstrap.example.json). Build application images only for source deployments; version packages use the images pinned in their manifest.

```sh
docker compose --env-file deploy/docker/nomosmart.env config --quiet
docker compose --env-file deploy/docker/nomosmart.env up -d
docker compose --env-file deploy/docker/nomosmart.env ps
```

Default datastore profiles are `postgresql,redis,rustfs,opensearch,neo4j`. For existing external services, disable the corresponding profile and configure actual endpoints, TLS trust and credentials.

After migration/bootstrap succeeds, a synchronized normal administrator signs in through the chosen mode. OIDC administrators also complete fresh authentication in system settings. Then run:

```sh
docker compose --env-file deploy/docker/nomosmart.env run --rm --no-deps deployment-finalize
```

After success, set `DEPLOYMENT_PHASE=operational`, update application services using the same configuration and check readiness. See the [deployment guide](deploy/README.md) for logs, shutdown and platform configuration generation.

## Kubernetes and Helm

The chart supports bundled or external datastores. The protocol installer currently uses `deploymentProfile=external-services`: services can reside in the same cluster; external means operator-managed, not necessarily on the public Internet.

Copy the [target TOML](deploy/installer/nomosmart-install.protocol.example.toml) and [non-secret values JSON](deploy/installer/protocol-values.example.json) into a private operator directory. Replace context, namespace, installation UUID, chart path, images, services, directory/group IDs and Secret names. Relative paths are resolved against the TOML. Save the JSON as the example's `protocol-values.json`. Keep `secrets.data={}` and reference credentials with `secrets.existingSecret`.

```sh
./deploy/installer/nomosmart-install plan --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install install --protocol-config /operator/path/target.toml
# Complete real normal-administrator sign-in before finalization.
./deploy/installer/nomosmart-install finalize --protocol-config /operator/path/target.toml
./deploy/installer/nomosmart-install verify --protocol-config /operator/path/target.toml
```

`/operator/path` is a placeholder. `action-required`/exit 10 is the administrator sign-in checkpoint. After interruption, check `status` instead of repeatedly reinstalling. See [Helm operations](deploy/README.md#helm-installation) for complete direct bundled-chart values and initialization stages.

## Upgrading from an older version

1. Verify package/image identities and retain recoverable existing data, configuration, encryption keys and TLS/CA materials. Review the target deployment difference.
2. Pause old import/synchronization producers and stop old Workers/Beat. Coordinate Frontend, Backend, Worker and Beat updates to avoid mixed-version writers.
3. Supply complete current authentication settings, select LDAP/AD or OIDC, and retain internal UUIDs, user/role relationships and history. Remove retired `keycloak.*` deployment fields. Use reviewed complete Helm values with `--reset-values`, not `--reuse-values`.
4. Use the normal migration flow to advance existing databases to **063**. Fresh databases use B054 followed by V055–V063; V062 and V063 only add columns. Compose installations created by an earlier version pin the old target in `deploy/docker/nomosmart.env`: set `MIGRATION_REQUIRED_VERSION=063` and `MIGRATION_REQUIRED_CHECKSUM=1135291166` before starting 0.3.0, otherwise bootstrap stops with `database_migration_version_unexpected` (data is unaffected). Never rewrite historical SQL or manually drop history fields. The [migration contract](deploy/migrations/release-contract.json) declares the target and checksum.
5. Update integrations for the 0.3.0 API (breaking): ask questions with `POST /api/public/v1/responses` and `model: "nomosmart:project/<project_id>"` instead of `/projects/{id}/chat` and `/chat/stream`, send feedback to `/responses/resp_<id>/feedback`, and read Open Responses responses and errors. `Idempotency-Key` is now optional. Remove the Helm values `ftpsCa` and `sftpKnownHosts`, which the values schema now rejects. Optional new settings with defaults: `CHAT_HISTORY_MAX_TURNS` (5), `CHAT_HISTORY_MAX_CHARACTERS` (12000) and `VALIDATION_SCENARIO_MAX_TURNS` (20).
6. Select an eligible native document model for new PDFs and configure capabilities, prices and output budgets. Retain old OCR models, page output, receipts and usage as history. Old unfinished work requires explicit review; it is not silently converted into a new request.
7. Complete bootstrap, normal-administrator sign-in and finalization, then check readiness, sign-in and existing data reads. Existing browser sessions must sign in again.

Application rollback and schema rollback are different operations. Do not drop new tables to downgrade or let old Workers write the new policy. Coordinate recovery using retained snapshots and compatible versions. The [authentication upgrade guide](docs/AUTHENTICATION.en.md) and [PDF operations guide](docs/NATIVE-PDF-OCR-OPERATIONS.md) describe limits. Publishing a version does not update existing deployments.

## APIs, operations and qualification

| Endpoint | Purpose |
| --- | --- |
| `/api/v1` | Internal Backend API; server sessions and Backend permission checks; the chat test asks through `POST /api/v1/responses` |
| `/api/public/v1` | Integration API; Open Responses compatible `POST /responses` (JSON or `stream: true`, multi-turn with `previous_response_id`) and `POST /responses/{response_id}/feedback`; independent API keys and project scope |
| `/openapi.json`, `/docs` | Backend OpenAPI/Swagger |
| `/api-docs` | In-product API guide |
| `/api/v1/health`, `/api/v1/ready` | Process health and dependency/bootstrap readiness |

Monitor the last successful directory sync, failed work, queues, audit records and readiness. Failed directory runs preserve the last successful snapshot. Reconcile uncertain paid requests through their receipts. If a worker disappears mid-document and new documents stop being admitted, release the stuck execution with `app.deployment.document_execution_recovery` (see [deploy/README.md](deploy/README.md#recovering-a-stuck-document-execution-025)). Logs must not contain credentials, tokens, cookies or document bodies.

0.2.5 was qualified on its own source and images: all 31 mandatory scenarios and 19 release gates were rerun, and the package was signed and verified, including tamper and wrong-fingerprint checks and a real `init`. Complete-denominator line coverage is 26.25% (frontend) and 46.0% (backend); 80% is an improvement target and does not decide readiness. Its three plaintext-FTP High findings are accepted for 0.2.5 only until 2026-12-15 08:00 (Taipei). 0.3.0 removes the FTP code (no High static-analysis findings remain), but 0.3.0 has not yet completed release qualification or signing; until it does, 0.2.5 remains the qualified release. Production multi-host capacity, HA, network isolation and production backup are not qualified (`production_ready=false`) and cannot be inferred from local acceptance.

## Repository and development

```text
frontend/                 Next.js UI, same-origin proxy and localization
backend/                  FastAPI, model/directory integrations and background work
sql/migrations/           B054 baseline and forward migration history (currently 063)
deploy/docker/            Compose configuration examples, entry point and Secret tools
deploy/helm/nomosmart/     Helm chart, ConfigMap/Secret references and probes
deploy/installer/          Protocol installation and onboarding tools
deploy/release/            Assembly, signing and integrity verification
docs/                     Operating guides and retained historical records
```

Source development requires real non-production services; start with the [Backend](backend/.env.example) and [Frontend](frontend/.env.example) examples. Select the narrowest harness checks for the change. Configuration syntax checks do not establish sign-in or workflow acceptance; reuse valid unaffected results.

See [LICENSE](LICENSE) for licensing.

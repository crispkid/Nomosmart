# Upgrading NomoSmart

English | [繁體中文](UPGRADING.zh-TW.md)

This guide covers upgrading an existing NomoSmart deployment. Read
[General steps](#general-steps) first, then the notes for **every version between your
current version and the target**, newest first. What each version changed is in
[CHANGELOG.md](CHANGELOG.md).

Publishing a new version never updates an existing deployment. Upgrade one deployment at
a time, after reading that version's GitHub Release and the upgrade guide shipped with its
package.

## General steps

1. **Verify the package.** Check the published SHA-256, the OpenPGP signature and the
   image digests, and verify the package against a signer fingerprint obtained through an
   independent trusted channel (see [Package verification](README.md#before-you-install)).
2. **Keep what you need to recover.** Retain the existing data, configuration, encryption
   keys and TLS/CA materials, and review the difference between the current and target
   deployment.
3. **Stop old writers.** Pause old import and directory-sync producers and stop the old
   Workers and Beat. Update Frontend, Backend, Worker and Beat together so that two
   versions never write at the same time.
4. **Migrate the database forward.** Use the normal migration flow to reach the target
   version. Fresh databases start from the baseline and apply every later migration.
   Never edit historical SQL or drop history fields by hand.
   - The current target and checksum are declared in the
     [migration contract](deploy/migrations/release-contract.json).
   - **Compose:** installations created by an earlier version pin the old target in
     `deploy/docker/nomosmart.env`. Set `MIGRATION_REQUIRED_VERSION` and
     `MIGRATION_REQUIRED_CHECKSUM` to the target's values (see
     [Migration targets](#migration-targets)) before starting the new version; otherwise
     bootstrap stops with `database_migration_version_unexpected` and data is unaffected.
   - **Helm:** the chart of each version already defaults to its target. Use reviewed,
     complete values with `--reset-values`, not `--reuse-values`.
5. **Finish and check.** Complete bootstrap, normal-administrator sign-in and
   finalization, then check readiness, sign-in and that existing data can be read.

**Rollback.** Rolling back the application and rolling back the schema are different
operations. Do not drop new tables to downgrade, and do not let old Workers write data in
a newer format. Recover with retained snapshots and compatible versions.

## Migration targets

| Version | Migration target | Checksum (Flyway) | New migrations |
| --- | --- | --- | --- |
| 0.5.0 | 070 | `135363118` | V070 |
| 0.4.2 | 069 | `-1562058873` | V069 |
| 0.4.1 | 068 | `-1307752697` | V068 |
| 0.4.0 | 067 | `1913543487` | V064–V067 |
| 0.3.0 | 063 | `1135291166` | V062–V063 |
| 0.2.5 | 061 | `1514288448` | V058–V061 |
| 0.2.4 | 057 | `-398616135` | V057 |
| 0.2.3 | 056 | `99561060` | V054–V056; new databases start from the B054 baseline |
| 0.2.0–0.2.2 | 053 | — | V052–V053 |
| 0.1.0–0.1.2 | 051 | — | B051 baseline; existing databases keep V001–V051 |

A dash means the version's migration contract lists separate checksums for the baseline
and the migration path; use the contract shipped in that version's package.

## Version notes

### Upgrading to 0.5.0 (from 0.4.2)

- V070 only adds `users.last_login_at` (nullable) and fills it from the audit log with
  each user's latest successful sign-in. No tables are added; users who never signed in
  stay empty.
- The interface is redesigned. Screens, names and navigation changed, so update user
  guides, screenshots and any browser automation that relies on page structure. The API
  only adds fields and endpoints; existing integrations keep working.
- Pending approvals are due 48 hours after submission, the same threshold as the existing
  "over 48 hours" warning; no setting is added.

### Upgrading to 0.4.2 (from 0.4.1)

- V069 only adds five question-answering settings (Top K 5, Top P 1.0, minimum score 0,
  reranking off, no reranker model), a per-project reranking switch (off), two retrieval
  trace fields, and allows the Reranker model type. No tables are added. Existing
  projects keep reranking off.
- Sub-questions now retrieve K chunks (default 5) instead of 2, so the answer model may
  receive more content.
- When `/responses` does not send `nomosmart:top_k`, the system setting
  `retrieval_top_k` is used (default 5, as before).
- A reranker service is not part of the installer; deploy it separately if you enable
  reranking.

### Upgrading to 0.4.1 (from 0.4.0)

- Manager delegates are removed. `PUT /api/v1/users/{id}` returns `422` when it receives
  `manager_delegate_*` fields, so remove them from integrations. Reviews already assigned
  to a delegate stay with that delegate.
- In a project whose only Project Owner is the submitter, the Owner stage has nobody to
  review: new submissions are refused (`no_other_project_owner`). Add a second Project
  Owner. Submissions already at that stage can be returned from Approval administration
  with the "nobody can handle" filter.
- V068 only adds the review route fields, the Owner fallback setting (off) and the
  Approval administration permission for the built-in `system-admin` role. No tables are
  added; existing submissions keep their reviewers.

### Upgrading to 0.4.0 (from 0.3.0)

- **Unique document names.** V064 requires live document names to be unique across all
  projects (compared after trimming, NFKC normalization and lowercasing; deleted
  documents and documents linked from another project are excluded). If duplicates exist,
  V064 fails, rolls back, and the database stays at 063 (Flyway reports
  `could not create unique index "uq_documents_title_key_live"`, SQL State 23505).
  0.3.0 has no rename screen: delete the extra duplicates in 0.3.0 or ask a database
  administrator to rename them before upgrading. The version's upgrade guide includes a
  pre-check query.
- **Existing documents** keep answering questions but have no stations or references.
  After the upgrade, run `python -m app.deployment.backfill_relations` once in the
  Backend container to add supersede relations (safe to repeat). Ordinary references
  appear after re-extracting a document (a new version). Versions returned before the
  upgrade cannot be edited directly; create a revision.
- **Reviews.** A submission can no longer be cancelled; the reviewer returns it. A
  document under review cannot be deleted.
- Question-answering options (reference routing, reference expansion, sub-questions) are
  system settings, not environment variables.

### Upgrading to 0.3.0 (from 0.2.5) — breaking changes

- **Data services.** FTP, FTPS and SFTP data services are removed. Move them to S3 or the
  HTTP API before upgrading. Existing ones stay visible but fail with
  `unsupported_protocol`.
- **API.** The old chat endpoints return 404. Use the Open Responses endpoints:

  | Before 0.3.0 | From 0.3.0 |
  | --- | --- |
  | `POST /api/public/v1/projects/{id}/chat` | `POST /api/public/v1/responses` with `model: "nomosmart:project/{id}"` |
  | `POST /api/public/v1/projects/{id}/chat/stream` | The same, with `"stream": true` |
  | `POST /api/public/v1/chat/responses/{id}/feedback` | `POST /api/public/v1/responses/resp_{id}/feedback` |
  | `POST /api/v1/projects/{id}/chat/query` (chat test) | `POST /api/v1/responses` |

  `Idempotency-Key` is optional. Responses and errors use the Open Responses format.
- **Helm.** Delete the `ftpsCa` and `sftpKnownHosts` values; the values schema rejects
  them. **Compose:** delete `FTPS_CA_CERT_PATH`, `FTPS_CA_DIRECTORY`,
  `SFTP_KNOWN_HOSTS_PATH`, `SFTP_KNOWN_HOSTS_FILE` and their mounts.
- New optional settings with defaults: `CHAT_HISTORY_MAX_TURNS` (5),
  `CHAT_HISTORY_MAX_CHARACTERS` (12000), `VALIDATION_SCENARIO_MAX_TURNS` (20).
- V062 and V063 only add columns.

### Upgrading to 0.2.5 (from 0.2.4)

- V061 switches existing OpenAI chat and judge models to the Responses API, records the previous
  mode in `config.api_mode_migrated_from`, clears their saved connection-test result and writes one
  `ai_model.api_mode_migrated` audit row per model. Its NOTICE output flags models whose base URL is
  not `api.openai.com`: if such a model points to a proxy that only supports Chat Completions, change
  its provider to vLLM or Custom. Test every migrated model again after the upgrade.
- V059 only drops the retired Keycloak column defaults. V060 writes the recorded creator into
  document versions that have none, marked `version_created_by_source = "V060"`.
- Every project needs an active OCR model with native PDF capability. Creating a project,
  or changing its chat, embedding or OCR model, is refused without one
  (`project_model_configuration_required`).
- V058 only adds indexes; writes to the indexed tables wait while each index is built, so
  run it in the normal upgrade window.

### Upgrading to 0.2.4 (from 0.2.3)

- Administration API clients must send the settings version condition; without it they
  receive `428`. Update such clients.

### Upgrading to 0.2.3 (from 0.2.2)

- **PDF processing.** Local OCR, text extraction, rasterization, page splitting and
  automatic fallbacks are retired. Every new PDF, including PDFs with selectable text,
  needs a compatible native document model. Configure its capabilities, prices and output
  budgets; input counting and generation may incur charges. Old OCR models, receipts,
  usage and policies are kept as history, and old unfinished work is not silently turned
  into new paid requests. See [PDF recognition operations](docs/NATIVE-PDF-OCR-OPERATIONS.md).
- **Sign-in.** Authentication contract 2: choose external OIDC or LDAP/AD and supply the
  directory sync and administrator group settings. Users, internal UUIDs, roles and
  history are kept; Keycloak Admin API is no longer needed. Remove the retired
  `keycloak.*` Helm values. Existing browser sessions must sign in again. See the
  [authentication guide](docs/AUTHENTICATION.en.md).
- Private images on GHCR need a registry account or `imagePullSecret` with read access.

### Upgrading to 0.2.2 (from 0.2.1)

- Apply the new NGINX proxy template. Custom proxies need the HTTP/1.1 streaming settings
  for the CSV paths. When using an internal OIDC token endpoint, set `OIDC_TOKEN_URL` as
  in the new template.
- The approval API prefers `submitter_id`; `editor_id` remains an alias.
- Packages use schema 5 and are verified with the bundled verifier and an independently
  trusted signer fingerprint.

### Upgrading to 0.2.1 (from 0.2.0)

- Knowledge document uploads accept only PDF, UTF-8 TXT and Markdown; convert other files
  first.
- FTPS needs a valid certificate matching the host name.

### Upgrading to 0.2.0 and 0.1.x

- No special steps beyond the [general steps](#general-steps). Keep the existing
  configuration, secrets, TLS/CA material and persistent volumes, and do not run reset or
  uninstall steps.

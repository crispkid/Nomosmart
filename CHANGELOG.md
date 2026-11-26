# Changelog

English | [繁體中文](CHANGELOG.zh-TW.md)

All notable changes to NomoSmart are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Dates are release dates in Taipei time.

How to upgrade between versions, including database migration targets, is in
[UPGRADING.md](UPGRADING.md). Each version's GitHub Release also lists its package,
image digests, acceptance results and known limitations.

## [Unreleased]

### Changed

- The README no longer changes with each release. Version history moved to this file,
  upgrade steps to [UPGRADING.md](UPGRADING.md), and security reporting to
  [SECURITY.md](SECURITY.md).

### Fixed

- Times in the chat test conversation history follow the interface language instead of the
  browser language.

## [0.4.2] - 2026-11-26

Database migration target: **069**.

### Added

- Retrieval depth and breadth (Top K / Top P) in System settings → Question answering:
  Top K (chunks per question, 1–20, default 5), Top P (share of the reranked score to
  keep, 0.1–1.0, default 1.0) and a minimum score (0–1, default 0). Sub-questions inherit
  K and P. Chat, batch validation and the public API (`nomosmart:top_k`, new
  `nomosmart:top_p`) can set them per question.
- A retrieval trace, with the timing of each stage, on chat records and validation items.
- Optional reranking: register a Reranker model (a service with a `/rerank` endpoint,
  for example TEI with bge-reranker-v2-m3; not part of the installer), enable it in
  System settings and let Project Owners enable it per project. If the reranker fails or
  times out, the answer falls back to the normal ranking.
- Project settings administration: administrators view all projects and set, one by one
  or in batches, the chat, embedding and OCR models, members and roles (including handing
  over the Owner role) and the reranking switch.
- API: `GET/PATCH /api/v1/projects/{id}/retrieval-settings`,
  `GET /api/v1/system/project-settings`, `GET /api/v1/system/project-settings/{id}`,
  `POST /api/v1/system/project-settings/batch`, and `model_type: "Reranker"` on
  `POST /api/v1/models`.

### Changed

- Each sub-question now retrieves K chunks (default 5) instead of 2.
- When `/responses` does not send `nomosmart:top_k`, the system setting
  `retrieval_top_k` (default 5, as before) is used.

### Fixed

- After a single-file upload, the dialog opens the document at the station waiting for
  confirmation instead of staying open.
- The answer judge and citation cards now include each chunk's section heading, so a key
  sentence recognized as a heading no longer makes the judge report missing citations.
- Review-route help text no longer mentions the removed manager delegates.

## [0.4.1] - 2026-11-23

Database migration target: **068**.

### Added

- Before a submission is sent, the reviewer is shown: the submitter's manager, or other
  Project Owners when the optional "send to Project Owner" setting is on. If nobody can
  review, the submission is refused (`409 review_route_unavailable`).
- Approval administration (System management → Approval): authorized administrators
  reassign a manager-stage review, return a submission at any stage and filter
  submissions nobody can handle. It never approves. Permission
  `Approval.ApprovalAdministration` is granted to the built-in `system-admin` role.

### Changed

- A submitter can never approve or return their own submission, even as Project Owner
  (`403 approval_self_review_forbidden`).
- Next.js 16.4.5.

### Removed

- Manager delegates: the user editor no longer sets a delegate, and the user API no
  longer returns `manager_delegate_*` fields and returns `422` when they are sent. The
  database keeps the old columns and data.

### Fixed

- An answer stream the client leaves while it is starting is recorded as cancelled, and
  its `Idempotency-Key` replays the cancellation.
- The soft-deleted residue maintenance tool works on the 0.4.0 schema again and stops
  when the residue still has chunk references.
- Application key rotation also covers follow-up question rewrites and replayed public
  responses.
- `nomosmart-install finalize` only uses running Backend pods during a rolling update and
  retries once on another pod.

### Security

- The 7 Medium findings in the 0.4.0 frontend image (from Next.js 16.4.1) are resolved.

## [0.4.0] - 2026-11-21

Database migration target: **067**.

### Added

- Four-station extraction: full text, chunks, tags and references, and embeddings and
  submission. Every station waits for an editor's confirmation, editors can go back to an
  earlier station while unchanged chunks keep their work, and chunks can be added by
  selecting text. Every extraction entry point uses the four stations.
- Document names can be edited and are unique across the site.
- References and supersedes: station 3 finds citations of other documents and
  "this rule replaces X" statements, and editors can correct them. The graph shows
  reference and supersede lines, and a superseded document shows which newer one
  replaces it.
- Question answering routes questions about references through the reference data and
  splits a question that asks several things into sub-questions. Its options moved to
  System settings → Question answering and apply without redeploying.
- Submission evidence shows reference counts, unmapped references and overlapping chunk
  groups.
- The in-product API guide has a quick start and a limits section.
- External question answering can retry with the same `Idempotency-Key` when the failure
  happened before the model was called. All API logs include `error_code`.
- `python -m app.deployment.backfill_relations` adds supersede relations to existing
  documents.

### Changed

- A submission can no longer be cancelled; only the reviewer returns it
  (`POST /api/v1/approval-requests/{id}/cancel` returns `409 approval_cancel_removed`).
  When the reviewer's account is disabled or missing, a Project Owner can return it but
  not approve it.
- A document under review cannot be deleted (`409 document_review_pending`).
- Processing states and setting updaters are shown in words, and dialogs and buttons
  follow one style.

### Fixed

- Deleting a chunk no longer always returns 409; its reference records are deleted with
  it.
- Deleting a document while it is queued for extraction no longer blocks the dispatch
  queue.
- A deleted document no longer leaves a pending review, and an approved version of a
  deleted document can no longer be published.
- Copied extractions no longer stop at station 3.
- The question answering settings page no longer fails.
- Deleting a referenced document returns its references to "unmapped" so they can map
  again.
- Station 4 no longer fails forever when a model returns `-0.0` in a vector.
- Helm values and the Compose environment example default to migration target 067.

## [0.3.0] - 2026-11-16

Database migration target: **063**. This release contains breaking changes to the API,
data services and Helm values.

### Added

- One Open Responses question-answering API for external systems
  (`POST /api/public/v1/responses`, API key) and in-product chat testing
  (`POST /api/v1/responses`, session), with JSON and SSE streaming and `url_citation`
  annotations. `Idempotency-Key` is optional. Feedback goes to
  `POST /api/public/v1/responses/{resp_id}/feedback`.
- Multi-turn conversations through `previous_response_id`, limited to the same API key,
  employee and project; follow-up questions are rewritten before search. Limits:
  `CHAT_HISTORY_MAX_TURNS` (5) and `CHAT_HISTORY_MAX_CHARACTERS` (12000).
- Single- or multi-turn mode for chat testing.
- Multi-turn scenarios in CSV batch validation (`conversation_key` and `turn` columns,
  `VALIDATION_SCENARIO_MAX_TURNS`, default 20) with a scenario pass rate.

### Removed

- FTP, FTPS and SFTP data services. Existing ones stay visible but fail with
  `unsupported_protocol`; creating them returns 422. Helm values `ftpsCa` and
  `sftpKnownHosts` and the related environment variables are removed.
- The old chat endpoints (`/api/public/v1/projects/{id}/chat`, `.../chat/stream`,
  `/api/public/v1/chat/responses/{id}/feedback`, `/api/v1/projects/{id}/chat/query`) now
  return 404.
- Unused code.

## [0.2.5] - 2026-11-15

Database migration target: **061**.

### Added

- `python -m app.deployment.document_execution_recovery preview|commit` recovers one
  stuck document execution after a worker disappeared; both outcomes are audited.
- An unexpected error inside a worker marks the document as failed and retryable instead
  of pausing all document processing.
- `nomosmart-package init` and `./nomosmart up` accept signed v5 packages with a trusted
  release fingerprint and pin the package's image digests.

### Changed

- OpenAI chat and judge models use the Responses API; V061 migrates existing models. The
  connection test sends a minimal real request and reports missing models,
  authentication failures and rejected formats separately. Projects need an OCR model.

### Fixed

- Submitting a document while it is still finalizing returns
  `409 document_processing_finalizing` instead of blocking finalization for every
  document.
- The OCR output limit now uses the smaller of the system setting and the model's
  capability.
- Two documents creating the same new tag at the same time no longer leave one stuck.
- `nomosmart-package init` works with signed v5 packages again.

## [0.2.4] - 2026-11-10

Database migration target: **057**.

### Added

- System settings in seven categories (people and permissions, identity and directory,
  AI models, documents and knowledge, API keys, general, system status) with search,
  draft protection and re-authentication where needed.
- Separate API key management.
- Per-section version conditions so administrators do not overwrite each other.
- Retention of returned documents follows the setting at the time and is cleaned up by
  the normal background flow.

### Changed

- Administration API clients without a settings version condition receive `428`.

### Fixed

- A wrong password during sign-in or re-authentication no longer shows as 502.
- HTTP remote files are checked against the size limit before or while downloading.
- Archiving an unfinished document version no longer fails on a foreign key.

## [0.2.3] - 2026-11-07

Database migration target: **056**. New databases start from the B054 baseline.

### Added

- Original PDFs are sent directly to a configured LLM document model that returns
  Markdown; TXT and Markdown are read directly. PDF capability settings, input counting,
  document budgets and recognition receipts.
- Sign-in through any OIDC provider or directly through LDAP / Windows AD, with direct
  user and group synchronization, a daily sync time and time zone, and connection
  settings managed in the web interface.
- Server sessions that sign out after 30 minutes of inactivity.
- A refreshed sign-in page, language menu, responsive header and drop-down menus.

### Changed

- Authentication contract 2: choose external OIDC or LDAP/AD. Keycloak Admin API is no
  longer needed; existing browser sessions must sign in again.

### Removed

- Local OCR, text extraction, page rendering, page splitting and automatic fallbacks.
  Every new PDF needs a compatible native document model.
- Built-in Keycloak service dependencies in Compose and Helm, and remaining Keycloak
  wording.

### Fixed

- Copying an extraction with the old and new tokenization formats.
- A cancelled submission no longer stays pending.
- Judge usage keeps the real document version, and deletion decisions keep usage,
  billing and audit records.
- The maintenance cleanup tool accepts the shared LDAP session.
- The title, page title and PDF state labels follow the selected language.

### Security

- Dependency updates for the high-risk findings confirmed in this release's scan.

## [0.2.2] - 2026-10-25

Database migration target: **053**.

### Added

- Filters on the approval list (project, document, submitter, stage, result, date).
- A Traditional Chinese / English switch on the sign-in page.
- Readable browser tab titles, an error recovery screen, and copy buttons in API
  examples.
- Installation packages with an OpenPGP signature, SHA256 checksums and an SBOM.

### Changed

- The approval API prefers `submitter_id`; `editor_id` remains an alias.

### Removed

- The site-wide search entry in the header; each module keeps its own search.

### Fixed

- Approval and publish lists beyond 100 items, total counts and paging.
- Load failures shown as empty data, and stale report requests overwriting current
  results.
- Interrupted CSV exports reported as successful downloads.
- Model validation stuck in the queue after a failed pre-check.
- OIDC re-authentication now uses the configured internal token and JWKS endpoints.
- Dialog focus, keyboard use, graph zoom and drag limits, narrow layouts, form errors,
  notification language, button contrast and touch sizes.

### Security

- Updated Next.js, certifi and development tooling dependencies.

## [0.2.1] - 2026-10-17

Database migration target: **053**.

### Added

- Unified notifications and dialog prompts, and a compact icon toolbar for extraction.
- Background layout, cached initial positions and less recalculation in the knowledge
  graph.
- Enterprise CA support for FTPS, and a separate maintenance command that cleans up
  expired derived data of soft-deleted documents.

### Changed

- Knowledge document uploads accept only PDF, UTF-8 TXT and Markdown.

### Fixed

- Duplicate submissions, query failures shown as empty data and wrong update prompts.
- Model checks, API key expiry, list and search completeness, role updates and data
  source credential references.
- Sign-in stuck in development mode, incomplete Docker build exclusions and stale local
  build caches.
- FTPS certificate and host name validation, and FTP/FTPS access errors reported as
  missing files.
- Replacement of chunks, vectors, tags, indexes and graph data after OCR content edits.

## [0.2.0] - 2026-10-11

Database migration target: **053**.

### Added

- Editing the whole document after OCR, which updates chunks, tags, vectors, indexes and
  the graph.
- PDF pages are rendered to images for OCR, with output budgets configured in the
  database (default 10,000 tokens per page and 1,000,000 per document).

### Changed

- Better retry actions, progress details, number formatting, continuous reading and
  source highlights. Chunking keeps paragraphs, sentences and tables intact where
  possible.

### Fixed

- Replaced derived data is removed, and query model usage is kept when later retrieval
  fails.

## [0.1.2] - 2026-10-03

Database migration target: **051**.

### Added

- `./nomosmart up`, `status`, `logs` and `down`: one command prepares random passwords,
  TLS, configuration, all services, migration and bootstrap and waits for HTTPS
  readiness. Supports localhost, custom ports and `./nomosmart up --build`.

### Removed

- Unused code and dependencies.

### Fixed

- Access scope of the approval and citation APIs, and error display when approvals fail
  to load.
- OIDC callbacks exchanged twice or arriving late; temporary cookies are isolated per
  sign-in flow, and the sign-in pages are consistent in both languages.

## [0.1.1] - 2026-10-01

Database migration target: **051**.

### Added

- A generic static PV and external services configuration contract, and a Docker Desktop
  guide with a dedicated Ingress, capacity checks and cleanup.

### Fixed

- Compose PostgreSQL secret file permissions and initialization, with separate
  administration, migration, application and Keycloak database identities.
- Redis / Sentinel authentication, internal TLS host names, per-file read-only CA mounts,
  and trust and discovery for a private HTTPS Keycloak.
- Example names and internal addresses removed; installation passwords are generated and
  stored in protected files.

### Security

- Next.js 16.3.8 and PyJWT 2.15.0.

## [0.1.0] - 2026-09-30

Database migration target: **051**. First release.

### Added

- Import documents and connected sources; parsing, OCR, Markdown conversion and
  embeddings.
- Document versions, review and publishing, search, graph relationships and answers with
  source citations.
- Keycloak OIDC, LDAP and Windows AD with project permissions and local roles.
- Installation with Docker Compose or Kubernetes, using bundled or existing external
  services.
- A B051 baseline for new databases; existing databases keep the V001–V051 history.

[Unreleased]: https://github.com/crispkid/Nomosmart/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.2
[0.4.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.1
[0.4.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.4.0
[0.3.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.3.0
[0.2.5]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.5
[0.2.4]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.4
[0.2.3]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.3
[0.2.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.2
[0.2.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.1
[0.2.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.2.0
[0.1.2]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.2
[0.1.1]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.1
[0.1.0]: https://github.com/crispkid/Nomosmart/releases/tag/v0.1.0

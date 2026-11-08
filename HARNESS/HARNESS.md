# Harness

The NomoSmart harness is the shared verification contract for agents and humans.
It provides one command surface for frontend, backend, and repository hygiene
checks. It also defines the deployment validation entry points for the future
Docker Compose and Helm/Kubernetes rewrite. The harness is
specification-driven: checks should prove that the repository has an explicit
specification, a test plan, and a path from requirements to human-approved
planning and verification.

`TEST-002` live-only policy applies to every behavioral harness command. The
harness must not report feature, integration, E2E, coverage, or release
acceptance success by substituting mocks, stubs, fakes, fixture adapters,
deterministic adapters, hard-coded success, or static-only smoke checks for real
runtime behavior. Static hygiene commands remain allowed, but they are not
behavioral acceptance.

CHG-340 small prerequisite regression: [entry and limits](../docs/CHG-340-VERIFICATION-GUIDE.md). The original six failed/skipped cases and related63 passed; the canonical complete backend/80% gate remains open. Two approved effective runs are exhausted.

## Quick Start

From the repository root:

```bash
./HARNESS/harness.sh
```

Default checks:

1. Specification hygiene: confirms the product specification and VIBECODING
   control files exist.
2. Planning hygiene: confirms the development plan gate file exists.
3. Repository hygiene: confirms generated dependency folders are not treated as
   source inputs.
4. Backend syntax: compiles backend Python files without importing the FastAPI app.

The default command is a static hygiene baseline only. It does not prove
runtime feature acceptance, live integration, browser E2E, or release
readiness.

Frontend lint and production build are opt-in because the current repository
baseline contains existing lint violations unrelated to harness operation.

## Commands

```bash
./HARNESS/harness.sh all
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh repo:doctor
./HARNESS/harness.sh frontend:lint
./HARNESS/harness.sh frontend:build
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh backend:import
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh i18n:hardcoded
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh test:installer
./HARNESS/harness.sh test:release
./HARNESS/harness.sh integration:release-live
./HARNESS/harness.sh test:e2e
./HARNESS/harness.sh integration:milestone7-live
./HARNESS/harness.sh integration:milestone8b-live
./HARNESS/harness.sh migration:live
./HARNESS/harness.sh coverage:check
./HARNESS/harness.sh coverage:selftest
./HARNESS/harness.sh i18n:ast
./HARNESS/harness.sh test:security-simplification
./HARNESS/harness.sh security:dependencies
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:doctor
./HARNESS/harness.sh deploy:config-policy
./HARNESS/harness.sh governance:selftest
```

Command details:

- `all`: runs `spec:doctor`, `plan:doctor`, `repo:doctor`, and
  `backend:syntax`.
- `spec:doctor`: checks that specification-driven control files exist, identifies
  the active change from the newest `SPEC_CHANGELOG.md` row, and requires that
  change in `SPECIFICATION.md`.
- `spec:trace`: requires the active change in the specification, changelog,
  development plan, test plan and traceability matrix. Approved and pending Gate
  4 states may not contradict each other. `API-COMPAT-001` also requires
  `API_COMPATIBILITY.md`.
- `plan:doctor`: checks that `DEVELOPMENT_PLAN.md` contains the general gates and
  a dedicated `## CHG-NNN ...` section for the active change.
- `plan:approved`: checks only the active change section and active changelog
  row for completed Gate 2, explicit dated Gate 4 human approval, and no pending
  Gate 4 marker. Historical approval text cannot satisfy the current gate.
- `repo:doctor`: verifies expected project directories and warns about generated
  dependency directories present in the working tree.
- `frontend:lint`: runs the existing ESLint setup.
- `frontend:build`: builds the Next.js application. Use this before handing back
  routing, SSR/ISR, i18n, or production-sensitive frontend changes.
- `backend:syntax`: runs `python -m compileall` against backend source files,
  preferring the uv-managed `backend/.venv` when present.
- `backend:import`: imports `backend/main.py`. This requires PostgreSQL and any
  import-time service clients expected by `backend/connection.py`.
- `docker:config`: validates the committed Compose model with service env-file
  resolution disabled, so ignored operator configuration and Secret-adjacent
  values are neither logged nor treated as repository evidence.
- `test:plan`: checks that `TEST_PLAN.md` contains the 80% coverage requirement
  and a test-design reference for the active change.
- `test:frontend`: runs the frontend test script. When `test:coverage` exists,
  it also produces `frontend/coverage/coverage-summary.json`.
- `i18n:hardcoded`: fails when Traditional Chinese literals are found under
  `frontend/src/app` or `frontend/src/components` outside locale files.
- `i18n:ast`: runs the AST-aware visible-copy/fixed-locale rule and its negative
  fixtures; the regex command remains only a fast secondary guard.
- `test:backend`: runs backend pytest once backend tests exist.
- `test:installer`: runs the CHG-248 secret-free config, digest-pinned image,
  redaction, resumable state and Helm stage boundary tests plus CHG-249 process
  group, terminal Job, doctor/reset safety and mounted-Secret input contracts.
  Helm-specific cases are skipped only when Helm is unavailable.
- `test:release`: uses a disposable GnuPG signing identity to prove the
  provider-neutral release manifest/checksum/signature contract, clean detached
  source enforcement, build-tool-free verification and tamper rejection. The
  disposable test key is not an operational release-signing key.
- `integration:release-live`: requires explicit `NOMOSMART_RELEASE_*` isolated
  builder inputs and runs the complete Production release command. A dirty or
  attached checkout, failed gate, missing 80% evidence, unsigned package or
  unavailable signing custody blocks the command.
- `integration:installer-live`: proves read-only planning and, only with
  `NOMOSMART_INSTALLER_LIVE_EXECUTE=YES`, executes/resumes the real installer
  against `NOMOSMART_INSTALLER_LIVE_CONFIG`. Missing approval/prerequisites are
  reported blocked; no fake cluster/provider result is accepted.
- `integration:installer-interrupt-live`: requires the same real config,
  `NOMOSMART_INSTALLER_INTERRUPT_STAGE`, and
  `NOMOSMART_INSTALLER_INTERRUPT_LIVE_APPROVED=YES`; it sends a real SIGINT
  during that stage and verifies a real resume. Set
  `NOMOSMART_INSTALLER_INTERRUPT_SIGNAL=SIGTERM` to run the corresponding
  termination case. Use disposable targets only.
- `test:e2e`: runs browser-backed end-to-end checks against real configured
  frontend, backend and supporting services and writes a report under
  `test-results/e2e/`. Static route/source smoke can be kept as a hygiene
  subcheck, but it must not be reported as E2E acceptance success.
  Required live prerequisite variables are `E2E_FRONTEND_BASE_URL`,
  `E2E_BACKEND_BASE_URL`, `E2E_OIDC_ISSUER_URL`, `E2E_PETER_EMAIL`,
  `E2E_PETER_PASSWORD`, `E2E_JOHN_EMAIL`, and `E2E_JOHN_PASSWORD`; missing
  variables or a missing browser runner are reported as blocked/unavailable and
  fail the command.
- `integration:milestone7-live`: runs the Milestone 7 live acceptance smoke
  against real Development PostgreSQL, OpenSearch and Neo4j. The command seeds a
  temporary approved document version in a database transaction, publishes it
  through the live adapters, verifies the published OpenSearch documents and
  active Neo4j graph, then rolls back database rows and deletes external test
  artifacts. It fails when the configured services are unavailable; it does not
  downgrade to deterministic stubs.
- `integration:milestone8b-live`: runs the Milestone 8B live RAG acceptance
  smoke against real Development PostgreSQL, OpenSearch and Neo4j plus a local
  OpenAI-compatible acceptance provider. The command publishes a controlled
  temporary fixture, starts a temporary Celery worker against the configured
  Redis broker, dispatches the validation outbox event, verifies persisted
  citations, chat record metadata, provider token usage and Judge scoring, then
  deletes the temporary database rows, OpenSearch index and Neo4j graph nodes.
- `migration:live`: creates disposable PostgreSQL databases and runs the real
  Flyway Docker image to prove fresh installation, V022 upgrade, no-op rerun,
  checksum rejection and transactional failed-migration rollback, then removes
  the disposable databases.
- `coverage:check`: validates machine-readable frontend and backend coverage
  reports against the 80% threshold. Both reports are required.
- `coverage:selftest`: proves source/diff fingerprints, suite manifests,
  timestamps and report hashes reject stale or focused-only coverage evidence.
- `test:security-simplification`: verifies CHG-260 mounted Kubernetes/Docker
  Secret references, direct canonical upload ingestion, removed scanner
  services and the Keycloak password-only theme contract.
- `security:dependencies`: audits locked production dependencies with
  `npm audit --omit=dev` and an exported `backend/uv.lock` through `pip-audit`.
  The command requires registry/advisory network access and fails on reported
  vulnerabilities.
- `security:static`: runs Bandit against `backend/app` and fails on findings
  that are both high confidence and high severity.
- `security:images`: builds the production Backend and Frontend images used by
  the container evidence commands.
- `security:containers`: scans both locally built images with Docker Scout and
  fails on critical or high findings.
- `security:sbom`: writes SPDX JSON bills of materials for both images under
  `test-results/security/` and fails if either artifact is empty.
- `docker:config`: validates root-level Docker Compose syntax. Requires Docker
  Compose and `docker-compose.yml`.
- `helm:lint`: validates the Helm chart. Requires Helm and
  `deploy/helm/nomosmart/Chart.yaml`.
- `deploy:doctor`: checks whether the expected Docker Compose and Helm deployment
  entry points exist.
- `deploy:config-policy`: checks whether deployment configuration is externalized
  through the expected Docker env file template and Helm ConfigMap/Secret
  templates.
- `governance:selftest`: runs isolated positive and negative fixtures proving
  active-change approval passes while pending Gate 4, historical approval reuse,
  and missing active trace references fail.

## Deployment Contract

The rewritten system is not complete until it can be deployed in both modes:

- Docker Compose: root-level `docker-compose.yml` for local or single-host
  deployment, with app services, required dependencies, health checks, named
  volumes, and environment-driven configuration. Compose deployments must use an
  independent config file template at `deploy/docker/nomosmart.env.example` and
  an uncommitted operator-owned env file such as `deploy/docker/nomosmart.env`.
- Helm/Kubernetes: chart at `deploy/helm/nomosmart/`, with values-driven image
  settings, services, ingress support, config maps, secret references, probes,
  resources, and persistent storage where needed. Non-sensitive configuration
  must be represented as ConfigMaps. Sensitive configuration such as database
  credentials, API keys, access tokens, OIDC client secrets, encryption keys, and
  private connection strings must be represented as Kubernetes Secrets or
  external/encrypted secret references.

Configuration must be independent from application source and container images.
Do not hard-code deployment parameters in source code, Dockerfiles, Compose
files, Helm templates, or committed values files except for safe local defaults
and placeholder examples.

Production deployment checks should also cover health/readiness probes,
structured logging, migration and rollback instructions, backup/restore notes,
release notes, and vulnerability/SBOM tooling once those artifacts exist.

## Test Contract

The rewritten system is not complete until automated coverage reaches at least
80%. Maintain the full testing strategy in `TEST_PLAN.md`.

Expected coverage report locations:

- Frontend: `frontend/coverage/coverage-summary.json`.
- Backend: `backend/coverage.json`.

Run:

```bash
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh test:e2e
./HARNESS/harness.sh coverage:check
```

Critical workflows require explicit tests even when total coverage already meets
80%: authentication, authorization, permission matrix, review workflow, import
pipeline, configuration loading, secret handling, migrations, and rollback paths.
These tests must satisfy `TEST-002`: real services and real implementations are
required, and missing prerequisites are blocked/unavailable rather than
mock-passed.

Behavioral test commands run a `TEST-002` policy guard before executing test
suites. The guard fails on obvious test-double patterns such as `MagicMock`,
`MockTransport`, `monkeypatch.setattr`, `class Fake...`, `def fake_...`, mocked
OIDC sessions, and static-smoke E2E artifacts.

CHG-216 removed the legacy mock-heavy backend suite after reference scanning and
live-suite replacement. Mock-heavy tests must not be reintroduced outside the
behavioral path as a way to bypass `TEST-002`.

## Specification Contract

Development is specification-driven. `SPECIFICATION.md` is the product baseline
and must be updated before or alongside any behavior change. The expected flow is:

1. Read and understand the specification.
2. List discussion and confirmation items for the human.
3. Wait for human confirmation of the understanding and open questions.
4. Write `DEVELOPMENT_PLAN.md`.
5. Wait for human approval of the development plan.
6. Map requirement identifiers to implementation and tests.
7. Implement only the approved, specified behavior.
8. Verify through harness commands.
9. Report satisfied spec sections and known gaps.

Implementation and test execution must not begin before the human has approved
the development plan. Use `DEVELOPMENT_PLAN.md` as the planning gate
record.

Specification changes must be recorded in `SPEC_CHANGELOG.md` with
date, change ID, section, reason, impact, compatibility/migration effect, test
impact, and approver.

The first dated row in `SPEC_CHANGELOG.md` is the active change. Its ID must use
`CHG-NNN`, and the same ID must appear in `SPECIFICATION.md`,
`DEVELOPMENT_PLAN.md`, `TEST_PLAN.md`, and `TRACEABILITY.md`. The active plan
must use a level-two heading beginning with that ID so the harness can isolate
its gate status from historical plans.

For the rewrite, maintain a traceability artifact such as
`TRACEABILITY.md` with columns or equivalent fields for:

- Requirement ID.
- Specification section.
- Implementation area.
- Test coverage.
- Harness command.
- Status and notes.

Use these checks:

```bash
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh plan:approved
```

## Definition of Done

A feature or milestone is complete only when:

- Specification and spec changelog are current.
- Human confirmation and plan approval are recorded.
- Traceability maps requirements to implementation, tests, harness command, and
  status.
- Tests pass and coverage is at least 80%.
- Critical workflows have explicit tests.
- Docker Compose and Helm checks pass for deployable milestones.
- Configuration is externalized and secrets are protected.
- Security scans, dependency/container checks, and SBOM generation are run once
  tooling exists.
- Observability, health/readiness, audit logging, backup/restore, migration,
  rollback, and release notes are covered for production-ready milestones.

Deployment checks are opt-in until those artifacts exist. Once the rewrite adds
them, run:

```bash
./HARNESS/harness.sh deploy:doctor
./HARNESS/harness.sh deploy:config-policy
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
```

## External Services

The lightweight default harness does not require PostgreSQL, Neo4j, S3,
OpenSearch, Milvus, or Keycloak. Integration checks that touch those services
are explicit opt-in commands.

Milestone 7 live acceptance:

```bash
./HARNESS/harness.sh integration:milestone7-live
```

Required configuration is read from `backend/.env` or environment variables:
`DATABASE_URL`, `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`,
`OPENSEARCH_PASSWORD`, `OPENSEARCH_VERIFY_TLS`, `OPENSEARCH_INDEX_PREFIX`,
`NEO4J_URI`, `NEO4J_DATABASE`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`.
The command uses random UUIDs and a temporary OpenSearch index prefix, performs
best-effort cleanup, and treats unreachable services as a failed acceptance
check.

Milestone 8B live acceptance:

```bash
./HARNESS/harness.sh integration:milestone8b-live
```

The command reads the same Development service configuration and starts a
temporary local OpenAI-compatible provider on `127.0.0.1`. It does not require a
real external AI API key, but it still exercises the live provider adapter HTTP
path, Redis-backed outbox dispatch, Celery worker execution, persisted chat
evidence, Judge scoring, OpenSearch retrieval and cleanup behavior.

## Exit Contract

- Exit code `0`: requested checks passed.
- Non-zero exit code: at least one requested check failed.
- The harness prints each command before running it so failures can be copied and
  rerun directly.

## Adding Checks

When adding a new check:

- Keep the command deterministic and runnable from the repository root.
- Prefer checks that do not need network access.
- Do not mutate source data unless the command name clearly says it is a fixer or
  migration.
- Add service-dependent checks as opt-in commands, not part of `all`, unless the
  check is deterministic and does not require live external services.
- Keep Docker Compose and Helm validation commands available as stable entry
  points even while the underlying deployment artifacts evolve.
- Keep test and coverage validation commands available as stable entry points
  even while test frameworks evolve.
- Keep specification and traceability validation commands available as stable
  entry points; spec-driven checks should become stricter as the rewrite matures.
- Update this file and `AGENTS.md` if the new check becomes part of the expected
  agent workflow.


### CHG-313 Docker workflow

`docker:workflow` runs the approved live acceptance against a generated, owned
`nomosmart-chg313-*` temporary checkout. Set `CHG313_ISOLATED=1`,
`CHG313_LIVE_ROOT` and `CHG313_LIVE_REPORT`; missing inputs are BLOCKED, not PASS.
The runner uses real Docker/TLS/PostgreSQL/S3/OpenSearch/Neo4j, checks repeats,
conflicts, locking, interrupt and persistent markers. It preserves state after
failure and does not clean unrelated resources. Create/start the owned installation
through `./nomosmart up` first; verify the separate live Browser OIDC case and
perform exact-ID cleanup afterward. This focused gate does not replace full
Frontend/Backend 80% coverage or release-package verification.

## CHG-335 formal E2E environment

The approved current-source coordinator is `backend/.venv/bin/python -B backend/scripts/e2e_environment.py run --scope authentication|focused|frontend|full|all`. Each scope uses fresh actual PostgreSQL/Keycloak, public source copies, real PKCE and in-memory credentials, and exact teardown; it invokes the unchanged canonical `test:e2e`/`test:frontend` entrypoints with a bound disposable root. See `docs/E2E-ENVIRONMENT-GUIDE.md`. Authentication-only PASS carries full_acceptance=false. Full missing genuine generation/creation/workflow receipts remains BLOCKED/exit2; failures/coverage/cleanup remain exit1. Legacy listed E2E password environment inputs are operator compatibility only; the coordinator never writes passwords, JWTs or cookies to files. LDAP federation and paid generation-to-publication acceptance are not covered by this no-Provider scope.

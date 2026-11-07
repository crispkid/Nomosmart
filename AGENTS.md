# AGENTS.md

This file defines how coding agents should work in the NomoSmart repository.

## Project Context

NomoSmart is an enterprise knowledge management platform. It ingests documents,
data services, and structured database sources into knowledge chunks, knowledge
graphs, search indexes, review workflows, reports, and chat verification.

The current repository is a monorepo:

- `frontend/`: Next.js App Router, React, TypeScript, i18n, Recharts, lucide-react.
- `backend/`: FastAPI, SQLAlchemy, Pydantic, PostgreSQL, Neo4j, S3, OpenSearch.
- `sql/`: PostgreSQL schema and sample/reset SQL.
- `SPECIFICATION.md`: Product and acceptance baseline. Treat this as the source
  of truth when README and code disagree.

## Working Rules

- Work in a specification-driven way. The specification leads design,
  implementation, tests, deployment, and acceptance.
- Keep changes scoped to the requested feature or fix.
- Read `SPECIFICATION.md` before changing product behavior, permissions,
  authentication, review workflow, imports, knowledge extraction, reports, or
  system management.
- Do not implement product behavior that is not described in `SPECIFICATION.md`
  or an approved companion specification. If the request changes behavior, update
  the specification first or in the same change.
- Every meaningful implementation change must be traceable from requirement to
  design decision, code, tests, and verification result.
- Record meaningful specification changes in `SPEC_CHANGELOG.md`
  before implementation starts.
- Prefer existing local patterns over new abstractions.
- Do not modify generated or dependency folders: `frontend/node_modules/`,
  `frontend/.next/`, `backend/venv/`, `__pycache__/`, and build artifacts.
- Do not commit secrets. Existing hard-coded local development values in
  `backend/connection.py` should not be copied into new files.
- Preserve Traditional Chinese and English i18n coverage for user-facing
  frontend text. Update both `frontend/src/i18n/locales/zh.json` and
  `frontend/src/i18n/locales/en.json` when adding strings.
- Use lucide-react icons for frontend controls when a matching icon exists.
- Keep operational UI dense, predictable, and work-focused. Avoid marketing-page
  layouts for application screens.
- For destructive actions, soft delete or deactivate unless the specification
  explicitly requires permanent deletion.

## Specification-Driven Workflow

All development follows this loop:

1. Specification: define or update the behavior in `SPECIFICATION.md` before
   implementation. Include user role, scenario, business rules, data contract,
   states, errors, permissions, and acceptance criteria.
2. Understanding: after reading the specification, summarize your understanding
   and list every item that needs discussion or confirmation. Do not write a
   development plan until the human confirms this understanding.
3. Human confirmation: ask the human to resolve blocking questions, ambiguity,
   conflicts, scope decisions, UX choices, data/API questions, deployment
   assumptions, and testability concerns.
4. Development plan: only after human confirmation, write or update
   `DEVELOPMENT_PLAN.md` with scope, approach, task breakdown,
   test strategy, deployment/config impact, risks, and verification commands.
5. Plan approval: do not implement or run feature tests until the human approves
   the development plan.
6. Traceability: record the relationship between requirement, implementation,
   tests, deployment/config changes, and verification. For the rewrite, maintain
   a traceability matrix such as `TRACEABILITY.md` or an equivalent
   structured artifact.
7. Test design: update `TEST_PLAN.md` or feature-specific test notes
   so the expected test level is clear before or alongside implementation.
8. Implementation: build only what the specification describes. When code and
   spec disagree, treat the spec as the decision point and update it explicitly
   if the intended behavior changed.
9. Verification: run the narrowest harness checks that prove the requirement,
   then run broader checks before handoff.
10. Acceptance: report which specification sections were satisfied, which harness
   commands were run, and any known gaps.

Planning gates:

- Gate 1: specification understanding and discussion list completed.
- Gate 2: human confirms the understanding and resolves blocking questions.
- Gate 3: development plan is written in `DEVELOPMENT_PLAN.md`.
- Gate 4: human approves the development plan.
- Gate 5: implementation and testing may start.

Agents must stop before Gate 2 or Gate 4 when human approval is missing. In that
case, provide the understanding summary, questions, or plan and wait for
approval instead of continuing into implementation.

Specification requirements:

- Each feature should have stable requirement identifiers where practical, for
  example `AUTH-001`, `PROJECT-003`, `IMPORT-002`, `DEPLOY-001`, or
  `TEST-001`.
- Requirements should be testable. Avoid vague wording that cannot be verified.
- Acceptance criteria should use concrete Given/When/Then or equivalent
  observable conditions.
- API, data model, UI state, permission, deployment, and configuration behavior
  must be specified before implementation.
- Non-functional requirements such as performance, security, observability,
  availability, backup/restore, i18n, accessibility, and browser support should
  be captured when relevant.
- If a design decision is made during implementation, add it to the spec or a
  linked decision record before relying on it.

Specification change management:

- Record each behavior-affecting specification change in
  `SPEC_CHANGELOG.md`.
- Each change record should include date, change ID, spec section, reason,
  impact, compatibility or migration effect, test impact, and approver.
- If a specification change affects API contracts, database schema, security,
  permissions, deployment, or configuration, update the development plan and
  traceability matrix before implementation.
- Do not treat code as the source of truth. When implementation reveals a spec
  gap, stop and update the spec/change record first.

Spec-driven handoff checklist:

- `SPECIFICATION.md` is updated or confirmed unchanged.
- `SPEC_CHANGELOG.md` is updated for behavior-affecting spec changes.
- `DEVELOPMENT_PLAN.md` includes the approved plan for the work.
- `TEST_PLAN.md` is updated or confirmed unchanged.
- Requirement-to-test traceability is updated for new or changed behavior.
- Definition of Done is satisfied.
- Harness checks include `spec:doctor`, `spec:trace`, `plan:approved`, plus the
  relevant test/deploy/security checks.
- Final response references the spec area and verification commands.

## Definition of Done

A feature, rewrite milestone, or release is not done until all relevant items are
true:

- Specification is updated, reviewed, and traceable to requirement IDs.
- Discussion items are resolved or explicitly accepted by the human.
- `DEVELOPMENT_PLAN.md` is approved by a human for the current scope.
- `TRACEABILITY.md` maps requirements to implementation, tests,
  harness commands, and status.
- All applicable current critical scenarios have valid passing evidence. Frontend
  and backend coverage must be measured from complete sources; 80% is an advisory
  improvement target, not a standalone release blocker (CHG-419 / RISKREL-001..008).
- Critical flows have explicit tests regardless of aggregate coverage: authentication, authorization, permission matrix, review workflow,
  import pipeline, configuration loading, secret handling, and migrations.
- Docker Compose and Helm deployment checks pass for deployable milestones.
- Runtime configuration is externalized and secrets are not committed.
- Security checks for dependencies, containers, and static analysis are run once
  tooling exists; high or critical findings are resolved or formally accepted.
- Observability and operations requirements are satisfied for production-ready
  milestones.
- Known gaps, skipped tests, and operational risks are documented with owner and
  follow-up.

## Frontend Guidance

- App routes live under `frontend/src/app`.
- Shared UI components live under `frontend/src/components`.
- Global styling lives in `frontend/src/app/globals.css`; follow existing class
  naming and layout conventions.
- Keep route pages thin when possible; place reusable behavior in components.
- Use TypeScript types for API payloads and UI state.
- Do not introduce a new styling framework unless explicitly requested.
- Validate responsive behavior for dashboard, modal, table, graph, and wizard
  views when changing layout.

## UI/UX Design Style

Use the provided reference image as the visual direction for NomoSmart: a clean,
trustworthy enterprise dashboard with a soft financial-service feel. The product
should look calm, precise, and operational rather than decorative or playful.

Visual language:

- Overall mood: light, airy, quiet, professional, and reliable.
- Layout: left navigation plus dense dashboard content, with clear top-level
  navigation, compact cards, data tables, modals, and workflow panels.
- Surfaces: Cloud White backgrounds with subtle Cool Gray borders, low shadows,
  and 8px or smaller border radius for cards and controls.
- Spacing: generous page gutters, consistent card padding, compact internal
  spacing for repeated operational data, and clear section separation without
  nesting cards inside cards.
- Illustration: use soft mint/green contextual illustrations sparingly for empty
  states, banners, or onboarding surfaces. Main work screens should prioritize
  real data and controls.

Color palette:

- Fresh Mint `#EAF7F1`: page tint, soft backgrounds, empty states, subtle bands.
- Soft Sage `#BFDCCE`: secondary fills, selected rows, quiet icon backgrounds.
- Calm Green `#5FAE88`: primary actions, active states, charts, positive values.
- Deep Action Green `#2F7D57`: primary hover, strong emphasis, active nav.
- Soft Coral Alert `#E98B87`: destructive or high-attention states.
- Cloud White `#FCFDFB`: primary app background and cards.
- Cool Gray `#E6EBEF`: borders, dividers, disabled outlines.
- Slate Text `#2E3A42`: primary text and high-contrast UI labels.
- Muted Gold `#D8C77A`: warnings, special highlights, secondary chart accents.

Typography:

- Prefer `Noto Sans TC` for Traditional Chinese UI. Fall back to system sans
  fonts when it is unavailable.
- Use regular, medium, and bold weights only.
- Keep dashboard headings restrained; reserve large display type for true landing
  or welcome areas.
- Use compact labels and numeric hierarchy for data cards: label, supporting
  helper text, then the primary value.

Components:

- Primary buttons use Calm Green fill, white text, and Deep Action Green hover.
- Secondary buttons use white or Cloud White fill with green border and green
  text.
- Text buttons use green text with a chevron or relevant lucide icon where
  action direction matters.
- Destructive actions use Soft Coral Alert and should include a trash/delete icon
  when space allows.
- Disabled controls use Cool Gray borders/fills and muted text; disabled primary
  buttons should not look clickable.
- Inputs must define normal, focus, error, success, and disabled states. Focus
  uses Calm Green; errors use Soft Coral Alert; success uses Calm Green with a
  check icon where useful.
- Dropdowns, checkboxes, radio buttons, and segmented controls should match the
  same green focus/selected states.
- Notifications use compact stacked rows with icon, title, description, date,
  and a clear status color.
- Charts should use Calm Green as the main series, Soft Sage as secondary series,
  and Muted Gold only for highlight or warning series.

Interaction:

- Prefer clear icon+text actions for business workflows such as import, approve,
  connect, search, verify, export, and delete.
- Hover states should be visible but subtle: slight shade change, border
  emphasis, or low shadow lift.
- Active navigation uses Deep Action Green text/icon and a thin underline or left
  indicator.
- Avoid flashy animation. Use short transitions for hover, focus, modal open,
  and row expansion only.

Accessibility and responsive behavior:

- Maintain sufficient contrast between Slate Text and light backgrounds.
- Do not communicate status by color alone; pair color with text and/or icons.
- Keep touch targets at least 40px high on mobile.
- Tables and dashboards should remain scannable on narrow screens through
  stacking, horizontal scroll, or dedicated mobile summaries.

## Backend Guidance

- FastAPI entry point: `backend/main.py`.
- SQLAlchemy models: `backend/models.py`.
- Database and external service clients: `backend/connection.py`.
- Keep API authorization checks on the backend, even when the frontend hides UI.
- Formal identity follows PROTAUTH-001..012: choose generic OIDC or direct
  LDAP/Windows AD authentication, with shared server sessions and direct directory
  synchronization. Keycloak is an optional OIDC implementation, never a required
  Admin API or directory intermediary. Legacy identity headers and external Bearer
  tokens must not establish an application session.
- Permission semantics:
  - `view` gates entry and read operations.
  - `create` does not imply `edit`.
  - `edit` does not imply `delete`.
  - Users can have multiple roles; effective permissions are the union.
  - Project Owner is a project-scope governance relationship, not a replacement
    for role permissions.
- Avoid importing `backend/main.py` in lightweight validation unless a database
  is available; module import creates tables through SQLAlchemy.

## Data and Integration Guidance

- Schema changes belong in `sql/nomosmart.sql` or a future migration mechanism.
- Keep `sql/sample.sql` aligned with schema additions when sample data is useful
  for local validation.
- Static hygiene checks may avoid Milvus, Neo4j, S3, OpenSearch, PostgreSQL, or
  Keycloak when they do not verify runtime behavior. Product behavior tests,
  integration checks, E2E checks, coverage gates, and release acceptance must
  use real configured services and report blocked/unavailable when prerequisites
  are absent.
- When adding integration behavior, document required environment variables,
  ports, and local service assumptions.

## Testing Target

The current release uses the approved CHG-419 risk-based quality policy. All
applicable critical normal, denial, error and data-preservation scenarios need
valid evidence. Coverage measurement is required; 80% is an advisory improvement
target. Missing or failed critical behavior and unknown risks still block readiness.
Frozen historical v4 package contracts retain their strict full-suite/80% meaning.

- Maintain the test plan in `TEST_PLAN.md`.
- Measure frontend and backend coverage separately against complete source
  denominators. Report the 80% improvement target separately from functional and
  release-readiness status; do not infer hits or omit untouched files.
- Coverage must be generated by automated tools and checked through the harness.
- Include unit, component, API, integration, end-to-end, deployment, and
  configuration/security-sensitive tests.
- Follow `TEST-002` live-only verification. Do not use mocks, stubs, fakes,
  fixture adapters, deterministic adapters, or hard-coded success paths as
  passing test behavior. Use isolated development/test services, disposable
  schemas, buckets, indexes, realms, namespaces, and cleanup instead of
  production credentials or production data.
- Do not delete tests, shrink denominators, infer hits or relabel old results to
  obtain a pass. Record coverage improvement gaps with a reason, owner and follow-up.
  Approved policy changes must update specification, tools and versioned contracts
  together; unknown or unreviewed scope must never silently become low risk.
- New features must include tests at the lowest useful level plus broader tests
  when the change affects cross-module behavior or user workflows.
- Critical-flow tests are mandatory for authentication, authorization,
  permission matrix behavior, review approvals, data import, configuration
  loading, secret handling, migrations, and rollback-sensitive changes.
- The 80% improvement target never replaces critical-flow verification. Preserve
  valid existing evidence and rerun only affected or genuinely missing scenarios.
  A valid measurement alone is neither a full-suite pass nor release readiness.

## Security and Operations Target

Production-oriented milestones must include explicit security and operations
coverage:

- Authentication and authorization tests must cover OIDC/JWT validation,
  disabled users, missing roles, permission unions, project owner rules, and
  denied destructive actions.
- Add dependency scanning, static analysis, container image scanning, and SBOM
  generation once tooling is selected.
- Do not ship high or critical security findings without a documented human
  risk acceptance.
- Use structured logging for backend services and avoid logging secrets,
  credentials, tokens, or sensitive document content.
- Provide health and readiness endpoints for runtime services and wire them into
  Docker Compose health checks and Kubernetes probes.
- Define audit logs for security-sensitive and governance-sensitive actions,
  including login, permission changes, imports, approvals, rejections, deletes,
  model/config changes, and deployment-impacting settings.
- Define metrics and operational dashboards for request latency, error rate,
  import pipeline status, job failures, queue depth where applicable, and storage
  or index connectivity.
- Document migration, rollback, backup, restore, log inspection, and release
  note expectations for deployable milestones.

## Deployment Target

The final rewritten system must be deployable through both Docker Compose and
Helm on Kubernetes. Treat this as a delivery requirement, not an optional
packaging task.

Configuration isolation expectations:

- All runtime parameters and settings must be externalized from application code,
  container images, and deployment templates.
- Application code must read configuration from environment variables or mounted
  configuration files through a typed configuration layer.
- Do not hard-code hostnames, ports, credentials, API keys, model names, storage
  buckets, feature flags, CORS origins, auth issuers, or service URLs in source
  code.
- Commit only safe example configuration. Do not commit real secrets, production
  endpoints, production tokens, or private keys.
- Keep non-sensitive settings separate from sensitive settings so operators can
  rotate secrets without changing general configuration.

Docker Compose expectations:

- Provide a root-level `docker-compose.yml` for local or single-host deployment.
- Provide an independent Docker deployment config file template at
  `deploy/docker/nomosmart.env.example`.
- Local Docker deployments should use an uncommitted config file such as
  `deploy/docker/nomosmart.env`, referenced through Compose `env_file`.
- Include build/run definitions for frontend, backend, database, and required
  supporting services.
- Keep service configuration environment-driven. Do not bake secrets into images,
  Dockerfiles, or compose files.
- Use named volumes for stateful local services and clear health checks for
  services that other containers depend on.
- Document local startup, shutdown, migration/seed, and log inspection commands.

Container image expectations:

- Each runnable application service must have a production-oriented Dockerfile.
- Images should run as non-root where practical.
- Build outputs should be deterministic and should not depend on local
  `node_modules`, Python `venv`, or machine-specific files.
- Runtime configuration should come from environment variables, mounted secrets,
  or Kubernetes Secret/ConfigMap values.

Helm/Kubernetes expectations:

- Provide a Helm chart under `deploy/helm/nomosmart/`.
- The chart must support Kubernetes deployment of frontend, backend, ingress,
  service accounts, config maps, secrets references, service definitions,
  probes, resource requests/limits, and persistent storage where needed.
- Non-sensitive runtime parameters must be rendered through Kubernetes
  ConfigMaps.
- Sensitive runtime parameters, including database connection passwords, access
  keys, API keys, JWT/OIDC client secrets, encryption keys, and private tokens,
  must be rendered through Kubernetes Secrets or referenced from an external
  secret system.
- Keep environment-specific settings in values files, for example
  `values.yaml`, `values-dev.yaml`, and `values-prod.yaml`.
- Do not commit real secrets in Helm values. Use placeholder examples,
  Kubernetes Secret references, ExternalSecret references, SealedSecret, SOPS, or
  an equivalent encrypted-secret workflow.
- Secret manifests, if committed, must contain placeholders or encrypted data
  only. Plaintext production credentials are never acceptable.
- Templates must support image repository/tag overrides and pull policy.
- Define readiness and liveness probes for app workloads.
- Include notes or documentation for install, upgrade, rollback, and uninstall.

Deployment verification:

- Use `./HARNESS/harness.sh docker:config` to validate Docker Compose syntax
  once compose files exist.
- Use `./HARNESS/harness.sh helm:lint` to validate the Helm chart once chart
  files exist.
- Use `./HARNESS/harness.sh deploy:config-policy` to check for the expected
  Docker config file template and Helm ConfigMap/Secret templates once deployment
  artifacts exist.
- Before considering a rewrite complete, run the relevant frontend/backend checks
  plus Docker Compose and Helm checks, and report any check that requires an
  unavailable local tool or service.

## Verification

Use the harness from the repository root:

```bash
./HARNESS/harness.sh
```

The default harness runs specification, repository, and backend smoke checks.
Run focused frontend, test, deployment, and traceability checks when the change
touches those areas.

Useful focused checks:

```bash
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:doctor
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh frontend:lint
./HARNESS/harness.sh frontend:build
./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh test:frontend
./HARNESS/harness.sh test:backend
./HARNESS/harness.sh test:e2e
./HARNESS/harness.sh coverage:check
./HARNESS/harness.sh docker:config
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:config-policy
```

Run the narrowest check that covers your change before handing work back. If a
check cannot run because a service or dependency is missing, report that clearly
with the exact command attempted.

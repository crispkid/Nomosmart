# CHG-292 Canonical Tag Graph Synchronization And Consistency

Verification date: 2026-09-09. Requirements: `SPECIFICATION.md` section 10.49,
GRAPH-009 through GRAPH-013. Peter approved the implementation plan with
`Peter approves CHG-292 Canonical Tag Graph Synchronization And Consistency`.

Status: repository implementation and focused isolated verification completed;
full release acceptance remains open. No current-environment graph inventory,
repair, image build, deployment or Provider request was performed. This report
does not approve or execute CHG-291 migration Stage B.

## Behavior delivered

PostgreSQL remains canonical for Tag UUIDs and document/chunk assignments.
Candidate previews are built from that evidence without writing formal Neo4j.
Published graph projection contains the existing Project/Document/Version/Chunk
structure and actual `VERSION_HAS_TAG` / `CHUNK_HAS_TAG` assignments.

- One project-local Tag UUID is shared by its genuine assignments. Equal names
  in different Projects do not merge. Document tags are not copied to chunks.
- Per-assignment source, timestamp, confidence and allowlisted model/prompt
  references are graph-edge metadata. No document body, arbitrary Provider
  metadata, credentials or new operational graph node types are projected.
- Publication, durable retry/resync and active-version switch use the same
  canonical builder and transactionally verified graph writer. Project locks,
  fresh ORM reads, source revisions, generation and digests fence stale work.
- Reconciliation preserves historical nodes, shared tags and unknown edges;
  only obsolete scoped managed tag edges can be removed. It does not call the
  existing destructive version cleanup. Duplicate IDs or uncertain ownership
  stop the operation instead of triggering automatic cleanup.
- A completion receipt follows actual node/edge/metadata read-back. A failed
  publication rolls back tentative PostgreSQL serving state and persists only
  failed-job/audit/notification evidence. A graph commit before the local receipt
  is recovered by idempotent retry; this is not a distributed atomic transaction.
- Candidate tag edits refresh preview/revision without embedding or indexing.
  Review locks remain, and previously published tags reject direct mutation with
  `published_tag_revision_required` (409). They require the existing revision and
  review workflow, not automatic publication.
- Published Project/Version graph, neighbors and paths read actual Neo4j edges.
  Authorized PostgreSQL content hydration is retained but cannot invent missing
  graph relationships. Incomplete projection returns `graph_projection_not_ready`
  (503); ownership conflicts return a safe 409. Candidate preview still works.
- Serving status verifies current graph evidence rather than trusting a past
  completed job. Existing Chat gating uses `index_ready` and remains unchanged.
  No GraphRAG, LlamaIndex, query rewrite, reranking or answer-generation change
  is included. An improved data foundation alone does not improve current answers.

## Changed code and data contracts

| Files | Main responsibilities |
| --- | --- |
| `backend/app/domain/graph_projection.py` | `GraphProjection`, canonical digest, `build_graph_projection`, UUID-based `preview_artifact`, safe graph differences. |
| `backend/app/domain/graph_reconciliation.py` | `Neo4jProjectionStore`, actual scoped reads, transaction reconciliation, `locked_projection`, `synchronize_graph`. |
| `backend/app/domain/review_publish.py` | Complete publication adapter, rollback/failure receipt, fresh publication and switch locks. |
| `backend/app/domain/graph_sync_jobs.py` | Bound durable jobs, lease checks, consistent lock order, stale-work rejection, truthful receipts and existing failure notifications. |
| `backend/app/domain/chunk_artifacts.py`, `extraction_pipeline.py` | Canonical candidate preview; remove candidate Neo4j writes and synthetic formal success. Existing content rebuild/index semantics retained. |
| `backend/app/api/routes/documents.py` | `_ensure_tag_mutable`, `_refresh_tag_preview`, readonly reason; manual and automatic tag endpoints guarded before generation. |
| `backend/app/api/routes/serving.py` | Actual graph evidence and status, scoped preview/formal distinction, content hydration and truncation propagation. |
| `backend/app/api/schemas.py`, `frontend/src/lib/api.ts` | Additive optional tag edit reason and graph-edge provenance metadata. |
| `backend/scripts/chg292_graph_tag_reconcile.py` | Explicitly scoped compare/apply, environment/source/target binding, safe output and audit. |
| `frontend/src/components/VersionGraphPreview.tsx`, `frontend/src/lib/versionGraphEvidence.ts` | Document graph consumes scoped API evidence, handles safe errors, maps only actual assignment edges. |
| `frontend/src/components/ProjectGraphPreview.tsx`, `frontend/src/app/project/[id]/knowledge/[knowledgeId]/page.tsx` | Honest not-ready state and published tag controls; no layout redesign. |
| `frontend/src/i18n/locales/zh.json`, `en.json` | Matching readonly, not-ready and truncation messages. |

No SQL migration, model table change, vector schema or OpenSearch mapping change
is introduced. Existing job/outbox/audit storage is reused. Candidate JSON gains
`graph_tag_revision`; formal Version nodes carry `graph_source_digest` and
`graph_projection_version`; managed edges carry projection ownership/provenance.
Immutable Approval evidence rendering is unchanged.

New tests are `backend/tests/test_chg292_tag_graph_consistency.py` and
`frontend/tests/chg292GraphEvidence.component.test.tsx`. Affected graph, content
hydration, review-lock and Frontend source-contract tests were updated to the
approved endpoint/helper boundaries; assertions were not removed to lower gates.
The updated broad live publication-adapter test was not executed as part of the
full live Backend suite; the new isolated suite exercises actual publication.

## Verification environment and commands

The final 27-test run used disposable PostgreSQL 17.10, Neo4j 5.26.4,
OpenSearch 2.19.6 and Keycloak 26.0.8 on Docker internal network
`chg292-test-20260909`, labelled `nomosmart.change=CHG-292`. Data directories
were ephemeral. It did not connect to the Kubernetes application services.
The existing Backend image supplied only a dependency runtime; current `app`,
`tests`, `scripts` and migrations were mounted read-only. No new image was built.

After verification, all four exact labelled disposable containers and the
internal network were removed; a label-filtered check returned no remaining
test containers/networks. Ephemeral test data was intentionally discarded and
can be recreated by the suite. Existing application services/data were untouched.

The suite creates a random PostgreSQL schema, scoped graph IDs, disposable
Keycloak realms and OpenSearch indexes, and cleans these up. The final run
applied SQL files through V048, excluding V042's CloudNativePG-specific role
grants in vanilla PostgreSQL. It did not require or apply V049. An actual
Neo4j uniqueness constraint in the disposable service forces a partial-write
failure; the transaction leaves no partial graph, then a retry succeeds after
removing that test-only constraint. No fake failure/success adapter is used.

Required test environment variables are `CHG292_DATABASE_URL`,
`CHG292_MIGRATIONS_PATH`, `CHG292_OPENSEARCH_URL`, `CHG292_KEYCLOAK_URL`,
`CHG292_KEYCLOAK_ADMIN`, `CHG292_KEYCLOAK_PASSWORD`, `NEO4J_URI`,
`NEO4J_USERNAME`, `NEO4J_PASSWORD` and `APP_ENV=test`. These must point only
to disposable services with ephemeral credentials; do not reuse application
credentials. The suite defaults to `CHG292_MAX_MIGRATION=48`.

Test command in that isolated runtime:

```bash
python -m unittest -v tests.test_chg292_tag_graph_consistency
```

Final execution used the same unittest loader under branch-enabled `coverage`
with `source=["app"]`; JSON evidence was written to
`/tmp/chg292-evidence.l7tnoh/backend-coverage.json`. This focused coverage is
supplemental, not the full Backend harness receipt.

Affected Backend regressions (no network or current data dependency):

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -c /dev/null --rootdir=. \
  backend/tests/test_chg270_graph_chunk_content_contract.py \
  backend/tests/test_chg283_authorized_display_boundary.py \
  backend/tests/test_chat_scope_and_review_lock.py \
  backend/tests/test_chg276_retrieval_and_citation_compaction.py \
  backend/tests/test_chg205_pipeline_progress_tagging.py
```

This deliberately focused invocation is not a substitute for full coverage or
live API acceptance. The separate new real-service suite supplies API evidence.

| Verification | Result |
| --- | --- |
| New real-service Backend suite | 27/27 pass. Real Keycloak tokens/JWKS, scoped API checks, publication/switch, graph transactions, concurrent sessions, retry and CLI subprocesses. |
| Affected Backend regressions above | 22/22 pass. |
| `./HARNESS/harness.sh test:frontend` | 146/146 contracts and 85/85 components pass; command exits 1 on global coverage thresholds. |
| Frontend graph evidence mapper | 100% measured statements/branches/functions/lines; pure mapping tests, not browser evidence. |
| Three graph Backend modules | Projection 94%, reconciliation 88%, jobs 83%; combined 88% branch-inclusive (rounded). |
| Backend app coverage from focused suite | 28.86% branch-inclusive; full Backend gate not met/proven by this subset. |
| Frontend global coverage | Lines 12.94%, statements 11.75%, branches 9.62%, functions 11.98%; below 80%. |
| `coverage:check` | Exits 1: complete Frontend coverage evidence missing; no waiver or fabricated passing receipt. |
| `spec:doctor`, `spec:trace`, `plan:doctor`, `plan:approved`, `test:plan` | Pass. |
| `backend:syntax`, `frontend:lint`, `frontend:build` | Pass, including TypeScript and optimized build. |
| `i18n:hardcoded`, `i18n:ast` | Pass, including guard tests. |
| `docker:config`, `helm:lint`, `deploy:config-policy` | Pass; static render/config validation only, not runtime deployment. |
| `security:static` | Pass for the harness high-severity/high-confidence filter; no high-severity findings. Lower-severity inventory remains (61 low, 31 medium); not a claim of zero findings. |
| `git diff --check` | Pass. |

Graph-only repair preservation evidence includes a genuinely published version,
nonempty stored vectors, two real OpenSearch documents and an active manifest.
Before/after hashes of canonical/model/build/vector/manifest/usage rows and
OpenSearch documents match. Only scoped graph projection and allowed
GraphSyncJob/audit receipts change. Seeded numeric vectors support this storage
test; no claim of model semantic quality or Provider inference is made.

## Outstanding gates and risks

1. Full Backend live harness was not run: it requires a fully isolated configured
   identity/service/Provider environment. Current `.env` data and credentials
   were not repurposed. Browser E2E, deployed zh/en feedback and readonly-control
   acceptance remain unverified. Automatic tagging generation/full ingestion
   were not run; automatic endpoint rejection before generation was verified.
2. A separately attempted existing approval-evidence test,
   `test_approval_detail_exposes_readonly_knowledge_evidence`, fails because it
   expects `_document_layout(version)` while the unchanged HEAD already calls
   `_document_layout(version, markdown_artifact.text)`. This pre-existing stale
   assertion was not changed as an unrelated fix and is not counted as passing.
3. Full Frontend and Backend 80% coverage gates remain open. Focused success
   does not make the repository release-ready. No threshold was lowered.
4. Existing published graphs may lack canonical tag edges, scope metadata or
   the new receipt. New reads will honestly report not-ready until a separately
   approved inventory and repair/cutover occurs. A graph missing structure or
   having unknown ownership requires an additional reviewed repair, not a
   broader automatic tag repair. No existing graph was inspected in this task.
5. No new Neo4j constraints/indexes are installed by startup. Same-project
   application writers serialize through PostgreSQL locks; manual external
   Neo4j writes still require operational coordination. Whole-scope read-back
   must be profiled on large graphs before production rollout.
6. PostgreSQL, Neo4j and OpenSearch are not one distributed transaction. Failed
   publication does not expose a tentative manifest; externally created index
   artifacts can still need existing operational cleanup. Tag repair never
   performs that unrelated cleanup. Existing explicit archive cleanup is not
   redesigned by this change.
7. Failed-job notification creation and retry resolution were checked against
   real PostgreSQL. End-to-end notification delivery/browser presentation was
   not exercised. General service connection/performance failures remain
   operational risks, not automatically repaired by the tag tool.

## Next separately authorized operations

Update 2026-09-09: Peter subsequently approved read-only MAAS inventory only.
The completed results are in `CHG-292-MAAS-READONLY-INVENTORY-20260909.md`:
there are no published versions or active manifests, so no published tag-repair
target currently qualifies. Existing legacy tag edges belong to a deleted,
unpublished document. No repair, image or deployment has been performed.

For any later inventory beyond the approved MAAS scope, request separate scope
approval. Use current inventory evidence to define compatibility cutover before
immutable image builds, dry-run render and exact-bound deployment. If published
repair targets exist later, apply approval must bind the environment, scope,
source/target digest, permitted changes and preservation baselines. No default
whole-database apply exists.

The operator tool's default command shape is:

```text
python backend/scripts/chg292_graph_tag_reconcile.py
  --environment <development|test|production>
  --project-id <UUID> --document-id <UUID> --version-id <UUID>
```

Only after explicit scoped approval may `--apply`, `--expected-source`,
`--expected-target`, `--expected-environment` and `--reason` be added. Changed
bindings stop the operation; a matching completed graph is a no-op.

Governance note: the five root specification/plan/trace documents are already
ignored by repository rules. They were updated and verified locally; no ignore
rule, index entry or commit was changed. This tracked report retains a reviewable
summary of requirements, decisions, code and actual test evidence.

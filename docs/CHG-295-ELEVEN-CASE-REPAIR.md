# CHG-295 — Eleven broad Backend cases

2026-09-11. Peter authorized the numbered proposed adjustments under existing
approved Stage B. Product specification/permissions/schema unchanged.

| # | Test suffix after `test_live_` | Requirement / test | Required correction | Status |
| --- | --- | --- | --- | --- |
| 1 | system_reports_and_session_drafts | REPORT-014 / T32 | Missing ModelReport deny, exact temporary grant/allow and cleanup | PASS |
| 2 | seeded_document_knowledge_serving_chat_and_notifications | GRAPH-008, API-PAGE-001 / T33 | Published-tag deny plus candidate mutation, explicit chat surface/pages; actual graph synchronization of stored input | Partial; FAIL: chat page lacks has_more |
| 3 | seeded_reference_and_approval_workflows | ACCEPT-REPAIR-002 / T34 | Real prerequisite evidence before positive submit/review; preserve blocked model boundary | BLOCKED prerequisites; pytest FAIL: submission_evidence_not_ready |
| 4 | external_services_and_domain_adapters | AUTH-017, RAG-EMBED-001 / T35 | Real disposable identity and actual parser/normalizer; replace fixed-vector positive index input with required canonical build | Partial; BLOCKED build; pytest FAIL: canonical_embedding_build_required |
| 5 | integration_adapter_embedding_and_switch_edges | RAG-EMBED-001 / T36 | Current secret contract; legacy-switch rejection before retained positive assertions and real build prerequisite | FAIL: legacy switch did not reject invalid retrieval evidence |
| 6 | configuration_identity_worker_and_sync_edges | API-PAGE-001 / T37 | Cursor envelope and current credential errors | Partial; FAIL: identity-sync page lacks has_more |
| 7 | pipeline_execution_and_publish_edge_behaviors | ACCEPT-REPAIR-002 / T38 | Flush controlled state before lock/refresh; legacy rejection followed by actual canonical normalization and exact missing-build guard | PASS (negative publish guards, not successful publication) |
| 8 | serving_and_document_response_helpers | GRAPH-008, MD-DISPLAY-001 / T39 | Canonical preview/dedup/truncation, citation source mapping/used-marker serialization and required lineage input | PASS |
| 9 | extraction_ai_provider_and_publish_helper_edges | RAG-EMBED-001 / T40 | Current secret validation errors; existing parser/helper assertions retained | PASS |
| 10 | approval_project_and_data_source_route_edges | PROJECT-009/012 / T41 | Current domain eligibility; any local view role, no grant/revocation/inactive denial; existing Owner guards; explicit settings | PASS |
| 11 | compatibility_routes_execute_governed_workflows | API-PAGE-001 / T42 | Cursor envelope, current validation run_scope/version IDs and actual graph projection input | Partial; FAIL: pipeline page lacks has_more; later cancellation/graph assertions not reached |

Keep the 529 PASS/11 FAIL historical full-suite evidence. First failures are not
the complete failure set of each long case. Cases must not become PASS merely
by deleting assertions, accepting any error, bypassing permissions or seeding
completed processing/build evidence. Stored inputs may test response/storage
semantics, not successful Provider/ingestion/publication. Genuine model-dependent
acceptance remains blocked until separately authorized. New unrelated product
defects require discussion. Fresh isolated service/data writes only; no current
configuration, credentials, application data, Kubernetes or Provider actions.

## Final focused evidence

`/tmp/chg295-eleven.c8iJuG/eleven-final-r2.xml`: **11 tests, 5 PASS,
6 FAIL, zero setup errors, zero skipped, 10.464 seconds**. The two prerequisite
blocks are FAIL in pytest; they have not been relabeled PASS or silently skipped.
Source/artifact hashes and exact outcomes are in
`docs/CHG-295-ELEVEN-CASE-EVIDENCE.json`.

All eleven original node IDs were rerun together, twice after intermediate
focused iterations. The first combined attempt additionally exposed a missing
explicit chat `scope_mode` in case 2; the final attempt includes the corrected
surface-bound request. Every iteration's XML/log remains private in the run
directory; iteration counts overlap and must not be added as coverage.

No product application source, API/schema, permissions or security checks were
changed in this continuation. Only the broad test file and governance/evidence
documents changed. Existing dirty CHG-293/294/295 implementation was preserved.
No full Backend/Frontend, browser, coverage or deployment acceptance is claimed.
The historical full-suite 529 PASS/11 FAIL and 59.3662% coverage remain historical,
not replaced by this eleven-case denominator.

## Newly confirmed product gaps — discussion required

1. **Cursor metadata missing** (`API-PAGE-001`, specification §7): actual
   `ProjectChatConversationPage`, `IdentitySyncRunPage` and the Pipeline history
   response lack `has_more`. Their current `items/next_cursor` shape is not the
   complete specified contract. The test deliberately retains the boolean and
   next-cursor consistency assertions. Follow-up must audit all cursor pages,
   retain opaque cursor security/scope, and verify empty/final/nonfinal pages.
   Do not remove the assertion or infer the missing field inside the test.
2. **Legacy active-version switch bypass** (`RAG-EMBED-001`, §10.40): the real
   `review_publish.switch_active_version` accepted a second stored version with
   no canonical retrieval representation, a manually stored published build
   status/index name and no genuine canonical vectors. The new required-denial
   assertion fails with `DID NOT RAISE`. Source inspection confirms the path
   checks status/profile/index name/nonempty chunks, then changes the manifest
   without the strict retrieval/build validation used by `publish_version`.
   Follow-up must validate target retrieval/hash/model/dimension/build/index
   evidence before any manifest/job/audit change; preserve compatible genuine
   published-version switching. The original successful-switch assertions are
   retained behind an actual canonical-build prerequisite; they remain unverified.

These product changes exceed this test-contract-only Stage B continuation and
were not implemented. Discuss scope/Gate 2 and obtain plan approval before fixing.
The switch test stayed in a disposable PostgreSQL transaction and rolled back;
a subsequent read-only query found **zero `switch-version.md` rows**.

## Genuine positive preparation still required

- Case 3: the server correctly refuses submission because graph preview,
  pipeline submission readiness and staging index readiness are absent. The
  existing reference operations execute, but positive submit/manager/Owner
  review assertions are not satisfied. Do not set these statuses manually.
- Case 4: a real fresh Keycloak user is created, appears in the real snapshot,
  and is deleted by exact ID in `finally`; normalization/reconciliation checks
  execute against actual services. Raw Chunk input passes through the real
  representation factory. There is no actual matching completed canonical
  embedding build, so positive OpenSearch indexing and later assertions stop.
- A future bounded, separately authorized real-model preparation must produce
  actual embedding/build/index/workflow evidence. No credentials, existing
  document, model endpoint or billing scope is inferred here. Even after the
  two product gaps are fixed, remaining assertions may expose further issues.

## Isolation and verification

- Fresh `/tmp/chg295-eleven.c8iJuG`, internal network
  `chg295-eleven-c8ijug`, six actual dependency services plus a byte-only relay.
  Fresh PostgreSQL schema through V048, fresh Keycloak realm/credentials/TLS,
  real Neo4j/OpenSearch/S3/Redis; no mock response or Provider success adapter.
- Stored SQL input in graph/read/serialization cases is explicitly not proof
  that ingestion or publication ran. Case 2 verifies graph readiness changes
  only after actual scoped Neo4j synchronization and read-back comparison.
- PASS: `./HARNESS/harness.sh spec:doctor`, `spec:trace`, `plan:approved`,
  `test:plan`, `backend:syntax`, and `git diff --check`.
- Cleanup verifies exact container labels, network membership and exclusive
  anonymous-volume ownership. It preserves the four pre-existing loopback
  ingress/LDAP containers and all images. Final counts are in evidence JSON.
- No Kubernetes/Helm writes, new image build, Provider request, current document
  processing, or current application/index/role/membership mutation.

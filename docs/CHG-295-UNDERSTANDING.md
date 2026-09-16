# CHG-295 — Acceptance defect repair: understanding and decisions

Date: 2026-09-11. Status: **Gate 2 confirmed; Gate 3 prepared; Gate 4 approved**.

Peter requested: `依據你的建議開始修復程式，如果有需要討論的議題，請跟我討論`.
Peter subsequently replied `Ok` to the proposed candidate-only deletion,
history/usage retention, nullable-reference detachment and atomic conflict
boundary. This confirms Gate 2, not approval of the newly prepared detailed
development plan, a release-gate waiver, or current-environment changes.

## Confirmed evidence

- The full Backend acceptance result remains 496 passed / 23 failed. E2E failed
  during fixture preparation; both independent 80% coverage gates remain open.
  See `CHG-294-R2-FULL-ACCEPTANCE.md` and its unchanged machine-readable report.
- `SPECIFICATION.md` section 6.4 `CHUNK-002` requires permanent deletion of the
  exact editable candidate Chunk and its owned assignments/vectors/staging
  evidence. `documents.delete_chunk` instead marks it `deleted` and leaves the
  row. This is a product defect, not an obsolete permanent-deletion assertion.
- `PROJECT-013` explicitly retains the existing candidate Chunk contract;
  ordinary document soft deletion does not override it. The CHG-293 focused
  CRUD test incorrectly asserts the retained deleted row and must be corrected.
  The current Git diff does not attribute this route's soft deletion to CHG-293;
  the conflicting CHG-293 test is additional evidence, not proof of origin.
- V034 defines restrictive nullable `chunks.parent_chunk_id` and
  `superseded_by_id` foreign keys. A superseded predecessor can point at the
  active replacement being deleted. Blind `session.delete(chunk)` can fail.
- `AIModelUsageEvent` has restrictive nullable foreign keys to ChatRecord and
  ValidationRunItem. The current staging-evidence cleanup does not account for
  those references. ValidationRunItem also has a restrictive parent-item FK.
  These are code/schema-identified risks, not newly reproduced test failures.
- `CHUNK-003` retains edit history; `USAGE-001` retains accounting evidence.
  The specification does not yet explicitly describe detachment when
  `CHUNK-002` permanently removes a referenced candidate entity.
- E2E directly constructs incomplete retrieval metadata and a completed
  embedding build using a fixed vector. Adding version strings alone would not
  demonstrate real ingestion/embedding success under `TEST-002`.

## Confirmed understanding / decisions

1. Restore permanent deletion only for the exact authorized editable candidate
   Chunk. Preserve raw document artifacts, other Chunks, other versions,
   submitted/published evidence, shared tags and all existing state/permission
   guards. Do not batch-purge historical rows already marked deleted.
2. Preserve prior edit content/hash/evidence and all usage-event rows, token
   totals and costs. Within the same transaction, detach only nullable foreign
   keys that point to entities legitimately deleted by this operation. Preserve
   the removed relationship as safe IDs in bounded audit/metadata, not copied
   content. Do not invent replacement IDs or change historical financial data.
3. Restrict lineage/evidence detachment to the same authorized candidate scope.
   If an out-of-scope/protected reference is encountered, reject the operation
   atomically with a safe conflict; never cascade into another version. Exact
   conflict contract, reference inventory and concurrency tests belong in the
   specification and plan after this decision is confirmed.
4. Correct the remaining failing tests only after mapping each to its current
   approved requirement. Preserve denied authorization, review/readiness and
   secret-reference guards; test real routes/services instead of removed helper
   names or obsolete response shapes. Restore substantive missing runbooks.
5. Repair E2E preparation through real canonical parsing/normalization. Do not
   manufacture a completed embedding build or readiness state. Non-Provider
   cases may proceed only after plan approval; any genuine end-to-end path
   requiring a model call stays blocked pending a separately bounded Provider
   approval. Storage/governance inputs do not certify generation quality.
6. Add meaningful real-service/UI coverage without reducing the independent
   80% thresholds, excluding uncovered application modules, deleting tests,
   substituting fake services or treating coverage work as already complete.

No SQL DDL is presently proposed: the inspected FKs are already nullable. If
safe retention/reference handling proves to require a schema change, stop and
discuss its migration scope before implementation. No legacy-row repair is
included; such work needs a separately approved inventory and exact scope.

## Gate boundary and next action

The retention/detachment/conflict decisions above were confirmed by Peter on
2026-09-11. Specification section 10.52, the changelog, `DEVELOPMENT_PLAN.md`,
test design and traceability now record the proposed implementation precisely.
Peter approved Gate 4 on 2026-09-11 with `Peter approves CHG-295 Candidate Chunk Deletion Integrity And Acceptance Repair`.
Bounded product/test implementation and disposable non-Provider verification may
start. Existing CHG-293/294 changes and reports remain preserved; current-data,
image/deployment and Provider work remain excluded.

## 2026-09-11 partial implementation and new discussion

The scoped deletion repair and focused real-service tests are implemented; full
acceptance is not complete. The latest full Backend result is 529 PASS / 11 FAIL,
with 59.3662% combined coverage. Source-bound details and remaining cases are in
`CHG-295-VERIFICATION.md`. Existing reports and current deployment are untouched.

E2E source review found a separate cleanup-scope hazard before any E2E cleanup
was executed: the helper accepts one project ID but gathers SQL data for all
matching-prefix projects; Neo4j cleanup traverses up to three hops with DETACH
DELETE, and index cleanup deletes a whole index based on a partial profile ID.
This is a source-identified risk, not an observed current-data incident.

Proposed refinement for Peter to confirm: use a per-run exact resource manifest
(project/document/version/role/model IDs, object keys and dedicated index names),
verify ownership and reject shared/unknown dependencies, remove only owned
relationships/nodes and permit idempotent cleanup after partial preparation.
Avoid changing the general maintenance cleanup utility unless separately scoped.
This approval would cover only disposable test preparation/cleanup code and
non-Provider verification, not current data, Provider usage or deployment.
Remaining broad contract/coverage work is still required regardless of this
decision; this discussion does not waive it or convert failed tests to blocked.

### Cleanup scope confirmation

Peter subsequently replied `Ok` to the proposed exact-ID/resource-only cleanup
and shared-data preservation. This confirms additional-scope Gate 2. The new
10.52 ACCEPT-CLEAN-001..004 requirements, detailed
`CHG-295-E2E-CLEANUP-PLAN.md`, tests and trace are now prepared (Gate 3).
Detailed-plan Gate 4 is pending; no cleanup implementation, feature test,
resource creation/deletion or Provider/deployment action was performed in this
planning continuation. Original CHG-295 approved work/results remain intact.

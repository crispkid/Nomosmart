"""Bounded maintenance of obsolete outputs under a retained soft-deleted parent.

This does not restore a document or make its old content-update job successful.
Provider, secret-resolution, S3-delete and graph-delete operations are absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import Text, cast, delete, or_, select, text

from app.core.errors import AppError
from app.db import models as m
from app.domain.content_pipeline_evidence import BODY_KEYS, DERIVED_BODY_STEPS
from app.domain.content_update_cleanup import delete_retired_index, require_unprotected_version, verify_committed_candidate
from app.domain.document_content_updates import can_edit_content
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name
from app.domain.index_residue import check_index_references, discover_indices, known_index_names, verify_external_owner
from app.security.context import resolve_identity_context
from app.security.permissions import require_application_access
from app.services.audit import add_audit

KEY = "soft_deleted_residue_cleanup_v1"
MAX_BYTES = 256 * 1024
BATCH = 200
LEASE_SECONDS = 120
ACTIVE = {"queued", "running", "processing", "blocked"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def row_value(row):
    return {col.name: getattr(row, row.__mapper__.get_property_by_column(col).key) for col in row.__table__.columns}


def rows_digest(rows):
    return digest(sorted((digest(row_value(row)) for row in rows)))


def reject(code="soft_residue_protected", status=409):
    raise AppError(code, "Maintenance scope, retained evidence or ownership cannot be verified", status_code=status)


@dataclass(frozen=True)
class Scope:
    project_id: UUID
    document_id: UUID
    version_id: UUID
    document_lock: int
    version_lock: int
    generation: int
    revision: int
    canonical_sha256: str

    def json(self):
        return {name: str(value) if isinstance(value, UUID) else value for name, value in self.__dict__.items()}

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            reject("soft_residue_invalid_scope", 422)
        data = dict(value)
        try:
            for key in ("project_id", "document_id", "version_id"):
                data[key] = UUID(data[key])
            for key in ("document_lock", "version_lock", "generation", "revision"):
                if type(data[key]) is not int or data[key] < 1:
                    reject("soft_residue_invalid_scope", 422)
            if len(data["canonical_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in data["canonical_sha256"]):
                reject("soft_residue_invalid_scope", 422)
        except (ValueError, TypeError, KeyError):
            reject("soft_residue_invalid_scope", 422)
        return cls(**data)


def locked_scope(session, scope, context):
    """All maintenance writes use the same parent lock order as governance."""
    project = session.scalar(select(m.Project).where(m.Project.id == scope.project_id)
        .with_for_update().execution_options(populate_existing=True))
    document = session.scalar(select(m.Document).where(m.Document.id == scope.document_id)
        .with_for_update().execution_options(populate_existing=True))
    version = session.scalar(select(m.DocumentVersion).where(m.DocumentVersion.id == scope.version_id)
        .with_for_update().execution_options(populate_existing=True))
    authorize(session, scope, context)
    if (project is None or document is None or version is None or project.status != "active"
        or document.project_id != project.id or version.project_id != project.id or version.document_id != document.id
        or not document.is_deleted or document.status != "deleted" or project.work_generation != scope.generation
        or document.lock_version != scope.document_lock or version.lock_version != scope.version_lock):
        reject("soft_residue_stale")
    require_unprotected_version(session, version)
    return project, document, version


def authorize(session, scope, context):
    # Re-resolve grants and membership, including revocation/disablement, each batch.
    fresh = resolve_identity_context(session, context.principal)
    require_application_access(fresh.grants)
    if (fresh.user_id != context.user_id or fresh.principal.expires_at <= datetime.now(UTC)
        or scope.project_id not in fresh.visible_project_ids or not can_edit_content(session, scope.project_id, fresh.user_id)):
        reject("soft_residue_permission_denied", 403)


def check_chunk_fks(session):
    """A new CASCADE or unknown referencing table must stop retirement."""
    allowed = {("chunks", "parent_chunk_id"), ("chunks", "superseded_by_id"),
        ("chunk_tags", "chunk_id"), ("embedding_build_vectors", "chunk_id")}
    actual = session.execute(text("""
        SELECT src.relname, a.attname, cardinality(c.conkey) AS width,
               src.relnamespace=dst.relnamespace AS same_namespace, da.attname AS dest
        FROM pg_constraint c JOIN pg_class src ON src.oid=c.conrelid
        JOIN pg_class dst ON dst.oid=c.confrelid JOIN pg_namespace ns ON ns.oid=dst.relnamespace
        JOIN pg_attribute a ON a.attrelid=src.oid AND a.attnum=ANY(c.conkey)
        JOIN pg_attribute da ON da.attrelid=dst.oid AND da.attnum=ANY(c.confkey)
        WHERE c.contype='f' AND ns.nspname=ANY(current_schemas(false)) AND dst.relname IN ('chunks','embedding_build_vectors')
    """)).all()
    if not actual or any((r[0], r[1]) not in allowed or r.width != 1 or not r.same_namespace or r.dest != "id" for r in actual):
        reject("soft_residue_unknown_reference")


def reference_inventory(session, scope, identities):
    """Conservatively refuse referenced history; never copy questions or answers."""
    check_chunk_fks(session)
    tokens = sorted(set(map(str, (scope.document_id, scope.version_id, *identities))))
    if len(tokens) > BATCH:
        reject("soft_residue_plan_too_large")
    reference_columns = ((m.ChatRecord, (m.ChatRecord.reference_docs, m.ChatRecord.selected_document_version_ids)),
        (m.ValidationRun, (m.ValidationRun.execution_manifest, m.ValidationRun.selected_document_ids)),
        (m.ValidationRunItem, (m.ValidationRunItem.reference_docs, m.ValidationRunItem.selected_document_ids)),
        (m.ApprovalEvidenceManifest, (m.ApprovalEvidenceManifest.manifest,)),
        (m.PublicApiRequestLog, (m.PublicApiRequestLog.citations, m.PublicApiRequestLog.selected_document_ids,
            m.PublicApiRequestLog.selected_document_version_ids)))
    summaries = []
    for model, columns in reference_columns:
        # Global occurrence search also catches cross-project references.
        predicate = or_(*(cast(col, Text).contains(token, autoescape=True) for col in columns for token in tokens))
        ids = list(session.scalars(select(model.id).where(predicate).limit(BATCH + 1)))
        if ids:
            reject("soft_residue_history_reference")
        summaries.append({"table": model.__tablename__, "references": 0})
    # Direct version references may have empty JSON. Keep all such evidence.
    for model in (m.ChatRecord, m.ValidationRun):
        if session.scalar(select(model.id).where(model.document_version_id == scope.version_id).limit(1)):
            reject("soft_residue_history_reference")
    if session.scalar(select(m.DocumentVersion.id).where(m.DocumentVersion.source_version_id == scope.version_id,
            m.DocumentVersion.id != scope.version_id).limit(1)):
        reject("soft_residue_history_reference")
    if session.scalar(select(m.DocumentReference.id).where(m.DocumentReference.source_document_id == scope.document_id).limit(1)):
        reject("soft_residue_history_reference")
    foreign_payloads = or_(*(cast(col, Text).contains(token, autoescape=True)
        for col in (m.PipelineRunStep.artifact_payload, m.PipelineRunStep.input_artifact_ref, m.PipelineRunStep.output_artifact_ref)
        for token in tokens))
    if session.scalar(select(m.PipelineRunStep.id).join(m.PipelineRun).where(
            m.PipelineRun.document_version_id != scope.version_id, foreign_payloads).limit(1)):
        reject("soft_residue_history_reference")
    if session.scalar(select(m.DocumentReferenceEvent.id).where(or_(
            m.DocumentReferenceEvent.old_source_version_id == scope.version_id,
            m.DocumentReferenceEvent.new_source_version_id == scope.version_id)).limit(1)):
        reject("soft_residue_history_reference")
    # Encrypted citations cannot be proved irrelevant without a separate privacy contract.
    if session.scalar(select(m.PublicApiRequestLog.id).where(m.PublicApiRequestLog.project_id == scope.project_id,
            m.PublicApiRequestLog.citations_encrypted.is_not(None)).limit(1)):
        reject("soft_residue_encrypted_reference")
    for model in (m.PipelineRun, m.DocumentContentUpdate, m.GraphSyncJob):
        if session.scalar(select(model.id).where(model.document_version_id == scope.version_id,
                model.status.in_(ACTIVE)).limit(1)):
            reject("soft_residue_active_work")
    for job in session.scalars(select(m.DocumentContentUpdate).where(m.DocumentContentUpdate.document_version_id == scope.version_id)):
        if (job.checkpoint or {}).get("provider_inflight") or job.claim_token or job.lease_expires_at:
            reject("soft_residue_active_work")
    if session.scalar(select(m.OutboxEvent.id).where(m.OutboxEvent.project_id == scope.project_id,
            m.OutboxEvent.status.in_(("pending", "processing"))).limit(1)):
        reject("soft_residue_active_work")
    # Unexpected JSON shape in same-project evidence is not an empty reference set.
    for model, columns in reference_columns:
        if not hasattr(model, "project_id"):
            query = select(model.id, *columns).join(m.ValidationRun, m.ValidationRun.id == m.ValidationRunItem.run_id).where(m.ValidationRun.project_id == scope.project_id)
        else:
            query = select(model.id, *columns).where(model.project_id == scope.project_id)
        for row in session.execute(query.execution_options(yield_per=BATCH)):
            for col, value in zip(columns, row[1:], strict=True):
                expected = dict if col.key in {"execution_manifest", "manifest"} else list
                if not isinstance(value, expected):
                    reject("soft_residue_unknown_reference")
                if expected is list and col.key in {"reference_docs", "citations"} and any(not isinstance(v, dict) for v in value):
                    reject("soft_residue_unknown_reference")
                if expected is list and col.key.startswith("selected_document"):
                    try:
                        for identity in value:
                            UUID(identity)
                    except (ValueError, TypeError, AttributeError):
                        reject("soft_residue_unknown_reference")
                if expected is dict and value.get("state") == "legacy_manifest_unavailable":
                    reject("soft_residue_unknown_reference")
            summaries.append({"table": model.__tablename__, "id": str(row[0]), "hash": digest(list(row[1:]))})
    return digest(summaries)


def database_items(session, scope, current_pipeline_id):
    """Inventory storage rows only. This does not certify a ready candidate."""
    old = list(session.scalars(select(m.Chunk).where(m.Chunk.document_version_id == scope.version_id,
        m.Chunk.status == "superseded").order_by(m.Chunk.id)))
    if len(old) > BATCH or any(c.project_id != scope.project_id or c.document_id != scope.document_id for c in old):
        reject()
    old_ids = [c.id for c in old]
    builds = list(session.scalars(select(m.EmbeddingBuild).where(m.EmbeddingBuild.document_version_id == scope.version_id).order_by(m.EmbeddingBuild.id)))
    links = list(session.scalars(select(m.ChunkTag).where(m.ChunkTag.chunk_id.in_(old_ids)))) if old_ids else []
    vectors = list(session.scalars(select(m.EmbeddingBuildVector).where(m.EmbeddingBuildVector.chunk_id.in_(old_ids)).order_by(m.EmbeddingBuildVector.id))) if old_ids else []
    for row in vectors:
        build = next((b for b in builds if b.id == row.embedding_build_id), None)
        if build is None or build.project_id != scope.project_id or build.document_id != scope.document_id:
            reject()
    if old_ids and session.scalar(select(m.Chunk.id).where(m.Chunk.document_version_id != scope.version_id,
            or_(m.Chunk.parent_chunk_id.in_(old_ids), m.Chunk.superseded_by_id.in_(old_ids),
                *(cast(m.Chunk.chunk_strategy, Text).contains(str(identity), autoescape=True) for identity in old_ids),
                *(cast(m.Chunk.source_mapping, Text).contains(str(identity), autoescape=True) for identity in old_ids))).limit(1)):
        reject("soft_residue_history_reference")
    steps = list(session.scalars(select(m.PipelineRunStep).join(m.PipelineRun, m.PipelineRun.id == m.PipelineRunStep.run_id)
        .where(m.PipelineRun.project_id == scope.project_id, m.PipelineRun.document_id == scope.document_id,
            m.PipelineRun.document_version_id == scope.version_id, m.PipelineRun.id != current_pipeline_id,
            m.PipelineRunStep.step_name.in_(DERIVED_BODY_STEPS),
            or_(*(m.PipelineRunStep.artifact_payload.op("?")(key) for key in BODY_KEYS)))
        .order_by(m.PipelineRunStep.id)))
    for step in steps:
        payload = step.artifact_payload
        if not isinstance(payload, dict) or not isinstance(payload.get("nodes", []), list):
            reject()
        for node in payload.get("nodes", []):
            if not isinstance(node, dict) or any(node.get(k) is not None and str(node[k]) != str(v) for k, v in (
                    ("project_id", scope.project_id), ("document_id", scope.document_id), ("document_version_id", scope.version_id))):
                reject()
    result = {"chunks": [{"id": str(c.id), "sha256": digest(row_value(c))} for c in old],
        "vectors": [{"id": str(v.id), "build_id": str(v.embedding_build_id), "sha256": digest(row_value(v))} for v in vectors],
        "links": sorted(({"chunk_id": str(l.chunk_id), "tag_id": str(l.tag_id), "sha256": digest(row_value(l))} for l in links), key=lambda v: (v["chunk_id"], v["tag_id"])),
        "steps": [{"id": str(s.id), "sha256": digest(row_value(s))} for s in steps]}
    if any(len(rows) > BATCH for rows in result.values()):
        reject("soft_residue_plan_too_large")
    return result


def identity_tokens(items):
    return [row["id"] for key in ("chunks", "vectors", "steps") for row in items[key]]


def retained_inventory(session, scope, settings, project, document, version):
    chunks, build, index = verify_committed_candidate(session, settings, project, document, version,
        revision=scope.revision, sha256=scope.canonical_sha256)
    if not chunks or build is None or not index:
        reject("soft_residue_retained_source_incomplete")
    state = session.get(m.DocumentContentState, version.id)
    values = row_value(version)
    strategy = dict(values["chunk_strategy"] or {})
    strategy.pop(KEY, None)
    values["chunk_strategy"] = strategy
    values.pop("updated_at", None)
    vectors = list(session.scalars(select(m.EmbeddingBuildVector).where(m.EmbeddingBuildVector.embedding_build_id == build.id)))
    links = list(session.scalars(select(m.ChunkTag).where(m.ChunkTag.chunk_id.in_([c.id for c in chunks]))))
    version_tags = list(session.scalars(select(m.DocumentVersionTag).where(m.DocumentVersionTag.document_version_id == version.id)))
    return {"version_sha256": digest(values), "canonical_sha256": digest(row_value(state)),
        "chunks_sha256": rows_digest(chunks), "vectors_sha256": rows_digest(vectors),
        "links_sha256": rows_digest(links), "version_tags_sha256": rows_digest(version_tags),
        "selected_build_sha256": digest(row_value(build)), "selected_build_id": str(build.id), "selected_index": index,
        "chunk_count": len(chunks), "vector_count": len(vectors)}


def inspect_cleanup(session, settings, scope, context):
    project, document, version = locked_scope(session, scope, context)
    retained = retained_inventory(session, scope, settings, project, document, version)
    from app.domain.content_pipeline_evidence import current_pipeline
    pipeline = current_pipeline(session, version.id, project_id=project.id, document_id=document.id)
    if pipeline is None:
        reject()
    items = database_items(session, scope, pipeline.id)
    adapter = LiveOpenSearchStagingIndexAdapter(settings)
    names = (discover_indices(adapter, staging_index_name(settings.opensearch_index_prefix, project.id, version.id))
        | known_index_names(session, version.id)) - {retained["selected_index"]}
    items["indices"] = []
    for name in sorted(names):
        check_index_references(session, version, name)
        owned = verify_external_owner(LiveOpenSearchStagingIndexAdapter(settings, index_override=name), name,
            project.id, document.id, version.id, known=name in known_index_names(session, version.id))
        if owned:
            items["indices"].append(name)
    refs = reference_inventory(session, scope, [*identity_tokens(items), *names])
    # Formal or stray graph nodes require a separate graph-retention plan.
    require_empty_candidate_graph(settings, version.id)
    manifest = {"scope": scope.json(), "retained": retained, "reference_digest": refs,
        "current_pipeline_id": str(pipeline.id), "items": items}
    if len(json.dumps(manifest).encode()) > MAX_BYTES:
        reject("soft_residue_plan_too_large")
    return manifest


def require_empty_candidate_graph(settings, version_id):
    from app.core.config import create_neo4j_driver
    with create_neo4j_driver(settings) as driver:
        with driver.session(database=settings.neo4j_database, default_access_mode="READ") as graph:
            count = graph.run("MATCH (n) WHERE n.document_version_id=$v OR n.id=$v RETURN count(n) AS n", v=str(version_id)).single()["n"]
            if count:
                reject("soft_residue_graph_reference")


def _save(session, version, run):
    if len(json.dumps(run).encode()) > MAX_BYTES:
        reject("soft_residue_plan_too_large")
    version.chunk_strategy = {**(version.chunk_strategy or {}), KEY: run}
    session.flush()


def plan_cleanup(session, settings, scope, context, *, manifest, plan_sha256, idempotency_key):
    project, document, version = locked_scope(session, scope, context)
    existing = (version.chunk_strategy or {}).get(KEY)
    if existing:
        if existing.get("idempotency_key") != str(idempotency_key) or existing.get("manifest_sha256") != digest(manifest):
            reject("soft_residue_conflict")
        return existing
    if len(plan_sha256) != 64 or any(c not in "0123456789abcdef" for c in plan_sha256):
        reject("soft_residue_invalid_plan", 422)
    if inspect_cleanup(session, settings, scope, context) != manifest:
        reject("soft_residue_stale")
    now = datetime.now(UTC).isoformat()
    run = {"schema_version": 1, "run_id": str(uuid4()), "actor_id": str(context.user_id),
        "idempotency_key": str(UUID(str(idempotency_key))), "approved_plan_sha256": plan_sha256,
        "manifest_sha256": digest(manifest), "manifest": manifest, "state": "planned", "stage": "intent",
        "claim_token": None, "lease_expires_at": None, "receipts": {}, "started_at": now, "updated_at": now}
    _save(session, version, run)
    add_audit(session, actor_user_id=context.user_id, action="document.soft_residue.planned", resource_type="document",
        resource_id=document.id, result="success", request_id=None,
        summary={"run_id": run["run_id"], "manifest_sha256": run["manifest_sha256"], "plan_sha256": plan_sha256})
    session.commit()
    return run


def _fence(session, settings, scope, context, run_id, token):
    project, document, version = locked_scope(session, scope, context)
    run = (version.chunk_strategy or {}).get(KEY)
    if (not isinstance(run, dict) or run.get("run_id") != str(run_id) or run.get("claim_token") != token
        or run.get("state") not in {"running", "verifying"}
        or datetime.fromisoformat(run["lease_expires_at"]) <= datetime.now(UTC)):
        reject("soft_residue_claim_lost")
    manifest = run["manifest"]
    if manifest["retained"] != retained_inventory(session, scope, settings, project, document, version):
        reject("soft_residue_stale")
    refs = reference_inventory(session, scope, [*identity_tokens(manifest["items"]), *manifest["items"]["indices"]])
    if refs != manifest["reference_digest"]:
        reject("soft_residue_reference_changed")
    require_empty_candidate_graph(settings, version.id)
    run = json.loads(json.dumps(run))
    run["lease_expires_at"] = (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat()
    run["updated_at"] = datetime.now(UTC).isoformat()
    return project, document, version, run


def retire_database_items(session, scope, items, *, run_id, revision):
    """Caller holds verified parent locks. Native storage tests are not readiness.

    Exact manifests are rechecked before any row mutation. No commit or Provider.
    """
    check_chunk_fks(session)
    chunk_ids = [UUID(r["id"]) for r in items["chunks"]]
    vector_ids = [UUID(r["id"]) for r in items["vectors"]]
    build_ids = {UUID(r["build_id"]) for r in items["vectors"]}
    for item in items["vectors"]:
        row = session.get(m.EmbeddingBuildVector, UUID(item["id"]))
        if row is not None and digest(row_value(row)) != item["sha256"]:
            reject("soft_residue_stale")
    for bid in build_ids:
        build = session.get(m.EmbeddingBuild, bid)
        if build is None or (build.project_id, build.document_id, build.document_version_id) != (scope.project_id, scope.document_id, scope.version_id):
            reject()
        if session.scalar(select(m.EmbeddingBuildVector.id).where(m.EmbeddingBuildVector.embedding_build_id == bid,
                m.EmbeddingBuildVector.id.not_in(vector_ids)).limit(1)):
            reject()
    for item in items["links"]:
        row = session.get(m.ChunkTag, (UUID(item["chunk_id"]), UUID(item["tag_id"])))
        if row is not None and digest(row_value(row)) != item["sha256"]:
            reject("soft_residue_stale")
    old = []
    for item in items["chunks"]:
        chunk = session.get(m.Chunk, UUID(item["id"]))
        if chunk is not None:
            if digest(row_value(chunk)) != item["sha256"] or chunk.status != "superseded" or (chunk.project_id, chunk.document_id, chunk.document_version_id) != (scope.project_id, scope.document_id, scope.version_id):
                reject("soft_residue_stale")
            old.append(chunk)
    if chunk_ids and session.scalar(select(m.Chunk.id).where(m.Chunk.document_version_id != scope.version_id,
            or_(m.Chunk.parent_chunk_id.in_(chunk_ids), m.Chunk.superseded_by_id.in_(chunk_ids),
                *(cast(m.Chunk.chunk_strategy, Text).contains(str(identity), autoescape=True) for identity in chunk_ids),
                *(cast(m.Chunk.source_mapping, Text).contains(str(identity), autoescape=True) for identity in chunk_ids))).limit(1)):
        reject()
    # All checks above precede writes, including unchanged link payloads.
    if vector_ids:
        session.execute(delete(m.EmbeddingBuildVector).where(m.EmbeddingBuildVector.id.in_(vector_ids)))
    for bid in build_ids:
        session.get(m.EmbeddingBuild, bid).status = "invalidated"
    for item in items["links"]:
        session.execute(delete(m.ChunkTag).where(m.ChunkTag.chunk_id == UUID(item["chunk_id"]), m.ChunkTag.tag_id == UUID(item["tag_id"])))
    for chunk in old:
        if session.scalar(select(m.EmbeddingBuildVector.id).where(m.EmbeddingBuildVector.chunk_id == chunk.id).limit(1)):
            reject()
        chunk.parent_chunk_id = None
        chunk.superseded_by_id = None
        chunk.content, chunk.markdown_content, chunk.display_markdown, chunk.retrieval_text = "", None, None, None
        chunk.title, chunk.section_path, chunk.heading_path, chunk.source_mapping = None, None, None, []
        chunk.chunk_strategy = {"cleanup": "obsolete_payload_removed", "content_hash": chunk.content_hash}
    session.flush()
    kept = []
    for chunk in old:
        if session.scalar(select(m.Chunk.id).where(m.Chunk.id != chunk.id, or_(m.Chunk.parent_chunk_id == chunk.id,
                m.Chunk.superseded_by_id == chunk.id, cast(m.Chunk.chunk_strategy, Text).contains(str(chunk.id), autoescape=True),
                cast(m.Chunk.source_mapping, Text).contains(str(chunk.id), autoescape=True))).limit(1)):
            kept.append(str(chunk.id))
        else:
            session.delete(chunk)
    for item in items["steps"]:
        step = session.get(m.PipelineRunStep, UUID(item["id"]))
        if step is None:
            reject()
        if (step.artifact_payload or {}).get("retired_for_maintenance_run_id") == str(run_id):
            continue
        if digest(row_value(step)) != item["sha256"]:
            reject("soft_residue_stale")
        original = step.artifact_payload
        step.artifact_payload = {"source": "retired_working_derived_output", "payload_retired": True,
            "project_id": str(scope.project_id), "document_id": str(scope.document_id), "document_version_id": str(scope.version_id),
            "pipeline_run_id": str(step.run_id), "step_id": str(step.id), "original_fingerprint": step.artifact_fingerprint,
            "original_payload_sha256": digest(original), "retired_for_maintenance_run_id": str(run_id), "retired_for_revision": revision,
            "counts": {key: len(original[key]) for key in BODY_KEYS if isinstance(original.get(key), (dict, list))}}
        step.artifact_fingerprint = digest(step.artifact_payload)
    session.flush()
    return {"vectors": len(vector_ids), "links": len(items["links"]), "chunks": len(old),
        "step_payloads": len(items["steps"]), "protected_lineage_ids": kept}


def verify_retirement(session, settings, scope, context, run):
    project, document, version = locked_scope(session, scope, context)
    manifest = run["manifest"]
    if retained_inventory(session, scope, settings, project, document, version) != manifest["retained"]:
        reject("soft_residue_stale")
    remaining = database_items(session, scope, UUID(manifest["current_pipeline_id"]))
    for item in remaining["chunks"]:
        chunk = session.get(m.Chunk, UUID(item["id"]))
        if any((chunk.content, chunk.markdown_content, chunk.display_markdown, chunk.retrieval_text, chunk.title, chunk.section_path, chunk.heading_path, chunk.source_mapping)):
            reject("soft_residue_not_clean")
    if remaining["vectors"] or remaining["links"] or remaining["steps"]:
        reject("soft_residue_not_clean")
    adapter = LiveOpenSearchStagingIndexAdapter(settings)
    names = discover_indices(adapter, staging_index_name(settings.opensearch_index_prefix, project.id, version.id))
    if names != {manifest["retained"]["selected_index"]}:
        reject("soft_residue_not_clean")
    if reference_inventory(session, scope, [*identity_tokens(manifest["items"]), *manifest["items"]["indices"]]) != manifest["reference_digest"]:
        reject("soft_residue_reference_changed")
    require_empty_candidate_graph(settings, version.id)
    return {"eligible_old_payload_bytes": 0, "old_vectors": 0, "old_links": 0, "old_indices": 0,
        "old_step_bodies": 0, "minimal_lineage_ids": [r["id"] for r in remaining["chunks"]],
        "retained_digest": digest(manifest["retained"]), "verified_at": datetime.now(UTC).isoformat()}


def execute_cleanup(session, settings, scope, context, *, run_id, manifest_sha256, plan_sha256):
    """One explicit claim. Failure is durable and never automatically replayed."""
    project, document, version = locked_scope(session, scope, context)
    saved = (version.chunk_strategy or {}).get(KEY)
    if (not isinstance(saved, dict) or saved.get("run_id") != str(run_id) or saved.get("manifest_sha256") != manifest_sha256
        or saved.get("approved_plan_sha256") != plan_sha256 or saved.get("actor_id") != str(context.user_id)):
        reject("soft_residue_conflict")
    if saved["state"] == "completed":
        return verify_retirement(session, settings, scope, context, saved)
    if saved["state"] != "planned" or saved.get("claim_token"):
        reject("soft_residue_claim_lost")
    if inspect_cleanup(session, settings, scope, context) != saved["manifest"]:
        reject("soft_residue_stale")
    run = json.loads(json.dumps(saved))
    token = str(uuid4())
    run.update(state="running", claim_token=token,
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat())
    _save(session, version, run)
    session.commit()
    try:
        project, document, version, run = _fence(session, settings, scope, context, run_id, token)
        run["stage"] = "indices"
        _save(session, version, run)
        session.commit()  # durable intent before the first external deletion
        for name in run["manifest"]["items"]["indices"]:
            project, document, version, run = _fence(session, settings, scope, context, run_id, token)
            delete_retired_index(session, settings, project, document, version, name, run["manifest"]["retained"]["selected_index"])
            run["receipts"][name] = {"absent_verified": True}
            _save(session, version, run)
            session.commit()
        project, document, version, run = _fence(session, settings, scope, context, run_id, token)
        run["stage"] = "database"
        if database_items(session, scope, UUID(run["manifest"]["current_pipeline_id"])) != {
                key: value for key, value in run["manifest"]["items"].items() if key != "indices"}:
            reject("soft_residue_stale")
        run["receipts"]["database"] = retire_database_items(session, scope, run["manifest"]["items"], run_id=run_id, revision=scope.revision)
        run.update(state="verifying", stage="readback")
        _save(session, version, run)
        session.commit()
        project, document, version, run = _fence(session, settings, scope, context, run_id, token)
        run["receipts"]["readback"] = verify_retirement(session, settings, scope, context, run)
        run.update(state="completed", claim_token=None, lease_expires_at=None, completed_at=datetime.now(UTC).isoformat())
        _save(session, version, run)
        add_audit(session, actor_user_id=context.user_id, action="document.soft_residue.completed", resource_type="document",
            resource_id=document.id, result="success", request_id=None, summary={"run_id": str(run_id), "manifest_sha256": manifest_sha256})
        session.commit()
        return run["receipts"]["readback"]
    except Exception as error:
        session.rollback()
        # Record partial state without changing an unrelated/new maintenance run.
        session.scalar(select(m.Project).where(m.Project.id == scope.project_id).with_for_update())
        session.scalar(select(m.Document).where(m.Document.id == scope.document_id).with_for_update())
        version = session.scalar(select(m.DocumentVersion).where(m.DocumentVersion.id == scope.version_id).with_for_update().execution_options(populate_existing=True))
        current = (version.chunk_strategy or {}).get(KEY) if version else None
        if current and current.get("run_id") == str(run_id) and current.get("claim_token") == token:
            current = json.loads(json.dumps(current))
            current.update(state="partial_unknown", error_code=getattr(error, "code", "soft_residue_execution_failed"),
                claim_token=None, lease_expires_at=None, updated_at=datetime.now(UTC).isoformat())
            _save(session, version, current)
            add_audit(session, actor_user_id=context.user_id, action="document.soft_residue.failed", resource_type="document",
                resource_id=scope.document_id, result="failed", request_id=None,
                summary={"run_id": str(run_id), "stage": current["stage"], "error_code": current["error_code"]})
            session.commit()
        raise

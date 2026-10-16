"""Exact-scope, resumable cleanup after a verified candidate promotion.

Build receipts, model usage and immutable source artifacts are never garbage.
Only unprotected obsolete payloads are removed. No model is called here.
"""
from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import delete, or_, select

from app.core.errors import AppError
from app.db.models import ActiveVersionManifest, ApprovalEvidenceManifest, ApprovalRequest, Chunk, ChunkTag, DocumentContentState, DocumentReference, EmbeddingBuild, EmbeddingBuildVector, EmbeddingProfile, PipelineRun, PipelineRunStep
from app.domain.content_pipeline_evidence import BODY_KEYS, DERIVED_BODY_STEPS, obsolete_step_bodies
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name
from app.domain.graph_projection import build_graph_projection

BATCH_SIZE = 200


def retire_obsolete_step_payloads(session, project, document, version, job, receipt, fence):
    """Retain audit hashes, not graph/tag output bodies of older working runs."""
    retired = int((receipt.get("step_payloads") or {}).get("retired_count", 0))
    while True:
        fence()
        require_unprotected_version(session, version)
        rows = list(session.scalars(select(PipelineRunStep).join(PipelineRun, PipelineRun.id == PipelineRunStep.run_id)
            .where(PipelineRun.project_id == project.id, PipelineRun.document_id == document.id,
                PipelineRun.document_version_id == version.id, PipelineRun.id != job.pipeline_run_id,
                PipelineRunStep.step_name.in_(DERIVED_BODY_STEPS),
                or_(*(PipelineRunStep.artifact_payload.op("?")(key) for key in sorted(BODY_KEYS))))
            .order_by(PipelineRunStep.id).limit(BATCH_SIZE).with_for_update(of=PipelineRunStep)))
        if not rows:
            break
        for step in rows:
            payload = step.artifact_payload
            if not isinstance(payload, dict):
                raise AppError("content_cleanup_protected", "Derived output ownership is invalid", status_code=409)
            nodes = payload.get("nodes", [])
            if not isinstance(nodes, list):
                raise AppError("content_cleanup_protected", "Derived output ownership is invalid", status_code=409)
            for node in nodes:
                if not isinstance(node, dict) or any(node.get(key) is not None and str(node[key]) != str(identity)
                    for key, identity in (("project_id", project.id), ("document_id", document.id), ("document_version_id", version.id))):
                    raise AppError("content_cleanup_protected", "Derived output contains another scope", status_code=409)
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
            minimal = {"source": "retired_working_derived_output", "payload_retired": True,
                "project_id": str(project.id), "document_id": str(document.id), "document_version_id": str(version.id),
                "pipeline_run_id": str(step.run_id), "step_id": str(step.id),
                "original_fingerprint": step.artifact_fingerprint, "original_payload_sha256": hashlib.sha256(raw).hexdigest(),
                "retired_for_update_id": str(job.id), "retired_for_revision": job.target_revision,
                "counts": {key: len(payload[key]) for key in sorted(BODY_KEYS) if isinstance(payload.get(key), (list, dict))}}
            step.artifact_payload = minimal
            step.artifact_fingerprint = hashlib.sha256(json.dumps(minimal, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            retired += 1
        receipt["step_payloads"] = {"retired_count": retired, "verified": False,
            "revision": job.target_revision, "canonical_sha256": job.target_sha256}
        job.checkpoint = {**job.checkpoint, "cleanup": dict(receipt)}
        session.commit()
    fence()
    require_unprotected_version(session, version)
    if obsolete_step_bodies(session, project, document, version, job.pipeline_run_id):
        raise AppError("content_cleanup_failed", "Obsolete derived outputs remain", status_code=409)
    receipt["step_payloads"] = {"retired_count": retired, "verified": True,
        "revision": job.target_revision, "canonical_sha256": job.target_sha256}


def require_unprotected_version(session, version):
    if (version.published_at is not None or version.status not in {"processing", "submission_ready", "failed"}
        or session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id).limit(1))
        or session.scalar(select(ApprovalEvidenceManifest.id).where(ApprovalEvidenceManifest.document_version_id == version.id).limit(1))
        or session.scalar(select(ActiveVersionManifest.id).where(ActiveVersionManifest.document_version_id == version.id).limit(1))
        or session.scalar(select(DocumentReference.id).where(DocumentReference.source_version_id == version.id).limit(1))):
        raise AppError("content_cleanup_protected", "This version is protected by history or references", status_code=409)


def verify_committed_candidate(session, settings, project, document, version, *, revision, sha256):
    """Verify persisted vectors without pretending disabled models are compatible."""
    state = session.get(DocumentContentState, version.id)
    if (state is None or state.project_id != project.id or state.document_id != document.id
        or state.content_revision != revision or state.current_sha256 != sha256
        or hashlib.sha256(state.current_markdown.encode()).hexdigest() != sha256):
        raise AppError("content_update_stale", "Committed content changed", status_code=409)
    chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
        Chunk.status == "active").order_by(Chunk.chunk_index)))
    if any(c.project_id != project.id or c.document_id != document.id for c in chunks):
        raise AppError("content_update_stale", "Chunk scope changed", status_code=409)
    graph = build_graph_projection(session, project, document, version, chunks)
    if (version.chunk_strategy or {}).get("graph_preview", {}).get("source_digest") != graph.source_digest:
        raise AppError("graph_source_stale", "Committed graph changed", status_code=409)
    index = (version.extraction_artifact_uri or "").removeprefix("opensearch://") or None
    build = None
    if chunks:
        builds = list(session.scalars(select(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version.id,
            EmbeddingBuild.index_name == index, EmbeddingBuild.status.in_(("staged", "completed")))))
        if not index or len(builds) != 1:
            raise AppError("canonical_embedding_build_invalid", "Selected build is ambiguous", status_code=409)
        build = builds[0]
        profile = session.get(EmbeddingProfile, build.embedding_profile_id)
        rows = list(session.scalars(select(EmbeddingBuildVector).where(EmbeddingBuildVector.embedding_build_id == build.id).order_by(EmbeddingBuildVector.chunk_index)))
        if (build.project_id != project.id or build.document_id != document.id or profile is None
            or build.vector_dimension != profile.vector_dimension or build.chunk_count != len(chunks) or len(rows) != len(chunks)):
            raise AppError("canonical_embedding_build_invalid", "Selected vector scope is invalid", status_code=409)
        for row, chunk in zip(rows, chunks, strict=True):
            if (row.chunk_id != chunk.id or row.chunk_index != chunk.chunk_index
                or hashlib.sha256(json.dumps(row.vector, separators=(",", ":")).encode()).hexdigest() != row.vector_checksum):
                raise AppError("canonical_embedding_build_invalid", "Selected vector checksum is invalid", status_code=409)
        if hashlib.sha256("".join(row.vector_checksum for row in rows).encode("ascii")).hexdigest() != build.checksum:
            raise AppError("canonical_embedding_build_invalid", "Selected corpus checksum is invalid", status_code=409)
        LiveOpenSearchStagingIndexAdapter(settings, index_override=index).verify_existing_chunks(
            project=project, document=document, version=version, chunks=chunks, vectors=[row.vector for row in rows], profile=profile)
    elif index:
        raise AppError("content_update_stale", "Empty candidate still selects an index", status_code=409)
    return chunks, build, index


def delete_retired_index(session, settings, project, document, version, index, selected_index):
    """Only an exclusive staging index with full UUID scope may be deleted."""
    base_name = staging_index_name(settings.opensearch_index_prefix, project.id, version.id)
    if (index == selected_index or not re.fullmatch(re.escape(base_name) + r"(?:-edit-[0-9a-f]{32})?", index)
        or session.scalar(select(EmbeddingBuild.id).where(EmbeddingBuild.index_name == index,
            or_(EmbeddingBuild.project_id != project.id, EmbeddingBuild.document_id != document.id,
                EmbeddingBuild.document_version_id != version.id)).limit(1))
        or session.scalar(select(ActiveVersionManifest.id).join(EmbeddingBuild,
            EmbeddingBuild.id == ActiveVersionManifest.embedding_build_id).where(EmbeddingBuild.index_name == index).limit(1))):
        raise AppError("content_cleanup_protected", "Index is selected, shared or outside this version", status_code=409)
    adapter = LiveOpenSearchStagingIndexAdapter(settings, index_override=index)
    from app.domain.index_residue import check_index_references, known_index_names, verify_external_owner
    check_index_references(session, version, index)
    exists = verify_external_owner(adapter, index, project.id, document.id, version.id,
                                   known=index in known_index_names(session, version.id))
    if not exists:
        return False
    url = settings.opensearch_url.rstrip("/") + "/" + index
    # An HTTP 404 proves absence. A timeout/503 never does.
    payload = adapter._request("POST", url + "/_count", json.dumps({"query": {"bool": {"must_not": [
        {"bool": {"filter": [{"term": {"project_id": str(project.id)}},
            {"term": {"document_id": str(document.id)}}, {"term": {"document_version_id": str(version.id)}}]}}
    ]}}}).encode(), context=settings.opensearch_ssl_context, content_type="application/json", allow_missing=True, read_json=True)
    if payload is not None:
        if (not isinstance(payload, dict) or payload.get("count") != 0
            or payload.get("_shards", {}).get("failed") != 0):
            raise AppError("content_cleanup_protected", "Index contains other scope data", status_code=409)
        adapter.delete_version(project_id=project.id, version_id=version.id)
    remains = adapter._request("GET", url, b"", context=settings.opensearch_ssl_context,
        content_type="application/json", allow_missing=True, read_json=True)
    if remains is not None:
        raise AppError("content_cleanup_failed", "Retired index remains", status_code=502)
    return True


def clean_obsolete_candidates(session, settings, project, document, version, job, fence):
    """Caller supplies the live claim/revision fence; every commit is resumable."""
    fence()
    require_unprotected_version(session, version)
    chunks, selected_build, selected_index = verify_committed_candidate(session, settings, project, document,
        version, revision=job.target_revision, sha256=job.target_sha256)
    active_ids = {c.id for c in chunks}
    receipt = dict((job.checkpoint or {}).get("cleanup") or {})
    receipt.update(status="running", selected_index=selected_index)
    while True:
        builds = list(session.scalars(select(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version.id,
            # Manual reconciliation invalidates receipts before rebuilding;
            # that status does not mean its stored vector payload was removed.
            or_(EmbeddingBuild.status != "invalidated", select(EmbeddingBuildVector.id).where(
                EmbeddingBuildVector.embedding_build_id == EmbeddingBuild.id).exists()),
            EmbeddingBuild.id != selected_build.id if selected_build else True)
            .order_by(EmbeddingBuild.id).limit(BATCH_SIZE)))
        if not builds:
            break
        for build in builds:
            fence(); require_unprotected_version(session, version)
            if build.project_id != project.id or build.document_id != document.id:
                raise AppError("content_cleanup_protected", "Build scope is invalid", status_code=409)
            if build.index_name:
                delete_retired_index(session, settings, project, document, version, build.index_name, selected_index)
            session.execute(delete(EmbeddingBuildVector).where(EmbeddingBuildVector.embedding_build_id == build.id))
            build.status = "invalidated"  # Keep the hash/usage/build receipt, not vector payloads.
            receipt["retired_builds"] = receipt.get("retired_builds", 0) + 1
            job.checkpoint = {**job.checkpoint, "cleanup": dict(receipt)}
            session.commit()
    # A failed index write can have no selected build index receipt. Include the
    # bounded historical step receipts; repeated deletes are safe on HTTP404.
    from app.domain.index_residue import discover_indices, known_index_names
    adapter = LiveOpenSearchStagingIndexAdapter(settings)
    base = staging_index_name(settings.opensearch_index_prefix, project.id, version.id)
    indices = (known_index_names(session, version.id) | discover_indices(adapter, base)) - {selected_index}
    for ordinal, index in enumerate(sorted(indices), 1):
        fence(); require_unprotected_version(session, version)
        if delete_retired_index(session, settings, project, document, version, index, selected_index):
            receipt["retired_indices"] = receipt.get("retired_indices", 0) + 1
        receipt["index_cursor"] = index
        if ordinal % BATCH_SIZE == 0:
            job.checkpoint = {**job.checkpoint, "cleanup": dict(receipt)}
            session.commit()
    if discover_indices(adapter, base) - {selected_index}:
        raise AppError("content_cleanup_failed", "Unselected external indices remain", status_code=409)
    # Never cascade through cross-version lineage; those payloads are explicitly
    # protected. Same-version lineage may keep only identity/hash/offset metadata.
    foreign_refs = set(session.scalars(select(Chunk.parent_chunk_id).where(Chunk.document_version_id != version.id,
        Chunk.parent_chunk_id.in_(select(Chunk.id).where(Chunk.document_version_id == version.id))))) | set(session.scalars(select(Chunk.superseded_by_id).where(
            Chunk.document_version_id != version.id, Chunk.superseded_by_id.in_(select(Chunk.id).where(Chunk.document_version_id == version.id)))))
    foreign_refs |= set(session.scalars(select(EmbeddingBuildVector.chunk_id).join(EmbeddingBuild,
        EmbeddingBuild.id == EmbeddingBuildVector.embedding_build_id).where(EmbeddingBuild.document_version_id != version.id,
            EmbeddingBuildVector.chunk_id.in_(select(Chunk.id).where(Chunk.document_version_id == version.id)))))
    protected = []
    while True:
        fence(); require_unprotected_version(session, version)
        old = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
            Chunk.status == "superseded", Chunk.id.not_in(foreign_refs),
            or_(Chunk.content != "", Chunk.markdown_content.is_not(None), Chunk.retrieval_text.is_not(None), Chunk.display_markdown.is_not(None)))
            .order_by(Chunk.id).limit(BATCH_SIZE)))
        if not old:
            break
        for chunk in old:
            if chunk.id in active_ids or chunk.project_id != project.id or chunk.document_id != document.id:
                raise AppError("content_cleanup_protected", "Chunk scope changed", status_code=409)
            linked_builds = list(session.scalars(select(EmbeddingBuild).join(EmbeddingBuildVector,
                EmbeddingBuildVector.embedding_build_id == EmbeddingBuild.id).where(EmbeddingBuildVector.chunk_id == chunk.id)))
            if linked_builds:
                raise AppError("content_cleanup_protected", "Obsolete chunk still has protected vectors", status_code=409)
            session.execute(delete(ChunkTag).where(ChunkTag.chunk_id == chunk.id))
            # Disconnect obsolete internal edges first; active descendants keep
            # their parent FK and therefore keep a minimal parent identity.
            chunk.parent_chunk_id = None
            chunk.superseded_by_id = None
            chunk.content, chunk.markdown_content, chunk.display_markdown, chunk.retrieval_text = "", None, None, None
            chunk.title, chunk.section_path, chunk.heading_path, chunk.source_mapping = None, None, None, []
            chunk.chunk_strategy = {"cleanup": "obsolete_payload_removed", "content_hash": chunk.content_hash}
        session.flush()
        for chunk in old:
            if not session.scalar(select(Chunk.id).where(or_(Chunk.parent_chunk_id == chunk.id, Chunk.superseded_by_id == chunk.id)).limit(1)):
                session.delete(chunk)
        receipt["retired_chunks"] = receipt.get("retired_chunks", 0) + len(old)
        job.checkpoint = {**job.checkpoint, "cleanup": dict(receipt)}
        session.commit()
    # A later manual edit may release an earlier minimal lineage identity.
    # Delete those orphan identities too, instead of accumulating metadata rows.
    from sqlalchemy.orm import aliased
    child = aliased(Chunk)
    while True:
        fence(); require_unprotected_version(session, version)
        orphan_ids = list(session.scalars(select(Chunk.id).where(Chunk.document_version_id == version.id,
            Chunk.status == "superseded", Chunk.content == "", Chunk.markdown_content.is_(None),
            Chunk.id.not_in(foreign_refs), ~select(child.id).where(or_(child.parent_chunk_id == Chunk.id,
                child.superseded_by_id == Chunk.id)).exists()).limit(BATCH_SIZE)))
        if not orphan_ids:
            break
        session.execute(delete(Chunk).where(Chunk.project_id == project.id, Chunk.document_id == document.id,
            Chunk.document_version_id == version.id, Chunk.id.in_(orphan_ids)))
        job.checkpoint = {**job.checkpoint, "cleanup": dict(receipt)}
        session.commit()
    protected = [str(c) for c in foreign_refs if session.scalar(select(Chunk.id).where(Chunk.id == c, Chunk.document_version_id == version.id))]
    fence(); require_unprotected_version(session, version)
    verify_committed_candidate(session, settings, project, document, version, revision=job.target_revision, sha256=job.target_sha256)
    from app.domain.graph_reconciliation import clean_candidate_graph_residues
    fence()
    receipt["graph_residue"] = clean_candidate_graph_residues(session, settings, project, document, version)
    retire_obsolete_step_payloads(session, project, document, version, job, receipt, fence)
    receipt.update(status="completed", protected_lineage_ids=protected[:BATCH_SIZE], protected_reason="cross_version_reference" if protected else None)
    job.checkpoint = {**job.checkpoint, "cleanup": receipt}
    session.flush()
    return receipt

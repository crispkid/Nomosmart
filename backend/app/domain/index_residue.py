"""Durable content-index ownership and complete external residue discovery."""
from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy import Text, cast, or_, select

from app.core.errors import AppError
from app.db.models import (ActiveVersionManifest, ApprovalEvidenceManifest, DocumentContentUpdate,
                           DocumentVersion, EmbeddingBuild, PipelineRunStep)

OWNER_FORMAT = "content-index-owner-v1"
OWNER_META = "nomosmart_content_owner"
BATCH_SIZE = 200


def protected():
    return AppError("content_cleanup_protected", "Index ownership or references cannot be verified", status_code=409)


def index_intent(job, project, version, index_name: str) -> dict:
    if (job.project_id != project.id or job.document_id != version.document_id
        or job.document_version_id != version.id or job.project_generation != project.work_generation
        or not re.fullmatch(r"[0-9a-f]{64}", job.target_sha256) or job.target_revision < 1):
        raise protected()
    return {"format": OWNER_FORMAT, "index_name": index_name, "project_id": str(project.id),
            "document_id": str(version.document_id), "document_version_id": str(version.id),
            "update_id": str(job.id), "project_generation": job.project_generation,
            "expected_lock": job.expected_lock, "target_revision": job.target_revision,
            "target_sha256": job.target_sha256}


def persist_index_intent(session, job, project, version, index_name: str) -> dict:
    from app.domain.extraction_pipeline import staging_index_name
    from app.core.config import get_settings
    base = staging_index_name(get_settings().opensearch_index_prefix, project.id, version.id)
    if index_name != base+"-edit-"+job.id.hex:
        raise protected()
    intent = index_intent(job, project, version, index_name)
    existing = (job.checkpoint or {}).get("staging_index_intent")
    if existing is not None and existing != intent:
        raise protected()
    job.checkpoint = {**(job.checkpoint or {}), "staging_index_intent": intent}
    session.commit()  # Before the first external create/delete/bulk operation.
    return intent


def _scope(intent, project_id, document_id, version_id, index_name):
    return (isinstance(intent, dict) and intent.get("format") == OWNER_FORMAT
            and intent.get("index_name") == index_name
            and intent.get("project_id") == str(project_id)
            and intent.get("document_id") == str(document_id)
            and intent.get("document_version_id") == str(version_id))


def verify_external_owner(adapter, index_name, project_id, document_id, version_id, *, known=False, intent=None):
    """Name prefix alone is never proof; unknown empty indices cannot be adopted."""
    base = adapter.settings.opensearch_url.rstrip("/") + "/" + index_name
    options = {"context": adapter.settings.opensearch_ssl_context, "content_type": "application/json",
               "allow_missing": True, "read_json": True}
    mapping = adapter._request("GET", base+"/_mapping", b"", **options)
    if mapping is None:
        return False
    if not isinstance(mapping, dict) or set(mapping) != {index_name}:
        raise protected()
    owner = mapping[index_name].get("mappings", {}).get("_meta", {}).get(OWNER_META)
    if owner is not None:
        if not _scope(owner, project_id, document_id, version_id, index_name):
            raise protected()
        try:
            update = str(UUID(owner["update_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise protected() from exc
        if (not index_name.endswith("-edit-"+UUID(update).hex)
            or not re.fullmatch(r"[0-9a-f]{64}", str(owner.get("target_sha256", "")))
            or any(type(owner.get(key)) is not int or owner[key] < 1
                   for key in ("target_revision", "project_generation", "expected_lock"))
            or (intent is not None and owner != intent)):
            raise protected()
    count = adapter._request("POST", base+"/_count", b'{"query":{"match_all":{}}}', **options)
    foreign = adapter._request("POST", base+"/_count", json.dumps({"query":{"bool":{"must_not":[
        {"bool":{"filter":[{"term":{"project_id":str(project_id)}},
                             {"term":{"document_id":str(document_id)}},
                             {"term":{"document_version_id":str(version_id)}}]}}
    ]}}}).encode(), **options)
    if (not isinstance(count, dict) or not isinstance(foreign, dict) or foreign.get("count") != 0
        or not isinstance(count.get("count"), int) or count["count"] < 0
        or count.get("_shards", {}).get("failed") != 0 or foreign.get("_shards", {}).get("failed") != 0):
        raise protected()
    if count["count"] == 0 and not known:
        raise protected()
    return True


def check_index_references(session, version, index_name):
    if (session.scalar(select(DocumentVersion.id).where(
            DocumentVersion.extraction_artifact_uri == "opensearch://"+index_name).limit(1))
        or session.scalar(select(EmbeddingBuild.id).where(EmbeddingBuild.index_name == index_name,
            or_(EmbeddingBuild.project_id != version.project_id, EmbeddingBuild.document_id != version.document_id,
                EmbeddingBuild.document_version_id != version.id)).limit(1))
        or session.scalar(select(ActiveVersionManifest.id).join(EmbeddingBuild,
            EmbeddingBuild.id == ActiveVersionManifest.embedding_build_id).where(EmbeddingBuild.index_name == index_name).limit(1))
        or session.scalar(select(ApprovalEvidenceManifest.id).where(
            cast(ApprovalEvidenceManifest.manifest, Text).contains(index_name, autoescape=True)).limit(1))
        or session.scalar(select(DocumentContentUpdate.id).where(
            DocumentContentUpdate.document_version_id != version.id,
            or_(DocumentContentUpdate.checkpoint["staging_index"].astext == index_name,
                DocumentContentUpdate.checkpoint["staging_index_intent"]["index_name"].astext == index_name)).limit(1))):
        raise protected()


def known_index_names(session, version_id) -> set[str]:
    names = set(session.scalars(select(EmbeddingBuild.index_name).where(
        EmbeddingBuild.document_version_id == version_id).execution_options(yield_per=BATCH_SIZE)))
    pipelines = select(DocumentContentUpdate.pipeline_run_id).where(DocumentContentUpdate.document_version_id == version_id)
    names.update(session.scalars(select(PipelineRunStep.artifact_payload["index_name"].astext).where(
        PipelineRunStep.run_id.in_(pipelines), PipelineRunStep.step_name == "staging_index").execution_options(yield_per=BATCH_SIZE)))
    for checkpoint in session.scalars(select(DocumentContentUpdate.checkpoint).where(
            DocumentContentUpdate.document_version_id == version_id).execution_options(yield_per=BATCH_SIZE)):
        names.add((checkpoint or {}).get("staging_index"))
        intent = (checkpoint or {}).get("staging_index_intent")
        if isinstance(intent, dict):
            names.add(intent.get("index_name"))
    return names - {None, ""}


def discover_indices(adapter, base_name):
    payload = adapter._request("GET", adapter.settings.opensearch_url.rstrip("/")+
        "/_cat/indices/"+base_name+"*?format=json&h=index&expand_wildcards=all", b"",
        context=adapter.settings.opensearch_ssl_context, content_type="application/json", read_json=True)
    if not isinstance(payload, list) or any(not isinstance(row, dict) or not isinstance(row.get("index"), str) for row in payload):
        raise protected()
    names = {row["index"] for row in payload}
    if any(not re.fullmatch(re.escape(base_name)+r"(?:-edit-[0-9a-f]{32})?", name) for name in names):
        raise protected()
    return names

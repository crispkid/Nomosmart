"""REF-COPY-001 negative persisted inputs; never manufacture a published source.

The positive workflow is exercised separately by the isolated upload/review/copy
runner. These malformed storage records must be rejected before target writes.
"""
from hashlib import sha256
from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.core.errors import AppError
from app.core.config import get_settings
from app.db.models import Chunk, Document, DocumentVersion, PipelineRun, PipelineRunStep
from app.domain.markdown_artifacts import markdown_artifact_ref
from app.domain.reference_copy import copy_chunks
from markdown_live_support import markdown_workspace  # noqa: F401


@pytest.mark.parametrize("problem", ["missing", "no_fingerprint", "bad_fingerprint", "wrong_reference", "no_chunks"])
def test_copy_rejects_incomplete_persisted_source_before_target_writes(markdown_workspace, problem):
    session, project, document, source = markdown_workspace
    target_document = Document(project_id=project.id, document_code=uuid4().hex,
        title="Target context", source_type="project_copy")
    session.add(target_document)
    session.flush()
    target = DocumentVersion(project_id=project.id, document_id=target_document.id,
        version_major=1, extraction_revision=0, version_label="v1", status="queued",
        chunk_strategy={"source_text": "# Original\n\nPreserve **meaning**."})
    session.add(target)
    session.flush()
    if problem != "missing":
        source.markdown_artifact_uri = markdown_artifact_ref(source.id)
        run = PipelineRun(project_id=project.id, document_id=document.id,
            document_version_id=source.id, run_type="document_extraction", status="failed", created_at=datetime.now(UTC))
        session.add(run)
        session.flush()
        payload = {"markdown": target.chunk_strategy["source_text"]}
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        session.add(PipelineRunStep(run_id=run.id, step_name="generate_markdown",
            status="completed", progress_percent=100, artifact_payload=payload,
            artifact_fingerprint=None if problem == "no_fingerprint" else "0"*64 if problem == "bad_fingerprint" else digest,
            output_artifact_ref=markdown_artifact_ref(uuid4() if problem == "wrong_reference" else source.id)))
        session.flush()
    with pytest.raises(AppError) as failure:
        copy_chunks(session, source=source, target=target, target_project=project, settings=get_settings())
    assert failure.value.code == "source_version_no_extractable_text"
    assert session.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_version_id == target.id)) == 0
    assert target.markdown_artifact_uri is None

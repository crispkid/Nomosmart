"""Actual same-run published graph readback; no publication or model replay."""
from dataclasses import replace
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.db.models import Document,DocumentVersion,Project
from app.db.session import get_session_factory
from app.domain.graph_projection import build_graph_projection
from app.domain.graph_reconciliation import Neo4jProjectionStore
from current_native_workspace_support import retained_adapter_publication
from scripts.edited_content_acceptance_graph_check import verify_binding


def test_actual_published_graph_receipt_has_its_own_version_lock_binding():
    factory=get_session_factory()
    actual=retained_adapter_publication(factory)
    with factory() as session:
        project=session.get(Project,UUID(actual['project_id']))
        document=session.get(Document,UUID(actual['document_id']))
        version=session.get(DocumentVersion,UUID(actual['version_id']))
        projection=build_graph_projection(session,project,document,version)
        comparison=Neo4jProjectionStore(get_settings()).read(projection)
        assert projection.revision==version.lock_version
        verify_binding(projection,comparison=comparison)
        # The same actual readback must reject an older/newer lock. No SQL or
        # Neo4j mutation and no invented comparison object is involved.
        wrong=replace(projection,revision=projection.revision+1)
        assert wrong.source_digest!=projection.source_digest
        with pytest.raises(AssertionError,match='published_graph_projection_or_receipt_mismatch'):
            verify_binding(wrong,comparison=comparison)

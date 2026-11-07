"""Missing current safety assertions, using retained real usage and graph data."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.db.models import Document, DocumentVersion, Project
from app.db.session import get_session_factory
from app.domain.graph_projection import build_graph_projection
from app.domain.graph_reconciliation import Neo4jProjectionStore
from current_native_workspace_support import retained_adapter_publication
from scripts.edited_content_acceptance_graph_check import verify_binding
from scripts.ftp_generation_acceptance_history import require_history_prefix
from test_current_usage_history_controls import actual_history


def save(name, value):
    root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
    with (root / name).open("x") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)


def test_actual_nested_provider_usage_cannot_be_changed_in_current_history(actual_history):
    context, rows, path, before = actual_history
    journal = json.loads(path.read_bytes())
    require_history_prefix(journal, rows, context["run_id"])
    invalid = deepcopy(journal)
    assert isinstance(invalid["requests"][0]["usage"], dict)
    old_usage = invalid["requests"][0]["usage"]
    field = next((k for k, value in old_usage.items() if isinstance(value, (int, float)) and not isinstance(value, bool)), None)
    # Deliberately invalid native input; no actual receipt or billed field is edited.
    if field is not None:
        old_usage[field] += 1
    else:
        old_usage["input_tokens"] = 1
    with pytest.raises(AssertionError, match="historical_request_prefix_changed"):
        require_history_prefix(invalid, rows, context["run_id"])
    assert sha256(path.read_bytes()).hexdigest() == before
    save("current-nested-usage-proof.json", {"run_uuid": context["run_id"],
        "actual_retained_model_events": len(rows), "nested_raw_usage_change_rejected": True,
        "actual_source_receipt_unchanged": True, "new_model_calls": 0,
        "historical_seven_or_23_or_50_request_journal_reconstructed": False})


def test_actual_review_preview_and_formal_graph_require_their_own_lock_identity():
    factory = get_session_factory()
    actual = retained_adapter_publication(factory)
    with factory() as session:
        project = session.get(Project, UUID(actual["project_id"]))
        document = session.get(Document, UUID(actual["document_id"]))
        version = session.get(DocumentVersion, UUID(actual["version_id"]))
        preview = deepcopy(version.chunk_strategy["graph_preview"])
        assert preview["status"] == "available" and isinstance(preview["revision"], int)
        current = build_graph_projection(session, project, document, version)
        comparison = Neo4jProjectionStore(get_settings()).read(current)
        # The immutable review preview is an actual persisted earlier lock,
        # while the current formal graph must match the actual published lock.
        earlier = replace(current, revision=preview["revision"])
        assert earlier.revision != current.revision and earlier.source_digest != current.source_digest
        verify_binding(earlier, preview=preview)
        verify_binding(current, comparison=comparison)
        with pytest.raises(AssertionError, match="candidate_graph_preview_source_mismatch"):
            verify_binding(current, preview=preview)
        with pytest.raises(AssertionError, match="published_graph_projection_or_receipt_mismatch"):
            verify_binding(earlier, comparison=comparison)
    save("current-preview-formal-graph-proof.json", {
        "actual_published_version": actual["version_id"], "persisted_preview_lock": earlier.revision,
        "actual_published_lock": current.revision, "both_actual_bindings_verified": True,
        "cross_binding_rejected": True, "new_model_or_publication_calls": 0,
        "historical_snapshot_reconstructed": False})

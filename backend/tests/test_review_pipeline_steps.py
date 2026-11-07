from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_review_approval_transitions_complete_previous_pipeline_steps() -> None:
    source = (ROOT / "backend" / "app" / "domain" / "review_publish.py").read_text(encoding="utf-8")

    assert '_complete_pipeline_step(session, version.id, MANAGER_REVIEW, "Manager review approved")' in source
    assert '_mark_pipeline_waiting(session, version.id, OWNER_REVIEW, "project_owner")' in source
    assert '_complete_pipeline_step(session, version.id, OWNER_REVIEW, "Project Owner review approved")' in source
    assert '_mark_pipeline_waiting(session, version.id, PUBLISH_STAGE, "publisher")' in source
    assert '_mark_pipeline_rejected(session, version.id, task.review_stage, "Review rejected")' in source


def test_publication_transitions_publish_index_and_graph_steps() -> None:
    source = (ROOT / "backend" / "app" / "domain" / "review_publish.py").read_text(encoding="utf-8")

    assert '_start_pipeline_step(session, version.id, PUBLISH_STAGE, "Publishing approved version")' in source
    assert '_complete_pipeline_step(session, version.id, PUBLISH_STAGE, "Publish authorized")' in source
    assert '_start_pipeline_step(session, version.id, "production_index", "Writing published index")' in source
    assert '_complete_pipeline_step(session, version.id, "production_index", "Published index written")' in source
    assert '_start_pipeline_step(session, version.id, GRAPH_SYNC_STAGE, "Synchronizing knowledge graph")' in source
    assert '_complete_pipeline_publication(session, version.id)' in source


def test_pipeline_step_helpers_clear_stale_waiting_state() -> None:
    source = (ROOT / "backend" / "app" / "domain" / "review_publish.py").read_text(encoding="utf-8")

    assert "def _mark_pipeline_waiting" in source
    assert 'step.status = "waiting_action"' in source
    assert "step.progress_percent = 0" in source
    assert "def _complete_pipeline_step" in source
    assert 'step.status = "completed"' in source
    assert "step.progress_percent = 100" in source
    assert "def _mark_pipeline_rejected" in source
    assert 'step.status = "review_rejected"' in source


def test_existing_review_pipeline_steps_are_normalized_by_migration() -> None:
    migration = (ROOT / "sql" / "migrations" / "V013__sync_review_pipeline_steps.sql").read_text(encoding="utf-8")

    assert "step.step_name = 'manager_review'" in migration
    assert "version.status IN ('pending_owner_review', 'approved', 'active')" in migration
    assert "step.step_name = 'owner_review'" in migration
    assert "version.status = 'pending_owner_review'" in migration
    assert "step.step_name = 'publish'" in migration
    assert "version.status = 'approved'" in migration
    assert "step.step_name IN ('publish', 'production_index', 'graph_sync')" in migration
    assert "version.status = 'active'" in migration

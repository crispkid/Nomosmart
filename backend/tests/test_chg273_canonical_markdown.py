from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from app.db.models import PipelineRun, PipelineRunStep
from markdown_live_support import markdown_workspace

from app.domain.markdown_artifacts import markdown_artifact_ref, normalize_source_mappings, paragraph_source_ranges, resolve_manual_source_mapping, resolve_markdown_artifact
from app.domain.extraction_pipeline import _create_chunks


def stored_pipeline(workspace, status):
    session,project,document,version=workspace
    pipeline=PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,
        run_type='auto_extraction',status=status,created_at=datetime.now(UTC))
    session.add(pipeline);session.flush()
    return pipeline


def stored_step(session, pipeline, **values):
    step=PipelineRunStep(run_id=pipeline.id,step_name='generate_markdown',**values)
    session.add(step);session.flush()
    return step


def test_paragraph_ranges_preserve_canonical_positions() -> None:
    source = "# Title\n\nBody 🚀\n\n- One\n- Two\n"
    ranges = paragraph_source_ranges(source)

    assert source[ranges["paragraph-1"].start : ranges["paragraph-1"].end] == "# Title"
    assert source[ranges["paragraph-2"].start : ranges["paragraph-2"].end] == "Body 🚀"
    assert source[ranges["paragraph-3"].start : ranges["paragraph-3"].end] == "- One\n- Two"


def test_legacy_global_and_anchor_local_offsets_resolve_exactly() -> None:
    source = "Alpha\n\n0123456789"

    global_mapping = normalize_source_mappings(
        "01234",
        [{"source_anchor": "paragraph-2", "start_offset": 7, "end_offset": 12}],
        source,
    )[0]
    local_mapping = normalize_source_mappings(
        "56789",
        [{"source_anchor": "paragraph-2", "view_mode": "original", "start_offset": 5, "end_offset": 10}],
        source,
    )[0]

    assert global_mapping["mapping_status"] == "resolved"
    assert global_mapping["offset_scope"] == "canonical_markdown"
    assert (global_mapping["anchor_start_offset"], global_mapping["anchor_end_offset"]) == (0, 5)
    assert local_mapping["mapping_status"] == "resolved"
    assert local_mapping["offset_scope"] == "source_anchor"
    assert (local_mapping["markdown_start_offset"], local_mapping["markdown_end_offset"]) == (12, 17)


def test_mismatch_fails_closed_without_fuzzy_matching() -> None:
    mapping = normalize_source_mappings(
        "not present",
        [{"source_anchor": "paragraph-1", "start_offset": 0, "end_offset": 4}],
        "Alpha",
    )[0]

    assert mapping["mapping_status"] == "unresolved"
    assert mapping["mapping_reason_code"] == "source_range_mismatch"
    assert mapping["markdown_start_offset"] is None


def test_completed_version_scoped_artifact_is_returned_without_trimming(markdown_workspace) -> None:
    session,_,_,version=markdown_workspace
    from app.core.config import get_settings
    from app.domain.extraction_pipeline import LiveOnlyOCRAdapter, _complete_step, _execute_step
    project, document = markdown_workspace[1:3]
    version.canonical_extension='.md'
    version.chunk_strategy={'source_text':'\n# Exact\n'}
    pipeline = stored_pipeline(markdown_workspace, "running")
    artifacts={}
    for name in ('parse_document', 'ocr_extract', 'generate_markdown'):
        # Execute actual native text stages; no model, adapter replacement or
        # invented completed provider/workflow state is used for this positive.
        artifact=_execute_step(session,get_settings(),None,LiveOnlyOCRAdapter(),
            project,document,version,pipeline,name,artifacts)
        assert artifact is not None
        artifacts[name]=artifact
        step=PipelineRunStep(run_id=pipeline.id,step_name=name,status='running')
        session.add(step);_complete_step(step,artifact)
        step.output_artifact_ref=artifact.ref;session.flush()
    assert artifacts['ocr_extract'].payload['skipped'] is True
    assert pipeline.status=='running'  # Not a published or completed LLM run.

    result = resolve_markdown_artifact(session, version)

    assert result.status == "available"
    assert result.reason_code is None
    assert result.text == "\n# Exact\n"


def test_artifact_ref_mismatch_and_processing_fail_closed(markdown_workspace) -> None:
    session,_,_,version=markdown_workspace
    version.markdown_artifact_uri=markdown_artifact_ref(version.id)
    pipeline = stored_pipeline(markdown_workspace,"running")
    step = stored_step(session,pipeline,status="running", output_artifact_ref=None, artifact_payload=None)
    processing = resolve_markdown_artifact(session, version)
    assert (processing.status, processing.reason_code, processing.text) == ("processing", "markdown_artifact_pending", None)

    step.status="completed";step.output_artifact_ref="artifact://wrong";step.artifact_payload={"markdown":"content"}
    session.flush()
    invalid = resolve_markdown_artifact(session, version)
    assert (invalid.status, invalid.reason_code, invalid.text) == ("invalid", "markdown_artifact_version_mismatch", None)


def test_artifact_unavailable_states_are_typed_and_never_fall_back(markdown_workspace) -> None:
    session,_,_,version=markdown_workspace
    version_id = version.id
    artifact_ref = markdown_artifact_ref(version_id)
    version.markdown_artifact_uri=artifact_ref
    assert resolve_markdown_artifact(session, version).status == "missing"
    pipeline=stored_pipeline(markdown_workspace,"running")
    assert resolve_markdown_artifact(session, version).status == "processing"
    pipeline.status="completed";session.flush()
    assert resolve_markdown_artifact(session, version).status == "missing"
    step=stored_step(session,pipeline,status="failed",output_artifact_ref=None,artifact_payload=None)
    assert resolve_markdown_artifact(session, version).status == "failed"
    step.status="cancelled";session.flush()
    assert resolve_markdown_artifact(session, version).status == "invalid"
    step.status="completed";step.output_artifact_ref=artifact_ref;step.artifact_payload={"markdown":"  "};session.flush()
    assert resolve_markdown_artifact(session, version).status == "invalid"


def test_manual_ranges_require_view_compatible_exact_coordinates() -> None:
    source = "First\n\n# Heading"
    markdown_mapping = resolve_manual_source_mapping(
        content="# Heading",
        markdown=source,
        source_anchor="paragraph-2",
        start_offset=7,
        end_offset=16,
        offset_scope="canonical_markdown",
        offset_unit="unicode_code_point",
    )
    original_mapping = resolve_manual_source_mapping(
        content="Heading",
        markdown=source,
        source_anchor="paragraph-2",
        start_offset=2,
        end_offset=9,
        offset_scope="source_anchor",
        offset_unit="unicode_code_point",
    )

    assert markdown_mapping and markdown_mapping["markdown_start_offset"] == 7
    assert original_mapping and (original_mapping["markdown_start_offset"], original_mapping["markdown_end_offset"]) == (9, 16)
    # CHG-304 exact-coordinate contract: rendered text offsets must not be
    # silently guessed as canonical Markdown offsets (the '# ' is two chars).
    assert resolve_manual_source_mapping(
        content="Heading", markdown=source, source_anchor="paragraph-2",
        start_offset=0, end_offset=7, offset_scope="source_anchor",
        offset_unit="unicode_code_point",
    ) is None
    assert resolve_manual_source_mapping(
        content="missing",
        markdown=source,
        source_anchor="paragraph-2",
        start_offset=0,
        end_offset=7,
        offset_scope="source_anchor",
        offset_unit="unicode_code_point",
    ) is None

    assert resolve_manual_source_mapping(
        content="First",
        markdown=source,
        source_anchor="paragraph-1",
        start_offset=0,
        end_offset=5,
        offset_scope="canonical_markdown",
        offset_unit="utf16",
    ) is None
    assert resolve_manual_source_mapping(
        content="First",
        markdown=source,
        source_anchor="missing",
        start_offset=0,
        end_offset=5,
        offset_scope="canonical_markdown",
        offset_unit="unicode_code_point",
    ) is None
    assert resolve_manual_source_mapping(
        content="First",
        markdown=source,
        source_anchor="paragraph-1",
        start_offset=0,
        end_offset=5,
        offset_scope="unknown",
        offset_unit="unicode_code_point",
    ) is None


def test_explicit_and_invalid_source_mapping_contracts() -> None:
    source = "Alpha\n\nBeta"
    explicit = normalize_source_mappings(
        "Beta",
        [{
            "source_anchor": "paragraph-2",
            "offset_scope": "canonical_markdown",
            "markdown_start_offset": 7,
            "markdown_end_offset": 11,
            "anchor_start_offset": 0,
            "anchor_end_offset": 4,
        }],
        source,
    )[0]
    assert explicit["mapping_status"] == "resolved"
    assert normalize_source_mappings("Beta", [], source) == []
    assert normalize_source_mappings("Beta", [{"source_anchor": "paragraph-2"}], source)[0]["mapping_reason_code"] == "source_range_missing"
    assert normalize_source_mappings("Beta", [{"source_anchor": "missing", "start_offset": 7, "end_offset": 11}], source)[0]["mapping_reason_code"] == "source_anchor_unresolved"
    assert normalize_source_mappings("Beta", [{"source_anchor": "paragraph-2", "start_offset": 7, "end_offset": 11}], None)[0]["mapping_reason_code"] == "markdown_artifact_unavailable"
    scope_mismatch = normalize_source_mappings(
        "Beta",
        [{"source_anchor": "paragraph-2", "start_offset": 7, "end_offset": 11, "offset_scope": "source_anchor"}],
        source,
    )[0]
    assert scope_mismatch["mapping_reason_code"] == "source_range_scope_mismatch"


def test_future_chunks_persist_exact_global_and_anchor_local_ranges(markdown_workspace) -> None:
    session,project,document,version=markdown_workspace
    markdown = "\nFirst 🚀\n\n\n  Second\n"

    chunks = _create_chunks(
        session,
        project,
        document,
        version,
        ["First 🚀", "Second"],
        markdown_source=markdown,
    )

    assert [(chunk.start_offset, chunk.end_offset) for chunk in chunks] == [(1, 8), (13, 19)]
    for chunk in chunks:
        mapping = chunk.source_mapping[0]
        assert mapping["mapping_status"] == "resolved"
        assert mapping["offset_unit"] == "unicode_code_point"
        assert markdown[mapping["markdown_start_offset"] : mapping["markdown_end_offset"]] == chunk.content
        assert (mapping["anchor_start_offset"], mapping["anchor_end_offset"]) == (0, len(chunk.content))

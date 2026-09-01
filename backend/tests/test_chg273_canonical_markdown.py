from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.domain.markdown_artifacts import markdown_artifact_ref, normalize_source_mappings, paragraph_source_ranges, resolve_manual_source_mapping, resolve_markdown_artifact
from app.domain.extraction_pipeline import _create_chunks


class ScalarSession:
    def __init__(self, *values: object) -> None:
        self.values = iter(values)

    def scalar(self, _statement):
        return next(self.values)


class ChunkSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def execute(self, _statement) -> None:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


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


def test_completed_version_scoped_artifact_is_returned_without_trimming() -> None:
    version_id = uuid4()
    artifact_ref = markdown_artifact_ref(version_id)
    version = SimpleNamespace(id=version_id, markdown_artifact_uri=artifact_ref)
    pipeline = SimpleNamespace(id=uuid4(), status="submission_ready", created_at=datetime.now(UTC))
    step = SimpleNamespace(status="completed", output_artifact_ref=artifact_ref, artifact_payload={"markdown": "\n# Exact\n"})

    result = resolve_markdown_artifact(ScalarSession(pipeline, step), version)

    assert result.status == "available"
    assert result.reason_code is None
    assert result.text == "\n# Exact\n"


def test_artifact_ref_mismatch_and_processing_fail_closed() -> None:
    version_id = uuid4()
    version = SimpleNamespace(id=version_id, markdown_artifact_uri=markdown_artifact_ref(version_id))
    pipeline = SimpleNamespace(id=uuid4(), status="running", created_at=datetime.now(UTC))
    pending = SimpleNamespace(status="running", output_artifact_ref=None, artifact_payload=None)
    processing = resolve_markdown_artifact(ScalarSession(pipeline, pending), version)
    assert (processing.status, processing.reason_code, processing.text) == ("processing", "markdown_artifact_pending", None)

    completed = SimpleNamespace(status="completed", output_artifact_ref="artifact://wrong", artifact_payload={"markdown": "content"})
    invalid = resolve_markdown_artifact(ScalarSession(pipeline, completed), version)
    assert (invalid.status, invalid.reason_code, invalid.text) == ("invalid", "markdown_artifact_version_mismatch", None)


def test_artifact_unavailable_states_are_typed_and_never_fall_back() -> None:
    version_id = uuid4()
    artifact_ref = markdown_artifact_ref(version_id)
    version = SimpleNamespace(id=version_id, markdown_artifact_uri=artifact_ref)
    completed_pipeline = SimpleNamespace(id=uuid4(), status="completed", created_at=datetime.now(UTC))
    running_pipeline = SimpleNamespace(id=uuid4(), status="running", created_at=datetime.now(UTC))

    assert resolve_markdown_artifact(ScalarSession(None), version).status == "missing"
    assert resolve_markdown_artifact(ScalarSession(running_pipeline, None), version).status == "processing"
    assert resolve_markdown_artifact(ScalarSession(completed_pipeline, None), version).status == "missing"
    failed = SimpleNamespace(status="failed", output_artifact_ref=None, artifact_payload=None)
    assert resolve_markdown_artifact(ScalarSession(completed_pipeline, failed), version).status == "failed"
    unexpected = SimpleNamespace(status="cancelled", output_artifact_ref=None, artifact_payload=None)
    assert resolve_markdown_artifact(ScalarSession(completed_pipeline, unexpected), version).status == "invalid"
    empty = SimpleNamespace(status="completed", output_artifact_ref=artifact_ref, artifact_payload={"markdown": "  "})
    assert resolve_markdown_artifact(ScalarSession(completed_pipeline, empty), version).status == "invalid"


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
        start_offset=0,
        end_offset=7,
        offset_scope="source_anchor",
        offset_unit="unicode_code_point",
    )

    assert markdown_mapping and markdown_mapping["markdown_start_offset"] == 7
    assert original_mapping and (original_mapping["markdown_start_offset"], original_mapping["markdown_end_offset"]) == (9, 16)
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


def test_future_chunks_persist_exact_global_and_anchor_local_ranges() -> None:
    session = ChunkSession()
    project = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(id=uuid4(), title="Exact source")
    version = SimpleNamespace(id=uuid4(), embedding_model_id=None)
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

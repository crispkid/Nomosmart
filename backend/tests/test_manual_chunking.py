from __future__ import annotations

from pathlib import Path


def test_manual_chunk_creation_assigns_unique_temporary_indexes_before_flush() -> None:
    source = (Path(__file__).resolve().parents[1] / "app/api/routes/documents.py").read_text(encoding="utf-8")

    assert "def _next_chunk_index" in source
    assert "select(func.max(Chunk.chunk_index)).where(Chunk.document_version_id == version_id)" in source
    assert "for index, item in enumerate([*new_segments, manual_chunk], start=_next_chunk_index(session, version.id)):" in source
    assert "item.chunk_index = index" in source
    assert "session.flush()\n    _reindex_active_chunks" in source
    assert "version_chunks = list(" in source
    assert "temporary_base = min(min_index, 0) - len(version_chunks) - 1_000" in source
    assert "chunk.chunk_index = temporary_base - index" in source
    assert "active_chunks = sorted([chunk for chunk in version_chunks if chunk.status == \"active\"], key=_chunk_source_sort_key)" in source
    assert "def _chunk_source_sort_key" in source
    assert "def _source_anchor_rank" in source
    assert "def _manual_split_text" in source
    assert "def _manual_split_text(chunk: Chunk) -> str:\n    return chunk.markdown_content or chunk.content" in source
    assert "build_manual_chunk_representation(" in source
    assert "retrieval_text=content" not in source
    assert "resolve_manual_source_mapping" in source
    assert 'offset_unit = payload.offset_unit or "unicode_code_point"' in source

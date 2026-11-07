from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes.serving import _same_section_ancestry, _select_prompt_chunks
from app.core.errors import AppError
from app.db.models import Chunk
from app.domain.chat_citations import CitationStreamCompactor, compact_citation_view
from app.domain.chat_retrieval import fuse_ranked_hits, grapheme_length, is_structural_only


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_compacts_used_sources_in_first_marker_order_without_mutating_raw_evidence() -> None:
    citations = [
        {"chunk_id": str(uuid4()), "chunk_index": index, "excerpt": f"source {index}"}
        for index in range(1, 6)
    ]
    original = deepcopy(citations)

    view = compact_citation_view("Grounded [3], then [5], and [3] again.", citations)

    assert view.answer == "Grounded [1], then [2], and [1] again."
    assert view.source_ordinals == (3, 5)
    assert [item["chunk_index"] for item in view.citations] == [3, 5]
    assert citations == original
    assert view.citations[0] is not citations[2]


def test_compaction_is_idempotent_and_preserves_invalid_legacy_markers() -> None:
    citations = [{"chunk_index": 3}, {"chunk_index": 5}]
    first = compact_citation_view("Answer [1][2][1] and invalid [9].", citations)
    second = compact_citation_view(first.answer, first.citations)

    assert second.answer == first.answer
    assert second.citations == first.citations
    assert compact_citation_view("No marker answer.", citations).citations == []
    assert compact_citation_view("Legacy [9].", citations).answer == "Legacy [9]."
    assert compact_citation_view("Legacy [9].", citations).citations == []


def test_stream_compactor_handles_split_markers_and_matches_final_view() -> None:
    stream = CitationStreamCompactor(5)

    parts = [
        stream.feed("Grounded ["),
        stream.feed("3], then [5"),
        stream.feed("] and [3]."),
        stream.finish(),
    ]

    assert "".join(parts) == "Grounded [1], then [2] and [1]."
    assert stream.source_ordinals == (3, 5)

    invalid = CitationStreamCompactor(2)
    with pytest.raises(AppError) as captured:
        invalid.feed("Invalid [3].")
    assert captured.value.code == "provider_response_contract_invalid"


def test_reciprocal_rank_fusion_includes_vector_keyword_and_shared_hits() -> None:
    vector = [
        {"_id": "vector-only", "_source": {"chunk_id": "a"}},
        {"_id": "shared", "_source": {"chunk_id": "b"}},
    ]
    keyword = [
        {"_id": "shared", "_source": {"chunk_id": "b"}},
        {"_id": "keyword-only", "_source": {"chunk_id": "c"}},
    ]

    fused = fuse_ranked_hits(vector, keyword)

    assert [hit["_id"] for hit in fused] == ["shared", "vector-only", "keyword-only"]
    assert fused[0]["_score"] == (1 / 62) + (1 / 61)
    assert fused[1]["_score"] == 1 / 61
    assert fused[2]["_score"] == 1 / 62
    assert "_score" not in vector[0]


def test_reciprocal_rank_fusion_deduplicates_and_ties_by_stable_identity() -> None:
    vector = [{"_id": "b"}, {"_id": "b"}]
    keyword = [{"_id": "a"}, {"_id": None}]

    assert [hit["_id"] for hit in fuse_ranked_hits(vector, keyword)] == ["a", "b"]


def test_structural_classifier_handles_headings_lead_ins_and_graphemes() -> None:
    assert is_structural_only("## 1. 架構設計願景與核心原則")
    assert is_structural_only("架構設計嚴守以下三大核心原則：")
    assert not is_structural_only("1. **控制與資料平面分離：** 詳細內容")
    assert not is_structural_only("| 欄位 | 內容 |：")
    assert grapheme_length("e\u0301") == 1
    assert grapheme_length("👨‍👩‍👧‍👦") == 1


def test_chunk_maps_existing_section_path_and_text_boundaries_fail_closed() -> None:
    assert "section_path" in Chunk.__mapper__.attrs
    assert _same_section_ancestry(None, "Section B")
    assert _same_section_ancestry("Section A", "Section A")
    assert not _same_section_ancestry("Section A", "Section B")


def test_prompt_selection_promotes_authorized_content_bearing_successor() -> None:
    project_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    lead_in = _chunk(project_id, document_id, version_id, 4, "架構設計嚴守以下三大核心原則：")
    principles = _chunk(
        project_id,
        document_id,
        version_id,
        5,
        "1. 控制與資料平面分離\n2. 適材適用的雙軌推論\n3. 零信任與精準問責",
    )
    next_heading = _chunk(project_id, document_id, version_id, 6, "## 2. 基礎設施與網路架構")
    chunks = {item.id: item for item in (lead_in, principles, next_heading)}
    positions = {
        (item.document_id, item.document_version_id, item.chunk_index): item
        for item in chunks.values()
    }
    hits = [_hit(lead_in), _hit(principles), _hit(next_heading)]

    selected = _select_prompt_chunks(
        hits,
        chunks_by_id=chunks,
        chunks_by_position=positions,
        project_id=project_id,
        scoped_version_ids={version_id},
        limit=2,
    )

    assert [chunk.chunk_index for _hit_value, chunk in selected] == [5, 6]
    assert selected[0][1].id == principles.id
    assert len(selected) == 2


def test_prompt_selection_stops_at_heading_and_rejects_scope_mismatch() -> None:
    project_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    heading = _chunk(project_id, document_id, version_id, 2, "## Section")
    next_heading = _chunk(project_id, document_id, version_id, 3, "### Subsection")
    chunks = {item.id: item for item in (heading, next_heading)}
    positions = {
        (item.document_id, item.document_version_id, item.chunk_index): item
        for item in chunks.values()
    }
    selected = _select_prompt_chunks(
        [_hit(heading)],
        chunks_by_id=chunks,
        chunks_by_position=positions,
        project_id=project_id,
        scoped_version_ids={version_id},
        limit=1,
    )
    denied = _select_prompt_chunks(
        [_hit(heading)],
        chunks_by_id=chunks,
        chunks_by_position=positions,
        project_id=uuid4(),
        scoped_version_ids={version_id},
        limit=1,
    )

    assert selected[0][1].id == heading.id
    assert denied == []


def test_shared_response_paths_use_compaction_and_preserve_raw_storage_contract() -> None:
    serving = _read("backend/app/api/routes/serving.py")
    public_api = _read("backend/app/api/routes/public_api.py")
    documents = _read("backend/app/api/routes/documents.py")
    approvals = _read("backend/app/api/routes/approvals.py")

    assert "reference_docs=[citation_persistence_payload(citation) for citation in citations]" in serving
    assert "compact_citation_view(answer, citations)" in serving
    assert "def _chat_record_response" in serving
    assert "def _validation_item_response" in serving
    assert serving.count("compact_citation_view(") >= 5
    assert "validate_citation_markers(raw_answer, len(prepared[3]))" in public_api
    assert "raw_answer=raw_answer" in public_api
    assert "compact_citation_view(row.answer, citations)" in documents
    assert "compact_citation_view(record.answer, citations)" in approvals


def _chunk(project_id, document_id, version_id, index: int, content: str):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        document_id=document_id,
        document_version_id=version_id,
        chunk_index=index,
        content=content,
        section_path=None,
    )


def _hit(chunk) -> dict:
    return {
        "_id": str(chunk.id),
        "_score": 0.01,
        "_source": {
            "chunk_id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "document_version_id": str(chunk.document_version_id),
        },
    }


def _read(path: str) -> str:
    relative = path.removeprefix("backend/")
    return (BACKEND_ROOT / relative).read_text(encoding="utf-8")

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chunk_tagging_allows_empty_without_relaxing_document_tags() -> None:
    provider = read("backend/app/domain/ai_provider.py")
    pipeline = read("backend/app/domain/extraction_pipeline.py")
    documents = read("backend/app/api/routes/documents.py")

    assert "allow_empty: bool = False" in provider
    assert "_build_tagging_prompt(trimmed, max_tags, resolved_prompt.content, allow_empty=allow_empty)" in provider
    assert "_parse_tag_result(content, allow_empty=allow_empty)" in provider
    assert "若內容沒有明確重點，請輸出空 JSON 陣列 []" in provider
    assert "if not tags and not allow_empty" in provider

    assert "document_result = _generate_pipeline_tags(" in pipeline
    assert 'usage_purpose="document_auto_tag"' in pipeline
    assert "chunk_result = _generate_pipeline_tags(" in pipeline
    assert 'usage_purpose="chunk_auto_tag"' in pipeline
    assert "generate_knowledge_tags(text=text, model=model, max_tags=max_tags, settings=settings, system_prompt=prompt, allow_empty=allow_empty)" in pipeline
    assert "_result_tags(chunk_result, allow_empty=True)" in pipeline
    assert "if not tags and not allow_empty" in pipeline

    assert 'usage_purpose="chunk_auto_tag"' in documents
    assert 'usage_purpose="document_auto_tag"' in documents
    assert "generate_knowledge_tags(text=text, model=model, max_tags=max_tags, system_prompt=prompt, allow_empty=allow_empty)" in documents


def test_upload_progress_detail_contract_is_traceable() -> None:
    modal = read("frontend/src/components/KnowledgeSourceModals.tsx")
    import_page = read("frontend/src/app/project/[id]/import/page.tsx")
    css = read("frontend/src/app/globals.css")
    zh = read("frontend/src/i18n/locales/zh.json")
    en = read("frontend/src/i18n/locales/en.json")

    assert "CANONICAL_UPLOAD_PIPELINE_STEPS" in modal
    assert "localUploadProgressSteps" in modal
    assert "progressDetailsOpen" in modal
    assert "liveProgressDocuments" in modal
    assert "upload-progress-detail-toggle" in modal
    assert "uploadProgressShowDetails" in modal
    assert "uploadProgressHideDetails" in modal
    assert "uploadProgressWaitingLivePipeline" in modal
    assert "onProgressDocuments?.(summaries)" in import_page
    assert "setLiveProgressDocuments" in modal
    assert ".upload-progress-detail-toggle" in css
    assert ".upload-progress-detail-panel" in css
    assert ".upload-progress-step-list" in css
    assert '"uploadProgressShowDetails": "展開處理細節"' in zh
    assert '"uploadProgressShowDetails": "Show processing details"' in en

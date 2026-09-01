from __future__ import annotations

from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AIModel, DocumentVersion
from app.domain import extraction_pipeline, office_parser
from app.domain.docx_security import inspect_docx_package
from app.domain.document_imports import UploadedFilePayload, validate_file_payload
from app.domain.uploads import canonical_extension


CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def docx_bytes(*, document_xml: bytes | None = None, comments: bool = False, unsafe_name: str | None = None) -> bytes:
    document = document_xml or b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Policy content</w:t></w:r></w:p></w:body>
</w:document>"""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", document)
        if comments:
            archive.writestr("word/comments.xml", b"<w:comments xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"/>")
        if unsafe_name:
            archive.writestr(unsafe_name, b"unsafe")
    return output.getvalue()


def test_docx_only_upload_contract_and_real_package_validation() -> None:
    settings = Settings(_env_file=None, app_env="development")
    valid = docx_bytes()
    name, extension = validate_file_payload(
        UploadedFilePayload(
            filename="policy.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=valid,
        ),
        settings,
    )
    assert name == "policy.docx"
    assert extension == ".docx"
    with pytest.raises(AppError) as legacy:
        validate_file_payload(UploadedFilePayload(filename="legacy.doc", content_type="application/msword", content=b"\xd0\xcf\x11\xe0"), settings)
    assert legacy.value.code == "unsupported_upload_type"
    with pytest.raises(ValueError):
        canonical_extension("legacy.doc")


def test_docx_inspection_records_comments_and_revisions() -> None:
    document = b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:ins><w:r><w:t>Final text</w:t></w:r></w:ins></w:p></w:body>
</w:document>"""
    package = docx_bytes(document_xml=document, comments=True)
    inspection = inspect_docx_package(package, max_source_bytes=len(package))
    assert inspection.has_comments is True
    assert inspection.revision_count == 1
    assert inspection.visible_text_nodes == 1


def test_docx_inspection_rejects_renamed_zip_and_unsafe_paths() -> None:
    with pytest.raises(AppError) as renamed_zip:
        inspect_docx_package(b"PK\x03\x04not-a-word-package", max_source_bytes=1024)
    assert renamed_zip.value.code == "invalid_docx_package"
    with pytest.raises(AppError) as traversal:
        inspect_docx_package(docx_bytes(unsafe_name="../escape.png"), max_source_bytes=1024 * 1024)
    assert traversal.value.code == "invalid_docx_package"


def test_legacy_doc_reextraction_fails_before_runtime_or_storage_access() -> None:
    settings = Settings(_env_file=None, app_env="development")
    with pytest.raises(AppError) as error:
        office_parser.parse_office_document(settings, DocumentVersion(canonical_extension=".doc"))
    assert error.value.code == "legacy_doc_reextraction_unsupported"
    with pytest.raises(AppError) as extraction_error:
        extraction_pipeline._parse_text(settings, DocumentVersion(canonical_extension=".doc", chunk_strategy={}))
    assert extraction_error.value.code == "legacy_doc_reextraction_unsupported"


def test_pandoc_runtime_settings_and_image_payload_contract() -> None:
    settings = Settings(_env_file=None, app_env="development")
    assert settings.pandoc_command == "pandoc"
    assert settings.pandoc_sandbox_command == "bwrap"
    assert settings.pandoc_cache_dir.endswith("nomosmart-pandoc-cache")
    model = AIModel(id=uuid4(), name="ocr", provider="OpenAI", model_type="OCR", config={"model_name": "gpt-test"})
    version = DocumentVersion(id=uuid4(), original_file_name="scan.docx", canonical_extension=".docx")
    payload = extraction_pipeline._openai_ocr_payload(model, version, [("page.png", "image/png", b"\x89PNG\r\n\x1a\ncontent")], "")
    content = payload["input"][1]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_media_magic_and_markdown_rewrite_are_fail_closed() -> None:
    assert office_parser._media_kind(b"\x89PNG\r\n\x1a\ncontent") == (".png", "image/png")
    with pytest.raises(AppError) as unsupported:
        office_parser._media_kind(b"<svg onload='bad'/>")
    assert unsupported.value.code == "pandoc_media_type_unsupported"
    rewritten = office_parser._rewrite_media_references("![diagram](media/media/image1.png)", {"media/media/image1.png": "artifact://document_versions/v/media/sha.png"})
    assert rewritten == "![diagram](artifact://document_versions/v/media/sha.png)"

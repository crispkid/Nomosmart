"""CHG-342: current format contract; original Word cases are indexed in docs.

Only actual bytes/domain calls. No adapter, process, storage or service double.
"""
from uuid import uuid4
import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AIModel, DocumentVersion
from app.domain import extraction_pipeline
from app.domain.document_imports import UploadedFilePayload, validate_file_payload
from app.domain.uploads import canonical_extension, validate_source_extension
from docx_source_samples import docx_bytes
from scripts.native_pdf_input import pdf_input


def test_docx_only_upload_contract_and_real_package_validation():
    settings = Settings(_env_file=None)
    for name, body in [('policy.docx', docx_bytes()), ('legacy.doc', b'\xd0\xcf\x11\xe0')]:
        with pytest.raises(AppError) as error:
            validate_file_payload(UploadedFilePayload(name, None, body), settings)
        assert error.value.code == 'unsupported_upload_type'
    # Recognizing a historical extension must not make it acceptable for writing.
    assert canonical_extension('history.DOCX') == '.docx'
    with pytest.raises(ValueError):
        validate_source_extension('history.DOCX', http_response=True)


def test_docx_with_comments_and_revisions_is_rejected():
    document = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:ins><w:r><w:t>Final text</w:t></w:r></w:ins></w:p></w:body></w:document>'
    with pytest.raises(AppError) as error:
        validate_file_payload(UploadedFilePayload('revisions.docx', None, docx_bytes(document_xml=document, comments=True)), Settings(_env_file=None))
    assert error.value.code == 'unsupported_upload_type'


def test_docx_inspection_rejects_renamed_zip_and_unsafe_paths():
    for body in (docx_bytes(), docx_bytes(unsafe_name='../escape.png')):
        for name in ('renamed.txt', 'renamed.md', 'renamed.pdf'):
            with pytest.raises(AppError) as error:
                validate_file_payload(UploadedFilePayload(name, None, body), Settings(_env_file=None))
            assert error.value.code == 'invalid_file_signature'


@pytest.mark.parametrize('extension', ['.doc', '.docx', '.csv', '.json', '.png', '.html'])
def test_legacy_doc_reextraction_fails_before_runtime_or_storage_access(extension):
    with pytest.raises(AppError) as error:
        extraction_pipeline._parse_document_payload(Settings(_env_file=None), DocumentVersion(canonical_extension=extension, chunk_strategy={'source_text': 'old cached source'}))
    assert error.value.code == 'unsupported_upload_type'


def test_pandoc_runtime_settings_and_image_payload_contract():
    settings = Settings(_env_file=None, pandoc_command='', pandoc_timeout_seconds='retired')
    assert not any(name.startswith('pandoc_') for name in type(settings).model_fields)
    # Genuine synthetic PNG input; serializing the PDF image payload makes no model call.
    import struct, zlib
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff')) + chunk(b'IEND', b'')
    model = AIModel(id=uuid4(), name='ocr', provider='OpenAI', model_type='OCR', config={'model_name': 'serialization-only'})
    version = DocumentVersion(id=uuid4(), original_file_name='scan.pdf', canonical_extension='.pdf')
    payload = extraction_pipeline._openai_ocr_payload(model, version, [('page.png', 'image/png', png)], '')
    content = payload['input'][1]['content']
    assert content[1]['type'] == 'input_image'
    assert content[1]['image_url'].startswith('data:image/png;base64,')


@pytest.mark.parametrize('extension', ['.pdf', '.txt', '.md', '.MARKDOWN', '.TXT', '.PDF'])
def test_supported_document_inputs(extension):
    body = pdf_input() if extension.lower() == '.pdf' else '中文 😀\n# 標題\n'.encode()
    name, ext = validate_file_payload(UploadedFilePayload('policy' + extension, None, body), Settings(_env_file=None))
    assert name.endswith(extension)
    assert ext == ('.md' if extension == '.MARKDOWN' else extension.lower())


@pytest.mark.parametrize('extension', ['.doc', '.docx', '.rtf', '.odt', '.ppt', '.pptx', '.xls', '.xlsx', '.html', '.csv', '.json', '.zip', '.png', '.jpg'])
def test_all_other_document_formats_are_rejected(extension):
    with pytest.raises(AppError) as error:
        validate_file_payload(UploadedFilePayload('policy' + extension, None, b'content'), Settings(_env_file=None))
    assert error.value.code == 'unsupported_upload_type'


@pytest.mark.parametrize('body', [b'a' * 8192 + b'\xff', b'a\x00b', b'<!DOCTYPE html><html>page</html>', b'<html>page</html>', b'%PDF-1.4\n', b'\x89PNG\r\n\x1a\n', docx_bytes()], ids=[None, None, None, None, None, None, 'actual-ooxml-archive'])
def test_binary_html_and_invalid_utf8_cannot_disguise_as_text(body):
    with pytest.raises(AppError) as error:
        validate_file_payload(UploadedFilePayload('renamed.txt', 'text/plain', body), Settings(_env_file=None))
    assert error.value.code == 'invalid_file_signature'


def test_utf8_boundary_and_structured_text_are_valid_txt():
    for body in (b'a' * 8191 + '中文'.encode(), b'{"text": "plain"}', b'name,value\none,two\n'):
        assert validate_file_payload(UploadedFilePayload('notes.txt', 'text/plain', body), Settings(_env_file=None))[1] == '.txt'


@pytest.mark.parametrize('name,mime,body', [('data.json', 'application/json', b'{"source":"owned"}'), ('data.csv', 'text/csv', b'name,value\none,two\n')])
def test_api_data_exception_is_source_specific(name, mime, body):
    file = UploadedFilePayload(name, mime, body)
    with pytest.raises(AppError) as error:
        validate_file_payload(file, Settings(_env_file=None))
    assert error.value.code == 'unsupported_upload_type'
    assert validate_file_payload(file, Settings(_env_file=None), http_response=True)[0] == name
    version = DocumentVersion(canonical_extension='.' + name.split('.')[-1], chunk_strategy={'sync_adapter': 'http_api', 'source_text': body.decode()})
    assert extraction_pipeline._parse_document_payload(Settings(_env_file=None), version)['canonical_markdown'] == body.decode()
    assert extraction_pipeline._has_reliable_text_layer(version)


@pytest.mark.parametrize('mime', ['text/html', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'image/png'])
def test_explicit_mime_disguise_is_rejected(mime):
    with pytest.raises(AppError) as error:
        validate_file_payload(UploadedFilePayload('notes.txt', mime, b'plain'), Settings(_env_file=None))
    assert error.value.code == 'invalid_file_signature'

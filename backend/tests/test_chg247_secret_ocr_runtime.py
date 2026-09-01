from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import paramiko
import pytest

from app.core.errors import AppError
from app.domain.extraction_pipeline import _tesseract_extension, _tesseract_languages
from app.integrations.remote_sources import _sftp_authentication


ROOT = Path(__file__).resolve().parents[2]


def test_sftp_password_and_private_key_auth_disable_ambient_key_discovery() -> None:
    assert _sftp_authentication(paramiko, "password-value") == {"password": "password-value"}
    assert _sftp_authentication(paramiko, json.dumps({"password": "json-password"})) == {
        "password": "json-password"
    }

    generated = paramiko.RSAKey.generate(1024)
    private_key = StringIO()
    generated.write_private_key(private_key)
    authentication = _sftp_authentication(
        paramiko,
        json.dumps({"private_key": private_key.getvalue(), "passphrase": None}),
    )
    assert isinstance(authentication["pkey"], paramiko.RSAKey)

    source = (ROOT / "backend/app/integrations/remote_sources.py").read_text(encoding="utf-8")
    assert "look_for_keys=False" in source
    assert "allow_agent=False" in source
    assert "key_filename" not in source
    assert "TemporaryDirectory" not in source


def test_sftp_private_key_errors_are_safe() -> None:
    for value in ('{"private_key":', '{"private_key": ""}', '{"passphrase": 123}'):
        with pytest.raises(AppError) as error:
            _sftp_authentication(paramiko, value)
        assert error.value.code in {"sftp_credential_invalid", "sftp_private_key_invalid"}
        assert value not in error.value.message


def test_tesseract_input_and_language_contract_is_bounded() -> None:
    assert _tesseract_extension("scan.bin", "application/pdf") == ".pdf"
    assert _tesseract_extension("scan.jpeg", "application/octet-stream") == ".jpeg"
    assert _tesseract_languages({"languages": ["zh-TW", "en-US", "chi_tra"]}) == "chi_tra+eng"
    with pytest.raises(AppError) as error:
        _tesseract_extension("source.txt", "text/plain")
    assert error.value.code == "ocr_tesseract_input_unsupported"
    with pytest.raises(AppError) as error:
        _tesseract_languages({"languages": ["eng;curl"]})
    assert error.value.code == "ocr_language_invalid"


def test_tesseract_container_and_sandbox_are_real_and_networkless() -> None:
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    source = (ROOT / "backend/app/domain/extraction_pipeline.py").read_text(encoding="utf-8")
    assert "tesseract-ocr=${TESSERACT_VERSION}" in dockerfile
    assert "tesseract-ocr-chi-tra=${TESSDATA_VERSION}" in dockerfile
    assert "tesseract-ocr-eng=${TESSDATA_VERSION}" in dockerfile
    assert "sandboxed-tesseract" in source
    assert '"--unshare-net"' in source
    assert "RLIMIT_CORE" in source
    assert "adapter_source=\"deterministic" not in source

"""Native arithmetic/schema checks; live database/API/provider checks run separately."""
import pytest
from pydantic import ValidationError
from app.core.errors import AppError
from app.domain.ocr_token_settings import OCRTokenSettings, from_snapshot
from app.api.schemas import SystemParametersUpdatePayload


def test_independent_page_and_document_limits():
    p = OCRTokenSettings(10000, 1000000)
    assert p.request_limit(1000000) == 10000
    assert p.request_limit(998000) == 10000
    assert p.request_limit(37) == 37
    with pytest.raises(AppError): p.request_limit(0)


@pytest.mark.parametrize("page,document", [(0,10000),(-1,10000),(True,10000),(1.2,10000),(10000,9999),(1,2147483648),(1,None)])
def test_invalid_budget_values_rejected(page, document):
    with pytest.raises(AppError): OCRTokenSettings(page, document)


def test_snapshot_integrity_and_legacy_absence():
    p=OCRTokenSettings(10000,1000000)
    assert from_snapshot(p.snapshot()) == p
    assert from_snapshot({}) is None
    with pytest.raises(AppError): from_snapshot({**p.snapshot(),"ocr_document_max_tokens":1000001})
    with pytest.raises(AppError): from_snapshot({"ocr_page_max_output_tokens":10000})


@pytest.mark.parametrize("value", [None,False,1.5,"10000",0,-2,2147483648])
def test_put_strict_integer_or_null_rejection(value):
    payload=dict(max_upload_size_mb=100, default_timezone="Asia/Taipei", staging_index_ttl_days=7, ocr_page_max_output_tokens=value)
    with pytest.raises(ValidationError): SystemParametersUpdatePayload(**payload)


def test_legacy_put_leaves_new_values_unset():
    payload=SystemParametersUpdatePayload(max_upload_size_mb=100,default_timezone="Asia/Taipei",staging_index_ttl_days=7)
    assert not {"ocr_page_max_output_tokens","ocr_document_max_tokens"} & payload.model_dump(exclude_unset=True).keys()

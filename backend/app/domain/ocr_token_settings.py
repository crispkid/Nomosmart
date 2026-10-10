"""Database-owned output budgets for physical-page PDF OCR."""
from dataclasses import dataclass
from hashlib import sha256
import json

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import SystemParameter

PAGE_KEY = "ocr_page_max_output_tokens"
DOCUMENT_KEY = "ocr_document_max_tokens"
KEYS = (PAGE_KEY, DOCUMENT_KEY)
POLICY = "output-v1"
SNAPSHOT_KEYS = (*KEYS, "ocr_token_budget_basis", "ocr_token_budget_policy", "ocr_token_settings_hash")
MAXIMUM = 2147483647


@dataclass(frozen=True)
class OCRTokenSettings:
    page: int
    document: int

    def __post_init__(self):
        if (type(self.page) is not int or type(self.document) is not int
                or not 1 <= self.page <= self.document <= MAXIMUM):
            raise AppError("ocr_token_settings_invalid", "OCR output settings are invalid", status_code=422)

    @property
    def content_hash(self):
        body = {PAGE_KEY: self.page, DOCUMENT_KEY: self.document,
                "ocr_token_budget_basis": "output", "ocr_token_budget_policy": POLICY}
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def snapshot(self):
        return {PAGE_KEY: self.page, DOCUMENT_KEY: self.document,
                "ocr_token_budget_basis": "output", "ocr_token_budget_policy": POLICY,
                "ocr_token_settings_hash": self.content_hash}

    def request_limit(self, remaining):
        if type(remaining) is not int or remaining <= 0:
            raise AppError("ocr_document_output_budget_exhausted", "OCR document output budget is exhausted", status_code=422)
        return min(self.page, remaining)


def from_snapshot(snapshot):
    if not any(key in snapshot for key in SNAPSHOT_KEYS):
        return None  # Existing paid/historical work retains its original policy.
    if (not all(key in snapshot for key in SNAPSHOT_KEYS)
            or snapshot["ocr_token_budget_basis"] != "output"
            or snapshot["ocr_token_budget_policy"] != POLICY):
        raise AppError("ocr_token_settings_invalid", "OCR output snapshot is invalid", status_code=409)
    values = OCRTokenSettings(snapshot[PAGE_KEY], snapshot[DOCUMENT_KEY])
    if snapshot["ocr_token_settings_hash"] != values.content_hash:
        raise AppError("ocr_token_settings_invalid", "OCR output snapshot is invalid", status_code=409)
    return values


def from_rows(rows, *, defaults=False):
    by_key = {row.key: row for row in rows if row.key in KEYS}
    if set(by_key) != set(KEYS):
        raise AppError("ocr_token_settings_missing", "OCR output settings must be initialized", status_code=503)
    if any(row.value_type != "integer" or row.unit != "output_tokens" for row in by_key.values()):
        raise AppError("ocr_token_settings_invalid", "OCR output setting metadata is invalid", status_code=503)
    field = "default_value" if defaults else "value"
    return OCRTokenSettings(getattr(by_key[PAGE_KEY], field), getattr(by_key[DOCUMENT_KEY], field))


def load_settings(session):
    rows = list(session.scalars(select(SystemParameter).where(SystemParameter.key.in_(KEYS))
        .order_by(SystemParameter.key).execution_options(populate_existing=True)))
    return from_rows(rows)

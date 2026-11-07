"""Negative production-entry guard; source only in R12 A, not PDF acceptance."""
from __future__ import annotations
from time import perf_counter

import pytest

from app.core.config import Settings
from app.core.errors import AppError


@pytest.mark.parametrize("text_only", [False, True])
def test_pdf_entry_without_durable_claim_never_falls_back(text_only):
    from app.domain.extraction_pipeline import physical_pdf_inputs
    with pytest.raises(AppError) as failure:
        physical_pdf_inputs(Settings(_env_file=None), b"%PDF-untrusted-input",
                            text_only=text_only, deadline=perf_counter() + 60)
    assert failure.value.code == "file_processing_claim_required"

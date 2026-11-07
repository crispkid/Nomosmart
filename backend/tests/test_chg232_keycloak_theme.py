from __future__ import annotations

import pytest

from pathlib import Path



ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "deploy/keycloak/themes/nomosmart/login"


def test_realm_theme_contract_is_exact_and_rejects_partial_state():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: provider-specific realm theme no longer shipped; current acceptance: frontend login UI and KC374-T03/T04')


def test_theme_is_same_origin_bilingual_and_password_only():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: provider-specific realm theme no longer shipped; current acceptance: frontend login UI and KC374-T03/T04')

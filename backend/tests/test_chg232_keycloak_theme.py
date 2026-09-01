from __future__ import annotations

from pathlib import Path

from app.integrations.keycloak import (
    NOMOSMART_DEFAULT_LOCALE,
    NOMOSMART_LOGIN_THEME,
    NOMOSMART_SUPPORTED_LOCALES,
    nomosmart_realm_theme_ready,
    nomosmart_realm_theme_settings,
)


ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "deploy/keycloak/themes/nomosmart/login"


def test_realm_theme_contract_is_exact_and_rejects_partial_state() -> None:
    expected = {
        "loginTheme": "nomosmart",
        "internationalizationEnabled": True,
        "supportedLocales": ["en", "zh-TW"],
        "defaultLocale": "zh-TW",
    }
    assert NOMOSMART_LOGIN_THEME == "nomosmart"
    assert NOMOSMART_SUPPORTED_LOCALES == {"en", "zh-TW"}
    assert NOMOSMART_DEFAULT_LOCALE == "zh-TW"
    assert nomosmart_realm_theme_settings() == expected
    assert nomosmart_realm_theme_ready(expected)

    for key in expected:
        incomplete = dict(expected)
        incomplete.pop(key)
        assert not nomosmart_realm_theme_ready(incomplete)
    assert not nomosmart_realm_theme_ready({**expected, "supportedLocales": ["en", "zh-TW", "fr"]})


def test_theme_is_same_origin_bilingual_and_password_only() -> None:
    template = (THEME / "template.ftl").read_text(encoding="utf-8")
    login = (THEME / "login.ftl").read_text(encoding="utf-8")
    properties = (THEME / "theme.properties").read_text(encoding="utf-8")
    css = (THEME / "resources/css/nomosmart.css").read_text(encoding="utf-8")
    script = (THEME / "resources/js/formState.js").read_text(encoding="utf-8")
    zh = (THEME / "messages/messages_zh_TW.properties").read_text(encoding="utf-8")
    en = (THEME / "messages/messages_en.properties").read_text(encoding="utf-8")

    assert 'action="${url.loginAction}"' in login
    assert 'autocomplete="current-password"' in login
    assert not (THEME / "login-otp.ftl").exists()
    assert 'id="login-select-toggle"' in template
    assert 'msg("nomosmartLocaleZhTw")' in template
    assert 'msg("nomosmartLocaleEn")' in template
    assert 'role="${(message.type = \'error\')?then(\'alert\',\'status\')}"' in template
    assert "resourcesPath" in template and "resourcesCommonPath" in template
    assert "parent=keycloak.v2" in properties
    assert "locales=en,zh-TW" in properties
    assert "scripts=js/formState.js" in properties
    assert "@media (max-width: 480px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "linear-gradient" not in css and "radial-gradient" not in css
    assert "http://" not in template + css + script
    assert "https://" not in template + css + script
    assert "localStorage" not in script and "sessionStorage" not in script
    assert ".value" not in script and "fetch(" not in script
    assert "event.preventDefault()" in script
    assert "Step 1 of 2" not in en and "步驟 1／2" not in zh
    assert "one-time-code" not in template + login + en + zh

    def keys(source: str) -> set[str]:
        return {line.split("=", 1)[0] for line in source.splitlines() if line and not line.startswith("#")}

    assert keys(zh) == keys(en)

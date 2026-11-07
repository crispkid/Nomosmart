

def test_reauthentication_result_url_is_same_tab_and_allowlisted() -> None:
    # Structural guard only; runtime replay/redirect evidence stays with PROTAUTH.
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    auth = (root / "backend/app/api/routes/protocol_auth.py").read_text()
    panel = (root / "frontend/src/components/ProtocolIdentityPanel.tsx").read_text()
    assert "safe_return_path(flow.return_path)" in auth
    assert 'origin + "/login"' in auth
    assert 'window.location.assign(result.authorization_url)' in panel
    assert 'searchParams.delete("reauth")' in panel
    assert "window.open" not in panel

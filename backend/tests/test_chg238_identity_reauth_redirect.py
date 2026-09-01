from app.api.routes.identity_settings import _reauth_result_url


def test_reauthentication_result_url_is_same_tab_and_allowlisted() -> None:
    origin = "http://127.0.0.1:3000/"
    assert _reauth_result_url(origin, "success") == "http://127.0.0.1:3000/system?tab=identity&reauth=success"
    assert _reauth_result_url(origin, "cancelled") == "http://127.0.0.1:3000/system?tab=identity&reauth=cancelled"
    assert _reauth_result_url(origin, "error") == "http://127.0.0.1:3000/system?tab=identity&reauth=error"
    assert _reauth_result_url(origin, "success&token=secret") == "http://127.0.0.1:3000/system?tab=identity&reauth=error"

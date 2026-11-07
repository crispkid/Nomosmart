"""Real typed configuration inputs; fixed duration policies never change."""
import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_fixed_auth_durations_accept_deployment_environment_strings():
    settings = Settings(_env_file=None, auth_session_idle_seconds='1800', auth_flow_ttl_seconds='300', auth_emergency_ttl_seconds='900')
    assert (settings.auth_session_idle_seconds, settings.auth_flow_ttl_seconds, settings.auth_emergency_ttl_seconds) == (1800, 300, 900)


@pytest.mark.parametrize('field,value', [
    ('auth_session_idle_seconds', '1799'), ('auth_session_idle_seconds', '1801'),
    ('auth_session_idle_seconds', '28800'), ('auth_session_idle_seconds', 'forever'),
    ('auth_flow_ttl_seconds', '301'), ('auth_emergency_ttl_seconds', '1800'),
])
def test_fixed_auth_durations_reject_policy_changes(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})

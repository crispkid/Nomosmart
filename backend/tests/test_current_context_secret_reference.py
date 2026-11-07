"""Actual owned secret input plus real file boundaries; no provider substitutes."""
import json
import os
from pathlib import Path

import pytest

from current_live_support import _read_current_service_secret, load_current_context


def test_current_existing_reference_matches_encrypted_setting_without_json_copy():
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.security.auth_configuration import current_setting, read_secret

    context = load_current_context()
    protocol = context['protocol_tests']
    secret = protocol['ldap_service_password']
    with get_session_factory()() as session:
        assert secret == read_secret(session, get_settings(), current_setting(session), 'ldap_bind_password')
    serialized = json.dumps(protocol)
    assert secret not in serialized
    assert 'ldap_service_password' not in json.loads(serialized)
    expected = ('CHG414:new-readonly-bind' if context['change_id'] == 'CHG-414' else
                'docker:directory-bind.txt' if context['change_id'] in {'CHG-411', 'CHG-413'} else 'directory-bind.txt')
    assert json.loads(serialized)['ldap_service_password_reference'] == expected


@pytest.mark.parametrize('reference', ['../directory-bind.txt', '/tmp/directory-bind.txt', 'other.txt', ''])
def test_current_reference_rejects_other_paths_before_open(tmp_path, reference):
    with pytest.raises(AssertionError, match='current_secret_reference_invalid'):
        _read_current_service_secret(tmp_path.resolve() / 'context.json', reference)


def test_current_reference_rejects_public_file_mode(tmp_path):
    # Native file format input, never used for a real LDAP authentication.
    path = tmp_path / 'directory-bind.txt'
    path.write_text('non-credential-input')
    path.chmod(0o644)
    with pytest.raises(AssertionError):
        _read_current_service_secret(tmp_path.resolve() / 'context.json', path.name)


def test_current_reference_rejects_symlink_before_read(tmp_path):
    target = tmp_path / 'non-credential-input'
    target.write_text('file-guard-input')
    target.chmod(0o600)
    path = tmp_path / 'directory-bind.txt'
    path.symlink_to(target)
    with pytest.raises(OSError):
        _read_current_service_secret(tmp_path.resolve() / 'context.json', path.name)


def test_current_reference_rejects_hardlink_before_read(tmp_path):
    target = tmp_path / 'non-credential-input'
    target.write_text('file-guard-input')
    target.chmod(0o600)
    path = tmp_path / 'directory-bind.txt'
    os.link(target, path)
    with pytest.raises(AssertionError):
        _read_current_service_secret(tmp_path.resolve() / 'context.json', path.name)

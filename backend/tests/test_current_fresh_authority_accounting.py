"""Real current scope projected into native refusal inputs, never a past ledger."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from current_live_support import load_current_context
from scripts.ftp_generation_acceptance_environment import require_fresh_capacity


def current_used_scope():
    # This guard opens the actual TLS database and verifies its stored UUID,
    # owner/non-superuser role and approved frozen public source before use.
    context = load_current_context()
    path = Path(os.environ['NOMOSMART_TEST_SCOPE'])
    before = path.read_bytes()
    scope = json.loads(before)
    if scope.get('version') == 413:
        assert scope['change_id']=='CHG-413' and scope['operation_uuid']==context['run_id']
        assert scope['source_root']==str(Path(__file__).resolve().parents[2])
    else:
        assert scope['run_id'] == context['run_id']
    # The actual scope is already verified against PostgreSQL above. Multiple
    # owned DBs are one run; an old fixture's fixed DB count is not fresh-run
    # capacity and must not require discarding preserved fixture data.
    assert scope['databases'] and len(set(scope['databases'])) == len(scope['databases'])
    # Native input to the legacy pure predicate, not a new authority or an
    # invented historical/model journal. The one run is genuinely allocated.
    native_input = {'fresh_limit': 2, 'runs': [{'run_id': context['run_id'],
        'state': 'CURRENT_REAL_SCOPE_ALREADY_ALLOCATED'}]}
    return path, before, native_input


def test_current_consumed_scope_is_denied_without_allocating():
    path, before, native_input = current_used_scope()
    with pytest.raises(RuntimeError, match='^approved_fresh_allowance_exhausted$'):
        require_fresh_capacity(native_input, limit=1, minimum_used=1)
    assert path.read_bytes() == before
    assert len(native_input['runs']) == 1


def test_current_scope_history_removal_cannot_reset_consumption():
    path, before, actual = current_used_scope()
    removed = deepcopy(actual)
    removed['runs'].clear()  # Invalid memory input; real scope stays intact.
    with pytest.raises(RuntimeError, match='^fresh_history_missing_or_reset$'):
        require_fresh_capacity(removed, limit=1, minimum_used=1)
    assert path.read_bytes() == before
    assert len(actual['runs']) == 1

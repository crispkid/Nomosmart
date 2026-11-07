"""Exact approved D4: qualify retained live invariants and real C2/C3 rollback.

This consumer reuses genuine HTTP/SQL/Flyway receipts. It starts no services and
never relabels the four historical DB48/49 combinations or coverage as passed.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import xml.etree.ElementTree as ET

CASE_ID = 'C388-d8ed9a00937a'
OPERATION = '24c50237-b9ef-4dc7-b732-13e60933c5cf'


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(path, name):
    body = path.read_text()
    node = next(n for n in ast.walk(ast.parse(body))
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(body, node).encode()


def successful_cases(path):
    rows = ET.parse(path).findall('.//testcase')
    return {r.attrib['name']: r for r in rows
            if not any(c.tag in {'failure', 'error', 'skipped'} for c in r)}


def test_current_protocol_api_compatibility_54_with_qualified_live_receipts():
    path = Path(os.environ['NOMOSMART_CHG389_D4_CONTEXT'])
    assert path.is_absolute() and path.resolve() == path and not path.is_symlink()
    assert path.stat().st_uid == os.getuid() and not stat.S_IMODE(path.stat().st_mode) & 0o077
    assert not stat.S_IMODE(path.parent.stat().st_mode) & 0o077
    ctx = load(path)
    assert ctx['case_id'] == CASE_ID and ctx['operation_uuid'] == OPERATION
    for ref in ctx['frozen_references'].values():
        assert sha(Path(ref['path'])) == ref['sha256']
    repo = Path(ctx['repo_root'])
    approval = load(repo / 'docs/CHG-389-APPROVAL.json')
    amendment_path = repo / 'docs/CHG-389-CASE-AMENDMENT-PROPOSAL.json'
    assert approval['gate_4'] == 'APPROVED' and approval['operation_uuid'] == OPERATION
    assert approval['approved_proposals'][amendment_path.name] == sha(amendment_path)
    amendment = load(amendment_path)['exact_one_ID_override_only']
    assert amendment['proposal_id'] == CASE_ID
    original = repo / amendment['original_case'].split('::')[0]
    assert hashlib.sha256(function(original, amendment['original_case'].split('::')[1])).hexdigest() == amendment['original_case_body_SHA256']
    assert amendment['old_four_parameters_not_reexecuted_or_relabelled_PASS'] == [
        ['deployed', 48], ['deployed', 49], ['current', 48], ['current', 49]]

    reuse = load(Path(ctx['qualified_reuse']))
    producer = Path(reuse['producer_receipt_root'])
    inventory = load(producer / 'source-inventory.json')
    source = Path(ctx['retained_API_source_root'])
    image_inputs = load(Path(ctx['C3_actual_backend_build_inputs']))
    # The seven invariants target the exact C3 API contract selected by D4.
    # C4's separate external-bootstrap repair is qualified independently below;
    # these old bootstrap counters are never carried into current coverage.
    matched = 0
    for relative, row in image_inputs['files'].items():
        if not relative.startswith('app/'):
            continue
        name = 'backend/' + relative
        assert inventory['files'][name]['sha256'] == row['sha256'] == sha(source / name)
        if name != 'backend/app/deployment/bootstrap.py':
            assert sha(repo / name) == row['sha256']
        matched += 1
    assert matched == 165
    api_owner = load(producer / 'api-owner.json')
    assert api_owner['closed'] and api_owner['exit_code'] == 0
    assert api_owner['stopped_normally'] and api_owner['actually_reaped']
    assert load(producer / 'phase-owner.json')['closed']
    cleanup = load(producer / 'membership-module-cleanup.json')
    assert cleanup['original_business_fingerprints_equal']
    assert set(cleanup['four_genuine_sessions_logout'].values()) == {204}
    assert cleanup['new_users_roles_or_models'] == 0
    all_cases = ET.parse(producer / 'seven-membership-methods.xml').findall('.//testcase')
    cases = successful_cases(producer / 'seven-membership-methods.xml')
    assert len(all_cases) == len(cases) == 10
    observed = {r['method']: r for r in reuse['seven_intents']}
    assert set(observed) == set(amendment['all_seven_safety_intents_required_methods'])
    for method, row in observed.items():
        before, current = function(source / 'backend/tests/test_chg291_v049_live_rehearsal.py', method), function(original, method)
        assert before == current
        assert hashlib.sha256(before).hexdigest() == row['original_and_producer_body_SHA256']
        parameters = sorted(name for name in cases if name == method or name.startswith(method + '['))
        assert parameters == sorted(row['native_parameter_names'])
        assert len(parameters) == (4 if method == 'test_api_invalid_cardinality_atomic' else 1)
    assert amendment['original_invalid_role_cardinality_parameters'] == [[], ['editor', 'viewer'], ['viewer', 'viewer'], ['unknown']]
    assert all(load(p)['phase'] == 'EXACT_CURRENT_PROJECT_CLEANUP_COMPLETE'
               for p in producer.glob('membership-project-*.json'))
    assert len(list(producer.glob('membership-project-*.json'))) == 10

    migration_parameters = []
    for row in reuse['migration_reuse']:
        root = Path(row['receipt_root'])
        assert sha(root / 'tests.xml') == row['tests_xml_SHA256']
        assert sha(root / 'source-inventory.json') == row['source_inventory_SHA256']
        assert load(root / 'phase-owner.json')['closed']
        cases = successful_cases(root / 'tests.xml')
        assert set(row['selected_genuine_parameters']) <= set(cases)
        migration_parameters += row['selected_genuine_parameters']
    assert len(migration_parameters) == 10
    assert sum(name.startswith('test_actual_current_target_passes_numeric_equivalence[')
               for name in migration_parameters) == 4
    assert sum(name.startswith('test_bootstrap_rejects_before_other_checks_or_ensure_writes[')
               for name in migration_parameters) == 2
    assert any(name == 'test_real_history_states_fail_closed[previous-database_migration_target_missing]'
               for name in migration_parameters)
    assert any(name == 'test_cli_real_predecessor_exits_nonzero_with_safe_code[0-database_migration_target_missing]'
               for name in migration_parameters)

    journal_root = Path(ctx['lifecycle_root'])
    journal = load(journal_root / 'journal.json')
    assert journal['closed'] and journal['completed'] and journal['operation_uuid'] == OPERATION
    assert journal['normal_logins'] == journal['normal_logouts'] == journal['real_initial_syncs'] == journal['formal_finalize_calls'] == 1
    assert journal['true_C3_to_C2_rollback'] and journal['current_C4_restored']
    assert all(c['closed'] and c['actual_wait_reaped'] for c in journal['children'])
    steps = {r['step']: r for r in journal['steps']}
    for step in ['actual-c2-version-upgrade', 'actual-c3-version-upgrade',
                 'actual-C3-to-C2-Helm-rollback', 'actual-restore-C4-Helm-rollback']:
        assert steps[step]['actual_exit'] == 0 and steps[step]['actual_wait_reaped']
    assert steps['actual-C3-to-C2-Helm-rollback']['actual_command'][1] == 'rollback'
    assert steps['actual-C3-to-C2-Helm-rollback']['actual_command'][3] == str(journal['C2_rollback_target_revision'])
    c2_images = load(Path(ctx['C2_actual_platforms']))
    c3_images = load(Path(ctx['C3_actual_platforms']))
    imports = load(Path(ctx['actual_node_import_owner']))['images']
    for label, epoch, images in [('c2', 'c2', c2_images), ('c3', 'c3', c3_images),
                                 ('C2-after-true-rollback', 'c2', c2_images)]:
        runtime = steps[label + '-actual-image-and-source-qualified']['runtime']
        assert len(runtime) == 4
        assert {row['component'] for row in runtime} == {'backend', 'frontend', 'worker', 'beat'}
        for row in runtime:
            component = 'frontend' if row['component'] == 'frontend' else 'backend'
            exact = next(i for i in images if i['component'] == component and i['platform'] == 'linux/arm64')
            assert row['source'] == exact['source']
            assert row['expected_manifest_digest'] == exact['manifest_digest']
            assert row['requested_image'].endswith('@' + exact['manifest_digest'])
            assert row['actual_Pod_UID'] and row['runtime_container_ID'].startswith('containerd://')
            imported = next(i for i in imports if i['component'] == component and i['epoch'] == epoch)
            assert imported['actual_exit'] == 0 and imported['actual_wait_reaped']
            archive = Path(ctx['actual_node_import_root']) / (component + '-' + epoch + '-arm64.oci.tar')
            assert sha(archive) == imported['derived_import_archive_sha256']
            with tarfile.open(archive) as tar:
                index_bytes = tar.extractfile('index.json').read()
                assert 'sha256:' + hashlib.sha256(index_bytes).hexdigest() == imported['derived_index_digest']
                index = json.loads(index_bytes)
                assert len(index['manifests']) == 1
                descriptor = index['manifests'][0]
                assert descriptor['digest'] == exact['manifest_digest']
                assert descriptor['platform'] == {'architecture': 'arm64', 'os': 'linux'}
                manifest_bytes = tar.extractfile('blobs/sha256/' + descriptor['digest'].split(':')[1]).read()
                assert 'sha256:' + hashlib.sha256(manifest_bytes).hexdigest() == exact['manifest_digest']
                assert json.loads(manifest_bytes)['config']['digest'] == exact['config_digest']
            if not row['runtime_image_ID'].endswith('@' + imported['derived_index_digest']):
                # CRI can retain several repository index aliases for one exact
                # config. Qualify an alternative only through genuine inspecti
                # output, never through a guessed tag or a summary Boolean.
                metadata = load(Path(ctx['native_cri_image_metadata'][component]))
                assert metadata['status']['id'] == exact['config_digest']
                assert row['runtime_image_ID'] in metadata['status']['repoDigests']
        session = load(journal_root / (label + '-same-normal-session-response.private.json'))
        assert session['actual_status'] == 200 and session['actual_body']['authenticated'] is True
    before = load(journal_root / 'actual-business-fingerprints-before-C2-C3.stdout')
    assert before == load(journal_root / 'actual-business-fingerprints-after-C3-to-C2.stdout')
    assert before == load(journal_root / 'actual-business-fingerprints-after-current-restoration.stdout')
    post = load(journal_root / 'actual-one-sync-one-onboarding-zero-active-sessions.stdout')
    assert post == {'successful_syncs': 1, 'onboarding': 1, 'unrevoked_sessions': 0}
    assert steps['one-normal-logout']['actual_HTTP'] == 204
    native = load(journal_root / 'native-auto-bundled-missing-admin-guards.stdout')
    assert native['actual_profile_parameters'] == [
        {'mode': 'auto', 'actual_code': 'opensearch_service_identity_invalid'},
        {'mode': 'bundled', 'actual_code': 'opensearch_service_identity_invalid'}]
    c4_inputs = load(Path(ctx['C4_actual_backend_build_inputs']))
    assert native['source_bootstrap_SHA256'] == c4_inputs['files']['app/deployment/bootstrap.py']['sha256']

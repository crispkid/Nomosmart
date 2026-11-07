"""Real file-boundary controls; no service replacement or secret-file reads."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.public_source_inventory import PublicSourceInventory, SourceBoundaryError


def private_tree(tmp_path):
    root = (tmp_path / 'public-source').resolve()
    root.mkdir(mode=0o700)
    (root / 'source.py').write_text('value = 1\n')
    return root


def test_unknown_and_private_paths_are_rejected_before_content_open(tmp_path):
    root = private_tree(tmp_path)
    (root / 'operator-private.txt').write_text(os.urandom(32).hex())
    script = '''
import sys
from pathlib import Path
from scripts.public_source_inventory import PublicSourceInventory,SourceBoundaryError
root=Path(sys.argv[1]); inventory=PublicSourceInventory.freeze(root,['source.py'])
opened=[]
def observe(event,args):
    if event=='open': opened.append(str(args[0]))
sys.addaudithook(observe)
for name in ['operator-private.txt','../escape.py','.env','deploy/docker/nomosmart.env','deploy/generated/secret.txt','source.key']:
    try: inventory.read(name)
    except SourceBoundaryError as error: assert str(error)=='source_not_in_approved_inventory'
    else: raise AssertionError('unapproved_read_accepted')
assert opened==[], 'unapproved_path_opened_before_rejection'
try: PublicSourceInventory.freeze(root,['source.py','deploy/generated/secret.txt'])
except SourceBoundaryError: pass
else: raise AssertionError('private_path_accepted')
assert opened==[], 'valid_prefix_read_before_invalid_list_rejection'
'''
    env = {key: value for key, value in os.environ.items() if not key.startswith(('COVERAGE_', 'COV_CORE_'))}
    result = subprocess.run([sys.executable, '-B', '-c', script, str(root)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, 'real_file_boundary_child_failed'


def test_symlinks_hardlinks_and_parent_escape_fail_closed(tmp_path):
    root = private_tree(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'public.py').write_text('outside = True\n')
    (root / 'alias.py').symlink_to(root / 'source.py')
    (root / 'directory').symlink_to(outside, target_is_directory=True)
    os.link(root / 'source.py', root / 'hardlink.py')
    for name in ['alias.py', 'directory/public.py', 'hardlink.py', '../outside/public.py', '/absolute.py']:
        with pytest.raises(SourceBoundaryError):
            PublicSourceInventory.freeze(root, [name])


def test_frozen_bytes_and_executable_mode_detect_actual_drift(tmp_path):
    root = private_tree(tmp_path)
    inventory = PublicSourceInventory.freeze(root, ['source.py'])
    assert inventory.read('source.py') == (b'value = 1\n', False)
    (root / 'source.py').write_text('value = 2\n')
    with pytest.raises(SourceBoundaryError, match='source_content_drift'):
        inventory.read('source.py')
    (root / 'source.py').write_text('value = 1\n')
    (root / 'source.py').chmod(0o700)
    with pytest.raises(SourceBoundaryError, match='source_content_drift'):
        inventory.read('source.py')


def test_private_manifest_digest_and_exclusive_copy(tmp_path):
    root = private_tree(tmp_path)
    inventory = PublicSourceInventory.freeze(root, ['source.py'])
    private = (tmp_path / 'control').resolve()
    private.mkdir(mode=0o700)
    path = private / 'inventory.json'
    path.write_text(json.dumps(inventory.manifest()))
    path.chmod(0o600)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = PublicSourceInventory.load(root, path, expected_sha256=digest)
    loaded.copy_to(private / 'candidate')
    copied = private / 'candidate/source.py'
    assert copied.read_bytes() == inventory.read('source.py')[0]
    assert copied.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        loaded.copy_to(private / 'candidate')
    with pytest.raises(SourceBoundaryError, match='digest_mismatch'):
        PublicSourceInventory.load(root, path, expected_sha256='0' * 64)
    path.chmod(0o644)
    with pytest.raises(SourceBoundaryError, match='private_file_required'):
        PublicSourceInventory.load(root, path, expected_sha256=digest)

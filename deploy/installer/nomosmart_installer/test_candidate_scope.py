"""Explicit, short-lived local test authorization; no implicit release fallback."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from uuid import UUID

from .core import PreconditionError
from . import release as _release_runtime
from nomosmart_release.contract import sha256_file
from nomosmart_release.contract_test_candidate import decode, verify_test_candidate
from nomosmart_release.public_sources import _read, relative_path


def _file(path: Path, *, private=False):
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file()
            or (private and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
                             or path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077))):
        raise ValueError('private regular scope required')
    body, _ = _read(path.parent, relative_path(path.name))
    return body


def _stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('aware timestamp required')
    return result


def approved_scope_limits(approval, resources, record):
    """Normalize two explicit human-authority formats; never infer approval."""
    if approval.get('gate_4') == 'APPROVED':
        if (not approval.get('approved_by')
                or approval.get('operation_uuid') != record['operation_uuid']
                or approval.get('approved_plan_sha256') != record['plan']['sha256']
                or approval.get('approved_proposals', {}).get(Path(record['resources']['path']).name) != record['resources']['sha256']
                or resources.get('operation_uuid') != record['operation_uuid']
                or resources.get('kubernetes_context') != record['context']
                or resources.get('one_additional_namespace') != record['namespace']
                or resources.get('helm_release') != record['release']):
            raise ValueError('historical human authority or target differs')
        lease = resources.get('namespace_fixed_lease_minutes')
        cleanup = resources.get('last_cleanup_only_minutes')
    elif approval.get('Gate4') == 'APPROVED':
        frozen = approval.get('frozen_documents')
        if (not isinstance(frozen, list) or not frozen
                or not approval.get('approver') or not approval.get('quote')
                or approval.get('change_id') != resources.get('change_id')):
            raise ValueError('frozen human authority is incomplete')
        hashes = {}
        for item in frozen:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
                raise ValueError('frozen authority reference differs')
            name = Path(item['path']).name
            if name in hashes:
                raise ValueError('duplicate frozen authority reference')
            hashes[name] = item['sha256']
        target = resources.get('kubernetes', {})
        if (hashes.get(Path(record['plan']['path']).name) != record['plan']['sha256']
                or hashes.get(Path(record['resources']['path']).name) != record['resources']['sha256']
                or resources.get('operation_uuid') != record['operation_uuid']
                or resources.get('kubernetes_context') != record['context']
                or target.get('namespace') != record['namespace']
                or target.get('helm_release') != record['release']
                or target.get('installation_uuid') != record['installation_id']
                or target.get('single_install_lifecycle') is not True):
            raise ValueError('frozen human authority or exact target differs')
        lease = resources.get('phase_max_minutes')
        cleanup = resources.get('cleanup_reserve_minutes')
    else:
        raise ValueError('human approval is absent')
    if type(lease) is not int or not 1 <= lease <= 120 or type(cleanup) is not int or not 1 <= cleanup < lease:
        raise ValueError('scope lease ceiling')
    return lease, cleanup


class TestCandidateScope:
    def __init__(self, path: Path, target, configuration_digest: str):
        self.path = path.expanduser().absolute()
        self.target = target
        self.configuration_digest = configuration_digest
        self.initial_scope_sha256 = hashlib.sha256(_file(self.path, private=True)).hexdigest()
        self.check()

    def check(self, *, mutation=False):
        try:
            body = _file(self.path, private=True)
            if hashlib.sha256(body).hexdigest() != self.initial_scope_sha256:
                raise ValueError('scope changed; never reopen or renew it')
            raw = decode(body)
            fields = {'version', 'test_only', 'closed', 'operation_uuid', 'context', 'namespace',
                'namespace_uid', 'release', 'installation_id', 'configuration_digest',
                'candidate_id', 'manifest_sha256', 'archive_sha256', 'created_at', 'expires_at',
                'approval', 'plan', 'resources'}
            if (not isinstance(raw, dict) or set(raw) != fields or type(raw['version']) is not int
                    or raw['version'] != 1 or raw['test_only'] is not True or raw['closed'] is not False):
                raise ValueError('scope identity or closed state')
            str(UUID(raw['operation_uuid']))
            str(UUID(raw['namespace_uid']))
            for key in ('context', 'namespace', 'release', 'installation_id'):
                if raw[key] != getattr(self.target, key):
                    raise ValueError('scope target differs')
            if raw['configuration_digest'] != self.configuration_digest:
                raise ValueError('scope configuration differs')
            loaded = {}
            for key in ('approval', 'plan', 'resources'):
                record = raw[key]
                if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
                    raise ValueError('scope authority reference')
                content = _file(Path(record['path']))
                if hashlib.sha256(content).hexdigest() != record['sha256']:
                    raise ValueError('scope authority changed')
                loaded[key] = decode(content) if key != 'plan' else content
            approval, resources = loaded['approval'], loaded['resources']
            lease, cleanup = approved_scope_limits(approval, resources, raw)
            created, expires = _stamp(raw['created_at']), _stamp(raw['expires_at'])
            now = datetime.now(timezone.utc)
            if expires != created + timedelta(minutes=lease) or not created <= now < expires:
                raise ValueError('scope not active')
            if mutation and now >= expires - timedelta(minutes=cleanup):
                raise ValueError('scope cleanup-only window')
            package = self.target.test_candidate['package_dir']
            result = verify_test_candidate(package)
            if (result['manifest_sha256'] != raw['manifest_sha256']
                    or result['candidate_id'] != raw['candidate_id']
                    or result['chart_sha256'] != self.target.test_candidate['chart_sha256']):
                raise ValueError('scope candidate differs')
            archive = self.target.test_candidate['archive']
            # The archive is operator-owned retained test material, never implicitly extracted.
            if (archive.resolve() != archive or archive.is_symlink() or not archive.is_file()
                    or archive.stat().st_uid != os.getuid() or archive.stat().st_mode & 0o077
                    or sha256_file(archive) != raw['archive_sha256']):
                raise ValueError('scope archive differs')
            self.record, self.result = raw, result
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            raise PreconditionError('Test candidate scope is invalid, changed, closed, expired or outside its human-approved target') from exc

    def check_namespace(self, record):
        try:
            metadata = record['metadata']
            if (metadata['name'] != self.record['namespace'] or metadata['uid'] != self.record['namespace_uid']
                    or _stamp(metadata['creationTimestamp']) != _stamp(self.record['created_at'])
                    or metadata.get('deletionTimestamp')
                    or metadata.get('labels', {}).get('nomosmart.io/protocol-installation') != self.record['installation_id']
                    or metadata.get('labels', {}).get('nomosmart.operation') != self.record['operation_uuid']):
                raise ValueError('scope namespace differs or terminating')
        except (KeyError, TypeError, ValueError) as exc:
            raise PreconditionError('Test candidate namespace identity, ownership or fixed lease differs') from exc

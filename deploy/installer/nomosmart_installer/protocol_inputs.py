"""Local identity and private initialization for protocol targets; no service calls."""
from pathlib import Path
import hashlib
import json
import os
import stat
from uuid import uuid4

from .chart_digest import chart_digest
from .core import PreconditionError


def regular_bytes(path: Path) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024 * 1024:
            raise ValueError("bounded regular file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            value = stream.read(4 * 1024 * 1024 + 1)
        after = os.fstat(descriptor)
        if (len(value) != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns):
            raise ValueError("input changed during read")
        return value
    except (OSError, ValueError) as exc:
        raise PreconditionError("Protocol input must be an unchanged bounded regular file, never a symlink") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def target_digest(path: Path, target) -> str:
    identity = {"target_sha256": hashlib.sha256(regular_bytes(path)).hexdigest(),
                "context": target.context, "namespace": target.namespace,
                "release": target.release, "installation_id": target.installation_id,
                "values_sha256": hashlib.sha256(regular_bytes(target.values_file)).hexdigest(),
                "chart_sha256": chart_digest(target.chart)}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def initialize_target(path: Path, *, chart: Path | None = None) -> dict:
    """Create two new operator-owned files, never overwrite or change parent modes."""
    path = path.expanduser().absolute()
    parent = path.parent
    descriptor = None
    created = []
    try:
        if parent.is_symlink():
            raise ValueError("private parent must not be a symlink")
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("create an owner-only parent directory first")
        chart = chart or Path(__file__).resolve().parents[2] / "helm" / "nomosmart"
        chart_digest(chart)
        chart = chart.resolve(strict=True)
        values_name = path.stem + ".values.json"
        if values_name == path.name:
            raise ValueError("target and values paths must differ")
        for name in (path.name, values_name):
            try:
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError("refusing to overwrite an existing target or values file")
        example = Path(__file__).resolve().parents[1] / "protocol-values.example.json"
        values = json.loads(regular_bytes(example))
        body = 'api_version = "install.nomosmart.io/protocol-v2"\n\n[target]\n'
        fields = {"context": "YOUR_EXPLICIT_KUBERNETES_CONTEXT", "namespace": "nomosmart",
                  "release": "nomosmart", "installation_id": str(uuid4()),
                  "values_file": values_name, "chart": str(chart)}
        body += "".join(key + " = " + json.dumps(value, ensure_ascii=False) + "\n" for key, value in fields.items())
        for name, content in ((values_name, json.dumps(values, ensure_ascii=False, indent=2) + "\n"),
                              (path.name, body)):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            created.append((name, os.fstat(fd)))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        return {"status": "configuration-created", "target": str(path),
                "values_file": str(parent / values_name), "profile": "external-services",
                "auth_contract_revision": 2, "service_actions": 0,
                "next_action": "Set the explicit target, real service/CA references and directory identifiers, then run --plan-only."}
    except (OSError, ValueError, PreconditionError) as exc:
        if descriptor is not None:
            for name, created_info in reversed(created):
                try:
                    current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (created_info.st_dev, created_info.st_ino):
                        os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        raise PreconditionError("Cannot initialize protocol configuration: " + str(exc)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

"""Shared chart identity; byte ordering matches the historical installer."""
from pathlib import Path
import hashlib
from .core import PreconditionError


def chart_digest(path: Path, *, error_type=PreconditionError) -> str:
    if not path.is_dir() or path.is_symlink():
        raise error_type(f"application.chart must be a chart directory: {path}")
    files = sorted(candidate for candidate in path.rglob("*")
                   if candidate.is_file() and not candidate.is_symlink()
                   and not any(part.startswith(".") for part in candidate.relative_to(path).parts))
    if not files:
        raise error_type("application.chart contains no files")
    digest = hashlib.sha256()
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = candidate.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()

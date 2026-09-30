"""Provider-neutral NomoSmart release tooling."""

from .contract import (
    MANIFEST_SCHEMA_VERSION,
    ReleaseContractError,
    verify_release_package,
)

__version__ = "0.1.0"

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ReleaseContractError",
    "verify_release_package",
]

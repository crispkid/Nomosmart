"""One credential policy for model probes and execution adapters."""
from __future__ import annotations

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel
from app.security.secrets import resolve_runtime_secret

MODEL_CREDENTIAL_ERRORS = frozenset({
    "model_credential_invalid", "runtime_secret_unavailable",
    "runtime_secret_reference_invalid", "runtime_secret_reference_denied",
    "legacy_model_credential_forbidden", "legacy_vault_reference_requires_migration",
})


def resolve_model_credential(settings: Settings, model: AIModel) -> str | None:
    if model.api_key_secret_ref:
        return resolve_runtime_secret(settings, model.api_key_secret_ref)
    if not model.api_key_encrypted:
        return None
    if settings.app_env == "production":
        raise AppError("legacy_model_credential_forbidden", "Legacy model credentials are not permitted in production", status_code=503)
    cipher = EnvelopeCipher(settings.encryption_key_bytes)
    for context in (f"ai-model:{model.id}", f"ai-model:{model.name}"):
        try:
            return cipher.decrypt(model.api_key_encrypted, context=context)
        except AppError:
            continue
    raise AppError("model_credential_invalid", "Model provider credential could not be decrypted", status_code=503)

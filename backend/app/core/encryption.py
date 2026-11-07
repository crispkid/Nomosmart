from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import AppError


class EnvelopeCipher:
    VERSION = "v1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM requires a 32-byte key")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return ":".join(
            (
                self.VERSION,
                base64.urlsafe_b64encode(nonce).decode("ascii"),
                base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            )
        )

    def decrypt(self, envelope: str, *, context: str) -> str:
        try:
            version, nonce_text, ciphertext_text = envelope.split(":", 2)
            if version != self.VERSION:
                raise ValueError("unsupported envelope version")
            nonce = base64.urlsafe_b64decode(nonce_text)
            ciphertext = base64.urlsafe_b64decode(ciphertext_text)
            return self._cipher.decrypt(nonce, ciphertext, context.encode("utf-8")).decode("utf-8")
        except (ValueError, InvalidTag, UnicodeDecodeError) as exc:
            raise AppError("invalid_encrypted_value", "Encrypted value could not be verified", status_code=422) from exc


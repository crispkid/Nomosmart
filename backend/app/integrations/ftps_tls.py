"""Strict FTPS trust shared by probes, downloads and connection evidence."""
from __future__ import annotations

import hashlib
import ssl

from app.core.errors import AppError


FTPS_TLS_POLICY = "ftps-verified-v1"


def ftps_ssl_context(ca_cert_path: str = "") -> ssl.SSLContext:
    try:
        context = ssl.create_default_context()
        if ca_cert_path:
            context.load_verify_locations(cafile=ca_cert_path)
    except (OSError, ValueError, ssl.SSLError) as exc:
        raise AppError("ftps_ca_unavailable", "FTPS trust configuration is unavailable", status_code=503) from exc
    # No request-level or legacy metadata option may disable these checks.
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def ftps_trust_fingerprint(ca_cert_path: str = "") -> str:
    context = ftps_ssl_context(ca_cert_path)
    digest = hashlib.sha256(FTPS_TLS_POLICY.encode())
    for certificate in sorted(context.get_ca_certs(binary_form=True)):
        digest.update(hashlib.sha256(certificate).digest())
    return digest.hexdigest()

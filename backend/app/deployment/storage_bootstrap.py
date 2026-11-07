from __future__ import annotations

import argparse
import os
from pathlib import Path
import ssl
from urllib.parse import urlparse

from app.integrations.s3_storage import S3ClientConfig, S3ObjectStorage


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _storage() -> S3ObjectStorage:
    endpoint = _required_environment("S3_ENDPOINT_URL").rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SystemExit("S3_ENDPOINT_URL must be credential-free HTTPS")
    if os.environ.get("S3_VERIFY_TLS", "").strip().lower() != "true":
        raise SystemExit("S3_VERIFY_TLS must be true")
    ca_path = Path(_required_environment("S3_CA_CERT_PATH"))
    if not ca_path.is_file():
        raise SystemExit("S3_CA_CERT_PATH must reference a mounted CA certificate")
    try:
        verify = ssl.create_default_context(cafile=str(ca_path))
    except (OSError, ssl.SSLError) as exc:
        raise SystemExit("S3_CA_CERT_PATH is not a usable CA certificate") from exc
    return S3ObjectStorage(
        S3ClientConfig(
            endpoint_url=endpoint,
            region=_required_environment("S3_REGION"),
            access_key=_required_environment("S3_ACCESS_KEY_ID"),
            secret_key=_required_environment("S3_SECRET_ACCESS_KEY"),
            verify_tls=verify,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one explicitly named NomoSmart S3 bucket"
    )
    parser.add_argument("--bucket", required=True)
    args = parser.parse_args()
    expected = _required_environment("S3_POSTGRESQL_BACKUP_BUCKET")
    if not expected or args.bucket != expected:
        raise SystemExit("backup bucket does not match typed configuration")
    _storage().ensure_bucket(expected)
    print("postgresql backup bucket is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

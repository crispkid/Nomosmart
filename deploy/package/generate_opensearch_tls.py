#!/usr/bin/env python3
"""Generate a private OpenSearch CA, HTTP/transport leaves and encrypted custody.

The CA signing key exists only in an owner-only temporary directory and is
encrypted to the supplied OpenPGP public key before that directory is removed.
Only the CA certificate and leaf material are written to the TLS output.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Final


DNS_LABEL: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


class GeneratorError(RuntimeError):
    pass


def _run(*arguments: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        list(arguments),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise GeneratorError(detail[0][:500] if detail else f"command failed: {arguments[0]}")
    return completed.stdout


def _dns_label(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 63 or not DNS_LABEL.fullmatch(normalized):
        raise GeneratorError(f"{field} must be a Kubernetes DNS label")
    return normalized


def _private_directory(path: Path, *, create: bool) -> None:
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise GeneratorError(f"private directory is unsafe: {path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise GeneratorError(f"private directory must be mode 0700: {path}")
        return
    if not create:
        raise GeneratorError(f"private directory does not exist: {path}")
    path.mkdir(parents=True, mode=0o700)
    os.chmod(path, 0o700)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _certificate_metadata(path: Path) -> dict[str, str]:
    identity = _run(
        "openssl",
        "x509",
        "-in",
        str(path),
        "-noout",
        "-subject",
        "-issuer",
        "-serial",
        "-fingerprint",
        "-sha256",
        "-startdate",
        "-enddate",
    )
    extensions = _run(
        "openssl", "x509", "-in", str(path), "-noout",
        "-ext", "subjectAltName,extendedKeyUsage,basicConstraints,keyUsage",
    )
    return {"inspection": (identity + extensions).strip(), "sha256": _sha256(path)}


def _pgp_fingerprint(public_key: Path, gnupg_home: Path) -> tuple[str, dict[str, str]]:
    if not public_key.is_file() or public_key.is_symlink():
        raise GeneratorError("OpenPGP public key must be a regular file")
    environment = dict(os.environ)
    environment["GNUPGHOME"] = str(gnupg_home)
    listing = _run(
        "gpg",
        "--batch",
        "--with-colons",
        "--import-options",
        "show-only",
        "--import",
        str(public_key),
        env=environment,
    )
    fingerprints = [
        row.split(":")[9]
        for row in listing.splitlines()
        if row.startswith("fpr:") and len(row.split(":")) > 9
    ]
    if not fingerprints:
        raise GeneratorError("OpenPGP public key fingerprint is unavailable")
    _run("gpg", "--batch", "--import", str(public_key), env=environment)
    return fingerprints[0], environment


def _leaf(
    work: Path,
    *,
    name: str,
    common_name: str,
    sans: list[str],
    extended_key_usage: str,
    ca_certificate: Path,
    ca_key: Path,
    valid_days: int,
) -> tuple[Path, Path]:
    key = work / f"{name}.key"
    request = work / f"{name}.csr"
    certificate = work / f"{name}.crt"
    extensions = work / f"{name}.ext"
    _run(
        "openssl", "req", "-new", "-newkey", "rsa:2048", "-sha256", "-nodes",
        "-subj", f"/CN={common_name}", "-keyout", str(key), "-out", str(request),
    )
    extensions.write_text(
        "\n".join(
            (
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                f"extendedKeyUsage={extended_key_usage}",
                "subjectAltName=" + ",".join(f"DNS:{item}" for item in sans),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(extensions, 0o600)
    _run(
        "openssl", "x509", "-req", "-in", str(request), "-CA", str(ca_certificate),
        "-CAkey", str(ca_key), "-CAcreateserial", "-days", str(valid_days), "-sha256",
        "-extfile", str(extensions), "-out", str(certificate),
    )
    os.chmod(key, 0o600)
    os.chmod(certificate, 0o600)
    _run("openssl", "verify", "-CAfile", str(ca_certificate), str(certificate))
    return certificate, key


def generate(args: argparse.Namespace) -> dict[str, object]:
    release = _dns_label(args.release, field="release")
    namespace = _dns_label(args.namespace, field="namespace")
    if args.replicas != 3:
        raise GeneratorError("CHG-251 requires exactly three OpenSearch replicas")
    if args.valid_days < 30 or args.valid_days > 825:
        raise GeneratorError("leaf validity must be between 30 and 825 days")

    output = Path(args.output_dir).expanduser().resolve()
    custody = Path(args.custody_output).expanduser().resolve()
    recipient = Path(args.pgp_public_key).expanduser().resolve()
    _private_directory(output.parent, create=False)
    _private_directory(custody.parent, create=False)
    if output.exists() or custody.exists():
        raise GeneratorError("TLS output and custody output must not already exist")

    temporary_root = Path(tempfile.mkdtemp(prefix=".opensearch-ca-", dir=output.parent))
    os.chmod(temporary_root, 0o700)
    work = temporary_root / "work"
    gpg_parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())
    gnupg_home = Path(tempfile.mkdtemp(prefix="nms-gpg-", dir=gpg_parent))
    os.chmod(gnupg_home, 0o700)
    work.mkdir(mode=0o700)
    try:
        ca_key = work / "opensearch-ca.key"
        ca_certificate = work / "opensearch-ca.crt"
        _run(
            "openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes",
            "-days", "3650", "-subj", "/CN=NomoSmart OpenSearch Private CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", str(ca_key), "-out", str(ca_certificate),
        )
        os.chmod(ca_key, 0o600)
        os.chmod(ca_certificate, 0o600)

        client_service = f"{release}-opensearch"
        headless = f"{client_service}-headless"
        http_sans = [
            client_service,
            f"{client_service}.{namespace}",
            f"{client_service}.{namespace}.svc",
            f"{client_service}.{namespace}.svc.cluster.local",
        ]
        transport_sans = [
            headless,
            f"{headless}.{namespace}",
            f"{headless}.{namespace}.svc",
            f"{headless}.{namespace}.svc.cluster.local",
            f"*.{headless}",
            f"*.{headless}.{namespace}",
            f"*.{headless}.{namespace}.svc",
            f"*.{headless}.{namespace}.svc.cluster.local",
        ]
        transport_sans.extend(
            f"{client_service}-{ordinal}.{headless}.{namespace}.svc.cluster.local"
            for ordinal in range(args.replicas)
        )
        http_certificate, http_key = _leaf(
            work,
            name="http",
            common_name=client_service,
            sans=http_sans,
            extended_key_usage="serverAuth",
            ca_certificate=ca_certificate,
            ca_key=ca_key,
            valid_days=args.valid_days,
        )
        transport_certificate, transport_key = _leaf(
            work,
            name="transport",
            common_name="nomosmart-opensearch-node",
            sans=transport_sans,
            extended_key_usage="serverAuth,clientAuth",
            ca_certificate=ca_certificate,
            ca_key=ca_key,
            valid_days=args.valid_days,
        )

        fingerprint, gpg_environment = _pgp_fingerprint(recipient, gnupg_home)
        encrypted = temporary_root / "opensearch-ca-key.asc"
        _run(
            "gpg", "--batch", "--yes", "--armor", "--trust-model", "always",
            "--recipient", fingerprint, "--output", str(encrypted), "--encrypt", str(ca_key),
            env=gpg_environment,
        )
        if not encrypted.is_file() or encrypted.stat().st_size < 100:
            raise GeneratorError("encrypted CA custody output was not produced")

        staged_output = temporary_root / "tls"
        staged_output.mkdir(mode=0o700)
        files = {
            "tls.crt": http_certificate,
            "tls.key": http_key,
            "transport.crt": transport_certificate,
            "transport.key": transport_key,
            "ca.crt": ca_certificate,
        }
        for name, source in files.items():
            destination = staged_output / name
            shutil.copy2(source, destination)
            os.chmod(destination, 0o600)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "release": release,
            "namespace": namespace,
            "replicas": args.replicas,
            "node_dn": "CN=nomosmart-opensearch-node",
            "pgp_recipient_fingerprint": fingerprint,
            "custody_sha256": _sha256(encrypted),
            "certificates": {
                "ca": _certificate_metadata(staged_output / "ca.crt"),
                "http": _certificate_metadata(staged_output / "tls.crt"),
                "transport": _certificate_metadata(staged_output / "transport.crt"),
            },
            "files": {name: _sha256(staged_output / name) for name in sorted(files)},
        }
        manifest_path = staged_output / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)

        os.replace(staged_output, output)
        os.replace(encrypted, custody)
        os.chmod(custody, 0o600)
        return manifest
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
        shutil.rmtree(gnupg_home, ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="generate-opensearch-tls")
    result.add_argument("--release", required=True)
    result.add_argument("--namespace", required=True)
    result.add_argument("--replicas", type=int, default=3)
    result.add_argument("--valid-days", type=int, default=365)
    result.add_argument("--output-dir", required=True)
    result.add_argument("--pgp-public-key", required=True)
    result.add_argument("--custody-output", required=True)
    return result


def main() -> int:
    try:
        manifest = generate(parser().parse_args())
    except (GeneratorError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({
        "status": "generated",
        "release": manifest["release"],
        "namespace": manifest["namespace"],
        "node_dn": manifest["node_dn"],
        "pgp_recipient_fingerprint": manifest["pgp_recipient_fingerprint"],
        "custody_sha256": manifest["custody_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Real filesystem/CLI/OpenSSL/GnuPG regressions; no deployed credentials.

All secrets and test keyrings live in dedicated temporary roots and are removed.
No mocks, fake binaries, service adapters, Provider calls or cluster access.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import errno
import pty
import select
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "deploy/package/nomosmart_package.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def package():
    return load(PACKAGE, "chg301_package_boundaries")


@pytest.fixture
def private():
    with tempfile.TemporaryDirectory(prefix="chg301-package-", dir="/private/tmp") as name:
        root = Path(name)
        root.chmod(0o700)
        yield root


def args(package, root, *extra):
    return package._parser().parse_args([
        "init", "--output-dir", str(root), "--profile", "factory_acceptance",
        "--app-env", "development", "--no-display", *extra])


@pytest.fixture(scope="module")
def real_package(package):
    with tempfile.TemporaryDirectory(prefix="chg301-package-", dir="/private/tmp") as name:
        root = Path(name)
        root.chmod(0o700)
        assert package.init_package(args(package, root)) == 0
        yield root


@pytest.mark.parametrize("text,valid", [
    ("  Example.Test. ", True), ("", False), ("https://host.test", False),
    ("x..test", False), ("-bad.test", False), ("bad-.test", False),
    ("x" * 64 + ".test", False), ("x" * 254, False)])
def test_public_host_validation(package, text, valid):
    if valid:
        assert package._validate_public_host(text) == "example.test"
    else:
        with pytest.raises(package.PackageError, match="valid DNS hostname"):
            package._validate_public_host(text)


@pytest.mark.parametrize("text", ["", "Bad_Name", "-bad", "bad-", "a" * 64])
def test_invalid_helm_dns_label(package, text):
    with pytest.raises(package.PackageError, match="DNS label"):
        package._validate_dns_label(text, context="isolated test")
    assert package._validate_dns_label(" Test-1 ", context="test") == "test-1"


def test_private_file_nonoverwrite_and_symlink_rejection(package, private):
    real = private / "real"
    real.mkdir(mode=0o700)
    linked = private / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(package.PackageError, match="symlink"):
        package._ensure_private_directory(linked)
    original = real / "secret"
    package._write_private(original, "synthetic file", trailing_newline=False)
    with pytest.raises(package.PackageError, match="overwrite"):
        package._write_private(original, "replacement")
    assert original.read_text() == "synthetic file"
    assert original.stat().st_mode & 0o777 == 0o600
    file_link = private / "file-link"
    file_link.symlink_to(original)
    for function in (package._copy_private, package._replace_private):
        with pytest.raises(package.PackageError, match="regular files"):
            function(file_link, private / "not-created")
        assert not (private / "not-created").exists()
    with pytest.raises(package.PackageError, match="overwrite"):
        package._copy_private(original, original)


@pytest.mark.parametrize("content", [None, "not json", "[]", '{"schema_version":0}'])
def test_invalid_manifest_fails_closed(package, private, content):
    manifest = private / "manifest.json"
    if content is not None:
        manifest.write_text(content)
    with pytest.raises(package.PackageError, match="manifest"):
        package._safe_manifest(manifest)


@pytest.mark.parametrize("text,expected", [
    ("127.0.0.1 nomosmart.local # local\n", True),
    ("127.0.0.1 localhost other.test\n", False),
    ("127.0.0.1 nomosmart.local\n127.0.0.1 nomosmart.local\n", False),
    ("192.0.2.1 nomosmart.local\n", False),
    ("::1 nomosmart.local\n", False)])
def test_hosts_mapping_reads_real_file(package, private, text, expected):
    hosts = private / "hosts"
    hosts.write_text(text)
    assert package._local_host_mapping(hosts, "nomosmart.local") is expected
    with pytest.raises(package.PackageError, match="hosts file"):
        package._local_host_mapping(private / "missing", "nomosmart.local")


def test_real_openssl_error_and_noninteractive_handoff(package):
    with pytest.raises(package.PackageError, match="TLS generation or validation failed"):
        package._run_openssl("this-is-not-an-openssl-command")
    with pytest.raises(package.PackageError, match="interactive TTY"):
        package._display_once({}, "factory_acceptance")
    with pytest.raises(package.PackageError, match="APP_ENV=production"):
        package._validate_profile("production", "development")


def test_actual_cli_errors_do_not_generate_a_package(private):
    command = [sys.executable, str(PACKAGE), "init", "--output-dir", str(private / "output"),
               "--profile", "production", "--app-env", "production", "--no-display"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "HTTPS break-glass runbook" in result.stderr
    assert not (private / "output").exists()
    result = subprocess.run([sys.executable, str(PACKAGE), "status", "--output-dir", str(private / "missing")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "manifest" in result.stderr


def test_status_rotation_and_finalize_guards_preserve_original(package, private, real_package, capsys):
    current = private / "package"
    shutil.copytree(real_package, current)
    before = {p.relative_to(current): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in current.rglob("*") if p.is_file()}
    status = package._parser().parse_args(["status", "--output-dir", str(current)])
    capsys.readouterr()
    assert package.status_package(status) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "ok"
    manifest = json.loads((current / "current/manifest.json").read_text())
    # The manifest intentionally exposes usernames (including "nomosmart").
    # Check actual primitive secret values, not non-sensitive username files.
    assert not any((current / "current" / item["file"]).read_text() in output
                   for name, item in manifest["secrets"].items()
                   if name in package.PRIMITIVE_SECRET_NAMES)
    with pytest.raises(package.PackageError, match="not initialized"):
        package.rotate_package(args(package, private / "empty"))
    mismatch = args(package, current)
    mismatch.profile = "production"
    with pytest.raises(package.PackageError, match="rotation profile"):
        package.rotate_package(mismatch)
    final = package._parser().parse_args(["finalize", "--target", "helm", "--output-dir", str(current)])
    with pytest.raises(package.PackageError, match="in-cluster"):
        package.finalize_package(final)
    assert before == {p.relative_to(current): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in current.rglob("*") if p.is_file()}


def validate_all(package, tls, **changes):
    kwargs = dict(public_host="nomosmart.local", source="isolated-test", target="compose",
                  helm_fullname="nomosmart", helm_release="nomosmart", helm_namespace="nomosmart")
    kwargs.update(changes)
    return package._validate_certificate_set(tls, **kwargs)


@pytest.mark.parametrize("name,message", [
    ("edge.crt", "missing a required"), ("opensearch-transport.crt", "transport identity"),
    ("postgresql-replication.crt", "replication identity")])
def test_missing_real_tls_component_is_rejected(package, private, real_package, name, message):
    tls = private / "tls"
    shutil.copytree(real_package / "current/tls/active", tls)
    (tls / name).unlink()
    with pytest.raises(package.PackageError, match=message):
        validate_all(package, tls)


@pytest.mark.parametrize("name,message", [
    ("edge.key", "private key does not match"),
    ("opensearch-transport.key", "transport private key"),
    ("postgresql-replication.key", "replication private key")])
def test_real_tls_mismatched_keys_are_rejected(package, private, real_package, name, message):
    tls = private / "tls"
    shutil.copytree(real_package / "current/tls/active", tls)
    shutil.copyfile(tls / "rustfs.key", tls / name)
    with pytest.raises(package.PackageError, match=message):
        validate_all(package, tls)


def test_real_tls_wrong_hostname_and_edge_guards(package, private, real_package):
    tls = private / "tls"
    shutil.copytree(real_package / "current/tls/active", tls)
    with pytest.raises(package.PackageError, match="subjectAltName"):
        validate_all(package, tls, public_host="other.invalid")
    edge = dict(public_host="nomosmart.local", source="isolated-test")
    with pytest.raises(package.PackageError, match="subjectAltName"):
        package._validate_edge_certificate_set(tls, **(edge | {"public_host": "other.invalid"}))
    shutil.copyfile(tls / "rustfs.key", tls / "edge.key")
    with pytest.raises(package.PackageError, match="private key does not match"):
        package._validate_edge_certificate_set(tls, **edge)
    (tls / "edge.key").unlink()
    with pytest.raises(package.PackageError, match="external profile requires"):
        package._validate_edge_certificate_set(tls, **edge)


def test_external_edge_rotation_keeps_real_operator_certificate(package, private, real_package):
    output = private / "output"
    init = args(package, output, "--external-services", "--trusted-tls-dir", str(real_package / "current/tls/active"))
    assert package.init_package(init) == 0
    before = (output / "current/tls/active/edge.crt").read_bytes()
    initial_manifest = json.loads((output / "current/manifest.json").read_text())
    assert initial_manifest["certificates"]["active_source"] == "operator_provided_edge"
    rotate = args(package, output, "--external-services")
    assert package.rotate_package(rotate) == 0
    assert (output / "current/tls/active/edge.crt").read_bytes() == before
    assert (output / "previous" / initial_manifest["generation_id"] / "manifest.json").is_file()


def test_helm_rotation_still_generates_random_admin_without_compose_scope(package):
    values = package._build_values("production", "helm", first_use=False)
    assert len(values["opensearch_admin_password"]) == 64
    assert len(values["break_glass_initial_password"]) == 64
    assert "sslmode=verify-full" in values["database_url"]


def test_real_private_ca_custody_roundtrip(private):
    generator = load(ROOT / "deploy/package/generate_opensearch_tls.py", "chg301_real_ca")
    keyring = private / "keyring"
    keyring.mkdir(mode=0o700)
    environment = dict(os.environ, GNUPGHOME=str(keyring))
    def gpg(*argv):
        result = subprocess.run(["gpg", "--batch", *argv], env=environment,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, "real isolated GnuPG operation failed"
        return result.stdout
    try:
        gpg("--passphrase", "", "--quick-generate-key", "CHG301 Test <chg301@example.invalid>", "rsa2048", "encrypt", "1d")
        recipient = private / "recipient.asc"
        recipient.write_text(gpg("--armor", "--export", "chg301@example.invalid")); recipient.chmod(0o600)
        arguments = generator.parser().parse_args([
            "--release", "chg301", "--namespace", "isolated", "--output-dir", str(private / "tls"),
            "--pgp-public-key", str(recipient), "--custody-output", str(private / "custody.asc")])
        result = generator.generate(arguments)
        assert "chg301-opensearch.isolated.svc.cluster.local" in result["certificates"]["http"]["inspection"]
        assert "TLS Web Client Authentication" in result["certificates"]["transport"]["inspection"]
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in (private / "tls").iterdir())
        assert not any(p.name == "opensearch-ca.key" for p in private.rglob("*"))
        # Actual decryption and openssl public-key comparison, without printing
        # or retaining the recovered private CA key.
        recovered = gpg("--decrypt", str(private / "custody.asc"))
        key = subprocess.run(["openssl", "pkey", "-pubout"], input=recovered,
                             capture_output=True, text=True, timeout=30)
        certificate_key = generator._run("openssl", "x509", "-in", str(private / "tls/ca.crt"), "-pubkey", "-noout")
        assert key.returncode == 0 and bool(key.stdout == certificate_key)
        with pytest.raises(generator.GeneratorError, match="already exist"):
            generator.generate(arguments)
    finally:
        subprocess.run(["gpgconf", "--homedir", str(keyring), "--kill", "gpg-agent"],
                       env=environment, capture_output=True, timeout=15)


@pytest.mark.parametrize("field,value", [("replicas", 1), ("valid_days", 1), ("release", "bad/name"), ("namespace", "!")])
def test_ca_generator_rejects_unsafe_configuration(private, field, value):
    generator = load(ROOT / "deploy/package/generate_opensearch_tls.py", "chg301_invalid_ca")
    arguments = generator.parser().parse_args([
        "--release", "chg301", "--namespace", "isolated", "--output-dir", str(private / "tls"),
        "--pgp-public-key", str(private / "recipient.asc"), "--custody-output", str(private / "custody.asc")])
    setattr(arguments, field, value)
    with pytest.raises(generator.GeneratorError):
        generator.generate(arguments)
    assert list(private.iterdir()) == []


def test_real_missing_openssl_rejects_before_generation(private):
    # A real empty PATH, not a fake openssl response or monkeypatched function.
    code = f"""import importlib.util
s = importlib.util.spec_from_file_location('no_openssl', {str(PACKAGE)!r})
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
try: m._run_openssl('version')
except m.PackageError as e:
    assert 'openssl is required' in str(e)
else: raise AssertionError('missing executable unexpectedly accepted')
"""
    environment = dict(os.environ, PATH=str(private))
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "real missing-openssl check failed"


def test_real_cli_requires_tty_and_output_root_is_explicit(package, private):
    command = [sys.executable, str(PACKAGE), "init", "--output-dir", str(private / "output"),
               "--profile", "factory_acceptance", "--app-env", "development"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "interactive TTY" in result.stderr
    assert not (private / "output").exists()
    # Computing defaults performs no IO and must not initialize operator paths.
    options = package._parser().parse_args(["status"])
    assert package._output_root(options) == package.DEFAULT_COMPOSE_DIR
    options.target = "helm"
    assert package._output_root(options) == package.DEFAULT_HELM_DIR


def test_real_tty_handoff_requires_and_uses_the_terminal():
    code = f"""import importlib.util, secrets
s = importlib.util.spec_from_file_location('tty_package', {str(PACKAGE)!r})
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
values = {{k: secrets.token_hex(32) for k in ('break_glass_initial_password', 'oidc_client_secret', 'app_encryption_key')}}
m._display_once(values, 'factory_acceptance')
"""
    master, slave = pty.openpty()
    child = None
    try:
        child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                                 stdout=slave, stderr=slave)
        os.close(slave); slave = -1
        data = bytearray()
        deadline = time.monotonic() + 30
        while True:
            if not select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                pytest.fail('real TTY handoff exceeded its30-second deadline')
            try:
                block = os.read(master, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not block:
                break
            data.extend(block)
        rc = child.wait(timeout=30)
        text = data.decode()
        # No captured synthetic password is persisted or put in failure output.
        if rc or text.count('app_encryption_key:') != 1 or text.count('oidc_client_secret:') != 1:
            pytest.fail('real TTY handoff did not show exactly one set of fields')
        if 'Required: change the temporary password' not in text:
            pytest.fail('real TTY first-use instructions missing')
        data.clear()
    finally:
        os.close(master)
        if slave >= 0: os.close(slave)
        if child is not None and child.poll() is None:
            child.terminate(); child.wait(timeout=5)


def test_finalize_invalid_state_does_not_launch_services(package, private, real_package):
    root = private / "package"
    shutil.copytree(real_package, root)
    manifest = root / "current/manifest.json"
    payload = json.loads(manifest.read_text())
    payload["deployment_state"] = "invalid-test-state"
    manifest.write_text(json.dumps(payload))
    options = package._parser().parse_args(["finalize", "--output-dir", str(root)])
    with pytest.raises(package.PackageError, match="not in an onboarding state"):
        package.finalize_package(options)


@pytest.mark.parametrize("component,san,eku,message", [
    ("opensearch", "other.invalid", "serverAuth,clientAuth", "SAN does not match"),
    ("opensearch", "opensearch", "serverAuth", "serverAuth and clientAuth"),
    ("postgresql", "postgresql", "serverAuth", "requires clientAuth"),
    ("edge", "nomosmart.local", "clientAuth", "requires serverAuth")])
def test_real_signed_tls_role_and_peer_constraints(package, private, real_package, component, san, eku, message):
    tls = private / "tls"
    shutil.copytree(real_package / "current/tls/active", tls)
    work = private / "signing"
    work.mkdir(mode=0o700)
    ca_key, ca = work / "ca.key", work / "ca.crt"
    package._run_openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                         "-subj", "/CN=CHG301 isolated test CA", "-addext", "basicConstraints=critical,CA:TRUE",
                         "-keyout", str(ca_key), "-out", str(ca))
    ca_key.chmod(0o600); ca.chmod(0o600)
    generator = load(ROOT / "deploy/package/generate_opensearch_tls.py", "chg301_signed_leaf")
    def leaf(name, hostname, usage):
        cert, key = generator._leaf(work, name=name, common_name=hostname, sans=[hostname],
            extended_key_usage=usage, ca_certificate=ca, ca_key=ca_key, valid_days=1)
        shutil.copyfile(cert, tls / (name + ".crt"))
        shutil.copyfile(key, tls / (name + ".key"))
    service_host = "nomosmart.local" if component == "edge" else component
    leaf(component, service_host, eku if component == "edge" else "serverAuth")
    shutil.copyfile(ca, tls / (component + "-ca.crt"))
    if component != "edge":
        suffix = "transport" if component == "opensearch" else "replication"
        leaf(component + "-" + suffix, san, eku)
    with pytest.raises(package.PackageError, match=message):
        if component == "edge":
            package._validate_edge_certificate_set(tls, public_host="nomosmart.local", source="isolated-test")
        else:
            validate_all(package, tls)


def test_ca_directory_public_key_and_real_command_guards(private):
    generator = load(ROOT / "deploy/package/generate_opensearch_tls.py", "chg301_ca_guards")
    absent = private / "absent"
    with pytest.raises(generator.GeneratorError, match="does not exist"):
        generator._private_directory(absent, create=False)
    generator._private_directory(absent, create=True)
    assert absent.stat().st_mode & 0o777 == 0o700
    absent.chmod(0o755)
    with pytest.raises(generator.GeneratorError, match="mode 0700"):
        generator._private_directory(absent, create=False)
    linked = private / "linked"
    linked.symlink_to(absent, target_is_directory=True)
    with pytest.raises(generator.GeneratorError, match="unsafe"):
        generator._private_directory(linked, create=False)
    with pytest.raises(generator.GeneratorError, match="regular file"):
        generator._pgp_fingerprint(private / "missing.asc", private)
    with pytest.raises(generator.GeneratorError):
        generator._run("openssl", "invalid-chg301-command")
    command = [sys.executable, str(ROOT / "deploy/package/generate_opensearch_tls.py"),
               "--release", "chg301", "--namespace", "isolated", "--replicas", "1",
               "--output-dir", str(private / "output"), "--pgp-public-key", str(private / "missing.asc"),
               "--custody-output", str(private / "custody.asc")]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "exactly three" in result.stderr
    assert not (private / "output").exists()

"""V049 bounded backup qualification and explicitly approved local custody.

Unencrypted mode requires source-bound qualification and an explicit opt-in.
No application import, inherited DB settings, scanner or Kubernetes mutation.
The original human-Pinentry qualification is retained, not silently marked passed.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PG_IMAGE = "sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a"
LABEL = "nomosmart.v049.backup-test"
MAX_STREAM = 512 * 1024 * 1024
SOURCE_LIMIT = 256 * 1024 * 1024
BACKUP_ROOT = Path("/Users/peter/NomoSmartBackups/V049")
TEST_FILE = ROOT / "backend/tests/test_chg291_v049_live_backup.py"
RESTRICT_KEY = "V049SchemaComparisonOnlyNotExecuted"
PSQL = ("-X", "-qAt", "-v", "ON_ERROR_STOP=1")
CLI_COVERAGE = None
CLI_DIRECTORY = None
PROOF_REPORTS = ("tests.xml", "coverage.json", "coverage-pytest.json", "coverage.xml",
                 "cleanup.json", ".coverage.cli", ".coverage.tests")
LEGACY_CASES_SHA256 = "65cd3e543d091047478f6a01f307902098ecb8d6509bd6ae773ea8a3709e169c"
ENTRY_CASES = frozenset(("test_r7_entry_roundtrip", "test_r7_entry_custody_and_scope",
    "test_r7_entry_finalization_guards", "test_r7_entry_cli", "test_r7_entry_compatibility",
    "test_r7_entry_cancellation"))


class BackupError(RuntimeError):
    """Only stable codes reach terminal/log; never print child SQL or credentials."""


def require(value, code):
    if not value:
        raise BackupError(code)


def clean_env():
    return {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "TERM") if key in os.environ}


def run(args, *, data=None, timeout=30):
    try:
        result = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=clean_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackupError("child_timeout") from None
    require(result.returncode == 0, "child_failed")
    return result.stdout


def secure_directory(path):
    path = Path(path)
    require(path.is_absolute(), "path_not_absolute")
    for parent in [*reversed(path.parents), path]:
        require(not parent.is_symlink(), "symlink_not_allowed")
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), "unsafe_directory_owner")
    require(stat.S_IMODE(info.st_mode) == 0o700, "directory_not_private")
    return path


def private_json(path, value):
    secure_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def pipeline(producer, consumer, *, limit=MAX_STREAM, seconds=300, interactive=False):
    """Bounded pipe, backpressure, process-group cleanup, BOTH exits required.

Plaintext is never spooled or returned; stderr is never copied to a report.
Only GPG's own terminal messages may be inherited during human qualification.
"""
    require(0 < limit <= MAX_STREAM and 0 < seconds <= 600, "invalid_pipeline_limit")
    started = time.monotonic()
    processes = []
    selector = selectors.DefaultSelector()
    pending = bytearray()
    size = 0
    eof = False
    try:
        for argv, is_source in ((producer, True), (consumer, False)):
            # No shell; process groups contain only children created by this call.
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL if is_source else subprocess.PIPE,
                stdout=subprocess.PIPE if is_source else subprocess.DEVNULL,
                stderr=None if interactive and Path(argv[0]).name == "gpg" else subprocess.DEVNULL,
                env=clean_env(), start_new_session=True)
            processes.append(child)
        source, target = processes
        os.set_blocking(source.stdout.fileno(), False)
        os.set_blocking(target.stdin.fileno(), False)
        selector.register(source.stdout, selectors.EVENT_READ, "read")
        writing = False
        reading = True
        while not eof or pending:
            require(time.monotonic() - started < seconds, "pipeline_timeout")
            require(target.poll() is None, "consumer_exited_early")
            for key, _ in selector.select(0.1):
                if key.data == "read":
                    block = os.read(source.stdout.fileno(), 65536)
                    if block:
                        size += len(block)
                        require(size <= limit, "stream_too_large")
                        pending.extend(block)
                    else:
                        eof = True
                        selector.unregister(source.stdout)
                        reading = False
                elif pending:
                    try:
                        written = os.write(target.stdin.fileno(), pending)
                    except BrokenPipeError:
                        raise BackupError("consumer_broken_pipe") from None
                    del pending[:written]
            if pending and not writing:
                selector.register(target.stdin, selectors.EVENT_WRITE, "write")
                writing = True
            if not pending and writing:
                selector.unregister(target.stdin)
                writing = False
            if len(pending) >= 131072 and reading:
                selector.unregister(source.stdout)
                reading = False
            elif len(pending) < 131072 and not eof and not reading:
                selector.register(source.stdout, selectors.EVENT_READ, "read")
                reading = True
        target.stdin.close()
        require(size > 0, "empty_stream")
        for child in processes:
            try:
                code = child.wait(timeout=max(0.1, seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                raise BackupError("pipeline_timeout") from None
            require(code == 0, "pipeline_child_failed")
        return {"bytes": size, "seconds": round(time.monotonic() - started, 3), "all_exits_zero": True}
    finally:
        selector.close()
        for child in processes:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=3)
            for stream in (child.stdin, child.stdout):
                if stream and not stream.closed:
                    stream.close()


def quote_ident(value):
    require(isinstance(value, str) and "\x00" not in value, "invalid_identifier")
    return '"' + value.replace('"', '""') + '"'


class Snapshot:
    """A bounded read-only transaction kept alive for pg_dump --snapshot."""

    def __init__(self, argv, *, deadline=None):
        self.child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=clean_env(), start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.deadline = min(time.monotonic() + 300, deadline) if deadline is not None else time.monotonic() + 300
        try:
            self.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; "
                "SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s'; "
                "SET LOCAL idle_in_transaction_session_timeout='300s'; SET LOCAL row_security=off; "
                "SET LOCAL extra_float_digits=3; SET LOCAL timezone='UTC'")
            self.snapshot = self.query("SELECT pg_export_snapshot()")[0]
            require(re.fullmatch(r"[A-Fa-f0-9-]+", self.snapshot), "snapshot_id_invalid")
        except BaseException:
            self.close()
            raise

    def query(self, sql):
        require(time.monotonic() < self.deadline, "snapshot_expired")
        marker = "end_" + secrets.token_hex(12)
        try:
            self.child.stdin.write((sql + ";\n\\echo " + marker + "\n").encode())
            self.child.stdin.flush()
        except BrokenPipeError:
            raise BackupError("snapshot_query_failed") from None
        lines = []
        deadline = min(self.deadline, time.monotonic() + 20)
        total = 0
        while time.monotonic() < deadline:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line.decode() == marker:
                    return [line for line in lines if line]
                lines.append(line.decode())
            require(self.child.poll() is None, "snapshot_query_failed")
            if self.selector.select(0.1):
                block = os.read(self.child.stdout.fileno(), 65536)
                require(block, "snapshot_query_failed")
                self.buffer += block
                total += len(block)
                require(total <= 4 * 1024 * 1024, "metadata_too_large")
        raise BackupError("snapshot_query_timeout")

    def value(self, sql):
        lines = self.query(sql)
        require(len(lines) == 1, "metadata_shape_invalid")
        try:
            return json.loads(lines[0])
        except (ValueError, TypeError):
            raise BackupError("metadata_json_invalid") from None

    def close(self):
        try:
            try:
                self.child.stdin.close()  # EOF rolls back the read-only transaction.
            except BrokenPipeError:
                pass  # Peer already exited; still close every local descriptor.
            if self.child.poll() is None:
                try:
                    self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    stop_process(self.child)
        finally:
            self.child.stdout.close()
            self.selector.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def stop_process(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)


def read_process(argv, sink, *, limit=MAX_STREAM, deadline=None, input_fd=None):
    """Stream into a private FD/hash, never tool stdout; retain the real exit code."""
    require(0 < limit <= MAX_STREAM, "invalid_stream_limit")
    deadline = deadline or time.monotonic() + 300
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL if input_fd is None else input_fd, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=clean_env(), start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    count = 0
    try:
        eof = False
        while not eof:
            require(time.monotonic() < deadline, "stream_timeout")
            if selector.select(0.1):
                block = os.read(child.stdout.fileno(), 65536)
                if not block:
                    eof = True
                else:
                    count += len(block)
                    require(count <= limit, "stream_too_large")
                    sink(block)
        try:
            code = child.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise BackupError("stream_timeout") from None
        require(code == 0 and count > 0, "stream_failed_or_empty")
        return count
    finally:
        selector.close()
        stop_process(child)
        child.stdout.close()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def literal(value):
    require(isinstance(value, str) and "\x00" not in value, "invalid_literal")
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def no_unsafe_acl(path):
    # Owner-only mode bits alone do not reject ACL-granted access on macOS.
    if sys.platform == "darwin":
        lines = run(["/bin/ls", "-lde", str(path)]).decode().splitlines()[1:]
        require(not any(re.match(r"\s*\d+:.*\sallow\s", line) for line in lines), "acl_grants_access")
    elif sys.platform.startswith("linux"):
        require(not any(name.startswith("system.posix_acl") for name in os.listxattr(path)), "acl_grants_access")
    else:
        raise BackupError("unsupported_acl_platform")


def custody(path):
    path = secure_directory(path)
    for parent in [*reversed(path.parents), path]:
        info = parent.lstat()
        require(info.st_uid in (0, os.getuid()), "unsafe_parent_owner")
        require(not (info.st_mode & 0o022) or bool(info.st_mode & stat.S_ISVTX), "writable_parent")
        no_unsafe_acl(parent)
    return path


class PlainArchive:
    """One exclusively-created unencrypted file; failure always leaves it private."""

    def __init__(self, directory, *, minimum_free=1024**3):
        self.directory = custody(directory)
        require(shutil.disk_usage(directory).free >= minimum_free, "insufficient_space")
        self.path = self.directory / "database.partial.dump"
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.identity = (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)
        self.expected = None
        self.schema_evidence_binding = None
        self.restore_identity_binding = None
        self.member_comments_binding = None
        self.entry = None
        try:
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        custody(self.directory)
        no_unsafe_acl(self.path)
        value = self.path.lstat()
        require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                and stat.S_IMODE(value.st_mode) == 0o600 and value.st_nlink == 1,
                "archive_not_private")
        require((value.st_dev, value.st_ino) == self.identity
                and (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino) == self.identity,
                "archive_replaced")

    def calculate(self):
        self.check()
        os.lseek(self.fd, 0, os.SEEK_SET)
        sha = hashlib.sha256()
        size = 0
        first = b""
        while block := os.read(self.fd, 65536):
            if not size:
                first = block[:5]
            size += len(block)
            require(size <= MAX_STREAM, "stream_too_large")
            sha.update(block)
        require(first == b"PGDMP" and size > 5, "invalid_archive_format")
        self.check()
        require(os.fstat(self.fd).st_size == size, "archive_size_changed")
        return {"bytes": size, "sha256": sha.hexdigest()}

    def export(self, argv, deadline):
        self.check()
        require(os.fstat(self.fd).st_size == 0 and self.expected is None, "archive_already_written")
        def write(block):
            view = memoryview(block)
            while view:
                count = os.write(self.fd, view)
                require(count > 0, "file_write_failed")
                view = view[count:]
        read_process(argv, write, deadline=deadline)
        os.fsync(self.fd)
        self.expected = self.calculate()
        return self.expected

    def verify(self):
        require(self.expected is not None and self.calculate() == self.expected, "archive_integrity_changed")

    def restore(self, argv, deadline):
        self.verify()
        os.lseek(self.fd, 0, os.SEEK_SET)
        child = subprocess.Popen(argv, stdin=self.fd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=clean_env(), start_new_session=True)
        try:
            try:
                code = child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise BackupError("restore_timeout") from None
            require(code == 0, "restore_failed")
            require(time.monotonic() < deadline, "restore_timeout")
        finally:
            stop_process(child)
        self.verify()

    def finalize(self, *, accepted):
        require(accepted is True, "verification_incomplete")
        self.verify()
        final = self.directory / "database.dump"
        # rename() replaces a destination; use the OS no-replace primitive instead.
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            operation = libc.renamex_np
            operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            result = operation(os.fsencode(self.path), os.fsencode(final), 4)  # RENAME_EXCL
        elif sys.platform.startswith("linux"):
            operation = libc.renameat2
            operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            result = operation(-100, os.fsencode(self.path), -100, os.fsencode(final), 1)
        else:
            raise BackupError("atomic_finalize_unsupported")
        if result != 0:
            raise BackupError("archive_finalize_exists" if ctypes.get_errno() == errno.EEXIST else "archive_finalize_failed")
        self.path = final
        self.check()
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return self.path

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


CATALOG_FILTER = "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_toast'"


class DatabaseState:
    """Complete supported object/data evidence, never row text in a report."""

    @staticmethod
    def schema_hash(command, snapshot):
        sha = hashlib.sha256()
        # This plain SQL is ONLY hashed, never executed, persisted or displayed.
        read_process(command("pg_dump", "--schema-only", "--quote-all-identifiers", "--encoding=UTF8",
            "--lock-wait-timeout=2s", "--restrict-key="+RESTRICT_KEY, "--snapshot="+snapshot.snapshot),
            sha.update, deadline=snapshot.deadline, limit=32 * 1024**2)
        return sha.hexdigest()

    @staticmethod
    def properties(snapshot):
        value = snapshot.value("""SELECT jsonb_build_object(
            'owner',pg_get_userbyid(d.datdba),'encoding',pg_encoding_to_char(d.encoding),
            'provider',d.datlocprovider,'collate',d.datcollate,'ctype',d.datctype,
            'locale',d.datlocale,'rules',d.daticurules,'collversion',d.datcollversion,
            'limit',d.datconnlimit,'allow',d.datallowconn,'template',d.datistemplate,
            'tablespace',(SELECT spcname FROM pg_tablespace WHERE oid=d.dattablespace),
            'comment',shobj_description(d.oid,'pg_database'),
            'acl',(SELECT jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
                CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                a.privilege_type,a.is_grantable) ORDER BY a.grantor,a.grantee,a.privilege_type)
                FROM aclexplode(COALESCE(d.datacl,acldefault('d',d.datdba))) a),
            'settings',(SELECT count(*) FROM pg_db_role_setting WHERE setdatabase=d.oid))
            FROM pg_database d WHERE d.datname=current_database()""")
        # Database comments/settings outside pg_restore's selected-db mode need
        # a separate faithful restore contract. Never silently omit them.
        require(value["comment"] is None and value["settings"] == 0
                and value["tablespace"] == "pg_default" and value["allow"]
                and not value["template"] and value["limit"] == -1, "unsupported_database_properties")
        value["acl"] = sorted(value["acl"])
        require(all(row[0] == value["owner"] for row in value["acl"]), "unsupported_database_acl_grantor")
        return value

    @staticmethod
    def object_list(snapshot):
        return snapshot.value("SELECT coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relkind) "
            "ORDER BY n.nspname,c.relname),'[]') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE " + CATALOG_FILTER + " AND c.relkind IN ('r','p','m','S')")

    @staticmethod
    def guard_supported(snapshot):
        require(snapshot.query("SHOW transaction_read_only") == ["on"], "source_not_readonly")
        require(snapshot.value("SELECT to_json(NOT pg_is_in_recovery())"), "standby_not_supported")
        require(snapshot.value("SELECT pg_database_size(current_database())") <= SOURCE_LIMIT, "database_too_large")
        extensions = snapshot.value("SELECT coalesce(jsonb_agg(extname ORDER BY extname),'[]') FROM pg_extension")
        require(set(extensions) <= {"plpgsql", "pgcrypto", "vector", "pg_trgm", "uuid-ossp"}, "unsupported_extension")
        require(snapshot.value("SELECT (SELECT count(*) FROM pg_foreign_server) + "
            "(SELECT count(*) FROM pg_publication) + (SELECT count(*) FROM pg_subscription) + "
            "(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "
            + CATALOG_FILTER + " AND c.reltablespace<>0)") == 0, "unsupported_external_or_tablespace")

    @staticmethod
    def sequences(snapshot, objects):
        result = []
        for schema, name, kind in objects:
            if kind == "S":
                relation = quote_ident(schema)+"."+quote_ident(name)
                values = snapshot.value("SELECT jsonb_build_array(last_value,is_called) FROM " + relation)
                result.append([schema, name, *values])
        return result

    @classmethod
    def collect(cls, snapshot, command):
        cls.guard_supported(snapshot)
        properties = cls.properties(snapshot)
        objects = cls.object_list(snapshot)
        data = []
        for schema, name, kind in objects:
            if kind == "S":
                continue
            relation = quote_ident(schema)+"."+quote_ident(name)
            # Multiset equality includes duplicate rows, NULLs and bytea; server
            # sends only a table count/digest. ONLY avoids inherited double counts.
            value = snapshot.value("SELECT jsonb_build_array(count(*),encode(sha256(convert_to("
                "coalesce(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex')) FROM "
                "(SELECT encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex') h FROM ONLY "
                + relation + " t) x")
            data.append([schema, name, kind, *value])
        blobs = snapshot.value("""SELECT jsonb_build_object('count',(SELECT count(*) FROM pg_largeobject_metadata),
            'pages',(SELECT count(*) FROM pg_largeobject),
            'data',(SELECT encode(sha256(convert_to(coalesce(string_agg(
                loid::text||':'||pageno::text||':'||encode(sha256(data),'hex'),'|' ORDER BY loid,pageno),''),'UTF8')),'hex')
                FROM pg_largeobject),
            'metadata',(SELECT encode(sha256(convert_to(coalesce(string_agg(jsonb_build_array(oid,
                pg_get_userbyid(lomowner),(SELECT jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
                    CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                    a.privilege_type,a.is_grantable) ORDER BY pg_get_userbyid(a.grantor),
                    CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,a.privilege_type)
                    FROM aclexplode(COALESCE(lomacl,acldefault('L',lomowner))) a),
                obj_description(oid,'pg_largeobject'))::text,'|' ORDER BY oid),''),'UTF8')),'hex')
                FROM pg_largeobject_metadata))""")
        roles = snapshot.value("SELECT coalesce(jsonb_agg(rolname ORDER BY rolname),'[]') FROM pg_roles WHERE oid IN ("
            "SELECT refobjid FROM pg_shdepend WHERE refclassid='pg_authid'::regclass "
            "AND dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "UNION SELECT datdba FROM pg_database WHERE datname=current_database())")
        return {"properties": properties, "roles": roles, "schema": cls.schema_hash(command, snapshot),
                "tables": data, "sequences": cls.sequences(snapshot, objects), "large_objects": blobs}

    @classmethod
    def assert_stable(cls, initial, snapshot, command):
        cls.guard_supported(snapshot)
        require(cls.properties(snapshot) == initial["properties"]
                and cls.sequences(snapshot, cls.object_list(snapshot)) == initial["sequences"]
                and cls.schema_hash(command, snapshot) == initial["schema"], "source_ddl_or_sequence_drift")

    @staticmethod
    def provision_restore(lab, target, state):
        lab.guard()
        lab.empty_restore(target)
        roles = set(state["roles"]) | {state["properties"]["owner"]}
        roles.update(row[1] for row in state["properties"]["acl"] if row[1] != "PUBLIC")
        for role in sorted(roles):
            exists = lab.sql(target, "SELECT count(*) FROM pg_roles WHERE rolname="+literal(role)).strip() == b"1"
            if exists:
                require(role == lab.bootstrap or role in lab.builtin_roles, "restore_role_collision")
            else:
                lab.sql(target, "CREATE ROLE "+quote_ident(role)+" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
        owner = state["properties"]["owner"]
        sql = "ALTER DATABASE "+quote_ident(target)+" OWNER TO "+quote_ident(owner)+"; "
        sql += "REVOKE ALL ON DATABASE "+quote_ident(target)+" FROM PUBLIC; "
        sql += "SET ROLE "+quote_ident(owner)+"; "
        for grantor, grantee, privilege, grantable in state["properties"]["acl"]:
            require(grantor == owner and privilege in ("CREATE", "CONNECT", "TEMPORARY"), "invalid_database_acl")
            sql += "GRANT "+privilege+" ON DATABASE "+quote_ident(target)+" TO "+(
                "PUBLIC" if grantee == "PUBLIC" else quote_ident(grantee))+(" WITH GRANT OPTION" if grantable else "")+"; "
        lab.sql(target, sql+"RESET ROLE")
        with Snapshot(lab.command("psql", target, *PSQL)) as actual:
            require(DatabaseState.properties(actual) == state["properties"], "restore_database_properties_differ")


class SchemaEvidence:
    """Versioned, bounded catalog evidence, never a substitute for pg_dump/data.

    No SQL/comment/function text leaves the database. Object identities are kept
    only in private evidence; differences exposed to logs contain digests only.
    OIDs are resolved inside the snapshot, never compared between clusters.
    Unsupported catalog classes explicitly make the evidence incomplete.
    """

    VERSION = 1
    COLLECTOR = "pg18-catalog-v1"
    FILE = "schema-evidence-v1.json"
    KINDS = ("schema", "relation", "column", "type", "routine", "constraint",
             "trigger", "rule", "policy", "default_acl", "extension", "language")

    @classmethod
    def collect(cls, snapshot):
        # Fix deparser qualification, independent of the source login's search_path.
        snapshot.query("SET LOCAL search_path=pg_catalog")
        version = snapshot.value("SELECT current_setting('server_version_num')::int")
        require(180000 <= version < 190000, "schema_evidence_pg_version_unsupported")
        user = "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)'"
        member = "EXISTS(SELECT 1 FROM pg_depend e WHERE e.classid=CLASS::regclass AND e.objid=x.oid AND e.deptype='e')"
        routines = member.replace("CLASS", "'pg_proc'")
        types = member.replace("CLASS", "'pg_type'")
        languages = member.replace("CLASS", "'pg_language'")
        # A typed projection for every covered class. Unknown classes are NOT
        # hashed as raw catalog tuples (those contain unstable cross-cluster OIDs).
        objects = f"""
        SELECT 'pg_namespace'::regclass AS classid,n.oid AS objid,0 AS subid,'schema'::text AS kind,
          jsonb_build_array(n.nspname) AS definition,n.nspowner AS owner,n.nspacl AS acl,'n'::"char" AS aclkind
          FROM pg_namespace n WHERE {user}
        UNION ALL SELECT 'pg_class'::regclass,c.oid,0,'relation',jsonb_build_object(
          'kind',c.relkind,'persistence',c.relpersistence,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,
          'replica_identity',c.relreplident,'access_method',am.amname,'options',c.reloptions,
          'tablespace',ts.spcname,'partition_key',CASE WHEN c.relkind='p' THEN pg_get_partkeydef(c.oid) END,
          'partition_bound',pg_get_expr(c.relpartbound,c.oid),
          'parents',(SELECT jsonb_agg(inhparent::regclass::text ORDER BY inhseqno) FROM pg_inherits WHERE inhrelid=c.oid),
          'view',CASE WHEN c.relkind IN ('v','m') THEN pg_get_viewdef(c.oid,false) END,
          'index',CASE WHEN c.relkind IN ('i','I') THEN pg_get_indexdef(c.oid) END,
          'index_flags',(SELECT jsonb_build_array(indisunique,indisprimary,indisexclusion,indisvalid,
             indisready,indisclustered,indisreplident,indnullsnotdistinct) FROM pg_index WHERE indexrelid=c.oid),
          'sequence',(SELECT jsonb_build_array(seqtypid::regtype::text,seqstart,seqincrement,seqmax,seqmin,
             seqcache,seqcycle) FROM pg_sequence WHERE seqrelid=c.oid)),c.relowner,c.relacl,
          CASE WHEN c.relkind='S' THEN 's' ELSE 'r' END::"char"
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_am am ON am.oid=c.relam LEFT JOIN pg_tablespace ts ON ts.oid=c.reltablespace WHERE {user}
        UNION ALL SELECT 'pg_class'::regclass,c.oid,a.attnum,'column',jsonb_build_object(
          'type',format_type(a.atttypid,a.atttypmod),'collation',co.oid::regcollation::text,
          'not_null',a.attnotnull,'identity',a.attidentity,'generated',a.attgenerated,
          'default',pg_get_expr(d.adbin,d.adrelid),'storage',a.attstorage,'compression',a.attcompression,
          'statistics',a.attstattarget,'options',a.attoptions,
          'position',(SELECT count(*) FROM pg_attribute pa WHERE pa.attrelid=c.oid AND pa.attnum>0
            AND NOT pa.attisdropped AND pa.attnum<=a.attnum)),c.relowner,a.attacl,'c'::"char"
          FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
          LEFT JOIN pg_collation co ON co.oid=a.attcollation WHERE {user} AND a.attnum>0 AND NOT a.attisdropped
        UNION ALL SELECT 'pg_type'::regclass,x.oid,0,'type',jsonb_build_object(
          'kind',x.typtype,'category',x.typcategory,'preferred',x.typispreferred,'defined',x.typisdefined,
          'delimiter',x.typdelim,'length',x.typlen,'byval',x.typbyval,'align',x.typalign,'storage',x.typstorage,
          'base',format_type(x.typbasetype,x.typtypmod),'not_null',x.typnotnull,'default',x.typdefault,
          'element',x.typelem::regtype::text,'array',x.typarray::regtype::text,'relation',x.typrelid::regclass::text,
          'collation',x.typcollation::regcollation::text,'input',x.typinput::regprocedure::text,
          'output',x.typoutput::regprocedure::text,'receive',x.typreceive::regprocedure::text,
          'send',x.typsend::regprocedure::text,'modin',x.typmodin::regprocedure::text,
          'modout',x.typmodout::regprocedure::text,'analyze',x.typanalyze::regprocedure::text,
          'subscript',x.typsubscript::regprocedure::text,
          'enum',(SELECT jsonb_agg(enumlabel ORDER BY enumsortorder) FROM pg_enum WHERE enumtypid=x.oid),
          'range',(SELECT jsonb_build_array(rngsubtype::regtype::text,rngcollation::regcollation::text,
             (SELECT i.identity FROM pg_identify_object('pg_opclass'::regclass,rngsubopc,0) i),
             rngcanonical::regprocedure::text,rngsubdiff::regprocedure::text,rngmultitypid::regtype::text)
             FROM pg_range WHERE rngtypid=x.oid)),x.typowner,x.typacl,'T'::"char"
          FROM pg_type x JOIN pg_namespace n ON n.oid=x.typnamespace WHERE ({user}) OR {types}
        UNION ALL SELECT 'pg_proc'::regclass,x.oid,0,'routine',jsonb_build_array(pg_get_functiondef(x.oid),
          x.prosupport::regprocedure::text),x.proowner,x.proacl,'f'::"char"
          FROM pg_proc x JOIN pg_namespace n ON n.oid=x.pronamespace WHERE x.prokind<>'a' AND (({user}) OR {routines})
        UNION ALL SELECT 'pg_constraint'::regclass,c.oid,0,'constraint',jsonb_build_array(
          pg_get_constraintdef(c.oid,false),c.convalidated,c.conenforced,c.condeferrable,c.condeferred,
          c.connoinherit),NULL::oid,NULL::aclitem[],NULL::"char"
          FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE {user}
        UNION ALL SELECT 'pg_trigger'::regclass,t.oid,0,'trigger',jsonb_build_array(pg_get_triggerdef(t.oid,false),
          t.tgenabled),NULL::oid,NULL::aclitem[],NULL::"char" FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {user} AND NOT t.tgisinternal
        UNION ALL SELECT 'pg_rewrite'::regclass,r.oid,0,'rule',jsonb_build_array(pg_get_ruledef(r.oid,false),
          r.ev_enabled),NULL::oid,NULL::aclitem[],NULL::"char" FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {user}
        UNION ALL SELECT 'pg_policy'::regclass,p.oid,0,'policy',jsonb_build_array(p.polcmd,p.polpermissive,
          (SELECT jsonb_agg(CASE WHEN role=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role) END ORDER BY
            CASE WHEN role=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role) END) FROM unnest(p.polroles) role),
          pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)),NULL::oid,NULL::aclitem[],NULL::"char"
          FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {user}
        UNION ALL SELECT 'pg_default_acl'::regclass,d.oid,0,'default_acl',jsonb_build_array(d.defaclobjtype),
          d.defaclrole,d.defaclacl,d.defaclobjtype FROM pg_default_acl d
        UNION ALL SELECT 'pg_extension'::regclass,x.oid,0,'extension',jsonb_build_object(
          'version',x.extversion,'schema',n.nspname,'relocatable',x.extrelocatable,
          'configuration',(SELECT jsonb_agg(jsonb_build_array(c::regclass::text,condition) ORDER BY c::regclass::text)
            FROM unnest(x.extconfig,x.extcondition) AS cfg(c,condition))),x.extowner,NULL::aclitem[],NULL::"char"
          FROM pg_extension x JOIN pg_namespace n ON n.oid=x.extnamespace
        UNION ALL SELECT 'pg_language'::regclass,x.oid,0,'language',jsonb_build_array(x.lanpltrusted,
          x.lanplcallfoid::regprocedure::text,x.laninline::regprocedure::text,x.lanvalidator::regprocedure::text),
          x.lanowner,x.lanacl,'l'::"char" FROM pg_language x WHERE x.lanispl OR {languages}
        """
        # Dependencies of attrdefs belong to the column evidence, including
        # referenced sequences/routines. Extension membership and bootstrap ACL
        # are explicit; they are never normalized to the restore login.
        query = "WITH objects AS ("+objects+"), evidence AS ("+"""
          SELECT o.kind,i.identity,jsonb_build_object(
            'definition',encode(sha256(convert_to(o.definition::text,'UTF8')),'hex'),
            'owner',CASE WHEN o.owner IS NOT NULL THEN pg_get_userbyid(o.owner) END,
            'comment',jsonb_build_object('state',CASE WHEN d.objoid IS NULL THEN 'absent'
              WHEN d.description IS NULL THEN 'null' WHEN d.description='' THEN 'empty' ELSE 'value' END,
              'sha256',CASE WHEN d.description IS NOT NULL THEN encode(sha256(convert_to(d.description,'UTF8')),'hex') END),
            'acl',jsonb_build_object('explicit',o.acl IS NOT NULL,'grants',
              (SELECT coalesce(jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
                CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable)
                ORDER BY pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                a.privilege_type,a.is_grantable),'[]') FROM aclexplode(CASE WHEN o.aclkind IS NULL THEN NULL
                ELSE coalesce(o.acl,acldefault(o.aclkind,o.owner)) END) a)),
            'initial_acl',(SELECT jsonb_build_object('type',ip.privtype,'grants',
              (SELECT coalesce(jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
                CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable)
                ORDER BY pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                a.privilege_type,a.is_grantable),'[]') FROM aclexplode(ip.initprivs) a))
              FROM pg_init_privs ip WHERE ip.classoid=o.classid AND ip.objoid=o.objid AND ip.objsubid=o.subid),
            'dependencies',(SELECT coalesce(jsonb_agg(dep ORDER BY dep::text),'[]') FROM (
              SELECT DISTINCT jsonb_build_array(e.deptype,ri.type,ri.identity) dep FROM pg_depend e
                CROSS JOIN LATERAL pg_identify_object(e.refclassid,e.refobjid,e.refobjsubid) ri
                WHERE (e.classid=o.classid AND e.objid=o.objid AND e.objsubid=o.subid) OR
                (o.kind='column' AND e.classid='pg_attrdef'::regclass AND e.objid IN
                  (SELECT ad.oid FROM pg_attrdef ad WHERE ad.adrelid=o.objid AND ad.adnum=o.subid))) deps)
          ) fields FROM objects o CROSS JOIN LATERAL pg_identify_object(o.classid,o.objid,o.subid) i
          LEFT JOIN pg_description d ON d.classoid=o.classid AND d.objoid=o.objid AND d.objsubid=o.subid)
          SELECT coalesce(jsonb_agg(jsonb_build_object('kind',kind,'identity',identity,'fields',fields)
            ORDER BY kind,identity),'[]') FROM evidence
        """
        rows = snapshot.value(query)
        # Inventory unhandled namespace-dependent objects, extension members and
        # schema-free classes. pg_attrdef/internal triggers are derived and already
        # described by column/constraint definitions. All other unknowns reject.
        unsupported = snapshot.value("WITH objects AS ("+objects+") "+"""
          SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array(i.type,i.identity)),'[]') FROM (
            SELECT e.classid,e.objid,e.objsubid FROM pg_depend e WHERE
              (e.refclassid='pg_namespace'::regclass AND e.refobjid IN
                (SELECT objid FROM objects WHERE kind='schema')) OR e.deptype='e'
            UNION SELECT 'pg_event_trigger'::regclass,oid,0 FROM pg_event_trigger
            UNION SELECT 'pg_cast'::regclass,c.oid,0 FROM pg_cast c WHERE c.castsource IN
              (SELECT objid FROM objects WHERE kind='type') OR c.casttarget IN
              (SELECT objid FROM objects WHERE kind='type')
          ) u CROSS JOIN LATERAL pg_identify_object(u.classid,u.objid,u.objsubid) i
          WHERE NOT EXISTS(SELECT 1 FROM objects o WHERE o.classid=u.classid AND o.objid=u.objid AND o.subid=u.objsubid)
            AND u.classid<>'pg_attrdef'::regclass
            AND NOT(u.classid='pg_trigger'::regclass AND EXISTS
              (SELECT 1 FROM pg_trigger t WHERE t.oid=u.objid AND t.tgisinternal))
        """)
        # Nonstandard relkinds and aggregates cannot be represented by this v1.
        extra = snapshot.value("SELECT coalesce(jsonb_agg(jsonb_build_array('relation',c.oid::regclass::text)),'[]') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+user+
            " AND c.relkind NOT IN ('r','p','m','S','v','i','I','c')")
        labels = snapshot.value("""SELECT coalesce(jsonb_agg(jsonb_build_array('security_label',s.provider,i.identity)),'[]')
            FROM pg_seclabel s CROSS JOIN LATERAL pg_identify_object(s.classoid,s.objoid,s.objsubid) i""")
        entries = {}
        for row in rows:
            key = canonical_hash([row["kind"], row["identity"]])
            require(key not in entries, "schema_evidence_duplicate_identity")
            entries[key] = row
        unknown = sorted({canonical_hash(item) for item in unsupported + extra + labels})
        result = {"server_version_num": version, "complete": not unknown, "unsupported": unknown,
                  "coverage": {kind: sum(row["kind"] == kind for row in rows) for kind in cls.KINDS},
                  "objects": entries}
        require(len(json.dumps(result).encode()) <= 3 * 1024**2, "schema_evidence_too_large")
        return result

    @classmethod
    def bind(cls, evidence, state, archive, sources):
        require(evidence["complete"], "schema_evidence_incomplete")
        return {"format": "nomosmart-schema-evidence", "version": cls.VERSION, "collector": cls.COLLECTOR,
                "sources": sources, "image": PG_IMAGE, "snapshot_sha256": canonical_hash(state),
                "archive": archive.expected, "evidence": evidence, "evidence_sha256": canonical_hash(evidence)}

    @classmethod
    def read(cls, archive, state):
        path = archive.directory / cls.FILE
        require(path.exists(), "schema_evidence_unavailable")
        value = read_private_json(path)
        require(value.get("format") == "nomosmart-schema-evidence" and type(value.get("version")) is int
                and value["version"] == cls.VERSION
                and value.get("collector") == cls.COLLECTOR, "schema_evidence_version")
        require(value.get("sources") == tool_sources() and value.get("image") == PG_IMAGE
                and value.get("snapshot_sha256") == canonical_hash(state)
                and value.get("archive") == archive.expected, "schema_evidence_binding")
        evidence = value.get("evidence", {})
        require(value.get("evidence_sha256") == canonical_hash(evidence), "schema_evidence_integrity")
        require(isinstance(evidence, dict) and evidence.get("complete") is True and evidence.get("unsupported") == []
                and isinstance(evidence.get("server_version_num"), int)
                and 180000 <= evidence["server_version_num"] < 190000
                and isinstance(evidence.get("coverage"), dict) and set(evidence["coverage"]) == set(cls.KINDS)
                and isinstance(evidence.get("objects"), dict), "schema_evidence_incomplete")
        counts = dict.fromkeys(cls.KINDS, 0)
        fields = {"definition", "owner", "comment", "acl", "initial_acl", "dependencies"}
        for key, row in evidence["objects"].items():
            require(isinstance(row, dict) and isinstance(row.get("kind"), str) and row["kind"] in counts
                    and isinstance(row.get("identity"), str)
                    and key == canonical_hash([row["kind"], row["identity"]])
                    and isinstance(row.get("fields"), dict) and set(row["fields"]) == fields,
                    "schema_evidence_object_invalid")
            counts[row["kind"]] += 1
        require(counts == evidence["coverage"] and counts["extension"] > 0, "schema_evidence_inventory")
        info = path.lstat()
        require(archive.schema_evidence_binding == (info.st_dev, info.st_ino, canonical_hash(value)),
                "schema_evidence_changed")
        archive.verify()
        return value

    @staticmethod
    def diff(expected, actual):
        left, right = expected["objects"], actual["objects"]
        changes = []
        for key in sorted(left.keys() | right.keys()):
            a, b = left.get(key), right.get(key)
            if a == b:
                continue
            field_names = sorted(name for name in (a or b)["fields"]
                                 if not a or not b or a["fields"].get(name) != b["fields"].get(name))
            changes.append({"key_sha256": key, "kind": (a or b)["kind"],
                "change": "added" if not a else "missing" if not b else "changed", "fields": field_names,
                "before_sha256": canonical_hash(a) if a else None, "after_sha256": canonical_hash(b) if b else None})
        complete = expected["complete"] and actual["complete"]
        same_version = expected["server_version_num"] == actual["server_version_num"]
        return {"status": "UNAVAILABLE" if not complete else "EQUAL" if not changes and same_version else "DIFFERENT",
                "same_server_version": same_version, "changes": changes, "count": len(changes),
                "expected_sha256": canonical_hash(expected), "actual_sha256": canonical_hash(actual)}


class RestoreIdentityProfile:
    """New same-snapshot collector, opt-in ONLY for our new synthetic sources.

    R3 catalog evidence stays readable and unchanged. This separate v1 profile
    supplies information R3 deliberately hashed (extension version/schema).
    No profile can be reconstructed from a retained/live archive or DB owner.
    """

    FILE = "restore-identity-v1.json"
    COLLECTOR = "pg18-restore-identity-v1"
    SOURCE_KIND = "r4-owned-synthetic"
    # Fixed PG_IMAGE installation inventories observed in the genuine T15
    # roundtrip; rejection guards, NOT replacement expected restore results.
    MEMBERS = {
        "plpgsql": ("pg_catalog", "3db14108c290004fc8727332676dd2267b72e238ccdef7b259f6a4c5f6194dfd"),
        "pgcrypto": ("public", "198493ec078727ef6de72ed71c8f1f243172dbad9b542155e1e4d2dbf2dea499"),
    }

    @staticmethod
    def identifier(value):
        require(isinstance(value, str) and 0 < len(value.encode("utf8")) <= 63
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
                and not value.lower().startswith("pg_")
                and value.lower() not in ("public", "none", "current_user", "session_user"),
                "restore_identity_invalid")
        return value

    @classmethod
    def collect(cls, snap, catalog):
        extensions = snap.value("""SELECT jsonb_agg(jsonb_build_object('name',e.extname,
            'version',e.extversion,'schema',n.nspname,'owner',pg_get_userbyid(e.extowner)) ORDER BY e.extname)
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace""")
        result = {"collector": cls.COLLECTOR, "version": 1,
            "server_version_num": catalog["server_version_num"],
            "catalog_sha256": canonical_hash(catalog), "extensions": extensions}
        cls.select(result, catalog)
        return result

    @classmethod
    def select(cls, value, catalog):
        require(value.get("collector") == cls.COLLECTOR and type(value.get("version")) is int
                and value["version"] == 1 and value.get("server_version_num") == catalog["server_version_num"]
                and value.get("catalog_sha256") == canonical_hash(catalog), "restore_profile_version_binding")
        require(catalog["complete"] and not catalog["unsupported"], "restore_profile_incomplete")
        extensions = value.get("extensions")
        require(isinstance(extensions, list) and extensions, "restore_profile_extensions_missing")
        rows = catalog["objects"]
        names, owners = set(), set()
        for extension in extensions:
            name = extension.get("name")
            # Initial covered fixed-image profiles, not an arbitrary installer.
            require(name in ("plpgsql", "pgcrypto") and name not in names,
                    "restore_profile_extension_unsupported")
            names.add(name)
            require(isinstance(extension.get("version"), str) and extension["version"]
                    and isinstance(extension.get("schema"), str) and extension["schema"],
                    "restore_profile_extension_metadata_missing")
            require(extension["version"] == {"plpgsql": "1.0", "pgcrypto": "1.4"}[name],
                    "restore_profile_version_unsupported")
            entry = rows.get(canonical_hash(["extension", name]))
            require(entry is not None and entry["fields"]["owner"] == extension.get("owner"),
                    "restore_profile_extension_owner")
            owners.add(cls.identifier(extension["owner"]))
            members = [row for row in rows.values()
                       if ["e", "extension", name] in row["fields"]["dependencies"]]
            require(members, "restore_profile_members_missing")
            schema, identities = cls.MEMBERS[name]
            require(extension["schema"] == schema and canonical_hash(sorted(
                [m["kind"], m["identity"]] for m in members)) == identities,
                "restore_profile_member_inventory")
            for member in members:
                require(member["kind"] in ("routine", "language", "type"), "restore_profile_member_unsupported")
                owners.add(cls.identifier(member["fields"]["owner"]))
                initial = member["fields"]["initial_acl"]
                if initial:
                    require(initial["type"] in ("i", "e"), "restore_profile_initial_acl")
                    owners.update(cls.identifier(grant[0]) for grant in initial["grants"])
        require(names == {row["identity"] for row in rows.values() if row["kind"] == "extension"}
                and "plpgsql" in names, "restore_profile_inventory")
        require(len(owners) == 1, "restore_profile_mixed_owners")
        return owners.pop()

    @classmethod
    def read(cls, archive, state):
        original = SchemaEvidence.read(archive, state)
        require(archive.restore_identity_binding is not None, "synthetic_restore_profile_required")
        path = archive.directory / cls.FILE
        value = read_private_json(path)
        info = path.lstat()
        require(archive.restore_identity_binding == (info.st_dev, info.st_ino, canonical_hash(value)),
                "restore_profile_changed")
        require(value.get("source_kind") == cls.SOURCE_KIND and value.get("sources") == tool_sources()
                and value.get("image") == PG_IMAGE and value.get("archive") == archive.expected
                and value.get("snapshot_sha256") == canonical_hash(state)
                and value.get("schema_evidence_sha256") == canonical_hash(original), "restore_profile_binding")
        bootstrap = cls.select(value["profile"], original["evidence"])
        return value, bootstrap

    @classmethod
    def prepare(cls, archive, state, lab, target, deadline):
        value, bootstrap = cls.read(archive, state)
        require(lab.bootstrap == bootstrap and target in lab.fresh_targets, "restore_profile_target_identity")
        lab.empty_restore(target)
        with Snapshot(lab.command("psql", target, *PSQL), deadline=deadline) as snap:
            require(snap.value("SELECT current_setting('server_version_num')::int") ==
                    value["profile"]["server_version_num"], "restore_profile_target_version")
            installed = snap.value("SELECT jsonb_agg(extname ORDER BY extname) FROM pg_extension")
            require(installed == ["plpgsql"], "restore_profile_target_extensions")
            for extension in value["profile"]["extensions"]:
                available = snap.value("SELECT count(*) FROM pg_available_extension_versions WHERE name="+
                    literal(extension["name"])+" AND version="+literal(extension["version"]))
                require(available == 1, "restore_profile_version_unavailable")
        names, toc = cls.read_toc(archive, value["profile"], lab, deadline)
        recreate = "plpgsql" in names
        if recreate:
            # RESTRICT is essential: unexpected dependencies must fail, not disappear.
            lab.sql(target, "DROP EXTENSION plpgsql RESTRICT")
        lab.fresh_targets.remove(target)
        private_json(archive.directory / ("restore-preparation-"+secrets.token_hex(8)+".json"), {
            "profile_sha256": canonical_hash(value), "bootstrap_sha256": canonical_hash(bootstrap),
            **toc, "plpgsql_recreated": recreate, "archive_filtered": False})

    @staticmethod
    def read_toc(archive, profile, lab, deadline):
        # Read the COMPLETE immutable archive TOC, never pass a selection list.
        archive.verify()
        os.lseek(archive.fd, 0, os.SEEK_SET)
        toc = bytearray()
        read_process(lab.docker("exec", "-i", lab.cid, "pg_restore", "--list"), toc.extend,
                     limit=4*1024**2, deadline=deadline, input_fd=archive.fd)
        archive.verify()
        entries = re.findall(rb"^\d+; \d+ \d+ EXTENSION - ([^\r\n]+)$", bytes(toc), re.M)
        names = {item.decode("utf8").strip() for item in entries}
        expected = {item["name"] for item in profile["extensions"]}
        require(names <= expected and expected - names <= {"plpgsql"}, "restore_profile_toc_inventory")
        return names, {"toc_sha256": hashlib.sha256(toc).hexdigest(), "toc_bytes": len(toc)}


class MixedRestoreIdentityProfile(RestoreIdentityProfile):
    """R5 opt-in trusted A/B shape only. Never upgrades a legacy profile."""

    FILE = "restore-identity-v2.json"
    COLLECTOR = "pg18-trusted-restore-identity-v2"
    SOURCE_KIND = "r5-owned-synthetic"
    VERSION = 2

    @staticmethod
    def controls(snap):
        return snap.value("""SELECT jsonb_agg(jsonb_build_object('name',name,'version',version,
            'trusted',trusted,'superuser',superuser,'requires',coalesce(requires,ARRAY[]::name[]))
            ORDER BY name) FROM pg_available_extension_versions
            WHERE (name='plpgsql' AND version='1.0') OR (name='pgcrypto' AND version='1.4')""")

    @classmethod
    def collect(cls, snap, catalog):
        extensions = snap.value("""SELECT jsonb_agg(jsonb_build_object('name',e.extname,
            'version',e.extversion,'schema',n.nspname,'owner',pg_get_userbyid(e.extowner)) ORDER BY e.extname)
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace""")
        facts = snap.value("""SELECT jsonb_build_object('database_owner',pg_get_userbyid(datdba),
            'owner_create',has_database_privilege(datdba,oid,'CREATE'),'roles',
            (SELECT jsonb_object_agg(rolname,jsonb_build_object('superuser',rolsuper)) FROM pg_roles
             WHERE oid IN (SELECT extowner FROM pg_extension) OR oid=d.datdba))
            FROM pg_database d WHERE datname=current_database()""")
        result = {"collector": cls.COLLECTOR, "version": cls.VERSION,
            "server_version_num": catalog["server_version_num"], "catalog_sha256": canonical_hash(catalog),
            "extensions": extensions, "controls": cls.controls(snap), **facts}
        cls.select(result, catalog)
        return result

    @classmethod
    def select(cls, value, catalog):
        require(value.get("collector") == cls.COLLECTOR and type(value.get("version")) is int
                and value["version"] == cls.VERSION and value.get("server_version_num") == 180004
                and catalog["server_version_num"] == 180004
                and value.get("catalog_sha256") == canonical_hash(catalog), "mixed_profile_version_binding")
        require(catalog["complete"] and not catalog["unsupported"], "mixed_profile_incomplete")
        extensions = value.get("extensions")
        require(isinstance(extensions, list) and len(extensions) == 2
                and {e.get("name") for e in extensions} == {"plpgsql", "pgcrypto"}, "mixed_profile_inventory")
        expected_controls = [{"name": name, "version": version, "trusted": True,
                              "superuser": True, "requires": []}
                             for name, version in (("pgcrypto", "1.4"), ("plpgsql", "1.0"))]
        require(canonical_hash(value.get("controls")) == canonical_hash(expected_controls), "mixed_profile_controls")
        by_name = {e["name"]: e for e in extensions}
        installer = cls.identifier(by_name["pgcrypto"].get("owner"))
        bootstrap = cls.identifier(by_name["plpgsql"].get("owner"))
        require(installer != bootstrap and value.get("database_owner") == installer
                and value.get("owner_create") is True
                and canonical_hash(value.get("roles")) == canonical_hash(
                    {installer: {"superuser": False}, bootstrap: {"superuser": True}}),
                "mixed_profile_roles")
        rows = catalog["objects"]
        require({r["identity"] for r in rows.values() if r["kind"] == "extension"} == set(by_name),
                "mixed_profile_inventory")
        for name, ext in by_name.items():
            require(ext.get("version") == {"plpgsql": "1.0", "pgcrypto": "1.4"}[name]
                    and ext.get("schema") == cls.MEMBERS[name][0], "mixed_profile_extension_metadata")
            entry = rows.get(canonical_hash(["extension", name]))
            require(entry and entry["fields"]["owner"] == ext["owner"], "mixed_profile_extension_owner")
            members = [r for r in rows.values() if ["e", "extension", name] in r["fields"]["dependencies"]]
            require(canonical_hash(sorted([r["kind"], r["identity"]] for r in members)) == cls.MEMBERS[name][1],
                    "mixed_profile_members")
            require(entry["fields"]["initial_acl"] is None and all(r["fields"]["owner"] == bootstrap
                and r["fields"]["initial_acl"] is None for r in members), "mixed_profile_member_ownership")
        return bootstrap

    @classmethod
    def prepare(cls, archive, state, lab, target, deadline):
        value, bootstrap = cls.read(archive, state)
        profile = value["profile"]
        installer = profile["database_owner"]
        require(state["properties"]["owner"] == installer and lab.bootstrap == bootstrap
                and target in lab.fresh_targets, "mixed_profile_target_identity")
        lab.guard()
        lab.empty_restore(target)
        with Snapshot(lab.command("psql", target, *PSQL), deadline=deadline) as snap:
            initial = SchemaEvidence.collect(snap)
            require(initial["server_version_num"] == profile["server_version_num"]
                    and cls.controls(snap) == profile["controls"], "mixed_target_controls")
            members = [r for r in initial["objects"].values()
                       if ["e", "extension", "plpgsql"] in r["fields"]["dependencies"]]
            require(initial["complete"] and len(initial["objects"]) == 6 and len(members) == 4
                    and canonical_hash(sorted([r["kind"], r["identity"]] for r in members)) == cls.MEMBERS["plpgsql"][1],
                    "mixed_target_not_pristine")
            public = initial["objects"].get(canonical_hash(["schema", "public"]))
            require(public and public["fields"]["owner"] == "pg_database_owner"
                    and not any(g[1] == "PUBLIC" and g[2] == "CREATE" for g in public["fields"]["acl"]["grants"]),
                    "mixed_target_schema_unsafe")
            initial_profile = RestoreIdentityProfile.collect(snap, initial)
            require(RestoreIdentityProfile.select(initial_profile, initial) == bootstrap, "mixed_target_bootstrap")
            cls.target_roles(snap, installer, bootstrap)
            require(snap.value("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                               "AND backend_type='client backend' AND pid<>pg_backend_pid()") == 0,
                    "mixed_target_connections")
        names, toc = cls.read_toc(archive, profile, lab, deadline)
        lab.fresh_targets.remove(target)  # Any preparation attempt consumes this target, including failure.
        sql = "BEGIN; SET LOCAL statement_timeout='10s'; SET LOCAL lock_timeout='2s'; SET LOCAL search_path=pg_catalog; "
        sql += "SET LOCAL application_name='v49b-trusted-install'; "
        if "plpgsql" in names:
            sql += "DROP EXTENSION plpgsql RESTRICT; "
        sql += "SET LOCAL ROLE "+quote_ident(installer)+"; CREATE EXTENSION pgcrypto WITH SCHEMA public VERSION '1.4'; COMMIT; "
        sql += "SELECT current_user="+literal(bootstrap)+" AND session_user="+literal(bootstrap)
        require(time.monotonic() < deadline, "restore_timeout")
        require(run(lab.command("psql", target, *PSQL), data=sql.encode(),
                    timeout=min(30, max(0.01, deadline-time.monotonic()))).strip() == b"t", "mixed_role_not_reset")
        source = SchemaEvidence.read(archive, state)["evidence"]
        with Snapshot(lab.command("psql", target, *PSQL), deadline=deadline) as snap:
            prepared = SchemaEvidence.collect(snap)
            cls.target_roles(snap, installer, bootstrap)
            require(snap.value("SELECT to_json(current_user="+literal(bootstrap)+")") is True, "mixed_role_not_reset")
        keys = {k for k, r in source["objects"].items() if r["kind"] == "extension" and r["identity"] == "pgcrypto"
                or ["e", "extension", "pgcrypto"] in r["fields"]["dependencies"]}
        actual_keys = {k for k, r in prepared["objects"].items() if r["kind"] == "extension" and r["identity"] == "pgcrypto"
                       or ["e", "extension", "pgcrypto"] in r["fields"]["dependencies"]}
        require(prepared["complete"] and keys == actual_keys, "mixed_prepared_members")
        require(all(all(source["objects"][k]["fields"][field] == prepared["objects"][k]["fields"][field]
                        for field in ("definition", "owner", "initial_acl", "dependencies")) for k in keys),
                "mixed_prepared_definition_differs")
        require(cls.read(archive, state)[0] == value, "mixed_profile_changed")
        private_json(archive.directory / ("restore-preparation-"+secrets.token_hex(8)+".json"), {
            "profile_sha256": canonical_hash(value), "bootstrap_sha256": canonical_hash(bootstrap),
            "installer_sha256": canonical_hash(installer), **toc, "pgcrypto_precreated": True,
            "plpgsql_recreated": "plpgsql" in names, "archive_filtered": False,
            "prepared_catalog_sha256": canonical_hash(prepared), "role_reset": True})

    @staticmethod
    def target_roles(snap, installer, bootstrap):
        require(snap.value("SELECT coalesce(jsonb_agg(rolname ORDER BY rolname),'[]') FROM pg_roles WHERE rolsuper")
                == [bootstrap], "mixed_target_superusers")
        require(snap.value("SELECT count(*) FROM pg_roles WHERE rolname="+literal(installer)+
            " AND NOT(rolsuper OR rolcanlogin OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)") == 1,
            "mixed_target_installer_privileges")
        require(snap.value("SELECT to_json(has_database_privilege("+literal(installer)+",current_database(),'CREATE'))") is True,
                "mixed_target_create_required")


class ExtensionMemberComments:
    """R6 explicit synthetic sidecar. Bodies are data, never executable SQL.

    Original catalog/hash collectors remain unchanged. Only this bounded
    collector exports comment bodies, exclusively to private source-bound files.
    """

    FILE = "extension-member-comments-v1.json"
    COLLECTOR = "pg18-extension-member-comments-v1"
    SOURCE_KIND = "r6-owned-synthetic"
    PROFILE = MixedRestoreIdentityProfile
    PER_COMMENT = 64 * 1024
    TOTAL = 1024 * 1024
    MEMBERS_SQL = """SELECT e.extname,e.extversion,en.nspname AS extension_schema,
        d.classid,d.objid,d.objsubid,des.objoid AS comment_oid,des.description
        FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
        JOIN pg_namespace en ON en.oid=e.extnamespace
        LEFT JOIN pg_description des ON des.classoid=d.classid AND des.objoid=d.objid AND des.objsubid=d.objsubid
        WHERE d.refclassid='pg_extension'::regclass AND d.deptype='e'"""

    @staticmethod
    def scope(directory):
        root = custody(Path(os.environ.get("V49_BACKUP_ARTIFACTS", "/")))
        require(root.parent == Path("/private/tmp") and root.name.startswith("v049-backup-plain-r6-")
                and directory.is_relative_to(root), "member_comments_scope")
        return root

    @classmethod
    def collect(cls, snap, catalog):
        snap.query("SET LOCAL search_path=pg_catalog")
        bounds = snap.value("WITH members AS ("+cls.MEMBERS_SQL+") SELECT jsonb_build_array(count(*), "
            "coalesce(max(octet_length(description)),0),coalesce(sum(octet_length(description)),0), "
            "count(*) FILTER(WHERE classid NOT IN ('pg_proc'::regclass,'pg_language'::regclass) OR objsubid<>0 "
            "OR (comment_oid IS NOT NULL AND (description IS NULL OR description='')))) FROM members")
        require(bounds[0] == 41 and bounds[3] == 0, "member_comments_inventory")
        require(bounds[1] <= cls.PER_COMMENT and bounds[2] <= cls.TOTAL, "member_comments_too_large")
        query = "WITH members AS ("+cls.MEMBERS_SQL+"""), rows AS (
          SELECT jsonb_build_object('extension',m.extname,'version',m.extversion,'extension_schema',m.extension_schema,
            'kind',CASE WHEN m.classid='pg_proc'::regclass THEN 'routine' ELSE 'language' END,'identity',i.identity,
            'target',CASE WHEN m.classid='pg_proc'::regclass THEN
              jsonb_build_object('kind','function','schema',n.nspname,'name',p.proname,'prokind',p.prokind,
                'args',(SELECT coalesce(jsonb_agg(jsonb_build_array(tn.nspname,t.typname) ORDER BY a.position),'[]')
                  FROM unnest(p.proargtypes) WITH ORDINALITY a(typeid,position)
                  JOIN pg_type t ON t.oid=a.typeid JOIN pg_namespace tn ON tn.oid=t.typnamespace))
              ELSE jsonb_build_object('kind','language','name',l.lanname) END,
            'body',m.description,'bytes',coalesce(octet_length(m.description),0),
            'comment',jsonb_build_object('state',CASE WHEN m.comment_oid IS NULL THEN 'absent' ELSE 'value' END,
              'sha256',CASE WHEN m.description IS NOT NULL THEN encode(sha256(convert_to(m.description,'UTF8')),'hex') END)
          ) AS value FROM members m
          CROSS JOIN LATERAL pg_identify_object(m.classid,m.objid,m.objsubid) i
          LEFT JOIN pg_proc p ON m.classid='pg_proc'::regclass AND p.oid=m.objid
          LEFT JOIN pg_namespace n ON n.oid=p.pronamespace
          LEFT JOIN pg_language l ON m.classid='pg_language'::regclass AND l.oid=m.objid)
          SELECT jsonb_agg(value ORDER BY value->>'kind',value->>'identity') FROM rows"""
        rows = snap.value(query)
        evidence = {canonical_hash([r["kind"], r["identity"]]): r for r in rows}
        cls.validate(evidence, catalog)
        return evidence

    @staticmethod
    def target_sql(target):
        require(isinstance(target, dict) and target.get("kind") in ("function", "language"), "member_target_invalid")
        def identifier(name):
            require(isinstance(name, str) and 0 < len(name.encode()) <= 63 and "\x00" not in name,
                    "member_target_identifier")
            return quote_ident(name)
        if target["kind"] == "language":
            require(set(target) == {"kind", "name"}, "member_target_invalid")
            return "LANGUAGE "+identifier(target["name"])
        require(set(target) == {"kind", "schema", "name", "prokind", "args"} and target["prokind"] == "f"
                and isinstance(target["args"], list) and len(target["args"]) <= 100, "member_target_invalid")
        args = []
        for pair in target["args"]:
            require(isinstance(pair, list) and len(pair) == 2, "member_target_argument")
            args.append(identifier(pair[0])+"."+identifier(pair[1]))
        return "FUNCTION "+identifier(target["schema"])+"."+identifier(target["name"])+"("+",".join(args)+")"

    @classmethod
    def validate(cls, rows, catalog):
        require(isinstance(rows, dict) and len(rows) == 41 and catalog["complete"]
                and catalog["server_version_num"] == 180004, "member_comments_inventory")
        expected = {k: r for k, r in catalog["objects"].items()
                    if any(["e", "extension", name] in r["fields"]["dependencies"] for name in ("pgcrypto", "plpgsql"))}
        require(set(rows) == set(expected), "member_comments_inventory")
        total, targets = 0, set()
        for key, row in rows.items():
            require(isinstance(row, dict) and set(row) == {"extension", "version", "extension_schema", "kind",
                "identity", "target", "body", "bytes", "comment"}, "member_comments_shape")
            original = expected[key]
            name = row["extension"]
            require(name in RestoreIdentityProfile.MEMBERS and row["version"] == {"pgcrypto": "1.4", "plpgsql": "1.0"}[name]
                    and row["extension_schema"] == RestoreIdentityProfile.MEMBERS[name][0]
                    and ["e", "extension", name] in original["fields"]["dependencies"]
                    and row["kind"] == original["kind"] and row["identity"] == original["identity"], "member_comments_identity")
            target = cls.target_sql(row["target"])
            require(target not in targets and row["target"]["kind"] == ("function" if row["kind"] == "routine" else "language"),
                    "member_comments_target")
            targets.add(target)
            body = row["body"]
            require(body is None or isinstance(body, str) and body and "\x00" not in body, "member_comment_state_unsupported")
            size = len(body.encode()) if body is not None else 0
            comment = {"state": "absent" if body is None else "value",
                       "sha256": hashlib.sha256(body.encode()).hexdigest() if body is not None else None}
            require(type(row["bytes"]) is int and row["bytes"] == size and row["comment"] == comment
                    and comment == original["fields"]["comment"], "member_comments_body_binding")
            total += size
            require(size <= cls.PER_COMMENT and total <= cls.TOTAL, "member_comments_too_large")
        for name, (_, digest) in RestoreIdentityProfile.MEMBERS.items():
            require(canonical_hash(sorted([r["kind"], r["identity"]] for r in rows.values() if r["extension"] == name))
                    == digest, "member_comments_inventory")
        require(len(json.dumps(rows).encode()) <= 4 * 1024**2, "member_comments_too_large")

    @classmethod
    def bind(cls, archive, state, rows, source):
        cls.scope(archive.directory)
        catalog = SchemaEvidence.read(archive, state)
        profile, _ = MixedRestoreIdentityProfile.read(archive, state)
        cls.validate(rows, catalog["evidence"])
        require(source == profile["source"] and re.fullmatch(r"v49b-[a-f0-9]{16}", source.get("run", "")),
                "member_comments_source")
        value = {"format": "nomosmart-extension-member-comments", "version": 1, "collector": cls.COLLECTOR,
            "source_kind": cls.SOURCE_KIND, "source": source, "image": PG_IMAGE, "sources": tool_sources(),
            "archive": archive.expected, "snapshot_sha256": canonical_hash(state),
            "catalog_sha256": canonical_hash(catalog), "profile_sha256": canonical_hash(profile),
            "members": rows, "members_sha256": canonical_hash(rows)}
        require(len(json.dumps(value, indent=2).encode()) < 4 * 1024**2, "member_comments_too_large")
        path = archive.directory / cls.FILE
        private_json(path, value)
        info = path.lstat()
        archive.member_comments_binding = (info.st_dev, info.st_ino, canonical_hash(value))

    @classmethod
    def read(cls, archive, state):
        cls.scope(archive.directory)
        require(archive.member_comments_binding is not None, "member_comments_required")
        catalog = SchemaEvidence.read(archive, state)
        profile, _ = MixedRestoreIdentityProfile.read(archive, state)
        path = archive.directory / cls.FILE
        value = read_private_json(path)
        info = path.lstat()
        require(archive.member_comments_binding == (info.st_dev, info.st_ino, canonical_hash(value)), "member_comments_changed")
        require(value.get("format") == "nomosmart-extension-member-comments" and type(value.get("version")) is int
                and value["version"] == 1 and value.get("collector") == cls.COLLECTOR
                and value.get("source_kind") == cls.SOURCE_KIND, "member_comments_version")
        require(value.get("source") == profile["source"] and value.get("sources") == tool_sources()
                and value.get("image") == PG_IMAGE and value.get("archive") == archive.expected
                and value.get("snapshot_sha256") == canonical_hash(state)
                and value.get("catalog_sha256") == canonical_hash(catalog)
                and value.get("profile_sha256") == canonical_hash(profile)
                and value.get("members_sha256") == canonical_hash(value.get("members")), "member_comments_binding")
        cls.validate(value["members"], catalog["evidence"])
        archive.verify()
        return value

    @classmethod
    def precheck(cls, expected, actual, original, current, state, actual_state):
        require(actual_state == state, "member_comments_state_differs")
        diff = SchemaEvidence.diff(original, current)
        require(diff["same_server_version"] and diff["status"] in ("EQUAL", "DIFFERENT")
                and all(d["key_sha256"] in expected and d["change"] == "changed" and d["fields"] == ["comment"]
                        for d in diff["changes"]), "member_comments_noncomment_difference")
        require(set(expected) == set(actual) and all(
            {k: v for k, v in expected[key].items() if k not in ("body", "bytes", "comment")} ==
            {k: v for k, v in actual[key].items() if k not in ("body", "bytes", "comment")} for key in expected),
            "member_comments_target_identity")
        return sorted(d["key_sha256"] for d in diff["changes"])

    @staticmethod
    def begin_write(tx):
        tx.query("ROLLBACK; BEGIN ISOLATION LEVEL REPEATABLE READ; SET LOCAL statement_timeout='10s'; "
            "SET LOCAL lock_timeout='2s'; SET LOCAL idle_in_transaction_session_timeout='300s'; "
            "SET LOCAL search_path=pg_catalog; SET LOCAL standard_conforming_strings=on; "
            "SET LOCAL application_name='v49b-member-comments'")

    @classmethod
    def apply_rows(cls, tx, rows):
        # Internal transaction primitive: replay has already validated complete
        # source bindings, target membership and all non-comment fields.
        for row in rows:
            tx.query("COMMENT ON "+cls.target_sql(row["target"])+" IS "+(
                "NULL" if row["body"] is None else literal(row["body"])))

    @classmethod
    def replay(cls, archive, state, lab, target, deadline):
        expected = cls.read(archive, state)
        original = SchemaEvidence.read(archive, state)["evidence"]
        profile, bootstrap = cls.PROFILE.read(archive, state)
        require(type(lab) is MemoryPostgres and lab.bootstrap == bootstrap
                and lab.comment_targets.pop(target, None) == (archive.identity, archive.expected["sha256"]),
                "member_comments_target_not_owned")
        lab.guard()
        command = lambda tool, *args: lab.command(tool, target, *args)
        report = {"status": "ERROR", "phase": "precheck", "evidence_sha256": canonical_hash(expected)}
        try:
            with Snapshot(command("psql", *PSQL), deadline=deadline) as tx:
                current = SchemaEvidence.collect(tx)
                actual = cls.collect(tx, current)
                actual_state = DatabaseState.collect(tx, command)
                # Preserve evidence before the strict guard can raise. Never
                # publish row text, object identities, comments or child stderr.
                report["state_diagnostics"] = state_diagnostics(state, actual_state, original, current)
                changed = cls.precheck(expected["members"], actual, original, current, state, actual_state)
                MixedRestoreIdentityProfile.target_roles(tx, profile["profile"]["database_owner"], bootstrap)
                require(tx.value("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND backend_type='client backend' AND pid<>pg_backend_pid()") == 0, "member_comments_connections")
                require(tx.value("SELECT to_json(current_user="+literal(bootstrap)+" AND session_user="+literal(bootstrap)+")")
                        is True, "member_comments_role")
                # Same bounded connection, now a NEW writable transaction. The
                # old read-only exported snapshot is not used for the writes.
                cls.begin_write(tx)
                report["phase"] = "comment"
                before = SchemaEvidence.collect(tx)
                require(before == current and cls.collect(tx, before) == actual, "member_comments_target_drift")
                cls.apply_rows(tx, [expected["members"][key] for key in changed])
                after = SchemaEvidence.collect(tx)
                require(cls.collect(tx, after) == expected["members"]
                        and SchemaEvidence.diff(original, after)["status"] == "EQUAL", "member_comments_replay_differs")
                require(cls.read(archive, state) == expected, "member_comments_changed")
                tx.query("COMMIT")
                report.update(status="PASS", phase="committed", changed=len(changed), members=41)
        finally:
            private_json(archive.directory / ("member-comments-replay-"+secrets.token_hex(8)+".json"), report)
        return canonical_hash(expected)


class MemoryPostgres:
    """One exact-owned PostgreSQL; no network, persistent volume or host mounts."""

    def __init__(self, directory, *, bootstrap="backup_verify"):
        self.directory = secure_directory(directory)
        self.bootstrap = RestoreIdentityProfile.identifier(bootstrap)
        self.builtin_roles = frozenset()
        self.fresh_targets = set()
        self.comment_targets = {}
        self.run_id = "v49b-" + secrets.token_hex(8)
        self.cid = None
        self.baseline = None

    @staticmethod
    def docker(*args):
        return ["docker", "--context", "desktop-linux", *args]

    def inspect(self):
        require(self.cid is not None, "missing_owned_container")
        return json.loads(run(self.docker("inspect", self.cid)))[0]

    def inventory(self):
        ids = run(self.docker("ps", "-aq", "--no-trunc")).decode().split()
        result = {"containers": {}}
        for cid in ids:
            item = json.loads(run(self.docker("inspect", cid)))[0]
            result["containers"][cid] = [item["Image"], item["State"]["Status"], item["State"]["StartedAt"]]
        for kind in ("volume", "network", "image"):
            result[kind] = sorted(set(run(self.docker(kind, "ls", "-q")).decode().split()))
        return result

    def guard(self):
        item = self.inspect()
        host = item["HostConfig"]
        require(item["Config"]["Labels"].get(LABEL) == self.run_id and item["Image"] == PG_IMAGE,
                "container_identity_changed")
        require(host["NetworkMode"] == "none" and not host["PortBindings"] and not host["Privileged"],
                "container_network_unsafe")
        require(host["LogConfig"]["Type"] == "none", "persistent_logs_not_allowed")
        require(host["Memory"] == 4 * 1024**3 and host["MemorySwap"] == host["Memory"]
                and host["NanoCpus"] == 2 * 10**9, "container_limits_changed")
        require(not host.get("Binds") and all(m["Type"] == "tmpfs" for m in item["Mounts"]),
                "persistent_storage_not_allowed")
        require("/var/lib/postgresql" in host["Tmpfs"] and "size=2g" in host["Tmpfs"]["/var/lib/postgresql"],
                "pg_tmpfs_missing")
        require("/docker-entrypoint-initdb.d" in host["Tmpfs"], "application_initializer_not_isolated")
        require(item["Config"]["Env"].count("PGDATA=/var/lib/postgresql/18/backup") == 1,
                "pgdata_changed")
        require([v for v in item["Config"]["Env"] if v.startswith("POSTGRES_USER=")] ==
                ["POSTGRES_USER="+self.bootstrap], "container_bootstrap_changed")

    def start(self):
        self.baseline = self.inventory()
        require(not run(self.docker("ps", "-aq", "--filter", "label="+LABEL)).strip(),
                "owned_postgres_already_active")
        require(json.loads(run(self.docker("image", "inspect", PG_IMAGE)))[0]["Id"] == PG_IMAGE,
                "postgres_image_changed")
        # Fresh random credential only, never copied from the source environment.
        credential = secrets.token_hex(32)
        private_json(self.directory / "container-intent.json", {"label": LABEL, "run": self.run_id,
            "image": PG_IMAGE, "baseline": self.baseline, "bootstrap": self.bootstrap})
        registry = os.environ.get("V49_BACKUP_ARTIFACTS")
        if registry:
            root = custody(Path(registry))
            require(root.parent == Path("/private/tmp") and root.name.startswith("v049-backup-"), "registry_path_invalid")
            require(self.directory.is_relative_to(root), "registry_outside_run")
            private_json(root / ("owned-receipt-"+self.run_id+".json"),
                {"relative_directory": str(self.directory.relative_to(root)), "run": self.run_id})
        argv = self.docker("create", "--pull=never", "--name", self.run_id, "--label", LABEL+"="+self.run_id,
            "--network=none", "--cpus=2", "--memory=4g", "--memory-swap=4g", "--pids-limit=256",
            "--log-driver=none", "--ulimit=core=0",
            "--tmpfs=/var/lib/postgresql:rw,nosuid,nodev,size=2g", "--tmpfs=/tmp:rw,nosuid,nodev,size=128m",
            "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16m",
            # This is a database restore sandbox, not an application install.
            # Hide bundled NomoSmart/Keycloak credential-provisioning scripts in
            # an empty memory mount; run the genuine PostgreSQL initializer only.
            "--tmpfs=/docker-entrypoint-initdb.d:ro,nosuid,nodev,size=1m",
            "--env", "PGDATA=/var/lib/postgresql/18/backup", "--env", "POSTGRES_USER="+self.bootstrap,
            "--env", "POSTGRES_DB=postgres", "--env", "POSTGRES_PASSWORD="+credential,
            PG_IMAGE, "postgres", "-c", "listen_addresses=", "-c", "log_statement=none",
            "-c", "log_min_error_statement=panic", "-c", "logging_collector=off")
        self.cid = run(argv).decode().strip()
        require(re.fullmatch(r"[0-9a-f]{64}", self.cid), "invalid_container_id")
        private_json(self.directory / "container-receipt.json", {"id": self.cid, "label": LABEL,
            "run": self.run_id, "image": PG_IMAGE, "baseline": self.baseline, "bootstrap": self.bootstrap})
        self.guard()
        run(self.docker("start", self.cid))
        for _ in range(100):
            try:
                run(self.docker("exec", self.cid, "pg_isready", "-U", self.bootstrap), timeout=3)
                require(run(self.docker("exec", self.cid, "sh", "-c",
                    'head -n 1 "$PGDATA/postmaster.pid"')).strip() == b"1", "postgres_still_initializing")
                initial = json.loads(run(self.docker("exec", "-i", self.cid, "psql", "-U", self.bootstrap,
                    "-d", "postgres", *PSQL), data=b"SELECT json_agg(rolname ORDER BY rolname) FROM pg_roles"))
                self.builtin_roles = frozenset(name for name in initial if name != self.bootstrap)
                return self
            except BackupError:
                time.sleep(0.2)
        raise BackupError("postgres_start_timeout")

    def command(self, tool, db, *args):
        self.guard()
        require(re.fullmatch(r"v49b_[a-z0-9_]+", db), "database_not_owned")
        require(tool in ("psql", "pg_dump", "pg_restore"), "unsupported_pg_tool")
        return self.docker("exec", "-i", self.cid, tool, "--no-password", "-U", self.bootstrap, "-d", db, *args)

    def sql(self, db, sql):
        return run(self.command("psql", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"), data=sql.encode())

    def create_db(self, name):
        self.guard()
        require(re.fullmatch(r"v49b_[a-z0-9_]+", name), "database_not_owned")
        run(self.docker("exec", self.cid, "createdb", "-U", self.bootstrap, "--template=template0", name))
        self.fresh_targets.add(name)

    def empty_restore(self, db):
        self.guard()
        count = int(self.sql(db, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'"))
        require(count == 0, "restore_target_not_empty")
        return self.command("pg_restore", db, "--single-transaction", "--exit-on-error")

    def cleanup(self):
        if self.cid:
            # Even on failed storage guard, identify exactly our own new container.
            item = self.inspect()
            require(item["Config"]["Labels"].get(LABEL) == self.run_id
                    and self.cid not in self.baseline["containers"]
                    and item["Config"]["Env"].count("POSTGRES_USER="+self.bootstrap) == 1,
                    "cleanup_identity_failed")
            volumes = [m["Name"] for m in item["Mounts"] if m["Type"] == "volume"]
            run(self.docker("rm", "-f", self.cid))
            for volume in volumes:
                require(volume not in self.baseline["volume"], "cleanup_existing_volume")
                require(not run(self.docker("ps", "-aq", "--filter", "volume="+volume)).strip(), "volume_shared")
                run(self.docker("volume", "rm", volume))
            self.cid = None
        if self.baseline is not None:
            require(self.inventory() == self.baseline, "docker_baseline_changed")


class BackupSourceEvidence:
    """Fixed, verified adapters. A JSON kind/hash is never a source capability.

    Objects live only for one export/restore/finalization process. Persisted
    evidence cannot recreate this authority or resume an old consumed claim.
    """

    OWNED = "owned-postgresql-rehearsal-v1"
    LIVE = "docker-desktop-live-v1"
    FILE = "backup-source-v1.json"

    def __init__(self):
        raise BackupError("entry_factory_required")

    @classmethod
    def _new(cls, directory, kind, identity, authority):
        value = object.__new__(cls)
        value.directory, value.kind = custody(directory), kind
        value.identity, value.authority = identity, authority
        value.sources = tool_sources()
        value.bindings = {}
        value.archive = None
        value.consumed = value.restored = value.finished = False
        value.fingerprint = canonical_hash([kind, str(directory), identity, authority, value.sources])
        value.bind_file("entry-claim.json", authority)
        return value

    @classmethod
    def owned(cls, lab, database, directory):
        require(type(lab) is MemoryPostgres, "entry_owned_source_required")
        root = ExtensionMemberComments.scope(directory)
        require(lab.directory.is_relative_to(root) and database in lab.fresh_targets,
                "entry_source_not_owned")
        lab.guard()
        identity = {"container": lab.cid, "database": database, "run": lab.run_id, "image": PG_IMAGE}
        authority = {"kind": cls.OWNED, "identity_sha256": canonical_hash(identity),
                     "baseline_sha256": canonical_hash(lab.baseline), "nonce": secrets.token_hex(16)}
        value = cls._new(directory, cls.OWNED, identity, authority)
        value.lab, value.database = lab, database
        return value

    @classmethod
    def live(cls, qualification, binding_sha256, accepted):
        require(accepted is True, "plaintext_opt_in_required")
        proof = require_qualification(qualification)  # All rejection before any live call.
        require(proof.get("entry_contract") == "r7", "entry_qualification_required")
        binding = read_private_json(qualification / "source-binding.json")
        require(binding.get("entry_contract") == "r7" and canonical_hash(binding) == binding_sha256
                and binding["sources"] == tool_sources() and binding["qualification_sha256"] == canonical_hash(proof)
                and 0 <= time.time()-binding["created_epoch"] <= 900, "binding_invalid_or_stale")
        require(LiveSource.identity() == binding["identity"] and LiveSource.protections() == binding["protections"],
                "preflight_drift")
        with Snapshot(LiveSource.command("psql", *PSQL)) as snap:
            LiveSource.member_baseline(snap)
            require(entry_compatibility(snap) == binding["compatibility"], "entry_source_compatibility_drift")
        claim = {"binding_sha256": binding_sha256, "qualification_sha256": canonical_hash(proof),
                 "entry_contract": "r7", "time": time.time()}
        private_json(qualification / "export-claimed.json", claim)
        directory = create_backup_directory()
        value = cls._new(directory, cls.LIVE, binding["identity"], {
            "kind": cls.LIVE, "qualification_sha256": canonical_hash(proof),
            "source_binding_sha256": canonical_hash(binding), "export_claim_sha256": canonical_hash(claim)})
        value.qualification, value.binding, value.claim = qualification, binding, claim
        value.bind_file("source-binding.json", binding)
        return value

    def check(self):
        require(type(self) is BackupSourceEvidence and self.sources == tool_sources()
                and self.fingerprint == canonical_hash([self.kind, str(self.directory), self.identity,
                                                       self.authority, self.sources]), "entry_source_changed")
        require(self.kind in (self.OWNED, self.LIVE), "entry_source_kind")
        custody(self.directory)
        self.read_file("entry-claim.json")

    def bind_file(self, name, value):
        require(Path(name).name == name and name not in self.bindings, "entry_binding_duplicate")
        require(len(json.dumps(value, indent=2).encode()) < 4*1024**2, "entry_metadata_too_large")
        path = self.directory / name
        private_json(path, value)
        info = path.lstat()
        self.bindings[name] = (info.st_dev, info.st_ino, canonical_hash(value))

    def read_file(self, name):
        require(name in self.bindings, "entry_evidence_missing")
        path = self.directory / name
        value = read_private_json(path)
        info = path.lstat()
        require(self.bindings[name] == (info.st_dev, info.st_ino, canonical_hash(value)), "entry_evidence_changed")
        return value

    def command(self, tool, *args):
        self.check()
        require(tool in ("psql", "pg_dump"), "entry_tool_not_readonly")
        if self.kind == self.OWNED:
            require(self.lab.cid == self.identity["container"] and self.lab.run_id == self.identity["run"],
                    "entry_source_identity_changed")
            self.lab.guard()
            return self.lab.command(tool, self.database, *args)
        return LiveSource.command(tool, *args)

    def attach(self, archive, state, catalog):
        self.check()
        require(self.consumed and self.archive is None and archive.directory == self.directory,
                "entry_archive_scope")
        self.archive = archive
        archive.entry = self
        self.bind_file(self.FILE, {"version": 1, "kind": self.kind, "identity": self.identity,
            "authority": self.authority, "sources": self.sources, "image": PG_IMAGE,
            "archive": archive.expected, "snapshot_sha256": canonical_hash(state),
            "schema_evidence_sha256": canonical_hash(catalog)})

    @classmethod
    def read(cls, archive, state):
        value = archive.entry
        require(type(value) is cls and value.archive is archive, "entry_archive_required")
        value.check()
        source = value.read_file(cls.FILE)
        require(source == {"version": 1, "kind": value.kind, "identity": value.identity,
            "authority": value.authority, "sources": value.sources, "image": PG_IMAGE,
            "archive": archive.expected, "snapshot_sha256": canonical_hash(state),
            "schema_evidence_sha256": canonical_hash(SchemaEvidence.read(archive, state))}, "entry_source_binding")
        archive.verify()
        return source

    def postflight(self):
        self.check()
        require(self.restored and self.archive is not None, "entry_restore_required")
        if self.kind == self.OWNED:
            require(self.lab.cid is None and self.lab.inventory() == self.lab.baseline,
                    "entry_source_cleanup_required")
            facts = {"scope": self.OWNED, "baseline_sha256": canonical_hash(self.lab.baseline)}
        else:
            require(require_qualification(self.qualification)["entry_contract"] == "r7"
                    and canonical_hash(read_private_json(self.qualification / "qualified.json")) ==
                    self.authority["qualification_sha256"]
                    and read_private_json(self.qualification / "source-binding.json") == self.binding
                    and read_private_json(self.qualification / "export-claimed.json") == self.claim,
                    "entry_authority_changed")
            require(LiveSource.identity() == self.binding["identity"] and
                    LiveSource.protections() == self.binding["protections"], "postflight_resource_drift")
            with Snapshot(LiveSource.command("psql", *PSQL)) as snap:
                LiveSource.member_baseline(snap)
                require(entry_compatibility(snap) == self.binding["compatibility"], "entry_source_compatibility_drift")
            facts = {"scope": self.LIVE, "source_binding_sha256": canonical_hash(self.binding)}
        self.bind_file("entry-postflight.json", {"status": "PASS", "facts": facts,
            "source_sha256": canonical_hash(self.read_file(self.FILE)), "sources": self.sources})


class BoundRestoreIdentityProfile(MixedRestoreIdentityProfile):
    FILE = "restore-identity-v3.json"
    COLLECTOR = "pg18-trusted-restore-identity-v3"
    VERSION = 3

    @classmethod
    def read(cls, archive, state):
        source = BackupSourceEvidence.read(archive, state)
        value = archive.entry.read_file(cls.FILE)
        original = SchemaEvidence.read(archive, state)
        require(value.get("version") == 3 and type(value["version"]) is int
                and value.get("source_sha256") == canonical_hash(source)
                and value.get("source_kind") == source["kind"], "entry_profile_binding")
        return value, cls.select(value["profile"], original["evidence"])


class BoundMemberComments(ExtensionMemberComments):
    FILE = "extension-member-comments-v2.json"
    COLLECTOR = "pg18-extension-member-comments-v2"
    PROFILE = BoundRestoreIdentityProfile

    @classmethod
    def bind(cls, archive, state, rows, source):
        provenance = BackupSourceEvidence.read(archive, state)
        catalog = SchemaEvidence.read(archive, state)
        profile, _ = cls.PROFILE.read(archive, state)
        cls.validate(rows, catalog["evidence"])
        archive.entry.bind_file(cls.FILE, {"version": 2, "collector": cls.COLLECTOR,
            "source_kind": provenance["kind"], "source_sha256": canonical_hash(provenance),
            "profile_sha256": canonical_hash(profile), "members": rows, "members_sha256": canonical_hash(rows)})

    @classmethod
    def read(cls, archive, state):
        source = BackupSourceEvidence.read(archive, state)
        profile, _ = cls.PROFILE.read(archive, state)
        value = archive.entry.read_file(cls.FILE)
        require(type(value.get("version")) is int and value["version"] == 2
                and value.get("collector") == cls.COLLECTOR and value.get("source_kind") == source["kind"]
                and value.get("source_sha256") == canonical_hash(source)
                and value.get("profile_sha256") == canonical_hash(profile)
                and value.get("members_sha256") == canonical_hash(value.get("members")), "entry_comments_binding")
        cls.validate(value["members"], SchemaEvidence.read(archive, state)["evidence"])
        return value


class HumanGPG:
    """Symmetric AES256, private agent, human-only Pinentry, no cached password."""

    def __init__(self, directory):
        require(sys.stdin.isatty() and sys.stdout.isatty(), "human_terminal_required")
        self.parent = secure_directory(directory)
        self.home = self.parent / "gpg"
        self.home.mkdir(mode=0o700)
        pinentry = shutil.which("pinentry")
        require(pinentry is not None and "\n" not in pinentry, "pinentry_missing")
        # Configuration only: this file never contains a password.
        config = self.home / "gpg-agent.conf"
        with config.open("x") as stream:
            config.chmod(0o600)
            stream.write("pinentry-program " + pinentry + "\nno-allow-external-cache\ndefault-cache-ttl 0\nmax-cache-ttl 0\n")
        self.args = ["gpg", "--no-options", "--homedir", str(self.home), "--no-symkey-cache",
                     "--pinentry-mode=ask", "--ttyname", os.ttyname(sys.stdin.fileno())]

    def encrypt(self, output):
        secure_directory(output.parent)
        require(not output.exists() and not output.is_symlink(), "ciphertext_exists")
        return [*self.args, "--cipher-algo=AES256", "--compress-algo=none", "--output", str(output), "--symmetric"]

    def decrypt(self, source):
        info = source.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600, "ciphertext_not_private")
        return [*self.args, "--decrypt", str(source)]

    def close(self):
        self.close_home(self.home)

    @staticmethod
    def close_home(home):
        secure_directory(home)
        run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"])
        # Remove only exact run-owned agent files (no keyrings or external symlinks).
        for item in home.iterdir():
            require(not item.is_symlink(), "gpg_cleanup_symlink")
            if item.is_dir():
                require(item.name == "private-keys-v1.d" and not any(item.iterdir()), "unexpected_gpg_keys")
                item.rmdir()
            else:
                item.unlink()
        home.rmdir()


def recover_test_resources(directory):
    """Exact receipt cleanup after a stopped qualification child, never live DB."""
    secure_directory(directory)
    receipt = directory / "container-receipt.json"
    if not receipt.exists() and (directory / "container-intent.json").exists():
        intent = read_private_json(directory / "container-intent.json")
        require(intent["label"] == LABEL and intent["image"] == PG_IMAGE
                and re.fullmatch(r"v49b-[a-f0-9]{16}", intent["run"]), "intent_invalid")
        ids = run(MemoryPostgres.docker("ps", "-aq", "--no-trunc", "--filter", "label="+LABEL+"="+intent["run"])).decode().split()
        require(len(ids) <= 1, "intent_multiple_containers")
        if ids:
            lab = MemoryPostgres(directory, bootstrap=intent.get("bootstrap", "backup_verify"))
            lab.baseline, lab.run_id, lab.cid = intent["baseline"], intent["run"], ids[0]
            require(lab.inspect()["Image"] == PG_IMAGE, "intent_image_changed")
            lab.cleanup()
    if receipt.exists():
        require(not receipt.is_symlink(), "receipt_symlink")
        state = json.loads(receipt.read_text())
        require(state["label"] == LABEL and state["image"] == PG_IMAGE
                and re.fullmatch(r"v49b-[a-f0-9]{16}", state["run"])
                and re.fullmatch(r"[a-f0-9]{64}", state["id"]), "receipt_invalid")
        lab = MemoryPostgres(directory, bootstrap=state.get("bootstrap", "backup_verify"))
        lab.baseline = state["baseline"]
        lab.run_id = state["run"]
        if state["id"] in run(lab.docker("ps", "-aq", "--no-trunc")).decode().split():
            lab.cid = state["id"]
            lab.cleanup()
    home = directory / "gpg"
    if home.exists():
        HumanGPG.close_home(home)


def recover_qualification(directory):
    """Only explicitly registered run-owned receipts; never traverse arbitrary trees."""
    custody(directory)
    require(directory.parent == Path("/private/tmp") and directory.name.startswith("v049-backup-"), "registry_path_invalid")
    # Validate the COMPLETE registry before deleting anything. An invalid later
    # entry must not partially clean up an otherwise still-running test suite.
    owned = [directory]
    for entry in directory.glob("owned-receipt-v49b-*.json"):
        receipt = read_private_json(entry)
        require(re.fullmatch(r"v49b-[a-f0-9]{16}", receipt["run"])
                and entry.name == "owned-receipt-"+receipt["run"]+".json", "registry_invalid")
        relative = Path(receipt["relative_directory"])
        require(not relative.is_absolute() and ".." not in relative.parts, "registry_outside_run")
        child = custody(directory / relative)
        intent = read_private_json(child / "container-intent.json")
        require(intent["run"] == receipt["run"], "registry_run_mismatch")
        if child not in owned:
            owned.append(child)
    for child in owned:
        recover_test_resources(child)


def tool_sources():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__).resolve(), TEST_FILE)}


def export_synthetic_database(lab, db, directory, *, mixed_identity=False, member_comments=False):
    """Explicit R4/R5 entry: freshly owned labs, never a LiveSource callable."""
    require(type(lab) is MemoryPostgres, "synthetic_source_required")
    require(type(mixed_identity) is bool, "synthetic_mode_invalid")
    require(type(member_comments) is bool and (not member_comments or mixed_identity), "member_comments_mode")
    if member_comments:
        ExtensionMemberComments.scope(directory)
    root = custody(Path(os.environ.get("V49_BACKUP_ARTIFACTS", "/")))
    prefixes = ("v049-backup-plain-r5-", "v049-backup-plain-r6-") if mixed_identity else (
        "v049-backup-plain-r4-", "v049-backup-plain-r5-", "v049-backup-plain-r6-")
    require(root.parent == Path("/private/tmp") and root.name.startswith(prefixes)
            and lab.directory.is_relative_to(root) and directory.is_relative_to(root), "synthetic_scope_required")
    lab.guard()
    return export_database(lambda tool, *args: lab.command(tool, db, *args), directory,
        _synthetic_source={"container": lab.cid, "database": db, **({"run": lab.run_id} if member_comments else {})},
        _mixed_identity=mixed_identity, _member_comments=member_comments)


def export_database(command, directory, *, _synthetic_source=None, _mixed_identity=False, _member_comments=False,
                    _entry=None):
    """Exactly one full archive, bound to one read-only source snapshot."""
    require(type(_mixed_identity) is bool and (not _mixed_identity or _synthetic_source), "synthetic_source_required")
    require(type(_member_comments) is bool and (not _member_comments or _mixed_identity
        and _synthetic_source and re.fullmatch(r"v49b-[a-f0-9]{16}", _synthetic_source.get("run", ""))),
        "member_comments_mode")
    if _member_comments:
        ExtensionMemberComments.scope(directory)
    if _entry is not None:
        require(type(_entry) is BackupSourceEvidence and command == _entry.command
                and directory == _entry.directory and not _synthetic_source and not _mixed_identity
                and not _member_comments, "entry_export_arguments")
        _entry.check()
        require(not _entry.consumed, "entry_export_consumed")
        _entry.consumed = True
    profile_type = BoundRestoreIdentityProfile if _entry else (
        MixedRestoreIdentityProfile if _mixed_identity else RestoreIdentityProfile)
    comment_type = BoundMemberComments if _entry else ExtensionMemberComments
    sources = tool_sources()
    archive = PlainArchive(directory)
    try:
        with Snapshot(command("psql", *PSQL)) as snap:
            deadline = snap.deadline
            state = DatabaseState.collect(snap, command)
            evidence = SchemaEvidence.collect(snap)
            require(evidence["complete"], "schema_evidence_incomplete")
            profile = profile_type.collect(snap, evidence) if _synthetic_source or _entry else None
            comments = comment_type.collect(snap, evidence) if _member_comments or _entry else None
            archive.export(command("pg_dump", "--format=custom", "--lock-wait-timeout=2s",
                "--snapshot="+snap.snapshot), snap.deadline)
        with Snapshot(command("psql", *PSQL)) as post:
            post.deadline = min(post.deadline, deadline)
            DatabaseState.assert_stable(state, post, command)
            require(SchemaEvidence.collect(post) == evidence, "source_schema_evidence_drift")
            if profile:
                require(profile_type.collect(post, evidence) == profile, "source_restore_profile_drift")
            if comments is not None:
                require(comment_type.collect(post, evidence) == comments, "source_member_comments_drift")
        require(tool_sources() == sources, "source_changed_during_backup")
        private_json(directory / "snapshot.json", state)
        sidecar = SchemaEvidence.bind(evidence, state, archive, sources)
        path = directory / SchemaEvidence.FILE
        private_json(path, sidecar)
        info = path.lstat()
        archive.schema_evidence_binding = (info.st_dev, info.st_ino, canonical_hash(sidecar))
        if _entry:
            _entry.attach(archive, state, sidecar)
            _entry.bind_file(profile_type.FILE, {"version": 3, "source_kind": _entry.kind,
                "source_sha256": canonical_hash(_entry.read_file(_entry.FILE)), "profile": profile})
        elif profile:
            bound_profile = {"source_kind": profile_type.SOURCE_KIND, "source": _synthetic_source,
                "sources": sources, "image": PG_IMAGE, "archive": archive.expected,
                "snapshot_sha256": canonical_hash(state), "schema_evidence_sha256": canonical_hash(sidecar),
                "profile": profile}
            profile_path = directory / profile_type.FILE
            private_json(profile_path, bound_profile)
            info = profile_path.lstat()
            archive.restore_identity_binding = (info.st_dev, info.st_ino, canonical_hash(bound_profile))
        if comments is not None:
            comment_type.bind(archive, state, comments, _synthetic_source)
        return archive, state
    except BaseException:
        archive.close()
        raise


def verify_restore(archive, state, lab, *, synthetic_identity=False, mixed_identity=False, member_comments=False,
                   _entry=None):
    require(type(mixed_identity) is bool and not (mixed_identity and synthetic_identity), "synthetic_mode_invalid")
    require(type(member_comments) is bool and (not member_comments or mixed_identity), "member_comments_mode")
    if _entry is not None:
        require(type(_entry) is BackupSourceEvidence and archive.entry is _entry
                and not synthetic_identity and not mixed_identity and not member_comments, "entry_restore_arguments")
        BackupSourceEvidence.read(archive, state)
    else:
        require(archive.entry is None, "entry_explicit_restore_required")
    profile_type = BoundRestoreIdentityProfile if _entry else (
        MixedRestoreIdentityProfile if mixed_identity else RestoreIdentityProfile)
    comment_type = BoundMemberComments if _entry else ExtensionMemberComments
    use_profile = synthetic_identity or mixed_identity or _entry is not None
    use_comments = member_comments or _entry is not None
    deadline = time.monotonic() + 600
    original = SchemaEvidence.read(archive, state)
    comments = comment_type.read(archive, state) if use_comments else None
    identity_profile = None
    if use_profile:
        identity_profile, bootstrap = profile_type.read(archive, state)
        require(lab.bootstrap == bootstrap, "restore_profile_target_identity")
    lab.guard()
    target = "v49b_restored_"+secrets.token_hex(8)
    lab.create_db(target)
    DatabaseState.provision_restore(lab, target, state)
    report_path = archive.directory / ("schema-comparison-"+secrets.token_hex(8)+".json")
    try:
        if use_profile:
            profile_type.prepare(archive, state, lab, target, deadline)
        archive.restore(lab.empty_restore(target), deadline)
        if use_comments:
            lab.comment_targets[target] = (archive.identity, archive.expected["sha256"])
            comment_type.replay(archive, state, lab, target, deadline)
        command = lambda tool, *args: lab.command(tool, target, *args)
        with Snapshot(command("psql", *PSQL), deadline=deadline) as restored:
            actual = DatabaseState.collect(restored, command)
            evidence = SchemaEvidence.collect(restored)
        difference = SchemaEvidence.diff(original["evidence"], evidence)
        comparison = {"catalog": difference, "categories": {key: actual[key] == state[key] for key in state},
            "representation_difference_candidate": actual["schema"] != state["schema"] and difference["status"] == "EQUAL"}
        private_json(report_path, comparison)
    except BaseException:
        if not report_path.exists():
            private_json(report_path, {"catalog": {"status": "ERROR"}, "full_comparison": False})
        raise
    require(actual == state, "restored_state_differs")
    require(difference["status"] == "EQUAL", "restored_schema_evidence_differs")
    require(SchemaEvidence.read(archive, state) == original, "schema_evidence_changed_during_restore")
    if use_profile:
        require(profile_type.read(archive, state)[0] == identity_profile,
                "restore_profile_changed_during_restore")
    if use_comments:
        require(comment_type.read(archive, state) == comments, "member_comments_changed")
    require(time.monotonic() < deadline, "restore_timeout")
    archive.verify()
    return {"snapshot_sha256": canonical_hash(state), "tables": len(state["tables"]),
            "rows": sum(table[3] for table in state["tables"]),
            "large_objects": state["large_objects"]["count"], "full_comparison": True,
            "schema_evidence_sha256": canonical_hash(original), "schema_comparison_sha256": canonical_hash(comparison),
            **({"restore_profile_sha256": canonical_hash(identity_profile)} if use_profile else {}),
            **({"member_comments_sha256": canonical_hash(comments)} if use_comments else {}),
            **({"source_sha256": canonical_hash(BackupSourceEvidence.read(archive, state))} if _entry else {})}


def restore_isolated(archive, state, directory, *, synthetic_identity=False, mixed_identity=False, member_comments=False,
                     _entry=None):
    """Legacy/current path is unchanged; new R4 mode needs a bound synthetic profile."""
    require(type(mixed_identity) is bool and not (mixed_identity and synthetic_identity), "synthetic_mode_invalid")
    require(type(member_comments) is bool and (not member_comments or mixed_identity), "member_comments_mode")
    if _entry is not None:
        require(type(_entry) is BackupSourceEvidence and archive.entry is _entry
                and not _entry.restored and not synthetic_identity and not mixed_identity and not member_comments,
                "entry_restore_arguments")
        BackupSourceEvidence.read(archive, state)
        if _entry.kind == _entry.OWNED:
            require(_entry.lab.cid is None and _entry.lab.inventory() == _entry.lab.baseline,
                    "entry_source_cleanup_required")
        _entry.restored = True  # Failure consumes the one restore attempt too.
        BoundMemberComments.read(archive, state)
    else:
        require(archive.entry is None, "entry_explicit_restore_required")
    if member_comments:
        ExtensionMemberComments.read(archive, state)
    profile_type = BoundRestoreIdentityProfile if _entry else (
        MixedRestoreIdentityProfile if mixed_identity else RestoreIdentityProfile)
    bootstrap = profile_type.read(archive, state)[1] if synthetic_identity or mixed_identity or _entry else "backup_verify"
    lab = MemoryPostgres(directory, bootstrap=bootstrap)
    try:
        lab.start()
        outcome = verify_restore(archive, state, lab, synthetic_identity=synthetic_identity,
                                 mixed_identity=mixed_identity, member_comments=member_comments, _entry=_entry)
    finally:
        if (directory / "container-receipt.json").exists():
            recover_test_resources(directory)
        else:
            lab.cleanup()
    proof = {"outcome": outcome, "archive": archive.expected,
        "cleanup_ok": True, "baseline_equal": True, "sources": tool_sources(), "image": PG_IMAGE}
    private_json(directory / "restore-proof.json", proof)
    if _entry:
        _entry.bind_file("entry-restore-proof.json", proof)
    return outcome


def finish_backup(archive, outcome, directory, identity, sources):
    require(archive.entry is None, "entry_explicit_finalization_required")
    require(tool_sources() == sources, "source_changed_during_backup")
    proof = read_private_json(directory / "restore-proof.json")
    require(proof["outcome"] == outcome and outcome["full_comparison"] is True
            and proof["archive"] == archive.expected and proof["cleanup_ok"] is True
            and proof["baseline_equal"] is True and proof["sources"] == sources
            and proof["image"] == PG_IMAGE, "restore_proof_mismatch")
    require(outcome.get("schema_evidence_sha256") == canonical_hash(SchemaEvidence.read(archive, read_private_json(
        archive.directory / "snapshot.json"))), "schema_evidence_proof_mismatch")
    final = archive.finalize(accepted=True)
    result = {"status": "PASS", "encrypted": False, "file": str(final), "archive": archive.expected,
        "source": identity, "tool_sources": sources, "restore_image": PG_IMAGE,
        "verification": outcome, "cleanup_ok": True, "protected_resources_unchanged": True,
        "migration_applied": False, "deployment": False, "provider_calls": 0}
    private_json(directory / "result.json", result)
    return result


def finish_bound_backup(entry, archive, state, outcome):
    require(type(entry) is BackupSourceEvidence and archive.entry is entry
            and entry.restored and not entry.finished, "entry_finalization_scope")
    source = BackupSourceEvidence.read(archive, state)
    profile, _ = BoundRestoreIdentityProfile.read(archive, state)
    comments = BoundMemberComments.read(archive, state)
    proof = entry.read_file("entry-restore-proof.json")
    post = entry.read_file("entry-postflight.json")
    require(read_private_json(archive.directory / "snapshot.json") == state, "entry_snapshot_changed")
    require(proof == {"outcome": outcome, "archive": archive.expected, "cleanup_ok": True,
        "baseline_equal": True, "sources": entry.sources, "image": PG_IMAGE}, "entry_restore_proof_mismatch")
    require(outcome.get("full_comparison") is True and outcome.get("snapshot_sha256") == canonical_hash(state)
            and outcome.get("source_sha256") == canonical_hash(source)
            and outcome.get("schema_evidence_sha256") == canonical_hash(SchemaEvidence.read(archive, state))
            and outcome.get("restore_profile_sha256") == canonical_hash(profile)
            and outcome.get("member_comments_sha256") == canonical_hash(comments), "entry_outcome_binding")
    matches = [read_private_json(p) for p in archive.directory.glob("schema-comparison-*.json")]
    require(any(canonical_hash(p) == outcome.get("schema_comparison_sha256") and p["catalog"]["status"] == "EQUAL"
        and p["categories"] == {key: True for key in state} and not p["representation_difference_candidate"]
        for p in matches), "entry_full_comparison_missing")
    require(post["status"] == "PASS" and post["sources"] == entry.sources
            and post["facts"]["scope"] == entry.kind and post["source_sha256"] == canonical_hash(source),
            "entry_postflight_binding")
    archive.verify()
    entry.finished = True
    live = entry.kind == entry.LIVE
    final = archive.finalize(accepted=True) if live else archive.path
    result = {"status": "PASS" if live else "ENTRY_REHEARSAL_PASS_NOT_QUALIFIED", "encrypted": False,
        "usable_backup": live, "current_data_export": live, "protected_resources_unchanged": True if live else None,
        "file": str(final), "archive": archive.expected, "verification": outcome,
        "source_kind": entry.kind, "source_sha256": canonical_hash(source),
        "claim_sha256": canonical_hash(entry.read_file("entry-claim.json")),
        "postflight_sha256": canonical_hash(post), "restore_proof_sha256": canonical_hash(proof),
        "tool_sources": entry.sources, "cleanup_ok": True, "migration_applied": False, "deployment": False}
    entry.bind_file("result.json" if live else "entry-rehearsal-result.json", result)
    return result


def read_private_json(path):
    """Bounded no-follow proof/metadata loading, never arbitrary exception text."""
    custody(path.parent)
    no_unsafe_acl(path)
    # Reject FIFOs/devices by fstat without first blocking in open().
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
                and before.st_size <= 4 * 1024**2, "metadata_file_not_private")
        blocks = bytearray()
        while chunk := os.read(fd, 65536):
            blocks.extend(chunk)
            require(len(blocks) <= 4 * 1024**2, "metadata_too_large")
        after = os.fstat(fd)
        same_path = path.lstat()
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) ==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
                and (same_path.st_dev,same_path.st_ino) == (after.st_dev,after.st_ino), "metadata_file_changed")
        try:
            value = json.loads(blocks)
        except (ValueError, TypeError):
            raise BackupError("metadata_json_invalid") from None
        require(isinstance(value, dict), "metadata_not_object")
        return value
    finally:
        os.close(fd)


RETAINED_DIRECTORY = BACKUP_ROOT / "run-20260913T050023Z-0fab208e7f354a1e"
RETAINED_INPUTS = {
    "database.partial.dump": {"bytes": 1213458, "sha256": "a1b2395fb8d0778319d18303fbc678f5a06b2551abe34fa8b5a8a453c33b139a"},
    "snapshot.json": {"bytes": 10484, "sha256": "54bfb213b84444e945e78709406d723f2618da51db8d72e3b4172bd0a5ac703b"},
    "source-binding.json": {"bytes": 8763, "sha256": "9c566cf7c62afe876dfbc2ac5b6d4c94739f3e248c474eefcc4660d08a612bc7"},
    "failed.json": {"bytes": 131, "sha256": "731702a15de37b7bc3e6082061a437c26e5e19a4793ab9fc89d6d6cbf469305a"},
}
DIAGNOSTIC_CATEGORIES = ("properties", "roles", "schema", "tables", "sequences", "large_objects")


class BoundInput:
    """An existing immutable input opened read-only; no write/export/finalize API."""

    def __init__(self, path, expected):
        self.directory = custody(path.parent)
        self.path, self.expected, self.fd = path, dict(expected), None
        require(0 < expected["bytes"] <= MAX_STREAM and re.fullmatch(r"[a-f0-9]{64}", expected["sha256"]),
                "invalid_input_binding")
        try:
            # O_NONBLOCK prevents an unexpected FIFO/device from blocking open.
            self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self.identity = self.fingerprint(os.fstat(self.fd))
            self.verify()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def fingerprint(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def check(self):
        custody(self.directory)
        no_unsafe_acl(self.path)
        info = self.path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, "input_not_private")
        require(self.fingerprint(info) == self.identity
                and self.fingerprint(os.fstat(self.fd)) == self.identity, "input_identity_changed")

    def verify(self):
        self.check()
        os.lseek(self.fd, 0, os.SEEK_SET)
        digest, size = hashlib.sha256(), 0
        while block := os.read(self.fd, 65536):
            size += len(block)
            require(size <= self.expected["bytes"], "input_size_changed")
            digest.update(block)
        self.check()
        require({"bytes": size, "sha256": digest.hexdigest()} == self.expected, "input_digest_changed")

    def json(self):
        require(self.expected["bytes"] <= 4 * 1024**2, "metadata_too_large")
        self.verify()
        os.lseek(self.fd, 0, os.SEEK_SET)
        value = json.loads(os.read(self.fd, self.expected["bytes"]))
        require(isinstance(value, dict), "metadata_not_object")
        self.verify()
        return value

    # Reuse only the bounded streaming restore and idempotent close; this object
    # is not constructed as, or inherited from, a writable PlainArchive.
    restore = PlainArchive.restore
    close = PlainArchive.close


class RetainedInputs:
    """All original inputs remain FD/hash/inode bound until after exact cleanup."""

    def __init__(self, directory, bindings):
        self.files = {}
        require(set(bindings) == set(RETAINED_INPUTS), "retained_input_names_invalid")
        self.directory = custody(directory)
        try:
            for name, binding in bindings.items():
                self.files[name] = BoundInput(directory / name, binding)
            self.archive = self.files["database.partial.dump"]
            os.lseek(self.archive.fd, 0, os.SEEK_SET)
            require(os.read(self.archive.fd, 5) == b"PGDMP", "invalid_archive_format")
            self.state = self.files["snapshot.json"].json()
            require(set(self.state) == set(DIAGNOSTIC_CATEGORIES), "snapshot_categories_invalid")
            failed = self.files["failed.json"].json()
            require(failed == {"status": "FAILED", "encrypted": False, "usable_backup": False,
                    "partial_retained": True, "migration_applied": False}, "failed_state_changed")
            self.files["source-binding.json"].json()
        except BaseException:
            self.close()
            raise

    def verify(self):
        for value in self.files.values():
            value.verify()

    def close(self):
        for value in self.files.values():
            value.close()

    def claim(self):
        self.verify()
        directory = self.directory / "r2-diagnostic"
        require(not os.path.lexists(directory), "diagnostic_already_claimed")
        directory.mkdir(mode=0o700)  # Exclusive even if another process won the race.
        custody(directory)
        private_json(directory / "claim.json", {"inputs": {key: value.expected for key, value in self.files.items()},
            "image": PG_IMAGE, "sources": tool_sources(), "created_at": time.time(), "once_only": True})
        return directory


def diagnostic_comparison(expected, actual):
    require(set(expected) == set(actual) == set(DIAGNOSTIC_CATEGORIES), "snapshot_categories_invalid")
    equal = {key: expected[key] == actual[key] for key in DIAGNOSTIC_CATEGORIES}
    return {"status": "MATCH" if all(equal.values()) else "DIFFERENT", "equal_categories": equal,
        "counts": {label: {"tables": len(state["tables"]), "rows": sum(table[3] for table in state["tables"]),
            "sequences": len(state["sequences"]), "large_objects": state["large_objects"]["count"]}
            for label, state in (("expected", expected), ("actual", actual))}}


def state_diagnostics(expected, actual, original, current):
    """Six bounded hash-only categories; diagnostic output never grants PASS."""
    require(set(expected) == set(actual) == set(DIAGNOSTIC_CATEGORIES), "snapshot_categories_invalid")
    def categories(state, catalog):
        role_fields = ("owner", "acl", "initial_acl")
        return {
            "schema": {"dump_sha256": state["schema"], "catalog": {
                key: {name: value for name, value in row["fields"].items() if name not in role_fields}
                for key, row in catalog["objects"].items()}},
            "rows": state["tables"], "sequences": state["sequences"],
            "properties": state["properties"],
            "owner_acl": {"roles": state["roles"], "objects": {
                key: {name: row["fields"][name] for name in role_fields}
                for key, row in catalog["objects"].items()}},
            "large_objects": state["large_objects"],
        }
    left, right = categories(expected, original), categories(actual, current)
    return {"version": 1, "full_comparison_pass": expected == actual and original == current,
        "categories": {key: {"equal": left[key] == right[key],
            "expected_sha256": canonical_hash(left[key]), "actual_sha256": canonical_hash(right[key])}
            for key in left}, "catalog": SchemaEvidence.diff(original, current)}


def schema_representation_summary(archive_sql, restored_sql):
    """Structural clues ONLY. Never substitute reconstructed SQL for original hash."""
    def shape(sql):
        text = sql.decode("utf-8")
        types = {}
        for kind in re.findall(r"^-- Name: .*?; Type: ([A-Z ]+); Schema: .*?; Owner: .*?$", text, re.M):
            # SQL/function/comment content is untrusted. Never echo arbitrary
            # text merely because it imitates a pg_dump header.
            kind = kind if kind in {"EXTENSION", "COMMENT", "SCHEMA", "TYPE", "FUNCTION", "PROCEDURE",
                "TABLE", "TABLE DATA", "TABLE ATTACH", "SEQUENCE", "SEQUENCE OWNED BY", "SEQUENCE SET",
                "VIEW", "MATERIALIZED VIEW", "MATERIALIZED VIEW DATA", "DEFAULT", "CONSTRAINT",
                "FK CONSTRAINT", "INDEX", "INDEX ATTACH", "TRIGGER", "RULE", "POLICY", "ROW SECURITY",
                "ACL", "DEFAULT ACL", "DATABASE", "DATABASE PROPERTIES", "STATISTICS"} else "OTHER"
            types[kind] = types.get(kind, 0) + 1
        extensions = sorted(set(re.findall(
            r'^CREATE EXTENSION IF NOT EXISTS "?(plpgsql|pgcrypto|vector|pg_trgm|uuid-ossp)"?\s', text, re.M)))
        return {"bytes": len(sql), "sha256": hashlib.sha256(sql).hexdigest(),
                "object_type_counts": types, "create_extension_names": extensions}
    return {"archive_reconstructed": shape(archive_sql), "restored_pg_dump": shape(restored_sql),
            "not_original_source_schema": True, "not_equivalence_proof": True}


def diagnostic_schema(inputs, lab, target, snapshot, deadline):
    lab.guard()
    inputs.archive.verify()
    os.lseek(inputs.archive.fd, 0, os.SEEK_SET)
    source, restored = bytearray(), bytearray()
    read_process(lab.docker("exec", "-i", lab.cid, "pg_restore", "--schema-only", "--file=-"),
        source.extend, input_fd=inputs.archive.fd, limit=32 * 1024**2, deadline=deadline)
    read_process(lab.command("pg_dump", target, "--schema-only", "--quote-all-identifiers", "--encoding=UTF8",
        "--lock-wait-timeout=2s", "--restrict-key="+RESTRICT_KEY, "--snapshot="+snapshot.snapshot),
        restored.extend, limit=32 * 1024**2, deadline=deadline)
    result = schema_representation_summary(source, restored)
    # Only approved catalog identifiers, never role credentials, SQL or data.
    result["restored_extensions"] = snapshot.value("SELECT jsonb_agg(jsonb_build_object("
        "'name',e.extname,'owner',pg_get_userbyid(e.extowner),'version',e.extversion) ORDER BY e.extname) "
        "FROM pg_extension e")
    inputs.archive.verify()
    return result


def diagnose_retained(inputs):
    """Once-only isolated diagnostic; original FAILED and archive stay untouched."""
    directory = inputs.claim()
    lab = MemoryPostgres(directory)
    sources = tool_sources()
    report = {"status": "ERROR", "equal_categories": {key: None for key in DIAGNOSTIC_CATEGORIES},
        "backup_qualified": False, "migration_applied": False, "deployment": False,
        "provider_calls": 0, "current_service_access": False, "sources": sources, "image": PG_IMAGE,
        "inputs_unchanged": False, "cleanup_ok": False, "schema_diagnostic": "NOT_RUN"}
    try:
        lab.start()
        target = "v49b_diagnostic_"+secrets.token_hex(8)
        lab.create_db(target)
        DatabaseState.provision_restore(lab, target, inputs.state)
        deadline = time.monotonic() + 600
        inputs.archive.restore(lab.empty_restore(target), deadline)
        command = lambda tool, *args: lab.command(tool, target, *args)
        with Snapshot(command("psql", *PSQL), deadline=deadline) as snapshot:
            actual = DatabaseState.collect(snapshot, command)
            report.update(diagnostic_comparison(inputs.state, actual))
            # Persist category evidence BEFORE optional inspection or cleanup.
            private_json(directory / "comparison.json", report)
            report["schema_diagnostic"] = diagnostic_schema(inputs, lab, target, snapshot, deadline)
        require(time.monotonic() < deadline, "restore_timeout")
    except (BackupError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        report["status"] = "ERROR"
        report["error_type"] = type(exc).__name__  # No child exception text/SQL/credentials.
        report["error_code"] = str(exc) if isinstance(exc, BackupError) and re.fullmatch(
            r"[a-z][a-z0-9_]{0,79}", str(exc)) else "details_withheld"
        private_json(directory / "operation-error.json", report)
    finally:
        try:
            if (directory / "container-intent.json").exists():
                recover_test_resources(directory)
                require(lab.inventory() == lab.baseline, "docker_baseline_changed")
            else:
                lab.cleanup()
            report["cleanup_ok"] = True
        finally:
            try:
                inputs.verify()
                require(tool_sources() == sources, "source_changed_during_diagnostic")
                report["inputs_unchanged"] = True
            finally:
                if not report["cleanup_ok"] or not report["inputs_unchanged"]:
                    report["status"] = "ERROR"
                private_json(directory / "diagnostic.json", report)
    return report


def retained_entry():
    # Production CLI deliberately has NO input/output/context/SQL override.
    require(not os.environ.get("V49_BACKUP_ARTIFACTS"), "diagnostic_test_registry_not_allowed")
    inputs = RetainedInputs(RETAINED_DIRECTORY, RETAINED_INPUTS)
    try:
        report = diagnose_retained(inputs)
    finally:
        inputs.close()
    print("Retained archive diagnostic:", report["status"], "backup_qualified=false")
    require(report["status"] == "MATCH", "retained_diagnostic_not_match")


def synthetic_reports(directory, code, sources):
    custody(directory)
    require(code == 0 and sources == tool_sources(), "qualification_failed_or_source_changed")
    tests = ET.parse(directory / "tests.xml").getroot().findall(".//testcase")
    require(len(tests) >= 212 and all(not list(test) for test in tests), "qualification_tests_not_passed")
    names = sorted(t.attrib["classname"]+"::"+t.attrib["name"] for t in tests)
    legacy = [name for name in names if "::test_r7_" not in name]
    entry = {t.attrib["name"].split("[")[0] for t in tests if t.attrib["name"].startswith("test_r7_")}
    require(len(set(names)) == len(names) and len(legacy) == 212 and canonical_hash(legacy) == LEGACY_CASES_SHA256
            and ENTRY_CASES <= entry, "qualification_case_inventory")
    coverage = json.loads((directory / "coverage.json").read_text())
    require(coverage["meta"]["branch_coverage"], "qualification_branches_not_measured")
    cleanup = read_private_json(directory / "cleanup.json")
    require(cleanup["cleanup_ok"] and cleanup["baseline_equal"] and cleanup["image"] == PG_IMAGE
            and cleanup["source_sha256"] == sources[str(Path(__file__).resolve().relative_to(ROOT))],
            "qualification_cleanup_missing")
    return {"tests": len(tests), "totals": coverage["totals"]}


def coverage_gate(totals):
    require(totals["percent_covered"] >= 80
            and totals["covered_lines"] / totals["num_statements"] >= 0.8
            and totals["covered_branches"] / totals["num_branches"] >= 0.8,
            "qualification_coverage_below_80")


def report_hashes(directory, names):
    result = {}
    for name in names:
        path = directory / name
        require(not path.is_symlink() and path.is_file(), "qualification_report_missing")
        require(stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1,
                "qualification_report_not_private")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def synthetic_proof(directory, code, sources):
    result = synthetic_reports(directory, code, sources)
    coverage_gate(result["totals"])
    value = {"version": 2, "entry_contract": "r7", "status": "SYNTHETIC_PASS_NOT_QUALIFIED",
        "sources": sources, "image": PG_IMAGE,
        "directory": str(directory), "pytest_exit": code, "tests": result["tests"],
        "created_epoch": time.time(), "reports": report_hashes(directory, PROOF_REPORTS)}
    private_json(directory / "synthetic-proof.json", value)
    return value


def require_synthetic(directory):
    custody(directory)
    require(directory.parent == Path("/private/tmp") and directory.name.startswith("v049-backup-plain-"),
            "qualification_path_invalid")
    require((directory / "synthetic-proof.json").is_file(), "synthetic_proof_missing")
    value = read_private_json(directory / "synthetic-proof.json")
    require(value.get("status") == "SYNTHETIC_PASS_NOT_QUALIFIED"
            and value.get("version") == 2 and value.get("entry_contract") == "r7"
            and value.get("directory") == str(directory) and value.get("sources") == tool_sources()
            and value.get("image") == PG_IMAGE and value.get("pytest_exit") == 0
            and 0 <= time.time()-value.get("created_epoch", 0) <= 86400, "synthetic_proof_invalid_or_stale")
    require(report_hashes(directory, PROOF_REPORTS) == value["reports"], "synthetic_report_changed")
    require(synthetic_reports(directory, value["pytest_exit"], value["sources"])["tests"] == value["tests"],
            "synthetic_test_count_changed")
    coverage_gate(synthetic_reports(directory, value["pytest_exit"], value["sources"])["totals"])
    return value


def qualification_reports(directory, code, sources):
    # Final proof may use readonly coverage, but never replace the synthetic report.
    result = synthetic_reports(directory, code, sources)
    names = list(PROOF_REPORTS)
    totals = result["totals"]
    if (directory / "readonly-result.json").exists():
        require_synthetic(directory)
        readonly = read_private_json(directory / "readonly-result.json")
        claim = read_private_json(directory / "readonly-claimed.json")
        require(readonly["status"] == "PASS" and readonly["exit_code"] == 0
                and readonly["sources"] == sources and readonly["claim_sha256"] == canonical_hash(claim)
                and claim["proof_sha256"] == canonical_hash(read_private_json(directory / "synthetic-proof.json"))
                and readonly["finished_epoch"] - readonly["started_epoch"] <= 300,
                "readonly_qualification_failed")
        require(report_hashes(directory, (".coverage.readonly",)) == readonly["reports"],
                "readonly_coverage_changed")
        totals = read_private_json(directory / "coverage-combined.json")["totals"]
        names += ["synthetic-proof.json", "readonly-result.json", "readonly-claimed.json",
                  ".coverage.readonly", "coverage-combined.json"]
    coverage_gate(totals)
    require((directory / "readonly-result.json").exists(), "readonly_qualification_required")
    require(readonly.get("checks", {}).get("entry_contract") == "r7"
            and readonly["checks"].get("compatibility"), "entry_readonly_evidence_required")
    value = {"status": "PASS", "entry_contract": "r7", "sources": sources, "image": PG_IMAGE, "tests": result["tests"],
        "coverage": totals["percent_covered"], "totals": totals, "human_gpg": "NOT RUN (separate encrypted mode)",
        "created_epoch": time.time(), "reports": report_hashes(directory, names)}
    private_json(directory / "qualified.json", value)
    return value


def require_qualification(directory):
    custody(directory)
    require(directory.parent == Path("/private/tmp")
            and directory.name.startswith("v049-backup-plain-"), "qualification_path_invalid")
    path = directory / "qualified.json"
    require(path.is_file() and not path.is_symlink(), "qualification_missing")
    value = read_private_json(path)
    require(value["status"] == "PASS" and value["sources"] == tool_sources() and value["image"] == PG_IMAGE
            and value["coverage"] >= 80 and 0 <= time.time()-value["created_epoch"] <= 86400,
            "qualification_invalid_or_stale")
    coverage_gate(value["totals"])
    require(all(Path(name).name == name for name in value["reports"]), "qualification_report_path_invalid")
    require(report_hashes(directory, value["reports"]) == value["reports"], "qualification_report_changed")
    require(value.get("entry_contract") == "r7" and {"readonly-result.json", "readonly-claimed.json",
            "synthetic-proof.json", ".coverage.readonly", "coverage-combined.json"} <= value["reports"].keys(),
            "entry_qualification_required")
    synthetic = require_synthetic(directory)
    readonly = read_private_json(directory / "readonly-result.json")
    claim = read_private_json(directory / "readonly-claimed.json")
    require(readonly["status"] == "PASS" and readonly["exit_code"] == 0 and readonly["sources"] == tool_sources()
            and readonly["checks"]["entry_contract"] == "r7" and readonly["checks"]["compatibility"]
            and readonly["claim_sha256"] == canonical_hash(claim) and claim["proof_sha256"] == canonical_hash(synthetic)
            and 0 <= readonly["finished_epoch"]-readonly["started_epoch"] <= 300, "entry_readonly_evidence_required")
    return value


def self_test_plain():
    import coverage
    os.umask(0o077)
    require(CLI_DIRECTORY is not None and CLI_COVERAGE is not None, "qualification_entry_required")
    directory = CLI_DIRECTORY
    sources = tool_sources()
    # Measure the real parent CLI orchestration and real pytest child together.
    # The ONE final gate remains >=80%; no subset threshold is lowered/ignored.
    parent_coverage = CLI_COVERAGE
    print("僅測試自建資料；不連線現行 Kubernetes，不匯出 MAAS。報告：", directory, flush=True)
    env = clean_env()
    env.update(V49_BACKUP_ARTIFACTS=str(directory), COVERAGE_FILE=str(directory / ".coverage.tests"))
    child = subprocess.Popen([sys.executable, "-B", "-m", "coverage", "run", "--branch",
        "--source=chg291_v049_live_backup", "-m", "pytest", "-c", "/dev/null", "-q", "-s",
        "-p", "no:cacheprovider", str(TEST_FILE), "-k", "not human_gpg", "--junitxml="+str(directory / "tests.xml")],
        cwd=ROOT, env=env, start_new_session=True)
    try:
        code = child.wait(timeout=600)
    finally:
        stop_process(child)
        recover_qualification(directory)
        parent_coverage.stop()
        parent_coverage.save()
    combined = coverage.Coverage(data_file=str(directory / ".coverage"))
    combined.combine(data_paths=[str(directory / ".coverage.cli"), str(directory / ".coverage.tests")], keep=True)
    combined.save()
    child_only = coverage.Coverage(data_file=str(directory / ".coverage.tests"))
    child_only.load()
    child_only.json_report(outfile=str(directory / "coverage-pytest.json"))
    combined.json_report(outfile=str(directory / "coverage.json"))
    combined.xml_report(outfile=str(directory / "coverage.xml"))
    combined.report(show_missing=True)
    result = synthetic_proof(directory, code, sources)
    print(json.dumps({"qualification": result["status"], "directory": str(directory),
        "tests": result["tests"], "coverage": synthetic_reports(directory, code, sources)["totals"]["percent_covered"],
        "current_data_export": False}))


def process_json(args, deadline):
    data = bytearray()
    read_process(args, data.extend, deadline=deadline, limit=4*1024**2)
    return json.loads(data)


def memory_tls_context(ca, certificate, key):
    """Use configured mTLS in memory; never create a credential file or argv.

    OpenSSL's Python API reads PEM from file descriptors. Anonymous pipes provide
    those descriptors without a filesystem object or a proxy/listener. Separate
    pipes are required because OpenSSL reads the cert and key independently.
    """
    context = ssl.create_default_context(cadata=ca.decode("ascii"))
    require(len(certificate) <= 65536 and len(key) <= 65536, "configured_certificate_too_large")
    pipes = []
    threads = []
    try:
        for payload in (certificate, key):
            read_fd, write_fd = os.pipe()
            pipes.append(read_fd)
            def write_pem(fd=write_fd, data=payload):
                try:
                    with os.fdopen(fd, "wb") as target:
                        target.write(data)
                except BrokenPipeError:
                    pass  # The TLS reader rejected the input; its error is authoritative.
            thread = threading.Thread(target=write_pem, daemon=True)
            thread.start()
            threads.append(thread)
        context.load_cert_chain(f"/dev/fd/{pipes[0]}", f"/dev/fd/{pipes[1]}")
        return context
    finally:
        for fd in pipes:
            os.close(fd)
        for thread in threads:
            thread.join(timeout=2)


def secret_metadata_digest(value):
    require(value.get("kind") == "PartialObjectMetadataList" and value.get("apiVersion") == "meta.k8s.io/v1"
            and set(value) <= {"apiVersion", "kind", "metadata", "items"}
            and not value.get("metadata", {}).get("continue"), "metadata_only_response_required")
    rows = []
    for item in value["items"]:
        require(set(item) <= {"apiVersion", "kind", "metadata"}
                and item.get("kind") in (None, "PartialObjectMetadata"), "secret_body_not_allowed")
        metadata = item["metadata"]
        require(metadata["namespace"] == "nomosmart", "metadata_namespace_changed")
        rows.append([metadata["name"], metadata["uid"], metadata["resourceVersion"]])
    require(rows, "secret_metadata_empty")
    return canonical_hash(sorted(rows))


def configured_secret_metadata(deadline):
    # Normal use of only the selected existing kubectl context. Raw credentials
    # remain in this process, are not returned/logged/persisted, and are never
    # passed as argv. Unsupported auth is a stop, not an invitation to extract it.
    config = process_json(["kubectl", "config", "view", "--context", "docker-desktop",
        "--minify", "--raw", "-o", "json"], deadline)
    require(len(config["contexts"]) == len(config["clusters"]) == len(config["users"]) == 1
            and config["contexts"][0]["name"] == "docker-desktop", "configured_context_changed")
    cluster, auth = config["clusters"][0]["cluster"], config["users"][0]["user"]
    require(set(cluster) == {"server", "certificate-authority-data"}
            and set(auth) == {"client-certificate-data", "client-key-data"}, "configured_auth_not_supported")
    url = urlsplit(cluster["server"])
    require(url.scheme == "https" and url.hostname and not url.username and not url.password
            and url.path in ("", "/") and not url.query and not url.fragment, "configured_api_url_invalid")
    context = memory_tls_context(base64.b64decode(cluster["certificate-authority-data"], validate=True),
        base64.b64decode(auth["client-certificate-data"], validate=True),
        base64.b64decode(auth["client-key-data"], validate=True))
    timeout = min(20, deadline-time.monotonic())
    require(timeout > 0, "readonly_deadline_exceeded")
    connection = http.client.HTTPSConnection(url.hostname, url.port or 443, context=context, timeout=timeout)
    try:
        # No application/json fallback, redirect, proxy or retry. A server which
        # cannot negotiate metadata-only must return 406 and stop qualification.
        connection.request("GET", "/api/v1/namespaces/nomosmart/secrets?limit=500", headers={
            "Accept": "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"})
        response = connection.getresponse()
        require(response.status == 200, f"metadata_only_http_{response.status}")
        data = response.read(4*1024**2+1)
        require(len(data) <= 4*1024**2, "metadata_too_large")
        return secret_metadata_digest(json.loads(data))
    finally:
        connection.close()


class LiveSource:
    """The single approved source. No configurable URL, namespace or remote host."""

    POD = "nomosmart-local-postgresql-0"
    PREFIX = ["kubectl", "--context", "docker-desktop", "-n", "nomosmart"]

    @classmethod
    def command(cls, tool, *args):
        require(tool in ("psql", "pg_dump"), "live_tool_not_readonly")
        # Use only existing in-Pod local authentication. No password is emitted,
        # copied into argv on the host, or passed to the restore container.
        script = ('test "$NOMOSMART_DB" = nomosmart && test -n "$POSTGRES_USER" || exit 70; '
            'unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGSERVICE PGSERVICEFILE; '
            'export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=10000 '
            '-c lock_timeout=2000 -c idle_in_transaction_session_timeout=300000 -c timezone=UTC"; '
            'exec "$@" --host=/var/run/postgresql --port=5432 --username="$POSTGRES_USER" '
            '--dbname=nomosmart --no-password')
        return [*cls.PREFIX, "exec", "-i", cls.POD, "-c", "postgresql", "--", "/bin/sh", "-c",
                script, "backup-readonly", tool, *args]

    @classmethod
    def identity(cls, deadline=None):
        deadline = deadline or time.monotonic()+60
        history = process_json(["helm", "history", "nomosmart-local", "--kube-context",
            "docker-desktop", "-n", "nomosmart", "-o", "json"], deadline)
        latest = max(history, key=lambda row: row["revision"])
        require(latest["revision"] == 36 and latest["status"] == "deployed", "release_baseline_changed")
        pod = process_json([*cls.PREFIX, "get", "pod", cls.POD, "-o", "json"], deadline)
        require(pod["metadata"]["namespace"] == "nomosmart" and pod["status"]["phase"] == "Running",
                "source_pod_not_ready")
        containers = {item["name"]: item for item in pod["spec"]["containers"]}
        status = {item["name"]: item for item in pod["status"]["containerStatuses"]}
        require(containers["postgresql"]["image"] == "nomosmart/postgresql:18.4"
                and status["postgresql"]["ready"]
                and status["postgresql"]["imageID"].split("@")[-1] == PG_IMAGE, "source_image_or_health_changed")
        return {"context": "docker-desktop", "namespace": "nomosmart", "release": "nomosmart-local",
            "revision": 36, "pod_uid": pod["metadata"]["uid"], "pod": cls.POD,
            "container": "postgresql", "database": "nomosmart", "image": containers["postgresql"]["image"],
            "runtime_image_id": status["postgresql"]["imageID"]}

    @classmethod
    def protections(cls, deadline=None):
        # Keep private payloads inside this process; no Secret body is requested.
        deadline = deadline or time.monotonic()+120
        resources = process_json([*cls.PREFIX, "get",
            "deployments,statefulsets,daemonsets,services,ingresses,persistentvolumeclaims", "-o", "json"], deadline)
        result = []
        for item in resources["items"]:
            if item["kind"] in ("Deployment", "StatefulSet"):
                require(item.get("status", {}).get("readyReplicas", 0) >= item["spec"].get("replicas", 1),
                        "application_not_ready")
            if item["kind"] == "DaemonSet":
                require(item.get("status", {}).get("numberReady", 0) >= item["status"]["desiredNumberScheduled"],
                        "supporting_daemon_not_ready")
            result.append([item["kind"], item["metadata"]["name"], item["metadata"]["uid"], canonical_hash(item["spec"])])
        pvc = [item for item in resources["items"] if item["kind"] == "PersistentVolumeClaim"]
        require(len(pvc) == 7 and all(item["status"]["phase"] == "Bound" for item in pvc), "pvc_baseline_changed")
        for claim in pvc:
            pv = process_json([*cls.PREFIX, "get", "pv", claim["spec"]["volumeName"], "-o", "json"], deadline)
            result.append(["PersistentVolume", pv["metadata"]["name"], pv["metadata"]["uid"], canonical_hash(pv["spec"])])
        # Secret resourceVersion is conservatively checked; no data, key or digest extraction.
        return {"resources": sorted(result), "secret_metadata_sha256":
                configured_secret_metadata(deadline)}

    @classmethod
    def member_baseline(cls, snapshot):
        result = snapshot.value("""SELECT jsonb_build_object(
            'database',current_database(),'readonly',current_setting('transaction_read_only'),
            'latest',(SELECT jsonb_build_array(version,checksum,success) FROM flyway_schema_history
                WHERE version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1),
            'v49',(SELECT count(*) FROM flyway_schema_history WHERE version IN ('049','49')),
            'failed',(SELECT count(*) FROM flyway_schema_history WHERE NOT success),
            'projects',(SELECT count(*) FROM projects),'owners',(SELECT count(*) FROM project_owners),
            'members',(SELECT count(*) FROM project_members),
            'expected_members',(SELECT count(*) FROM project_members m JOIN projects p ON p.id=m.project_id
                JOIN users u ON u.id=m.user_id WHERE p.name='MAAS' AND u.is_active AND
                ((u.email='user01@nomosmart.test' AND m.project_role='owner') OR
                 (u.email='user02@nomosmart.test' AND m.project_role IN ('editor','viewer')))),
            'expected_owner',(SELECT count(*) FROM project_owners o JOIN projects p ON p.id=o.project_id
                JOIN users u ON u.id=o.user_id WHERE p.name='MAAS' AND u.email='user01@nomosmart.test' AND u.is_active))""")
        require(result == {"database": "nomosmart", "readonly": "on", "latest": ["048",1657807790,True],
            "v49": 0, "failed": 0, "projects": 1, "owners": 1, "members": 3,
            "expected_members": 3, "expected_owner": 1}, "schema_or_membership_baseline_changed")
        return result


def entry_compatibility(snapshot):
    """Readonly metadata only: no body/row export, schema dump or data hashing."""
    version = snapshot.value("SELECT current_setting('server_version_num')::int")
    facts = snapshot.value("""SELECT jsonb_build_object('database_owner',pg_get_userbyid(datdba),
        'owner_create',has_database_privilege(datdba,oid,'CREATE'),
        'extensions',(SELECT jsonb_agg(jsonb_build_array(e.extname,e.extversion,n.nspname,pg_get_userbyid(e.extowner))
            ORDER BY e.extname) FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace),
        'roles',(SELECT jsonb_object_agg(rolname,rolsuper) FROM pg_roles
            WHERE oid=d.datdba OR oid IN(SELECT extowner FROM pg_extension)))
        FROM pg_database d WHERE datname=current_database()""")
    members = snapshot.value("""SELECT jsonb_agg(jsonb_build_array(e.extname,
        CASE WHEN d.classid='pg_proc'::regclass THEN 'routine' ELSE 'language' END,i.identity,
        pg_get_userbyid(coalesce(p.proowner,l.lanowner)),
        EXISTS(SELECT 1 FROM pg_init_privs v WHERE v.classoid=d.classid AND v.objoid=d.objid AND v.objsubid=d.objsubid))
        ORDER BY e.extname,i.identity) FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
        CROSS JOIN LATERAL pg_identify_object(d.classid,d.objid,d.objsubid) i
        LEFT JOIN pg_proc p ON d.classid='pg_proc'::regclass AND p.oid=d.objid
        LEFT JOIN pg_language l ON d.classid='pg_language'::regclass AND l.oid=d.objid
        WHERE d.refclassid='pg_extension'::regclass AND d.deptype='e'""")
    ext = facts["extensions"]
    require(version == 180004 and isinstance(ext, list) and len(ext) == 2, "entry_compatibility_version")
    installer = RestoreIdentityProfile.identifier(ext[0][3])
    bootstrap = RestoreIdentityProfile.identifier(ext[1][3])
    require(ext == [["pgcrypto", "1.4", "public", installer], ["plpgsql", "1.0", "pg_catalog", bootstrap]]
            and installer != bootstrap and facts["database_owner"] == installer and facts["owner_create"] is True
            and facts["roles"] == {installer: False, bootstrap: True}, "entry_compatibility_roles")
    require(len(members) == 41 and all(m[3] == bootstrap and m[4] is False for m in members),
            "entry_compatibility_members")
    for name, (_, digest) in RestoreIdentityProfile.MEMBERS.items():
        require(canonical_hash(sorted([m[1], m[2]] for m in members if m[0] == name)) == digest,
                "entry_compatibility_members")
    controls = MixedRestoreIdentityProfile.controls(snapshot)
    require(controls == [{"name": n, "version": v, "trusted": True, "superuser": True, "requires": []}
        for n, v in (("pgcrypto", "1.4"), ("plpgsql", "1.0"))], "entry_compatibility_controls")
    bounds = snapshot.value("WITH members AS ("+ExtensionMemberComments.MEMBERS_SQL+") SELECT jsonb_build_array(count(*),"
        "coalesce(max(octet_length(description)),0),coalesce(sum(octet_length(description)),0),"
        "count(*) FILTER(WHERE classid NOT IN ('pg_proc'::regclass,'pg_language'::regclass) OR objsubid<>0 "
        "OR (comment_oid IS NOT NULL AND (description IS NULL OR description='')))) FROM members")
    require(bounds[0] == 41 and bounds[1] <= ExtensionMemberComments.PER_COMMENT
            and bounds[2] <= ExtensionMemberComments.TOTAL and bounds[3] == 0, "entry_compatibility_comment_bounds")
    return {"contract": "r7", "server_version_num": version, "facts_sha256": canonical_hash(facts),
            "members_sha256": canonical_hash(members), "controls_sha256": canonical_hash(controls), "bounds": bounds}


def prepare_source(qualification):
    proof = require_qualification(qualification)
    identity = LiveSource.identity()
    protections = LiveSource.protections()
    with Snapshot(LiveSource.command("psql", *PSQL)) as snapshot:
        baseline = LiveSource.member_baseline(snapshot)
        DatabaseState.guard_supported(snapshot)
        DatabaseState.properties(snapshot)
        compatibility = entry_compatibility(snapshot)
    binding = {"identity": identity, "protections": protections, "baseline": baseline,
               "sources": tool_sources(), "created_epoch": time.time(), "entry_contract": "r7",
               "qualification_sha256": canonical_hash(proof), "compatibility": compatibility}
    private_json(qualification / "source-binding.json", binding)
    print(json.dumps({"preflight": "PASS", "binding_sha256": canonical_hash(binding),
                      "current_data_export": False}))


def readonly_source_checks(deadline):
    """Fixed allowlist only: never archive, dump, data hash, SQL override or write."""
    identity = LiveSource.identity(deadline)
    protections = LiveSource.protections(deadline)
    with Snapshot(LiveSource.command("psql", *PSQL)) as snapshot:
        snapshot.deadline = min(snapshot.deadline, deadline)
        baseline = LiveSource.member_baseline(snapshot)
        DatabaseState.guard_supported(snapshot)
        properties = DatabaseState.properties(snapshot)
        compatibility = entry_compatibility(snapshot)
    require(time.monotonic() < deadline, "readonly_deadline_exceeded")
    require(LiveSource.identity(deadline) == identity and LiveSource.protections(deadline) == protections,
            "readonly_source_drift")
    return {"identity": identity, "protections": protections, "baseline": baseline,
            "database_properties_sha256": canonical_hash(properties), "current_data_export": False,
            "entry_contract": "r7", "compatibility": compatibility}


def qualify_source_readonly(directory, accepted):
    import coverage
    require(accepted is True, "source_readonly_opt_in_required")
    proof = require_synthetic(directory)
    os.umask(0o077)  # Also protects coverage.py's newly created SQLite reports.
    claim = {"proof_sha256": canonical_hash(proof), "created_epoch": time.time()}
    private_json(directory / "readonly-claimed.json", claim)
    measured = coverage.Coverage(data_file=str(directory / ".coverage.readonly"),
        branch=True, include=[str(Path(__file__).resolve())])
    result = {"status": "FAILED", "exit_code": 1, "sources": tool_sources(),
        "claim_sha256": canonical_hash(claim), "started_epoch": time.time(), "current_data_export": False}
    def expired(signum, frame):
        raise BackupError("readonly_deadline_exceeded")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(300)
    measured.start()
    try:
        require_synthetic(directory)
        result["checks"] = readonly_source_checks(time.monotonic()+300)
        require(tool_sources() == proof["sources"], "readonly_source_changed")
        result.update(status="PASS", exit_code=0)
    except BackupError as exc:
        result["failure_code"] = str(exc)
        raise
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        result["failure_code"] = "readonly_operation_failed_details_withheld"
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        measured.stop()
        measured.save()
        result["finished_epoch"] = time.time()
        result["reports"] = report_hashes(directory, (".coverage.readonly",))
        private_json(directory / "readonly-result.json", result)
    require_synthetic(directory)
    combined = coverage.Coverage(data_file=str(directory / ".coverage.combined"))
    combined.combine(data_paths=[str(directory/name) for name in
        (".coverage.cli", ".coverage.tests", ".coverage.readonly")], keep=True)
    combined.save()
    combined.json_report(outfile=str(directory / "coverage-combined.json"))
    combined.report(show_missing=True)
    qualified = qualification_reports(directory, proof["pytest_exit"], proof["sources"])
    print(json.dumps({"qualification": "PASS", "tests": qualified["tests"],
        "coverage": qualified["coverage"], "current_data_export": False}), flush=True)


def create_backup_directory():
    for path in (BACKUP_ROOT.parent, BACKUP_ROOT):
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        custody(path)
    directory = BACKUP_ROOT / ("run-"+time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())+"-"+secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    return custody(directory)


def live_backup(qualification, binding_sha256, accepted):
    entry = BackupSourceEvidence.live(qualification, binding_sha256, accepted)
    directory = entry.directory
    print(json.dumps({"status": "STARTED", "directory": str(directory)}), flush=True)
    archive = None
    success = False
    try:
        archive, state = export_database(entry.command, directory, _entry=entry)
        outcome = restore_isolated(archive, state, directory, _entry=entry)
        entry.postflight()
        result = finish_bound_backup(entry, archive, state, outcome)
        success = True
        print(json.dumps(result), flush=True)
    finally:
        if archive:
            archive.close()
        if not success:
            private_json(directory / "failed.json", {"status": "FAILED", "encrypted": False,
                "usable_backup": False, "partial_retained": True, "migration_applied": False})


def rehearse_backup_entry():
    """Real owned PG, no configurable remote source or archive input."""
    os.umask(0o077)
    configured = os.environ.get("V49_BACKUP_ARTIFACTS")
    root = Path(configured) if configured else Path(tempfile.mkdtemp(prefix="v049-backup-plain-r6-", dir="/private/tmp"))
    if not configured:
        os.environ["V49_BACKUP_ARTIFACTS"] = str(root)
    ExtensionMemberComments.scope(root)
    directory = root / ("r7-entry-"+secrets.token_hex(8))
    directory.mkdir(mode=0o700)
    source_dir = directory / "source"
    source_dir.mkdir(mode=0o700)
    source = MemoryPostgres(source_dir, bootstrap="r7_bootstrap")
    archive = None
    try:
        try:
            source.start()
            db = "v49b_r7_source_"+secrets.token_hex(8)
            source.create_db(db)
            source.sql(db, "CREATE ROLE r7_installer NOLOGIN NOSUPERUSER; ALTER DATABASE "+quote_ident(db)+
                " OWNER TO r7_installer; SET ROLE r7_installer; CREATE EXTENSION pgcrypto WITH SCHEMA public VERSION '1.4'; "
                "CREATE TABLE rehearsal(id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,content text); "
                "INSERT INTO rehearsal(content) VALUES ('new synthetic entry data'),('第二筆合成資料'); RESET ROLE; "
                "COMMENT ON FUNCTION digest(text,text) IS "+literal("合成註解\n'string' \\path; not SQL")+"; "
                "COMMENT ON FUNCTION plpgsql_call_handler() IS NULL")
            entry = BackupSourceEvidence.owned(source, db, directory)
            archive, state = export_database(entry.command, directory, _entry=entry)
        finally:
            source.cleanup()
        target_dir = directory / "restore"
        target_dir.mkdir(mode=0o700)
        outcome = restore_isolated(archive, state, target_dir, _entry=entry)
        entry.postflight()
        result = finish_bound_backup(entry, archive, state, outcome)
        print(json.dumps({"status": result["status"], "directory": str(directory), "current_data_export": False,
                          "usable_backup": False, "cleanup_ok": result["cleanup_ok"]}), flush=True)
    finally:
        if archive:
            archive.close()
        if not configured:
            os.environ.pop("V49_BACKUP_ARTIFACTS", None)


def plain_entry(args):
    if args.qualify_source_readonly:
        require(args.qualification is not None and args.accept_source_readonly
                and not args.binding_sha256 and not args.accept_unencrypted, "readonly_arguments_invalid")
        qualify_source_readonly(args.qualification, args.accept_source_readonly)
        return True
    require(not args.accept_source_readonly, "unrelated_readonly_opt_in")
    if args.self_test_unencrypted:
        require(not args.qualification and not args.binding_sha256 and not args.accept_unencrypted,
                "self_test_arguments_invalid")
        self_test_plain()
        return True
    if args.prepare_source or args.backup_unencrypted:
        require(args.qualification is not None, "qualification_required")
        if args.prepare_source:
            require(not args.binding_sha256 and not args.accept_unencrypted, "preflight_arguments_invalid")
            prepare_source(args.qualification)
        else:
            require(args.binding_sha256 and args.accept_unencrypted, "plaintext_binding_and_opt_in_required")
            live_backup(args.qualification, args.binding_sha256, args.accept_unencrypted)
        return True
    require(not args.qualification and not args.binding_sha256 and not args.accept_unencrypted,
            "unrelated_mode_arguments")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--cleanup-test", type=Path)
    modes.add_argument("--self-test-unencrypted", action="store_true")
    modes.add_argument("--prepare-source", action="store_true")
    modes.add_argument("--backup-unencrypted", action="store_true")
    modes.add_argument("--qualify-source-readonly", action="store_true")
    modes.add_argument("--diagnose-retained-archive", action="store_true")
    modes.add_argument("--rehearse-backup-entry", action="store_true")
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--binding-sha256")
    parser.add_argument("--accept-unencrypted", action="store_true")
    parser.add_argument("--accept-source-readonly", action="store_true")
    parser.add_argument("--accept-retained-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    if args.rehearse_backup_entry:
        require(not args.qualification and not args.binding_sha256 and not args.accept_unencrypted
                and not args.accept_source_readonly and not args.accept_retained_diagnostic, "entry_arguments_invalid")
        rehearse_backup_entry()
        return
    if args.diagnose_retained_archive:
        require(args.accept_retained_diagnostic and not args.qualification and not args.binding_sha256
                and not args.accept_unencrypted and not args.accept_source_readonly, "diagnostic_arguments_invalid")
        retained_entry()
        return
    require(not args.accept_retained_diagnostic, "unrelated_diagnostic_opt_in")
    if plain_entry(args):
        return
    if args.cleanup_test:
        require(args.cleanup_test.parent == Path("/private/tmp") and re.fullmatch(
            r"v049-backup-(?:qualification|auto|test|plain)-[A-Za-z0-9_-]+", args.cleanup_test.name), "cleanup_path_invalid")
        recover_qualification(args.cleanup_test)
        print("僅清理指定測試紀錄的容器／agent；備份檔保留。")
        return
    require(args.self_test and sys.stdin.isatty(), "human_terminal_required")
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="v049-backup-qualification-", dir="/private/tmp"))
    directory.chmod(0o700)
    print("僅測試合成資料；不連線 Kubernetes，不備份或修改 MAAS。")
    print("本輪報告目錄：", directory, flush=True)
    print("Pinentry 會要求測試用密碼；請勿使用現行帳號密碼。密碼不會交給代理。")
    env = clean_env()
    env.update(V49_BACKUP_ARTIFACTS=str(directory), COVERAGE_FILE=str(directory / ".coverage"))
    child = subprocess.Popen([sys.executable, "-B", "-m", "pytest", "-c", "/dev/null", "-q", "-s", "-p", "no:cacheprovider",
        str(ROOT / "backend/tests/test_chg291_v049_live_backup.py"),
        "--cov=chg291_v049_live_backup", "--cov-branch", "--cov-fail-under=80", "--cov-report=term",
        "--cov-report=json:"+str(directory / "qualification-coverage.json"),
        "--junitxml="+str(directory / "qualification.xml")], cwd=ROOT, env=env)
    try:
        try:
            code = child.wait()
        except KeyboardInterrupt:
            print("取消中，等待隔離資源清理，請勿關閉終端。", flush=True)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            code = 130
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        recover_test_resources(directory)
    print("合成資料驗證結果：", "通過" if code == 0 else "未完成／失敗", "；報告：", directory)
    raise SystemExit(code)


if __name__ == "__main__":
    try:
        if "--self-test-unencrypted" in sys.argv:
            import coverage
            os.umask(0o077)
            CLI_DIRECTORY = Path(tempfile.mkdtemp(prefix="v049-backup-plain-r6-", dir="/private/tmp"))
            CLI_COVERAGE = coverage.Coverage(data_file=str(CLI_DIRECTORY / ".coverage.cli"),
                branch=True, include=[str(Path(__file__).resolve())])
            CLI_COVERAGE.start()
        main()
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.TimeoutExpired, http.client.HTTPException):
        print("backup_operation_failed_details_withheld", file=sys.stderr)
        raise SystemExit(1)

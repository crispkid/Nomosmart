"""Approved V049 rehearsal. Real Docker services, no live credentials or data.

Run with backend/.venv/bin/python from the repository. No product imports here.
The private journal enables exact owned cleanup even after a failed test.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
LABEL = "nomosmart.v049.rehearsal"
SQL = ROOT / "sql/migrations/V049__exclusive_project_member_role.sql"
SQL_SHA = "b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96"
TAGS = {
    "pg": "nomosmart/postgresql:18.4",
    "kc": "nomosmart/keycloak:26.0.8",
    "flyway": "flyway/flyway:13.0.0-alpine",
    "backend": "nomosmart/backend:0.1.0-chg292",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_hashes():
    files = sorted((ROOT / "backend/app").rglob("*.py")) + sorted((ROOT / "sql/migrations").glob("*.sql"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def tooling_hashes():
    paths = [Path(__file__), ROOT / "backend/tests/test_chg291_v049_live_rehearsal.py",
             ROOT / "backend/tests/test_chg291_exclusive_project_member_role.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class Rehearsal:
    def __init__(self, state_path):
        self.path = Path(state_path)
        self.state = json.loads(self.path.read_text())

    def save(self):
        self.path.write_text(json.dumps(self.state, indent=2))
        self.path.chmod(0o600)

    def docker(self, *args, data=None, timeout=120, check=True, extra_env=None):
        # No inherited Proxy, database settings, repo .env, or Docker host override.
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        env.update(extra_env or {})
        result = subprocess.run(["docker", "--context", "desktop-linux", *args], input=data,
                                capture_output=True, timeout=timeout, env=env)
        if check and result.returncode:
            # Synthetic env still must not leak into error artifacts.
            message = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
            for value in self.state.get("secrets", {}).values():
                message = message.replace(value, "[REDACTED]")
            raise RuntimeError(f"docker {args[0]} failed ({result.returncode}): {message[-2500:]}")
        return result

    def inspect(self, kind, ident):
        return json.loads(self.docker(kind, "inspect", ident).stdout)[0]

    def baseline(self):
        ids = self.docker("ps", "-aq", "--no-trunc").stdout.decode().split()
        containers = {}
        for ident in ids:
            info = self.inspect("container", ident)
            containers[ident] = {"name": info["Name"], "image": info["Image"],
                                 "status": info["State"]["Status"], "started": info["State"]["StartedAt"],
                                 "finished": info["State"]["FinishedAt"]}
        return {"containers": containers,
                "images": sorted(set(self.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())),
                "volumes": sorted(self.docker("volume", "ls", "-q").stdout.decode().split()),
                "networks": sorted(self.docker("network", "ls", "-q", "--no-trunc").stdout.decode().split())}

    def guard(self, db=None):
        assert hashlib.sha256(SQL.read_bytes()).hexdigest() == SQL_SHA, "V049 drift"
        assert re.fullmatch(r"v49-[a-f0-9]{12}", self.state["run"])
        net = self.inspect("network", self.state["network"])
        assert net["Internal"] and net["Labels"].get(LABEL) == self.state["run"]
        assert set(net.get("Containers", {})).issubset(set(self.state["containers"]))
        if db is not None:
            assert db in self.state["databases"] and re.fullmatch(r"v49_[a-z0-9_]+", db)
        for ident in self.state["containers"]:
            info = self.inspect("container", ident)
            assert info["Config"]["Labels"].get(LABEL) == self.state["run"]
            assert not info["HostConfig"]["Privileged"] and not info["HostConfig"]["PortBindings"]
            assert set(info["NetworkSettings"]["Networks"]) == {net["Name"]}
            for mount in info["Mounts"]:
                if mount["Type"] == "volume":
                    assert mount["Name"] in self.state["volumes"]
                else:
                    assert mount["Source"] in self.state["allowed_mounts"]
                    assert not mount["RW"] or mount["Source"] == str(self.path.parent)
        assert source_hashes() == self.state["sources"], "application/migration source drift"
        assert tooling_hashes() == self.state["tooling"], "rehearsal test/tool drift"

    def create(self, key, image, *, env=None, mounts=(), entrypoint=None, command=(), memory="1g"):
        name = self.state["run"] + "-" + key
        args = ["create", "--pull=never", "--name", name, "--label", LABEL + "=" + self.state["run"],
                "--network", self.state["network"], "--network-alias", key, "--cpus=1", "--memory=" + memory,
                "--memory-swap=" + memory, "--pids-limit=256"]
        for k in env or {}:
            args += ["-e", k]
        for source, target, readonly in mounts:
            if source not in self.state["volumes"]:
                self.state["allowed_mounts"].append(source)
            args += ["-v", source + ":" + target + (":ro" if readonly else "")]
        if entrypoint:
            args += ["--entrypoint", entrypoint]
        args += [self.state["images"][image], *command]
        ident = self.docker(*args, extra_env=env).stdout.decode().strip()
        self.state["containers"].append(ident)
        self.state["services"][key] = ident
        self.save()
        info = self.inspect("container", ident)
        # Images can declare anonymous volumes. Journal only newly-created,
        # exclusive volumes, and validate exclusivity again before removal.
        for mount in info["Mounts"]:
            if mount["Type"] == "volume" and mount["Name"] not in self.state["volumes"]:
                assert mount["Name"] not in self.state["baseline"]["volumes"]
                self.state["volumes"].append(mount["Name"])
        self.save()
        self.guard()
        self.docker("start", ident)
        return ident

    def setup(self):
        assert hashlib.sha256(SQL.read_bytes()).hexdigest() == SQL_SHA
        self.state["baseline"] = self.baseline()
        self.state["sources"] = source_hashes()
        self.state["tooling"] = tooling_hashes()
        self.state["images"] = {k: self.inspect("image", tag)["Id"] for k, tag in TAGS.items()}
        self.save()
        network = self.docker("network", "create", "--internal", "--label", LABEL + "=" + self.state["run"],
                              self.state["run"]).stdout.decode().strip()
        self.state["network"] = network
        self.save()
        pg_env = {"POSTGRES_PASSWORD": self.state["secrets"]["pg"], "POSTGRES_DB": "v49_control",
                  "NOMOSMART_DB": "nomosmart", "NOMOSMART_DB_USER": "nomosmart",
                  "NOMOSMART_MIGRATION_USER": "v49_migrator", "KEYCLOAK_DB": "v49_identity", "KEYCLOAK_DB_USER": "v49_identity"}
        pg_mounts = []
        for key in ("NOMOSMART_DB_PASSWORD", "NOMOSMART_MIGRATION_PASSWORD", "KEYCLOAK_DB_PASSWORD"):
            value = secrets.token_hex(24)
            self.state["secrets"][key] = value
            secret_path = self.path.parent / (key.lower() + ".secret")
            secret_path.write_text(value); secret_path.chmod(0o600)
            self.state.setdefault("secret_files", []).append(str(secret_path))
            pg_env[key + "_FILE"] = "/run/secrets/" + key
            pg_mounts.append((str(secret_path), pg_env[key + "_FILE"], True))
        self.save()
        self.create("pg", "pg", env=pg_env, mounts=pg_mounts)
        for _ in range(60):
            result = self.docker("exec", self.state["services"]["pg"], "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated PostgreSQL not ready")
        # Historical V042 needs a role/database named nomosmart. Both are freshly
        # created by this isolated image initializer, never a live DB connection.
        self.create("flyway", "flyway", env={"FLYWAY_USER": "v49_migrator", "FLYWAY_PASSWORD": self.state["secrets"]["NOMOSMART_MIGRATION_PASSWORD"],
                    "FLYWAY_CONNECT_RETRIES": "5", "FLYWAY_VALIDATE_MIGRATION_NAMING": "true"},
                    mounts=[(str(ROOT / "sql/migrations"), "/flyway/sql", True)],
                    entrypoint="/bin/sh", command=["-c", "exec sleep 86400"])
        self.create("kc", "kc", env={"KC_BOOTSTRAP_ADMIN_USERNAME": "v49-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": self.state["secrets"]["kc"], "KC_HTTP_ENABLED": "true"},
                    command=["start-dev", "--http-port=8080", "--hostname-strict=false"], memory="2g")
        self.state["databases"].append("v49_control")
        self.save()

    def psql(self, db, sql, *, check=True):
        self.guard(db)
        return self.docker("exec", "-i", self.state["services"]["pg"], "psql", "-X", "-U", "postgres", "-d", db,
                           "-v", "ON_ERROR_STOP=1", "-Atq", data=sql.encode(), check=check)

    def query(self, db, sql):
        value = self.psql(db, sql).stdout.decode().strip()
        return json.loads(value) if value else None

    def database(self, label):
        db = "v49_" + label
        assert re.fullmatch(r"v49_[a-z0-9_]+", db) and db not in self.state["databases"]
        self.psql("v49_control", f'CREATE DATABASE "{db}" OWNER v49_migrator')
        self.state["databases"].append(db)
        self.save()
        return db

    def migrate(self, db, target=49, *, check=True, timeout_lock=False):
        self.guard(db)
        url = f"jdbc:postgresql://pg:5432/{db}"
        if timeout_lock:
            url += "?options=-c%20lock_timeout%3D1500ms%20-c%20statement_timeout%3D5000ms"
        started = time.monotonic()
        result = self.docker("exec", self.state["services"]["flyway"], "/flyway/flyway", "-url=" + url,
                             "-target=" + str(target), "migrate", check=False)
        self.state["operations"].append({"operation": "flyway migrate", "database": db, "target": target,
                    "returncode": result.returncode, "seconds": round(time.monotonic()-started, 3),
                    "lock_timeout": timeout_lock,
                    "output": result.stdout.decode(errors="replace")[-5000:] + result.stderr.decode(errors="replace")[-3000:]})
        self.save()
        if check and result.returncode:
            raise RuntimeError("isolated Flyway failed: " + self.state["operations"][-1]["output"][-4000:])
        return result

    def snapshot(self, db):
        tables = self.query(db, "SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public'")
        parts = []
        for table in tables:
            assert re.fullmatch(r"[a-z0-9_]+", table)
            parts.append(f'''SELECT '{table}' name,json_build_object('count',count(*),'md5',
                md5(coalesce(string_agg(to_jsonb(t)::text,E'\\n' ORDER BY to_jsonb(t)::text),''))) value FROM "{table}" t''')
        result = self.query(db, "SELECT json_object_agg(name,value) FROM (" + " UNION ALL ".join(parts) + ") x")
        result["_constraints"] = self.query(db, """SELECT coalesce(json_agg(x ORDER BY tab,conname),'[]') FROM
            (SELECT c.relname tab,p.conname,pg_get_constraintdef(p.oid) def,obj_description(p.oid,'pg_constraint') comment
            FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public') x""")
        result["_columns"] = self.query(db, """SELECT json_agg(x ORDER BY table_name,ordinal_position) FROM
            (SELECT table_name,column_name,ordinal_position,data_type,is_nullable,column_default FROM
            information_schema.columns WHERE table_schema='public') x""")
        result["_acl"] = self.query(db, """SELECT json_agg(x ORDER BY relname) FROM
            (SELECT c.relname,c.relkind,r.rolname owner,c.relacl FROM pg_class c
             JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner
             WHERE n.nspname='public') x""")
        sequences = self.query(db, "SELECT coalesce(json_agg(sequencename ORDER BY sequencename),'[]') FROM pg_sequences WHERE schemaname='public'")
        result["_sequences"] = {s: self.query(db, f'SELECT row_to_json(t) FROM "{s}" t') for s in sequences}
        return result

    def backup(self, db):
        self.guard(db)
        started = time.monotonic()
        result = self.docker("exec", self.state["services"]["pg"], "pg_dump", "-U", "postgres", "-Fc", "-d", db)
        path = self.path.parent / (db + ".dump")
        path.write_bytes(result.stdout)
        path.chmod(0o600)
        self.state["dumps"].append(str(path))
        self.state["operations"].append({"operation": "pg_dump -Fc", "database": db, "bytes": len(result.stdout),
                    "sha256": hashlib.sha256(result.stdout).hexdigest(), "seconds": round(time.monotonic()-started,3)})
        self.save()
        return path

    def restore(self, db, path):
        self.guard(db)
        assert str(path) in self.state["dumps"] and Path(path).parent == self.path.parent
        assert self.query(db, "SELECT count(*) FROM pg_tables WHERE schemaname='public'") == 0
        started = time.monotonic()
        self.docker("exec", "-i", self.state["services"]["pg"], "pg_restore", "-U", "postgres", "--exit-on-error",
                    "--single-transaction", "-d", db, data=Path(path).read_bytes())
        self.state["operations"].append({"operation": "pg_restore", "database": db, "seconds": round(time.monotonic()-started,3)})
        self.save()

    def api(self, db, source, label, *, keepalive=False):
        self.guard(db)
        packages = ROOT / "backend/.venv/lib/python3.12/site-packages"
        retained = "/verify/retained/backend/tests/test_chg291_exclusive_project_member_role.py"
        mounts = [(str(ROOT / "backend/tests/test_chg291_v049_live_rehearsal.py"), "/verify/test_v049.py", True),
                  (str(ROOT / "backend/tests/test_chg291_exclusive_project_member_role.py"), retained, True),
                  (str(ROOT / "sql/migrations"), "/verify/retained/sql/migrations", True)]
        for package in ("pytest", "_pytest", "pluggy", "iniconfig", "packaging", "pygments", "pytest_cov", "coverage"):
            assert (packages / package).is_dir()
            mounts.append((str(packages / package), "/test-deps/" + package, True))
        mounts.append((str(packages / "py.py"), "/test-deps/py.py", True))
        if source == "current":
            mounts.append((str(ROOT / "backend/app"), "/current/app", True))
        env = {"APP_ENV": "test", "DATABASE_URL": f"postgresql+psycopg2://nomosmart:{self.state['secrets']['NOMOSMART_DB_PASSWORD']}@pg:5432/{db}",
               "V49_API": "1", "V49_API_SOURCE": source, "V49_RUN": self.state["run"], "V49_DB": db,
               "V49_KC_PASSWORD": self.state["secrets"]["kc"], "V49_KC_URL": "http://kc:8080",
               "APP_ENCRYPTION_KEY": self.state["secrets"]["app"], "LOG_LEVEL": "ERROR", "PYTHONDONTWRITEBYTECODE": "1",
               "COVERAGE_CORE": "pytrace", "COVERAGE_FILE": "/tmp/.coverage-v049", "PYTHONSAFEPATH": "1",
               "PYTHONPATH": ("/current:" if source == "current" else "") + "/app:/test-deps:/verify"}
        pytest_args = [
            "-m", "pytest", "-c", "/dev/null", "--rootdir=/verify", "-p", "no:cacheprovider", "--tb=short", "-q",
            "/verify/test_v049.py", retained, "--junitxml=/tmp/v049.xml", "-p", "pytest_cov.plugin",
            "--cov=app.security.project_roles", "--cov-branch", "--cov-report=json:/tmp/v049-coverage.json",
            "--cov-report=term", "--cov-fail-under=80"]
        started = time.monotonic()
        if keepalive:
            ident = self.create("api-" + label, "backend", env=env, mounts=mounts,
                entrypoint="/bin/sh", command=["-c", "exec sleep 3600"])
            logs = self.docker("exec", ident, "python", *pytest_args, timeout=180, check=False)
            code = logs.returncode
        else:
            ident = self.create("api-" + label, "backend", env=env, mounts=mounts, entrypoint="python", command=pytest_args)
            result = self.docker("wait", ident, timeout=180)
            code = int(result.stdout.decode().strip())
            logs = self.docker("logs", ident)
        output = logs.stdout.decode(errors="replace") + logs.stderr.decode(errors="replace")
        for secret in self.state["secrets"].values():
            output = output.replace(secret, "[REDACTED]")
        self.state["operations"].append({"operation": "real SQL/OIDC API pytest", "database": db, "source": source,
                    "image": self.state["images"]["backend"], "returncode": code,
                    "seconds": round(time.monotonic()-started,3), "output": output})
        self.save()
        for source, target in (("/tmp/v049.xml", self.path.parent / (label + ".xml")),
                               ("/tmp/v049-coverage.json", self.path.parent / (label + "-coverage.json"))):
            if keepalive:
                content = self.docker("exec", ident, "cat", source).stdout
                assert 0 < len(content) < 5_000_000
                with target.open("xb") as stream:
                    target.chmod(0o600); stream.write(content)
            else:
                self.docker("cp", ident + ":" + source, str(target), check=False)
        self.remove_container(ident)
        assert code == 0, output[-5000:]

    def remove_container(self, ident):
        assert ident in self.state["containers"]
        info = self.inspect("container", ident)
        assert info["Config"]["Labels"].get(LABEL) == self.state["run"]
        self.docker("rm", "-f", ident)
        self.state["containers"].remove(ident)
        self.save()

    def cleanup(self):
        # No broad-name/prefix deletion. Verify exact IDs and exclusive consumers.
        for ident in list(reversed(self.state["containers"])):
            self.remove_container(ident)
        for volume in self.state["volumes"]:
            assert volume not in self.state["baseline"]["volumes"]
            assert not self.docker("ps", "-aq", "--filter", "volume=" + volume).stdout.strip()
            self.docker("volume", "rm", volume)
        if self.state.get("network"):
            net = self.inspect("network", self.state["network"])
            assert net["Labels"].get(LABEL) == self.state["run"] and not net["Containers"]
            self.docker("network", "rm", net["Id"])
        for name in self.state["dumps"]:
            path = Path(name)
            assert path.parent == self.path.parent and path.suffix == ".dump"
            path.unlink()
        for name in self.state.get("secret_files", []):
            path = Path(name)
            assert path.parent == self.path.parent and path.suffix == ".secret"
            path.unlink()
        self.state["cleanup_equal"] = self.baseline() == self.state["baseline"]
        self.state["source_preserved"] = source_hashes() == self.state["sources"]
        self.save()
        assert self.state["cleanup_equal"], "preexisting Docker baseline changed"
        assert self.state["source_preserved"], "application/migration source changed"


def main():
    directory = Path(tempfile.mkdtemp(prefix="v049-rehearsal-", dir="/private/tmp"))
    directory.chmod(0o700)
    path = directory / "private-state.json"
    state = {"run": "v49-" + secrets.token_hex(6), "containers": [], "volumes": [], "databases": [],
             "services": {}, "allowed_mounts": [], "operations": [], "dumps": [],
             "secrets": {"pg": secrets.token_hex(24), "kc": secrets.token_hex(24), "app": secrets.token_hex(32)}}
    path.write_text(json.dumps(state)); path.chmod(0o600)
    rehearsal = Rehearsal(path)
    print("Rehearsal directory:", directory, flush=True)
    status = 1
    try:
        rehearsal.setup()
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        env.update({"V49_STATE": str(path), "PYTHONDONTWRITEBYTECODE": "1"})
        result = subprocess.run([sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir=" + str(ROOT),
                  "-p", "no:cacheprovider", "--tb=short", "-x", "-q", str(ROOT / "backend/tests/test_chg291_v049_live_rehearsal.py"),
                  "--junitxml=" + str(directory / "migration-tests.xml")], env=env)
        status = result.returncode
    finally:
        rehearsal = Rehearsal(path)
        if "baseline" in rehearsal.state:
            rehearsal.cleanup()
        safe = {k: v for k, v in rehearsal.state.items() if k not in {"secrets", "allowed_mounts"}}
        safe["test_returncode"] = status
        (directory / "evidence.json").write_text(json.dumps(safe, indent=2))
        # All credentials were fresh and only used by now-deleted test services.
        path.unlink()
        print("Safe evidence:", directory / "evidence.json", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())

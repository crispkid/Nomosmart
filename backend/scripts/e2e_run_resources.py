"""Run-owned test resources, never a prefix-based maintenance cleanup utility.

No application configuration is loaded here. Callers must supply explicitly
isolated real clients. A receipt is an ownership record, not a way to adopt data.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import UTC, date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, inspect, select, text, update
from sqlalchemy.orm import Session

from app.db.models import Base


class CleanupConflict(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)  # Never include service response/body/credentials.


def require(condition, code):
    if not condition:
        raise CleanupConflict(code)


def scalar(value):
    if isinstance(value, (UUID, datetime, date)):
        return str(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=scalar).encode()).hexdigest()


class RunJournal:
    """Private, locked, atomic receipt. Keep this open for the whole operation."""
    def __init__(self, path: Path, *, create=False, bindings=None, run_id=None):
        self.path = Path(path).absolute()
        parent = self.path.parent
        require(parent.resolve() == parent, "receipt_parent_symlink")
        info = parent.stat()
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0, "receipt_directory_not_private")
        self.lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            lock_info = os.fstat(self.lock)
            require(stat.S_ISREG(lock_info.st_mode) and lock_info.st_uid == os.getuid()
                and stat.S_IMODE(lock_info.st_mode) & 0o077 == 0, "receipt_lock_not_private")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if create:
                require(not self.path.exists() and not self.path.is_symlink(), "receipt_already_exists")
                self.data = {"version": 1, "run_id": str(UUID(str(run_id))) if run_id else str(uuid4()),
                    "created_at": datetime.now(UTC).isoformat(),
                    "source_sha256": digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(Path(__file__).parent.glob("e2e_*.py"))}),
                    "bindings": bindings or {}, "resources": [], "state": "preparing", "errors": []}
                self.save()
            else:
                fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd) as stream:
                    info = os.fstat(stream.fileno())
                    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                        stat.S_IMODE(info.st_mode) & 0o077 == 0 and info.st_size <= 4_000_000, "receipt_invalid_file")
                    self.data = json.load(stream)
                self.validate()
        except BaseException:
            os.close(self.lock)
            raise

    def validate(self):
        require(isinstance(self.data, dict) and set(self.data) == {"version", "run_id", "created_at",
            "source_sha256", "bindings", "resources", "state", "errors"}, "receipt_invalid_schema")
        require(self.data["version"] == 1 and str(UUID(self.data["run_id"])) == self.data["run_id"], "receipt_invalid_schema")
        require(isinstance(self.data["bindings"], dict) and isinstance(self.data["resources"], list)
            and len(self.data["resources"]) <= 10000, "receipt_invalid_schema")
        require(self.data["state"] in {"preparing", "cleaning", "cleanup_complete", "cleanup_failed", "cleanup_partial"}
            and isinstance(self.data["errors"], list), "receipt_invalid_state")
        ids = set()
        identities = set()
        projects = 0
        for entry in self.data["resources"]:
            require(isinstance(entry, dict) and set(entry) == {"id", "kind", "identity", "proof", "state"}, "receipt_invalid_entry")
            require(entry["kind"] in {"sql", "graph", "index", "object"} and
                isinstance(entry["identity"], dict) and isinstance(entry["proof"], dict) and
                entry["state"] in {"intent", "created", "deleted"}, "receipt_invalid_entry")
            require(str(UUID(entry["id"])) == entry["id"] and entry["id"] not in ids, "receipt_duplicate_entry")
            ids.add(entry["id"])
            identity = digest([entry["kind"], entry["identity"]])
            require(identity not in identities, "receipt_duplicate_identity")
            identities.add(identity)
            projects += int(entry["kind"] == "sql" and entry["identity"].get("table") == "projects")
        require(projects <= 1, "receipt_multiple_projects")

    def save(self):
        self.validate()
        serialized = json.dumps(self.data, sort_keys=True, default=scalar)
        require(len(serialized.encode()) <= 4_000_000, "receipt_size_limit")
        fd, name = tempfile.mkstemp(prefix=".receipt-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(serialized)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(name): os.unlink(name)

    def intent(self, kind, identity):
        require(self.data["state"] == "preparing", "receipt_creation_closed")
        entry = {"id": str(uuid4()), "kind": kind, "identity": identity, "proof": {}, "state": "intent"}
        self.data["resources"].append(entry); self.save()
        return entry

    def created(self, entry, proof):
        entry["proof"] = proof; entry["state"] = "created"; self.save()

    def __enter__(self): return self
    def __exit__(self, *_): os.close(self.lock)


# Explicit support only; users/auth/system tables can never become cleanup targets.
SQL_TABLES = frozenset({"projects", "project_owners", "project_members", "roles", "role_permissions", "role_users",
    "ai_models", "embedding_profiles", "documents", "document_versions", "chunks", "tags", "chunk_tags",
    "document_version_tags", "pipeline_runs", "pipeline_run_steps", "embedding_builds", "embedding_build_vectors",
    "graph_sync_jobs", "chat_records", "validation_runs", "validation_run_items", "approval_requests",
    "approval_tasks", "review_records", "active_version_manifests"})


def table_for(name):
    require(name in SQL_TABLES and name in Base.metadata.tables, "sql_table_not_supported")
    return Base.metadata.tables[name]


def predicate(table, pk):
    require(set(pk) == {c.name for c in table.primary_key}, "sql_incomplete_primary_key")
    return and_(*(table.c[k] == (UUID(v) if table.c[k].type.python_type is UUID else v) for k, v in pk.items()))


def row_proof(table, row):
    keys = {c.name for c in table.primary_key} | {
        "created_at", "project_id", "document_id", "document_version_id", "role_id", "user_id", "model_id", "embedding_profile_id"}
    require("created_at" in row, "sql_creation_identity_missing")
    return {"scope_sha256": digest({k: scalar(row[k]) for k in sorted(keys & row.keys())})}


class SqlResources:
    kind = "sql"
    def __init__(self, engine): self.engine = engine

    def binding(self):
        with self.engine.connect() as connection:
            row = connection.execute(text("""SELECT current_database() AS database, current_schema() AS schema,
                (SELECT oid FROM pg_database WHERE datname=current_database())::text AS database_oid,
                (SELECT oid FROM pg_namespace WHERE nspname=current_schema())::text AS schema_oid,
                (SELECT system_identifier::text FROM pg_control_system()) AS system_id""")).mappings().one()
            return dict(row)

    def create(self, journal, objects):
        require(journal.data["bindings"].get(self.kind) == self.binding(), "sql_target_changed")
        with Session(self.engine, expire_on_commit=False) as session:
            entries = []
            for obj in objects:
                require(inspect(obj).transient, "sql_cannot_adopt_existing_object")
                table = table_for(obj.__table__.name)
                pk = {}
                for column in table.primary_key:
                    value = getattr(obj, column.name)
                    if value is None and column.type.python_type is UUID:
                        value = uuid4(); setattr(obj, column.name, value)
                    require(value is not None, "sql_primary_key_required")
                    pk[column.name] = scalar(value)
                require(session.execute(select(table).where(predicate(table, pk))).first() is None, "sql_resource_exists")
                entry = journal.intent(self.kind, {"table": table.name, "pk": pk})
                session.add(obj)
                session.flush()
                row = session.execute(select(table).where(predicate(table, pk))).mappings().one()
                # Durable proof before commit supports a lost commit acknowledgement.
                journal.created(entry, row_proof(table, row)); entries.append(entry)
            session.commit()
            return entries

    @contextmanager
    def prepare(self, entries):
        with Session(self.engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
            batch = SqlBatch(session, entries)
            batch.preflight()
            yield batch


class SqlBatch:
    def __init__(self, session, entries):
        self.session, self.entries = session, entries

    def preflight(self):
        connection = self.session.connection()
        inspector = inspect(connection)
        schema = connection.scalar(text("SELECT current_schema()"))
        existing_tables = set(inspector.get_table_names(schema=schema))
        targets = {entry["identity"].get("table") for entry in self.entries}
        for name in targets: table_for(name)
        # Inspect actual constraints, not just ORM assumptions; outside-schema FKs fail closed.
        constraints = connection.execute(text("""SELECT ns.nspname AS source_schema, c.relname AS source_table,
            nt.nspname AS target_schema, t.relname AS target_table FROM pg_constraint f
            JOIN pg_class c ON c.oid=f.conrelid JOIN pg_namespace ns ON ns.oid=c.relnamespace
            JOIN pg_class t ON t.oid=f.confrelid JOIN pg_namespace nt ON nt.oid=t.relnamespace
            WHERE f.contype='f' AND nt.nspname=:schema"""), {"schema": schema}).mappings().all()
        incoming = [r for r in constraints if r["target_table"] in targets]
        require(all(r["source_schema"] == schema for r in incoming), "sql_cross_schema_dependency")
        lock_tables = targets | {r["source_table"] for r in incoming}
        quote = connection.dialect.identifier_preparer.quote
        for name in sorted(lock_tables):
            require(name in existing_tables, "sql_schema_changed")
            connection.execute(text(f"LOCK TABLE {quote(schema)}.{quote(name)} IN SHARE ROW EXCLUSIVE MODE"))
        triggers = connection.scalar(text("""SELECT count(*) FROM pg_trigger g JOIN pg_class c ON c.oid=g.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT g.tgisinternal AND n.nspname=:schema
            AND c.relname = ANY(:tables)"""), {"schema": schema, "tables": list(lock_tables)})
        require(not triggers, "sql_custom_trigger_requires_review")
        self.rows, self.tables = {}, {}
        for entry in self.entries:
            ident = entry["identity"]
            require(set(ident) == {"table", "pk"}, "sql_invalid_identity")
            table = table_for(ident["table"])
            row = self.session.execute(select(table).where(predicate(table, ident["pk"]))).mappings().first()
            self.tables[entry["id"]] = table
            if row:
                require(entry["state"] != "deleted" and entry["proof"] == row_proof(table, row), "sql_ownership_changed")
                self.rows[entry["id"]] = row
        self.dependencies = []
        for target_entry in self.entries:
            tid = target_entry["id"]
            if tid not in self.rows: continue
            target_table = self.tables[tid]
            for source_name in sorted({r["source_table"] for r in incoming if r["target_table"] == target_table.name}):
                for fk in inspector.get_foreign_keys(source_name, schema=schema):
                    if fk["referred_table"] != target_table.name: continue
                    # Reflection is only for reading dependencies; never a deletion allowlist.
                    from sqlalchemy import MetaData, Table
                    source = Table(source_name, MetaData(), schema=schema, autoload_with=connection)
                    condition = and_(*(source.c[a] == self.rows[tid][b]
                        for a, b in zip(fk["constrained_columns"], fk["referred_columns"], strict=True)))
                    for row in self.session.execute(select(source).where(condition)).mappings():
                        matches = [e for e in self.entries if e["id"] in self.rows and self.tables[e["id"]].name == source_name
                            and all(scalar(row[k]) == v for k, v in e["identity"]["pk"].items())]
                        require(len(matches) == 1, "sql_unowned_dependency")
                        self.dependencies.append((matches[0]["id"], tid, tuple(fk["constrained_columns"])))

    def delete(self):
        remaining = set(self.rows)
        dependencies = list(self.dependencies)
        while remaining:
            ready = sorted(remaining - {b for a, b, _ in dependencies if a in remaining and b in remaining})
            if not ready:
                # Break only nullable, non-PK links between the exact owned rows.
                cycle = next(((a, b, cols) for a, b, cols in dependencies if a in remaining and b in remaining
                    and all(self.tables[a].c[c].nullable and not self.tables[a].c[c].primary_key for c in cols)), None)
                require(cycle is not None, "sql_nonnullable_cycle")
                a, b, columns = cycle
                entry = next(e for e in self.entries if e["id"] == a)
                self.session.execute(update(self.tables[a]).where(predicate(self.tables[a], entry["identity"]["pk"]))
                    .values(**{c: None for c in columns}))
                dependencies.remove(cycle)
                continue
            for rid in ready:
                entry = next(e for e in self.entries if e["id"] == rid)
                self.session.execute(delete(self.tables[rid]).where(predicate(self.tables[rid], entry["identity"]["pk"])))
                remaining.remove(rid)
        self.session.commit()


def cleanup_run(journal, services):
    """All preflight first; per-service commit receipts, never distributed rollback."""
    journal.validate()
    entries = journal.data["resources"]
    kinds = sorted({e["kind"] for e in entries})
    deletion_started = False
    def confirmed_deleted(entry):
        entry["state"] = "deleted"
        journal.save()
    try:
        for kind in kinds:
            require(kind in services and journal.data["bindings"].get(kind) == services[kind].binding(), "cleanup_target_changed")
        journal.data["state"] = "cleaning"; journal.save()
        with ExitStack() as stack:
            batches = [(kind, stack.enter_context(services[kind].prepare([e for e in entries if e["kind"] == kind]))) for kind in kinds]
            for kind, batch in batches:
                deletion_started = True
                if kind in {"index", "object"}:
                    batch.delete(on_deleted=confirmed_deleted)
                else:
                    batch.delete()
                for entry in entries:
                    if entry["kind"] == kind: entry["state"] = "deleted"
                journal.save()
        # Re-read exact identities. Recreated same-ID resources are conflicts, not owned.
        with ExitStack() as stack:
            for kind in kinds:
                stack.enter_context(services[kind].prepare([e for e in entries if e["kind"] == kind]))
        journal.data["state"] = "cleanup_complete"; journal.save()
        return {"status": "cleanup_complete", "run_id": journal.data["run_id"], "resources": len(entries)}
    except Exception as exc:
        # A lost deletion acknowledgement is unresolved/partial, never a claim
        # that nothing changed. Nontransactional stores persist each receipt.
        journal.data["state"] = "cleanup_partial" if deletion_started or any(e["state"] == "deleted" for e in entries) else "cleanup_failed"
        journal.data["errors"].append({"code": exc.code if isinstance(exc, CleanupConflict) else "cleanup_service_failure"})
        journal.data["errors"] = journal.data["errors"][-100:]
        journal.save()
        raise CleanupConflict(journal.data["errors"][-1]["code"]) from None

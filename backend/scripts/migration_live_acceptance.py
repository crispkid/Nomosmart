from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.deployment.bootstrap import (
    BOOTSTRAP_CHECK_NAMES,
    BootstrapCheck,
    BootstrapFailure,
    _bootstrap_evidence_check,
    _database_check,
    _record_bootstrap_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "sql" / "migrations"
FLYWAY_IMAGE = os.getenv("FLYWAY_IMAGE", "flyway/flyway:13.0.0-alpine")
MIGRATION_FILES = sorted(MIGRATIONS.glob("V*.sql"))
LATEST_VERSION_NUMBER = max(int(path.name.split("__", 1)[0][1:]) for path in MIGRATION_FILES)
LATEST_VERSION = f"{LATEST_VERSION_NUMBER:03d}"


def main() -> None:
    source_url = make_url(get_settings().database_url.get_secret_value())
    if source_url.get_backend_name() != "postgresql" or not source_url.database:
        raise RuntimeError("migration acceptance requires PostgreSQL")
    prefix = f"nomosmart_migration_{uuid4().hex[:10]}"
    databases = [
        f"{prefix}_fresh",
        f"{prefix}_upgrade",
        f"{prefix}_chg266",
        f"{prefix}_chg267",
        f"{prefix}_chg283",
        f"{prefix}_failure",
    ]
    admin_engine = create_engine(source_url.set(database=source_url.database), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            for database in databases:
                connection.execute(text(f'CREATE DATABASE "{database}"'))
        _fresh_and_checksum(source_url, databases[0])
        _upgrade(source_url, databases[1])
        _chg266_upgrade(source_url, databases[2])
        _chg267_upgrade(source_url, databases[3])
        _chg283_upgrade(source_url, databases[4])
        _failure_rollback(source_url, databases[5])
        print(
            "migration-live: fresh, upgrade, CHG-266 backfill, CHG-267 preservation, "
            "CHG-283 additive preservation, rerun, checksum and rollback evidence passed"
        )
    finally:
        with admin_engine.connect() as connection:
            for database in databases:
                connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :database"), {"database": database})
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin_engine.dispose()


def _fresh_and_checksum(source_url, database: str) -> None:
    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    _assert_version(source_url, database, LATEST_VERSION)
    _assert_chg233_fresh_state(source_url, database)
    _assert_chg266_column(source_url, database)
    _assert_chg267_columns(source_url, database)
    _assert_chg281_columns(source_url, database)
    _assert_chg283_column(source_url, database)
    _assert_deployment_bootstrap_evidence(source_url, database)
    rerun = _run_flyway(source_url, database, MIGRATIONS, "migrate")
    if "up to date" not in rerun.lower():
        raise RuntimeError("Flyway rerun did not report an up-to-date schema")
    with tempfile.TemporaryDirectory(prefix="nomosmart-checksum-") as directory:
        altered = Path(directory)
        _copy_migrations(MIGRATIONS, altered)
        with (altered / "V024__initialization_last_known_good.sql").open("a", encoding="utf-8") as file:
            file.write("\n-- checksum acceptance mutation\n")
        _run_flyway(source_url, database, altered, "validate", expect_success=False)


def _assert_deployment_bootstrap_evidence(source_url, database: str) -> None:
    release_id = "migration-live-release"
    settings = get_settings().model_copy(
        update={
            "database_url": SecretStr(source_url.set(database=database).render_as_string(hide_password=False)),
            "deployment_bootstrap_release": release_id,
        }
    )
    _database_check(settings)
    checks = [BootstrapCheck(name=name, detail="live") for name in sorted(BOOTSTRAP_CHECK_NAMES)]
    _record_bootstrap_evidence(settings, checks)
    _record_bootstrap_evidence(settings, checks)
    _bootstrap_evidence_check(settings)

    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            count = int(
                connection.scalar(
                    text("SELECT count(*) FROM deployment_bootstrap_evidence WHERE release_id = :release_id"),
                    {"release_id": release_id},
                )
                or 0
            )
    finally:
        engine.dispose()
    if count != 1:
        raise RuntimeError("deployment bootstrap evidence is not idempotent")

    stale_settings = settings.model_copy(update={"deployment_bootstrap_release": f"{release_id}-next"})
    try:
        _bootstrap_evidence_check(stale_settings)
    except BootstrapFailure as exc:
        if exc.code != "deployment_evidence_missing":
            raise
    else:
        raise RuntimeError("stale deployment evidence unlocked a different release")


def _upgrade(source_url, database: str) -> None:
    with tempfile.TemporaryDirectory(prefix="nomosmart-upgrade-") as directory:
        old = Path(directory)
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            version = int(migration.name.split("__", 1)[0][1:])
            if version <= 25:
                shutil.copy2(migration, old / migration.name)
        _run_flyway(source_url, database, old, "migrate")
    _assert_version(source_url, database, "025")
    legacy_before = _seed_legacy_initialization_evidence(source_url, database)
    chg233_before = _seed_chg233_upgrade_state(source_url, database)
    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    _assert_version(source_url, database, LATEST_VERSION)
    legacy_after = _legacy_initialization_evidence(source_url, database)
    if legacy_after != legacy_before:
        raise RuntimeError("CHG-231 migration changed legacy initialization evidence")
    _assert_chg233_upgrade_state(source_url, database, chg233_before)
    _assert_chg281_columns(source_url, database)
    _assert_chg283_column(source_url, database)


def _assert_chg233_fresh_state(source_url, database: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            roles = connection.execute(text("SELECT name, is_system FROM roles ORDER BY name")).all()
            constraints = set(
                connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'external_group_role_mappings'::regclass AND contype = 'u'"
                    )
                ).scalars()
            )
            if roles != [("system-admin", True)]:
                raise RuntimeError(f"CHG-233 fresh roles are incorrect: {roles}")
            expected = {"uq_external_group_role_mappings_external_group", "uq_external_group_role_mappings_role"}
            if not expected.issubset(constraints):
                raise RuntimeError(f"CHG-233 one-to-one constraints are missing: {constraints}")
    finally:
        engine.dispose()


def _assert_chg266_column(source_url, database: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            metadata = connection.execute(
                text(
                    "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'identity_sync_provider_results' "
                    "AND column_name = 'user_sync_ignored'"
                )
            ).one()
            if metadata[0] != "boolean" or metadata[1] != "NO" or str(metadata[2]).lower() != "false":
                raise RuntimeError(f"CHG-266 boolean column metadata is incorrect: {metadata}")
    finally:
        engine.dispose()


def _assert_chg267_columns(source_url, database: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            metadata = connection.execute(
                text(
                    "SELECT column_name, data_type, character_maximum_length, is_nullable "
                    "FROM information_schema.columns WHERE table_schema = 'public' "
                    "AND table_name = 'users' AND column_name IN ('given_name', 'family_name') "
                    "ORDER BY column_name"
                )
            ).all()
            expected = [
                ("family_name", "character varying", 255, "YES"),
                ("given_name", "character varying", 255, "YES"),
            ]
            if [tuple(row) for row in metadata] != expected:
                raise RuntimeError(f"CHG-267 structured-name column metadata is incorrect: {metadata}")
    finally:
        engine.dispose()


def _assert_chg281_columns(source_url, database: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            metadata = connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'chunks' "
                    "AND column_name IN ('retrieval_text','embedding_content_hash','heading_path','heading_level',"
                    "'page_start','page_end','sequence','stable_chunk_key') ORDER BY column_name"
                )
            ).all()
            expected = {
                ("embedding_content_hash", "character varying", "YES"),
                ("heading_level", "integer", "YES"),
                ("heading_path", "jsonb", "YES"),
                ("page_end", "integer", "YES"),
                ("page_start", "integer", "YES"),
                ("retrieval_text", "text", "YES"),
                ("sequence", "integer", "YES"),
                ("stable_chunk_key", "character varying", "YES"),
            }
            if {tuple(row) for row in metadata} != expected:
                raise RuntimeError(f"CHG-281 additive Chunk columns are incorrect: {metadata}")
    finally:
        engine.dispose()


def _assert_chg283_column(source_url, database: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            metadata = connection.execute(
                text(
                    "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'chunks' "
                    "AND column_name = 'display_markdown'"
                )
            ).one()
            if tuple(metadata) != ("text", "YES", None):
                raise RuntimeError(f"CHG-283 display_markdown metadata is incorrect: {metadata}")
            column_comment = connection.scalar(
                text(
                    "SELECT col_description('chunks'::regclass, attnum) FROM pg_attribute "
                    "WHERE attrelid = 'chunks'::regclass AND attname = 'display_markdown'"
                )
            )
            expected_comment = (
                "Deterministic Chunk-specific Markdown display projection; "
                "never an embedding or BM25 input."
            )
            if column_comment != expected_comment:
                raise RuntimeError(f"CHG-283 display_markdown comment is incorrect: {column_comment!r}")
            audit_count = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE action = 'migration.chg283.markdown_display_and_retrieval_only_embedding'"
                    )
                )
                or 0
            )
            if audit_count != 1:
                raise RuntimeError(f"CHG-283 migration audit count is incorrect: {audit_count}")
    finally:
        engine.dispose()


def _chg283_upgrade(source_url, database: str) -> None:
    with tempfile.TemporaryDirectory(prefix="nomosmart-chg283-") as directory:
        old = Path(directory)
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            version = int(migration.name.split("__", 1)[0][1:])
            if version <= 46:
                shutil.copy2(migration, old / migration.name)
        _run_flyway(source_url, database, old, "migrate")
    _assert_version(source_url, database, "046")

    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            project_id = connection.scalar(
                text("INSERT INTO projects (name) VALUES ('CHG-283 migration project') RETURNING id")
            )
            document_id = connection.scalar(
                text(
                    "INSERT INTO documents (project_id, document_code, title, source_type) "
                    "VALUES (:project_id, 'CHG283', 'CHG-283 migration document', 'upload') RETURNING id"
                ),
                {"project_id": project_id},
            )
            version_id = connection.scalar(
                text(
                    "INSERT INTO document_versions "
                    "(document_id, project_id, version_major, extraction_revision, version_label, status) "
                    "VALUES (:document_id, :project_id, 1, 0, 'v1.0', 'staging') RETURNING id"
                ),
                {"document_id": document_id, "project_id": project_id},
            )
            chunk_id = connection.scalar(
                text(
                    "INSERT INTO chunks "
                    "(project_id, document_id, document_version_id, chunk_index, title, content, "
                    "markdown_content, content_hash, retrieval_text, embedding_content_hash, "
                    "heading_path, heading_level, page_start, page_end, sequence, stable_chunk_key) "
                    "VALUES (:project_id, :document_id, :version_id, 0, 'Legacy heading', "
                    "'Legacy visible text', '# Legacy heading\\n\\nLegacy **visible** text', "
                    "repeat('a', 64), '文件：CHG-283 migration document\\n章節：Legacy heading\\n\\nLegacy visible text', "
                    "repeat('b', 64), '[\"Legacy heading\"]'::jsonb, 1, 7, 7, 1, repeat('c', 64)) "
                    "RETURNING id"
                ),
                {"project_id": project_id, "document_id": document_id, "version_id": version_id},
            )
            model_id = connection.scalar(
                text(
                    "INSERT INTO ai_models (name, model_type, provider) "
                    "VALUES ('CHG-283 migration embedding', 'Embedding', 'disposable') RETURNING id"
                )
            )
            profile_id = connection.scalar(
                text(
                    "INSERT INTO embedding_profiles "
                    "(model_id, model_version, vector_dimension, distance_method, mapping_version) "
                    "VALUES (:model_id, 'v1', 2, 'cosine', 2) RETURNING id"
                ),
                {"model_id": model_id},
            )
            build_id = connection.scalar(
                text(
                    "INSERT INTO embedding_builds "
                    "(project_id, document_id, document_version_id, embedding_profile_id, status, "
                    "chunk_count, content_fingerprint, model_id, vector_dimension, token_count, completed_at) "
                    "VALUES (:project_id, :document_id, :version_id, :profile_id, 'completed', 1, "
                    "repeat('d', 64), :model_id, 2, 5, now()) RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "profile_id": profile_id,
                    "model_id": model_id,
                },
            )
            vector_id = connection.scalar(
                text(
                    "INSERT INTO embedding_build_vectors "
                    "(id, embedding_build_id, chunk_id, chunk_index, vector, vector_checksum, token_count, created_at) "
                    "VALUES (gen_random_uuid(), :build_id, :chunk_id, 0, '[0.1, 0.2]'::jsonb, "
                    "repeat('e', 64), 5, now()) RETURNING id"
                ),
                {"build_id": build_id, "chunk_id": chunk_id},
            )
            manifest_id = connection.scalar(
                text(
                    "INSERT INTO active_version_manifests "
                    "(project_id, document_id, document_version_id, embedding_profile_id, "
                    "embedding_build_id, publication_generation, index_ready) "
                    "VALUES (:project_id, :document_id, :version_id, :profile_id, :build_id, 1, true) "
                    "RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "profile_id": profile_id,
                    "build_id": build_id,
                },
            )
            reference_id = connection.scalar(
                text(
                    "INSERT INTO document_references "
                    "(target_project_id, target_document_id, source_project_id, source_document_id, "
                    "source_version_id, source_project_name_snapshot, source_document_name_snapshot) "
                    "VALUES (:project_id, :document_id, :project_id, :document_id, :version_id, "
                    "'CHG-283 migration project', 'CHG-283 migration document') RETURNING id"
                ),
                {"project_id": project_id, "document_id": document_id, "version_id": version_id},
            )
            before = _chg283_row_snapshots(
                connection,
                chunk_id=chunk_id,
                build_id=build_id,
                vector_id=vector_id,
                manifest_id=manifest_id,
                reference_id=reference_id,
            )
            counts_before = _application_row_counts(connection)
    finally:
        engine.dispose()

    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    _assert_version(source_url, database, LATEST_VERSION)
    _assert_chg283_column(source_url, database)

    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            after = _chg283_row_snapshots(
                connection,
                chunk_id=chunk_id,
                build_id=build_id,
                vector_id=vector_id,
                manifest_id=manifest_id,
                reference_id=reference_id,
            )
            counts_after = _application_row_counts(connection)
            display_markdown = connection.scalar(
                text("SELECT display_markdown FROM chunks WHERE id = :chunk_id"),
                {"chunk_id": chunk_id},
            )
            if after != before or counts_after != counts_before or display_markdown is not None:
                raise RuntimeError("CHG-283 migration changed existing application rows")
    finally:
        engine.dispose()


def _chg283_row_snapshots(
    connection,
    *,
    chunk_id,
    build_id,
    vector_id,
    manifest_id,
    reference_id,
) -> dict[str, object]:
    targets = {
        "chunk": ("chunks", chunk_id, True),
        "build": ("embedding_builds", build_id, False),
        "vector": ("embedding_build_vectors", vector_id, False),
        "manifest": ("active_version_manifests", manifest_id, False),
        "reference": ("document_references", reference_id, False),
    }
    snapshots: dict[str, object] = {}
    for name, (table_name, row_id, omit_display_markdown) in targets.items():
        projection = "to_jsonb(row_value) - 'display_markdown'" if omit_display_markdown else "to_jsonb(row_value)"
        snapshots[name] = connection.scalar(
            text(f"SELECT {projection} FROM {table_name} AS row_value WHERE id = :row_id"),  # noqa: S608 - fixed table names above
            {"row_id": row_id},
        )
    return snapshots


def _application_row_counts(connection) -> dict[str, int]:
    table_names = connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name NOT IN ('audit_logs', 'flyway_schema_history') ORDER BY table_name"
        )
    ).scalars()
    return {
        table_name: int(connection.scalar(text(f'SELECT count(*) FROM "{table_name}"')) or 0)  # noqa: S608 - catalog-derived identifiers
        for table_name in table_names
    }


def _chg266_upgrade(source_url, database: str) -> None:
    with tempfile.TemporaryDirectory(prefix="nomosmart-chg266-") as directory:
        old = Path(directory)
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            version = int(migration.name.split("__", 1)[0][1:])
            if version <= 43:
                shutil.copy2(migration, old / migration.name)
        _run_flyway(source_url, database, old, "migrate")
    _assert_version(source_url, database, "043")

    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            for index in range(4):
                run_id = connection.execute(
                    text(
                        "INSERT INTO identity_sync_runs "
                        "(source, status, trigger_type, requested_scope, phase, queued_at, started_at, completed_at, error_message, error_code, attempt) "
                        "VALUES ('keycloak', 'failed', 'manual', 'people_and_groups', 'failed', now(), now(), now(), "
                        "'Identity synchronization failed', 'keycloak_invalid_response', 1) RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO identity_sync_provider_results "
                        "(run_id, provider_id, provider_name, provider_vendor, requested_scope, status, "
                        "user_sync_status, group_sync_status, users_added, users_updated, users_removed, "
                        "users_failed, users_ignored, error_code, started_at, heartbeat_at, completed_at) "
                        "VALUES (:run_id, :provider_id, 'CHG-266 Provider', 'ldap', 'people_and_groups', "
                        "'failed', 'failed', 'failed', 0, 0, 0, 0, 0, 'keycloak_invalid_response', now(), now(), now())"
                    ),
                    {"run_id": run_id, "provider_id": f"chg266-provider-{index}"},
                )
            before = connection.execute(
                text(
                    "SELECT id::text, run_id::text, provider_id, status, user_sync_status, group_sync_status, "
                    "users_ignored, error_code FROM identity_sync_provider_results ORDER BY provider_id"
                )
            ).all()
    finally:
        engine.dispose()

    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    _assert_version(source_url, database, LATEST_VERSION)
    _assert_chg266_column(source_url, database)

    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT id::text, run_id::text, provider_id, status, user_sync_status, group_sync_status, "
                    "users_ignored, error_code, user_sync_ignored "
                    "FROM identity_sync_provider_results ORDER BY provider_id"
                )
            ).all()
    finally:
        engine.dispose()
    if [tuple(row[:-1]) for row in after] != [tuple(row) for row in before]:
        raise RuntimeError("CHG-266 migration changed historical provider results")
    if len(after) != 4 or any(row[-1] is not False for row in after):
        raise RuntimeError("CHG-266 migration did not backfill four historical results to false")

    rerun = _run_flyway(source_url, database, MIGRATIONS, "migrate")
    if "up to date" not in rerun.lower():
        raise RuntimeError("CHG-266 Flyway rerun did not report an up-to-date schema")


def _chg267_upgrade(source_url, database: str) -> None:
    with tempfile.TemporaryDirectory(prefix="nomosmart-chg267-") as directory:
        old = Path(directory)
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            version = int(migration.name.split("__", 1)[0][1:])
            if version <= 44:
                shutil.copy2(migration, old / migration.name)
        _run_flyway(source_url, database, old, "migrate")
    _assert_version(source_url, database, "044")

    duplicate_names = (
        ("chg267-user01", "Peter Chu Chu"),
        ("chg267-user02", "Justin Wu Wu"),
        ("chg267-user03", "Jerry Lee Lee"),
        ("chg267-user04", "Paggy Lu Lu"),
        ("chg267-user05", "Jam Liu Liu"),
    )
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            for keycloak_user_id, display_name in duplicate_names:
                connection.execute(
                    text(
                        "INSERT INTO users (keycloak_user_id, display_name, auth_source, is_active) "
                        "VALUES (:keycloak_user_id, :display_name, 'ldap', true)"
                    ),
                    {"keycloak_user_id": keycloak_user_id, "display_name": display_name},
                )
            before = connection.execute(
                text(
                    "SELECT id::text, keycloak_user_id, display_name, auth_source, is_active "
                    "FROM users WHERE keycloak_user_id LIKE 'chg267-%' ORDER BY keycloak_user_id"
                )
            ).all()
    finally:
        engine.dispose()

    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    _assert_version(source_url, database, LATEST_VERSION)
    _assert_chg267_columns(source_url, database)
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT id::text, keycloak_user_id, display_name, auth_source, is_active, given_name, family_name "
                    "FROM users WHERE keycloak_user_id LIKE 'chg267-%' ORDER BY keycloak_user_id"
                )
            ).all()
    finally:
        engine.dispose()
    if [tuple(row[:-2]) for row in after] != [tuple(row) for row in before]:
        raise RuntimeError("CHG-267 migration changed existing user identity rows")
    if len(after) != 5 or any(row[-2:] != (None, None) for row in after):
        raise RuntimeError("CHG-267 migration did not preserve five existing rows with nullable structured names")
    rerun = _run_flyway(source_url, database, MIGRATIONS, "migrate")
    if "up to date" not in rerun.lower():
        raise RuntimeError("CHG-267 Flyway rerun did not report an up-to-date schema")


def _seed_chg233_upgrade_state(source_url, database: str) -> dict[str, str]:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (keycloak_user_id, display_name, auth_source, is_active) "
                    "VALUES ('migration-live-user', 'Migration Live User', 'keycloak', true) RETURNING id"
                )
            ).scalar_one()
            system_role_id = connection.execute(text("SELECT id FROM roles WHERE name = 'system-admin'")).scalar_one()
            project_owner_id = connection.execute(text("SELECT id FROM roles WHERE name = 'project-owner'")).scalar_one()
            systemadmin_group_id = connection.execute(
                text(
                    "INSERT INTO external_groups (source, external_group_id, group_name, path, is_active) "
                    "VALUES ('keycloak', 'migration-live-systemadmin', 'systemadmin', '/ldap/systemadmin', true) RETURNING id"
                )
            ).scalar_one()
            users_group_id = connection.execute(
                text(
                    "INSERT INTO external_groups (source, external_group_id, group_name, path, is_active) "
                    "VALUES ('keycloak', 'migration-live-users', 'users', '/ldap/users', true) RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO external_group_role_mappings (external_group_id, role_id, created_by) "
                    "VALUES (:systemadmin_group_id, :role_id, :user_id), (:users_group_id, :role_id, :user_id)"
                ),
                {"systemadmin_group_id": systemadmin_group_id, "users_group_id": users_group_id, "role_id": system_role_id, "user_id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO external_group_users (external_group_id, user_id) "
                    "VALUES (:systemadmin_group_id, :user_id), (:users_group_id, :user_id)"
                ),
                {"systemadmin_group_id": systemadmin_group_id, "users_group_id": users_group_id, "user_id": user_id},
            )
            connection.execute(
                text("INSERT INTO role_users (role_id, user_id, source) VALUES (:role_id, :user_id, 'manual')"),
                {"role_id": project_owner_id, "user_id": user_id},
            )
        return {"user_id": str(user_id), "system_role_id": str(system_role_id), "project_owner_id": str(project_owner_id)}
    finally:
        engine.dispose()


def _assert_chg233_upgrade_state(source_url, database: str, expected: dict[str, str]) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            roles = dict(
                connection.execute(
                    text("SELECT name, is_system FROM roles WHERE name IN ('system-admin', 'project-owner', 'knowledge-editor', 'reviewer')")
                ).all()
            )
            mappings = connection.execute(
                text(
                    "SELECT external_group.group_name FROM external_group_role_mappings mapping "
                    "JOIN external_groups external_group ON external_group.id = mapping.external_group_id "
                    "WHERE mapping.role_id = CAST(:role_id AS uuid) ORDER BY external_group.group_name"
                ),
                {"role_id": expected["system_role_id"]},
            ).scalars().all()
            manual_count = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM role_users WHERE role_id = CAST(:role_id AS uuid) "
                        "AND user_id = CAST(:user_id AS uuid) AND source = 'manual'"
                    ),
                    {"role_id": expected["project_owner_id"], "user_id": expected["user_id"]},
                )
                or 0
            )
            external_count = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM role_users WHERE role_id = CAST(:role_id AS uuid) "
                        "AND user_id = CAST(:user_id AS uuid) AND source = 'external_sync'"
                    ),
                    {"role_id": expected["system_role_id"], "user_id": expected["user_id"]},
                )
                or 0
            )
            origins = dict(connection.execute(text("SELECT group_name, identity_origin FROM external_groups WHERE external_group_id LIKE 'migration-live-%'")).all())
            if roles != {"system-admin": True, "project-owner": False, "knowledge-editor": False, "reviewer": False}:
                raise RuntimeError(f"CHG-233 upgrade role preservation is incorrect: {roles}")
            if mappings != ["systemadmin"]:
                raise RuntimeError(f"CHG-233 upgrade mapping cleanup is incorrect: {mappings}")
            if manual_count != 1 or external_count != 1:
                raise RuntimeError(f"CHG-233 membership reconciliation is incorrect: manual={manual_count}, external={external_count}")
            if origins != {"systemadmin": "ldap", "users": "ldap"}:
                raise RuntimeError(f"CHG-233 group origin backfill is incorrect: {origins}")
            connection.execute(
                text("INSERT INTO role_users (role_id, user_id, source) VALUES (CAST(:role_id AS uuid), CAST(:user_id AS uuid), 'break_glass')"),
                {"role_id": expected["system_role_id"], "user_id": expected["user_id"]},
            )
            connection.execute(
                text("DELETE FROM role_users WHERE role_id = CAST(:role_id AS uuid) AND user_id = CAST(:user_id AS uuid) AND source = 'break_glass'"),
                {"role_id": expected["system_role_id"], "user_id": expected["user_id"]},
            )
    finally:
        engine.dispose()


def _failure_rollback(source_url, database: str) -> None:
    _run_flyway(source_url, database, MIGRATIONS, "migrate")
    with tempfile.TemporaryDirectory(prefix="nomosmart-failure-") as directory:
        broken = Path(directory)
        _copy_migrations(MIGRATIONS, broken)
        failure_version = LATEST_VERSION_NUMBER + 1
        (broken / f"V{failure_version:03d}__intentional_failure.sql").write_text("CREATE TABLE migration_failure_probe(id integer);\nSELECT missing_column FROM missing_table;\n", encoding="utf-8")
        _run_flyway(source_url, database, broken, "migrate", expect_success=False)
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version FROM flyway_schema_history WHERE success = true ORDER BY installed_rank DESC LIMIT 1")).scalar_one()
            probe = connection.execute(text("SELECT to_regclass('public.migration_failure_probe')")).scalar_one()
            if version != LATEST_VERSION or probe is not None:
                raise RuntimeError("failed migration was not transactionally rolled back")
    finally:
        engine.dispose()


def _run_flyway(source_url, database: str, migrations: Path, command: str, *, expect_success: bool = True) -> str:
    environment = os.environ.copy()
    environment.update(
        FLYWAY_URL=f"jdbc:postgresql://host.docker.internal:{source_url.port or 5432}/{database}",
        FLYWAY_USER=source_url.username or "",
        FLYWAY_PASSWORD=source_url.password or "",
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "FLYWAY_URL",
            "-e",
            "FLYWAY_USER",
            "-e",
            "FLYWAY_PASSWORD",
            "-v",
            f"{migrations}:/flyway/sql:ro",
            FLYWAY_IMAGE,
            "-locations=filesystem:/flyway/sql",
            "-validateMigrationNaming=true",
            command,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if expect_success and result.returncode != 0:
        raise RuntimeError(f"Flyway {command} failed: {output[-2000:]}")
    if not expect_success and result.returncode == 0:
        raise RuntimeError(f"Flyway {command} unexpectedly succeeded")
    return output


def _assert_version(source_url, database: str, expected: str) -> None:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version FROM flyway_schema_history WHERE success = true ORDER BY installed_rank DESC LIMIT 1")).scalar_one()
            if version != expected:
                raise RuntimeError(f"expected migration {expected}, found {version}")
    finally:
        engine.dispose()


def _seed_legacy_initialization_evidence(source_url, database: str) -> tuple[dict[str, object], dict[str, object]]:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.begin() as connection:
            state_id = connection.execute(
                text(
                    "INSERT INTO system_initialization_state "
                    "(deployment_mode, status, lock_state, current_revision, last_known_good_revision, "
                    "candidate_metadata, readiness_summary, last_known_good_metadata, last_known_good_readiness) "
                    "VALUES ('appliance', 'completed', 'locked', 9, 8, CAST(:candidate AS jsonb), "
                    "CAST(:readiness AS jsonb), CAST(:known_good AS jsonb), CAST(:readiness AS jsonb)) RETURNING id"
                ),
                {
                    "candidate": '{"marker":"chg231"}',
                    "readiness": '{"ready":true}',
                    "known_good": '{"marker":"legacy"}',
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO system_initialization_steps "
                    "(initialization_state_id, step_key, status, detail_code, safe_summary) "
                    "VALUES (:state_id, 'legacy', 'completed', 'legacy_preserved', CAST(:safe_summary AS jsonb))"
                ),
                {"state_id": state_id, "safe_summary": '{"marker":"chg231"}'},
            )
        return _legacy_initialization_evidence(source_url, database)
    finally:
        engine.dispose()


def _legacy_initialization_evidence(source_url, database: str) -> tuple[dict[str, object], dict[str, object]]:
    engine = create_engine(source_url.set(database=database))
    try:
        with engine.connect() as connection:
            state = connection.execute(
                text("SELECT to_jsonb(state) FROM system_initialization_state AS state WHERE candidate_metadata->>'marker' = 'chg231'")
            ).scalar_one()
            step = connection.execute(
                text("SELECT to_jsonb(step) FROM system_initialization_steps AS step WHERE safe_summary->>'marker' = 'chg231'")
            ).scalar_one()
            return state, step
    finally:
        engine.dispose()


def _copy_migrations(source: Path, target: Path) -> None:
    for migration in source.glob("V*.sql"):
        shutil.copy2(migration, target / migration.name)


if __name__ == "__main__":
    main()

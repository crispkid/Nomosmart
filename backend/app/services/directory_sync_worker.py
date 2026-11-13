from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import IdentitySetting, IdentitySyncProviderResult, IdentitySyncRun
from app.integrations.ldap_directory import LdapDirectory
from app.security.auth_configuration import configuration, current_setting, read_secret
from app.services.audit import add_audit
from app.services.directory_sync import reconcile_directory


def execute_directory_sync(settings, factory, run_id, lease_token) -> None:
    with factory.begin() as session:
        run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.id == run_id).with_for_update())
        if run is None or run.status != "queued" or run.lease_token != lease_token:
            return
        run.status, run.phase = "running", "snapshot_fetch"
        run.started_at = run.heartbeat_at = datetime.now(UTC)
        run.attempt += 1
    try:
        with factory() as session:
            run = session.get(IdentitySyncRun, run_id)
            setting = session.scalar(select(IdentitySetting).where(IdentitySetting.revision == run.configuration_revision))
            if setting is None:
                raise AppError("identity_configuration_changed", "Directory configuration revision is unavailable", status_code=409)
            cfg = configuration(setting)
            scope = run.requested_scope
            secret = read_secret(session, settings, setting, "ldap_bind_password")
            source_id = cfg.directory.source_id
        with factory.begin() as session:
            provider = session.scalar(select(IdentitySyncProviderResult).where(IdentitySyncProviderResult.run_id == run_id, IdentitySyncProviderResult.provider_id == str(source_id)))
            if provider is None:
                provider = IdentitySyncProviderResult(run_id=run_id, provider_id=str(source_id), provider_name=cfg.directory.name, provider_vendor=cfg.directory.schema_type, requested_scope=scope)
                session.add(provider)
            provider.status, provider.started_at, provider.heartbeat_at = "running", datetime.now(UTC), datetime.now(UTC)
        snapshot = LdapDirectory(settings, cfg.directory, secret).snapshot(scope)
        secret = ""
        with factory.begin() as session:
            run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.id == run_id).with_for_update())
            if run.status != "running" or run.lease_token != lease_token:
                return
            active = current_setting(session)
            active_config, requested_config = configuration(active).model_dump(mode="json"), cfg.model_dump(mode="json")
            for key in ("sync_schedule", "timezone", "sync_enabled", "sync_scope", "display_name"):
                active_config.pop(key, None); requested_config.pop(key, None)
            if active_config != requested_config:
                raise AppError("identity_configuration_changed", "Directory configuration changed while synchronization was running", status_code=409)
            if (datetime.now(UTC) - run.started_at).total_seconds() > settings.identity_sync_run_timeout_seconds:
                raise AppError("identity_sync_timeout", "Directory synchronization exceeded its time limit", status_code=504)
            run.phase = "reconciliation"
            reconcile_directory(session, run, snapshot)
            run.status, run.phase = "succeeded", "completed"
            run.completed_at = run.heartbeat_at = datetime.now(UTC)
            provider = session.scalar(select(IdentitySyncProviderResult).where(IdentitySyncProviderResult.run_id == run_id, IdentitySyncProviderResult.provider_id == str(source_id)))
            provider.status = "succeeded"
            provider.user_sync_status = "succeeded" if scope != "groups" else "not_requested"
            provider.group_sync_status = "succeeded" if scope != "people" else "not_requested"
            provider.users_added, provider.users_updated, provider.users_removed = run.users_created, run.users_updated, run.users_disabled
            provider.completed_at = provider.heartbeat_at = run.completed_at
            add_audit(session, actor_user_id=None, action="worker.identity_sync.completed", resource_type="identity_sync_run", resource_id=run.id, result="success", request_id=None, summary={"source_id": str(source_id), "scope": scope, "attempt": run.attempt})
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else "directory_sync_failed"
        with factory.begin() as session:
            run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.id == run_id).with_for_update())
            if run is None or run.status != "running" or run.lease_token != lease_token:
                return
            run.status, run.phase, run.error_code = "failed", "failed", code
            run.error_message = "Directory synchronization did not complete; the previous snapshot was retained"
            run.completed_at = run.heartbeat_at = datetime.now(UTC)
            for provider in session.scalars(select(IdentitySyncProviderResult).where(IdentitySyncProviderResult.run_id == run_id)):
                provider.status, provider.error_code, provider.completed_at = "failed", code, run.completed_at
            from app.services.auth_alerts import directory_failure_alert
            directory_failure_alert(session, run_id=run.id, error_code=code)
            add_audit(session, actor_user_id=None, action="worker.identity_sync.failed", resource_type="identity_sync_run", resource_id=run.id, result="failed", request_id=None, summary={"error_code": code, "attempt": run.attempt})

"""Serve current code with real disposable CHG-293 DB/OIDC browser data.

This is setup/teardown, not a replacement API or Provider. The shared pytest
fixtures create a random PostgreSQL schema and a real Keycloak realm. Normal
FastAPI routing, JWT validation and persistence remain in use over HTTP.
Terminate normally (SIGINT/SIGTERM) to drop the exact realm/schema. Never point
this command at current application services.
"""
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys

import httpx
import uvicorn
from sqlalchemy import text


def main():
    expected = {
        "CHG293_DATABASE_URL": "postgresql+psycopg2://postgres@127.0.0.1:15493/chg293_test",
        "CHG293_KEYCLOAK_URL": "http://127.0.0.1:18093",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise SystemExit("Refusing non-isolated CHG-293 browser services")
    if Path(".env").exists():
        raise SystemExit("Run from a directory without .env; do not inherit app secrets")
    # All unexercised integrations point at an unused loopback port, with no keys.
    os.environ.update({
        "REDIS_URL": "redis://127.0.0.1:15999/0",
        "CELERY_BROKER_URL": "redis://127.0.0.1:15999/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:15999/1",
        "S3_ENDPOINT_URL": "http://127.0.0.1:15999",
        "S3_ACCESS_KEY_ID": "", "S3_SECRET_ACCESS_KEY": "",
        "OPENSEARCH_URL": "http://127.0.0.1:15999",
        "OPENSEARCH_USERNAME": "", "OPENSEARCH_PASSWORD": "",
        "NEO4J_URI": "bolt://127.0.0.1:15999", "NEO4J_PASSWORD": "",
        "KEYCLOAK_SYNC_CLIENT_SECRET": "", "OIDC_CLIENT_SECRET": "",
        "IDENTITY_SYNC_ENABLED": "false",
        "FRONTEND_APP_ORIGIN": "http://127.0.0.1:13093",
        "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:13093",
    })
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_chg293_project_content_and_chat_history import (
        authenticated, history, live_engine, scoped_data,
    )
    from app.core.config import get_settings
    from app.db.models import User
    from sqlalchemy.orm import Session
    from app.main import create_app

    with ExitStack() as stack:
        engine = stack.enter_context(contextmanager(live_engine.__wrapped__)())
        auth = stack.enter_context(contextmanager(authenticated.__wrapped__)(engine))
        scopes = []
        for _ in range(2):
            with Session(engine) as read_session:
                scope_users = {label: read_session.get(User, actor.id) for label, actor in auth[1].items()}
            scope_auth = (auth[0], scope_users, auth[2])
            scopes.append(stack.enter_context(contextmanager(scoped_data.__wrapped__)(scope_auth, engine)))
        settings = get_settings()
        client, users, _ = auth
        issuer = settings.oidc_issuer_url
        realm = issuer.rsplit("/", 1)[1]
        base = os.environ["CHG293_KEYCLOAK_URL"]
        with httpx.Client(base_url=base, timeout=20) as http:
            response = http.post("/realms/master/protocol/openid-connect/token", data={
                "client_id": "admin-cli", "grant_type": "password",
                "username": os.environ["CHG293_KEYCLOAK_ADMIN"],
                "password": os.environ["CHG293_KEYCLOAK_PASSWORD"],
            })
            response.raise_for_status()
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            result = http.get(f"/admin/realms/{realm}/clients", params={"clientId": "chg293-test"}, headers=headers)
            result.raise_for_status()
            oidc_client = result.json()[0]
            oidc_client.update({"standardFlowEnabled": True,
                "redirectUris": ["http://127.0.0.1:13093/auth/callback"],
                "webOrigins": ["http://127.0.0.1:13093"]})
            http.put(f"/admin/realms/{realm}/clients/{oidc_client['id']}", headers=headers, json=oidc_client).raise_for_status()
            for label in ("owner", "editor", "viewer"):
                subject = users[label].keycloak_user_id
                http.put(f"/admin/realms/{realm}/users/{subject}/reset-password", headers=headers,
                    json={"type": "password", "temporary": False, "value": "chg293-browser-disposable-only"}).raise_for_status()

        with Session(engine) as session:
            for label, actor in users.items():
                merged = session.merge(actor)
                merged.display_name = f"CHG293 {label.title()}"
                merged.email = f"{label}@chg293.invalid"
            session.commit()

        evidence = {"issuer": issuer, "frontend": "http://127.0.0.1:13093", "backend": "http://127.0.0.1:18094",
                    "actors": {label: str(actor.id) for label, actor in users.items()}, "scopes": []}
        for index, scope in enumerate(scopes, start=1):
            _, scope_users, _, session, project, document, version, rows = scope
            project.name = f"CHG293 Browser Project {index}"
            document.title = f"CHG293 Stored Document {index}"
            # Earlier rows make paging real, without pushing the named cases off page 1.
            now = datetime.now(UTC)
            for number in range(52):
                extra, _, _ = history(session, actor=scope_users["owner"], project=project,
                    scope="document_staging", versions=[version.id], document_version_id=version.id)
                extra.question = f"Stored paging case {number + 1:02d}"
                extra.asked_at = extra.created_at = now - timedelta(days=2, minutes=number)
            published = {}
            for label, row in rows.items():
                row.question = f"Document {index} {label} stored question"
                row.answer = f"Stored history from {label}, document {index}. Not a Provider answer."
                public_row, _, _ = history(session, actor=scope_users[label], project=project, versions=[version.id])
                public_row.question = f"Project {index} {label} stored question"
                public_row.answer = f"Published-surface historical record by {label}. No active manifest."
                published[label] = str(public_row.conversation_id)
            # Two turns from the same real creator exercise turn counting and authorship.
            first = rows["owner"]
            second, _, _ = history(session, actor=scope_users["owner"], project=project,
                conversation_id=first.conversation_id, scope="document_staging",
                versions=[version.id], document_version_id=version.id)
            second.question = f"Document {index} owner second stored question"
            second.answer = "Second stored turn, not generated."
            session.commit()
            evidence["scopes"].append({"project_id": str(project.id), "document_id": str(document.id),
                "version_id": str(version.id), "document_conversations": {label: str(row.conversation_id) for label, row in rows.items()},
                "published_conversations": published})
        print(json.dumps({"ready": evidence}, ensure_ascii=False), flush=True)
        try:
            uvicorn.run(create_app(settings), host="127.0.0.1", port=18094, log_level="warning")
        finally:
            with engine.connect() as connection:
                print(json.dumps({"final_counts": {
                    "chat_records": connection.execute(text("SELECT count(*) FROM chat_records")).scalar(),
                    "usage_events": connection.execute(text("SELECT count(*) FROM ai_model_usage_events")).scalar(),
                    "models": connection.execute(text("SELECT count(*) FROM ai_models")).scalar(),
                }}), flush=True)


if __name__ == "__main__":
    main()

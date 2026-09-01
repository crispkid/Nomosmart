from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LDAP_TOOL_DIR = ROOT / "deploy" / "docker" / "ldap-test"
sys.path.insert(0, str(LDAP_TOOL_DIR))

import reconcile_keycloak as ldap  # type: ignore[import-not-found]  # noqa: E402


NAMESPACE = "nomosmart"
EXPECTED_PROVIDER_ID = "uVYlBRsGTJa5tasXTZ7pFQ"
EXPECTED_GROUP_MAPPER_ID = "222b4874-ebd5-4533-a198-3850a606dc54"
EXPECTED_FAILED_RUN_IDS = {
    "237b7f7b-0633-4991-8925-d8ae77de9f89",
    "75975909-326b-46ed-9be6-c867e691a1e4",
    "b7f09265-748a-4580-91bf-2be4cfeb4b94",
    "14d7add8-684b-4eab-ac50-e9a337d7cfb8",
}
TARGET_EMPLOYEE_IDS = {
    "Z000000101",
    "Z000000102",
    "Z000000103",
    "Z000000104",
    "Z000000105",
}
TARGET_GROUP_NAMES = {"HR", "IT", "FIN", "nomosmart-admin"}
EXPECTED_MANAGERS = {
    "Z000000101": None,
    "Z000000102": "Z000000101",
    "Z000000103": None,
    "Z000000104": None,
    "Z000000105": "Z000000103",
}
EXPECTED_MEMBERSHIPS = {
    "Z000000101": {"HR", "nomosmart-admin"},
    "Z000000102": {"HR"},
    "Z000000103": {"IT"},
    "Z000000104": {"FIN"},
    "Z000000105": {"IT"},
}


DB_INVENTORY = r'''
import json
from sqlalchemy import text
from app.db.session import get_session_factory

employees = ["Z000000101", "Z000000102", "Z000000103", "Z000000104", "Z000000105"]
groups = ["HR", "IT", "FIN", "nomosmart-admin"]
factory = get_session_factory()
with factory() as session:
    has_boolean = bool(session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='identity_sync_provider_results' "
        "AND column_name='user_sync_ignored')"
    )))
    failed = session.execute(text(
        "SELECT run.id::text AS id, run.status, run.error_code, result.provider_id, "
        "result.status AS provider_status, result.error_code AS provider_error "
        "FROM identity_sync_runs run JOIN identity_sync_provider_results result ON result.run_id=run.id "
        "WHERE run.error_code='keycloak_invalid_response' ORDER BY run.queued_at"
    )).mappings().all()
    users = session.execute(text(
        "SELECT subject.id::text AS id, subject.keycloak_user_id, subject.employee_id, subject.ldap_dn, "
        "subject.email, subject.display_name, subject.department, subject.is_active, "
        "manager.employee_id AS manager_employee_id "
        "FROM users subject LEFT JOIN users manager ON manager.id=subject.manager_user_id "
        "WHERE subject.employee_id=ANY(:employees) ORDER BY subject.employee_id"
    ), {"employees": employees}).mappings().all()
    external_groups = session.execute(text(
        "SELECT id::text AS id, external_group_id, group_name, path, identity_origin, is_active "
        "FROM external_groups WHERE group_name=ANY(:groups) ORDER BY group_name"
    ), {"groups": groups}).mappings().all()
    memberships = session.execute(text(
        "SELECT subject.employee_id, external_group.group_name "
        "FROM external_group_users membership "
        "JOIN users subject ON subject.id=membership.user_id "
        "JOIN external_groups external_group ON external_group.id=membership.external_group_id "
        "WHERE subject.employee_id=ANY(:employees) AND external_group.group_name=ANY(:groups) "
        "ORDER BY subject.employee_id, external_group.group_name"
    ), {"employees": employees, "groups": groups}).mappings().all()
    mapping_count = int(session.scalar(text(
        "SELECT count(*) FROM external_group_role_mappings mapping "
        "JOIN external_groups external_group ON external_group.id=mapping.external_group_id "
        "WHERE external_group.group_name=ANY(:groups)"
    ), {"groups": groups}) or 0)
    role_membership_count = int(session.scalar(text(
        "SELECT count(*) FROM role_users membership JOIN users subject ON subject.id=membership.user_id "
        "WHERE subject.employee_id=ANY(:employees)"
    ), {"employees": employees}) or 0)
    latest = None
    if has_boolean:
        latest_row = session.execute(text(
            "SELECT run.id::text AS id, run.status, run.phase, run.error_code, run.users_created, "
            "run.users_updated, run.groups_created, run.groups_updated, run.role_memberships_updated, "
            "result.provider_id, result.status AS provider_status, result.user_sync_status, "
            "result.group_sync_status, result.users_added, result.users_updated AS provider_users_updated, "
            "result.users_removed, result.users_failed, result.users_ignored, result.user_sync_ignored, "
            "result.error_code AS provider_error "
            "FROM identity_sync_runs run JOIN identity_sync_provider_results result ON result.run_id=run.id "
            "ORDER BY run.queued_at DESC LIMIT 1"
        )).mappings().first()
        latest = dict(latest_row) if latest_row else None
    output = {
        "schema_version": session.scalar(text(
            "SELECT version FROM flyway_schema_history WHERE success=true "
            "ORDER BY installed_rank DESC LIMIT 1"
        )),
        "has_user_sync_ignored": has_boolean,
        "failed_runs": [dict(row) for row in failed],
        "target_users": [dict(row) for row in users],
        "target_groups": [dict(row) for row in external_groups],
        "memberships": [dict(row) for row in memberships],
        "target_mapping_count": mapping_count,
        "target_role_membership_count": role_membership_count,
        "latest_run": latest,
    }
print(json.dumps(output, sort_keys=True, default=str))
'''.strip()


def command(arguments: list[str]) -> str:
    result = subprocess.run(arguments, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed without an error message")
    return result.stdout


def database_inventory(pod: str) -> dict[str, Any]:
    output = command(
        [
            "kubectl",
            "exec",
            "-n",
            NAMESPACE,
            pod,
            "-c",
            "backend",
            "--",
            "python",
            "-c",
            DB_INVENTORY,
        ]
    )
    return json.loads(output)


def keycloak_inventory(pod: str) -> dict[str, Any]:
    providers = [
        row
        for row in ldap.components(NAMESPACE, pod)
        if row.get("name") == ldap.PROVIDER_NAME and row.get("providerId") == "ldap"
    ]
    if len(providers) != 1:
        raise RuntimeError("exactly one openldap-local-test provider is required")
    provider = providers[0]
    provider_id = str(provider.get("id") or "")
    mappers = ldap.components(NAMESPACE, pod, parent=provider_id)
    group_mappers = [
        row
        for row in mappers
        if row.get("name") == ldap.GROUP_MAPPER_NAME
        and row.get("providerId") == "group-ldap-mapper"
    ]
    if len(group_mappers) != 1:
        raise RuntimeError("exactly one approved LDAP group mapper is required")
    root = ldap.ldap_group_root(NAMESPACE, pod)
    if root is None or not root.get("id"):
        raise RuntimeError("Keycloak /ldap root is missing")
    child_rows = ldap.admin_request(
        NAMESPACE,
        pod,
        method="GET",
        path=f"/admin/realms/{ldap.REALM}/groups/{root['id']}/children",
        params={"max": "100"},
    )
    users: dict[str, Any] = {}
    for username in ldap.EXPECTED_USERS:
        rows = ldap.admin_request(
            NAMESPACE,
            pod,
            method="GET",
            path=f"/admin/realms/{ldap.REALM}/users",
            params={"username": username, "exact": "true"},
        )
        matches = [
            row
            for row in rows
            if row.get("username") == username and row.get("federationLink") == provider_id
        ]
        if len(matches) != 1:
            raise RuntimeError(f"federated Keycloak user mismatch: {username}")
        user_id = str(matches[0].get("id") or "")
        detail = ldap.admin_request(
            NAMESPACE,
            pod,
            method="GET",
            path=f"/admin/realms/{ldap.REALM}/users/{user_id}",
        )
        memberships = ldap.admin_request(
            NAMESPACE,
            pod,
            method="GET",
            path=f"/admin/realms/{ldap.REALM}/users/{user_id}/groups",
        )
        role_rows = ldap.admin_request(
            NAMESPACE,
            pod,
            method="GET",
            path=f"/admin/realms/{ldap.REALM}/users/{user_id}/role-mappings",
        )
        users[username] = {
            "id": user_id,
            "attributes": {
                key: (detail.get("attributes") or {}).get(key)
                for key in ("ldap_dn", "employee_id", "department", "manager")
                if key in (detail.get("attributes") or {})
            },
            "group_paths": sorted(str(row.get("path")) for row in memberships),
            "direct_realm_roles": sorted(
                str(row.get("name"))
                for row in role_rows.get("realmMappings", [])
                if row.get("name") != "default-roles-nomosmart"
            ),
            "direct_client_role_count": len(role_rows.get("clientMappings") or {}),
        }
    config = provider.get("config") or {}
    return {
        "provider_id": provider_id,
        "group_mapper_id": str(group_mappers[0].get("id") or ""),
        "provider_security": {
            "connectionUrl": config.get("connectionUrl"),
            "editMode": config.get("editMode"),
            "useTruststoreSpi": config.get("useTruststoreSpi"),
        },
        "role_mapper_count": sum(1 for row in mappers if row.get("providerId") == "role-ldap-mapper"),
        "users": users,
        "groups": sorted(str(row.get("name")) for row in child_rows),
    }


def validate_keycloak(inventory: dict[str, Any]) -> None:
    if inventory["provider_id"] != EXPECTED_PROVIDER_ID:
        raise RuntimeError("Keycloak provider ID drifted")
    if inventory["group_mapper_id"] != EXPECTED_GROUP_MAPPER_ID:
        raise RuntimeError("Keycloak group mapper ID drifted")
    if inventory["provider_security"] != {
        "connectionUrl": ["ldaps://172.19.0.20:636"],
        "editMode": ["READ_ONLY"],
        "useTruststoreSpi": ["ldapsOnly"],
    }:
        raise RuntimeError("Keycloak LDAP security configuration drifted")
    if inventory["role_mapper_count"] != 0:
        raise RuntimeError("unexpected LDAP role mapper")
    if set(inventory["users"]) != set(ldap.EXPECTED_USERS):
        raise RuntimeError("Keycloak seven-user inventory is incomplete")
    if set(inventory["groups"]) != {
        "FIN",
        "HR",
        "IT",
        "nomosmart-admin",
        "nomosmart-reviewers",
        "nomosmart-testers",
    }:
        raise RuntimeError("Keycloak six-group inventory is incomplete")
    for username, expected_paths in ldap.EXPECTED_GROUP_PATHS.items():
        user = inventory["users"][username]
        if user["group_paths"] != sorted(expected_paths):
            raise RuntimeError(f"Keycloak membership drifted: {username}")
        if user["direct_realm_roles"] or user["direct_client_role_count"]:
            raise RuntimeError(f"Keycloak role drifted: {username}")


def validate_failed_history(database: dict[str, Any]) -> None:
    failed = database["failed_runs"]
    if {row["id"] for row in failed} != EXPECTED_FAILED_RUN_IDS or len(failed) != 4:
        raise RuntimeError("the four CHG-266 failed runs were not preserved exactly")
    if any(
        row["status"] != "failed"
        or row["provider_status"] != "failed"
        or row["error_code"] != "keycloak_invalid_response"
        or row["provider_error"] != "keycloak_invalid_response"
        or row["provider_id"] != EXPECTED_PROVIDER_ID
        for row in failed
    ):
        raise RuntimeError("CHG-266 failed-run evidence drifted")


def validate_preflight(database: dict[str, Any]) -> None:
    if database["schema_version"] != "043" or database["has_user_sync_ignored"]:
        raise RuntimeError("preflight database is not at the exact V043 baseline")
    validate_failed_history(database)
    if database["target_users"] or database["target_groups"] or database["memberships"]:
        raise RuntimeError("NomoSmart target identity rows are not absent at preflight")
    if database["target_mapping_count"] or database["target_role_membership_count"]:
        raise RuntimeError("unexpected NomoSmart target authorization exists at preflight")


def validate_post_upgrade(database: dict[str, Any], run_id: str) -> None:
    if database["schema_version"] != "044" or not database["has_user_sync_ignored"]:
        raise RuntimeError("post-upgrade database has not applied V044")
    validate_failed_history(database)
    users = {row["employee_id"]: row for row in database["target_users"]}
    if set(users) != TARGET_EMPLOYEE_IDS:
        raise RuntimeError("NomoSmart five-user inventory is incomplete")
    for employee_id, expected_manager in EXPECTED_MANAGERS.items():
        row = users[employee_id]
        if row["manager_employee_id"] != expected_manager or not row["is_active"]:
            raise RuntimeError(f"NomoSmart manager/active state mismatch: {employee_id}")
    groups = {row["group_name"]: row for row in database["target_groups"]}
    if set(groups) != TARGET_GROUP_NAMES:
        raise RuntimeError("NomoSmart four-group inventory is incomplete")
    if any(not row["is_active"] or row["identity_origin"] != "ldap" for row in groups.values()):
        raise RuntimeError("NomoSmart LDAP group origin/active state mismatch")
    memberships = {employee: set() for employee in TARGET_EMPLOYEE_IDS}
    for row in database["memberships"]:
        memberships[row["employee_id"]].add(row["group_name"])
    if memberships != EXPECTED_MEMBERSHIPS:
        raise RuntimeError("NomoSmart target memberships are incorrect")
    if database["target_mapping_count"] or database["target_role_membership_count"]:
        raise RuntimeError("NomoSmart target identities unexpectedly received authorization")
    latest = database["latest_run"] or {}
    if latest.get("id") != run_id:
        raise RuntimeError("requested CHG-266 run is not the latest run")
    for key in ("status", "phase", "provider_status", "user_sync_status", "group_sync_status"):
        expected = "completed" if key == "phase" else "succeeded"
        if latest.get(key) != expected:
            raise RuntimeError(f"CHG-266 run state is incorrect: {key}")
    if latest.get("error_code") is not None or latest.get("provider_error") is not None:
        raise RuntimeError("CHG-266 run unexpectedly has an error")
    if latest.get("user_sync_ignored") is not False or latest.get("users_ignored") != 0:
        raise RuntimeError("CHG-266 boolean/deprecated ignored evidence is incorrect")
    for key in ("users_added", "provider_users_updated", "users_removed", "users_failed"):
        value = latest.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"CHG-266 counter is not a non-negative integer: {key}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "verify"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    context = command(["kubectl", "config", "current-context"]).strip()
    if context != "docker-desktop":
        raise RuntimeError(f"unexpected Kubernetes context: {context}")
    releases = json.loads(command(["helm", "list", "-n", NAMESPACE, "-o", "json"]))
    release = next((row for row in releases if row.get("name") == "nomosmart-local"), None)
    if not release or release.get("status") != "deployed":
        raise RuntimeError("nomosmart-local Helm release is not deployed")
    pod = ldap.backend_pod(NAMESPACE)
    database = database_inventory(pod)
    keycloak = keycloak_inventory(pod)
    validate_keycloak(keycloak)
    if args.mode == "preflight":
        if str(release.get("revision")) != "11":
            raise RuntimeError("preflight Helm revision is not 11")
        validate_preflight(database)
    else:
        if not args.run_id:
            raise RuntimeError("--run-id is required for post-upgrade verification")
        validate_post_upgrade(database, args.run_id)
    print(
        json.dumps(
            {
                "context": context,
                "release_revision": str(release.get("revision")),
                "schema_version": database["schema_version"],
                "failed_history_count": len(database["failed_runs"]),
                "target_user_count": len(database["target_users"]),
                "target_group_count": len(database["target_groups"]),
                "provider_id": keycloak["provider_id"],
                "group_mapper_id": keycloak["group_mapper_id"],
                "keycloak_user_count": len(keycloak["users"]),
                "keycloak_group_count": len(keycloak["groups"]),
                "run_id": args.run_id,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"CHG-266 live acceptance failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

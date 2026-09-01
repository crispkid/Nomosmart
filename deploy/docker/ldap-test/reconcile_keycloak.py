#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REALM = "nomosmart"
PROVIDER_NAME = "openldap-local-test"
GROUP_MAPPER_NAME = "openldap-local-test-groups"
COMPONENT_TYPE = "org.keycloak.storage.UserStorageProvider"
MAPPER_TYPE = "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
EXPECTED_USERS = (
    "ldap.alice",
    "ldap.bob",
    "user01",
    "user02",
    "user03",
    "user04",
    "user05",
)
EXPECTED_GROUP_PATHS = {
    "ldap.alice": ("/ldap/nomosmart-reviewers", "/ldap/nomosmart-testers"),
    "ldap.bob": ("/ldap/nomosmart-testers",),
    "user01": ("/ldap/HR", "/ldap/nomosmart-admin"),
    "user02": ("/ldap/HR",),
    "user03": ("/ldap/IT",),
    "user04": ("/ldap/FIN",),
    "user05": ("/ldap/IT",),
}
EXPECTED_CHG265_ATTRIBUTES = {
    "user01": {
        "ldap_dn": ["uid=user01,ou=users,dc=nomosmart,dc=test"],
        "employee_id": ["Z000000101"],
        "department": ["HR"],
    },
    "user02": {
        "ldap_dn": ["uid=user02,ou=users,dc=nomosmart,dc=test"],
        "employee_id": ["Z000000102"],
        "department": ["HR"],
        "manager": ["uid=user01,ou=users,dc=nomosmart,dc=test"],
    },
    "user03": {
        "ldap_dn": ["uid=user03,ou=users,dc=nomosmart,dc=test"],
        "employee_id": ["Z000000103"],
        "department": ["IT"],
    },
    "user04": {
        "ldap_dn": ["uid=user04,ou=users,dc=nomosmart,dc=test"],
        "employee_id": ["Z000000104"],
        "department": ["FIN"],
    },
    "user05": {
        "ldap_dn": ["uid=user05,ou=users,dc=nomosmart,dc=test"],
        "employee_id": ["Z000000105"],
        "department": ["IT"],
        "manager": ["uid=user03,ou=users,dc=nomosmart,dc=test"],
    },
}
EXPECTED_CHG267_NAMES = {
    "user01": ("Peter", "Chu"),
    "user02": ("Justin", "Wu"),
    "user03": ("Jerry", "Lee"),
    "user04": ("Paggy", "Lu"),
    "user05": ("Jam", "Liu"),
}
EXPECTED_SAFE_PROVIDER_CONFIG = {
    "connectionUrl": ["ldaps://172.19.0.20:636"],
    "usersDn": ["ou=users,dc=nomosmart,dc=test"],
    "bindDn": ["cn=nomosmart-bind,dc=nomosmart,dc=test"],
    "authType": ["simple"],
    "editMode": ["READ_ONLY"],
    "syncRegistrations": ["false"],
    "customUserSearchFilter": ["(objectClass=inetOrgPerson)"],
    "useTruststoreSpi": ["ldapsOnly"],
}
FIRST_NAME_MODEL_ATTRIBUTE = "firstName"
LAST_NAME_MODEL_ATTRIBUTE = "lastName"
EXPECTED_FIRST_NAME_LDAP_ATTRIBUTES = {"cn", "givenName"}


def run(command: list[str], *, stdin: str = "") -> str:
    result = subprocess.run(
        command,
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "command failed without an error message"
        raise RuntimeError(message)
    return result.stdout


def kubectl_json(namespace: str, arguments: list[str]) -> Any:
    return json.loads(run(["kubectl", *arguments, "-n", namespace, "-o", "json"]))


def backend_pod(namespace: str) -> str:
    payload = kubectl_json(
        namespace,
        [
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/instance=nomosmart-local,app.kubernetes.io/component=backend",
        ],
    )
    names = [
        row["metadata"]["name"]
        for row in payload.get("items", [])
        if row.get("status", {}).get("phase") == "Running"
    ]
    if len(names) != 1:
        raise RuntimeError("exactly one running NomoSmart Backend Pod is required")
    return names[0]


def bind_credential(namespace: str) -> str:
    payload = kubectl_json(
        namespace,
        ["get", "secret", "nomosmart-directory-bind"],
    )
    encoded = payload.get("data", {}).get("bind-password")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("directory bind Secret is missing bind-password")
    value = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
    if not value:
        raise RuntimeError("directory bind credential is empty")
    return value


ADMIN_HELPER = r"""
import json
import os
import sys

import httpx

request = json.load(sys.stdin)
base_url = os.environ["KEYCLOAK_ADMIN_INTERNAL_URL"].rstrip("/")
realm = "nomosmart"
with httpx.Client(timeout=600.0) as client:
    token_response = client.post(
        f"{base_url}/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["KEYCLOAK_SYNC_CLIENT_ID"],
            "client_secret": os.environ["KEYCLOAK_SYNC_CLIENT_SECRET"],
        },
    )
    if token_response.status_code >= 400:
        raise SystemExit(
            f"service-account authentication failed with status {token_response.status_code}"
        )
    token = token_response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("service-account token response was invalid")
    response = client.request(
        request["method"],
        f"{base_url}{request['path']}",
        headers={"Authorization": f"Bearer {token}"},
        params=request.get("params"),
        json=request.get("payload"),
    )
    if response.status_code >= 400:
        raise SystemExit(f"Keycloak Admin API failed with status {response.status_code}")
    sys.stdout.write(response.text if response.content else "{}")
""".strip()


def admin_request(
    namespace: str,
    pod: str,
    *,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    serialized = json.dumps(
        {
            "method": method,
            "path": path,
            "params": params,
            "payload": payload,
        },
        separators=(",", ":"),
    )
    output = run(
        [
            "kubectl",
            "exec",
            "-i",
            "-n",
            namespace,
            pod,
            "--",
            "python",
            "-c",
            ADMIN_HELPER,
        ],
        stdin=serialized,
    )
    return json.loads(output)


def components(namespace: str, pod: str, *, parent: str | None = None) -> list[dict[str, Any]]:
    params = {"type": MAPPER_TYPE if parent else COMPONENT_TYPE}
    if parent:
        params["parent"] = parent
    payload = admin_request(
        namespace,
        pod,
        method="GET",
        path=f"/admin/realms/{REALM}/components",
        params=params,
    )
    if not isinstance(payload, list):
        raise RuntimeError("Keycloak components response is invalid")
    return [row for row in payload if isinstance(row, dict)]


def _single_config_value(row: dict[str, Any], key: str) -> str:
    config = row.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("Keycloak mapper config is invalid")
    values = config.get(key)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
        raise RuntimeError(f"Keycloak mapper config must contain one {key} value")
    return values[0]


def person_name_mapper_plan(mapper_rows: list[dict[str, Any]]) -> dict[str, Any]:
    attribute_mappers = [
        row for row in mapper_rows
        if row.get("providerId") == "user-attribute-ldap-mapper"
    ]
    first_matches = [
        row for row in attribute_mappers
        if _single_config_value(row, "user.model.attribute") == FIRST_NAME_MODEL_ATTRIBUTE
    ]
    last_matches = [
        row for row in attribute_mappers
        if _single_config_value(row, "user.model.attribute") == LAST_NAME_MODEL_ATTRIBUTE
    ]
    if len(first_matches) != 1:
        raise RuntimeError("exactly one Keycloak firstName LDAP mapper is required")
    if len(last_matches) != 1:
        raise RuntimeError("exactly one Keycloak lastName LDAP mapper is required")
    first_mapper = first_matches[0]
    last_mapper = last_matches[0]
    first_mapper_id = str(first_mapper.get("id") or "")
    last_mapper_id = str(last_mapper.get("id") or "")
    if not first_mapper_id or not last_mapper_id:
        raise RuntimeError("Keycloak person-name mapper has no id")
    first_ldap_attribute = _single_config_value(first_mapper, "ldap.attribute")
    last_ldap_attribute = _single_config_value(last_mapper, "ldap.attribute")
    if first_ldap_attribute not in EXPECTED_FIRST_NAME_LDAP_ATTRIBUTES:
        raise RuntimeError("unexpected Keycloak firstName LDAP attribute")
    if last_ldap_attribute != "sn":
        raise RuntimeError("Keycloak lastName mapper must remain bound to sn")
    return {
        "first_mapper": first_mapper,
        "first_mapper_id": first_mapper_id,
        "first_ldap_attribute": first_ldap_attribute,
        "last_mapper_id": last_mapper_id,
        "last_ldap_attribute": last_ldap_attribute,
        "requires_change": first_ldap_attribute == "cn",
    }


def _component_update_payload(row: dict[str, Any]) -> dict[str, Any]:
    allowed = ("id", "name", "providerId", "providerType", "parentId", "subType", "config")
    payload = {key: copy.deepcopy(row[key]) for key in allowed if key in row}
    if not all(payload.get(key) for key in ("id", "name", "providerId", "providerType", "parentId")):
        raise RuntimeError("Keycloak mapper representation is incomplete")
    return payload


def _mapper_rows_by_id(mapper_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in mapper_rows:
        component_id = str(row.get("id") or "")
        if not component_id or component_id in result:
            raise RuntimeError("Keycloak mapper ids are missing or duplicated")
        result[component_id] = row
    return result


def reconcile_person_name_mapper(namespace: str, pod: str, provider_id: str) -> dict[str, Any]:
    before_rows = components(namespace, pod, parent=provider_id)
    before = person_name_mapper_plan(before_rows)
    if not before["requires_change"]:
        return {
            "provider_id": provider_id,
            "first_mapper_id": before["first_mapper_id"],
            "first_ldap_attribute_before": before["first_ldap_attribute"],
            "first_ldap_attribute_after": before["first_ldap_attribute"],
            "last_mapper_id": before["last_mapper_id"],
            "last_ldap_attribute": before["last_ldap_attribute"],
            "mapper_count": len(before_rows),
            "changed": False,
        }
    payload = _component_update_payload(before["first_mapper"])
    payload["config"]["ldap.attribute"] = ["givenName"]
    admin_request(
        namespace,
        pod,
        method="PUT",
        path=f"/admin/realms/{REALM}/components/{before['first_mapper_id']}",
        payload=payload,
    )
    after_rows = components(namespace, pod, parent=provider_id)
    after = person_name_mapper_plan(after_rows)
    if after["requires_change"] or after["first_mapper_id"] != before["first_mapper_id"]:
        raise RuntimeError("Keycloak firstName LDAP mapper update verification failed")
    if after["last_mapper_id"] != before["last_mapper_id"]:
        raise RuntimeError("Keycloak lastName mapper identity changed unexpectedly")

    before_by_id = _mapper_rows_by_id(before_rows)
    after_by_id = _mapper_rows_by_id(after_rows)
    if set(before_by_id) != set(after_by_id):
        raise RuntimeError("Keycloak mapper set changed unexpectedly")
    expected_after_target = copy.deepcopy(before_by_id[before["first_mapper_id"]])
    expected_after_target["config"]["ldap.attribute"] = ["givenName"]
    for component_id, before_row in before_by_id.items():
        expected = expected_after_target if component_id == before["first_mapper_id"] else before_row
        if after_by_id[component_id] != expected:
            raise RuntimeError(f"unexpected Keycloak mapper drift: {component_id}")
    return {
        "provider_id": provider_id,
        "first_mapper_id": before["first_mapper_id"],
        "first_ldap_attribute_before": before["first_ldap_attribute"],
        "first_ldap_attribute_after": after["first_ldap_attribute"],
        "last_mapper_id": after["last_mapper_id"],
        "last_ldap_attribute": after["last_ldap_attribute"],
        "mapper_count": len(after_rows),
        "changed": True,
    }


def trigger_person_name_full_sync(namespace: str, pod: str, provider_id: str) -> dict[str, int]:
    state = person_name_mapper_plan(components(namespace, pod, parent=provider_id))
    if state["requires_change"]:
        raise RuntimeError("Keycloak firstName LDAP mapper must be reconciled before full sync")
    sync = admin_request(
        namespace,
        pod,
        method="POST",
        path=f"/admin/realms/{REALM}/user-storage/{provider_id}/sync",
        params={"action": "triggerFullSync"},
    )
    result = {
        key: int(sync.get(key, 0))
        for key in ("added", "updated", "removed", "failed", "ignored")
    }
    if result["failed"] != 0:
        raise RuntimeError("Keycloak LDAP user full sync reported failures")
    return result


def person_name_user_readback(namespace: str, pod: str, provider_id: str) -> dict[str, Any]:
    users: dict[str, Any] = {}
    for username, (expected_given, expected_family) in EXPECTED_CHG267_NAMES.items():
        rows = admin_request(
            namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users",
            params={"username": username, "exact": "true"},
        )
        matches = [
            row for row in rows
            if row.get("username") == username and row.get("federationLink") == provider_id
        ]
        if len(matches) != 1:
            raise RuntimeError(f"federated Keycloak user mismatch: {username}")
        user_id = str(matches[0].get("id") or "")
        detail = admin_request(
            namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users/{user_id}",
        )
        given_name = str(detail.get("firstName") or "")
        family_name = str(detail.get("lastName") or "")
        if (given_name, family_name) != (expected_given, expected_family):
            raise RuntimeError(f"federated Keycloak person name mismatch: {username}")
        users[username] = {
            "id": user_id,
            "given_name": given_name,
            "family_name": family_name,
        }
    return users


def write_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def realm_id(namespace: str, pod: str) -> str:
    payload = admin_request(
        namespace,
        pod,
        method="GET",
        path=f"/admin/realms/{REALM}",
    )
    value = str(payload.get("id") or "")
    if not value:
        raise RuntimeError("Keycloak realm representation has no id")
    return value


def upsert_component(
    namespace: str,
    pod: str,
    payload: dict[str, Any],
    *,
    parent: str | None = None,
) -> str:
    matches = [
        row
        for row in components(namespace, pod, parent=parent)
        if row.get("name") == payload["name"]
        and row.get("providerId") == payload["providerId"]
    ]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate Keycloak component: {payload['name']}")
    if matches:
        component_id = str(matches[0].get("id") or "")
        if not component_id:
            raise RuntimeError(f"Keycloak component has no id: {payload['name']}")
        admin_request(
            namespace,
            pod,
            method="PUT",
            path=f"/admin/realms/{REALM}/components/{component_id}",
            payload=payload,
        )
    else:
        admin_request(
            namespace,
            pod,
            method="POST",
            path=f"/admin/realms/{REALM}/components",
            payload=payload,
        )
        created = [
            row
            for row in components(namespace, pod, parent=parent)
            if row.get("name") == payload["name"]
            and row.get("providerId") == payload["providerId"]
        ]
        if len(created) != 1:
            raise RuntimeError(f"Keycloak component create verification failed: {payload['name']}")
        component_id = str(created[0].get("id") or "")
    return component_id


def provider_payload(password: str, parent_id: str) -> dict[str, Any]:
    return {
        "name": PROVIDER_NAME,
        "providerId": "ldap",
        "providerType": COMPONENT_TYPE,
        "parentId": parent_id,
        "config": {
            "enabled": ["true"],
            "vendor": ["other"],
            "connectionUrl": ["ldaps://172.19.0.20:636"],
            "usersDn": ["ou=users,dc=nomosmart,dc=test"],
            "bindDn": ["cn=nomosmart-bind,dc=nomosmart,dc=test"],
            "bindCredential": [password],
            "authType": ["simple"],
            "editMode": ["READ_ONLY"],
            "importEnabled": ["true"],
            "syncRegistrations": ["false"],
            "usernameLDAPAttribute": ["uid"],
            "rdnLDAPAttribute": ["uid"],
            "uuidLDAPAttribute": ["entryUUID"],
            "userObjectClasses": ["inetOrgPerson"],
            "customUserSearchFilter": ["(objectClass=inetOrgPerson)"],
            "searchScope": ["1"],
            "pagination": ["true"],
            "connectionPooling": ["true"],
            "useTruststoreSpi": ["ldapsOnly"],
            "batchSizeForSync": ["1000"],
            "fullSyncPeriod": ["-1"],
            "changedSyncPeriod": ["-1"],
            "cachePolicy": ["DEFAULT"],
        },
    }


def group_mapper_payload(provider_id: str) -> dict[str, Any]:
    return {
        "name": GROUP_MAPPER_NAME,
        "providerId": "group-ldap-mapper",
        "providerType": MAPPER_TYPE,
        "parentId": provider_id,
        "config": {
            "groups.dn": ["ou=groups,dc=nomosmart,dc=test"],
            "group.name.ldap.attribute": ["cn"],
            "group.object.classes": ["groupOfNames"],
            "membership.ldap.attribute": ["member"],
            "membership.attribute.type": ["DN"],
            "membership.user.ldap.attribute": ["uid"],
            "mode": ["READ_ONLY"],
            "groups.path": ["/ldap"],
            "preserve.group.inheritance": ["true"],
            "drop.non.existing.groups.during.sync": ["true"],
        },
    }


def attribute_mapper_payload(
    provider_id: str,
    *,
    name: str,
    ldap_attribute: str,
    keycloak_attribute: str,
) -> dict[str, Any]:
    return {
        "name": f"openldap-local-test-{name}",
        "providerId": "user-attribute-ldap-mapper",
        "providerType": MAPPER_TYPE,
        "parentId": provider_id,
        "config": {
            "ldap.attribute": [ldap_attribute],
            "user.model.attribute": [keycloak_attribute],
            "read.only": ["true"],
            "always.read.value.from.ldap": ["true"],
            "is.mandatory.in.ldap": ["false"],
        },
    }


def ldap_group_root(namespace: str, pod: str) -> dict[str, Any] | None:
    groups = admin_request(
        namespace,
        pod,
        method="GET",
        path=f"/admin/realms/{REALM}/groups",
    )
    matches = [
        row
        for row in groups
        if isinstance(row, dict) and (row.get("path") == "/ldap" or row.get("name") == "ldap")
    ]
    if len(matches) > 1:
        raise RuntimeError("duplicate Keycloak /ldap group roots")
    if matches and (matches[0].get("path") != "/ldap" or matches[0].get("name") != "ldap"):
        raise RuntimeError("conflicting Keycloak ldap root group")
    return matches[0] if matches else None


def ensure_ldap_group_root(namespace: str, pod: str) -> str:
    existing = ldap_group_root(namespace, pod)
    if existing is None:
        admin_request(
            namespace,
            pod,
            method="POST",
            path=f"/admin/realms/{REALM}/groups",
            payload={"name": "ldap"},
        )
        existing = ldap_group_root(namespace, pod)
    group_id = str((existing or {}).get("id") or "")
    if not group_id:
        raise RuntimeError("Keycloak /ldap group root verification failed")
    return group_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="nomosmart")
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    person_name_action = parser.add_mutually_exclusive_group()
    person_name_action.add_argument("--person-name-mapper-preflight", action="store_true")
    person_name_action.add_argument("--reconcile-person-name-mapper", action="store_true")
    person_name_action.add_argument("--trigger-person-name-full-sync", action="store_true")
    person_name_action.add_argument("--person-name-user-readback", action="store_true")
    args = parser.parse_args()

    context = run(["kubectl", "config", "current-context"]).strip()
    if context != "docker-desktop":
        raise RuntimeError(f"unexpected Kubernetes context: {context}")
    pod = backend_pod(args.namespace)
    existing_ldap_root = ldap_group_root(args.namespace, pod)
    matching = [
        row
        for row in components(args.namespace, pod)
        if row.get("name") == PROVIDER_NAME and row.get("providerId") == "ldap"
    ]
    if args.person_name_mapper_preflight or args.reconcile_person_name_mapper or args.trigger_person_name_full_sync or args.person_name_user_readback:
        if len(matching) != 1:
            raise RuntimeError("exactly one openldap-local-test provider is required")
        provider_id = str(matching[0].get("id") or "")
        if not provider_id:
            raise RuntimeError("openldap-local-test provider has no id")
        if args.person_name_mapper_preflight:
            state = person_name_mapper_plan(components(args.namespace, pod, parent=provider_id))
            output = {
                "context": context,
                "provider_id": provider_id,
                "first_mapper_id": state["first_mapper_id"],
                "first_ldap_attribute": state["first_ldap_attribute"],
                "last_mapper_id": state["last_mapper_id"],
                "last_ldap_attribute": state["last_ldap_attribute"],
                "requires_change": state["requires_change"],
            }
        elif args.person_name_user_readback:
            output = {
                "context": context,
                "provider_id": provider_id,
                "users": person_name_user_readback(args.namespace, pod, provider_id),
            }
        else:
            if args.evidence_file is None:
                raise RuntimeError("--evidence-file is required for person-name mapper mutation or sync")
            if args.reconcile_person_name_mapper:
                output = reconcile_person_name_mapper(args.namespace, pod, provider_id)
                output["action"] = "mapper_reconciled"
            else:
                output = {
                    "action": "keycloak_full_user_sync",
                    "provider_id": provider_id,
                    "full_sync": trigger_person_name_full_sync(args.namespace, pod, provider_id),
                }
            output["context"] = context
            write_evidence(args.evidence_file, output)
        print(json.dumps(output, sort_keys=True))
        return 0
    if args.preflight_only:
        if matching:
            raise RuntimeError("openldap-local-test provider already exists")
        print(
            json.dumps(
                {
                    "context": context,
                    "provider_absent": True,
                    "ldap_group_root": "present" if existing_ldap_root else "will-create",
                }
            )
        )
        return 0
    if args.evidence_file is None:
        raise RuntimeError("--evidence-file is required unless --preflight-only is used")
    ldap_group_root_id = ensure_ldap_group_root(args.namespace, pod)
    password = bind_credential(args.namespace)
    parent_id = realm_id(args.namespace, pod)

    provider_id = upsert_component(
        args.namespace,
        pod,
        provider_payload(password, parent_id),
    )
    group_mapper_id = upsert_component(
        args.namespace,
        pod,
        group_mapper_payload(provider_id),
        parent=provider_id,
    )
    attribute_mappers = {}
    for name, ldap_attribute, keycloak_attribute in (
        ("ldap-dn", "entryDN", "ldap_dn"),
        ("manager", "manager", "manager"),
        ("employee-id", "employeeNumber", "employee_id"),
        ("department", "departmentNumber", "department"),
        ("title", "title", "title"),
    ):
        attribute_mappers[name] = upsert_component(
            args.namespace,
            pod,
            attribute_mapper_payload(
                provider_id,
                name=name,
                ldap_attribute=ldap_attribute,
                keycloak_attribute=keycloak_attribute,
            ),
            parent=provider_id,
        )

    sync = admin_request(
        args.namespace,
        pod,
        method="POST",
        path=f"/admin/realms/{REALM}/user-storage/{provider_id}/sync",
        params={"action": "triggerFullSync"},
    )
    if int(sync.get("failed", 0)) != 0:
        raise RuntimeError("Keycloak LDAP user full sync reported failures")
    admin_request(
        args.namespace,
        pod,
        method="POST",
        path=(
            f"/admin/realms/{REALM}/user-storage/{provider_id}/mappers/"
            f"{group_mapper_id}/sync"
        ),
        params={"direction": "fedToKeycloak"},
    )

    provider_rows = [
        row
        for row in components(args.namespace, pod)
        if row.get("id") == provider_id
    ]
    if len(provider_rows) != 1:
        raise RuntimeError("Keycloak LDAP provider post-sync verification failed")
    provider_config = provider_rows[0].get("config") or {}
    if not isinstance(provider_config, dict):
        raise RuntimeError("Keycloak LDAP provider config is invalid")
    for key, expected in EXPECTED_SAFE_PROVIDER_CONFIG.items():
        if provider_config.get(key) != expected:
            raise RuntimeError(f"Keycloak LDAP provider security drift: {key}")
    provider_mappers = components(args.namespace, pod, parent=provider_id)
    if any(row.get("providerId") == "role-ldap-mapper" for row in provider_mappers):
        raise RuntimeError("unexpected Keycloak LDAP role mapper")

    users = {}
    user_evidence = {}
    for username in EXPECTED_USERS:
        rows = admin_request(
            args.namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users",
            params={"username": username, "exact": "true"},
        )
        matches = [row for row in rows if row.get("username") == username]
        if len(matches) != 1 or matches[0].get("federationLink") != provider_id:
            raise RuntimeError(f"federated Keycloak user verification failed: {username}")
        user_id = str(matches[0].get("id") or "")
        if not user_id:
            raise RuntimeError(f"federated Keycloak user has no id: {username}")
        detail = admin_request(
            args.namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users/{user_id}",
        )
        attributes = detail.get("attributes") or {}
        if not isinstance(attributes, dict):
            raise RuntimeError(f"Keycloak user attributes are invalid: {username}")
        expected_attributes = EXPECTED_CHG265_ATTRIBUTES.get(username, {})
        for key, expected in expected_attributes.items():
            if attributes.get(key) != expected:
                raise RuntimeError(
                    f"federated Keycloak attribute verification failed: {username} {key}"
                )
        group_rows = admin_request(
            args.namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users/{user_id}/groups",
        )
        group_paths = sorted(
            str(row.get("path")) for row in group_rows if isinstance(row, dict)
        )
        if group_paths != sorted(EXPECTED_GROUP_PATHS[username]):
            raise RuntimeError(f"federated Keycloak group verification failed: {username}")
        role_rows = admin_request(
            args.namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/users/{user_id}/role-mappings",
        )
        direct_realm_roles = sorted(
            str(row.get("name"))
            for row in role_rows.get("realmMappings", [])
            if isinstance(row, dict)
        )
        if any(role != "default-roles-nomosmart" for role in direct_realm_roles):
            raise RuntimeError(f"unexpected direct Keycloak realm role: {username}")
        if role_rows.get("clientMappings"):
            raise RuntimeError(f"unexpected direct Keycloak client role: {username}")
        users[username] = user_id
        user_evidence[username] = {
            "attributes": {
                key: attributes[key]
                for key in expected_attributes
            },
            "group_paths": group_paths,
            "direct_realm_roles": direct_realm_roles,
        }

    group_rows = admin_request(
        args.namespace,
        pod,
        method="GET",
        path=f"/admin/realms/{REALM}/groups/{ldap_group_root_id}/children",
        params={"max": "100"},
    )
    expected_group_names = {
        "nomosmart-testers",
        "nomosmart-reviewers",
        "nomosmart-admin",
        "HR",
        "IT",
        "FIN",
    }
    groups = {
        str(row.get("name")): {
            "id": str(row.get("id") or ""),
            "path": str(row.get("path") or ""),
        }
        for row in group_rows
        if isinstance(row, dict) and row.get("name") in expected_group_names
    }
    if set(groups) != expected_group_names:
        raise RuntimeError("federated Keycloak group set verification failed")
    if any(row["path"] != f"/ldap/{name}" for name, row in groups.items()):
        raise RuntimeError("federated Keycloak group path verification failed")
    for name, group in groups.items():
        role_rows = admin_request(
            args.namespace,
            pod,
            method="GET",
            path=f"/admin/realms/{REALM}/groups/{group['id']}/role-mappings",
        )
        direct_realm_roles = sorted(
            str(row.get("name"))
            for row in role_rows.get("realmMappings", [])
            if isinstance(row, dict)
        )
        direct_client_roles = role_rows.get("clientMappings") or {}
        if direct_realm_roles or direct_client_roles:
            raise RuntimeError(f"unexpected direct Keycloak group role: {name}")
        group["direct_realm_roles"] = direct_realm_roles
        group["direct_client_roles"] = direct_client_roles

    evidence = {
        "context": context,
        "namespace": args.namespace,
        "provider_id": provider_id,
        "provider_name": PROVIDER_NAME,
        "ldap_group_root_id": ldap_group_root_id,
        "group_mapper_id": group_mapper_id,
        "group_mapper_name": GROUP_MAPPER_NAME,
        "attribute_mapper_ids": attribute_mappers,
        "user_ids": users,
        "users": user_evidence,
        "groups": groups,
        "provider_security_config": EXPECTED_SAFE_PROVIDER_CONFIG,
        "full_sync": {
            key: int(sync.get(key, 0))
            for key in ("added", "updated", "removed", "failed", "ignored")
        },
    }
    write_evidence(args.evidence_file, evidence)
    print(
        json.dumps(
            {
                "provider_id": provider_id,
                "group_mapper_id": group_mapper_id,
                "federated_users": sorted(users),
                "federated_groups": sorted(groups),
                "full_sync": evidence["full_sync"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Local LDAP Keycloak reconciliation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "deploy" / "docker" / "ldap-test"
COMPOSE = STACK / "docker-compose.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chg264_compose_pins_images_and_keeps_directory_private() -> None:
    compose = yaml.safe_load(read(COMPOSE))
    services = compose["services"]
    ldap = services["openldap"]
    init = services["directory-init"]
    pla = services["phpldapadmin"]

    assert ldap["image"].endswith(
        "@sha256:e1f778655d02b96875352879e2168e4bc233153b338ce40c4026812935b38dfa"
    )
    assert pla["image"].endswith(
        "@sha256:5ed66c77b792b0ad8a7d2e3de76681b4ea65ad4bf32bf4f14d7b42c58536c146"
    )
    assert "ports" not in ldap
    assert "ports" not in init
    assert pla["ports"] == [
        {
            "name": "http",
            "target": 8080,
            "published": "8080",
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
    ]
    assert set(ldap["networks"]) == {"ldap-private", "kind"}
    assert init["networks"] == ["ldap-private"]
    assert pla["networks"] == ["ldap-private", "pla-loopback"]
    assert ldap["networks"]["kind"]["ipv4_address"] == "172.19.0.20"
    assert compose["networks"]["ldap-private"]["internal"] is True
    assert compose["networks"]["pla-loopback"] == {
        "name": "nomosmart-ldap-test-loopback",
        "driver": "bridge",
    }
    assert compose["networks"]["kind"] == {"external": True, "name": "kind"}


def test_chg264_compose_enforces_ldaps_and_external_secret_files() -> None:
    compose = yaml.safe_load(read(COMPOSE))
    ldap = compose["services"]["openldap"]
    pla = compose["services"]["phpldapadmin"]

    assert ldap["environment"]["ENABLE_TLS"] == "TRUE"
    assert ldap["environment"]["TLS_ENFORCE"] == "TRUE"
    assert ldap["environment"]["TLS_CREATE_SELFSIGNED"] == "FALSE"
    assert pla["environment"]["LDAP_CONNECTION"] == "ldaps"
    assert pla["environment"]["LDAP_PORT"] == "636"
    assert pla["environment"]["LDAP_ALLOW_GUEST"] == "false"
    assert "LDAP_USERNAME" not in pla["environment"]
    assert "LDAP_PASSWORD" not in pla["environment"]
    assert 'LDAP_PASSWORD="$$(tr -d' in pla["command"][0]
    assert "/run/secrets/ldap-bind-password" in pla["command"][0]
    assert "cn=nomosmart-bind,dc=nomosmart,dc=test" in pla["command"][0]
    assert {row["source"] for row in pla["secrets"]} == {
        "ldap_ca_cert",
        "ldap_bind_password",
    }

    secret_files = {row["file"] for row in compose["secrets"].values()}
    assert secret_files == {
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/secrets/ldap-admin-password",
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/secrets/ldap-config-password",
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/secrets/ldap-bind-password",
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/tls/ca.crt",
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/tls/server.crt",
        "${LDAP_RUNTIME_DIR:?Set LDAP_RUNTIME_DIR}/tls/server.key",
    }
    trust = read(STACK / "phpldapadmin-ldap.conf")
    assert "TLS_CACERT /run/secrets/nomosmart-directory-ca.crt" in trust
    assert "TLS_REQCERT demand" in trust


def test_chg264_seed_is_synthetic_read_only_and_non_anonymous() -> None:
    seed = read(STACK / "seed" / "10-nomosmart-seed.sh")
    assert "dc=nomosmart,dc=test" in seed
    assert seed.count("objectClass: inetOrgPerson") == 2
    assert "uid=ldap.alice" in seed
    assert "uid=ldap.bob" in seed
    assert "objectClass: groupOfNames" in seed
    assert "cn=nomosmart-bind" in seed
    assert "employeeNumber: Z000000001" in seed
    assert "employeeNumber: Z000000002" in seed
    assert "slappasswd -s 'P@ssw0rd'" in seed
    assert "by dn.exact=\"${bind_dn}\" read" in seed
    assert "by anonymous auth by * none" in seed
    assert 'ldap_url="ldaps://nomosmart-openldap:636"' in seed
    assert 'ldapadd -x -H "${ldap_url}"' in seed
    assert '-D cn=config -y "${config_secret_file}"' in seed
    assert "Anonymous LDAP search unexpectedly succeeded" in seed
    assert "-y \"${admin_secret_file}\"" in seed
    assert "-w " not in seed


def test_chg264_keycloak_reconciliation_is_read_only_without_role_mapping() -> None:
    source = read(STACK / "reconcile_keycloak.py")
    assert '"connectionUrl": ["ldaps://172.19.0.20:636"]' in source
    assert '"editMode": ["READ_ONLY"]' in source
    assert '"syncRegistrations": ["false"]' in source
    assert '"useTruststoreSpi": ["ldapsOnly"]' in source
    assert '"groups.path": ["/ldap"]' in source
    assert '"mode": ["READ_ONLY"]' in source
    assert '"ldap.attribute": [ldap_attribute]' in source
    assert '"always.read.value.from.ldap": ["true"]' in source
    assert '"parentId": parent_id' in source
    assert "parent_id = realm_id(args.namespace, pod)" in source
    assert 'payload={"name": "ldap"}' in source
    assert '"ldap_group_root": "present" if existing_ldap_root else "will-create"' in source
    assert "system-admin" not in source
    assert "bind-password" in source
    assert "print(password" not in source


def test_chg264_runbook_has_non_destructive_lifecycle_boundary() -> None:
    readme = read(STACK / "README.md")
    assert "127.0.0.1:8080" in readme
    assert "ldaps://172.19.0.20:636" in readme
    assert "P@ssw0rd" in readme
    assert "application_access_denied" in readme
    assert "停止 stack 不刪除 named volumes" in readme
    assert "永久清除須另行盤點與批准" in readme


def test_chg265_compose_runs_both_seed_generations_in_order() -> None:
    compose = yaml.safe_load(read(COMPOSE))
    init = compose["services"]["directory-init"]

    assert init["entrypoint"] == ["/bin/bash", "-ec"]
    assert init["command"] == [
        "/bin/bash /seed/10-nomosmart-seed.sh && "
        "/bin/bash /seed/20-chg265-directory-data.sh"
    ]
    assert init["volumes"] == [
        "./seed/10-nomosmart-seed.sh:/seed/10-nomosmart-seed.sh:ro",
        "./seed/20-chg265-directory-data.sh:/seed/20-chg265-directory-data.sh:ro",
    ]


def test_chg265_seed_defines_exact_users_managers_and_groups() -> None:
    seed = read(STACK / "seed" / "20-chg265-directory-data.sh")
    user_contracts = (
        'user01 Chu Peter "Peter Chu" Z000000101 HR ""',
        'user02 Wu Justin "Justin Wu" Z000000102 HR "${user01_dn}"',
        'user03 Lee Jerry "Jerry Lee" Z000000103 IT ""',
        'user04 Lu Paggy "Paggy Lu" Z000000104 FIN ""',
        'user05 Liu Jam "Jam Liu" Z000000105 IT "${user03_dn}"',
    )
    for contract in user_contracts:
        assert f"preflight_user {contract}" in seed
        assert f"ensure_user {contract}" in seed

    assert 'user01_dn="uid=user01,${users_dn}"' in seed
    assert 'user02_dn="uid=user02,${users_dn}"' in seed
    assert 'user03_dn="uid=user03,${users_dn}"' in seed
    assert 'user04_dn="uid=user04,${users_dn}"' in seed
    assert 'user05_dn="uid=user05,${users_dn}"' in seed
    assert "mail: ${uid}@nomosmart.test" in seed
    assert "employeeNumber: ${employee_number}" in seed
    assert "departmentNumber: ${department}" in seed
    assert "manager: %s" in seed

    group_contracts = (
        'preflight_group HR "${user01_dn}" "${user02_dn}"',
        'preflight_group IT "${user03_dn}" "${user05_dn}"',
        'preflight_group FIN "${user04_dn}"',
        'preflight_group nomosmart-admin "${user01_dn}"',
        'ensure_group HR "Synthetic NomoSmart HR test group"',
        'ensure_group IT "Synthetic NomoSmart IT test group"',
        'ensure_group FIN "Synthetic NomoSmart FIN test group"',
        "ensure_group nomosmart-admin",
    )
    for contract in group_contracts:
        assert contract in seed
    assert "objectClass: groupOfNames" in seed
    assert "member: %s" in seed


def test_chg265_seed_is_fail_closed_idempotent_and_non_destructive() -> None:
    seed = read(STACK / "seed" / "20-chg265-directory-data.sh")

    assert seed.count("P@ssw0rd") == 1
    assert 'slappasswd -T "${user_password_file}"' in seed
    assert 'ldap_url="ldaps://nomosmart-openldap:636"' in seed
    assert 'export LDAPTLS_REQCERT=demand' in seed
    assert '-y "${admin_secret_file}"' in seed
    assert '-y "${bind_secret_file}"' in seed
    assert " -w " not in seed
    assert "ldapdelete" not in seed
    assert "ldapmodrdn" not in seed
    assert "ldapmodify" not in seed
    assert "userPassword" not in seed.partition("ensure_user() {")[0]

    last_preflight = seed.index('preflight_group nomosmart-admin "${user01_dn}"')
    first_write_phase = seed.index("ensure_user user01")
    assert last_preflight < first_write_phase
    assert 'if entry_exists "${dn}"; then\n        verify_user' in seed
    assert 'if ! entry_exists "${dn}"; then' in seed
    assert "Conflicting LDAP entry attribute" in seed
    assert "Conflicting LDAP group membership" in seed


def test_chg265_keycloak_sync_verifies_users_groups_attributes_and_no_roles() -> None:
    source = read(STACK / "reconcile_keycloak.py")

    for username in (
        "ldap.alice",
        "ldap.bob",
        "user01",
        "user02",
        "user03",
        "user04",
        "user05",
    ):
        assert f'"{username}"' in source
    for group_path in (
        "/ldap/nomosmart-testers",
        "/ldap/nomosmart-reviewers",
        "/ldap/nomosmart-admin",
        "/ldap/HR",
        "/ldap/IT",
        "/ldap/FIN",
    ):
        assert f'"{group_path}"' in source

    assert '"manager": ["uid=user01,ou=users,dc=nomosmart,dc=test"]' in source
    assert '"manager": ["uid=user03,ou=users,dc=nomosmart,dc=test"]' in source
    assert 'params={"action": "triggerFullSync"}' in source
    assert 'params={"direction": "fedToKeycloak"}' in source
    assert 'method="GET",\n            path=f"/admin/realms/{REALM}/users/{user_id}/role-mappings"' in source
    assert 'path=f"/admin/realms/{REALM}/groups/{group[\'id\']}/role-mappings"' in source
    assert "unexpected direct Keycloak realm role" in source
    assert "unexpected direct Keycloak client role" in source
    assert "unexpected direct Keycloak group role" in source
    assert 'row.get("providerId") == "role-ldap-mapper"' in source
    assert '"editMode": ["READ_ONLY"]' in source
    assert '"useTruststoreSpi": ["ldapsOnly"]' in source
    assert 'method="POST",\n            path=f"/admin/realms/{REALM}/users/{user_id}/role-mappings"' not in source
    assert "external_group_role_mappings" not in source
    assert "identity_sync_runs" not in source


def test_chg265_runbook_documents_synthetic_directory_scope() -> None:
    readme = read(STACK / "README.md")

    assert "七個\n  synthetic users" in readme
    assert "`uid=user01,ou=users,dc=nomosmart,dc=test` 至" in readme
    assert "`uid=user05,ou=users,dc=nomosmart,dc=test`" in readme
    assert "`HR` (user01/user02)" in readme
    assert "`IT` (user03/user05)" in readme
    assert "`FIN`\n(user04)" in readme
    assert "`nomosmart-admin` (user01)" in readme
    assert "沒有 Keycloak 或\nNomoSmart role mapping" in readme

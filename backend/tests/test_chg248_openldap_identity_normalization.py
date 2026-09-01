import unittest

from app.deployment.onboarding_status import OnboardingStatusSettings
from app.integrations.keycloak import KeycloakSnapshot
from app.services.identity_sync import normalize_snapshot


def _snapshot(user: dict[str, object]) -> KeycloakSnapshot:
    return KeycloakSnapshot(
        users=(user,),
        groups=(),
        user_group_ids={str(user["id"]): frozenset()},
    )


class OpenLDAPIdentityNormalizationTest(unittest.TestCase):
    def test_onboarding_probe_does_not_require_one_time_bootstrap_secrets(
        self,
    ) -> None:
        settings = OnboardingStatusSettings(
            _env_file=None,
            deployment_finalization_admin_username="user01",
            deployment_finalization_admin_group="nomosmart-uat-admins",
        )

        self.assertEqual(
            settings.deployment_finalization_admin_username,
            "user01",
        )
        self.assertNotIn(
            "break_glass_initial_password",
            OnboardingStatusSettings.model_fields,
        )
        self.assertNotIn(
            "keycloak_bootstrap_admin_password",
            OnboardingStatusSettings.model_fields,
        )

    def test_keycloak_builtin_ldap_entry_dn_is_normalized(self) -> None:
        users, groups = normalize_snapshot(
            _snapshot(
                {
                    "id": "openldap-user-01",
                    "username": "user01",
                    "enabled": True,
                    "federationLink": "openldap-provider",
                    "attributes": {
                        "LDAP_ENTRY_DN": [
                            "cn=user01,ou=users,dc=ldap,dc=example,dc=com"
                        ]
                    },
                }
            )
        )

        self.assertEqual(groups, [])
        self.assertEqual(
            users[0].ldap_dn,
            "cn=user01,ou=users,dc=ldap,dc=example,dc=com",
        )
        self.assertEqual(users[0].auth_source, "ldap")

    def test_explicit_ldap_dn_alias_takes_precedence(self) -> None:
        users, _groups = normalize_snapshot(
            _snapshot(
                {
                    "id": "directory-user-02",
                    "username": "user02",
                    "enabled": True,
                    "federationLink": "directory-provider",
                    "attributes": {
                        "ldap_dn": ["uid=user02,dc=explicit,dc=example"],
                        "LDAP_ENTRY_DN": [
                            "uid=user02,dc=builtin,dc=example"
                        ],
                    },
                }
            )
        )

        self.assertEqual(
            users[0].ldap_dn,
            "uid=user02,dc=explicit,dc=example",
        )
        self.assertEqual(users[0].auth_source, "ldap")

    def test_federation_link_preserves_ldap_origin_without_dn_attribute(
        self,
    ) -> None:
        users, _groups = normalize_snapshot(
            _snapshot(
                {
                    "id": "directory-user-03",
                    "username": "user03",
                    "enabled": True,
                    "federationLink": "directory-provider",
                    "attributes": {},
                }
            )
        )

        self.assertIsNone(users[0].ldap_dn)
        self.assertEqual(users[0].auth_source, "ldap")

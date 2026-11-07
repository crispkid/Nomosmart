import unittest

from app.deployment.onboarding_status import OnboardingStatusSettings


class OpenLDAPIdentityNormalizationTest(unittest.TestCase):
    def test_onboarding_probe_does_not_require_one_time_bootstrap_secrets(
        self,
    ) -> None:
        settings = OnboardingStatusSettings(
            _env_file=None,
            auth_emergency_username="maintenance-admin",
        )

        self.assertEqual(
            settings.auth_emergency_username,
            "maintenance-admin",
        )
        self.assertNotIn(
            "break_glass_initial_password",
            OnboardingStatusSettings.model_fields,
        )
        self.assertNotIn(
            "keycloak_bootstrap_admin_password",
            OnboardingStatusSettings.model_fields,
        )





from current_live_support import current_live  # noqa: F401
from current_directory_support import current_directory_snapshot


def test_direct_directory_dn_and_origin_are_authoritative(current_live):
    snapshot = current_directory_snapshot(current_live)
    assert snapshot.schema_type in {"ldap", "ad"} and snapshot.people
    assert all(person.dn and person.object_id and person.username for person in snapshot.people)
    assert len({person.object_id for person in snapshot.people}) == len(snapshot.people)

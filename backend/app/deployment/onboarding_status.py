from __future__ import annotations

import json
import sys

from app.deployment.bootstrap import (
    BootstrapFailure,
    _realm_name,
    _verify_finalization_database_evidence,
)
from app.core.config import Settings
from app.integrations.keycloak import KeycloakAdminClient


class OnboardingStatusSettings(Settings):
    deployment_finalization_admin_username: str = ""
    deployment_finalization_admin_group: str = ""


def verify_onboarding_status(
    settings: OnboardingStatusSettings,
    *,
    allow_disabled_break_glass: bool = False,
) -> dict[str, object]:
    if settings.app_env != "production":
        raise BootstrapFailure("onboarding_status_requires_production")
    client = KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    break_glass_id = client.verify_break_glass_onboarding_complete(
        settings.break_glass_username,
        system_admin_group=settings.break_glass_system_admin_group,
        allow_disabled=allow_disabled_break_glass,
    )
    federated_id = client.verify_federated_admin_onboarding_complete(
        settings.deployment_finalization_admin_username,
        external_group=settings.deployment_finalization_admin_group,
    )
    _verify_finalization_database_evidence(
        settings,
        break_glass_keycloak_user_id=break_glass_id,
        federated_admin_keycloak_user_id=federated_id,
    )
    return {
        "status": "ready",
        "break_glass": "first_use_complete",
        "federated_administrator": "oidc_password_role_ready",
    }


def main() -> int:
    try:
        print(
            json.dumps(
                verify_onboarding_status(OnboardingStatusSettings()),
                sort_keys=True,
            )
        )
        return 0
    except BootstrapFailure as exc:
        print(
            json.dumps({"status": "action-required", "code": exc.code}),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "action-required",
                    "code": "onboarding_evidence_incomplete",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

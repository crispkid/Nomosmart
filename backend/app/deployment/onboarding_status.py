from __future__ import annotations
import json
from app.core.config import Settings
from app.deployment.bootstrap import BootstrapFailure, _protocol_onboarding_check

class OnboardingStatusSettings(Settings):
    pass

def verify_onboarding_status(settings, *, allow_disabled_break_glass=False):
    _protocol_onboarding_check(settings)
    return {"status": "ready", "authentication": "normal_administrator_verified", "emergency": "deployment_only"}

def main():
    try:
        print(json.dumps(verify_onboarding_status(OnboardingStatusSettings())))
        return 0
    except BootstrapFailure as exc:
        print(json.dumps({"status": "action-required", "code": exc.code}))
        return 1
if __name__ == "__main__":
    raise SystemExit(main())

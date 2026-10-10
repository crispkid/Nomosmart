"""Read-only OCR call state; durable intent is normal during a valid claim."""
from datetime import UTC, datetime


def ocr_call_state(*, has_intent: bool, step_status: str, pipeline_status: str | None,
                   claim_token: object, lease_expires_at: datetime | None,
                   now: datetime | None = None) -> str:
    if not has_intent:
        return "idle"
    now = now or datetime.now(UTC)
    lease = lease_expires_at
    if lease is not None and lease.tzinfo is None:
        lease = lease.replace(tzinfo=UTC)
    if (step_status == "running" and pipeline_status == "running" and claim_token
            and lease is not None and lease > now):
        return "in_flight"
    return "unconfirmed"

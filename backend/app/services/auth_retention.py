"""Remove expired temporary auth material without an absolute session lifetime."""
from datetime import UTC, datetime, timedelta
from sqlalchemy import delete, exists, or_, select
from app.db.models import AuthAttemptWindow, AuthCandidateEvidence, AuthLoginFlow, AuthSession, IdentityUnlockGrant


def cleanup_authentication(session) -> dict[str, int]:
    cutoff = datetime.now(UTC) - timedelta(days=1)
    removed = {}
    for model, predicate in (
        (AuthLoginFlow, AuthLoginFlow.expires_at < cutoff),
        (AuthCandidateEvidence, AuthCandidateEvidence.expires_at < cutoff),
        (IdentityUnlockGrant, IdentityUnlockGrant.expires_at < cutoff),
        (AuthAttemptWindow, AuthAttemptWindow.started_at < cutoff),
    ):
        removed[model.__tablename__] = session.execute(delete(model).where(predicate)).rowcount
    # An active session can be arbitrarily old. Only last activity/revocation
    # controls eligibility, and live one-time evidence always keeps its parent.
    removed["auth_sessions"] = session.execute(delete(AuthSession).where(or_(AuthSession.last_activity_at < cutoff, AuthSession.revoked_at < cutoff), ~exists(select(AuthLoginFlow.id).where(AuthLoginFlow.initiating_session_id == AuthSession.id)), ~exists(select(AuthCandidateEvidence.id).where(AuthCandidateEvidence.session_id == AuthSession.id)))).rowcount
    return removed

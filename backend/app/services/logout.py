from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import IdentityUnlockGrant, RevokedAuthToken, User
from app.security.auth import IdentityPrincipal, token_digest, token_identity
from app.services.audit import add_audit


def revoke_login_session(
    session: Session,
    *,
    principal: IdentityPrincipal,
    token: str,
    request_id: str | None,
    now: datetime | None = None,
) -> RevokedAuthToken:
    timestamp = now or datetime.now(UTC)
    identity = token_identity(principal, token)
    digest = token_digest(token)
    user = session.scalar(select(User).where(User.keycloak_user_id == principal.subject))
    existing = session.scalar(select(RevokedAuthToken).where(RevokedAuthToken.token_identity == identity))
    if existing is None:
        existing = RevokedAuthToken(
            token_identity=identity,
            token_digest=digest,
            issuer=principal.issuer,
            subject=principal.subject,
            audience=principal.audience,
            token_id=principal.token_id,
            session_id=principal.session_id,
            issued_at=principal.issued_at,
            expires_at=principal.expires_at,
            revoked_at=timestamp,
            revoked_by=user.id if user else None,
            reason="user_logout",
            metadata_json={"source": "auth.logout", "has_jti": bool(principal.token_id)},
        )
        session.add(existing)

    revoked_grants = 0
    if user and principal.session_id:
        result = session.execute(
            update(IdentityUnlockGrant)
            .where(
                IdentityUnlockGrant.user_id == user.id,
                IdentityUnlockGrant.session_id == principal.session_id,
                IdentityUnlockGrant.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
        revoked_grants = int(result.rowcount or 0)

    add_audit(
        session,
        actor_user_id=user.id if user else None,
        action="auth.logout",
        resource_type="auth_session",
        resource_id=None,
        result="success",
        request_id=request_id,
        summary={
            "subject": principal.subject,
            "session_id_present": bool(principal.session_id),
            "revoked_grants": revoked_grants,
            "token_expires_at": principal.expires_at.isoformat(),
            "token_identity_prefix": identity[:12],
        },
    )
    return existing

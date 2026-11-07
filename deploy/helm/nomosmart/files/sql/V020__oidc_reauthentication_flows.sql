CREATE TABLE identity_reauth_flows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    subject varchar(255) NOT NULL,
    session_id varchar(255) NOT NULL,
    scope varchar(100) NOT NULL,
    state_digest varchar(64) NOT NULL UNIQUE,
    nonce_digest varchar(64) NOT NULL,
    pkce_verifier_encrypted text NOT NULL,
    issuer_url varchar(500) NOT NULL,
    jwks_url varchar(500) NOT NULL,
    client_id varchar(255) NOT NULL,
    redirect_uri varchar(1000) NOT NULL,
    return_path varchar(1000) NOT NULL,
    completion_token_digest varchar(64) UNIQUE,
    authenticated_subject varchar(255),
    authenticated_session_id varchar(255),
    authenticated_auth_time timestamptz,
    expires_at timestamptz NOT NULL,
    authenticated_at timestamptz,
    consumed_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_identity_reauth_flows_expires_at
    ON identity_reauth_flows (expires_at);

CREATE INDEX ix_identity_reauth_flows_user_session_scope
    ON identity_reauth_flows (user_id, session_id, scope);

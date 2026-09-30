CREATE TABLE revoked_auth_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_identity varchar(64) NOT NULL UNIQUE,
    token_digest varchar(64) NOT NULL,
    issuer varchar(500) NOT NULL,
    subject varchar(255) NOT NULL,
    audience varchar(500) NOT NULL,
    token_id varchar(255),
    session_id varchar(255),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz NOT NULL,
    revoked_by uuid REFERENCES users(id),
    reason varchar(64) NOT NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX ix_revoked_auth_tokens_expires_at ON revoked_auth_tokens(expires_at);
CREATE INDEX ix_revoked_auth_tokens_subject_session ON revoked_auth_tokens(subject, session_id);

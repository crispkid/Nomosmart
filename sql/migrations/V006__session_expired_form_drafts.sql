CREATE TABLE session_expired_form_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    form_key varchar(120) NOT NULL,
    return_path text NOT NULL,
    nonce_hash varchar(64) NOT NULL,
    payload_encrypted text NOT NULL,
    field_count integer NOT NULL DEFAULT 0,
    status varchar(32) NOT NULL DEFAULT 'pending',
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    restored_at timestamptz,
    discarded_at timestamptz
);
CREATE INDEX ix_session_expired_form_drafts_user_status ON session_expired_form_drafts(user_id, status);
CREATE INDEX ix_session_expired_form_drafts_expires_at ON session_expired_form_drafts(expires_at);

INSERT INTO system_parameters (key, value, default_value, value_type, unit, description)
VALUES ('session_expired_form_draft_ttl_minutes', '30'::jsonb, '30'::jsonb, 'integer', 'minutes', 'Retention for encrypted session-expired form drafts')
ON CONFLICT (key) DO NOTHING;

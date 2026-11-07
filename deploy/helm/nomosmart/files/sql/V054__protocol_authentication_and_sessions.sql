-- CHG-363 / PROTAUTH-001..012: additive coordinated authentication migration.
ALTER TABLE identity_settings DROP CONSTRAINT identity_settings_state_check;
ALTER TABLE identity_settings ADD CONSTRAINT identity_settings_state_check CHECK (state IN ('draft_unvalidated','validated_active_locked','temporarily_unlocked','validated_candidate','validated_candidate_requires_login'));
CREATE TABLE directory_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(255) NOT NULL,
    schema varchar(16) NOT NULL CHECK (schema IN ('ldap','ad')),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE identity_settings ADD COLUMN session_revision integer;
ALTER TABLE identity_settings ADD COLUMN base_revision integer;
ALTER TABLE identity_sync_runs ADD COLUMN configuration_revision integer;
ALTER TABLE users ALTER COLUMN keycloak_user_id DROP NOT NULL;
ALTER TABLE users ADD COLUMN directory_source_id uuid REFERENCES directory_sources(id);
ALTER TABLE users ADD COLUMN directory_object_id varchar(255);
ALTER TABLE users ADD COLUMN directory_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN locally_disabled boolean NOT NULL DEFAULT false;
-- Existing inactive records must never be silently enabled by a new directory sync.
UPDATE users SET locally_disabled = NOT is_active;
CREATE UNIQUE INDEX users_directory_object_unique ON users(directory_source_id,directory_object_id)
    WHERE directory_source_id IS NOT NULL AND directory_object_id IS NOT NULL;
ALTER TABLE external_groups ADD COLUMN directory_source_id uuid REFERENCES directory_sources(id);
CREATE TABLE authentication_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES directory_sources(id),
    issuer text NOT NULL, subject varchar(255) NOT NULL, user_id uuid NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(source_id,issuer,subject)
);
CREATE INDEX authentication_identities_user ON authentication_identities(user_id);
CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), secret_digest varchar(64) NOT NULL UNIQUE,
    csrf_digest varchar(64) NOT NULL, user_id uuid NOT NULL REFERENCES users(id),
    login_method varchar(16) NOT NULL CHECK(login_method IN ('oidc','ldap','emergency')),
    config_revision integer NOT NULL, authenticated_at timestamptz NOT NULL,
    last_activity_at timestamptz NOT NULL, revoked_at timestamptz,
    emergency_expires_at timestamptz, upstream_ciphertext text, upstream_key_id varchar(80)
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX auth_sessions_activity ON auth_sessions(last_activity_at);
CREATE TABLE auth_login_flows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), state_digest varchar(64) NOT NULL UNIQUE,
    nonce_digest varchar(64) NOT NULL, verifier_ciphertext text NOT NULL, key_id varchar(80) NOT NULL,
    setting_id uuid NOT NULL REFERENCES identity_settings(id), purpose varchar(16) NOT NULL,
    initiating_session_id uuid REFERENCES auth_sessions(id), user_id uuid REFERENCES users(id),
    return_path text NOT NULL, created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL, consumed_at timestamptz
);
CREATE INDEX auth_login_flows_expiry ON auth_login_flows(expires_at);
CREATE TABLE auth_connection_secrets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), setting_id uuid NOT NULL REFERENCES identity_settings(id),
    source_id uuid NOT NULL REFERENCES directory_sources(id), purpose varchar(32) NOT NULL,
    context_revision integer NOT NULL, key_id varchar(80) NOT NULL, envelope text NOT NULL,
    created_at timestamptz NOT NULL, UNIQUE(setting_id,purpose)
);
CREATE TABLE auth_candidate_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), setting_id uuid NOT NULL REFERENCES identity_settings(id),
    session_id uuid NOT NULL REFERENCES auth_sessions(id), user_id uuid NOT NULL REFERENCES users(id),
    candidate_digest varchar(64) NOT NULL, expires_at timestamptz NOT NULL, consumed_at timestamptz
);
CREATE INDEX auth_candidate_evidence_setting ON auth_candidate_evidence(setting_id);
CREATE TABLE auth_emergency_access (
    user_id uuid PRIMARY KEY REFERENCES users(id), username varchar(255) NOT NULL UNIQUE,
    password_verifier text, activated_at timestamptz, active_until timestamptz
);
CREATE TABLE auth_attempt_windows (
    key_digest varchar(64) PRIMARY KEY, started_at timestamptz NOT NULL,
    attempts integer NOT NULL CHECK(attempts >= 0)
);
CREATE UNIQUE INDEX identity_settings_one_current ON identity_settings((is_current)) WHERE is_current;
CREATE UNIQUE INDEX identity_settings_revision_unique ON identity_settings(revision);
-- Legacy JWT/flow state is intentionally not promoted to the new cookie session.
UPDATE identity_unlock_grants SET revoked_at=now() WHERE revoked_at IS NULL;

-- Fence legacy identity producers during a coordinated upgrade.
UPDATE identity_sync_runs SET status='failed', phase='failed', error_code='auth_contract_changed',
 error_message='Authentication contract changed; retry with the new worker', completed_at=now()
 WHERE status IN ('queued','running');
UPDATE outbox_events SET status='cancelled', last_error='auth_contract_changed', processed_at=now(),
 claim_token=NULL, claimed_at=NULL, lease_expires_at=NULL
 WHERE topic='identity.sync.requested' AND status IN ('pending','dispatching');
CREATE FUNCTION enforce_protocol_identity_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('queued','running','succeeded')
    AND EXISTS (SELECT 1 FROM identity_settings WHERE is_current AND configuration->>'auth_contract_revision'='2')
    AND (NEW.configuration_revision IS NULL OR NEW.source NOT IN ('ldap','ad')) THEN
  RAISE EXCEPTION 'identity_sync_auth_contract_mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER identity_run_protocol_contract BEFORE INSERT OR UPDATE ON identity_sync_runs
 FOR EACH ROW EXECUTE FUNCTION enforce_protocol_identity_run();

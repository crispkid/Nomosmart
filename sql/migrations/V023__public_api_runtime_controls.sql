ALTER TABLE public_api_request_logs
    ADD COLUMN lifecycle_status varchar(32) NOT NULL DEFAULT 'answered',
    ADD COLUMN request_hash varchar(64),
    ADD COLUMN idempotency_key_hash varchar(64),
    ADD COLUMN end_user_identity_hash varchar(64),
    ADD COLUMN question_encrypted text,
    ADD COLUMN answer_encrypted text,
    ADD COLUMN citations_encrypted text,
    ADD COLUMN end_user_metadata_encrypted text,
    ADD COLUMN started_at timestamptz,
    ADD COLUMN completed_at timestamptz,
    ADD COLUMN cancelled_at timestamptz,
    ADD COLUMN content_expires_at timestamptz,
    ADD COLUMN retention_expires_at timestamptz,
    ADD COLUMN legal_hold boolean NOT NULL DEFAULT false,
    ADD COLUMN redacted_at timestamptz,
    ADD COLUMN deleted_at timestamptz;

UPDATE public_api_request_logs
SET started_at = created_at,
    completed_at = created_at,
    content_expires_at = created_at + interval '30 days',
    retention_expires_at = created_at + interval '365 days';

ALTER TABLE chat_feedback_events
    ADD COLUMN end_user_identity_hash varchar(64),
    ADD COLUMN end_user_metadata_encrypted text,
    ADD COLUMN idempotency_key_hash varchar(64);

CREATE INDEX ix_public_api_request_logs_lifecycle ON public_api_request_logs (lifecycle_status, created_at);
CREATE INDEX ix_public_api_request_logs_retention ON public_api_request_logs (legal_hold, content_expires_at, retention_expires_at);
CREATE INDEX ix_public_api_request_logs_idempotency ON public_api_request_logs (integration_client_id, idempotency_key_hash);
CREATE INDEX ix_chat_feedback_events_idempotency ON chat_feedback_events (integration_client_id, idempotency_key_hash);

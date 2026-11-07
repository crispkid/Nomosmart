BEGIN;

CREATE TABLE notification_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES projects(id),
    event_type varchar(100) NOT NULL,
    business_key varchar(255) NOT NULL,
    dedupe_key varchar(64) NOT NULL UNIQUE,
    recipient_user_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    terminal boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL DEFAULT 'queued',
    attempts integer NOT NULL DEFAULT 0,
    error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX ix_notification_events_status_created
    ON notification_events (status, created_at, id);

ALTER TABLE notifications
    ADD COLUMN source_event_id uuid REFERENCES notification_events(id),
    ADD COLUMN business_key varchar(255),
    ADD COLUMN resolved_reason varchar(100);

ALTER TABLE notifications
    ADD CONSTRAINT uq_notifications_source_event_recipient
    UNIQUE (source_event_id, recipient_user_id);

CREATE INDEX ix_notifications_business_recipient_open
    ON notifications (business_key, recipient_user_id, resolved_at);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg247.durable_notification_events',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-247', 'requirement_id', 'NOTIF-003'),
    now()
);

COMMIT;

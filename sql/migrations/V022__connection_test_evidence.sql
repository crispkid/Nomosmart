ALTER TABLE ai_models
    ADD COLUMN last_test_fingerprint varchar(64),
    ADD COLUMN last_test_latency_ms integer,
    ADD COLUMN last_test_detail_code varchar(100),
    ADD COLUMN last_test_actor_id uuid REFERENCES users(id);

ALTER TABLE data_connections
    ADD COLUMN last_test_status varchar(32),
    ADD COLUMN last_tested_at timestamptz,
    ADD COLUMN last_test_fingerprint varchar(64),
    ADD COLUMN last_test_latency_ms integer,
    ADD COLUMN last_test_detail_code varchar(100),
    ADD COLUMN last_test_actor_id uuid REFERENCES users(id);

CREATE INDEX ix_ai_models_last_test_status ON ai_models (last_test_status);
CREATE INDEX ix_data_connections_last_test_status ON data_connections (last_test_status);

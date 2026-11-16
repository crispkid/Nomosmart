-- CHG-435 MTURN435-010: multi-turn question answering context. Additive only.
-- chat_records (web chat test) and public_api_request_logs (public API) record the
-- previous answer a question continues from, how many earlier turns were sent to the
-- model, whether older turns were dropped, and the rewritten search question.
-- Existing rows keep their meaning: single-turn, no history, no rewrite.
-- previous_response_id uses ON DELETE SET NULL so a permanent purge of an earlier row
-- (project archive cleanup, retention) never blocks on a later turn.
-- Rollback: application 0.2.x ignores these columns; they can stay in place.

ALTER TABLE public.chat_records
    ADD COLUMN previous_response_id uuid REFERENCES public.chat_records(id) ON DELETE SET NULL,
    ADD COLUMN conversation_mode character varying(16) NOT NULL DEFAULT 'single',
    ADD COLUMN history_turns integer NOT NULL DEFAULT 0,
    ADD COLUMN history_truncated boolean NOT NULL DEFAULT false,
    ADD COLUMN rewritten_query text,
    ADD COLUMN rewrite_status character varying(16) NOT NULL DEFAULT 'not_needed',
    ADD CONSTRAINT chat_records_conversation_mode_check CHECK (conversation_mode IN ('single', 'multi')),
    ADD CONSTRAINT chat_records_history_turns_check CHECK (history_turns >= 0),
    ADD CONSTRAINT chat_records_rewrite_status_check CHECK (rewrite_status IN ('not_needed', 'rewritten', 'failed'));

CREATE INDEX chat_records_previous_response_idx
    ON public.chat_records (previous_response_id) WHERE previous_response_id IS NOT NULL;

ALTER TABLE public.public_api_request_logs
    ADD COLUMN previous_response_id uuid REFERENCES public.public_api_request_logs(id) ON DELETE SET NULL,
    ADD COLUMN history_turns integer NOT NULL DEFAULT 0,
    ADD COLUMN history_truncated boolean NOT NULL DEFAULT false,
    ADD COLUMN rewritten_query_encrypted text,
    ADD COLUMN rewrite_status character varying(16) NOT NULL DEFAULT 'not_needed',
    ADD CONSTRAINT public_api_request_logs_history_turns_check CHECK (history_turns >= 0),
    ADD CONSTRAINT public_api_request_logs_rewrite_status_check CHECK (rewrite_status IN ('not_needed', 'rewritten', 'failed'));

CREATE INDEX public_api_request_logs_previous_response_idx
    ON public.public_api_request_logs (previous_response_id) WHERE previous_response_id IS NOT NULL;

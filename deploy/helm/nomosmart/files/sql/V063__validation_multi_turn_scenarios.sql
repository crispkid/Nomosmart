-- CHG-436 MTVAL436-009: multi-turn scenarios in CSV validation. Additive only.
-- Rows sharing a conversation_key run in turn_index order as one multi-turn conversation.
-- Existing rows keep both columns NULL and stay single-turn.
-- Rollback: application 0.2.x ignores these columns; they can stay in place.

ALTER TABLE public.validation_run_items
    ADD COLUMN conversation_key character varying(100),
    ADD COLUMN turn_index integer,
    ADD CONSTRAINT validation_run_items_scenario_pair_check
        CHECK ((conversation_key IS NULL) = (turn_index IS NULL)),
    ADD CONSTRAINT validation_run_items_turn_index_check
        CHECK (turn_index IS NULL OR turn_index >= 1);

CREATE INDEX validation_run_items_scenario_idx
    ON public.validation_run_items (run_id, conversation_key, turn_index) WHERE conversation_key IS NOT NULL;

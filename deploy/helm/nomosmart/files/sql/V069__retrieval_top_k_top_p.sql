-- CHG-486 TOPKP486-001 / RERANK486-002..004 / RTRACE486-001: retrieval Top K / Top P with optional reranking.
-- Additive only: five question-answering settings rows, the per-project rerank switch (off) and nullable trace columns.
-- Existing rows, values and projects are unchanged; reranking stays off until both switches are turned on.
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description)
VALUES
 ('retrieval_top_k', '5'::jsonb, '5'::jsonb, 'integer', 'chunks', 'Maximum chunks sent to the answer model per retrieval'),
 ('retrieval_top_p', '1.0'::jsonb, '1.0'::jsonb, 'number', NULL, 'Cumulative rerank score share at which retrieval stops (applies only when reranking)'),
 ('retrieval_rerank_min_score', '0.0'::jsonb, '0.0'::jsonb, 'number', NULL, 'Chunks with a rerank score below this value are dropped; 0 keeps every chunk'),
 ('retrieval_rerank_enabled', 'false'::jsonb, 'false'::jsonb, 'boolean', NULL, 'Allow projects to rerank retrieved chunks with the selected rerank model'),
 ('retrieval_rerank_model_id', 'null'::jsonb, 'null'::jsonb, 'model_id', NULL, 'Rerank model used when reranking is enabled')
ON CONFLICT (key) DO NOTHING;

-- RERANK486-001: rerank models are a new AI model type.
ALTER TABLE public.ai_models DROP CONSTRAINT ai_models_model_type_check;
ALTER TABLE public.ai_models ADD CONSTRAINT ai_models_model_type_check
    CHECK (model_type IN ('OCR', 'Embedding', 'Chat', 'Judge', 'Reranker'));

ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS rerank_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE public.chat_records ADD COLUMN IF NOT EXISTS retrieval_trace jsonb;
ALTER TABLE public.validation_run_items ADD COLUMN IF NOT EXISTS retrieval_trace jsonb;

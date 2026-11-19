-- CHG-450 SUBQ450-004: sub-question splitting for published-scope answers (system settings section "question_answering").
-- Additive only: two settings rows; existing rows and values are unchanged.
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description)
VALUES
 ('subquestion_enabled', 'true'::jsonb, 'true'::jsonb, 'boolean', NULL, 'Split a multi-part published-scope question into sub-questions searched separately'),
 ('subquestion_max', '3'::jsonb, '3'::jsonb, 'integer', 'questions', 'Maximum sub-questions per question')
ON CONFLICT (key) DO NOTHING;

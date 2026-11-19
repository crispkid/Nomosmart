-- CHG-445 ROUTE445-004: question answering settings owned by the database (system settings section "question_answering").
-- Reference routing (ROUTE445-001/002) and reference expansion (REF442-006, formerly REFERENCE_EXPANSION_* env). Additive only.
ALTER TABLE public.system_parameter_section_revisions ALTER COLUMN section TYPE varchar(32);
ALTER TABLE public.system_parameter_section_revisions DROP CONSTRAINT system_parameter_section_revisions_section_check;
ALTER TABLE public.system_parameter_section_revisions ADD CONSTRAINT system_parameter_section_revisions_section_check
    CHECK (section IN ('general', 'documents', 'question_answering'));
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description)
VALUES
 ('reference_routing_enabled', 'true'::jsonb, 'true'::jsonb, 'boolean', NULL, 'Ask the Chat model whether a published-scope question asks about document references'),
 ('reference_routing_max_documents', '10'::jsonb, '10'::jsonb, 'integer', 'documents', 'Maximum documents added for a reference question'),
 ('reference_expansion_enabled', 'true'::jsonb, 'true'::jsonb, 'boolean', NULL, 'Add chunks of documents linked by references to published-scope answers'),
 ('reference_expansion_max_chunks', '3'::jsonb, '3'::jsonb, 'integer', 'chunks', 'Maximum chunks added by reference expansion')
ON CONFLICT (key) DO NOTHING;
INSERT INTO public.system_parameter_section_revisions (section) VALUES ('question_answering') ON CONFLICT DO NOTHING;

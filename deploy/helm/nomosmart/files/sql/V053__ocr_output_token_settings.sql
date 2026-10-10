BEGIN;
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description)
VALUES
 ('ocr_page_max_output_tokens', '10000'::jsonb, '10000'::jsonb, 'integer', 'output_tokens', 'Maximum OCR output tokens per physical PDF page'),
 ('ocr_document_max_tokens', '1000000'::jsonb, '1000000'::jsonb, 'integer', 'output_tokens', 'Maximum accumulated OCR output tokens per document')
ON CONFLICT (key) DO NOTHING;
COMMIT;

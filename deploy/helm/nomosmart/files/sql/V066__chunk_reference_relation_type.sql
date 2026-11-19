-- CHG-446 SUPER446-001: relation kind of a chunk reference: references (existing, default) or supersedes
-- (this document supersedes or repeals the target). Additive only; existing rows become references.
ALTER TABLE public.chunk_references ADD COLUMN relation_type varchar(16) NOT NULL DEFAULT 'references';
ALTER TABLE public.chunk_references ADD CONSTRAINT chunk_references_relation_type_check
    CHECK (relation_type IN ('references', 'supersedes'));
CREATE INDEX ix_chunk_references_relation_target ON public.chunk_references (project_id, relation_type, target_document_id)
    WHERE is_deleted = false;

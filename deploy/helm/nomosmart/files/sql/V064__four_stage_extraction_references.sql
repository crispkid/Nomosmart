-- CHG-442: four-station extraction, chunk references and site-wide document names. Additive only.
-- STAGE442-002: one row per document version and station (1 content, 2 chunks, 3 tags and references, 4 index and test).
-- REF442-001..005: textual references found in chunks (rule or manual), resolved to a document in the same project.
-- REN442-004: documents.title_key is the normalized name; live non-reference documents must not share it.
-- MIG442-001: supported on fresh deployments only; existing duplicate names make this migration fail.
-- Rollback: application 0.3.x ignores the new table, columns and index; they can stay in place.

ALTER TABLE public.documents
    ADD COLUMN title_key character varying(500);

UPDATE public.documents SET title_key = lower(normalize(btrim(title), NFKC));

ALTER TABLE public.documents
    ALTER COLUMN title_key SET NOT NULL;

CREATE UNIQUE INDEX uq_documents_title_key_live
    ON public.documents (title_key)
    WHERE is_deleted = false AND source_type <> 'project_reference';

CREATE TABLE public.document_version_stations (
    document_version_id uuid NOT NULL REFERENCES public.document_versions (id),
    station smallint NOT NULL,
    status character varying(16) NOT NULL,
    confirmed_by uuid REFERENCES public.users (id),
    confirmed_at timestamp with time zone,
    reused boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (document_version_id, station),
    CONSTRAINT document_version_stations_station_check CHECK (station BETWEEN 1 AND 4),
    CONSTRAINT document_version_stations_status_check CHECK (status IN ('pending', 'ready', 'confirmed')),
    CONSTRAINT document_version_stations_confirmed_check
        CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL))
);

CREATE TABLE public.chunk_references (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES public.projects (id),
    document_id uuid NOT NULL REFERENCES public.documents (id),
    document_version_id uuid NOT NULL REFERENCES public.document_versions (id),
    chunk_id uuid NOT NULL REFERENCES public.chunks (id) ON DELETE CASCADE,
    raw_text character varying(500) NOT NULL,
    start_offset integer,
    end_offset integer,
    normalized_name character varying(500) NOT NULL,
    status character varying(16) NOT NULL,
    target_document_id uuid REFERENCES public.documents (id),
    source character varying(16) NOT NULL,
    is_deleted boolean NOT NULL DEFAULT false,
    created_by uuid REFERENCES public.users (id),
    updated_by uuid REFERENCES public.users (id),
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT chunk_references_status_check CHECK (status IN ('resolved', 'unresolved', 'external')),
    CONSTRAINT chunk_references_source_check CHECK (source IN ('rule', 'manual')),
    CONSTRAINT chunk_references_target_check CHECK ((status = 'resolved') = (target_document_id IS NOT NULL)),
    CONSTRAINT chunk_references_not_self_check CHECK (target_document_id IS NULL OR target_document_id <> document_id),
    CONSTRAINT chunk_references_offsets_check
        CHECK (start_offset IS NULL OR (start_offset >= 0 AND end_offset > start_offset))
);

CREATE INDEX chunk_references_version_idx
    ON public.chunk_references (document_version_id, chunk_id) WHERE is_deleted = false;

CREATE INDEX chunk_references_unresolved_idx
    ON public.chunk_references (project_id, normalized_name) WHERE is_deleted = false AND status = 'unresolved';

CREATE INDEX chunk_references_target_idx
    ON public.chunk_references (target_document_id) WHERE is_deleted = false AND status = 'resolved';

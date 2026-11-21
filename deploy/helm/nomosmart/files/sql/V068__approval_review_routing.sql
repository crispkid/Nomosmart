-- CHG-467 REVROUTE467-005/006/008/011: review routing, Project Owner fallback setting and approval administration.
-- Additive only: one settings section and row (default off), three columns with defaults that describe
-- existing rows as before, and one permission row for the built-in system-admin role.

ALTER TABLE public.system_parameter_section_revisions DROP CONSTRAINT system_parameter_section_revisions_section_check;
ALTER TABLE public.system_parameter_section_revisions ADD CONSTRAINT system_parameter_section_revisions_section_check
    CHECK (section IN ('general', 'documents', 'question_answering', 'approvals'));
INSERT INTO public.system_parameter_section_revisions (section) VALUES ('approvals') ON CONFLICT DO NOTHING;

INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description)
VALUES ('approval_owner_fallback_enabled', 'false'::jsonb, 'false'::jsonb, 'boolean', NULL,
        'When no eligible manager can review, send the submission to the Project Owners instead of refusing it')
ON CONFLICT (key) DO NOTHING;

-- How the manager stage of a request was routed (existing requests were all routed to a manager).
ALTER TABLE public.approval_requests
    ADD COLUMN review_route character varying(32) DEFAULT 'manager' NOT NULL,
    ADD COLUMN review_route_reason character varying(64),
    ADD CONSTRAINT approval_requests_review_route_check
        CHECK (review_route IN ('manager', 'delegate', 'project_owner_fallback'));

-- Who made a review decision (existing records were made by the assigned reviewer or a Project Owner).
ALTER TABLE public.review_records
    ADD COLUMN decision_source character varying(32) DEFAULT 'reviewer' NOT NULL,
    ADD CONSTRAINT review_records_decision_source_check
        CHECK (decision_source IN ('reviewer', 'project_owner_fallback', 'administration'));

INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute)
SELECT id, 'Approval', 'ApprovalAdministration', false, false, false, false, true
FROM public.roles WHERE name = 'system-admin' AND is_system
ON CONFLICT (role_id, module_name, function_name) DO NOTHING;

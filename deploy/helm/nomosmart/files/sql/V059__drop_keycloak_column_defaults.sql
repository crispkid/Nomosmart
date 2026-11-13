-- CHG-424 D424-09 / OPT424-022: remove the retired Keycloak column defaults.
-- Every identity the application creates sets these columns explicitly
-- (directory sync, emergency bootstrap), so no insert relies on them. Existing
-- rows are not changed.
-- Rollback:
--   ALTER TABLE public.users ALTER COLUMN auth_source SET DEFAULT 'keycloak';
--   ALTER TABLE public.external_groups ALTER COLUMN identity_origin SET DEFAULT 'keycloak_local';
ALTER TABLE public.users ALTER COLUMN auth_source DROP DEFAULT;
ALTER TABLE public.external_groups ALTER COLUMN identity_origin DROP DEFAULT;

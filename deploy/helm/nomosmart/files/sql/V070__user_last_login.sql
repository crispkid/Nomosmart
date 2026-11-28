-- CHG-497 LOGIN497-001: when each user last signed in successfully.
-- Additive only: a nullable column, filled once from the existing successful sign-in audit rows
-- (LDAP/OIDC `auth.login.success`, emergency access `auth.emergency.login`); users without one stay NULL.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS last_login_at timestamp with time zone;

UPDATE public.users AS u
SET last_login_at = signed_in.last_at
FROM (
    SELECT actor_user_id, max(created_at) AS last_at
    FROM public.audit_logs
    WHERE action IN ('auth.login.success', 'auth.emergency.login')
      AND result = 'success'
      AND actor_user_id IS NOT NULL
    GROUP BY actor_user_id
) AS signed_in
WHERE u.id = signed_in.actor_user_id
  AND u.last_login_at IS NULL;

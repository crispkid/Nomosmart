# NomoSmart authentication and directory operations (contract 2)

CHG-363 / PROTAUTH-001..012. Select OIDC **or** LDAP/Windows AD for ordinary sign-in. Both modes synchronize users and groups directly from one directory. Internal roles and project permissions remain authoritative. No IdP administration API is required.

## Preparation and OIDC registration

Prepare a read-only directory account, user/group search bases, public CA certificates, stable source UUID, and the immutable ID of the first administrator group. LDAP uses entryUUID; AD uses objectGUID. Do not match identities by email, names or DN. OIDC binds `(source, issuer, sub)` to an existing synchronized user through a configured common stable claim or explicit administrator binding. Employee IDs require an explicit unique, immutable, non-reused policy.

Examples under deploy/docker: auth-bootstrap.example.json, auth-bootstrap.ad.example.json and auth-bootstrap.oidc.example.json. Replace all example identifiers and endpoints. Source UUID/schema remain stable after initialization. **Real AD validation remains pending; the AD example is not acceptance evidence.**

Register Authorization Code + PKCE S256 and this exact callback in your OIDC service:

```
https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback
```

The backend owns normal, fresh-auth and candidate flows through that callback. The old /auth/callback no longer exchanges codes. Public clients, client_secret_basic and client_secret_post are supported when declared by Discovery. Fresh authentication requires verifiable auth_time. Issuer matching and HTTPS CA/hostname checks are strict. Explicit internal discovery/token/JWKS endpoints must be operator-allowlisted and belong to the same issuer. Do not carry internal endpoints across unrelated issuers. Refresh, silent SSO and upstream logout currently advertise false; local logout immediately revokes the local session.

## Configuration locations

| Purpose | Compose host setting | Backend source-development setting |
| --- | --- | --- |
| Bootstrap JSON | `AUTH_BOOTSTRAP_CONFIG_FILE` | `AUTH_BOOTSTRAP_CONFIGURATION` |
| Public CA directory | `AUTH_CA_DIRECTORY` | `AUTH_TRUST_ROOT` |
| Previous-key ring | `AUTH_PREVIOUS_KEYS_FILE` | `AUTH_ENCRYPTION_PREVIOUS_KEYS_FILE` |
| Real connection credentials | `DIRECTORY_BIND_PASSWORD_FILE` / required `OIDC_CLIENT_SECRET_FILE` | The same `*_FILE` names, pointing to private local files |

Compose maps host paths into container paths; host selectors are not Backend Settings names. Helm supplies equivalent inputs through `authentication.*`, bootstrap ConfigMap and runtime Secret. Use the matching [Backend](../backend/.env.example), [Compose](../deploy/docker/nomosmart.env.example) or [Helm values](../deploy/installer/protocol-values.example.json) example.

Normal deployment bootstrap reads the complete example wrapper (`configuration` plus `admin_group_id`). Direct `protocol_bootstrap initialize --configuration` instead expects only the inner configuration object, with the administrator group supplied separately through `--admin-group-id`. The group must be a real immutable directory group ID.

## Deployment and upgrade

For Compose, use deploy/docker/nomosmart.env.example, private runtime Secret files, HTTPS, a non-secret bootstrap JSON and mounted public CA directory. Allow only approved auth endpoints through AUTH_ENDPOINT_ALLOWED_HOSTS/CIDRS. Pause old identity producers/workers before the coordinated frontend/backend/worker upgrade. Apply V054 to an existing database, or B054 to an empty database. Run deployment-bootstrap ensure, keep onboarding restricted to administrator source IPs, then sign in as a real synchronized administrator. OIDC administrators must also complete fresh authentication. Run deployment-finalize, switch to operational, and verify readiness. Emergency access does not qualify normal-administrator onboarding.

User UUIDs, local roles and history are preserved. keycloak_user_id becomes nullable historical data. Initialization never guesses legacy directory links. The initialize command accepts explicit --migration-bindings of user_id to directory_object_id when verified migration input is available. See CLI --help for required arguments. Compose and Helm no longer include any bundled or optional identity-provider workload, theme, ingress, product credential, database provisioning, network policy or capacity entry. Operators manage the external OIDC service separately.

For Helm, use the existing installer commands with --protocol-config and the target TOML example in deploy/installer/nomosmart-install.protocol.example.toml. Provide an explicit context, owned namespace, release, installation UUID, non-secret values JSON and chart path. This installer path uses operator-managed external infrastructure and an existing runtime Secret. It never creates an IdP realm, provider, mapper or account. Use plan, install/resume, real normal-administrator sign-in, finalize, status/verify in that order, passing the same --protocol-config. Finalization checks real database session and sync evidence.

Set authentication.bootstrapConfiguration to the whole example JSON object. Configure endpoint allowlists, caSecretName and encryptionKeyId in values. Bootstrap alone receives DIRECTORY_BIND_PASSWORD and, when required, OIDC_CLIENT_SECRET from the runtime Secret. Ordinary services consume encrypted database credentials. Production values must reference external Secrets; do not commit credential values.

For restricted local test networking, operators may explicitly set `podDnsOverTcp: true` (default false). This changes resolver options only for application Pods, without changing cluster DNS. Validate actual networking and capacity separately; this run used maintenance rollouts with brief interruptions and does not qualify zero downtime or HA.

## Existing deployments

Review the deployment diff before applying changes. Remove retired `keycloak.*`, `global.keycloakPath`, `bootstrap.keycloak*`, product-specific environment/Secret/PostgreSQL values and `/identity` ingress entries. Supply explicit current values rather than `--reuse-values`; old component settings are rejected before apply. All public values profiles exclude this component.

When operators actually apply the new chart, old release-managed identity workloads, Services, Ingresses and product Secrets appear as removals. Arrange independent IdP ownership and data/credential retention first, then preview/upgrade using complete current values with `--reset-values`. This task does not perform that upgrade or delete existing resources.

Published SQL and historical identity columns remain intact. Operators must separately retain/manage any existing identity-provider data and credentials they still need. This source change does not operate existing containers, databases or PVCs. External OIDC still uses the standard issuer/client/callback and directory-binding contract described above.

The Compose generator no longer creates product-specific identity credentials or guesses an enterprise issuer. Provide the real `DIRECTORY_BIND_PASSWORD_FILE`, and `OIDC_CLIENT_SECRET_FILE` when the chosen OIDC client needs it. These operator-managed files must be private regular files without symlinks. Only the unchanged empty JSON example may be used as a public `AUTH_PREVIOUS_KEYS_FILE`; real keys belong in private files. First sign-in uses a synchronized normal administrator, without a fixed initial application password.

## Web management and session behavior

System management → Identity sources → Verify identity and edit. The settings unlock lasts ten minutes. Validate a candidate using real connections; mode/OIDC identity/client-secret changes additionally require the same administrator to sign in using that candidate. Apply within five minutes. Failure preserves the active configuration. Sensitive activation revokes previous sessions. Changing only the daily schedule preserves sessions.

Credentials are write-only: keep, replace or clear. Required credentials cannot be cleared on activation. End-user login passwords are never saved. Encryption keys and emergency activation remain deployment-only.

The default directory schedule is daily at 02:00 Asia/Taipei. Operators may choose a daily time/timezone/scope or run manually. No five-minute directory polling or 30-minute snapshot lockout is added. Changes may remain effective until the next successful sync. Incomplete reads retain the previous committed snapshot and issue an alert. Manual disable is separate from directory disable; synchronization cannot undo it. Manual and mapped role grants are combined.

Ordinary sessions expire after thirty minutes without foreground user activity. Real input extends them; background refresh does not. There is no fixed eight-hour or other absolute ordinary-session lifetime. Tabs sharing a browser cookie share activity/logout; devices have independent sessions. Logout, disabled accounts and security revocation still end sessions.

## Key rotation and recovery

AES-GCM authenticates the source, setting revision and purpose of each encrypted credential. Keys remain outside the database. Prefer an independent 64-hex-character AUTH_ENCRYPTION_KEY and AUTH_ENCRYPTION_KEY_ID. Initial compatibility can use APP_ENCRYPTION_KEY, but **do not rotate the shared application key as an auth-only rotation**.

Pause auth configuration writes. Deploy the new auth key/ID consistently to API, workers and bootstrap, retaining old keys through AUTH_ENCRYPTION_PREVIOUS_KEYS_FILE (JSON mapping old IDs to 32-byte hex keys). That file must be regular, private, and not a symlink; Helm previousKeysSecretName uses an init container to create the private copy. Run `python -m app.deployment.protocol_bootstrap rotate-keys`. It re-encrypts connection rows and unexpired flow secrets and is repeatable. Verify actual consumers before removing old keys. Missing or damaged keys fail closed.

Deployment operators may run `python -m app.deployment.protocol_bootstrap emergency-enable --password-file /PRIVATE/NEW_FILE`. The file must not exist; a random password is written privately and is not printed. The activation window is fifteen minutes and cannot slide with activity. Run emergency-disable afterward; finalization also disables it. Ordinary backend permissions, audit and internal critical notifications still apply.

restore-last-known-good validates available keys, the real directory and required OIDC metadata, restores the previous verified configuration and revokes sessions/unlocks. It is configuration recovery, not database restore. Rolling back old software requires compatible settings/schema and a coordinated deployment.

Monitor last successful directory sync, failed runs, auth/emergency audit and alerts. Exclude callback query strings, credentials, tokens and session cookies from ingress logs. Never weaken TLS validation, AD signing or channel-binding policy. Current results and remaining release gates are in AUTHENTICATION-STATUS.md.

## Effective roles and AD maintenance

System user responses expose active, nondeleted system roles, merging manual and synchronized sources per role. Knowledge Owner and Project Owner remain separate relationships. Callers without system-management read permission receive no global-role projection.

On the AD host, `backend/scripts/ad_readiness.ps1` takes Domain, ExpectedHost and ExpectedNamingContext and checks NTDS/Netlogon/DNS, DC discovery and synchronized RootDSE before reporting readiness. An optional restricted-ACL CredentialFile plus SentinelDn/ExpectedGuid enables one strict LDAPS bind and stable-identity readback. Keep passwords off the command line; rejected credentials are never retried automatically. See [scoped evidence](CHG-369-AD-READINESS-RESULT.json).

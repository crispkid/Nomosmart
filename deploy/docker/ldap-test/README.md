# Local synthetic LDAP test directory

This stack is for isolated/local synthetic identities only. It is not an
enterprise LDAP deployment recipe. Its fixed container names, named volumes,
Docker `kind` network and `172.19.0.20` address can collide with an existing
installation: inventory them first and stop on conflicting ownership. Do not run
the examples against the user's existing stack without explicit authorization.

## Scope and access

- phpLDAPadmin is available only at `http://127.0.0.1:8080`; do not expose it on
  all host interfaces or a public reverse proxy.
- Keycloak uses `ldaps://172.19.0.20:636` with the configured CA. OpenLDAP does
  not publish a host port. The private LDAP network is internal; the existing
  `kind` attachment is for the separately governed Keycloak connection.
- Directory admin DN: `cn=admin,dc=nomosmart,dc=test`. Read-only bind DN:
  `cn=nomosmart-bind,dc=nomosmart,dc=test`. Their passwords are separate mounted
  runtime secrets, not the synthetic user password and not values in this file.
- The seed scripts contain the public demonstration password `P@ssw0rd` for
  synthetic users. Treat it as insecure test data. Never reuse it for admin,
  bind, production users or internet-accessible services; restrict this stack.

## Runtime prerequisites

Set `LDAP_RUNTIME_DIR` to an operator-owned directory outside Git. It must have:

```text
secrets/ldap-admin-password
secrets/ldap-config-password
secrets/ldap-bind-password
tls/ca.crt
tls/server.crt
tls/server.key
phpldapadmin.env
```

Generate independent passwords and a CA/server certificate with SANs matching
the approved hostname/IP. Keep private material owner-only and back it up under
the approved custody policy. `ldap-test.env.example` documents the generated
Laravel `APP_KEY` format for `phpldapadmin.env`; the placeholder is not usable.
Mount permissions must allow the declared containers to read required files.
Do not use TLS bypasses, print secrets, or check runtime files into Git.

After separate approval and conflict checks, from the repository root:

```sh
docker compose -f deploy/docker/ldap-test/docker-compose.yml up -d
docker compose -f deploy/docker/ldap-test/docker-compose.yml ps
docker compose -f deploy/docker/ldap-test/docker-compose.yml logs --tail=100 directory-init
```

Compose starts OpenLDAP, waits for its authenticated CA-verified LDAPS health
check, then runs `10-nomosmart-seed.sh` followed by
`20-chg265-directory-data.sh`. Existing conflicting identities/attributes must
fail rather than be silently overwritten. phpLDAPadmin uses the read-only bind
secret for directory discovery; do not interpret that as application membership.
Inspect logs locally and redact identities/secrets before sharing evidence.

## Synthetic identities and application authority

- 兩份 seed 合計建立七個
  synthetic users: `ldap.alice`, `ldap.bob`, and user01 through user05.
- The latter DNs run from `uid=user01,ou=users,dc=nomosmart,dc=test` 至
  `uid=user05,ou=users,dc=nomosmart,dc=test`.
- Department groups are `HR` (user01/user02), `IT` (user03/user05), and `FIN`
(user04). `nomosmart-admin` (user01) is a directory group name, not a granted
NomoSmart system-admin role. Alice/Bob have the synthetic tester/reviewer groups.

初始目錄與群組沒有 Keycloak 或
NomoSmart role mapping。`reconcile_keycloak.py` manages a read-only
LDAP provider and directory attribute/group mappers; this does not authorize
local role assignments, external-group role mappings or Project membership.
Its default invocation is mutating. Inspect `--help` and use the explicitly
approved preflight mode before any separately approved reconciliation/sync.
The script targets a real Kubernetes Keycloak realm: never run it merely to
check this README or as automatic test setup.

An authenticated user without local application grants may receive
`application_access_denied`. To be searchable for Project membership, the user
must have effective `Menu.KnowledgeProjects.can_view` from an active local role;
the role need not be named `knowledge-project-user`. Project Owner/Editor/Viewer
membership is a separate project-scoped decision. Do not auto-assign roles to
make a login or search test pass.

## Non-destructive lifecycle and recovery

停止 stack 不刪除 named volumes. Use:

```sh
docker compose -f deploy/docker/ldap-test/docker-compose.yml stop
```

Restart with the same approved runtime directory and retained volumes. Do not
use `down -v`, volume prune, blanket container deletion or a seed reset to repair
a login. Back up the directory data/config volumes plus runtime secrets/TLS and
the related Keycloak federation configuration before an approved upgrade.
Validate restore on separate isolated resources, not by overwriting this stack.
永久清除須另行盤點與批准; identify exact volume/container/network owners, affected
identities and recovery ability first. Application role/group/member data is
outside this stack's cleanup authority.

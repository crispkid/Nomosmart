# Local Kubernetes deployment — authentication contract2

[繁體中文](README.zh-TW.md) · [Current deployment guide](../README.md#helm-installation)

Compose and Helm include no identity-provider software. A local application still needs real PostgreSQL, Redis, S3/RustFS, OpenSearch, Neo4j, an LDAP/AD directory and, only in OIDC mode, an external OIDC service. Datastores may run locally but retain explicit operator ownership and trusted TLS.

## Select the current path

- The protocol installer accepts `external-services`, an existing runtime Secret and a target bound to an installation UUID. Start from the [target TOML](../installer/nomosmart-install.protocol.example.toml) and [values JSON](../installer/protocol-values.example.json).
- Direct Helm can render bundled datastores, but the operator must manage its bootstrap/onboarding/finalization stages. See [Helm operations](../README.md#helm-installation).
- `values-docker-desktop.yaml` retains the legacy `localDevelopment`/`factory_acceptance` profile. Its successful rendering is not current protocol-installer compatibility or a production qualification. Do not pass that profile unchanged to the protocol installer, which selects normal onboarding.
- The current one-click wrapper uses `--protocol-config` and external-services; it stops at normal-administrator sign-in. Legacy `prepare-helm.py`, factory and authentication-contract-1 examples remain historical and are excluded from the current payload. The tunnel example has datastore forwarding only; no IdP software or fixed identity proxy is provisioned.

## Prepare the target

Use an explicit context and a unique namespace/release. When precreating a namespace for Secret inputs, its `nomosmart.io/protocol-installation` label must match the target's installation UUID. Do not adopt another installation's namespace.

Review real node allocatable resources, taints, workload requests/limits, ingress, StorageClass and persistent storage. Several Kubernetes nodes sharing one Docker VM do not provide independent host/storage failure domains; count the shared host once. Make the exact reviewed application images available to every selected node.

Keep runtime credentials, encryption keys and CA/private-key inputs in private operator storage and Kubernetes Secrets. The target/values files contain references and non-secret configuration. Directory Bind and optional OIDC credentials must match real external accounts. No fixed application password or automatically created directory administrator is supplied.

An optional `podDnsOverTcp: true` changes only application Pod resolver options. It does not change cluster DNS/CNI or justify disabling CA/hostname checks. Do not enable the older factory credential profile merely to request TCP DNS.

## Verify the lifecycle

Follow plan → install/resume → real synchronized administrator sign-in → finalize → verify. OIDC administrators complete fresh authentication before finalization. Inspect status after an interruption before sending another write. Treat exit10/action-required as the sign-in checkpoint.

Check actual HTTPS, readiness dependencies, normal permissions and a real directory sync. Render/lint success alone does not qualify installation, identity or HA. Source changes do not update existing workloads until the operator applies them.

For cleanup, use exact ownership/UID/resource inventories. Preserve external services, retained PVCs and other namespaces; no blanket prune or arbitrary host-path deletion. Application rollback is not SQL/data rollback.

## Evidence and history

- [Current authentication/runtime evidence and open gaps](../../docs/AUTHENTICATION-STATUS.md)
- [Current configuration checks](../../docs/AUTHENTICATION-STATUS.md#deployment-file-checks)
- [Archived local instructions](../../docs/archive/authentication-contract-1/local.en.before-doc-sync.md)
- [2026-10-01 historical validation](VALIDATION.md): original results only, not acceptance of current source

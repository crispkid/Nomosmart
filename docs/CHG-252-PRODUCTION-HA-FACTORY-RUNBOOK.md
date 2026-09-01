# CHG-252 Production HA Stack And Factory Reinstall

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

Status: Gate 4 approved on 2026-08-04. Repository implementation and
non-destructive/disposable verification are authorized. Live NomoSmart deletion,
quiesce and reinstall are **not authorized** until a read-only exact factory plan
has no blockers and Peter separately approves its plan-bound permanent-delete
phrase.

## Implemented release contract

- CloudNativePG 1.30.0: three PostgreSQL 18.4 instances, hard three-node spread,
  synchronous `ANY 1`, failover quorum, separate roles, user-provided server and
  `streaming_replica` TLS identities, stable `-rw` service and PDB 2.
- Barman Cloud CNPG-I 0.13.0: digest-pinned operator and sidecar, self-signed
  cert-manager operator/plugin mTLS, RustFS private-CA HTTPS ObjectStore,
  AES256-encrypted/compressed data and WAL, 30-day retention, immediate plus
  daily standby-preferred backup. The guided foundation first creates the S3
  bucket; the application revision then enables WAL archiving and waits for a
  completed backup/recovery window.
- Redis: three TLS-only AOF data Pods, three TLS Sentinel voters, quorum 2,
  separate service/replication/Sentinel ACLs and Sentinel-aware clients.
- Celery Beat: two hard-spread Pods, one exact namespaced Lease, exactly one
  active child and one standby.
- RustFS: four fixed TLS endpoints/PVCs over three physical domains with `2/1/1`
  scheduling, 2 data + 2 parity and PDB 3. This remains three failure domains,
  not four.
- Keycloak 3, ClamAV 2, OpenSearch 3; Neo4j Community remains the explicitly
  accepted singleton exception.
- Capacity contract: 22 retained PVCs request 485 GiB. The existing three
  8-core/32-GiB/300-GB nodes must each expose at least 7000m/28Gi allocatable,
  pass 20% CPU/RAM and 25% physical-storage reserve, and use an existing
  Longhorn CSI StorageClass with exactly one replica and `disabled` or
  `best-effort` data locality. Longhorn 3x layered replication would require
  about 1.45 TiB before reserve and is rejected.

CloudNativePG 1.30 uses a per-cluster Lease to coordinate promotion. Barman
Cloud is the supported CNPG-I backup/PITR path and its plugin must share the
CloudNativePG operator namespace. See the official
[CloudNativePG installation notes](https://cloudnative-pg.io/docs/1.30/installation_upgrade/),
[Barman installation](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/),
[Barman usage](https://cloudnative-pg.io/plugin-barman-cloud/docs/0.10.0/usage/)
and [private-CA ObjectStore settings](https://cloudnative-pg.io/plugin-barman-cloud/docs/object_stores/).

## Non-destructive verification before any live reset

Run from the repository root and retain redacted output:

```bash
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh helm:lint
./HARNESS/harness.sh deploy:config-policy
backend/.venv/bin/python -m unittest discover -s deploy/installer/tests -p 'test_*.py'
```

The release remains blocked until all new/changed images have exact platform
digest, license inventory, SPDX SBOM and CVE evidence. The existing OpenSearch
2.19.6 UAT acceptance does not approve the other CHG-252 images and is not a
Production security gate.

The CHG-252 release builder uses signed manifest schema v2. Operator-supplied
application/peripheral images remain in `images`; the CloudNativePG operator,
Barman Cloud plugin and Barman Cloud sidecar are fixed in `platform_images`.
Release creation scans every logical entry and retains a complete SARIF and
SPDX inventory. Do not run this release command until Docker Scout processing
of the explicit image inventory has been separately approved.

Before a factory plan may be considered ready, retain the read-only installer
`capacity` evidence. It must include all three node allocatable/current
non-NomoSmart requests and limits, prospective request headroom, Longhorn disk
maximum/available/scheduled values, current NomoSmart reclaimable bytes, the
selected StorageClass parameters and the 485-GiB physical plan. A Pod count or
StorageClass name without this evidence is not a capacity pass.

## Factory plan and approval boundary

Run `factory-plan` only. It does not mutate Kubernetes:

```bash
deploy/installer/nomosmart-install factory-plan \
  --config /secure/nomosmart/env-uat-001.toml \
  --output /secure/nomosmart/chg252-factory-plan.json
```

Do not request deletion approval when the result has any blocker. In particular,
all selected Longhorn volumes must be detached and the OpenLDAP volume
`pvc-aceaa515-e901-4771-bdb5-687d79d71aec` must appear only under `preserve`.
The plan must enumerate all NomoSmart resources, Secrets, PVCs, PVs, Longhorn
Volumes/Snapshots and the Helm revision, while preserving the existing
Namespace UID and Rancher Project ID.

After a separate approved quiesce window, rerun the plan. Present its exact
deletion and preservation lists, `backup_choice=delete-without-backup`, digest
and generated `approval_phrase` to Peter. Only his later verbatim plan-bound
approval may be passed to `factory-apply`; Gate 4 is rejected by design.

## PostgreSQL backup and isolated PITR acceptance

1. Confirm the Cluster condition `ContinuousArchiving=True`, ObjectStore
   `serverRecoveryWindow` contains the source server, and a `Backup` is
   `Completed`. Do not expose Secret values in evidence.
2. Create a new disposable Namespace and a new read-only RustFS credential.
   Copy only the RustFS public CA into that Namespace. Do not reuse the
   production write credential or PostgreSQL client Secret.
3. Render
   [`postgresql-pitr-restore.example.yaml`](../deploy/installer/postgresql-pitr-restore.example.yaml)
   with an approved digest-pinned PostgreSQL image, isolated StorageClass/PVC,
   original server name `nomosmart-postgresql`, and an RFC3339 point after a
   recorded test transaction.
4. Wait for the isolated Cluster to become Ready. Compare migration version,
   representative row counts and deterministic checksums with the recorded
   source point. Prove data after the selected point is absent.
5. Record measured RTO/RPO, backup ID, target time, CA fingerprint and only
   Secret references. Delete the disposable Namespace only after evidence is
   accepted. Never delete the production ObjectStore or source backup as part
   of restore verification.

ScheduledBackup uses a six-field cron expression; the official
[CNPG backup reference](https://cloudnative-pg.io/docs/1.28/backup/) explains
the seconds field and recommends recurring restore tests.

## Live HA acceptance still required

After fresh install and both human TOTP checkpoints, execute the exact
`DEPLOY-015` cases in `TEST_PLAN.md`: PostgreSQL primary/each-node loss and
fencing, Redis quorum/promotion/client rediscovery, Beat kill/partition/rolling
no-dual-active, each RustFS Pod/node including the double-resident node,
Keycloak session/TOTP/LDAP sync, ClamAV clean/EICAR, OpenSearch green/snapshot,
Vault Shamir/Raft and continuous browser/API/job traffic. Recover every quorum
before the next disruption. Leave all services running for UAT.

Static Helm output, Pod counts, PDBs or Longhorn replica counts alone never
close a live HA or PITR acceptance case.

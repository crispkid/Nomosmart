# CHG-252 Supply-Chain Evidence Register

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

Status: repository enforcement and clean-builder verification implemented by
2026-08-05; Production container evidence remains open. This file contains
image identities and gate status only. It contains no registry credential,
Kubernetes Secret or Docker credential material.

Application dependency/static checks on the clean builder passed: production
`npm audit` reports zero findings, `pip-audit` reports no known vulnerabilities
after upgrading the locked Backend runtime from `cryptography` 49.0.0 to
50.0.0, and Bandit reports zero High-severity findings. These checks do not
inspect container base layers or replace Docker Scout CVE/SPDX processing.

## Enforced release contract

NomoSmart Production release manifest schema v2 separates:

- `images`: Frontend, Backend, migration, PostgreSQL, Redis, RustFS,
  OpenSearch, Neo4j, Keycloak, ClamAV and Vault identities supplied by the
  release operator; and
- `platform_images`: fixed CloudNativePG operator, Barman Cloud plugin and
  Barman Cloud sidecar identities controlled by the release contract.

Release creation runs Docker Scout CVE and SPDX 2.3 commands for every logical
entry. It rejects an unresolved High or Critical result, generates one combined
license inventory and binds every artifact digest into the signed closed
package. A component-specific human risk acceptance may govern UAT, but does
not silently turn that result into a Production pass.

## Exact identities already fixed

| Component | Digest-pinned identity | Evidence status |
|---|---|---|
| CloudNativePG operator 1.30.0 | `ghcr.io/cloudnative-pg/cloudnative-pg@sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb` | Contract/installer drift test passed; CVE/SPDX/license scan open |
| Barman Cloud plugin 0.13.0 | `ghcr.io/cloudnative-pg/plugin-barman-cloud@sha256:71589dbac582333442812b07b31f7ea4d00324a8358aac7ca507dabf9f4b6c96` | Contract/installer drift test passed; CVE/SPDX/license scan open |
| Barman Cloud sidecar 0.13.0 | `ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar@sha256:990361af3319f9e23aafa0f6d7981f99bf1f69b4e6a85cf1bc7d71d6f09bb288` | Contract/installer drift test passed; CVE/SPDX/license scan open |
| PostgreSQL operand 18.4 | `ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:f0cc49632b5cc1e51f65ba03658c89bd31d64ea2672b14843a808a8d281417e1` | Helm/installer identity passed; CVE/SPDX/license scan open |
| OpenSearch 2.19.6 repository-s3 | `nms-uat-registry.ctbclab.com/nomosmart/opensearch:2.19.6-s3-chg251-20260804@sha256:4897a404a6791fcc1229a35c5d66f12260ce3b4231b09b513f0bf0dfacf4bb30` | Existing 1 Critical/34 High acceptance is UAT-only; Production gate open |
| Vault 2.0.3 | `hashicorp/vault:2.0.3@sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54` | Chart identity fixed; CHG-252 all-runtime scan open |

## Identities still requiring a clean release build or digest selection

The standalone production values render is intentionally not sufficient release
evidence. The guided installer must receive a signed digest-pinned image
inventory. As of 2026-08-04 these logical entries are not yet bound to a new
CHG-252 release package:

- NomoSmart Frontend;
- NomoSmart Backend and Celery Beat/Worker helper containers;
- NomoSmart migration image;
- Redis 7.4.2 candidate;
- RustFS 1.0.0-beta.10 candidate;
- Neo4j Community 5.26.4 candidate;
- NomoSmart Keycloak 26.0.8 image; and
- ClamAV 1.4.3 candidate.

The current shared worktree is not an acceptable Production builder input: it
contains unrelated and uncommitted changes. An independent clean CHG-252 branch
is therefore prepared from the approved CHG-247 through CHG-252 dependency
chain. Images must be built from its clean, detached, full Git SHA, published
without overwriting an existing tag, and then supplied as
`tag@sha256:digest` entries.

## Remaining authorization and acceptance

No CHG-252 Docker Scout command was run while creating this register. Before
the release builder processes image-derived package metadata, obtain explicit
approval covering the complete final digest inventory. After a zero-unaccepted
High/Critical result (or explicit component-specific UAT acceptance), retain
the SARIF, SPDX and license inventory in the signed package. Production remains
blocked until all images pass the stricter gate.

Only after supply-chain, disposable install/HA/PITR and exact live capacity
gates pass may the read-only exact factory plan be presented for a separate,
digest-bound permanent-delete approval.

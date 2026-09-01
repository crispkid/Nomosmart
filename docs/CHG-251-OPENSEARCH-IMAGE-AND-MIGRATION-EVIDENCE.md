# CHG-251 OpenSearch Image And Migration Evidence

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

## Current status

CHG-251 is partially implemented as of 2026-08-04. Repository, certificate,
image supply-chain and first recovery-point work is complete. Both live TOTP
enrollments are verified, but the live StatefulSet conversion has not started
because the retained Initial Root Recipient passphrases cannot decrypt the CA
signing-key custody artifact. No out-of-band Helm revision or OpenSearch
workload restart has been performed.

The exact live target remains Rancher Project `NomoSmart`, Kubernetes Namespace
`nomosmart`, namespace UID `4bf5d5e5-e92a-4b1b-9886-3788f7d21c1f`, Rancher
project label `p-d6792` and annotation `c-mjq45:p-d6792`.

## Approved image decision and UAT risk boundary

The first pinned OpenSearch 2.19.1 candidate produced 4 Critical and 245 High
Docker Scout results. Its derived `repository-s3` layer produced zero
Critical/High when Scout applied the base-image provenance.

The official OpenSearch 2.19.6 candidate reduced the result to 1 Critical and
34 High. Peter approved 2.19.6 and accepted that residual result only for UAT,
conditioned on no public OpenSearch endpoint, authenticated HTTPS, private-CA
transport TLS and the least-privilege NetworkPolicy. The acceptance explicitly
does not close the Production release security gate.

The pushed image is:

- repository/tag: `nms-uat-registry.ctbclab.com/nomosmart/opensearch:2.19.6-s3-chg251-20260804`
- OCI index digest: `sha256:4897a404a6791fcc1229a35c5d66f12260ce3b4231b09b513f0bf0dfacf4bb30`
- linux/amd64 platform digest: `sha256:b3d8eaccc98ba38702a32086026af4df1ab79653f6d2f01c4b14f5447c5d3564`
- provenance attestation digest: `sha256:54b5f1449c4e0b2bba9d3e886406f5679131718b48394fae19f8910720f80ab7`
- pinned official base: `opensearchproject/opensearch:2.19.6@sha256:b6c3071dde7b170d85f3a44b9c4ef1cae2e7a23f47448ffd7a2538524476d864`
- plugin inventory: matching official `repository-s3` present
- live RKE2 pull verification: a tokenless, data-less one-shot Pod on
  `nms-uat-rke2-03` pulled the OCI index digest, printed exactly
  `repository-s3`, reached `Succeeded` and reported config image ID
  `sha256:d7bf7fd77a586c226745f5f5c71b0644bb2dc3c509fc3c6c187bbefee929245a`;
  the Pod was then deleted
- final Registry-platform scan: 1 Critical, 34 High; 17 affected package
  coordinates and 22 unique High/Critical vulnerability identifiers
- SPDX: 2.3, 799 document packages and 10,513 relationships

The official-base and pushed-platform High/Critical CVE sets and affected
package/version sets are identical. No new High/Critical identifier or affected
package/version was introduced by the derived image. The final UAT Helm image
reference uses `repository@sha256:4897...bb30`; a production render without a
valid SHA-256 digest fails closed.

Raw evidence is owner-only under
`/Users/peter/Documents/NomoSmart-UAT-Handoff/CHG-251-Evidence/20260804`.
`SHA256SUMS` covers the SPDX, SARIF, High/Critical comparison, Registry response
headers and exact OCI index manifest. Registry access used the existing
`nomosmart-registry` imagePullSecret through stdin and a temporary credential
helper entry. The entry, temporary Docker config, one-time builder/cache and
builder-local host/CA settings were removed after push. macOS, FortiClient and
Docker Desktop global DNS/trust settings were not changed.

## Certificate custody

The self-issued OpenSearch private hierarchy is stored owner-only under
`/Users/peter/Documents/NomoSmart-UAT-Handoff/OpenSearch-Custody/chg251-20260804`.
It contains the public CA, HTTP leaf/key, transport leaf/key and manifest. The
transport leaf has server/client EKUs and the required service, headless and
three peer SANs. The CA signing key exists only as PGP ciphertext:

- recipient fingerprint: `647D6BE8D77773CD2F8805BFF50E92DFE9872814`
- ciphertext SHA-256: `f1931437faab7c00903e96ab27017a56df95f2db6c89092634252c3050616095`
- public CA SHA-256: `2f0ab798663cc16b1555d6f1fb94fd1265307e9d39b6c0cbc0eec8126ede81c9`
- HTTP leaf SHA-256: `0ee3a3cdac56f286d57c1945c316ad171ea86b617b03a6c4a88418fe500c3c94`
- transport leaf SHA-256: `791899b15bc897b09806e2dc0dc4eab68b75e5d0a46ad96c1135165e0582b548`

OpenSSL chain verification passed for both leaves. GPG packet inspection binds
the ciphertext to key ID `F50E92DFE9872814`.

On 2026-08-04, Peter approved a memory-scoped Initial Root Recipient custody
test. The ciphertext SHA-256, public CA SHA-256 and recipient fingerprint all
matched the manifest. GnuPG accepted the expected encrypted recipient private
key, but rejected the passphrase retained in the current KeePass database, all
three retained KeePass backup generations and the matching entry histories
with `Bad secret key`. No candidate decrypted the CA signing-key ciphertext.
The test stopped without printing or persisting plaintext key material; its
temporary GnuPG agents, homes and verifier artifacts were removed. The custody
decryptability gate is therefore **blocked**, not passed. A new live TLS Secret
and the three-node migration were not started.

## Recovery point and remaining live gates

Longhorn Snapshot `chg251-pre-migration-20260804` is `readyToUse=true` for only
the current OpenSearch volume
`pvc-e71d1be5-53fd-45d2-9387-08bc87c02a5e`; creation time is
`2026-08-03T19:24:03Z`. No other application or OpenLDAP volume was targeted.

The live TOTP checkpoint was independently verified through the in-cluster
Keycloak Admin API on 2026-08-04:

- `user01`: enabled federated user, no required actions, OTP credential present,
  member of `nomosmart-uat-admins`;
- `nomosmart`: enabled local user, no required actions, OTP credential present,
  member of `system-admin`.

The installer state is intentionally still at `totp-checkpoint`: the current
CHG-251 installer/config validation requires the new transport TLS inputs, and
the CA custody gate failed before those inputs could be activated. No Helm,
Secret, StatefulSet, PVC, Snapshot or OpenSearch data mutation was performed by
this checkpoint verification.

The following still require real live evidence and are not passed:

1. Recover the correct Initial Root Recipient private-key passphrase, or approve
   a controlled replacement custody design, and repeat the CA public-key match
   test successfully.
2. Reconcile the verified TOTP result into the guided installer and complete
   operational finalization without applying the three-node chart out of order.
3. Install the new TLS Secret generation without overwriting the old Secret.
4. Enable the pushed image on node-0 while preserving its cluster UUID and data,
   create/verify the native TLS RustFS snapshot and representative renamed-index
   restore, and retain it.
5. Perform the controlled existing-cluster discovery/TLS conversion, then add
   node-1 and node-2 on independent retained PVCs.
6. Verify green health, three expected nodes, zero unassigned shards, stable
   UUID/counts, authenticated NomoSmart read/write, NetworkPolicy positive and
   negative paths, and one-node disruption/recovery.

## Repository verification completed

- `./HARNESS/harness.sh spec:doctor`
- `./HARNESS/harness.sh spec:trace`
- `./HARNESS/harness.sh plan:approved`
- `./HARNESS/harness.sh test:plan`
- `helm lint deploy/helm/nomosmart`
- `helm lint deploy/helm/nomosmart -f deploy/helm/nomosmart/values-prod.yaml`
- focused CHG-251/deployment regression: 24 passed, 1 GnuPG-agent sandbox skip
- live Registry/RKE2 digest pull and `repository-s3` inventory: passed; the
  one-shot verification Pod was removed
- the skipped GnuPG test path was covered by the real owner-only CA generation,
  OpenSSL chain/SAN/EKU validation and ciphertext packet/fingerprint evidence
- `git diff --check`

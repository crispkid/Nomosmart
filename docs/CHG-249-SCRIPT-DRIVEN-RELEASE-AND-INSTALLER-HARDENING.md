# CHG-249 Script-driven Production Release And Installer Hardening

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

## Implemented interfaces

- Provider-neutral `deploy/release/nomosmart-release` with `source-check`,
  `create` and `verify-package`.
- Closed, signed Production release contract with exact source, compatibility,
  image digest, mandatory gate, coverage, CVE, license, SPDX and payload
  checksum evidence.
- Installer configuration `install.nomosmart.io/v1alpha2` with a package path
  and independently trusted release signer fingerprint. Existing `v1alpha1`
  remains explicitly UAT/legacy compatible.
- Read-only `doctor` and two-step `reset-plan` / `reset-apply`.
- Process-group child supervision, SIGINT/SIGTERM forwarding, bounded TERM/KILL
  cleanup and holder/config/UID/resourceVersion-safe Lease deletion.
- Terminal Kubernetes Job classification for Complete, Failed,
  BackoffLimitExceeded, DeadlineExceeded, permanent image/config waiting
  reasons and non-zero container termination.
- Bounded exponential Vault startup retry with transient/permanent
  classification.
- Shared Python TLS client with CA, hostname/SNI, same-origin redirect,
  content-type, body-size and timeout enforcement; `curl` is not required.
- In-memory GnuPG custody boundary for Vault ciphertext/private-key/passphrase
  pipes and owner-only ephemeral GNUPGHOME. The live CHG-248 manual share path
  remains in place until the real Vault-generated 5/3 regression is approved
  and passes.
- OpenLDAP multi-valued `cn` warning from Keycloak-visible imported attributes,
  with no directory-write path.

## One-command operator entry point

`deploy/installer/nomosmart-one-click` is a thin, provider-neutral shell
wrapper around the guided installer. It keeps the approved manual/script-driven
boundary while removing repetitive command selection for operators:

1. runs `plan` and prints the redacted read-only result;
2. requires the exact displayed `APPLY <config_digest>` in an interactive TTY,
   or an explicit `--yes` / matching `--confirm-digest` for an approved
   non-interactive invocation;
3. reads `status` and chooses `install`, `resume`, or `verify`;
4. runs final `status` and `verify` after a successful install/resume.

The wrapper never handles password, token, private-key, Vault-share or TOTP
values, and exposes no factory-reset, permanent-delete or uninstall operation.
It is included in signed release packages beside `nomosmart-install`; all
failure, Lease, checkpoint, Secret/PVC preservation and exit-code behavior
continues to come from the Python installer.

## Reset safety

Reset is intentionally not uninstall. It refuses:

- an operational-finalization state or operational deployment phase;
- an active Lease;
- any Helm release;
- installer-owned Secret, PVC/PV, StatefulSet or other protected state;
- drifted/changed observations between plan and apply.

Eligible pre-Helm abandoned attempts may remove only the exact installer state
ConfigMap, exact stale Lease and the two installer ownership keys on the
Namespace. It never deletes the Namespace. Local state and receipt are copied
to an owner-only attempt archive before cluster mutation, and the original is
removed only after all exact operations succeed.

## OpenLDAP data-quality operator checkpoint

The supported identity rule is:

- login identifier: `uid`;
- canonical name: exactly one `cn`;
- UI display value: explicit `displayName`.

The installer reports only an aggregate warning count and never writes LDAP.
Before an operator changes an existing entry, they must export an exact LDIF
backup, review every LDAP consumer, obtain separate change approval, apply the
minimal directory-owner change and rerun Keycloak sync plus NomoSmart identity
verification. No LDAP credential or entry content belongs in the normal
installer receipt.

## Acceptance still requiring external authority

The following tests are designed but are not represented as passed by local
contract tests:

- complete Production `create` on a clean detached isolated Linux builder using
  the operator's real release-signing key;
- real Frontend and Backend full-suite coverage at or above 80% for lines,
  statements/functions where available and branches;
- retained live OCI CVE/license/SPDX evidence bound to the same source;
- no-Git/no-Docker/no-Podman clean-host install on an approved disposable
  cluster;
- live SIGINT/SIGTERM/uncatchable termination matrix and Lease TTL recovery;
- real failed migration/bootstrap/directory/finalization Job latency;
- transient Vault recovery versus permanent TLS/CA/RBAC/configuration failure;
- Vault-generated five encrypted shares, three-share threshold, wrong key,
  duplicate share, corrupted ciphertext and GnuPG version matrix.

The existing UAT environment is not mutated by CHG-249 implementation or local
tests.

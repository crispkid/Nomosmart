# PDF startup guard — CHG-305 R18

> Historical / retired by CHG-305 R20 (2026-09-23). This document preserves prior
> design and evidence only; referenced container code and tools have been retired.
> Do not run these installation or recovery commands. The current Worker-local
> implementation and verification limits are in docs/CHG-305-R20-SOURCE-HANDOFF.md
> at the repository root. Source retirement did not uninstall any live resources.

2026-09-23 D19 source-only handoff: image/profile packaging and the fixed-node
installer/recovery/rollback entrypoints are wired. New code is **NOT TESTED OR
COMPILED**, at Peter's request. See
[`CHG-305-R18-R5-INSTALLATION-WIRING.md`](../../docs/CHG-305-R18-R5-INSTALLATION-WIRING.md).
It does not open PDF admission or generate a capability PASS. Historical results
below predate this change; typed R5 recovery has since been approved separately.

Implementation in progress, **not installed; complete node/PDF acceptance has
not passed**. A Linux handler entry now exists; it is not deployment-ready merely
because it compiles.

Latest D35 checkpoint: Peter approved ONLY diagnostic option2. The unchanged
D32 binary ran once in the explicit root-private /opt/nomosmart-pdf-diagnostics
location. Actual Container/Get, Sandbox/Get, Snapshot/Stat/Mounts, wrong-daemon
hash rejection and original-record recheck PASS. Exact binary and both owned
empty directories were removed; /run noexec and revision39/config unchanged.
This is read-only client compatibility, NOT new PDF/handler/isolation acceptance.
Alternative terminal recovery remains unapproved. D35 receipt:
`/private/tmp/nomosmart-chg305-r18-r4-node-client-zku39b9s/result.json`, SHA256
`57c880240fd60ec88d993582a4845911337e2e1005388ff5dfb804d22e8adb60`.

Latest D33 checkpoint (2026-09-22): **163 host Go top-level PASS**, race/vet,
host89.6%; **150 Python PASS/zeroSKIP**, selected71.1554% **FAIL80**. The two
standalone child-helper skips are not counted as PASS. Linux/arm64 compile and
offline Compose/Helm checks passed, not actual node execution.

`nodeconfig` holds independently installed pins/profiles and scoped clients.
`ociproof.Checked` binds the original/output hashes and role image; parser
resource limits remain finite/zero-swap, fixed pause resources are separately
compared. `nodeobserver.Start` now joins actual API/CRI reads, original init.pid,
whole-OCI proof, retained pidfd/cgroup and a sealed-runc read-only running-state
check. `ObserveAndReport` persists before delivery and keeps genuine terminal
proof after a lost start ACK instead of sending a premature stop-first report.
These Linux integrations have **not run on the actual node**. No false runtime
responses or passing capability have been generated to exercise them.

D26–D31 assembled fixed entry/control/independent observation, independently
derived live-source facts, original stop redelivery and stopped-only private
bundle cleanup. Recovery commands require exact original CID/start SHA:
`recover-report`, `recover-delete`, `recover-observe`. None grants a new start,
changes the original work deadline, invents a stop or erases audit records.
Partial create and loss of the original PID before observer recovery still stay
UNKNOWN; those are unfinished recovery cases, not passing cleanup evidence.

Still missing: independently reviewed complete platform profiles, installer/
canary producer, remaining uncertain-state recovery, image builds/deploy and
real PDF acceptance. Private mounts/runtime control have compiled, not executed.
Do not point a live RuntimeClass at this source tree or treat unit checks as
readiness. D33 receipt:
`/private/tmp/nomosmart-chg305-r18-r4-contracts-g_2am_td/result.json`, SHA256
`55c095b6da28ee070f4fc0816dd7e377b44b17e63c135135829ebef633e6be7d`.
The preceding run exposed an expiry-test wait race; a bounded actual-clock wait
fixed synchronization without changing product expiry or any denial assertion.

D32's fixed existing-container read-only diagnostic is a separate executable,
not a handler or capability producer. Its first archive transfer failed; the
subsequent exact binary transfer succeeded but `/run` is `noexec` and execution
was denied (126). Both owned temporary directories/binary were precisely removed.
No daemon-client/PDF/node acceptance PASS is claimed. Do not disable/bypass that
mount policy or silently choose a different executable path. The runner now
checks `noexec` before creating files; location authorization must be resolved.
Current environment remains revision39. Fresh read-only V049 checksum/constraint/
owner-parity checks passed without backup or data mutation.

Historical D18/D19 checkpoint:122 host Go top-level PASS/race/vet, host89.4%;137
Python PASS/zeroSKIP, selected72.3712% FAIL80. `cgroupproof` retains the original
process/cgroup identity and reads actual v2 resource/population metadata; a real
networkless Linux smoke passed (85.0% for that package). It correctly retained
the nonempty group after one child's exit. No positive empty-container/kernel
stop, complete OCI execution, or Kubernetes acceptance is claimed.

`runtimequery.WaitTask` adds only fixed read-only original-task exit metadata,
with exact before/after container binding and strict exit/time decoding. It must
run OUTSIDE synchronous runc callbacks; those callbacks hold shim locks. Codec
tests and Linux compile passed, actual Wait daemon/observer lifecycle NOT_RUN.
Complete producer, immutable execution and capability/recovery remain pending.

Latest D17 local checkpoint:137 Python PASS/zeroSKIP, selected72.3712% (FAIL80%),
Go115/race/vet/host89.0% PASS. Schema5 attach/start and terminal/cleanup consumers
are wired; no actual guard producer or immutable runtime handoff yet. D17 adds
opt-in Helm v3 grant/gate policy with unchanged legacy hashes; offline rendering
PASS does NOT establish CEL/API enforcement. Full integration/deployment remains
incomplete. Older checkpoint descriptions below are retained as historical.

R18 R4 D12 implements the dedicated node evidence codec and outbound mTLS client.
It has one fixed POST endpoint, explicit CA/server/leaf pin, no proxy/redirect/
retry or alternate credential, original bounded deadline and exact durable ACK.
Real Go-to-coordinator TLS/role/duplicate/conflicting-report checks passed; they
do not prove the metadata describes an actual running/stopped container.
Formal node credentials and handler/start/stop emission are not installed/wired.

D13 connects durable evidence ownership to the coordinator's schema5 input
checks, keeps `creating` until verified attach, rejects missing/stopped/restarted
pairs and revalidates records against original grants/config pins on reread.
New grant3 termination metadata uses `/dev/termination-log` to avoid a nested
`/work` mount; old contracts stay unchanged. The v3 admission gate is still shut.
Latest local receipt vxv7yl4_:127 Python PASS/zero skip, expanded selected coverage
72.1129% (below80%); evidence module100% for pure contracts/files, not runtime.
Host Go115/race/vet PASS; full handler, immutable execution bundle, live source,
capability/attach/termination and installation remain necessary.

R18 R4 D11 adds `workproof` and independent `kubeproof.Derive`/`kubequery.Resolve`:
expected work bindings come from the original canonical request on the actual
Job/template/Pod plus installation pins, never by copying a grant's claims.
Legacy journals keep their metadata version; missing/corrupt/cross-version
annotations, run IDs and resource ceilings fail closed. `ociproof` compares the
whole daemon and bundle JSON against an independently hash-pinned role profile
before the four permitted parser deltas. Unknown fields, array reordering and
null/absent changes are rejected. Dynamic slots permit only enumerated scalar
locations, not replacement of entire security objects. Actual profile creation,
trusted dynamic-fact derivation and held immutable runtime execution remain
unwired; this comparator alone does not authorize an OCI process.

The D11 local regression had 109 host Go top-level tests/race/vet PASS (88.8%
host statements) and 109 Python PASS/one host-setuid skip. Selected Python
coverage remained 66.7747%, below 80%; the complete wrapper correctly failed.
Linux cross-compilation/offline deployment checks passed, not runtime execution.
`ociproof` alone measured 86.4%; its bounded fuzz run made 892 executions with no
failure. These local figures are not application-wide or full PDF acceptance.

R18 R4 D10 adds `procproof`: a read-only Linux pidfd plus retained proc directory
binds the original PID, kernel boot ID and start ticks. Reopen requires the same
fingerprint; absence, permission errors, deadline expiry and reused identity
remain unknown/rejected, never successful cleanup. The observer reads only
kernel identity metadata, does not signal/reap/clone a process, and has no
numeric-PID fallback. Its exit event proves only the held thread group exited,
not that descendants are gone, a cgroup is empty or a DB slot may be released.
The genuine networkless Linux smoke passed (6 top-level/20 subcases, 85.9%,
zero skips; one top-level entry is the child-process helper). It exercised actual
child exit and retained handles, not forced PID reuse or a running OCI handler.
Runtime/CRI ownership, durable terminal evidence and cleanup wiring are still
required. The exact stopped test container was removed; v3 admission stays shut.

R18 R4 D09 adds `mountproof`: bounded mountinfo/fdinfo decoding, duplicate held
directory descriptors, kernel mount/device/inode/path/metadata re-observation,
exact tmpfs total-capacity checks and an overlay snapshot-description comparator.
It only reads its own procfs; no mount, remount, namespace entry or runtime call.
It rejects overmounts, nested mounts, drift, unknown overlay options and
unapproved propagation. Directory ancestry must already be trusted by the caller.
The genuine networkless Linux smoke test passed (10 top-level/60 subcases,
93.5%, zero skips); the run-owned container was stopped and removed. This proves
the tmpfs/descriptor path, **not** live containerd overlay provenance. The strict
overlay path currently expects absolute layer paths and private mounts; actual
platform compatibility, large-layer path compaction and shared-source mounts
must not be silently treated as verified. Full OCI, held execution bundle,
runtime lifecycle and final fences are still required; admission stays closed.

R18 R4 D08 adds `kubeproof` and `kubequery`: exact Pod/Job identity, signed grant
comparison, current assignment/owner/lifecycle/spec checks and a fixed HTTPS
GET-only namespace reader. TLS uses an explicit CA/server name and limited
identity; there is no kubeconfig, ambient proxy, redirect, retry, list/write or
admin fallback. Responses are bounded and never logged. Resource versions are
opaque: normal status updates do not masquerade as security-spec drift.
`runtimequery.ReadLiveProvenance` now assembles API-before/CRI-image-snapshot/
API-after under the original deadline. The actual limited-identity API and
Linux daemon round trip remain NOT_RUN, not covered by synthetic success APIs.
Pure metadata/real Ed25519 and Python-vs-Go hash checks are separate evidence.
This source chain does not complete full OCI/held-rootfs checks, execution,
coordinator cancellation fencing, capability or attach. New admission is closed.

R18 R4 D06 adds `runtimecmd`: a bounded parser for the pinned shim's explicit
create/start/state/kill/delete/stats/ps syntax and isolated version/features
queries. It rejects arbitrary runtime verbs, extra flags, cross-container paths
and non-termination signals. `journal.LookupContainer` recovers only an existing
pair binding, including uncertain/deleted historical states, without granting a
new start or treating journal state as proof of a stopped process.

R18 R4 D07 adds `trustedfs`: root-only production directory traversal, retained
ancestor/file descriptors, bounded read-only snapshots and content/metadata/
inode rechecks. Symlink/hardlink and named file/directory replacements fail.
Host tests and a real, networkless Linux/arm64 test container exercised source
file handling (including the production root entry). This still does NOT lock
an immutable execution bundle, prove rootfs mounts or make runc use these bytes.
No runtime handler entry point or v3 admission has been enabled.

R18 R3 D09 adds a Linux-only, fixed read-only Snapshot.Mounts client under
`runtimequery/`: Go stdlib HTTP2 over a held-root Unix socket, root peer and daemon
executable hash verification, bounded strict protobuf/gRPC decoding. It does NOT
call `ctr snapshots mounts` (which can activate mounts), accept arbitrary RPCs,
create resources or establish complete rootfs provenance by itself. Local codec
tests and Linux cross-compilation do not prove successful containerd operation.

R18 R4 D04 adds exact Container/Get and Sandbox Store/Get. `ReadPairMetadata`
uses authenticated daemon reads and re-observes both records; `IdentifyPairRole`
cross-checks CRI kind, versioned extensions, Pod name/namespace/UID, runtime and
the original parser's sandbox link. It never trusts a caller's role annotation.
The public CRI sandbox status store is populated only after successful startup
in containerd2.3.1, so it cannot be the pre-start authorization prerequisite.
These durable records do not prove Running/Stopped and do not replace image,
rootfs, full OCI, live API, grant or held-descriptor execution checks.
All queries remain read-only and fixed-method; no arbitrary RPC/list/exec path.

R18 R4 D05 adds an exact Images/Get + bounded Content/Read metadata chain. The
target/config digests are independent pins; raw SHA256/size, unique Linux
manifest selection, config rootfs diffIDs/ChainID and active Snapshot/Stat parent
are cross-checked. `ReadProvenance` derives the role from actual CRI metadata,
selects that role's pins, then re-observes metadata and Mounts for drift.
It never pulls/imports images, reads layers, follows content URLs, activates
mounts, accepts artifacts or outputs image config/Env to logs. Metadata readers
still do not prove mounted rootfs contents or replace held-FD/API/OCI checks.
Local hash/codec tests and Linux cross-compilation are not daemon acceptance.

R18 R4 explicitly approved one signed work/Pod/node pair with exactly one sandbox
and one parser, never an unconditional sandbox exemption. `grant/v3.go` and
`sign-v3` use a separate domain and fixed sandbox pins. `journal.OpenPair` uses
version2 records in a separate pair-journal.jsonl; legacy bytes are untouched.
Each role, Pod/work and container ID is once-bound. Local journal Running is not
CRI evidence; the still-incomplete node handler must independently validate it.
See CHG-305-R18-R4-EXECUTION-RESULT.md for actual tests and remaining gaps.

The `grant` package implements signed issuance and strict private-wire verification.
The `journal` package implements private durable intents, nonce/container reuse
rejection, OS-level writer exclusion and append-only recovery. These are separate
primitives, not a working runtime handler. Journal states are not proof that a
container started/stopped and cannot release any application DB slot.
The `ocidelta` package computes the four approved namespace/PID/swap/work-bind
changes without I/O; it preserves all unrelated JSON values and rejects ambiguous
input or CPU/memory drift. OCI memory-plus-swap is set equal to memory.limit for
zero swap. It is NOT a full OCI profile validator: preservation of an unknown
field does not authorize it. Never execute its output without the separate full
profile, live API/CRI/grant, mount-capacity and held-descriptor checks.
Passing its local real-crypto tests does not prove Pod identity, exclusivity,
replay protection, runtime enforcement or any R18 integrated acceptance case.

Protocol: ASCII-only machine metadata, canonical sorted-key compact JSON,
integer-only numbers, duplicate/unknown/missing fields rejected. An envelope has
exactly `payload` (standard padded base64 of canonical JSON) and `signature`
(base64 Ed25519 signature over `nomosmart/pdf-start-grant/v1\0` + payload bytes).
Key ID is SHA256 of the Ed25519 public key. No document content or credentials.
The public key comes from trusted deployment configuration, never the envelope.
Every binding field must match independently obtained live evidence. TTL ≤120s,
issued/not-before equality and ≤5s future skew, no expiry grace.

Coordinator issuance/key-loading/gated Pod update source and schema5 records are
now wired, but guarded live admission stays disabled. Full implementation needs
live API/CRI identity checks, node journal integration/replay fencing, full OCI policy
validation and same-bundle descriptor enforcement around the delta primitive,
runtime lifecycle, dedicated handler installation, capability binding and all
real platform tests. Do not configure `BinaryName` to this directory or bypass the
existing capability gate. Docker and all existing application paths are unchanged.

Toolchain selected from the existing local installation: Go1.26.5 darwin/arm64,
compiler command SHA256 `3f947495f00cb7f8088a5cfd694da8dc43869b33f5e7377b048fb18922ffb7e0`.
Stdlib only; execute with GOTOOLCHAIN=local, GOENV=off, GOPROXY=off, GOSUMDB=off.
Runtime Linux/arm64 binary/toolchain provenance must be bound before deployment;
the host command hash alone is not complete compiler or cross-build attestation.

R18 R2 local tests use real private files, fsync, cross-process locks, writer
SIGKILL/reopen, strict corruption rejection, synthetic machine metadata and actual
Ed25519. They do not simulate a successful Kubernetes API or PDF result. A detected
in-root symlink issue was fixed using descriptor-relative entry/descriptor identity
checks; initial failure evidence is preserved. See the R18 R2 execution report
for exact scope and results. Full Linux node, runtime, permission and isolation
acceptance remains outstanding; no capability receipt or installer is supplied.

`backend/scripts/chg305_r18_r2/verify_guard.py` runs host primitive regression,
race detection, vet, bounded pure-data fuzzing and Linux/arm64 cross-compilation.
Pure OCI contract inputs are not simulated service responses; passing them proves
neither kernel limits nor Kubernetes compatibility. No automatic handler activation.

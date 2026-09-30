# Independent PDF OCI profile recipe

> Historical / retired by CHG-305 R20 (2026-09-23). This document preserves prior
> design and evidence only; referenced container code and tools have been retired.
> Do not run these installation or recovery commands. The current Worker-local
> implementation and verification limits are in docs/CHG-305-R20-SOURCE-HANDOFF.md
> at the repository root. Source retirement did not uninstall any live resources.

Build-only companion for CHG-305 R18 R5 W1. It must never learn expected OCI
fields from a candidate container, daemon OCI record or runtime bundle.

The separate Go module uses pinned upstream containerd options. The nested
module path allows Go `internal` imports; this is NomoSmart code, not an
official containerd tool. It is not a dependency of `pdf_start_guard`.

`source-lock.json` pins the reviewed upstream OCI/CRI and Kubelet source files.
`backend/scripts/chg305_r18_r4/build_profile_recipe.py` verifies module trees,
reviewed sources and the fixed compiler, then produces two equal Linux/arm64
binaries offline. Input provenance must still be gathered independently from
the installed node/configuration and content-addressed image metadata. No
profile produced here by itself authorizes deployment or establishes runtime PASS.

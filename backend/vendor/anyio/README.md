# AnyIO downstream worker-stderr repair

**REJECTED CANDIDATE — DO NOT INSTALL OR SHIP.** R4 Linux testing removed the
raw-fd2 deadlock but exposed AttributeError in AnyIO's shutdown callback, which
unconditionally dereferences stderr even when DEVNULL means no stream exists.
Formal pyproject/lock/Dockerfile adoption was withdrawn. The artifact is retained
only as reproducible diagnostic evidence; no current workload uses it.

`4.14.2+nomosmart.1` is NomoSmart's minimal **wheel-derived** downstream package,
not an upstream release or a source-distribution build. The only behavioral
change explicitly connects the process-pool worker's OS stderr to DEVNULL.
It prevents an unread stderr PIPE filling up during direct fd2 writes; stdout's
worker protocol, the parent stderr and other subprocess APIs are unchanged.

`provenance.json` records the fixed official URL/hash, every input/output member,
builder/patch/license hashes and the generated artifact hash. All other package
bytes are preserved; the dist-info local version and RECORD are updated.

Rebuild twice in separate empty directories with Python3.12:

```sh
python backend/scripts/chg304_r4_anyio_wheel.py /path/to/anyio-4.14.2-py3-none-any.whl /private/tmp/empty-build-directory
```

An isolated candidate `uv sync --frozen --no-dev --no-editable` installed this
relative wheel normally, but it was NOT accepted for Backend delivery. The
repository remains on official4.14.2; there is no vendor COPY in the Dockerfile.
Any later adoption requires a separately approved, fully tested lifecycle repair.
Do not hand-patch site-packages or override imports with a wheel PYTHONPATH.

Security scanners may not identify a local version. UNKNOWN is not a clean scan;
compare upstream4.14.2 advisories and this exact diff explicitly. NomoSmart owns
ongoing patch maintenance; remove it only after an independently verified upstream
equivalent and the unchanged raw-fd2/TLS/group-denial/lifecycle regressions pass.
This change alone does not approve a release or deployment.

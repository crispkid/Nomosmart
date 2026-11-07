# AnyIO 4.14.2+nomosmart.2 — CHG-304 R5

This is a wheel-derived downstream build, **not an official AnyIO release**.
Upstream wheel, every input/output member, builder/validator, two-site patch and
MIT license hashes are recorded in `provenance.json`. The upstream license is
also included inside the wheel. The rejected `.1` artifact in the parent directory
is historical only; the application lock and Docker COPY select this `.2` folder.

Changes are limited to worker stderr → DEVNULL and an optional-stderr guard in
forced asyncio shutdown. Worker kill/watcher cleanup, stdin/stdout protocol,
ordinary subprocess output and parent stderr remain intact. No files in existing
Python environments were manually overwritten.

Reproduce twice into separate **new** directories using the official wheel whose
SHA256 is `9f505dda5ac9f0c8309b5e8bd445a8c2bf7246f3ce950121e45ea15bc41d1494`:

```sh
python3 backend/scripts/chg304_r5_anyio_wheel.py OFFICIAL_WHEEL NEW_OUTPUT_DIR
```

Expected output SHA256:
`be38c4b59b4129d0f4c8a2e42a868faa4cfe7781a3d560da2e2f0e7625a58e3a`.
ZIP ordering/timestamps/modes/compression are fixed. Normal `uv sync --frozen
--no-dev --no-editable` installs the locked local wheel; do not use PYTHONPATH to
shadow AnyIO. Other61third-party lock entries/62versions remain unchanged.

Local verification: original6 + strict lifecycle4 + real uvloop4 passed twice in
non-root Linux containers; source-bound API/S3/PG/OIDC/natural expiry also passed.
See `docs/CHG-304-R5-LIFECYCLE-PDF-REPAIR-RESULT.md` for limits and full evidence.
PyPI audit cannot identify this local version: its assessment remains UNKNOWN.
Upstream4.14.2 and53otherinstalled packages had no reported known vulnerabilities
at the recorded check; that is not a guarantee of safety for this downstream build.
Maintain/review these two hunks until an official compatible release can replace
them under a separately approved dependency update. No image/deploy acceptance
or complete80%coverage is claimed by this artifact.

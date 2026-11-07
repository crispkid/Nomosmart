# NomoSmart downstream python-multipart 0.0.32+nomosmart.1

This is **not an official python-multipart release**. CHG-305 R20 R19 R23 R1
adds bounded closing-boundary confirmation for NomoSmart's existing byte-exact
near-boundary compatibility. This is not a claim of an upstream CVE or an RFC
guarantee that arbitrary boundary collisions must be accepted.

The official 0.0.32 wheel is the sole input. See `provenance.json` for its URL,
SHA-256, every input/output member hash, builder/validator hashes and patch hash.
The original Apache-2.0 license is preserved in `LICENSE` and inside the wheel.

## Behavior

- Delay part/end callbacks until a complete closing delimiter is confirmed by
  CRLF or valid EOF; reject incomplete framing at finalization.
- Return a false closing candidate to file data exactly once, including across
  writes and overlapping prefixes. Do not retain the file body in memory.
- Bound optional trailing space/tab lookahead: default 16 KiB, permitted
  configuration 0–64 KiB. NomoSmart uses its existing part-header allowance.
- Ordinary part/header parsing is unchanged. `boundary.patch` shows all parser
  changes. Other changes are version metadata and wheel integrity records only.

## Reproduction and installation

Run from the repository root, with a verified official wheel and a **new** output
directory for each build:

```sh
python3 backend/scripts/chg305_r23_r1_multipart_wheel.py \
  /path/to/python_multipart-0.0.32-py3-none-any.whl /path/to/new-output
```

Official input SHA-256:
`ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23`.
Expected output SHA-256:
`50ea368e317d8db958a2714fc643e1aa57fc6bd310c41d4bb9de42388b1e8f5c`.
Two independent builds must match. Do not modify installed site-packages.
`backend/pyproject.toml` and `uv.lock` pin this local wheel; normal frozen uv
installation and the existing Dockerfile install it through the package manager.

## Verification and maintenance

Regression tests are `tests/test_chg305_r23_r1_multipart_boundary.py`, the
unchanged `test_boundary_like_bytes_remain_content` assertion, and existing
multipart/DOCX tests. Integration, memory and release gates remain separate;
parser regression success alone is not deployment approval.

Owner: NomoSmart Backend maintainers. Review future upstream fixes before
replacing this fork. Scanners may not recognize the local version: report that
as UNKNOWN, not vulnerability-free. Provenance hashes establish integrity,
not an upstream signature or a security guarantee.

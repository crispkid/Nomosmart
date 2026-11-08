# CHG-422 integration decisions

The approved settings specification is preserved in CHG-422-SYSTEM-SETTINGS-SPEC.md to avoid collisions with published historical change numbers. REL422 governs its NativeOCR adaptation: the active request-output budget replaces the legacy page editor; the legacy GET field and refusal semantics remain. Coverage is informational per Peter. Existing v0.2.3 NativeOCR and v5 controls are the baseline.

Three-way integration exposed duplicated functions and missing imports. Corrections preserve published strict governance readiness and the approved content-update pipeline; they complete the previously approved real batch-run polling rather than creating success responses. Settings CSS is carried as its own scoped block. Fresh bootstrap also checks the active native request parameter. No authentication success, model response, cleanup, or migration history is seeded.

Verification: pending genuine API, UI, upgrade and lifecycle acceptance. TypeScript, ESLint and production frontend compilation passed on the integration snapshot; static checks do not establish runtime acceptance.

## Application image security merge, before rebuild

The published Native Dockerfiles are retained. Carry forward only the already verified CHG-391 application-image library repairs: Alpine zlib 1.4-r0; Noble PCRE2 10.42-4ubuntu2.2, perl-base 5.38.2-3.2ubuntu0.6 and zlib1g 1:1.3.dfsg-3.1ubuntu2.3. Preserve the newer published npm 11.21.1 and explicit undici 6.29.1, plus uv 0.13.4. Do not reintroduce LocalPDF/Tesseract/Poppler/Bubblewrap. These are NomoSmart-owned image inputs, not peripheral software changes. Validate by exact dual-platform builds, scans, SBOM and application regressions. No new risk acceptance.

# CHG-422 integration decisions

The approved settings specification is preserved in CHG-422-SYSTEM-SETTINGS-SPEC.md to avoid collisions with published historical change numbers. REL422 governs its NativeOCR adaptation: the active request-output budget replaces the legacy page editor; the legacy GET field and refusal semantics remain. Coverage is informational per Peter. Existing v0.2.3 NativeOCR and v5 controls are the baseline.

Three-way integration exposed duplicated functions and missing imports. Corrections preserve published strict governance readiness and the approved content-update pipeline; they complete the previously approved real batch-run polling rather than creating success responses. Settings CSS is carried as its own scoped block. Fresh bootstrap also checks the active native request parameter. No authentication success, model response, cleanup, or migration history is seeded.

Verification: pending genuine API, UI, upgrade and lifecycle acceptance. TypeScript, ESLint and production frontend compilation passed on the integration snapshot; static checks do not establish runtime acceptance.

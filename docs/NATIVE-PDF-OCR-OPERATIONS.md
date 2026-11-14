# Native PDF document recognition operations

CHG-410 replaces new local PDF parsing and page-image OCR with raw-PDF document
recognition. Historical jobs, model references, usage and receipts remain readable.
This guide does not authorize a deployment or modify the 8443 test environment.

## Model setup

Create or reselect an active OCR model using the supported OpenAI Responses
protocol. Set the actual model and service connection in system management; no
model is selected by inference from its name. Use the PDF capability form to
enter the explicitly declared values for that exact model. They are saved in
the same `native_pdf` object; do not duplicate conflicting values in advanced JSON:

- `protocol`: `openai_responses`; `supports_pdf`: `true`.
- `mime_types`: `["application/pdf"]`; `count_input_tokens`: `true`.
- Positive `max_input_bytes`, `max_request_bytes`, `max_response_bytes`,
  `context_window`, `max_output_tokens`; positive `min_output_tokens` not exceeding the declared output maximum.

These are model capability declarations, not deployment byte-limit defaults.
Missing or unsupported capability declarations are rejected. A valid declaration
is not proof of a successful PDF request; the ordinary connection probe is separate. Existing local/HTTP OCR models
are retained for historical references and need explicit reselection for new PDF
work. Do not replace historical model or job snapshots to make old work runnable.
Configure input/output prices per million tokens and a currency; historical page
and image charges are not converted. Keep provider credentials in their existing
secret fields or secret references, never in the capability JSON.

The model's `max_output_tokens` must be at least the system parameter
`ocr_request_max_output_tokens` (128000 after a new installation); a smaller
declaration fails recognition with `ocr_native_output_limit_invalid`. Changing a
model's capabilities does not affect a document whose recognition already
started: its run keeps the earlier snapshot, so upload the document again.

The connection test checks the capability declaration, confirms the model exists
and calls the provider's input-token count endpoint with a short text. It does not
send a recognition request.

## Before the first upload

A new installation must initialize the file-processing policy before any upload
or extraction can run. Until then uploads fail with
`file_processing_policy_missing` and System management > Status shows the
`file_processing_policy` item as degraded. Follow
[File-processing policy initialization](../deploy/README.md#file-processing-policy-initialization-new-installations)
for the Docker Compose and Helm commands.

## Limits and processing

Runtime transport ceilings are external settings:

| Setting | Example deployment ceiling |
| --- | ---: |
| `NOMOSMART_OCR_MAX_INPUT_BYTES` | 45000000 |
| `NOMOSMART_OCR_MAX_REQUEST_BYTES` | 67108864 |
| `NOMOSMART_OCR_MAX_RESPONSE_BYTES` | 8388608 |
| `NOMOSMART_OCR_DOCUMENT_TIMEOUT_SECONDS` | 120 |

The tighter configured/model limit applies. The request-size limit includes the
base64 request body. Oversize documents are rejected; ask for a smaller file or a
model with verified larger capacity. There is no automatic splitting, local text
extraction, page rasterization, or provider fallback. TXT and Markdown bypass OCR.

System parameters own `ocr_request_max_output_tokens` and
`ocr_document_max_tokens`. Initial migration sets the request limit to the lesser
of 128000 and the existing document budget, preserving the latter. New work takes
a versioned snapshot. The old page limit remains readable for history; a changed
legacy page field is rejected. Saves use the current settings hash to prevent
silently overwriting another administrator's update.

The service counts the exact model/input before generation and checks context
plus the requested output. Counting sends the original document to the provider
and may incur charges. Generation uses base64 input, `store=false` and
`truncation=disabled`; it does not create Files API objects. Only a completed,
nonempty Markdown result with confirmed usage and a valid work claim is accepted.

## Provenance and recovery

New PDF output has document-level provenance: unknown physical page count,
`page_map_status=unknown`, empty page ranges, and no inferred chunk page numbers.
Use real processing stages and request state instead of page percentages. The
historical page-image display remains available for older work.

A durable document receipt is reserved before a paid call. Unconfirmed intent,
timeout or unknown response must not be automatically replayed. Reconcile the
existing receipt and usage first. Cancellation or an incomplete response retains
confirmed usage even when the content is not accepted. Do not delete receipts or
change snapshots to force recovery. Old in-progress or page-image jobs require
explicit review rather than silent conversion.

## Deployment scope

Current backend images omit Tesseract, Poppler and bubblewrap. Compose/Helm omit
their command variables and per-page scratch volume. Python, upload storage,
Worker/Beat, task claims, cancellation, generic admission/concurrency, secret/CA
mounts and service security controls remain required. Optional
`CELERY_GLOBAL_KEYPREFIX` isolates Redis keys; blank preserves the existing
namespace. Retired source and original test failures remain historical evidence,
not passing evidence for the new model path.


## Versioned document policy and project status

V056 preserves all old13-field policy revisions and their hashes, adds version2,
and imports existing effective values without increasing time/concurrency limits:
`document_processing_max_concurrent`, `document_processing_timeout_seconds`,
`document_dispatch_yield_delay_seconds`, `file_processing_progress_interval_seconds`,
`file_processing_background_poll_interval_seconds`. Yield delay is queue scheduling,
not permission to replay a paid request. Retired parser keys are history-only;
unchanged old fields are compatible, conflicting or changed retired fields fail.
An uninitialized deployment still requires authenticated operator initialization.

Valid Chat/Embedding configuration is separate from PDF model eligibility. The
project filter `model_state=complete` now means basic configuration; optional
`pdf_model_state=configured|not_configured|invalid` selects PDF capability. Neither
state certifies connectivity or provider success. TXT/Markdown do not require OCR.

Reports distinguish native document counts from historical pages/images. Unknown
and partly unknown values are labelled in both the UI and localized CSV; original
accounting amounts are never rewritten or converted to zero.

## Archive safety and recovery

Archive checks work/paid-call quiescence before external deletion. Active work,
unconfirmed stop or an unresolved call blocks content cleanup. Eligible unfinished
content may be removed only after those guards pass; original receipt document,
version, run and step UUIDs, fingerprints and accounting remain immutable. The
four live content relationships can then be detached with cleanup audit. A removed
content marker is not a successful download or evidence that no fee occurred.

Upgrade requires coordinated API/Worker code and additive V056 after V055. Stop
old writers, retain an encrypted pre-upgrade snapshot and verify migration on an
owned clone first. Do not run old Workers against version2 policy or downgrade by
dropping receipt columns/tables. Recovery tests restore the055 snapshot to an
isolated database with old API read-only and Workers stopped; this is not proof
of full operational rollback or authorization to modify8443.

## Verification boundary

Historical410/411 outcomes and original failures remain in repository acceptance
records. A successful OCR receipt does not prove the full downstream pipeline,
coverage, deployment matrix or release. Current412 scoped results must identify
source hashes, actual provider usage, teardown and remaining gaps separately.
Current releases follow CHG-419 risk-based quality: all applicable critical
normal/denial/error/data-preservation scenarios require valid source-bound evidence.
Complete-source coverage measurement remains required; 80% is an advisory improvement
target. Retain actual full-suite statistics and historical failures, and reuse
qualified unaffected evidence. Signed candidate integrity and accepted security
conditions remain mandatory; local acceptance does not qualify deferred production
platforms. Use the external-services bootstrap profile for existing stores;
never change shared identities or forge readiness evidence to make a test pass.

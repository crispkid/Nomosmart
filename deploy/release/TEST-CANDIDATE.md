# Unqualified protocol test candidate / 協定安裝測試候選

Schema 5 is local test material. It is never a release, a trusted signature, or a
replacement for full tests, security review, separate 80% coverage, or schema 4.
Existing `verify-package` purposes reject it. SHA256 verifies content only;
`authenticity=not_verified` and all release qualification flags remain false.

Schema 5 僅供已核准的本機隔離驗證；不能作正式發布包。既有正式驗證入口
一律拒絕。校驗正確不代表可信簽章，未完成門檻仍列在 `pending_requirements`。

Create one candidate from a clean detached packaging commit and real retained
image build materials:

```sh
deploy/release/nomosmart-release assemble-test-candidate \
  --repo PATH --commit FULL_COMMIT --release-id VERSION \
  --candidate-id VERSION-test-SCOPE --materials PRIVATE_JSON --output-dir PRIVATE_DIRECTORY
deploy/release/nomosmart-release verify-test-candidate --package ABSOLUTE_DIRECTORY
```

The owner-only intake has version 1, `platforms_file`, and `components` (frontend
and backend, each specifying `build_inputs_file`, `multi_archive_file`, and
`blob_verification_file`). These refer to genuine retained, content-bound build
and OCI materials. `pending_requirements` contains every mandatory gate with an
unqualified status and explanation. `observations` retain original commands,
sources, actual exits and structured native Docker execution receipts. Their
`raw` entries specify a public JSON `name`, private input `file`, and `sha256`.
Only sanitized receipts may be supplied. Operator configuration, credentials,
business data, private diagnostic logs, and scope files must remain outside the
package. Existing application image bytes are reused only when every original
build input and executable flag still matches.

`image_build_source` records frontend and backend separately. An unchanged
component keeps its original build source, labels and scan identity when the
other component requires a repair. Protocol external-services bootstrap verifies
existing service identities and buckets; it does not provision/reset external
accounts, roles or storage, and does not mount external administrator passwords.

Intake需為本人專用檔案；輸出目錄也只允許本人存取。原映像的build source與
打包工具的source分開保存；不更改舊映像label，也不重建未受影響的應用。

Test installation additionally requires `[test_candidate]` in the target TOML
(`package_dir`, retained `archive`, and exact `platform`) and the explicit
`--test-candidate-scope PRIVATE_JSON` argument. `[release]` and `[test_candidate]`
are mutually exclusive. The packaged chart and exact application/migration
images are mandatory. Scope verification binds the human-approved plan and
resource proposal hashes, candidate/manifest/archive, target configuration,
operation, context, an existing namespace UID/owner/creation time and fixed
lease. It runs before mutations; the final cleanup interval cannot start new
application operations. A closed, changed, expired, missing or mismatched scope
fails without a fallback. The ordinary engineering-source route also rejects a
schema 5 packaged chart. Neither the installer nor verifier implicitly extracts
an archive.

測試安裝必須明確指定scope，並綁定既有且有歸屬的隔離namespace；不能隨意
建立其他目標。核准不等於簽署或正式平台合格；對外發布仍是獨立決定。

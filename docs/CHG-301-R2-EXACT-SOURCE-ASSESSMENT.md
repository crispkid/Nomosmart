# CHG-301 R2：兩項告警的固定來源適用性判定

2026-09-16（Asia/Taipei）。Peter要求「先完成驗證吧」；維持先驗證、後更新PR。
本輪只續做已核准CMPPATCH-001/003的公開來源與實物靜態分析，沒有修改產品程式、
重建映像或啟動服務。狀態：**兩項均有不受影響的提議證據，正式排除尚待Peter確認**。
這不是風險豁免、VEX已套用、Kubernetes通過或完整R2完成。

## 1. 結論與範圍

| 告警 | 原始掃描 | 本輪判定 | 理由 |
| --- | --- | --- | --- |
| CVE-2025-15558 | High | PROPOSED_NOT_AFFECTED | 官方限定Windows CLI plugin manager；本映像是Linux/ARM64，實際docker/cli為29.7.2，晚於修正版29.2.0。 |
| GO-2026-5932 | Unspecified | PROPOSED_NOT_AFFECTED，原為INDETERMINATE | 與官方發行binary、vcs commit及依賴checksum綁定的完整Linux/ARM64來源import closure共2,647個packages，沒有OpenPGP及其子套件。不是以字串搜尋未命中推定安全。 |

Go公告針對`golang.org/x/crypto/openpgp`及其子套件，不是整個`x/crypto`模組。
本程式確實使用同模組的bcrypt、ocsp、ssh等19個package，但沒有OpenPGP。
這解釋了為何module-level掃描仍可列出告警，卻不能單憑模組存在判定漏洞適用。

適用性提議**僅限以下同一份本機測試映像**：

```text
nomosmart-test/traefik:3.7.13-chg301-r2-say0hh9k
image / ARM64 manifest:
sha256:5043ce31721c19e4a3a18afd60f449a7c842d46a52ec1ed6d7fdfb84a68cf7cd
Traefik binary:
sha256:7415b6155dfd70f4d8ec8dd6092ec4534e016baa5f051d44f179f7b4780878ca
source commit:
fc92cc118a0557a029c7019d5ee06665127b0f13
```

不擴及其他映像、Windows版、Go dependency版本或新告警；不啟用本地/下載式/動態
Traefik plugins。映像、binary、來源、dependency、build target或plugin組態變更即
須重新評估。既有94項guard與10项OpenSSL修補證據保持原範圍，不宣稱本轮新增94PASS。

## 2. 證據链

1. 原已驗證OCI的Traefik binary SHA不變；Go build info記錄Go1.26.8、
   linux/arm64、CGO=0、GOARM64=v8.0及上述vcs commit，`vcs.modified=false`。
2. 僅下載此固定commit的官方source archive；2,277個regular files共32,768,841bytes。
   拒絕越界path、symlink及過大檔案，不執行source、`go generate`、build或release腳本。
   archive內go.mod/go.sum與同commit官方raw檔逐byte一致。
3. 使用既有Go1.26.5執行`go list -deps -json ./cmd/traefik`，明確指定linux/arm64、
   CGO=0、GOARM64=v8.0、GOWORK=off、GOTOOLCHAIN=local、-mod=readonly。
   私有module/cache目錄；GOAUTH=off、GOVCS=*:off，僅官方Go proxy/checksum服務。
   不讀現行env/credential、不編譯/執行Traefik、不自動下載新Go。
4. 真實命令exit0；2,647個packages無Error/DepsErrors/Incomplete，所有import edges
   都可解析，從main走訪得到完全相同集合；其中OpenPGP及全部子套件為0。
5. binary有356個dependency entries：355個外部module的實際版本、replacement及
   h1 checksum全部一致。另一個是`./pkg/config/dynamic/ext`，binary顯示`(devel)`、
   Go list本地module版本欄空白；沒有把此表示差異假稱外部版本一致。
   該本地module的ext.go/go.mod都在同commit archive中並保留逐檔SHA。
   source額外的第357個module只為Traefik主module，不是新增dependency。
6. `go mod verify`最後exit0，`all modules verified`。第一次GOPROXY=off因缺少
   未在main import closure使用的dario.cat/mergo固定版本metadata而停止；保留原始
   exit1。補取原go.mod所指定的公開metadata後重驗，沒有升級或修改go.mod/go.sum。
7. 從官方v3.7.13 Release取得ARM64 archive；archive SHA同時符合Release asset digest
   及官方checksums檔。只讀archive內單一Traefik檔案，不extractall/執行；其SHA與
   image binary完全一致。GitHub commit API亦回傳同commit及verified=true。
8. 同commit release build template的main、CGO、target、trimpath與觀測一致，沒有額外
   Go build tags；`go generate`來源只產生文件，不在本輪執行。全部source檔案分析前後不變。

## 3. 必須保留的限制

- 原govulncheck零symbols的結果仍然成立；本輪是**固定來源的完整package依賴證據**，
  不是已取得binary call graph，也不是改寫原失敗為成功。
- 原binary由Go1.26.8編譯；來源分析使用既有Go1.26.5，target及release tags一致，
  但沒有做同toolchain逐byte可重現重建。公開Release/hash/commit/build metadata
  是來源綁定證據，不冒充本地驗證過的reproducible-build attestation。
- 未啟用外部plugins的限定重要；不能將本判定延伸到任意動態載入的程式碼。
- 本輪沒有重新掃描整份映像。前輪SARIF/SPDX及兩項raw severity保留，沒有suppress、
  VEX或正式排除。其他R2資安/coverage/critical-flow/清理要求沒有被豁免。

## 4. 實際驗證與保留資料

| 檢查 | 結果 |
| --- | --- |
| 固定commit archive/raw go.mod/go.sum | PASS |
| 來源`go list -deps -json`、完整closure與零OpenPGP | PASS，2,647 packages |
| 355個外部dependency版本/checksum與本地module provenance | PASS，差異表示已列明 |
| `go mod verify` | 初次離線BLOCKED；補固定公開metadata後PASS |
| 官方release asset/checksums/binary/image綁定 | PASS |
| source前後逐檔hash | PASS，2,277 files unchanged |
| controller smoke、Kubernetes、Frontend/Backend完整coverage | NOT RUN in this continuation；完整R2仍未完成 |
| 新Docker/Helm/Provider/PR操作 | 0 |

機器證據：[去敏感摘要](CHG-301-R2-EXACT-SOURCE-EVIDENCE.json)。
私有原始JSON、import graph、公開source/release archives及module checksum證據
保留於本輪0700暫存目錄，約116MiB；沒有現行設定、credential或應用資料。
已核對exact-owned path/inode並以明確私有GOMODCACHE/GOCACHE執行Go clean，
清除約1.8GiB可重新下載的module cache與34MiB分析cache；原Go cache未讀寫。
原6小時批次期限沒有重置。

規格§10.58 CMPPATCH-001/003保持不變；只補實際分析證據及traceability。
收尾`spec:doctor`、`spec:trace`（21 mappings）、`plan:approved`（含plan doctor）、
`test:plan`、`git diff --check`全部通過；不把治理PASS當作候選安全放行。

## 5. 尚需的精確確認

原核准明確要求由Peter確認適用性排除，`先完成驗證吧`不是漏洞豁免。
建議Peter接受本文件限定映像與上述證據/限制，將**這兩項**列為不適用，保留raw
報告，解除這兩項對隔離測試候選的阻擋；不改其他security gate、不接受新漏洞。

此確認不核准現行部署、PR更新/merge、Provider或新增產品修改；後續nonroot/
network-none smoke及獨立Kubernetes實測仍須遵守原R2計畫的來源、資源、安全與時間
前置條件。效力不超過原批次期限2026-09-15T20:17:52.088462Z（台北09/16 04:17:52）；
沒有額外6小時或重試預算，逾期須另行討論後續執行窗。

可確認：`核准 CHG-301 R2 固定測試映像的兩項不適用判定，接受文件所列證據限制，僅供原計畫的隔離驗證。`

## 官方依據

- [Docker CLI公告](https://github.com/docker/cli/security/advisories/GHSA-p436-gjf2-799p)
- [Go OpenPGP公告](https://pkg.go.dev/vuln/GO-2026-5932)
- [固定Traefik來源commit](https://github.com/traefik/traefik/tree/fc92cc118a0557a029c7019d5ee06665127b0f13)
- [v3.7.13官方Release](https://github.com/traefik/traefik/releases/tag/v3.7.13)
- [固定官方image recipe](https://github.com/traefik/traefik-library-image/blob/06814bb30ce37fe65a09268ea792eec6e037dff5/v3.7/alpine/Dockerfile)

# CHG-301 R2：節點與基礎映像靜態盤點結果

2026-09-16 Asia/Taipei。對應規格 §10.58 CMPNODE-001..005。
Peter 已核准[靜態判定計畫](CHG-301-R2-NODE-QUALIFICATION-PLAN.md)；本報告**不是修補、建置或叢集執行核准**。

## 1. 結論先看

**已完成固定映像清單、原 59 項帳列、12 份額外映像掃描及 Debian 官方材料索引核對；完整適用性與修補相依閉包仍未完成。**
整體狀態為 `PARTIAL_RUNTIME_BLOCKED`，不能宣稱映像安全通過或完整 R2 驗收完成。

- 原 59 項：30 項「套件版本需修補」、1 項「有不適用證據但尚未核准」、28 項「適用性未確定」。
- 30 項是保守的已安裝套件／版本判定，**不是已實證 30 個可利用漏洞**；實際功能、呼叫與設定可達性仍有限制。
- 額外 12 份映像掃描已完成，留下 339 個「映像 × 告警」帳列，跨映像去重為 139 個 ID；不能加總成 339 個不同漏洞。逐映像原始 SARIF／SPDX 均綁定 ARM64 digest，個別來源閉包仍待核對。
- 新 guard/artifact suite：77 PASS。舊 134 項：133 PASS、1 FAIL（舊測試的當前核准假設失效，詳 §6）。
- 原有 14 個 Docker 容器的 ID／狀態／啟動時間／重啟次數及 image/network inventory 前後相同；產品來源沒有改動。
- 沒有建置、載入或啟動候選映像；沒有 Kubernetes／Helm server／Provider／PR 操作，也沒有新增豁免。

完整來源、雜湊、59 項材料與所有額外 ID 見[機器證據](CHG-301-R2-NODE-QUALIFICATION-EVIDENCE.json)。
大型原始報告留在私有目錄，不把 scanner 摘要冒充原始證據。

## 2. 固定清單與掃描結果

Node 固定 `kindest/node:v1.36.4`，index
`sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`，
ARM64 manifest
`sha256:10210eabcf5dc4b585756bbd3f7fbb60cc0a12a252f28aeba269d93e0070c025`。
兩個 layer 的 compressed digest／diff ID 均驗證，還原 6,319 個有效檔案紀錄；
沒有把 symlink、device 或 setuid 套用至主機。

本輪初始依固定 digest 取物；tag 的前置綁定沿用前輪研究，**不是本輪新做的前置 tag check**。
本輪後置 tag 查驗與固定 index 一致，此證據限制保留。

Node 外殼沿用前輪同 digest 真實掃描時間，不偽裝成重掃：10 Critical、40 High、
27 Medium、65 Low、9 未分類；151 個 ID、181 命中實例、534 個 SPDX 項目。
原始檔與[前輪評估](CHG-301-R2-NODE-REMEDIATION-RESEARCH.md) SHA 未變。

從實物 containerd CAS 找到 10 個 Linux/ARM64 預載映像；9 個列為啟用。
kindnet 精確 digest `aa67f22ca961…` 因既定 Cilium／停用 default CNI 而排除，沒有無聲省略。
四個 Kubernetes 元件角色有預載 index／config/history 來源，不靠猜測 tag。

| 啟用映像 | ARM64 digest 前綴 | Critical | High | Medium | Low | 未分類 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CoreDNS | `3c5a66ca0d50` | 9 | 38 | 27 | 1 | 5 |
| kube-apiserver | `3e32131d4115` | 1 | 13 | 6 | 1 | 1 |
| local-path helper | `4cdfa639b9ab` | 0 | 0 | 0 | 0 | 0 |
| local-path-provisioner | `7f1d529e9b26` | 1 | 3 | 7 | 1 | 2 |
| etcd | `82bf8bc50b9a` | 9 | 25 | 22 | 2 | 5 |
| kube-proxy | `af438ff68aa1` | 1 | 13 | 6 | 1 | 1 |
| kube-controller-manager | `b3720ba4eddd` | 1 | 13 | 6 | 1 | 1 |
| kube-scheduler | `bf7f78acdfbe` | 1 | 13 | 6 | 1 | 1 |
| pause | `e50b7059b633` | 0 | 0 | 0 | 0 | 0 |
| Cilium Envoy | `cb70c451a0ee` | 0 | 3 | 35 | 11 | 1 |
| Cilium agent／init | `6e55c1206ae4` | 1 | 12 | 5 | 1 | 3 |
| Cilium operator | `48f6d9ce9120` | 1 | 12 | 5 | 1 | 3 |

以上數字是逐映像 raw 結果，**0 告警也不等於 runtime 安全保證**。
預載映像透過 verified OCI directory 掃描，未 Docker load/pull；Cilium 使用固定 registry digest。

Cilium 官方 chart 1.20.1 SHA
`06210eef7c23d15f7699c79e2fe3a1ec9c389024c5c5c006ea04022d322449a2`，
9 個 image field 對應 agent／6 個 init／Envoy／operator，共 3 個 image digest。
離線 render 保留 kube-proxy，停用 Hubble，未產生 Secret 或 hook。
三個 lookup 出處已核對為未啟用分支；使用 `helm template --dry-run=client`、私有空 kubeconfig，
不是 server dry-run。[Cilium 官方 kind 指引](https://docs.cilium.io/en/stable/installation/kind/)、
[Helm template 文件](https://helm.sh/docs/helm/helm_template/)。

既有修補 Traefik 的 image ID／binary／raw SARIF／SPDX／接受文件重新核對；
兩项既有接受未擴張、不重設期限，本輪未重新執行它。其原始報告仍保留 High 與未分類告警。

## 3. 修補材料：三類處理

### A. 有官方更新材料，但還不能直接安裝

官方 Debian trixie 與 trixie-security InRelease 的 GPG 驗證、suite、有效期限（如提供）、
SHA256 → ARM64 Packages.xz 鏈已核對。17 筆索引候選包含不同 suite 的版本，不是17個必須更新的套件。

| Source family | 目前 source version | 官方 fixed candidate | 已安裝 binary package 範圍 |
| --- | --- | --- | --- |
| glibc | 2.41-12+deb13u3 | 2.41-12+deb13u4 | libc6、libc-bin |
| gzip | 1.13-1 | 1.13-1+deb13u1 | gzip |
| libevent | 2.1.12-stable-10 | 2.1.13-stable-1~deb13u1（security） | libevent-core-2.1-7t64 |
| libssh2 | 1.11.1-1+deb13u1 | 1.11.1-1+deb13u2 | libssh2-1t64 |
| openssl | 3.5.6-1~deb13u2 | 3.5.7-1~deb13u2 | libssl3t64、openssl、openssl-provider-legacy |
| pcre2 | 10.46-1~deb13u1 | 10.46-1~deb13u2 | libpcre2-8-0 |
| perl | 5.40.1-6 | 5.40.1-6+deb13u1 | perl-base |
| sqlite3 | 3.46.1-7+deb13u1 | 3.46.1-7+deb13u2 | libsqlite3-0 |

每一候選的 URL、SHA256、大小、Depends／Pre-Depends、release/index digest 與對應告警，
都列在機器證據的 `debianMaterialCandidates` 與 `nodeFindings[].materials`。
**尚未下載 deb payload、執行 solver、驗證完整相依閉包或重掃修補結果，不是可執行 lock。**
不把 libssh2 較舊 security 版本誤選為較新 fixed 版本，也不把 Perl 的獨立 Socket 套件版本套到 perl-base。

金鑰只寫入本輪私有 keyring；指紋取自 [Debian 官方 signing keys](https://ftp-master.debian.org/keys.html)。
遇到缺少 Debian 12 archive/security 簽署金鑰各停止一次，核對官方指紋後補入，
第三次完成兩個索引驗證；未忽略 NO_PUBKEY/BADSIG 或使用主機私人 keyring。
信任起點仍是官方 HTTPS＋公開指紋，**沒有獨立離線／第二管道信任驗證**。
索引來源：[trixie InRelease](https://deb.debian.org/debian/dists/trixie/InRelease)、
[trixie-security InRelease](https://security.debian.org/debian-security/dists/trixie-security/InRelease)。

### B. 有不適用證據，仍待精確核准

僅提出 `CVE-2026-8376`：官方公告的必要條件為 32-bit Perl build；
實物 `usr/bin/perl` 為 ELF64 ARM64，Config.pm／Config_heavy.pl 的
ivsize、ptrsize、sizesize 都為8。binary及兩份設定 SHA 均保存。
這支持本固定實物的 `PROPOSED_NOT_AFFECTED`，**尚未套用排除或 VEX**。
同套件其他 Perl 告警不繼承這項判定。[Debian 公告](https://security-tracker.debian.org/tracker/CVE-2026-8376)。

### C. 未確定／沒有完整修補材料

1. **27 項 Go 告警**：7 個 node Go ELF 的 build-info、module/version、平台與 vcs 已保存，
   但既有 govulncheck extract 對這些 binary 回傳零 symbols，沒有完整 compiled import/call closure。
   module 出現不能證明可利用，零 symbols 也不能證明不存在；全部保留 INDETERMINATE。
2. **zlib CVE-2026-85091**：tracker 對 Debian 1.3.1 標示 vulnerable，
   說明卻从 upstream 1.3.1.2 起列範圍；尚未完成 source patch 比對，無 bound fixed package，
   不自行判為誤報。[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091)。
3. **12 個額外映像的來源判定**：339 個映像告警帳列的 raw rule/instance 已保留；
   官方函式／build closure、修補 binary 與相依尚未逐一完成。
4. **官方 binary／重編方案**：Go module 無法像 shared library 一樣直接換檔。
   每個 advisory 的 upstream fixed branch 已記錄，但不以其中一個最低修正版宣稱整個 binary 已安全。
   優先找相容、固定且有校驗資訊的官方節點／元件更新；不在此輪 fork Kubernetes 或重編。

gRPC 兩個 Go DB alias 缺項已補看官方公告：缺少 authority/Host 的 xDS server panic，
以及極小 HTTP/2 DATA frame 造成記憶體耗盡；實際啟用與可達性尚未確定。
官方修正版分支見
[gRPC GHSA-2v4p-qf9q-27wj](https://github.com/grpc/grpc-go/security/advisories/GHSA-2v4p-qf9q-27wj)、
[gRPC GHSA-vp52-pcj8-j9qc](https://github.com/grpc/grpc-go/security/advisories/GHSA-vp52-pcj8-j9qc)。

## 4. containerd 特別核對

主 daemon 是 containerd 2.3.4；fuse-overlayfs snapshotter 的 binary 另帶 containerd/v2 2.2.0。
兩者不能合併判讀。主 daemon 的版本不會自動消除 snapshotter 內嵌 module 的告警。

另列補充 `GHSA-p7v4-vr35-mj6f`，不灌入原59／151的scanner計數。
官方說明2.3.4預設停用 experimental restore，但重新啟用會恢復風險。
實物 base config 使用 overlayfs、未出現 restore opt-in；entrypoint 可因環境／檔案系統切換
並啟用 fuse service，故 **不能由 base config 推定未來有效 runtime 設定**。
後續需驗證最終有效設定與服務，這次沒有執行。
[containerd 官方公告](https://github.com/containerd/containerd/security/advisories/GHSA-p7v4-vr35-mj6f)。

## 5. 真實證據與保護界線

- 私有目錄：`/private/tmp/chg301-r2-node-qual-_py7trju`，0700；產生檔案0600。
- Run manifest SHA：`c866f4693484dd03a13a133788ae87f85bc85f944707d2827b5822b8c871dd0c`。
- Node ledger 59項 SHA：`30a374b013ad973dc213e546f15d7a7da0fb7ab8297322f80b519e64cb1d296b`。
- 額外339帳列 SHA：`9cd2b2f86a6023e7d4670a293f3f7974d70577d37fb1d30276f62d76855ad4f4`。
- 原始輸出：`analysis/*.sarif.json`、`*.spdx.json`、`node-binaries.json`、
  `node-assessment-final.json`、`additional-image-findings.json`、簽章成功／失敗 stdout/stderr。
- Scout 1.24.0；scanner不提供獨立DB revision，保留查詢時間而不宣稱DB固定。
  Scout binary hash在結案補記，不能倒推為所有掃描的起始attestation。
- 本輪保留 2,369,090,201 bytes（約 2.21 GiB）公開artifact及證據。
  依 exact path/inode/owner/hash dry-run 僅刪除一個0-byte失敗下載暫存；不刪原始有效證據、旧run或共享快取。
- 資源監測非OS硬quota；host memory估值不代表Docker VM可用記憶體。
  本輪原始硬期限 `2026-09-15T20:17:52.088462Z` 未重設；工作在期限前完成本報告階段。
- 改動僅限新分析runner、其tests及治理／報告；產品、SQL、依賴、正式chart與既有Traefik接受未更動。

歷史安全停點都保留：已核對的 Docker 官方 CDN redirect、關閉分支的 chart lookup、
超出64MiB下載上限的全量Debian tracker（改為32個有界CVE頁面），以及兩次缺少公開簽署金鑰。
沒有因錯誤關閉TLS／簽章檢查或放大限制。[Docker 官方 allow-list](https://docs.docker.com/desktop/setup/allow-list/)。

## 6. 測試與未通過項

| 檢查 | 本輪結果 | 意義 |
| --- | --- | --- |
| 新靜態guard／真實artifact suite | 77 PASS、0FAIL、0ERROR、0SKIP；1.95秒 | 含OCI/SBOM綁定、ELF、簽章、拒絕案例、exact-owned cleanup |
| 舊134項suite（檔案未改） | 133 PASS、1 FAIL；11.14秒 | 舊positive測試仍以當前activeplan期待舊執行核准 |
| 新的歷史／當前核准分離測試 | PASS（含在77項） | 真實歷史核准仍保持原scope；當前靜態scope必須拒絕執行 |
| Bandit --ignore-nosec | exit1；4 Low，0 Medium/High；未skip/suppress | B404/B603 subprocess提示＋B105把公開token endpoint誤認為password；沒有抹除raw結果 |
| Frontend/Backend完整suite／兩端80% | NOT RUN | 本輪不能替代產品覆蓋率門檻 |
| Kubernetes／Ingress runtime／Provider | NOT RUN/BLOCKED | 無本輪runtime核准，映像安全仍有未結項 |

舊失敗名稱：`test_cmppatch_real_human_acceptance_preserves_raw_findings`。
`applicability_active_plan` 正確拒絕舊核准當作目前核准；不能把這個舊測試改成「重新准許執行」。
本輪保持舊檔SHA，明列測試契約尚未調整；**不宣稱134全PASS**。

新suite首輪有5個guard dispatch錯誤（GPG分支提早存取未初始化work），已修正先判命令種類；
保留首輪JUnit，最終77PASS。不是產品功能錯誤，也沒有執行被拒絕的命令。

驗證命令（均隔離、未import應用）：

```text
CHG301_R2_NODE_QUAL_EVIDENCE=<exact run root> PYTHONDONTWRITEBYTECODE=1
  <existing isolated python> -m pytest --noconftest -p no:cacheprovider
  -c /dev/null backend/tests/test_chg301_r2_node_qualification.py -q
  --junitxml=<private analysis>/guards-final.xml

<same python> -m pytest --noconftest -p no:cacheprovider -c /dev/null
  backend/tests/test_chg301_r2_ingress.py -q
  --junitxml=<private analysis>/prior-134-guards.xml
# five existing CHG301_R2_*_EVIDENCE variables point only to original fixed public artifacts.

<existing bandit> --ignore-nosec -f json
  -o <private analysis>/bandit-final.json backend/scripts/chg301_r2_node_qualification.py
```

Focused harness結果在本報告結尾記錄；無一般live測試或Helm server呼叫。

Focused harness本輪結果：`spec:doctor`、`spec:trace`（26 active mappings）、
`plan:doctor`、`plan:approved`、`test:plan`、`git diff --check` 全部 exit0。
這些只證明治理／文件門檻，不消除上列1個舊suite失敗、映像告警或未執行項。

## 7. 建議下一步（尚未核准）

**不要直接建立測試叢集，也不要先把所有未知告警排除。**

1. 先決定以「更新官方整包節點／元件」為優先；無相容官方材料時才討論最小自建修補，
   並先完成來源／相依閉包。新的image或CNI版本需重新固定digest與核准，不默默換版。
2. Debian八類可列入最小修補候選，但要另行核准payload／solver／建置／重掃範圍。
   Go27項、額外映像及zlib未確定項應一併完成處置，避免只修外殼。
3. Perl單項若要排除，需獨立精確接受；也可隨已需更新的perl-base一起修補，避免新增豁免。
4. 調整舊positive測試為歷史核准語境＋當前scope拒絕的契約，不放寬安全guard。
5. 只有上述項目與原完整R2安全／資源門檻滿足後，才另行核准實際叢集驗證；PR尚未更新。

Owner：Peter決定後續修補／可接受風險與新核准範圍；Codex依新範圍完成材料和測試。
本批次期限不續期；任何後續跨原期限工作都需明確新執行窗口。

## 附錄：原59項完整帳列

以下保留原始ID與severity，不因不適用提案而刪除。
PURL、binary/path/hash、official advisory與候選材料見機器證據相同ID。

| # | ID | 原severity | Component | 本輪判定 |
| ---: | --- | --- | --- | --- |
| 1 | CVE-2026-41991 | UNSPECIFIED | gzip | 套件版本需修補 |
| 2 | CVE-2026-56852 | UNSPECIFIED | golang.org/x/text | 適用性未確定 |
| 3 | CVE-2026-57433 | UNSPECIFIED | perl | 套件版本需修補 |
| 4 | CVE-2026-58050 | UNSPECIFIED | libssh2 | 套件版本需修補 |
| 5 | CVE-2026-58051 | UNSPECIFIED | libssh2 | 套件版本需修補 |
| 6 | CVE-2026-66034 | UNSPECIFIED | libssh2 | 套件版本需修補 |
| 7 | CVE-2026-7017 | UNSPECIFIED | perl | 套件版本需修補 |
| 8 | GHSA-259r-337f-4rfw | UNSPECIFIED | github.com/klauspost/compress | 適用性未確定 |
| 9 | GO-2026-5932 | UNSPECIFIED | golang.org/x/crypto | 適用性未確定 |
| 10 | CVE-2026-84445 | HIGH | google.golang.org/grpc | 適用性未確定 |
| 11 | CVE-2026-63387 | HIGH | libevent | 套件版本需修補 |
| 12 | CVE-2026-53489 | HIGH | github.com/containerd/containerd/v2 | 適用性未確定 |
| 13 | CVE-2026-41567 | HIGH | github.com/docker/docker | 適用性未確定 |
| 14 | CVE-2026-42306 | HIGH | github.com/docker/docker | 適用性未確定 |
| 15 | CVE-2026-39883 | HIGH | go.opentelemetry.io/otel/sdk | 適用性未確定 |
| 16 | CVE-2026-46680 | HIGH | github.com/containerd/containerd/v2 | 適用性未確定 |
| 17 | CVE-2026-48962 | HIGH | perl | 套件版本需修補 |
| 18 | CVE-2026-89161 | HIGH | pcre2 | 套件版本需修補 |
| 19 | CVE-2026-33814 | HIGH | golang.org/x/net | 適用性未確定 |
| 20 | CVE-2026-33818 | HIGH | stdlib | 適用性未確定 |
| 21 | CVE-2026-42497 | HIGH | perl | 套件版本需修補 |
| 22 | CVE-2026-46600 | HIGH | golang.org/x/net, stdlib | 適用性未確定 |
| 23 | CVE-2026-48959 | HIGH | perl | 套件版本需修補 |
| 24 | CVE-2026-54874 | HIGH | openssl | 套件版本需修補 |
| 25 | CVE-2026-56853 | HIGH | stdlib | 適用性未確定 |
| 26 | CVE-2026-56854 | HIGH | golang.org/x/crypto | 適用性未確定 |
| 27 | CVE-2026-56855 | HIGH | golang.org/x/crypto | 適用性未確定 |
| 28 | CVE-2026-56859 | HIGH | stdlib | 適用性未確定 |
| 29 | CVE-2026-56862 | HIGH | stdlib | 適用性未確定 |
| 30 | CVE-2026-56864 | HIGH | golang.org/x/mod | 適用性未確定 |
| 31 | CVE-2026-5928 | HIGH | glibc | 套件版本需修補 |
| 32 | CVE-2026-63072 | HIGH | openssl | 套件版本需修補 |
| 33 | CVE-2026-63076 | HIGH | openssl | 套件版本需修補 |
| 34 | CVE-2026-78662 | HIGH | golang.org/x/crypto | 適用性未確定 |
| 35 | CVE-2026-86145 | HIGH | pcre2 | 套件版本需修補 |
| 36 | CVE-2026-85091 | HIGH | zlib | 適用性未確定 |
| 37 | CVE-2026-53492 | HIGH | github.com/containerd/containerd/v2 | 適用性未確定 |
| 38 | CVE-2026-56865 | HIGH | golang.org/x/mod | 適用性未確定 |
| 39 | CVE-2026-57432 | HIGH | perl | 套件版本需修補 |
| 40 | CVE-2026-63388 | HIGH | libevent | 套件版本需修補 |
| 41 | CVE-2026-11822 | HIGH | sqlite3 | 套件版本需修補 |
| 42 | CVE-2026-11824 | HIGH | sqlite3 | 套件版本需修補 |
| 43 | CVE-2026-53488 | HIGH | github.com/containerd/containerd/v2 | 適用性未確定 |
| 44 | CVE-2026-63383 | HIGH | libevent | 套件版本需修補 |
| 45 | CVE-2026-63384 | HIGH | libevent | 套件版本需修補 |
| 46 | CVE-2026-66032 | HIGH | libssh2 | 套件版本需修補 |
| 47 | CVE-2026-73500 | HIGH | go.etcd.io/etcd/client/pkg/v3 | 適用性未確定 |
| 48 | CVE-2026-84304 | HIGH | google.golang.org/grpc | 適用性未確定 |
| 49 | GHSA-hrxh-6v49-42gf | HIGH | google.golang.org/grpc | 適用性未確定 |
| 50 | CVE-2026-12087 | CRITICAL | perl | 套件版本需修補 |
| 51 | CVE-2026-13221 | CRITICAL | perl | 套件版本需修補 |
| 52 | CVE-2026-33186 | CRITICAL | google.golang.org/grpc | 適用性未確定 |
| 53 | CVE-2026-42496 | CRITICAL | perl | 套件版本需修補 |
| 54 | CVE-2026-75803 | CRITICAL | openssl | 套件版本需修補 |
| 55 | CVE-2026-63382 | CRITICAL | libevent | 套件版本需修補 |
| 56 | CVE-2026-63385 | CRITICAL | libevent | 套件版本需修補 |
| 57 | CVE-2026-39821 | CRITICAL | golang.org/x/net, stdlib | 適用性未確定 |
| 58 | CVE-2026-5450 | CRITICAL | glibc | 套件版本需修補 |
| 59 | CVE-2026-8376 | CRITICAL | perl | 不適用提案；未核准 |

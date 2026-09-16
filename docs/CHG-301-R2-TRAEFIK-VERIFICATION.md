# CHG-301 R2 Traefik 候選檢查結果

2026-09-15。**已完成來源確認、registry-only 掃描與局部保護測試；安全門檻未通過，未建立叢集。**
本次不是 NomoSmart 功能測試失敗，也不是已證實入口可被攻擊。

## 已完成

| 工作 | 結果 |
| --- | --- |
| Gate 4 | Peter「OK」核准既有隔離計畫；不含新漏洞豁免或現行環境變更。 |
| 官方候選 | Traefik v3.7.13 / Helm chart41.5.0；archive SHA及image index/ARM64 digest綁定成功，前後tag一致。 |
| 容量預檢 | 扣除保留量後約3.55 CPU、14.97GiB RAM；磁碟約255GiB可用。只是取樣，尚未證明完整三節點服務能放入。 |
| 完整severity掃描 | Docker Scout1.24.0：2 Critical、8 High、1 Medium、1 Unspecified。11 CVE及1 GO advisory，12個結果。 |
| SBOM | SPDX381筆含映像本身，ARM64 image PURL與候選digest一致。 |
| 保護工具測試 | **28 PASS / 0 FAIL / 0 SKIP**，真實官方artifact、檔案與CLI；不使用假外部服務／假掃描通過結果。 |
| 現有環境 | 預檢探測容器已精確清除；收尾14個原有Docker容器ID、狀態、啟動時間、restart count相同。未操作Kubernetes。 |

`scout cves` exit0只代表掃描完成；runner按內容回exit1 / `BLOCKED_FINDINGS`。
未排除base image、未套FTP例外、未套VEX或隱藏未知severity。
原始SARIF及SPDX、SHA、工具／時間／來源記於
[machine evidence](CHG-301-R2-TRAEFIK-EVIDENCE.json)。Scanner不提供獨立DB版本，
不聲稱已驗證資料庫版本新鮮度。查詢時間2026-09-15T13:07:57–13:08:23Z。

## 告警是什麼：保留原始評級，不誇大適用性

### 1. OpenSSL：10項命中

映像套件為`openssl3.5.7-r0`；Scanner指出Alpine修正版`3.5.8-r0`。
OpenSSL官方確認3.5.8修補相關問題，但**套件有問題不等於Traefik必然走到該功能**。
本輪未分析候選ELF的實際link/call path，也未啟動候選，不能判定不可達。

| CVE | Scanner | OpenSSL原廠 | 必須核對的功能條件 |
| --- | --- | --- | --- |
| 2026-14456 | High | Low | OpenSSL QUIC server queue |
| 2026-18798 | High | Moderate | QUIC initial packet錯誤處理 |
| 2026-63072 | High | Moderate | CMS key unwrap |
| 2026-63076 | High | Moderate | CMP PBM驗證 |
| 2026-14457 | High | Low | RPK只有private key、無certificate |
| 2026-54874 | High | Low | DTLS buffering |
| 2026-63073 | Critical | Low | CMP sender驗證 |
| 2026-63074 | Medium | Low | CMP certificate cache |
| 2026-63075 | High | Low | QUIC ACK retention |
| 2026-75803 | Critical | Low | EVP_Cipher空ciphertext的AEAD驗證 |

原廠來源：[8月25日公告](https://openssl-library.org/news/secadv/20260825.txt)、
[8月13日公告](https://openssl-library.org/news/secadv/20260813.txt)。
不把原廠Low默默覆蓋Scanner Critical，也不把OpenSSL QUIC直接等同Traefik HTTP/3。
版本／功能適用性與風險接受是兩件事，後者本次未獲授權。

### 2. Docker CLI：1項High，存在明確適用性差異

`CVE-2025-15558`上游限定Windows CLI plugin manager，且修正於29.2.0。
本候選是Linux/ARM64，SBOM的docker/cli為29.7.2，因此與平台及版本條件均不符。
這是有依據的誤配判讀，不是已接受風險；raw結果仍保留，未套自動放行。
[Docker官方公告](https://github.com/docker/cli/security/advisories/GHSA-p436-gjf2-799p)。

### 3. Go crypto：1項未分類，不能只靠模組名稱判定

`GO-2026-5932`針對已停止維護的`golang.org/x/crypto/openpgp`系列子套件。
SBOM只顯示整個`x/crypto0.56.0`模組，尚不能證明openpgp被連入或執行。
需候選二進位／package-level證據；不能把所有x/crypto使用都當作此漏洞。
[Go官方資料](https://pkg.go.dev/vuln/GO-2026-5932)。

## 範圍、測試與原始失敗

新增`backend/scripts/chg301_r2_ingress.py`，目前只提供`candidate` phase；
未實作的install等phase直接拒絕，尚無可執行cluster安裝或Browser runner。
新增`backend/tests/test_chg301_r2_ingress.py`，對應CMPING-T02局部，涵蓋：
真實chart/hash/provider、固定ARM64/image/SBOM、錯誤版本／重複／缺失、
Scanner身分／錯誤／抑制／缺漏拒絕、未知severity、私有證據不可覆寫、
實際CLI未opt-in或未實作phase拒絕。

重現本次局部測試（private路徑是本次證據；未來執行另建目錄）：

```bash
env -i PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPYCACHEPREFIX=/private/tmp/chg301-r2-ingress-tests-dYzi1v/pycache \
  CHG301_R2_CANDIDATE_EVIDENCE=/private/tmp/chg301-r2-traefik-vtkgc8jt \
  /private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python -m pytest \
  -c /dev/null --rootdir=. --noconftest -p no:cacheprovider \
  --basetemp=/private/tmp/chg301-r2-ingress-tests-dYzi1v/cases \
  --junitxml=/private/tmp/chg301-r2-ingress-tests-dYzi1v/junit.xml \
  -q backend/tests/test_chg301_r2_ingress.py
```

首次下載因Python未設預設CA檔失敗；改用已安裝certifi，TLS/hostname驗證未關閉，
沒有修改OS信任庫。第二次下載成功，但runner把provider鍵寫成Nginx，實際官方鍵
為`kubernetesIngressNGINX`；修正後第三次完整掃描成功並被安全門檻擋下。
所有attempt都保留，沒有把錯誤結果覆寫成PASS。

原result把12個advisory稱為unique_cves，已在後續runner區分11 CVE與12 advisory；
原raw結果未改、嚴重度與BLOCKED結論未改。後續加入scanner身分檢查及test-source
綁定，28項測試驗證更新後工具；不宣稱更新後工具又執行了新掃描。
除上述runner外，原scan綁定的其他283個既有來源檔未變。

收尾`./HARNESS/harness.sh spec:doctor`、`spec:trace`（17條active mappings）、
`plan:doctor`、`plan:approved`、`test:plan`及`git diff --check`皆PASS。
規格§10.58 CMPING-T02局部證據已回寫計畫／追蹤；產品規格、API、權限、SQL、
正式chart及runtime依賴無新增行為變更。其餘CMPING驗收仍待安全門檻。

## 前輪建議與後續修補前檢查

後續書面計畫已核准且完成真實artifact分析／58個guard。
[最新修補檢查結果](CHG-301-R2-TRAEFIK-REPAIR-VERIFICATION.md)：原image實際只有
兩個OpenSSL函式庫、沒有openssl套件，三套件recipe須先修正範圍；OpenPGP因
零symbols仍不能判定安全。未建置／執行controller，所有原始告警保留。

後續Peter於2026-09-15回覆「Ok」，確認以下修補方向（新Gate2）；已另寫
[測試映像修補計畫](CHG-301-R2-TRAEFIK-REMEDIATION-PLAN.md)。Peter隨後明確
核准此書面計畫，Gate4 APPROVED；原image/raw掃描結果不變，不自動豁免。

建議維持Traefik相容方向，先確認候選內實際用到的漏洞套件／程式路徑，再決定
固定版本的測試專用底層映像修補或等待官方修補映像；OpenSSL3.5.8是已知修補方向，
不保證只改這個套件便能全數通過。任何新image/build、版本選擇或精確VEX例外均須
另確認範圍；不建議接受整包High/Critical，也不自動輪換controller。

完整Frontend/Backend suites、各>=80%全來源coverage、三節點Kubernetes、
TLS/IP/OIDC/BFF/NetworkPolicy與Browser驗收仍未完成。Provider呼叫、PR更新、
現行部署變更均為0。不能把本次28個保護測試當成上述驗收。

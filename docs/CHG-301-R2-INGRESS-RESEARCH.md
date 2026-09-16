# CHG-301 R2 Ingress 漏洞適用性與受維護替代方案研究

日期：2026-09-15。狀態：**研究完成；安全放行與替代方案實測尚未完成**。

Peter 的「Ok」同意先研究漏洞適用性及入口替代方案，不動目前部署。
本文件是規格理解／方向討論材料，**不是新開發計畫、風險接受或部署授權**。
未修改產品、Helm、Installer、規格、鎖檔、資料、PR 或現行環境。
未建立叢集、執行候選映像、發出 Provider 呼叫或進行漏洞攻擊測試。

## 結論先說

1. 74 個 High/Critical 是掃描器的套件告警，不能解讀為 74 個已證實可攻擊的入口漏洞。
2. 本輪詳細記錄 9 個代表性 CVE：3 個有版本／架構不適用證據、2 個疑似套件生態誤配、4 個仍需確認呼叫條件。其餘 65 個沒有逐項完成適用性判定。
3. 即使校正誤報，也不建議將已退休的 community Ingress NGINX 作為新驗證環境的長期入口。官方公告其於 2026 年 3 月停止維護及安全更新。[退休公告](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)
4. 建議優先討論 **Traefik 的 Kubernetes Ingress NGINX 相容模式**：保留目前 Ingress 契約，先在獨立環境證明相容。不是直接替換現行入口，也不是聲稱候選映像已無漏洞。
5. R2 的安全 gate 仍未放行。原計畫要求相容 controller；更換技術前須補充規格／計畫並取得核准，不能用「測試環境」名義省略。

## 一、依據與範圍

- 規格基線：`SPECIFICATION.md` §10.58 的 CMPSTART／CMPVERIFY 與 TEST-002 live-only 原則。
- 已核准驗證界線：[完整驗證計畫](CHG-301-R2-FULL-VERIFICATION-PLAN.md)，特別是 §C.6／§D。
- 原始證據：[Ingress security evidence](CHG-301-R2-INGRESS-SECURITY-EVIDENCE.json)。
- 該 JSON SHA-256：`11220b08475e24df8dc1b4698652fe314519b72f38db70674853c76fe81f3431`。
- 候選：community controller `v1.15.1`；multiarch digest `sha256:594ceea76b01c592858f803f9ff4d2cb40542cae2060410b2c95f75907d659e1`。
- 本次 ARM64 digest：`sha256:fa34e053d6ac30a9df379caa4180154c3a6ff17b5f78ac377117da440b09ba20`。
- Scout 1.24.0：125 個唯一 CVE、128 個結果；16 Critical、58 High、37 Medium、7 Low、7 未指定。227 個 components。

這是前一輪 registry-only 掃描，不是目前運行 controller 的重新盤點。
本輪唯讀重新核對 JSON／SPDX、程式碼及官方公開公告；不把這份候選報告套用到其他 tag、digest 或架構。

High/Critical 的套件分布如下；Go stdlib 與 x/net 共享 3 個 CVE，不能重複計數：

| 套件 | 候選版本 | High/Critical 唯一 CVE 數（套件內） |
| --- | --- | ---: |
| curl | 8.17.0-r1 | 29 |
| OpenSSL | 3.5.5-r0 | 24 |
| Go stdlib | 1.26.1 | 16 |
| golang.org/x/net | 0.52.0 | 3，均與 stdlib 重複 |
| nghttp2／c-ares／musl／protobuf／grpc | 見原始證據 | 各 1 |

## 二、漏洞適用性：目前能確定什麼

### 有不適用證據的 3 項

| CVE | 原始嚴重度 | 官方條件與本候選對照 | 判讀 |
| --- | --- | --- | --- |
| CVE-2026-11352 | High | curl 上游受影響範圍為 8.18.0–8.20.0；本候選 8.17.0-r1。Scanner 的 Alpine 範圍只有 `<8.22.0-r0`，未表達引入下限。[公告](https://curl.se/docs/CVE-2026-11352.html) | 依上游版本範圍不適用；若要形成正式 VEX，仍須核對該 Alpine revision 是否另行 backport 引入。 |
| CVE-2026-9546 | High | 同樣從 curl 8.18.0 才引入；本候選 8.17.0-r1。另上游說明 curl CLI 不受影響。[公告](https://curl.se/docs/CVE-2026-9546.html) | 同上，不把過寬的 distro 範圍當作已證實漏洞。 |
| CVE-2026-31789 | Critical | OpenSSL 上游評 Low，條件為 32 位元程式印出／記錄超過 1 GiB 的不可信憑證；本候選為 ARM64。[公告](https://openssl-library.org/news/vulnerabilities/index.html#CVE-2026-31789) | 本次原生 64 位元構件不符合架構條件；不可外推到 32 位元映像。 |

以上是研究判讀，**沒有更改 scanner 原始結果、建立 VEX、移除告警或接受風險**。

### 疑似生態誤配的 2 項

| CVE | 原始嚴重度 | 不一致之處 | 尚缺證據 |
| --- | --- | --- | --- |
| CVE-2026-33186 | Critical | 上游是 `grpc-go` 的路徑授權問題，修正於 Go 套件 1.79.3；掃描卻命中 Alpine `grpc@1.76.0-r2`。SPDX 列出 grpc-cpp／libgrpc／libgrpc_unsecure，沒有列出 Go grpc。[維護者公告](https://github.com/grpc/grpc-go/security/advisories/GHSA-p77j-4mvh-x3m3) | 核對映像檔案與 Go build metadata、發行版 advisory；SBOM 未列出不等於證明完全不存在。不能拿 Go 版本號直接更新 C++ 套件。 |
| CVE-2026-0994 | High | 上游修正 Python `json_format.ParseDict` 的 Any 遞迴深度限制；scanner 指向 Alpine protobuf 31.1-r1。SPDX 可見 libprotobuf／libprotobuf-lite 及 Go protobuf，未列 Python protobuf。[原始修正](https://github.com/protocolbuffers/protobuf/pull/25239) | 需確認該 APK 的實際檔案／subpackages 與是否存在 Python 呼叫路徑，不能僅憑名稱直接正式排除。 |

### 不能排除、但尚未證實入口可利用的 4 項

| CVE | 原始嚴重度 | 已確認條件 | 研究結論 |
| --- | --- | --- | --- |
| CVE-2026-39821 | Critical | Go 1.26.1／x/net 0.52.0 在受影響範圍。若先對 ASCII hostname 授權、再做 IDNA 轉換，可能出現不同名稱判斷；修正 Go 1.26.6／x/net 0.55.0。[Go 公告](https://pkg.go.dev/vuln/GO-2026-5026) | controller 二進位含版本命中構件，但實際可達呼叫鏈尚未證明；不能因 ARM64 就排除。 |
| CVE-2026-27135 | High | nghttp2 1.68.0 命中，1.68.1 修正。涉及 session 終止後處理異常 frame 的 assert；部分路徑須開啟 extension。[公告](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-6933-cjhr-5qg6) | 需證明誰連結並使用 libnghttp2、編譯旗標及協定路徑；NGINX 接受 HTTP/2 不等於一定走此函式庫。 |
| CVE-2026-40200 | High | musl qsort 超大輸入。維護者指出 64 位元需要超過約 34 兆 elements 與極大量位址空間。[維護者公告](https://www.openwall.com/lists/oss-security/2026/04/10/13) | 實際可觸發性遠低於一般輸入，但 ARM64 不是形式上的不受影響；尚未驗證映像呼叫點與運行限制。 |
| CVE-2026-10536 | Critical | libcurl HTTP/2 dependency API、reset／cleanup 交互造成 UAF；上游評 Low，CLI 不受影響。[公告](https://curl.se/docs/CVE-2026-10536.html) | CLI 不受影響不能延伸為整個 libcurl 不受影響；需查呼叫 API。 |

其餘 **65 個唯一 High/Critical 保持未完成逐項判定**，包括其他 curl、OpenSSL、Go 以及 c-ares。
上游與 scanner 嚴重度不同不構成自動降級依據；套件版本符合也不等於遠端一定可利用。
本次沒有足夠證據宣稱整個候選安全，也沒有必要為長期使用而自行接手退休 controller 的維護。

## 三、現有 NomoSmart 契約與相依程式

以下來自 repository，不是推測部署的即時狀態：

| 功能 | 實作來源 | 更換入口不能破壞的條件 |
| --- | --- | --- |
| 主入口／TLS | `deploy/helm/nomosmart/templates/ingress.yaml`、`values.yaml` | 保留 host、TLS Secret 與 HTTP→HTTPS；`/` 到 Frontend，bundled 模式的 `/identity` 到 Keycloak。 |
| 初始化存取限制 | `ingress.yaml`、`deploy/installer/nomosmart_installer/config.py` | 非 operational 階段由 onboardingAdminAllowCidr 限制來源；不可只改正式入口而漏掉 bootstrap。 |
| Keycloak 管理區 | `ingress.yaml` 的獨立 `-keycloak-admin` Ingress | 同 host 的 `/identity/admin`、`/identity/realms/master` 必須保留較嚴格 allowlist，不能落回一般 `/identity`。 |
| client IP | `values-docker-desktop.yaml` 的 allowlist | 現有含 loopback 與 Pod CIDR；更換代理後須重新驗證 SNAT／真實來源，不能把所有 Pod 自動當成可信管理者。 |
| 網路隔離 | `templates/networkpolicy.yaml`、`values.yaml` | controller namespace 與 pod selectors 共同限制 Frontend 3000／Keycloak 8080；Backend 8000 仍只允許同 release Frontend。 |
| API／登入 | `frontend/src/app/api/backend/[...path]/route.ts`、`templates/keycloak.yaml` | 保留 Frontend BFF、Keycloak xforwarded 行為、OIDC issuer／callback／cookies；不為了換入口直接公開 Backend 或搬動認證邏輯。 |

這些多數已可透過 values 配置，但 NGINX annotation 與 bootstrap 產生邏輯仍有耦合。
所以「只換 image」與「刪掉 annotation 讓網站開得起來」都不是等價驗證。

## 四、替代方案比較

以下版本是研究日觀察的候選，**尚未固定 image digest、掃描或通過 NomoSmart 實測**。

| 方案 | 維護依據 | 對現有契約的影響 | 建議定位 |
| --- | --- | --- | --- |
| Traefik 3.7.13，NGINX 相容 provider | [2026-09-04 release](https://github.com/traefik/traefik/releases/tag/v3.7.13)，含安全修補 | 3.7 文件列出支援目前用到的 whitelist-source-range、ssl-redirect；仍須驗證差異，不保證所有 NGINX 功能相容。[相容文件](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/ingress-nginx/) | **優先評估**：較少路由規格改寫，先解開 R2 入口前置阻礙。 |
| F5 NGINX Ingress Controller OSS 5.6.1 | [2026-09-04 changelog](https://docs.nginx.com/nginx-ingress-controller/changelog/) | 與退休的 community ingress-nginx 不同專案；annotation／Policy／同 host 路徑整合需要轉換及驗證。[遷移文件](https://docs.nginx.com/nginx-ingress-controller/install/migrate-ingress-nginx/) | 備選：希望維持 NGINX 技術棧時適合；不能視為直接升版，OSS 與付費 Plus／LTS 支援不可混用。 |
| Envoy Gateway 1.9 系列＋Gateway API | [1.9 release](https://gateway.envoyproxy.io/news/releases/v1.9/) | 要把 Ingress 改成 Gateway／HTTPRoute；來源 IP 透過 SecurityPolicy 與 client-IP 設定。[IP policy 文件](https://gateway.envoyproxy.io/docs/tasks/security/restrict-ip-access/) | 長期架構選項；這次為修復驗證前置條件而全面改 API，範圍較大。 |

Traefik 的建議是基於現有契約相容度，不是已證明它最安全或沒有漏洞。
相容模式仍帶有 NGINX annotation 技術債；未來若轉原生設定／Gateway API，應另立需求，不在這次順便重寫。

### Traefik 尤其要釐清的地方

- 必須用 `kubernetesIngressNGINX` provider；不要把一般 Kubernetes Ingress provider 當成相容模式，或讓兩者同時處理同一組路由。
- discovery 必須限制在專用 namespace／IngressClass／controllerClass。`ingressClassByName=true` 是增加匹配來源，不是縮小監聽範圍，不能用它單獨隔離。
- 不需要開放跨 namespace 資源、不可信 snippets 或全域外部 auth；最小權限與既有 app OIDC 分工應保留。[Provider 官方設定](https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress-nginx/)
- allowlist 預設使用 remote address；代理後的 X-Forwarded-For 策略必須對照實際拓樸與可信 hop，不能直接信任用戶送來的 IP。
- 全域 TLS redirect 與個別路由 opt-out 有相容差異；body size／buffering／timeout 也不能僅靠 annotation 名稱判定一致。[3.7 限制](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/ingress-nginx/)

## 五、方向核准前應同意的驗證標準（尚未執行）

這是方案評估的必要條件，不是已核准的執行步驟：

1. **映像本身安全**：精確版本／ARM64 digest／SBOM／原始漏洞結果；不能用 release note 代替掃描。新增 High/Critical 不自動繼承 FTP 接受。
2. **路由正確**：Frontend、BFF、Keycloak 都走原路徑；管理路徑不能繞過獨立限制，未知 host／路徑不意外暴露管理服務。
3. **TLS 與登入正確**：CA 驗證、redirect 狀態與位置、OIDC callback／issuer／cookies；不能以 `-k` 或關掉 TLS 作通過證據。
4. **允許與拒絕都實測**：核准來源可進、其他來源被拒絕；偽造 X-Forwarded-For 不得繞過。涵蓋 onboarding 與 operational 兩種狀態。
5. **網路隔離仍有效**：用真正支援 NetworkPolicy 的 CNI，證明 controller 可達指定服務、不相關 Pod 不可達，不能將 selectors 清空來修連線。
6. **一般功能不退步**：登入後頁面、無 Provider 的 API、合成檔上傳／下載與合理 timeout；真正模型回答的付費案例仍需另外核准。
7. **維持獨立測試邊界**：不用現行 kubeconfig／Secret／PVC／正式網域流量；專用端口、run-owned 資源、容量及 cleanup 證據。不能以擴大現有環境 allowlist 解決測試問題。

若同意此方向，才依 AGENTS.md 更新 companion spec／SPEC_CHANGELOG、R2 計畫、
測試與 traceability，列出明確範圍及所需操作授權。當前完整 FE／BE coverage、
Kubernetes、候選應用 image 安全與 PR 更新等未完成事項仍照原報告保留。

## 六、本輪交付與限制

- 只新增本研究報告並在驗證進度連結它；產品、測試行為及部署設定未改。
- 原始掃描證據 SHA 未變；沒有 suppress／waiver、沒有聲稱 PASS。
- 本輪未跑 feature tests 或 Kubernetes acceptance，因此沒有新的測試 PASS 數。
- 本輪未逐項完成 74 個 CVE 的 VEX／呼叫鏈審核；如果決定繼續使用退休候選，仍須補完，不能用本報告放行。
- 一次 Node 公開文件 fetch 因 sandbox DNS `ENOTFOUND` 未成功，後續以可用的 web 閱讀官方文件；沒有放寬環境權限或存取私密 endpoint。
- 收尾僅檢查文件差異格式、來源證據雜湊及計數；不代替 R2 安全／功能驗收。

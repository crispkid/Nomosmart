# CHG-301 R2：測試用 Traefik 映像修補與精確漏洞判定計畫

2026-09-15。Peter對前輪「僅限測試映像修補＋精確漏洞判定」回覆「Ok」，
**Gate2 confirmed；Gate3 written；Gate4 approval: APPROVED**。
Peter隨後明確回覆「核准 CHG-301 R2 測試映像修補與精確漏洞判定計畫」。
核准前文件SHA256：`3ed18f43106e87adce5e4da3bd9c997deff8374ca654cf91b58ad2b30e1aea54`。
核准含明列build-only例外，不含漏洞豁免、controller服務執行或現行部署變更。

最新有限修訂：Peter已確認只修補兩個既有函式庫、不新增openssl，並保留OpenPGP
阻擋。見[兩函式庫修訂計畫](CHG-301-R2-TWO-LIBRARY-PLAN.md)，其Gate4已獲Peter明確核准。
執行前查到離線索引材料限制，見該文件§6；目前停止於範圍確認，不代表未核准原修訂。
本文件原三套件方案及核准作歷史紀錄保留，不能解鎖修訂後執行範圍。

沿用[完整R2計畫](CHG-301-R2-FULL-VERIFICATION-PLAN.md)與
[Traefik隔離計畫](CHG-301-R2-TRAEFIK-PLAN.md)；只補充候選修補，
不重新授權現行部署、風險豁免、Provider或PR更新。需求為§10.58 CMPPATCH-001..004。

## 1. 目標、基線與完成界線

目標是取得可供後續隔離驗收的候選，而不是把掃描報告改成零。
前輪12advisories（11CVE+1GO）、2Critical/8High/1Medium/1Unspecified原樣保留。

- Traefik3.7.13、linux/arm64；不重編controller、不更新Go依賴、不切換controller。
- 原image index：`sha256:f86a2cab1b5c649070c49f883c743dd32d8485a56e3368c5f93b9e91f1e91259`。
- ARM64 manifest：`sha256:444bb54c1f7ebe5fac94d1c40f02b48c08dc005a92fc65ca29c1c75991d16baa`。
- chart41.5.0，archive SHA：`30f8db73182019b2764179d7fc0a7efc9505670204f847ffc3a779bacaae3a1a`。
- 原掃描摘要`CHG-301-R2-TRAEFIK-EVIDENCE.json` SHA：
  `9397f02e78b88a180acd8577b860a0522bdff44ab9815972571762c1b421d7bc`。
- HEAD`c261a494283835af57c0e0678afc7ee7e2c0dcc8`，merge parent
  `5f1a0a2505dee9c85ee621bd2c8680b92d397a45`；執行前重新記錄dirty來源manifest。

完成時交付：固定來源/APK/工具/映像SHA、完整SBOM與raw掃描、逐項判定及限制、
真實測試與cleanup。若仍需VEX/風險接受則只交付待決清單，不自動開始叢集。
本附註不含Kubernetes寫入；後續驗收只可沿原計畫且所有前置條件均符合。

## 2. 核准後的一次性有限範圍

1. 改測試runner、test-only Dockerfile、證據/guard測試；不改應用及部署預設。
2. 下載固定官方原image、Alpine3.24/aarch64三個修補APK、必要公開簽章/索引，
   與固定govulncheck1.8.0工具至run-owned0700目錄。不能使用latest或關驗證。
3. 唯讀拆解候選layers/ELF、公開原碼及建置metadata；不啟動原controller。
4. 只為套用修補，在既有BuildKit的隔離build sandbox執行離線apk及必要腳本。
   **這會短暫執行原本含漏洞的基底工具，屬本計畫已核准的build-only例外。**
   不是原controller可提供服務的風險接受；不得啟動Traefik、連Kubernetes、暴露埠。
5. 建立唯一local-only測試tag，重掃/比較/guard測試；安全gate完全解決後才跑
   nonroot、無網路的version/help smoke。精確清理run-owned暫存資源。

禁止：新Backend/Frontend/Migration修補、production Dockerfile/chart/Installer
變更、DDL/資料/manifest/角色變更、現在的Ingress/CNI/Secret/PVC/kubeconfig操作、
host trust/DNS/防火牆/Docker VM調整、secret mount、SSHagent/socket掛入build、
Registry push、PR寫入、Provider呼叫、自動VEX或整包風險接受。

## 3. A：來源與分析，不執行候選

先重核原始artifact SHA與工具版本，收集既有容器/網路/tag/builder非敏感基線。
固定existing builder identity；不得改default builder或其daemon設定，不增加另一
長駐builder。無法證明sandbox/資源界線則停止，不使用host network或insecure entitlement。
只用allowlist build context；不將repo、.env、generated package、備份、帳密放入。

以官方digest下載/save映像，解析有效rootfs時處理layer順序、whiteout與symlink，
拒絕path traversal、特殊檔、未限量tar展開，不執行抽出的檔案或用ldd載入它們。
只取指定binary、entrypoint、package database/metadata等必要檔，保留檔案SHA。

靜態核對ELF架構、Go build info/版本、dynamic dependencies與符號資料。
可在private工具目錄使用官方govulncheck1.8.0；module/download hash、Go checksum
database及binary SHA需綁定。使用現有Go、GOENV=off/GOTOOLCHAIN=local及私有
cache，不修改host工具鏈，不因版本不支援而自動下載新Go。不可用即回報。
工具只查公開module/advisory metadata，不上傳完整binary/私有來源。

`govulncheck -mode=binary -json`的exit0不是安全結果，需解析finding和掃描能力；
binary模式不提供完整call graph，符號無法抽取時可能退到module層級。只得到
module inventory、strings無命中或無法辨識build config均不足以證明未受影響。
需要補充同SHA公開來源時，只有可追溯到實際build的證據有用，不能拿main代替。

## 4. B：三個套件離線修補

基於原immutable ARM64image，僅針對`openssl`、`libssl3`、`libcrypto3`，
從原`3.5.7-r0`改到官方Alpine3.24/aarch64 **3.5.8-r0**。
三個artifact的URL/SHA/簽章/依賴閉包在執行前記錄至lock；現在尚未下載，
不編造其hash。版本缺失、架構不符、簽章不可驗證或需要第四項套件升級即停止。
不得用apk upgrade全面更新、edge/main混源、allow-untrusted或手改packageDB騙scanner。

先下載，確認官方keys及signed index/package，再使用既有BuildKit、固定FROM、
最小context與`RUN --network=none`離線安裝明列APK。RUN root只作用於build
snapshot；不掛hostroot/socket/現行volume，不讀Secret，不跑controller。
必要package安裝腳本/trigger也屬執行程式，要先檢視並只允許套件本身所需動作；
出現網路、啟動service、額外套件或非預期檔案變更即拒絕，不擴權重跑。
保留原CA信任內容；不能藉由換信任根讓下載或測試過關。

產出唯一`nomosmart-test/traefik:3.7.13-chg301-r2-<run-id>`，禁止覆寫舊tag。
記錄base、recipe、context及APK lock SHA、image ID/manifest、平台與工具。
同recipe的image ID可能因建置metadata而異；只認實際驗證的那份image，不假稱
跨次位元組相同。不能把這份私製test image說成官方發布或production核准。

## 5. C：比較、重掃及判定

先用靜態方式比對最終有效rootfs與原始image：

- Traefik binary和entrypoint SHA完全相同；其他Go模組/OS package版本不變。
- Entrypoint/Cmd/User/Env/Workdir/ports/stop signal/security契約不變，僅明列
  test provenance labels與允許的package安裝metadata變更。對檔案內容/owner/mode
  建allowlist，不只比套件名稱；任何額外刪改阻擋。
- 三個套件及對應library實際一致；不能只換openssl命令而漏libssl/libcrypto。
- 衍生FROM會保留舊lower layers，完整掃描仍保留它們的證據；有效runtime修補
  不等於archive中舊bytes消失。不能加ignore-base消掉報告；若政策仍阻擋則另議。

同image執行完整Scout/SBOM（不啟動controller），分開raw severity與以下分析：

| 類別 | 允許結論／限制 |
| --- | --- |
| OpenSSL十項 | 版本/實際library/完整重掃證明修補才標FIXED；原廠Low不能直接抵銷rawCritical。 |
| CVE-2025-15558 | 核對最終Linux/ARM64、docker/cli模組版本及上游Windows條件；證據完整可提出PROPOSED_NOT_AFFECTED，不能自動忽略。 |
| GO-2026-5932 | 檢查OpenPGP子套件及binary符號/分析能力；模組存在不等於可達，模組未報也不自動表示安全；不確定標INDETERMINATE。 |
| 其他／新告警 | 全部列出；High/Critical/未知或scanner失敗停止，不自動更新更多套件。 |

本計畫**不核准任何具體VEX或漏洞接受**。若最終仍有需適用性排除的告警，提供
image/binary/advisory SHA、條件、證據及期限給Peter確認；不得由「核准修補」推導
「核准例外」。此時先交付結果，不跑controller。無未解決安全項才可依本計畫執行
短時間、networknone、nonroot、cap-dropALL/no-new-privileges、唯讀rootfs的
version/help smoke；不掛憑證、沒有Ingress，不冒充TLS/路由或Kubernetes驗收。

## 6. 測試與改動檔案

| 區域 | 有限用途 |
| --- | --- |
| `backend/scripts/chg301_r2_ingress.py` | 新plan Gate4檢查、固定extract/repair/rescan/cleanup phases及來源/證據guard；原candidate結果保留。 |
| `deploy/test/chg301-r2-traefik/Dockerfile` | 計畫新增test-only離線三套件修補recipe，不接production build。 |
| `backend/tests/test_chg301_r2_ingress.py` | 原28個真實guard保留，新增CMPPATCH-T01..T08正反例。 |
| `docs/CHG-301-R2-*`與治理檔 | 來源/包簽章/binary分析/raw-vs-assessed/diff/測試/清理證據。 |
| private0700root | 固定下載、工具、APKlock、有限rootfs資料/掃描；不提交私有設定。 |

測試用真實official artifacts、檔案與process失敗，不能fake signature/scanner/
Docker回應。新增錯誤digest/版本/架構/簽章/額外依賴/符號缺失/偽造白名單/
未核准phase/源漂移等guard；任何測試程式變動重新綁定SHA。
原28測試可在private pytest9.0.3環境執行，不import app或現行test conftest；
真實smoke只在安全條件符合後執行。未執行如實NOT RUN，未決不是PASS。

Gate4前只可跑：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check`；`plan:approved`應因本PENDING附註回exit1。
Gate4後的planned runner phases：inspect/repair/rescan/smoke/cleanup/evidence；
每一phase要求新核准及exact-owned manifest，尚未實作，不宣稱現有CLI可用。
成功後只接回原R2門檻，不改80%分母、不修改PR或現行環境。

## 7. 風險、資源、清理與停止

離線root build仍有供應鏈/解析器/共用VM核心風險，hash或簽章只證明來源/完整性，
不是安全保證。新Gate4核准只接受明列修補作業風險，不接受候選作為服務運行。
如果既有builder無法提供隔離/資源證據，停止，不默默建立另一套builder或調整VM。
資源門檻沿原R2：保留4CPU及至少8GiB/20%RAM、100GiB可用disk、80GiB增量上限；
build/scan與完整stack不並行。監測不是硬隔離，不保證現行負載零延遲影響。
單build30m、scanner20m、整批6h、同原因最多2次修正重試；不能藉重建runID重置預算。

開始記錄owned IDs/PID/tag及下載路徑；成功或失敗先列exact-ownedcleanup清單，
再移除本run臨時container/process/APK暫存context，保留去敏感證據及明列test image。
不刪既有builder/cache/network或用prune/down-v；不能證明owner就停止清理並回報。
重核原容器/網路/tag基線，外部漂移如實回報，不刪他人資源以製造相同。

簽章/來源/版本/能力不足、新依賴/新漏洞、權限拒絕、非預期diff、工具不支援、
資源/時間不足均停止；不放寬TLS、RBAC、allowlist或新建current-environment例外。

參考：[固定官方Dockerfile](https://raw.githubusercontent.com/traefik/traefik-library-image/06814bb30ce37fe65a09268ea792eec6e037dff5/v3.7/alpine/Dockerfile)、
[OpenSSL修補公告](https://openssl-library.org/news/secadv/20260825.txt)、
[Docker CLI適用性](https://github.com/docker/cli/security/advisories/GHSA-p436-gjf2-799p)、
[OpenPGP公告](https://pkg.go.dev/vuln/GO-2026-5932)、
[govulncheck能力與限制](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)、
[BuildKit離線RUN](https://docs.docker.com/reference/dockerfile/#run---network)。

本輪只檢視檔案/公開文件與工具版本，寫規格/計畫/追蹤；未新增下載artifact、
安裝工具、執行feature測試、build、scanner、controller或Kubernetes操作。
可回覆：`核准 CHG-301 R2 測試映像修補與精確漏洞判定計畫`。

## 8. 本輪規劃檢查

2026-09-15：`spec:doctor`、`spec:trace`（21條active需求映射）、`plan:doctor`、
`test:plan`、`git diff --check`通過。首次trace因「no ... accepted yet」被既有
guard判成PLANNED/accepted矛盾；改為明確「Gate4 PENDING」後通過，未改驗證器。
`plan:approved`仍回exit1，原因為新Gate4待核准，符合停止條件。
原Traefik/NGINX掃描證據及既有runner/tests的SHA與本輪開始完全一致。
本輪未跑feature測試、安裝工具、build、scan或操作任何Docker/Kubernetes資源。

## 9. 核准後執行結果與範圍停點

Peter明確核准後，已收集固定image/APK/索引/工具，驗證簽章、index/datahash及
原image有效rootfs。58個guard測試通過。實際只安裝libssl3/libcrypto3；
沒有openssl套件，直接照三套件recipe會增加套件而非純升級。因此未建立recipe
或建置；本計畫§4仍未變更，兩函式庫修補方向等待確認。
govulncheck1.8.0 extract無symbols，原碼證實module fallback；OpenPGP仍不確定。
Docker CLI僅提出not-affected判定，不套VEX。掃描原始severity不變。
原容器、網路、image inventory已核對不變，精確清理新增image引用與Go編譯cache。
完整證據／未執行case：[修補檢查結果](CHG-301-R2-TRAEFIK-REPAIR-VERIFICATION.md)。
上述是執行結果，不是未經確認的新開發計畫或漏洞接受；fullR2/80%及PR門檻仍在。

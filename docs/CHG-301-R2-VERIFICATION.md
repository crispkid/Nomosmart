# CHG-301 R2 驗證進度與安全停點

最新範圍調整（2026-09-16）：Peter已確認聚焦交付程式與正式安裝依賴，未啟用的
純測試infra延期且保持不啟用。完成[唯讀盤點](CHG-301-R2-DELIVERY-SECURITY-INVENTORY.md)
與[書面修訂計畫](CHG-301-R2-DELIVERY-SECURITY-PLAN.md)，Gate4待核准。
尚無本輪新掃描/修補/featuretests/映像建置/PR寫入；下面247PASS及高風險清單
保留為歷史，不把用途延期改成修復，也不沿用舊run期限/接受範圍。

最新高風險批次（2026-09-16）：**必要回歸247PASS，高風險修補未完成，PR未更新**。
7個測試失敗已修正，原211案例全數保留，新增36項；不是整體產品驗收或漏洞清零。
221筆High/Critical映像×ID仍未解除；270筆非高風險只延期。未建置或重新掃描
映像，未更動目前部署/資料/Provider。完整證據、限制與剩餘範圍決策見
[本輪結果](CHG-301-R2-HIGH-PR-RESULT.md)及[機器證據](CHG-301-R2-HIGH-PR-EVIDENCE.json)。
以下「最新」與Gate4待核准文字是各舊批次的歷史紀錄，不代表目前狀態。

最新已核准靜態盤點（2026-09-16）：**PARTIAL_RUNTIME_BLOCKED**。
固定node的59項已列帳：30套件版本需修補、1不適用提案未核准、28未確定；
另完成12份ARM64映像全severity/SBOM掃描、339個映像×告警帳列及Debian簽章索引核對。
新77guard/artifact tests PASS；舊134suite133PASS/1FAIL（歷史執行核准不是目前靜態核准，
guard正確拒絕；舊檔未改，新測試已分別驗證歷史核准與當前拒絕）。
完整來源／相依閉包仍未完成；未建置、啟動、部署、接受新風險或更新PR。
原14容器／image／network和產品來源不變，保留原完整R2／80%門檻。
詳見[本輪結果與材料提案](CHG-301-R2-NODE-QUALIFICATION-RESULT.md)及
[機器證據](CHG-301-R2-NODE-QUALIFICATION-EVIDENCE.json)。下方新Gate4待核准是歷史規劃。

最新規劃（2026-09-16）：Peter以「Ok」確認固定node1.36.4、剩餘告警與預載／
CNI映像整批靜態判定方向（Gate2）。已新增
[整批靜態判定計畫](CHG-301-R2-NODE-QUALIFICATION-PLAN.md)、CMPNODE-001..005
及T01–T08；**新Gate4待核准**。本輪只有文件變更，沒有新featuretest、下載、
掃描、imagebuild、Docker／Kubernetes／Provider／PR操作。核准後也只先分析，
不直接修補或執行節點；原完整R2與期限不變。以下是前輪證據，未改寫為新結果。
本輪`spec:doctor`、`spec:trace`（26 mappings）、`plan:doctor`、`test:plan`、
`git diff --check` PASS；`plan:approved`因新Gate4 PENDING回exit1，為預期停點。
研究報告／機器證據、兩支既有runner及既有test SHA與規劃前相同。
書面計畫核准前SHA256：
`f1cc8bec449f60aa4e4eae29f3d7eb9c7f4bc67badb1c8b3936650f7c43ac132`。

最新唯讀評估（2026-09-16）：Peter同意研究node更新／修補方案。
官方kind0.33候選node1.36.4 registry-only比較結果為10Critical/40High/9未分類，
相較舊候選18/57/16下降，但仍BLOCKED；沒有新豁免、建置、節點執行或叢集。
建議先一批完成精確適用性、預載映像／CNI盤點，再交付整合修補清單；
新方向待確認，不沿用舊Traefik核准。詳見
[節點修補評估](CHG-301-R2-NODE-REMEDIATION-RESEARCH.md)及
[機器證據](CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json)。
既有14Docker容器／網路／image清單不變；完整R2／coverage／PR尚未完成。

最新核准後續驗（2026-09-16）：**Traefik精確兩項適用性判定已獲Peter核准，
受限CLI smoke通過，134項guard tests通過；新的kind節點映像安全gate阻擋。**
官方kind0.32預設node1.36.1 ARM64掃描18Critical/57High/16未分類尚未接受，
不是已證實75個可利用漏洞，未執行節點。兩個smoke容器已精確清理，原Docker
基線不變；未建立Kubernetes、未更新PR／現行部署、未呼叫Provider。
詳見[續驗結果](CHG-301-R2-CONTINUATION-RESULT.md)及
[機器證據](CHG-301-R2-CONTINUATION-EVIDENCE.json)。完整R2/coverage仍未完成。

前輪唯讀續驗（2026-09-16 Asia/Taipei）：固定官方Release/binary/commit與355外部module
校驗值吻合，2,647個package的完整source import closure沒有OpenPGP。兩項均為
PROPOSED_NOT_AFFECTED，**正式適用性排除仍待Peter確認**，沒有自動VEX/啟動controller。
詳見[固定來源判定](CHG-301-R2-EXACT-SOURCE-ASSESSMENT.md)及
[證據摘要](CHG-301-R2-EXACT-SOURCE-EVIDENCE.json)。此續驗不等於完整R2、coverage或
Kubernetes通過；PR未更新，既有raw掃描與zero-symbol限制保留。

前輪執行結果（2026-09-16 Asia/Taipei）：**兩函式庫修補與驗證完成，整體安全仍阻擋**。
原10項OpenSSL告警移除，剩Docker CLI High與OpenPGP Unspecified兩項；未套用VEX。
實際18套件不變，只有7個library檔案及安裝metadata改動，94個guard tests全通過。
原14容器／網路／產品來源未動，只保留一個local-only測試tag；沒有controller、
Kubernetes、Provider或PR操作。詳見[最新報告](CHG-301-R2-TWO-LIBRARY-VERIFICATION.md)
與[機器證據](CHG-301-R2-TWO-LIBRARY-EVIDENCE.json)。下列歷史停點不代表最新結果。

最新材料進度：Peter已同意把固定官方signed index加入建置材料（Gate2）。
[書面索引補充](CHG-301-R2-SIGNED-INDEX-PLAN.md)後續已獲Peter明確核准，Gate4 APPROVED；
僅調整材料／solver證據要求，仍不啟動controller、不改現行環境或PR。
本輪只改規格／計畫／traceability，未實作或執行featuretests／build／scan。

前輪治理進度：Peter已明確核准[兩函式庫修訂計畫](CHG-301-R2-TWO-LIBRARY-PLAN.md)，
Gate4 APPROVED。執行前核對apk3.0.6官方原碼，發現離線升級並保留world需要
另帶官方signed index，超出目前recipe＋兩APK的材料清單；待確認此有限材料調整。
狀態BLOCKED_OFFLINE_INDEX_SCOPE，詳見修訂計畫§6。OpenPGP仍INDETERMINATE。
本輪只有核准紀錄／唯讀可行性研究；runner/tests SHA未變，下方58PASS及cleanup
是前輪證據，未新增feature測試、建置、重掃、Docker/Kubernetes或PR操作。

最新執行結果：[修補前真實檢查與58項測試](CHG-301-R2-TRAEFIK-REPAIR-VERIFICATION.md)。
固定APK簽章/索引已通過；實際rootfs不存在openssl指令套件，三套件升級方案
停止，尚未建置。OpenPGP分析退到模組層，仍INDETERMINATE；不自動豁免。
已精確清理，原14容器/網路/image inventory不變，Kubernetes/資料/PR未動。
兩函式庫範圍現已核准；新的索引材料問題如上，完整R2未完成。

2026-09-15最新方向確認：Peter以「Ok」接受前輪測試映像修補＋精確漏洞判定
建議（新Gate2）。[修補計畫](CHG-301-R2-TRAEFIK-REMEDIATION-PLAN.md)已寫妥，
Peter隨後明確核准書面計畫，Gate4 APPROVED；執行由固定來源及隔離前置檢查開始。
下方候選失敗與28PASS均為前輪證據；本次核准不等於漏洞接受或完整驗收通過。

## 最新：已核准Traefik計畫並完成候選掃描

Peter於2026-09-15以「OK」核准書面Traefik隔離計畫。已完成官方
v3.7.13/chart41.5.0、ARM64 digest、全severity/SBOM和28項局部guard測試。
新候選掃描2Critical/8High/1Medium/1Unspecified，安全gate仍BLOCKED。
已記錄OpenSSL原廠評級／功能條件、Docker CLI的Windows/版本不符、OpenPGP
子套件判讀限制；不把raw命中當成已證實可利用，也未自動豁免。
[最新詳細結果](CHG-301-R2-TRAEFIK-VERIFICATION.md)及
[machine evidence](CHG-301-R2-TRAEFIK-EVIDENCE.json)。
探測容器已清除、原有14個Docker容器基線相同；未建立叢集或改動現行Kubernetes。
完整R2／80%全來源coverage／實際Ingress驗收／PR更新仍未完成。

## 前輪歷史：pytest／FTP、退休NGINX與替代方案規劃

2026-09-15。Peter 已核准 R2 Gate 4，並以「同意升級pytest，接收明文風險」
核准已呈現的最小安全修正。**pytest／FTP 兩項停點已處理；完整驗收仍 BLOCKED。**
新停點是測試叢集的 Ingress NGINX 候選映像：官方已停止維護，且本次掃描尚有
未接受的 High/Critical。沒有安裝叢集、變更現行環境或更新 PR。
此輪只改 dev pytest及其lock、測試／驗證工具及治理證據；沒有產品／SQL更動。

後續經 Peter 同意完成[入口漏洞與替代方案研究](CHG-301-R2-INGRESS-RESEARCH.md)：
9 個代表性 CVE 已記錄條件判讀，其餘 65 個 High/Critical 未完成逐項判定；
建議優先討論 Traefik NGINX 相容模式。這只是研究，不是安全放行或方案實作核准；
沒有新增 image／controller、修改 chart、執行部署或更新 PR，完整 R2 仍 BLOCKED。

2026-09-15 Peter 後續以「同意」確認上述測試方向（新附註 Gate2）。已新增
[Traefik 隔離驗證計畫](CHG-301-R2-TRAEFIK-PLAN.md)及 CMPING-001..005、
CMPING-T01..T08 規格／追蹤。新 Gate4 尚待核准；本次只寫治理文件，
Traefik image/chart 尚未下載、掃描、安裝或實測，現行環境未改。

## 最新結果：pytest 升級與 FTP 風險核准

| 檢查 | 新結果與範圍 |
| --- | --- |
| 最小依賴更新 | `pytest8.4.2 → 9.0.3`，`pytest-cov6.3.0` 不變；所有其他完整package records相同，專案metadata只改dev pytest限制。 |
| 正式依賴隔離 | 前後 `uv --no-config --offline export --frozen --no-dev --no-emit-project --no-header --no-annotate` 位元組相同，SHA256 `28a78400e81f15a01bd204f81f1203b253f30ef5215986a7af7cb39e8e1fc5e8`；原venv未改。不是候選runtime SBOM證明。 |
| pytest9.0.3 相容性 | 全新frozen venv跑原81項package/config回歸，**81 PASS**；真實GnuPG/OpenSSL/檔案操作，test-file cleanup=true。 |
| 局部coverage | package全模組lines87.69%／branches82.26%／combined86.56%；兩模組各項均>=80%。不是完整Frontend/Backend coverage。 |
| 風險政策測試 | **13 PASS**；真實來源檔與純政策輸入，核准缺失、SHA／路徑／行號／規則／嚴重度／信心改變或新High不得套用FTP接受；原 findings保留。 |
| 依賴重掃 | npm production/full皆0；pip production54套件/full60套件皆0；原pytest漏洞不再命中。 |
| Bandit重掃 | `--ignore-nosec`仍報3 High、32 Medium、90 Low；只有指定來源hash的3處FTP為 **ACCEPTED_RISK**，不是修復、忽略或全系統PASS。 |
| 來源／操作界線 | 140項來源／鎖檔／風險核准allowlist SHA前後相同；零Provider、零Kubernetes寫入、零PR操作。 |

新證據：[SECURITY-AMENDMENT-EVIDENCE.json](CHG-301-R2-SECURITY-AMENDMENT-EVIDENCE.json)。
明文風險核准：[FTP-RISK-ACCEPTANCE.json](CHG-301-R2-FTP-RISK-ACCEPTANCE.json)。
掃描時間2026-09-15T11:45:36–11:45:50Z；狀態
`PASS_WITH_ACCEPTED_RISK_SCOPED`只限這次dependency/static掃描。
原失敗結果完整保留於下方歷史段落及舊JSON，未以新PASS覆蓋。

### 已執行的重現命令

```bash
env -i PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPYCACHEPREFIX=/private/tmp/chg301-r2-pytest-layr63SP/pycache \
  /private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python -m pytest \
  -c /dev/null --rootdir=. --noconftest -p no:cacheprovider \
  --basetemp=/private/tmp/chg301-r2-pytest-layr63SP/policy-files \
  --junitxml=/private/tmp/chg301-r2-pytest-layr63SP/policy.xml \
  -q backend/tests/test_chg301_r2_security_policy.py
CHG301_ISOLATED=1 /private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python \
  backend/scripts/chg301_package_verify.py
CHG301_R2_ISOLATED=1 backend/.venv/bin/python backend/scripts/chg301_r2_security.py
```

上面是當次確切路徑；重現時另建0700目錄與frozen venv，不覆寫既有證據。
掃描runner自行建立固定scanner環境，不依賴原venv內pytest版本。

## 新停點：Ingress 候選映像，不是 pytest 或 FTP

現有chart使用nginx ingress class、NGINX allowlist及TLS redirect annotations。
不能用另一controller或關掉Ingress/TLS來冒充同一chart驗收。
[官方公告](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)
說明Ingress NGINX於2026年3月停止維護／安全修補。
官方最後版本controller1.15.1/chart4.15.1，來源固定為
[該版本values](https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/charts/ingress-nginx/values.yaml)。

- 官方multiarch digest：`sha256:594ceea76b01c592858f803f9ff4d2cb40542cae2060410b2c95f75907d659e1`。
- 本次`linux/arm64` SPDX辨識的image digest：`sha256:fa34e053d6ac30a9df379caa4180154c3a6ff17b5f78ac377117da440b09ba20`。
- Docker Scout1.24.0 registry-only分析，未執行映像或安裝controller。
  227個components；125個唯一CVE、128個package/result instances。
  原始嚴重度：**16 Critical／58 High／37 Medium／7 Low／7 Unspecified**。
- `scout cves`沒有加`--exit-code`，exit0僅代表掃描完成，**不是安全gate通過**。
  JSON中有未接受High/Critical，依計畫§C.6／§D判定FAIL_GATE_REQUIRES_DISCUSSION。
- 已保存all-severity SARIF與SPDX及SHA；沒有套用ignore-base、ignore-suppressed、
  VEX排除或既有waiver。SARIF未提供獨立漏洞DB版本，不能聲稱已驗證DB freshness。
- 這些是套件／版本掃描命中，**不能說74項都已證實可被攻擊**。初步核對：

| 示例 | 實際判讀／下一步 |
| --- | --- |
| CVE-2026-39821 | Go1.26.1／x/net0.52.0版本命中，controller二進位含相關構件；若hostname授權檢查後再做IDNA轉換，可能被繞過。上游修正Go1.26.6、x/net0.55.0；本controller實際可達路徑未證明，未自行重建。 |
| CVE-2026-31789 | Scanner標Critical，但OpenSSL上游標Low且限32位元、大於1GiB憑證的印出／記錄；本次ARM64存在適用性差異。保留raw結果，不當成已證實ARM64漏洞，也未默默豁免。 |
| CVE-2026-33186 | 上游是gRPC-Go路徑授權問題；scanner卻匹配Alpine C++ grpc1.76.0-r2。需釐清ecosystem誤配；Go修正版1.79.3不能直接套用C++套件。 |

示例來源：[Go](https://pkg.go.dev/vuln/GO-2026-5026)、
[OpenSSL](https://openssl-library.org/news/vulnerabilities/index.html#CVE-2026-31789)、
[gRPC-Go](https://github.com/grpc/grpc-go/security/advisories/GHSA-p77j-4mvh-x3m3)。
全部命中與來源：[INGRESS-SECURITY-EVIDENCE.json](CHG-301-R2-INGRESS-SECURITY-EVIDENCE.json)。

處理方向需另行決定：建議先規劃受維護入口controller的相容性調整，保留TLS、
allowlist、OIDC與NetworkPolicy契約；先在獨立環境驗證，不動現行部署。
另一選擇是只為短期、loopback、合成資料測試提出精確風險例外，但仍需逐項適用性
判讀、剩餘風險及補償措施，不能繼承本次FTP核准或以「隔離」視為零風險。
目前兩個方向都沒有執行／視為已核准；沒有新增產品開發計畫或更換chart。

本輪只保留私有證據、公開套件venv/cache與registry分析cache；沒有測試叢集、
controller容器、新服務帳密／PVC／應用資料需要清理。package測試Secret已由runner
exact-owned cleanup移除。完整suites／全來源coverage／候選應用images／Kubernetes／
Provider案例仍未完成；不commit/push/deploy。

最新收尾檢查：`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、
`test:plan`、`git diff --check`、`uv --no-config --offline lock --check`皆PASS。
這些是治理／鎖檔一致性檢查，不能取代未執行的完整測試或Kubernetes驗收。

## 歷史：核准安全附註以前的結果（下列FAIL已由上方處理）

| 檢查 | 結果與界線 |
| --- | --- |
| 隔離預檢 | Docker 8 CPU / 約31.3GiB；探測當時餘裕扣保留量後約3.63 CPU /14.79GiB，磁碟約255GiB可用。這不是三節點完整負載可行性的證明；尚未建叢集。 |
| 既有資源保護 | 只建立一個無網路、無掛載、唯讀根檔案系統的32MiB容量探測容器；核對 exact ID/label 後清除，既有容器 ID/狀態/啟動時間/重啟次數比對相同。 |
| Frontend production / full npm audit | 兩者查詢皆0項已知漏洞。鎖檔677筆外部項目皆為公開 npm registry。未安裝或升級應用套件。 |
| Backend production pip-audit | 54套件，0項已知漏洞。 |
| Backend full pip-audit | 60套件；pytest 8.4.2 命中1個唯一漏洞。原始服務重複回報兩筆同ID，未誤算為兩個漏洞。**FAIL**。 |
| 既有 Bandit 高嚴重度／高信心 gate | 原本顯示0，但含3個既有 `nosec` 忽略；不能用這個結果當完整 R2 PASS。 |
| 不繼承忽略的 Bandit 重掃 | `--ignore-nosec`：44,551行、3 High、32 Medium、90 Low、0 skipped。3個 High 都關於明文 FTP；**FAIL，沒有風險豁免**。中低靜態提示也未宣稱全數排除或修復。 |
| 規格／部署靜態檢查 | `spec:doctor`、`spec:trace`（11需求）、`plan:doctor`、`plan:approved`、`test:plan`、`deploy:config-policy`、`helm:lint`、`docker:config` 通過。不是 Kubernetes 實測。 |
| 語法與差異 | 兩個新runner AST解析、兩個entrypoint `sh -n`、`git diff --check` 通過；沒有匯入應用或盲跑 live test collection。 |

掃描日期與工具／鎖檔／139個allowlist來源SHA見
[machine evidence](CHG-301-R2-VERIFICATION-EVIDENCE.json)。前後來源hash相同。
npm11.12.1、Node25.9.0、uv0.11.8、Python3.12.10、pip-audit2.10.1、Bandit1.9.4。
這是本機掃描工具版本，不是候選 Frontend 映像的 Node 版本。

## 歷史：先前提出、現已核准處理的兩類問題

### 1. pytest 測試工具漏洞

- 命中：`pytest 8.4.2`，`CVE-2025-71176 / GHSA-6w46-j5rx-g56g`。
- GitHub Advisory 評為 Moderate，CVSS3.1=6.8。不是新增的應用遠端漏洞。
- 風險：UNIX共用暫存目錄及symlink處理，可被本機其他使用者干擾測試／可能提權。
- 上游修正版本9.0.3；現有 `pytest>=8.4,<9` 不允許直接更新到此版本。
- 建議討論最小調整：dev pytest升至9.0.3並更新uv.lock；檢查pytest-cov相容性、保留測試斷言與80%門檻，再重新掃描及跑完整suite。
- 不把更換測試venv內版本當作修復鎖檔；也不自行修改其他runtime依賴。
- 本輪runner使用0700獨立目錄降低暴露，但不是正式修復或核准風險豁免。
- Backend Dockerfile 使用 `uv sync --frozen --no-dev`，依建置規則此套件不屬正式runtime；候選映像尚未建置／掃描，不能用此推論代替SBOM。

來源：[pytest修正PR](https://github.com/pytest-dev/pytest/pull/14343)、
[官方9.0.3變更紀錄](https://docs.pytest.org/en/stable/changelog.html#pytest-9-0-3-2026-04-07)、
[安全公告](https://github.com/advisories/GHSA-6w46-j5rx-g56g)。

### 2. 明文 FTP 是既有產品設計，但有安全風險

- `backend/app/integrations/remote_sources.py` 第4行 B402、86與111行 B321；皆High/High。
- 這是同一類問題的3個程式位置，不是3個CVE；實際probe與download均使用 `ftplib.FTP()`。
- 帳密和檔案傳輸未加密，能觀察／干擾該網路流量的人可能取得或修改內容。
- `DSYNC-001` 明確保留FTP/FTPS/SFTP選項；`NET-002` 保留合法內部端點，因此不能直接移除FTP當成單純測試修補。
- 可討論：保留既有FTP相容性、明確接受本次範圍內的明文FTP風險及使用限制；或另行修改規格，只允許加密FTPS/SFTP。兩者均尚未獲新核准。
- 本次不能因舊 `nosec` 或舊風險接受而把它當PASS；後續runner已固定加入 `--ignore-nosec`。

## 原始失敗與重試保留

1. 第一次外連scanner被安全審查拒絕，擔心私有metadata傳送。未執行掃描。
   唯讀核對鎖檔所有外部套件皆公開、npm程式排除root專案，並引用已核准§D；
   加入public-only guard、PyPI明確服務及no-emit-project後，同一權限請求獲准。
   沒有繞道或傳送source/Secret；不讀operator npm/uv設定。
2. 首次runner因npm不允許user/global同用 `/dev/null` 而BLOCKED：
   `/private/tmp/chg301-r2-security-3r46b4nv/result.json`。改用另一個本run空global設定檔後重試。
3. 重試dependency/static完成：`/private/tmp/chg301-r2-security-g_q1g4pw/result.json`。
   其Bandit帶既有忽略結果由同來源補充 `bandit-unsuppressed.json` 取代作R2判定。
4. `docker:config`第一次因極小PATH未包含 `/usr/local/bin/docker` 回127；
   補回既有工具路徑後PASS。仍以空環境、`COMPOSE_ENV_FILES=/dev/null`、
   `COMPOSE_DISABLE_ENV_FILE=1`及`--no-env-resolution`禁止讀取operator設定。

## 還沒有完成的項目

- 完整Frontend/Backend suite、去除行為mock、兩端全來源80%coverage及live E2E。
- 候選映像建置、全部容器漏洞掃描與SBOM。
- 獨立三節點Kubernetes／CNI／TLS／OIDC／NetworkPolicy／V049／失敗與回退驗收。
- 真實Provider相關案例：仍未核准，零呼叫；不得用fake補成PASS。
- PR更新：沒有commit/push/merge；保持等待全部gate符合。

本輪未建立叢集、namespace、PVC、測試帳密或合成應用資料。容量探測容器已清除；
只保留私有0700暫存root內的公開套件scanner環境/cache、allowlist程式副本與證據，
沒有新長駐服務、沒有新增候選映像、沒有修改目前部署／kubeconfig／資料。
原CHG-301局部81測試／19容器／3 Compose PASS只保留原範圍，不冒充R2完成。

## 重現命令

```bash
CHG301_R2_ISOLATED=1 backend/.venv/bin/python backend/scripts/chg301_r2_preflight.py
CHG301_R2_ISOLATED=1 backend/.venv/bin/python backend/scripts/chg301_r2_security.py
```

前者僅建立／清除精確owned探測容器；後者只對新私有allowlist副本進行公開metadata
掃描與靜態分析，不連應用或Kubernetes。兩者都不是完整release驗收runner。

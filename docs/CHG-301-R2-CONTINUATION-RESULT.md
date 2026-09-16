# CHG-301 R2：適用性核准後的續驗結果

2026-09-16 Asia/Taipei。**局部通過；完整驗證停在新的 kind 節點映像安全門檻。**
規格：§10.58 CMPPATCH-003/004、CMPVERIFY-004/005。未更新PR或現行部署。

## 1. 本輪完成

- Peter的原文核准記錄於[APPLICABILITY-ACCEPTANCE.json](CHG-301-R2-APPLICABILITY-ACCEPTANCE.json)，
  SHA256 `87c5c7b4e26e363a51a8328780955b93d57855d40821e51f2e883807b10a7110`。
  只接受指定Traefik映像的CVE-2025-15558、GO-2026-5932不適用判定及既述證據限制。
  原掃描／判定文件未改寫，沒有scanner suppression、通用VEX或其他漏洞豁免。
- 固定Traefik imageID
  `sha256:5043ce31721c19e4a3a18afd60f449a7c842d46a52ec1ed6d7fdfb84a68cf7cd`
  的binary、已核准文件、原始SARIF/SPDX及產品來源核對通過。
- 真實`version`和`--help`均exit0，版本3.7.13、linux/arm64。
  使用兩個獨立暫時容器：UID/GID10001、network=none、read-only、cap-dropALL、
  no-new-privileges、128MiB RAM/swap、0.5CPU、64PIDs、無mount/port/plugin。
  這只是CLI啟動，不是HTTP/TLS/OIDC/NGINX相容性或Kubernetes驗收。
- **134 tests PASS，0FAIL/0ERROR/0SKIP，11.192秒**：保留原94項契約，
  加入精確核准、時限、禁止擴張、真實容器設定及node掃描身分／隔離guard。
  原94項中的歷史核准測試改用真實歷史段落，並新增它不能解鎖當前操作的斷言；
  未刪除原斷言語意。此suite不是完整Backend/Frontend coverage。
- 兩支本輪runner Bandit1.9.4完整掃描：0High/0Critical、1Medium、11Low，
  無分析error、無nosec。Medium為既有APK歷史簽章演算法判讀，raw結果保留。

首次smoke前置檢查因兩份既有「建置後結果文件」與建置時snapshot不同而拒絕，
尚未操作Docker。核對其內容、修改時間及產品SHA後，只將兩份文件的精確新SHA
綁入guard；没有放寬任何產品／image／依賴校驗。原失敗未算PASS。

## 2. 新停點：kind測試節點映像

[kind v0.32.0官方發布頁](https://github.com/kubernetes-sigs/kind/releases/tag/v0.32.0)
列出的預設節點`kindest/node:v1.36.1`：

- index SHA：`3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5`
- linux/arm64 SHA：`8d85371a247dc0fddce0d585d3de1ce40f2ee43f97fc0d0b6ee37b158771109e`
- 掃描2026-09-15T17:36:42Z–17:37:15Z；官方tag前後未漂移。
- **registry-only，未Docker pull/load/run，未建立kind節點**；530個SPDX項目（含image）。

| 原始掃描分類 | 去重告警數 |
| --- | ---: |
| Critical | 18 |
| High | 57 |
| Medium | 59 |
| Low | 80 |
| 未分類 | 16 |
| 合計 | 230 |

另有313筆package命中實例，不能和230個去重告警混算。75個High/Critical及16個
未分類尚未逐項完成適用性判定。**不是75個已證實可利用漏洞，也不是NomoSmart
程式新增75個Bug**；它們屬於另一份測試基礎映像，不能繼承Traefik核准。
Scout未提供可獨立核實的DB版本，保留實際查詢時間／工具版本及raw報告限制。

代表性項目（不是完整triage或自動排除）：

- `CVE-2026-33186`：掃描命中grpc1.76.0。原廠說明須涉及path-based授權及
  特定deny/fallback-allow組合，修補版1.79.3；尚未證明節點內相應binary滿足或
  不滿足條件。[gRPC官方公告](https://github.com/grpc/grpc-go/security/advisories/GHSA-p77j-4mvh-x3m3)
- `CVE-2026-34182`：OpenSSL CMS輸入驗證問題，不能僅因節點使用TLS就推論
  可利用或不適用；需核實CMS使用路徑與實際Debian修補包。
  [Debian官方追蹤](https://security-tracker.debian.org/tracker/CVE-2026-34182)
- `CVE-2026-8376`：Perl問題包含32-bit build／不可信正規表示式條件。
  目前image平台為ARM64，但不能用平台字串代替內部構件證明，更不能因此排除
  全部Perl告警。[Debian官方追蹤](https://security-tracker.debian.org/tracker/CVE-2026-8376)

[機器證據](CHG-301-R2-CONTINUATION-EVIDENCE.json)完整列出91個尚未接受的
High/Critical/未分類ID、命中package與scanner提供的修補版本；修補版本仍需
逐項核對原廠，不代表已批准升级。原始SARIF及SPDX在私有run目錄保留。

## 3. 環境、資源與清理

- 原14個Docker容器的ID/status/startedAt/restartCount、網路及映像清單不變。
- 兩個暫時CLI容器與容量probe已按精確ID/owner移除；未移除其他資源。
  暫時容器可重新建立，執行證據保留；既有local-only Traefik測試tag仍保留。
- 容量實測：保留原4CPU/8GiB後，當時約剩3.39CPU／14.74GiB，磁碟約254.8GiB。
  這不是已證明三節點加完整服務stack能容納；仍須render/request/limit與runtime證明。
- 原批次deadline `2026-09-15T20:17:52.088462Z`不重置；後续若跨過時限需另決定，
  不因本次核准或新run ID默默延長。

## 4. 未完成及下一步決策

停止在安裝之前，未執行Cilium／其餘應用映像完整安全gate、三節點安裝、真實
Ingress/OIDC/NetworkPolicy、完整Frontend/Backend coverage或Provider案例。
沒有Provider呼叫，沒有PR寫入，沒有現行Kubernetes操作。

建議先針對**測試節點映像**提出安全可用的更新／最小修補方案，核對全部構件與
kind/Cilium相容性，再決定是否採用。不要將本批告警全部當誤報直接略過。
原計畫不允許自行更新這些依賴或新增風險例外，故本輪沒有開始修補或執行節點。
Owner：Peter決定新修補／適用性範圍；Codex提供可重現證據與方案。

## 5. 檔案及驗證

- `chg301_r2_ingress.py`：exact applicability/time/raw-evidence guard與受限CLI smoke。
- `chg301_r2_node_candidate.py`：固定官方node的registry-only SARIF/SPDX及baseline檢查。
- `test_chg301_r2_ingress.py`：真實artifact/CLI/容器結果與拒絕案例。
- 核准記錄、規格、計畫、TEST_PLAN、TRACEABILITY與本結果：只更新驗證範圍及證據。

命令：隔離pytest（`--noconftest -p no:cacheprovider -c /dev/null`，不import應用）；
`chg301_r2_ingress.py --phase smoke`；`chg301_r2_node_candidate.py`；
Bandit `--ignore-nosec`；`spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、
`git diff --check`。治理PASS不等於尚未執行的產品驗收PASS。

# CHG-301 R2 高風險修正與 PR 更新計畫

2026-09-16 Asia/Taipei。Gate 2 confirmed：Peter「同意」只處理High/Critical，
必要回歸通過後先更新原PR，完整coverage/Kubernetes實測明列未完成。
**Gate 3 written；Gate 4 approval: APPROVED。**
Peter於2026-09-16核准：「核准 CHG-301 R2 高風險修正、必要回歸與 PR 更新計畫」。
核准前計畫SHA256：ef830bcb3007261cb61b4cea5fcb0e96a607c16c2912065c54c248f6b4c34dbb。
以下範圍不變；末段pending/檢查結果保留為核准前歷史，不延長任何舊風險接受。
規格：SPECIFICATION.md §10.58 CMPHIGH-001..004、原CMPSTART-001..005及TEST-002/004。

## 1. 交付與不做的事

本批依序完成「高風險修正 → 必要真實回歸 → 原PR更新」，在已核准範圍內
連續執行，不為每個套件再次停問；無法安全完成則保留原因，不假稱修好了。

- High/Critical包含適用性未定及原廠已知Critical補充公告；不是只修已證實可利用者。
- Medium/Low/Unspecified標DEFERRED_BY_SCOPE，保留原始報告，不主動研究或修補。
  工具輸出其他severity照實保存；共同套件修復的附帶改善可記錄，不額外擴張。
- 延後全應用兩端coverage、全套E2E、Kubernetes實測，不建立叢集、不部署或合併PR。
  80%門檻／critical flow測試及所有舊失敗保留，不降低設定或刪除測試。
- 不改NomoSmart业务API、權限、SQL、現行Docker Desktop、資料、索引、Secret、
  Helm revision、主線部署設定；不呼叫Provider，不讀目前.env/備份/credentials。
- 不把「略過非高風險」解釋成接受尚未判定的High/Critical或新的安全豁免。

## 2. 起點與處理順序

以NODE-QUALIFICATION-EVIDENCE.json及其綁定raw/SBOM為起點。已知外層node有50項
High/Critical；12個額外映像有170個image×ID帳列，合併83個raw ID，另有
containerd GHSA-p7v4-vr35-mj6f。逐實物處理，不把去重ID數當成漏洞可利用數。

1. **固定基線與清單**：重新核对來源、待提交差異、工具、材料hash與現有容器
   非敏感ID/狀態/啟動時間/重啟次數；核對PR #1和main SHA。沿用有效舊證據但
   明列日期，為最終候選重掃，不對現行部署另做弱點掃描。
2. **按共同來源修補**：將告警依OS套件、Go工具鏈/相依模組、啟用映像分類，
   同一修正版可以覆蓋多個ID，仍逐image/package檢查。優先官方相容修正版，
   避免為每個CVE建立一套工具或自製整個Kubernetes發行版。
3. **完整候選驗證**：同時驗證外層node和啟用的預載/CNI/Ingress清單，不以
   更新外層Go/OS冒充內層binary已更新。相依閉包、有效rootfs、版本、digest、
   全severity原始掃描與SBOM綁定；必要guard/CLI/安裝修正回歸通過才進入PR。
4. **交付PR**：準備明確文件及來源綁定；通過§6才commit/一般push原分支並更新
   PR說明，保留既有討論，不合併、不直接改main，不觸發發布操作。

## 3. 可連續執行的修補界線

此節在新Gate4後才生效；不借用舊靜態核准。候選尚未證明可用，不預告必能清零。

### A. 官方候選與材料

- 官方kind node只選既定Kubernetes 1.36系列的相容patch，Cilium只選1.20系列
  相容patch，Traefik只選3.7系列相容patch；以官方支援資訊及來源校驗為準。
  先唯讀查詢官方公告/registry/release，再固定tag/index/ARM64 digest/配置。
- 預載CoreDNS、etcd、控制平面、helper等隨完整官方node候選一起校驗；
  不私自混搭控制平面、改預載CAS、換CNI實作或啟用以前未啟用的controller。
- 原CHG-301候選應用/依賴/SAST報告也核對有效性；若已有High/Critical，
  不以「只看node」排除。新增業務runtime依賴變更不在本計畫內，列為阻擋。
- 每個source family最多比較3個官方相容候選（含目前基線）；沒有修正版或
  需要跨minor/major、自製Go dependency fork、重編Kubernetes等，停止該修補路徑，
  完成其餘範圍後集中回報，不自行放行PR。
- 公開工具/OCI/套件只能從已驗證官方來源取得，記錄版本、大小、hash及原廠
  提供的簽章。不得關TLS/簽章、繞權限、執行下載的install script或自動toolchain。
  新工具信任根、私有服務或需不同runtime策略時停止討論。

### B. 限定本機測試映像 OS 修補

如果官方相容patch仍含可由OS套件更新解決的High/Critical，可對**外層測試node**
或既有測試Traefik產生唯一local-only衍生映像；不得覆蓋原tag/推registry。

- Node僅Debian13/ARM64現有已安裝套件，Traefik僅Alpine3.24/aarch64現有套件；
  依High/Critical的來源套件與必要已安裝相依閉包升版，不安裝額外服務/套件名。
- 維持相同distro、已安裝套件集合、entrypoint/CMD、USER、服務設定、CA信任、
  repository配置及啟用feature；保持應用/Go binaries與預載image CAS不变。
  不使用全系統upgrade，不把改動其他binary當成僅OS修補。
- 先由官方簽章index確認exact版本/架構/hash及solver的完整變更清單，形成
  machine-readable材料lock；payload與其必要相依均綁定後才建置，拒絕額外diff。
  舊17項index metadata不是可執行lock，不以資料夠了為由跳過payload/solver。
- 只在隔離BuildKit、明列公開材料context、network=none執行套件工具及必要
  maintainer scripts；這是包含待修漏洞工具的build-only風險，不啟動node/服務。
  禁止privileged/insecure entitlement/host network、host data/Secret/socket mount。
  BuildKit不能滿足隔離、腳本需啟服務或非允許檔案變動時停止，不放寬限制。
- 重掃與有效rootfs diff必須證實實際修正；歷史layers/raw告警保留。內層Go漏洞
  不會被外層OS更新治好，仍須官方候選或精確不適用證據。

### C. 適用性與既有測試契約

- High/Critical只能由真實修正版證據標FIXED；證明不適用者先標
  PROPOSED_NOT_AFFECTED，新判定仍需精確風險確認，不自行做VEX/suppression。
- 既有Traefik兩項接受只在原image/source/config/用途/有效期完整吻合時有效；
  新窗口不延長旧接受或把它移植至新映像。一般FTP接受亦不繼承到新來源。
- 修正舊test_cmppatch_real_human_acceptance_preserves_raw_findings的測試契約：
  真實歷史scope可驗證歷史接受，當前未授權scope仍必須拒絕。不得把目前計畫
  冒充歷史核准、刪測試、改guard直接允許或以mock/fake外部成功填補缺口。
- 新runner用自己的active plan/hash檢查；既有靜態runner仍拒絕build/runtime，
  原Traefik執行gate保持其用途限制，不靠修改舊scope文字繞過安全檢查。

## 4. 檔案與設定影響

| 檔案/範圍 | 修改目的 |
| --- | --- |
| 新backend/scripts/chg301_r2_high_risk.py與matching tests | 薄層協調既有artifact工具，high-only帳列、官方候選/材料lock、回歸/PR前置檢查 |
| backend/tests/test_chg301_r2_ingress.py | 修正歷史接受與當前拒絕的測試契約，不放寬production guard |
| deploy/test/內本次候選recipe/manifest | 精確测试映像與版本；正式chart/default/Compose產品設定不變 |
| docs/CHG-301-R2-HIGH-PR-* | 計畫、可審核帳列、材料/來源hash、結果與PR說明；不提交Secret/raw大檔 |
| SPECIFICATION/SPEC_CHANGELOG/DEVELOPMENT_PLAN/TEST_PLAN/TRACEABILITY | 範圍與驗證連結；原結果保留，不覆寫成新PASS |

既有暫存/已stage整合修改屬先前CHG-301整合工作，先盤點並保留，不混入無關新改動。
不新增SQL migration、功能flag或產品API；測試版本不宣稱可直接正式部署。

## 5. 必要回歸與資源

測試詳細Case見TEST_PLAN CMPHIGH-T01..T08。最小順序：材料及pure policy →
真實artifact/CLI → 所改映像必要smoke → 同來源治理/部署靜態檢查 → PR gate。

- 重跑原134及新77個真實artifact/guard cases；測試數可增加，不刪既有case。
  修正前1FAIL保留；純guardPASS不冒充實際registry/solver/build/漏洞修复PASS。
- 改動runner執行Bandit --ignore-nosec。候選跑完整raw Scout/SBOM，僅High/Critical
  作本批修補阻擋，不改scanner設定隱藏其他severity。新高風險亦需處理。
- 掃描已通過安全門檻的binary可以唯一owned nonroot容器做version/help smoke，
  network-none/read-only/cap-drop ALL/no-new-privileges、無host mounts/ports；
  不啟動kind node、controller、daemon或cluster。不能支援此模式者如實未測。
- 若實際修改原安裝器/Secret/CMD範圍，重跑既有真實CHG-301 entrypoint/package
  回歸；未修改且來源hash相同者引用歷史證據，明列不是本輪重跑。若需要更大
  live stack才能證明本次修補，停止並說明；不以假服務補足。
- 治理：spec:doctor、spec:trace、plan:doctor、plan:approved、test:plan；
  backend:syntax、helm:lint、deploy:config-policy、git diff --check。
  docker:config僅用合成設定/現有安全檢查路徑，不讀現行.env，執行前確認命令。
- 本計畫核准後第一個execution preflight建立新run，**6小時wall-clock窗口**，
  連續turn不重設，停止接新工作在截止前10分鐘；這不是延長舊run期限。
  每命令最長20分鐘、build30分鐘、相同原因最多2次retry，最多1build/1scan同時。
  保留至少4CPU/8GiB及20%RAM餘裕、100GiB磁碟free；本run磁碟≤40GiB、歷史測試
  artifacts加總≤80GiB。不可停止現有服務、清共享cache或改主機配置取得空間。
  Build/CLI計算最多4CPU/8GiB；Docker VM限額無法核實則不開始重作業。
- 所有新資源記exact ID/label/path/hash；清理先dry-run，只清本run所有物。
  禁止docker prune/廣泛down-v/刪旧audit證據。非敏感baseline變動即停查，
  不自行restart/delete現有資源。權限拒絕及保護流程是停點，不迂迴。

## 6. PR 唯一放行條件與 Git 行為

全部成立才更新 https://github.com/crispkid/Nomosmart/pull/1：

1. 核准範圍中的High/Critical都已FIXED或已有精確有效接受，沒有未解決或缺證據；
   本批必要回歸PASS、精確清理通過，來源與最後結果吻合。
2. PR说明明列Medium/Low/Unspecified延期、完整兩端coverage/Kubernetes/E2E未完成、
   舊測試與掃描失敗歷史及測試image用途；不寫「全部驗收完成／可正式部署」。
3. 重核PR #1仍OPEN，head分支fix/compose-method1-installer、base main，與preflight
   固定remote SHA一致。前次head c261a494283835af57c0e0678afc7ee7e2c0dcc8只作參考。
4. 唯讀檢查現有merge狀態、parents、tracked/staged/untracked diff；若原main整合
   無衝突且來源均為已核准範圍，可以完成原分支的整合commit與修補commit。
   不reset/abort/cherry-pick丟棄使用者變更，不git add .，逐檔檢查與stage。
   無關變更、衝突、他人新提交、未知merge狀態停止，保留工作樹。
5. 提交前檢查待push內容無Secret/私有資料/大raw檔，核對既有CI不會自動發布部署；
   若push會觸發不可分離的部署流程，停止討論，不更改保護規則繞過。
6. 一般push原PR分支並更新PR description（保留原文/加入本次段落）；不force、
   不push main、不新開替代PR、不merge/close/auto-merge、不approve自己的PR。
   重讀遠端驗證new SHA和說明；GitHub check沒有結果或失敗需照實回報，不能假PASS。

任一條件不成立就交付阻擋清單，不自行把未解決高風險改成低風險或先推已修復宣告。

## 7. 計畫核准與目前狀態

本輪只更新規格、理解、計畫與測試設計。沒有開始新修補/建置/scan/feature test、
Git commit/push、PR寫入或部署。舊77PASS/133PASS+1FAIL仍是歷史結果。

Gate 4待核准，建議核准文字：
「核准 CHG-301 R2 高風險修正、必要回歸與 PR 更新計畫」。
核准涵蓋上述官方相容候選選擇、限定local-only測試建置、新有界窗口及條件式
原PR更新；不包括高風險豁免、跨minor/major、自製Kubernetes、合併或部署。

本輪治理檢查：spec:doctor、spec:trace（30 active mappings）、plan:doctor、
test:plan及git diff --check皆PASS；plan:approved以exit1正確指出新Gate4 pending。
這些是計畫一致性檢查，不是修補／featuretests或完整驗收完成。

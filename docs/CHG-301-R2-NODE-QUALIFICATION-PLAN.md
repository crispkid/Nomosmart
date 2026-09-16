# CHG-301 R2：節點與基礎映像整批靜態判定計畫

2026-09-16 Asia/Taipei。Gate 2 confirmed：Peter以「Ok」確認前輪建議。
Gate 3：本計畫已寫妥。**Gate 4 approval: APPROVED**。
Peter於2026-09-16明確核准「核准 CHG-301 R2 節點與基礎映像整批靜態判定計畫」。
核准前SHA256：`f1cc8bec449f60aa4e4eae29f3d7eb9c7f4bc67badb1c8b3936650f7c43ac132`。
下方規劃階段的PENDING／未執行說明保留為歷史；只依本計畫限定靜態範圍執行。

## 1. 這次要完成什麼

**先把測試基礎環境的問題一次查清楚，交付一份可核准的修補清單。**
不在這一步修補、建置、啟動節點或部署；不承諾未知項一定能證明不適用。
規格：§10.58 CMPNODE-001..005，沿用CMPVERIFY-001..006／TEST-002及原R2界線。

已確認的工作：

1. 以固定官方Kubernetes1.36.4 node為候選，完整判定既有59項待處理告警。
2. 補查預載控制平面及既定CNI／Ingress真正使用的映像，不只掃node外殼。
3. 對應每項告警到實際套件／binary／來源及觸發條件，不能只看套件名稱。
4. 合併成一份修補材料清單：哪些可更新官方套件、哪些需官方binary、哪些仍未知。
5. 留存真實原始結果、工具限制、未完成項與環境未變的證據。

前輪依據（不得覆寫成新結果）：

- [更新評估](CHG-301-R2-NODE-REMEDIATION-RESEARCH.md)，SHA256
  `108971961a27e7b11ac33b2d251d7854e5e9c21f01dc3bc60dfab2ed09adf785`。
- [評估機器證據](CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json)，SHA256
  `c457eb15d3322451e6aefc544c70e1b969fa5b68cb8616f7224ef21c4f2f77ba`。
- 新候選raw：10Critical／40High／9未分類／27Medium／65Low，151個去重ID、
  181命中實例、534個SPDX項目（含image）。59項不是59個已證實可利用漏洞。
- 補充`GHSA-p7v4-vr35-mj6f`獨立核對，不竄改原scanner計數。
- 先前134guard PASS及Traefik CLI smoke保持原範圍，不代替本輪或完整R2。

## 2. 固定範圍與授權界線

### 2.1 可分析的候選

| 項目 | 固定來源／選取方式 |
| --- | --- |
| Node | `docker.io/kindest/node:v1.36.4`；index `sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`；ARM64 `sha256:10210eabcf5dc4b585756bbd3f7fbb60cc0a12a252f28aeba269d93e0070c025`。 |
| kind | v0.33.0只讀官方固定來源／發布metadata，供node對應及設定理解；本計畫不下載或執行新kind binary。 |
| Node預載／必要映像 | 從上述固定OCI實物、啟動設定及同版本來源發現控制平面、etcd、DNS、pause、儲存helper等實際reference；保存parent digest及來源位置。沒有實物／來源依據不猜tag。 |
| Cilium | 既定1.20.1官方chart；只解析與綁定同版本archive／appVersion／image digests。包含實際啟用的agent/operator/Envoy、init/sidecar/hook/helper；不改CNI版本、啟用Hubble或加入新功能。 |
| Traefik | 既有3.7.13／chart41.5.0，chart SHA256 `30f8db73182019b2764179d7fc0a7efc9505670204f847ffc3a779bacaae3a1a`。固定修補imageID `sha256:5043ce31721c19e4a3a18afd60f449a7c842d46a52ec1ed6d7fdfb84a68cf7cd`；優先重核已存archive／raw報告，不啟動。 |

Traefik两項接受只依原APPLICABILITY-ACCEPTANCE.json精確綁定，不傳播到node或
其他image，不重置有效期限。修补與原版image證據不可混用。
本次整批盤點只含以上基礎映像；應用Backend／Frontend／Migration和其他服務
仍有原R2安全門檻，不冒稱本次已覆蓋全系統，也不新增其建置工作。

### 2.2 Gate4後允許

- 寫有限的分析runner及真實artifact／純政策guard測試；不改產品行為。
- 唯讀非敏感Docker inventory；既有Scout正常使用其已配置授權，只傳送
  公開image/PURL/digest資料，不擷取／複製其credential。
- 從官方來源下載固定OCI blob、chart、advisory、對應原始碼及純資料形式的
  package索引／簽章／材料；先綁定出處、版本、hash、大小及平台。
- 在唯一私有run目錄解析、比對、記錄。必要archive是下載到檔案，
  **不是Docker pull/load**；不得導入Docker或containerd image store。
- 使用既有已驗證工具做靜態ELF/build-info／source分析、registry或可支援的
  archive-only掃描、offline Helm template（固定Kubernetes版本、無cluster）。
- 保留結果並依exact-owned manifest清理本輪暫存檔；不逐項重問相同範圍。

### 2.3 明確不允許

- Docker build/pull/load/create/run/exec、node或controller smoke、kind建立／刪除、
  kubectl／Helm server操作、Job／network／volume建立或變更。
- 執行候選binary、entrypoint、套件安裝腳本、`apt upgrade`，或重編Kubernetes。
- 執行`go generate/build/test/install`、自動下載／切換toolchain、安裝新工具，
  或以本輪修正更改應用／OS／Go依賴鎖檔、正式Dockerfile或chart。
- 讀現行.env、Secret、模型設定、備份、私有keyring、生成套件或資料目錄；
  修改主機proxy、DNS/hosts、信任庫、Docker Desktop或使用者kubeconfig。
- 呼叫Provider、處理真實文件、reprocess/re-embed/reindex、更新PR／commit/push。
- 新VEX／scanner suppression／風險豁免，或把本輪完整盤點等同runtime安全通過。

## 3. 一次性執行順序

### A. 核准、來源及資源綁定

1. 驗證最新active plan明確Gate4核准和核准前本計畫SHA，不能用歷史APPROVED。
2. 記錄HEAD／merge parent與明確allowlist來源SHA、runner/tests/tool版本；
   不將git diff正文或私有設定傳給scanner。保留dirty worktree，不做git寫入。
3. 驗證原批次deadline及資源條件。只讀既有容器ID/status/startedAt/restartCount、
   network/image inventory和可用容量；不建立容量probe容器。
4. 建立0700私有run root／0600manifest及raw結果。每個操作記argv、時間、exitcode、
   工具SHA及output SHA；不得將bearer token、cookies或設定值寫入報告。

### B. 一次建立完整候選清單

1. 前後核對node tag→固定index→ARM64 manifest→config/layer digests；有漂移即停止
   該候選，不換用新tag。下載器只取manifest授權的blob，檢查長度／SHA／TLS。
2. 既有Traefik`image_rootfs()`將整個小image讀入記憶體，限制1GiB archive／256MiB
   blob，不適合直接處理大型node。新runner需用受限stream／disk-backed解析，
   **不調大或關閉既有Traefikguard**。共用純安全邏輯須保留原回歸契約。
3. 正確還原有效layer視圖，記錄檔案hash、模式、owner、symlink/hardlink及whiteout；
   不套用setuid或device node至host，不追隨artifact symlink寫檔，不執行任何內容。
   防止absolute/parent path、連結逃逸、重复衝突、超量展開；無法辨識則標缺口。
4. 找出內嵌OCI/containerd archive與啟動設定，逐一綁定子image的平台與digest。
   舊layer內但已被whiteout移除者須標明歷史層，不混成有效runtime。
5. 取得固定Cilium chart，核實archive SHA／version／appVersion／依賴來源；
   以原R2保留kube-proxy、無新增功能的設定offline render，列出所有image field、
   hooks、init／sidecar與來源模板。未啟用image也記原因，不能無聲漏掉。
6. Render使用private合成values、固定kube-version／必要API清單，禁止server dry-run、
   lookup連線、post-render executable和動態dependency update。chart不足或結果
   依賴未知cluster能力時列BLOCKED，不臆造完整清單。
7. 建立去重inventory，包含image父子關係與實際用途。不相關URL／版本／repository
   不納入自動抓取；同版本官方registry/CDN redirect須逐跳檢查，不關TLS。

### C. 掃描與逐項判定

1. 每個有效候選image保留all-severity SARIF／SPDX、平台／config／來源綁定、
   工具和查詢時間／可得DB資料。優先reuse相同digest的真實證據並標原查詢時間，
   不把舊報告改日期；不支援nested archive且無相同digest的公開image時明列BLOCKED，
   不為方便而Docker load、改tag或上傳完整image。
2. Node59項及補充公告各有帳列。每個advisory對应所有命中PURL/version/binary
   path／hash，保留scanner規則／原評級及package-instance粒度；避免rule合併造成
   fixed_version套錯套件。新增／消失／改評級分開，不以去重數代替修復證明。
3. OS：核對Debian原廠安全追蹤、實物package資料、source版本／patch、架構及
   官方signed index；現行主機keyring不參與。簽章／信任來源不足明列未證實。
4. Go：核對binary build-info、vcs revision、module checksums／replacement、
   build tags／平台，再核對advisory實際package／函式／觸發條件。
   只有module出現／strings沒命中不構成可利用或不適用證據。
5. 只用既有固定工具做`go version -m`／ELF解析／可用的binary分析。若需source
   closure，先驗證官方commit與module binding，在private caches中用既有已驗證Go
   解析，`GOTOOLCHAIN=local`、`GOENV=off`、`GOWORK=off`、`GOTELEMETRY=off`；
   下載與離線分析分階段，不執行第三方generate/tests／新toolchain。
   缺module、cgo／build環境不符、工具版本差、partial graph或缺symbol都明列限制，
   不能拿Go命令exit0當完整證明；需要更大執行權限時停止該項並記INDETERMINATE。
6. 特別核對containerd checkpoint公告與預定有效設定。只看2.3.4版本不代表
   功能未重新啟用；snapshotter附帶2.2.0與主daemon須分開。靜態無法確定的
   runtime設定列後續驗收條件，不冒稱已實測。
7. 原始ID不能刪除。分類為AFFECTED／PROPOSED_NOT_AFFECTED／INDETERMINATE；
   只有充分版本／patch／實物證據才可FIXED。新not-affected建議仍待Peter逐範圍
   確認，不繼承Traefik或FTP接受，不產生通用VEX。

發現High/Critical或未知時，runtime持續BLOCKED，但**繼續其他已核准且安全的
靜態盤點，最後一次交付全部結果**。這不是放行；權限、來源、下載安全、容量或
期限失效則停止相關操作，不能用批次處理名義越過限制。

### D. 整合修補材料清單及交接

每項方案至少含：受影響image/binary、原版本、建議官方版本、URL／hash／簽章
證據、必要相依閉包、對應advisory、預期rootfs／設定變更、重編需求、驗證方式。
優先官方更新構件；不能確認hash／來源／相依者標UNRESOLVED，不輸出可執行lock。

交付三類：

1. 可提出精確最小修補的材料；仍需後續建置核准。
2. 有證據支持不適用但等待確認的項目；不是自動豁免。
3. 證據不足、無修正版、工具限制或需Kubernetes fork的項目及代價／替代選項。

本計畫成功只能標`STATIC_ASSESSMENT_COMPLETE`（所有項目有誠實狀態）；若時間或
工具不允許完整盤點則`PARTIAL/BLOCKED`。即使全列完，仍可有runtime blockers，
不能標image安全PASS、fullR2完成或自動銜接原計畫建置／叢集。原兩端80%及
Kubernetes／Provider／PR門檻不變。後續只對這份整合清單另行核准修補與驗證。

## 4. 有界網路、資源與清理

- 下載僅限從固定artifact與官方資料導出的registry/CDN／source／advisory／package
  metadata；禁止現行服務、內網URL、任意圖譜連結探索。公有registry匿名短效token
  只保留記憶體、最小read scope、不記錄值。redirect禁止降級HTTP或傳送跨站授權。
- 原工具正常設定不擷取；新下載器不繼承operator proxy/auth/env，TLS驗證保持開啟。
  需要安裝新工具或更改網路設定時列缺口，不自行繞过權限／proxy限制。
- 一個scanner、最多兩個下載並行；不啟動stack。分析需保留原4CPU／至少8GiB及
  20%RAM餘裕，主動監測CPU/RSS；分析程序合計RSS停止值4GiB。
  監控不是OS硬quota；高壓時停止本run，不調整Docker VM或現行服務。
- 本run下載／展開／分析暫存合計<=40GiB，仍計入原整批80GiB增量；可用磁碟
  至少100GiB。單blob<=4GiB、單layer展開<=8GiB、最多64layers/image、
  1,000,000 entries/image、archive巢狀深度<=4，超限記BLOCKED，不自動放大。
  Digest去重、省略不必要payload及streaming不可以跳過完整性核對。
- 單下載／scanner／source分析最多20分鐘；始終取與原批次剩餘時間的較小值。
  原硬期限 **2026-09-15T20:17:52.088462Z（台北09-16 04:17:52）不重置**，
  截止前預留10分鐘保存／清理，不足即不啟新工作。核准到達已過期只回報，
  不以新runID延長。相同暫時故障最多兩次修正重試，權限拒絕不自動重試繞過。
- 清理先列manifest內精確路徑／inode／owner／hash dry-run，再刪本run暫存檔；
  不刪舊證據／快取／testimage、不system prune、不遞迴清除共享root。
  保留去敏感原始報告及必要公有artifact，記錄清除與保留的項目／大小。
- 前後唯讀比較Docker inventory及來源；外部作者／程序改動也記漂移，不動他人
  資源來恢復相等。失敗和cleanup失敗保留為BLOCKED，不偽造baseline相同。

## 5. 程式與資料契約

| 檔案／資料 | 核准後有限變更 |
| --- | --- |
| `backend/scripts/chg301_r2_node_qualification.py` | 新增靜態phase runner；approval/time/source、OCI streaming、inventory、scan/triage、evidence／cleanup；無runtime phase。 |
| `backend/tests/test_chg301_r2_node_qualification.py` | 新增T01–T08，真實publicartifact／本機程序／純政策negative inputs；不mockregistry、scanner、cluster或成功資料。 |
| `backend/scripts/chg301_r2_node_candidate.py` | 若有必要才抽出純identity／raw-report共用邏輯，保留舊固定候選及失敗證據，不將舊核准改成新放行。 |
| `docs/CHG-301-R2-NODE-*`及治理檔 | plan、實际inventory／assessment／材料提案／驗證結果；來源／證據可追溯。 |
| private run root | inventory-lock、phase outputs、OCI/source cache、raw SARIF/SPDX、逐項ledger、baseline與cleanup manifest；敏感資料禁止進版控。 |
| 產品、SQL、dependencies、正式chart、既有Traefik修補 | 不改；本輪結果不能改寫歷史raw或hash-bound接受文件。 |

Inventory最少：parent/image digest、platform/config、來源URL／實物位置、用途、
啟用狀態及原因、scan/SBOM SHA與時間、解析完整性／錯誤。
Assessment最少：ID、raw severity、package/version、binary/path/hash、official
advisory、conditions、實物／source binding、判定、limits、建議修補及待確認項。
新增lookup鍵／hash不能代替查不到的真實證據；不填預設PASS。

## 6. 測試設計與驗證命令

| Case | Requirement | 必須觀察到的結果 |
| --- | --- | --- |
| CMPNODE-T01 | 001/005 | 真實active plan／來源／平台／digest binding；未核准、舊核准、hash／平台失配、到期均在下載前拒絕。 |
| CMPNODE-T02 | 002 | 真實OCI與本機安全解析輸入；SHA錯誤、path/link escape、whiteout、重複member、解壓／深度超限不得逃逸或執行；正常artifact映射正確。 |
| CMPNODE-T03 | 001 | 從真實固定node/archive/chart列所有啟用image／父子digest／hook/init；缺image或無platform/scan證據不能標完整。 |
| CMPNODE-T04 | 003 | 真實全severity SARIF/SPDX與image binding；保留ID及package instances；不因聚合fixed_version、suppression、缺DB/失敗scan而假PASS。 |
| CMPNODE-T05 | 002/003 | 真實ELF/build-info/source closure和實際限制；module-only、零symbol、partial graph及工具／build環境不符不得PROVEN_NOT_AFFECTED。 |
| CMPNODE-T06 | 004 | 材料ledger對應原告警／來源hash／相依；未取得材料或官方無fix明列未知；不產生可執行的假lock。 |
| CMPNODE-T07 | 002/005 | 真實CLI及argument policy拒絕build/run/exec/kubectl/server/auto-toolchain/任意endpoint；不靠fake subprocess證明沒有副作用。 |
| CMPNODE-T08 | 005 | 原期限／資源停止、before/after來源／Docker基線、exact-owned cleanup；保留不属于run的真實檔案，漂移／清理失敗不能PASS。 |

純政策negative inputs只驗證guard，不冒充真實external服務。已知缺證據的拒絕
guard可以PASS，但對應候選依然BLOCKED，必須分開記錄。不能以新窄suite取代
原134項、完整Frontend/Backend suite或80%門檻；受影響既有契約保留並重驗，
新的activeplan拒絕舊execution scope是預期，不可改guard放行。

規劃階段：`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check`；`plan:approved`應因本節Gate4 PENDING回exit1。

Gate4後**擬實作介面，現在不存在／未執行**：

```text
CHG301_R2_ISOLATED=1 <existing-isolated-python> backend/scripts/chg301_r2_node_qualification.py
  --phase preflight|inventory|scan|assess|evidence|cleanup
  --run-manifest <exact-private-manifest>
```

Runner內按allowlist組出registry／archive-only Scout、offline Helm、既有Go/ELF
工具命令；能力不支援回BLOCKED，不直接呼叫會建置／接現行環境的通用harness。
隔離pytest使用`--noconftest -p no:cacheprovider -c /dev/null`與精確新test檔／
artifact manifest，避免import應用／讀.env。Bandit只掃新／改分析工具，
`--ignore-nosec`保留所有severity；High/Critical不自行接受。

## 7. 完成界線與下一個核准點

交付整批盤點、逐項判定、材料清單、真實guard／工具結果及剩餘缺口。
**核准這份計畫只准靜態分析與guard工具／測試，不准修補建置或啟動任何新容器。**
遇到不可判定項可完成其他安全工作後一次提出；需新權限／新依賴／新工具／
執行／延期時則依實際阻擋請Peter決定，不把未知假裝解決。

如同意，可回覆：`核准 CHG-301 R2 節點與基礎映像整批靜態判定計畫`。

## 8. 規劃結果

本輪只有規格／計畫／TEST_PLAN／traceability／進度文件變更；沒有新下載、掃描、
feature test、image build、Docker或Kubernetes操作。治理結果完成後記於進度文件。
評估報告、機器證據及既有runner/test的SHA應保持本輪規劃前一致。

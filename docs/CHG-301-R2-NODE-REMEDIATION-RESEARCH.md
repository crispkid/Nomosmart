# CHG-301 R2：測試節點映像更新／修補評估

2026-09-16 Asia/Taipei。**評估完成；未修補、未放行節點。**

Peter本輪「同意」確認的是先評估方案。執行僅限官方資料研究、既有報告分析及
公開候選的registry-only掃描／SBOM比較，不是新依賴修補或漏洞豁免核准。
規格§10.58 CMPVERIFY-003..006不變；原Traefik精確兩項核准不適用於node。

## 1. 結論

建議以官方 **kind v0.33.0搭配Kubernetes v1.36.4** 作為下一階段靜態分析候選，
不直接改用預設的v1.37.0，也不直接安裝。先完成全構件與告警判定，交付一份
整合修補材料清單，再決定建置範圍。**不是50個已證實可利用漏洞，也不是
NomoSmart新增50個Bug。**

理由：同一Kubernetes minor的新版已減少告警，但仍有50項High/Critical及9項
未分類；單純更新Debian套件無法修補編譯進Go工具的依賴。現階段沒有證據支持
把全部剩餘告警視為誤報，也不宜為了通過測試自行維護整套Kubernetes分支。

## 2. 真實掃描比較

兩次均Docker Scout1.24.0、linux/arm64、全部severity、registry-only；
未Docker pull/load/run，未啟動節點。官方tag前後digest相同。

| 原始掃描分類 | 原候選v1.36.1 | 新候選v1.36.4 |
| --- | ---: | ---: |
| Critical | 18 | 10 |
| High | 57 | 40 |
| 未分類 | 16 | 9 |
| Medium | 59 | 27 |
| Low | 80 | 65 |
| 去重告警合計 | 230 | 151 |
| High/Critical/未分類待判定合計 | 91 | 59 |
| package命中實例（不可與告警數相加） | 313 | 181 |
| SPDX項目（含image） | 530 | 534 |

新掃描時間：2026-09-15T17:46:56Z–17:47:28Z。原掃描為同日17:36–17:37Z。
原91項中32項不再出現在新版的High/Critical/未分類集合，此集合沒有新增ID；
**這是掃描比較，不等於逐项證明32項已修復**。Scanner未提供可獨立核實DB版本，
不能排除資料源更新影響。原始全部報告保留，沒有ignore-base、severity篩除或VEX。

固定候選：

- tag：`docker.io/kindest/node:v1.36.4`
- index：`sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`
- ARM64：`sha256:10210eabcf5dc4b585756bbd3f7fbb60cc0a12a252f28aeba269d93e0070c025`
- 官方依據：[kind v0.33.0發布清單](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0)。
  發布頁開頭仍寫舊default1.36.1，但Breaking Changes／prebuilt清單列1.37.0及
  1.36.4；本次使用明列1.36.4的digest，並經registry核對，不採信相衝突的概述。

## 3. 為什麼不能只做apt upgrade

新版59項待判定告警可分成32項Debian、27項Go依賴（跨生態無重複ID）。
原候選則是48項Debian、43項Go。以下是**掃描的套件群**，不是已核准升級清單。

| 類別 | 涉及套件群 | 建議處理 |
| --- | --- | --- |
| Debian：32項 | glibc、gzip、libevent、libssh2、openssl、pcre2、perl、sqlite3、zlib | 核對官方Debian安全版本、架構、回補patch、套件簽章及必要相依；固定最小材料後才可建置，非全面upgrade。 |
| Go：27項 | containerd/v2、docker/docker、compress、etcd/client/pkg、otel/sdk、x/crypto、x/mod、x/net、x/text、grpc、stdlib | 先對應實際binary和受影響package；優先已修補的官方binary，必要重編需另列來源／工具链／相依及核准，不會被apt更新。 |

Scanner的規則可能合併多個PURL／版本。例如同一ID同時涵蓋Go stdlib與x/net，
不能把規則上的單一fixed_version直接套到每個套件；機器證據保留raw association，
尚未將它當作可執行repair lock。未修補／未知項保持INDETERMINATE，不自動接受。

### 已核對的三個實際位置

- `CVE-2026-53489`命中containerd/v2 **2.2.0** 的位置是
  `/usr/local/bin/containerd-fuse-overlayfs-grpc`；新版另含主containerd **2.3.4**。
  不能看到containerd套件名稱就當作主daemon仍2.2.0。原廠公告涉及CRI checkpoint
  restore，仍須核對snapshotter是否編入／可達該路徑，未宣告不適用。
  [containerd原廠公告](https://github.com/containerd/containerd/security/advisories/GHSA-rgh6-rfwx-v388)
- `CVE-2026-41567`的docker/docker28.5.2位於`/usr/local/bin/crictl`，
  不是已證明此節點運行dockerd。需要精確import／binary證據，不能僅憑名稱排除。
- `CVE-2026-73500`的etcd/client/pkg3.6.8位於`/usr/bin/kubeadm`及`/usr/bin/kubelet`；
  這不是etcd server映像版本證據，不能只替換etcd server就聲稱該命中已解決。

以上位置由raw SARIF取得，不是已完成全部59項的source/binary可利用性分析。

### 掃描以外還須補核對

原廠另有Critical公告 **GHSA-p7v4-vr35-mj6f**：CRI checkpoint restore可能繞過
目的端security context；2.2.7／2.3.4預設關閉該功能，但重新啟用會保留風險。
本次SARIF沒有這個ID；SBOM同時含containerd2.2.0與2.3.4，所以仍須核對
binary import及實際設定。[原廠公告](https://github.com/containerd/containerd/security/advisories/GHSA-p7v4-vr35-mj6f)

此項列為獨立待確認事項，**不竄改上述scanner數字，不直接宣布可利用或不適用**。
不能把「掃描沒有報」等同「已驗證安全」。

## 4. 相容性與隔離風險

- 選v1.36.4而非v1.37.0：原本Cilium1.20.1版本來源的相容矩陣列1.33–1.36，
  維持同minor較能減少同時變動。這是文件相容性，不是已通過本機實測。
  [固定Cilium版本資料](https://raw.githubusercontent.com/cilium/cilium/v1.20.1/Documentation/network/kubernetes/compatibility.rst)
- 若最後採用，kind工具也應使用該release的固定私有副本，不以brew更新全域工具；
  本輪未下載／執行新kind binary。
- kind0.33新增尊重Docker client proxy設定。後續執行設計須使用獨立、無operator
  credential／proxy的設定，顯式限定既有本機Docker端點，不能讀取或沿用私人配置。
  [官方release說明](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0)
- kind Docker節點本身使用privileged及主機相關mount，獨立network並不等於獨立VM；
  共用Docker Desktop核心／容量的風險不變。不能假稱一般nonroot smoke已證明node隔離。
  [固定版本節點建立程式](https://raw.githubusercontent.com/kubernetes-sigs/kind/v0.33.0/pkg/cluster/internal/providers/docker/provision.go)
- 官方base Dockerfile列出containerd、runc、crictl等建置來源，但source預設不是
  產物證明；直接照抄含未固定工具的建置流程也不能宣稱可重現。
  [官方base Dockerfile](https://raw.githubusercontent.com/kubernetes-sigs/kind/v0.33.0/images/base/Dockerfile)
- 外層node的534項SPDX不保證預載控制平面OCI archive內的image都掃過；
  kube-apiserver/controller/scheduler、etcd、DNS、pause及實際啟用的其他映像需
  逐一從固定產物列出digest後檢查，並涵蓋Cilium/operator/Envoy等實際render清單。
  本輪沒有完成這一層盤點，不能稱完整叢集安全檢查通過。

## 5. 下一步建議範圍（待確認，不是修補／執行核准）

為避免逐套件建置後才發現新停點，建議**先一批完成靜態盤點與判定，交付整合清單**：

1. 固定上述v1.36.4 candidate，安全讀取公開OCI／ELF／build metadata及對應原始碼，
   不執行node、套件安裝腳本或新增工具binary。
2. 一次列完59項及補充公告的實際binary、觸發條件、修補版、證據限制；
   分列AFFECTED／PROPOSED_NOT_AFFECTED／INDETERMINATE。未完成者不算PASS。
3. 加入預載控制平面與既定CNI/Ingress映像的完整digest清單和安全檢查，
   先找出整批阻擋；不安裝、不拿Traefik核准套到其他image。
4. 交付**一份固定套件／binary／來源hash的修補方案**，列出新增材料及必要重編
   是否可避免；若需維護Kubernetes fork，明確呈現成本／風險，不能擅自執行。
5. 只有書面範圍核准後才建置；修補後重掃、比較rootfs／設定並補驗收。
   新不適用判定或風險接受仍需精確核准，原完整coverage／Kubernetes／PR gate不變。

上述新增candidate採用、OCI/source分析和跨映像盤點方向尚待Peter確認；
確認後依AGENTS流程寫開發／驗證計畫再取得Gate4，不從本輪「同意評估」推定允許建置。
本輪不變更§10.58產品／驗證規則，TEST_PLAN既有案例及134PASS歷史證據維持原範圍。

## 6. 本輪操作、限制與證據

- 無產品／runner／測試程式變更；只新增研究報告／去敏感機器證據及更新進度引用。
- 既有14個Docker容器ID/status/startedAt/restartCount、networks、image inventory前後相同。
- 零image build/pull/load、零node執行、零Kubernetes操作、零Provider及PR寫入。
  Registry掃描可能使用scanner本機快取，不等同Docker daemon載入image。
- 新候選534SPDX／151raw告警／59待判定；全部59列於
  [機器證據](CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json)。
- Private raw root：`/private/tmp/chg301-r2-node-research-pkn1sbr_`。
  `result.json` SHA256 `b970fae7e895fa10e4ccd16e7f1bfb819657228426f99b1c23c2c3acd7f236d4`；
  SARIF `e8605ed6a1c54b8747628ae69f1fa0cda8bb71be360bc14378bc2b15caacf135`；
  SPDX `9000da32e602edf5bb3d9b779822af55cfa7ee96442f433a3e06822e1c090571`。
- 可重現診斷：`docker --context desktop-linux buildx imagetools inspect`核對tag/index；
  `docker --context desktop-linux scout cves --platform linux/arm64 --format sarif`
  及`scout sbom --platform linux/arm64 --format spdx`，輸入本報告固定index的
  `registry://docker.io/kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`。
  私有result記錄完整參數、exitcode、前後基線及所有raw SHA。
- 原批次deadline `2026-09-15T20:17:52.088462Z`不重置。若後續核准／執行已過期，
  須明確處理時限，不能藉新runID自動延期。
- 本輪只跑文件／治理檢查；不新增產品feature test，134PASS仍是前輪限定結果。
  完整R2、全來源80%、Kubernetes、剩餘image安全與PR更新仍未完成。

本輪治理結果：`spec:doctor`、`spec:trace`（21 mappings）、`plan:doctor`、
`plan:approved`、`test:plan`、`git diff --check`均PASS；JSON數量／狀態斷言、
四份raw SHA256重核及前後Docker基線逐位元比較PASS。
`plan:approved`只辨識原R2既有核准，不是本報告新候選採用／修補建置核准。

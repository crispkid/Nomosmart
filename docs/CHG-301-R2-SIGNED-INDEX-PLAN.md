# CHG-301 R2：官方簽章索引材料補充計畫

2026-09-15。Peter針對「把已驗證官方索引加入建置材料，其餘限制不變」回覆
「同意」，**Gate 2 confirmed；Gate 3 written；Gate 4 approval: APPROVED**。
Peter於2026-09-15明確核准「核准 CHG-301 R2 官方簽章索引補充計畫」。
核准前SHA256：`c0a4b2348abe9fd4b5472b172629629c5e147191fec5f38a81f09e0d7d7cbfab`。
這是[已核准兩函式庫計畫](CHG-301-R2-TWO-LIBRARY-PLAN.md)的有限材料補充，
不是新增套件升級、漏洞豁免、部署或完整R2驗收核准。現可依本計畫執行有限建置。

## 1. 材料清單的唯一變更

原recipe與兩個固定APK之外，增加一份前輪已下載並驗證官方RSA簽章的
`APKINDEX.tar.gz`：

- SHA256：`f0ee7c9c6bb43109521715530f6c1922bd486207ae63e598557ce2900e5a1a49`。
- 官方來源：`https://dl-cdn.alpinelinux.org/alpine/v3.24/main/aarch64/APKINDEX.tar.gz`。
- 使用既存、固定hash的私有證據副本；不下載隨時間改變的新索引。
- 信任金鑰仍取自固定Traefik ARM64原映像；不新增或替換信任根。
- 索引只作離線repository metadata；**其中其他套件不因此獲准安裝**。

可安裝材料仍只有：

| 套件 | 唯一版本變化 | APK SHA256 |
| --- | --- | --- |
| libssl3 | 3.5.7-r0 → 3.5.8-r0 | d6ec970cc10e01539e41626f720c4e0ac69016eaa2079a10ef776ffd3243db5b |
| libcrypto3 | 3.5.7-r0 → 3.5.8-r0 | 35b892813c23664a3592e4fc8c12a03538a22c579057655361c7043305272a9a |

不新增openssl；固定原ARM64 manifest仍為
`sha256:444bb54c1f7ebe5fac94d1c40f02b48c08dc005a92fc65ca29c1c75991d16baa`。
容器registry index digest及其餘原始artifact沿用兩函式庫計畫，不換base。

## 2. 核准後的執行順序

1. current-active approval guard綁定本補充計畫及核准前SHA；舊APPROVED不能代替。
   重驗原始OCI、固定APK/index簽章與內容hash、index對兩APK的Q1 checksum／大小／
   版本／架構綁定、18套件基線、trigger與來源manifest。重核既有builder及容量。
2. 私有allowlist context恰為recipe、兩個APK、一個固定signed index。
   缺檔、多檔、symlink、路徑或hash不符即拒絕；不送repo、.env、備份或其他材料。
3. 既有BuildKit中以`RUN --network=none`、apk自身禁用網路、只指定本機索引且
   不讀系統repositories的方式，先執行明列兩套件的真實solver simulation。
   使用不修改world的fix/upgrade模式；只有兩個指定版本升級才可進入實際套用。
   其他安裝／刪除／升級、需額外APK或無法精確解析變更集即停止。不得改成apk add、
   allow-untrusted、全面升級或先改world再恢復以製造不變結果。
4. 離線套用同一候選及同一材料，沿用有限root build-only例外與必要已檢視腳本。
   不將APK/index留入最終image，不改runtime repository設定。使用支援的單次資源
   限制；不能改builder/VM、增設長駐builder、host network或insecure entitlement。
5. 用靜態方式驗證最終effective rootfs／packageDB／config。18個package名稱集合
   不變，只有兩個版本改變；world、CA、Traefik binary/entrypoint及runtime config
   保持不變。其餘檔案差異只限兩APK實際檔案及明列必要安裝metadata的hash/mode/owner。
   不手改packageDB；未知diff停止。solver simulation本身不算最終差異驗收通過。
6. 同一唯一local-only測試tag完整Scout／SPDX重掃，保留原層及所有severity，
   不使用ignore-base／VEX。執行真實artifact／CLI／新增guard回歸，更新證據。
7. 精確清理本run owned暫存context／資源，保留明列測試image與原始去敏感證據；
   重比原容器、網路、tag基線。不得prune或清理他人資源。

## 3. 改動、測試與停止條件

檔案範圍不變：`backend/scripts/chg301_r2_ingress.py`、
`backend/tests/test_chg301_r2_ingress.py`、
`deploy/test/chg301-r2-traefik/Dockerfile`、治理文件及私有證據。
需求仍為§10.58 CMPPATCH-001..004；既有T01..T09與58PASS歷史證據保留。
新增CMPPATCH-T10驗證固定signed index／context完整清單、第三個APK拒絕、錯誤
index hash／簽章／APK binding拒絕、solver額外變更拒絕、world/config不變及新
active approval必須成立。使用真實來源及失敗process，不fake掃描／solver成功。

仍不執行Traefik version/help或提供服務；OpenPGP INDETERMINATE維持安全阻擋。
不動Kubernetes/Helm/CNI、應用或資料／SQL／indexes／identity、PR、Provider，
不push image或調整host trust/DNS。沒有新增產品API／schema或migration。
原保留4CPU、至少8GiB/20%RAM、100GiB free disk、80GiB增量限制不變；build30m、
scanner20m、同原因最多2次修正重試、原批次6h不重置。原批次起點
`2026-09-15T14:17:52.088462Z`，期限`2026-09-15T20:17:52.088462Z`；
超時／容量不足、簽章／來源／隔離能力不足、未知diff、需額外權限均停止。
整體R2、每端全來源80% coverage及Kubernetes驗收仍未完成，不因函式庫修補免除。

## 4. 規劃驗證與核准

Gate4前只跑`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`與
`git diff --check`；`plan:approved`應拒絕本PENDING補充。Gate4後才實作及建置。
交付兩函式庫版本與逐檔差異、image ID、raw scan／SBOM、真實測試和cleanup結果，
清楚標示未解OpenPGP及整體BLOCKED，不能聲稱安全部署或完整R2通過。

可核准文字：`核准 CHG-301 R2 官方簽章索引補充計畫`。

實作設計釐清（不擴充材料／執行範圍）：APK v2的Q1欄位使用歷史SHA1識別格式，
不能作為安全接受的依據。計算Q1的helper本身必須先驗證完整APK的已核准固定SHA256；
不符合直接拒絕，不能只由呼叫端保證。SHA1計算明示為非安全用途的格式比對，
官方RSA-SHA1舊式簽章仍獨立驗證，相關靜態MEDIUM警示保留，不自動豁免。
原始靜態掃描結果與補強後重掃均保留；不能以標記取代實際SHA256前置檢核。

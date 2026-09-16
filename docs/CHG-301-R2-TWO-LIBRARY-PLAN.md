# CHG-301 R2：兩函式庫最小修補修訂計畫

2026-09-15。Peter回覆「同意」，確認只修補兩個已安裝函式庫，保留OpenPGP
安全阻擋。**Gate 2 confirmed；Gate 3 written；Gate 4 approval: APPROVED**。
Peter approved Gate 4 on 2026-09-15 with「核准 CHG-301 R2 兩函式庫修補修訂計畫」。
核准前SHA256：`44fc07b9db4d568ae972213735b68961420660268112ea484270a8515c386161`。
本文件是對[原已核准修補計畫](CHG-301-R2-TRAEFIK-REMEDIATION-PLAN.md)的
有限範圍更正；其餘來源、風險、隔離、資源及清理限制不變。
原核准紀錄及[58項測試／實物證據](CHG-301-R2-TRAEFIK-REPAIR-VERIFICATION.md)
保留；本次已取得修訂計畫本身的明確核准，不是沿用原三套件核准。

最新材料補充：Peter已同意§6的既有official signed index材料調整（Gate2）。
[索引補充計畫](CHG-301-R2-SIGNED-INDEX-PLAN.md)後續已獲Peter明確核准，Gate4 APPROVED；
本文件原「recipe＋兩APK」及其核准保留作歷史，不代替新材料計畫的核准。

執行結果：[兩函式庫驗證](CHG-301-R2-TWO-LIBRARY-VERIFICATION.md)。94PASS，
10項OpenSSL已移除，2項安全判定仍阻擋；沒有controller／Kubernetes／PR操作。

## 1. 唯一修補差異

只升級Alpine3.24/aarch64的下列**已安裝**函式庫：

| 套件 | 原版本 → 目標版本 | 官方APK SHA256 |
| --- | --- | --- |
| libssl3 | 3.5.7-r0 → 3.5.8-r0 | d6ec970cc10e01539e41626f720c4e0ac69016eaa2079a10ef776ffd3243db5b |
| libcrypto3 | 3.5.7-r0 → 3.5.8-r0 | 35b892813c23664a3592e4fc8c12a03538a22c579057655361c7043305272a9a |

不安裝openssl套件，不新增`/usr/bin/openssl`。原三個已下載APK只保留作歷史
分析資料；build context與安裝清單只允許上述兩個。這取代原計畫§2/4/5/6內
「三套件修補」條件，不代表全面apk upgrade或其他依賴更新。
固定Traefik3.7.13 ARM64 manifest仍為
`sha256:444bb54c1f7ebe5fac94d1c40f02b48c08dc005a92fc65ca29c1c75991d16baa`，
image index仍為`sha256:f86a2cab1b5c649070c49f883c743dd32d8485a56e3368c5f93b9e91f1e91259`。

## 2. 實作及驗證順序

1. 綁定本修訂Gate4／來源SHA及原始證據；approval guard只認當前active計畫，
   不因文件後面留有舊APPROVED段落而放行。重核原容器／網路／tag及容量基線。
2. 修改`backend/scripts/chg301_r2_ingress.py`的repair targets、scope guard及
   build/rescan證據流程。區分歷史artifact清單與可安裝清單。驗證fixed OCI、
   APK簽章、signed index、datahash、18個installed packages和既有trigger。
3. 建立`deploy/test/chg301-r2-traefik/Dockerfile`及私有allowlist context，
   僅含recipe與兩個固定APK；仍以既有BuildKit、offline RUN、明列有限root
   build-only例外套用修補，不執行Traefik、不掛host／Secret／現行volume。
   使用已支援的單次資源限制，不能為此改builder／VM或新建長駐builder。
4. 建立唯一local-only測試tag，再核對effective rootfs、package database及
   原config。**installed package名稱集合／數量保持18，只有兩個版本改變**；
   `/etc/apk/world`、CA信任內容、Traefik binary／entrypoint及其他套件版本保持
   不變。檔案SHA/owner/mode差異只限兩個APK的實際修補檔與明列必要安裝metadata。
   不手改package database；若工具會新增套件／world項目或造成額外差異，停止。
5. 對同一新image完整Scout／SPDX重掃，保留raw severity和lower-layer證據。
   只有實際library與重掃共同證明才標OpenSSL FIXED；不使用ignore-base或豁免。
6. 更新`backend/tests/test_chg301_r2_ingress.py`，保留原28guards及前輪58PASS
   證據；新契約測試不得靠刪除案例、降低門檻或fake外部成功。驗證：兩個既有
   函式庫可進修補流程、第三個APK／新增套件／錯誤版本與簽章拒絕、rootfs／world
   額外變更拒絕、舊核准不能解鎖新範圍、零symbols仍INDETERMINATE。
7. 精確清理本run暫存與資源，保留指定test image及去敏感證據；比較原基線。
   更新治理／測試／traceability／報告，清楚區分library repair與runtime safety。

## 3. 不變的安全停點

OpenPGP `GO-2026-5932`仍是INDETERMINATE、安全gate仍阻擋。
只修兩個函式庫不會改變Traefik binary或其零symbols限制。**此次不跑controller
version/help smoke、不提供服務、不建立Kubernetes叢集**；不得自動VEX／豁免。
Docker CLI仍只是PROPOSED_NOT_AFFECTED，原raw報告不變。新告警、簽章／來源／
能力不足、未知diff或資源不足仍依原計畫停止；不能擴增修補套件或重編controller。

不改Backend/Frontend/Migration產品依賴、API、權限、SQL、chart／Installer預設、
現行Kubernetes／Helm／CNI／Secrets／PVC／資料／indexes／identity；不push image、
更新PR、呼叫Provider、調整host trust／DNS／Docker設定。
沿用保留4CPU、至少8GiB/20%RAM、100GiB free disk、80GiB增量、單build30m、
scanner20m、整批6h、同原因最多2次修正重試；不以改run ID或此修訂重置預算。
原批次及前輪停止／cleanup證據需連結；監測不等於硬隔離或現行服務零影響保證。

## 4. 驗收及交付界線

需求§10.58 CMPPATCH-001..004；測試CMPPATCH-T02/T04/T05/T06/T08及新增T09。
Gate4前只執行`spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`、
`git diff --check`；`plan:approved`預期拒絕當前PENDING。
Gate4後才改runner／recipe／tests並執行隔離建置、rootfs diff及完整重掃。
所有歷史58PASS保持原來源範圍；本輪尚無新feature測試結果。
交付固定image ID、兩library與檔案比較、raw scan/SBOM、真實測試與cleanup證據；
即使library repair通過，整體仍因OpenPGP保持BLOCKED，不宣稱可部署或完成R2。
完整應用每端80%／Kubernetes驗收／PR更新門檻不變。

可核准文字：`核准 CHG-301 R2 兩函式庫修補修訂計畫`。

## 5. 本輪規劃檢查

2026-09-15：`spec:doctor`、`spec:trace`（21個active需求）、`plan:doctor`、
`test:plan`、`git diff --check`通過。`plan:approved`回exit1，明確指出當前
修訂Gate4 PENDING，符合停止條件。runner、tests及前輪machine evidence的SHA
與本輪開始相同；本輪未跑feature tests、下載／build／scan或操作Docker/Kubernetes。

## 6. 核准後的唯讀可行性檢查：離線索引材料待確認

Peter已核准本計畫；本節是執行前發現的限制與討論，不是自行擴充核准範圍。
目前狀態：**BLOCKED_OFFLINE_INDEX_SCOPE**。尚未修改runner/tests或新增recipe，
未建置／重掃／執行controller，沒有Docker或Kubernetes資源操作。

固定原映像使用apk-tools3.0.6。核對該版本官方原碼及文件後：

- `apk add`可以讀本機APK，但會把指定套件加入world；不符合本計畫§2的world不變條件。
- `apk fix --upgrade`保留原world，但以套件名稱查詢repository中的候選，不能把
  APK檔案路徑當作套件輸入。`apk upgrade`亦使用repository候選。
- 本機repository仍需要索引；目前§2明列context只含recipe與兩個APK，沒有授權
  把既有官方signed index放入build context。不能改用allow-untrusted、臨時新增後
  刪除world項目、手改package database，或把索引藏進recipe以繞過材料限制。

證據：[固定app_add.c](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.6/src/app_add.c)、
[app_fix.c](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.6/src/app_fix.c)、
[database.c的apk_db_foreach_matching_name](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.6/src/database.c)、
[repository格式](https://raw.githubusercontent.com/alpinelinux/apk-tools/v3.0.6/doc/apk-repositories.5.scd)。
這是原碼可行性檢查，不是已執行apk或已證明最終image差異符合的測試。

待Peter確認的唯一材料調整：允許context另外帶入**已下載、已驗證官方RSA簽章的
APKINDEX.tar.gz**，SHA256
`f0ee7c9c6bb43109521715530f6c1922bd486207ae63e598557ce2900e5a1a49`。
它是索引而非新增安裝套件；仍只能升級兩個指定函式庫，不允許其他套件安裝或
版本改變。索引不代表授權其中所有候選，安裝差異仍須精確符合18個套件基線。
固定公開來源：Alpine3.24/main/aarch64；沿用前輪私有證據及簽章綁定。
不重新下載新版索引、不增加信任根、不放寬離線條件／OpenPGP安全阻擋，
也不重置原2026-09-15T14:17:52.088462Z開始的6小時批次與既有重試預算。
確認後再更新相應材料契約、執行計畫與guard，未確認前不開始建置。

本次只記錄核准及唯讀發現。runner SHA仍為
`c2f69cbd1a06b422df41571eb0b8da98ea8f55c50dfb7beb456d608fe9056841`，
tests SHA仍為`a0c89e1dc0d9980836b53a429cd23d65c09922bce8993379304d30945f2ecb0d`；
前輪58PASS／機器證據未改寫，不將其視為本修訂的測試成功。

本輪收尾：`spec:doctor`、`spec:trace`（21個active mappings）、`plan:doctor`、
`plan:approved`、`test:plan`及`git diff --check`全數PASS。這些只驗證治理一致性，
不證明建置或安全重掃通過；新的feature測試尚未執行。§10.58 CMPPATCH-002/004
仍受上述材料確認與既有安全停點限制。

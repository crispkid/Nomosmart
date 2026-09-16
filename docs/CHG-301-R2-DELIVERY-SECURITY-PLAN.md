# CHG-301 R2 交付程式與正式安裝依賴安全修訂計畫

2026-09-16 Asia/Taipei。Gate 2 confirmed：Peter先選「2」，再明確要求
「聚焦『交付程式＋正式安裝路徑的依賴』，繼續吧」。Gate 3 written。
**Gate 4 approval: APPROVED。** Peter於2026-09-16明確核准：
「核准 CHG-301 R2 交付程式與正式安裝依賴安全修訂計畫」。
核准前SHA256：f73b28d6a30d4fc7581a91804b89e11f40065dc240b4d2d997a8358e2f43d1f0。
範圍與下列執行限制不變；末段建議核准文字保留為歷史，不是另一道核准。
規格§10.58 CMPDEL-001..004；[唯讀盤點](CHG-301-R2-DELIVERY-SECURITY-INVENTORY.md)。

## 1. 交付目標與界線

一次完成正式交付用途盤點 → 安全檢查 → 範圍內高風險處理/必要回歸 → 條件式原PR更新。
不要求清完未啟用的隔離Kubernetes測試基礎映像；也不把「不交付Image檔」當作
略過正式安裝依賴的理由。原HIGH-PR計畫與結果保持immutable歷史，不延長舊接受。

只延期已確認非正式用途且保持不啟用的kind node/預載、測試Cilium/Traefik。
保留raw嚴重度與未解項；不是修復、NA或風險接受。用途未知及正式路徑相同CVE
仍阻擋。Medium/Low/Unspecified修補、全應用coverage、完整E2E/Kubernetes驗證
延後並揭露；不降低80%設定，不刪舊失敗，不宣稱release-ready。

不修改現行docker-desktop、資料/Secret/索引/角色/SQL/Helm revision，不呼叫
Provider；不新建叢集、不安裝operator、不建立正式Job、不合併PR/發布映像。
不新增native binary產品打包方式；只驗實際交付artifact及現有程式/建置方法。

## 2. 範圍帳列與安全證據

1. 固定Git HEAD/MERGE_HEAD/remote、來源差異及實際交付清單，不讀operator env/
   generated package/備份/credential。保留既有staged與未提交變更，不reset/abort。
2. 以Compose全部受支援profile、Helm安全範例/default/prod/bundled/external及
   installer階段建立manifest。抽出main/init/hook/job/helper/sidecar、FROM與
   package/plugin下載；每筆記用途、啟用條件、來源、版本/platform/digest、維護方。
   只做離線render，不向現行叢集查Secret或採用live values。不用grep命中數當closure。
3. 官方manifest含CNPG/Barman與其sidecar；客戶自管cert-manager/K8s/CNI/CSI/
   Ingress等記外部前提。Compose Nginx/選配debug、不同OpenSearch版本不能誤排。
   僅測試用途明列DEFERRED_TEST_INFRA；若混合用途或資料不足，留IN_SCOPE/UNRESOLVED。
4. 對原始碼/鎖檔跑既有dependency/SAST/Secret與設定檢查；對exact binary/image
   保留完整SBOM/全部severity和掃描資料時間，含OS、原生工具及內嵌runtime。
   舊證據只在source/image/platform/config/hash一致時引用並明列日期；final候選
   要有完整安全結果，不能以source audit或base scan取代衍生映像。
5. 優先沿用來源可證的現有候選；缺exact final artifact時只以現有Dockerfile/
   鎖檔建立唯一local candidate，不覆蓋原tag、不push registry。下載僅限公開官方
   材料/已驗證工具，驗證hash/簽章，候選套件metadata可查詢；不傳完整原始碼、
   映像、文件或Secret，不買scanner額度、不關TLS、不執行遠端install script。

## 3. 可連續進行與必須停下的修正

- 先完整收集正式用途High/Critical，按共同來源與受影響artifact整理，不每個CVE
  建一套工具。未確定適用性仍為未解；新NA僅提案，需精確確認，不自動VEX/suppress。
- 本次可修本次驗證帳列/測試契約、Secret/helper/安裝器既有CHG-301契約中的問題；
  規格已定義的範圍內採最小改動，保持API/權限/SQL、啟動依賴與fail-closed不變。
- 發現需升級產品runtime相依、第三方base、Flyway/Java/Node/Python/DB/operator，
  或需要跨版本/授權/功能/資料遷移時，**先集中列確切修正建議與必要回歸，停止該
  修補路徑**。本次不是任意版本升級授權；可以繼續其餘已核准檢查後一次回報。
- 範圍已排除的測試infra不再修補或重掃，不把它們的未解High當本次PR阻擋；
  但不可在本run使用它們作測試/建置執行環境，也不沿用它們的舊scope繞過檢查。
- 不建立新通用安全框架；優先沿用既有source/image/scan工具，只補最小用途帳列
  與PR檢查。若需改guard，新增正式/測試混用與缺證據拒絕測試，不移除原保護。

## 4. 必要回歸、資源與清理

- 保留原247項案例與歷史結果；新active scope按真實歷史/目前核准區分，不以改
  文件或偽造外部成功讓舊執行guard放行。分類/證據pure-policy測試不是服務PASS。
- 未改source可重驗hash後引用既有真實CLI/Compose證據；任何helper/Secret/CMD/
  安裝器變更都需真實CHG-301 package/entrypoint窄回歸。不能以掛新helper冒充
  final image。需要超出本計畫的完整stack/付費模型時標BLOCKED並討論。
- 不以漏洞掃描PASS取代功能測試。必要isolated CLI使用nonroot/read-only/
  cap-drop ALL/no-new-privileges/network-none、無host data/Secret/socket/port。
  不執行尚未過安全門檻的候選server/daemon；公開下載僅供材料/metadata/建置。
- 新Gate4後開獨立run，6h wall-clock、截止前10min停止接新工作，不重設舊run。
  一次最多1build或1scan；command20min/build30min、同原因最多2次retry。
  run≤40GiB、歷史測試artifact合計≤80GiB、磁碟free≥100GiB；不得prune舊證據。
- 區分host靜態掃描與Docker VM建置/CLI。host檢查實際host餘裕；VM作業須驗證
  VM可用資源且enforce最多4CPU/8GiB，保留4CPU/8GiB及20%RAM餘裕。無法核實
  就不啟動該重作業；Metrics API缺少不自動代表host靜態掃描不可做，也不宣稱
  VM餘裕已知。不安裝metrics-server、不調VM或停止服務來達標。
- 新資源使用唯一run labels/exact IDs與0700目錄，建立前後比對現有非敏感基線。
  可清本run登記所有物，先dry-run清單再exact cleanup；禁止廣泛down-v/prune。
  基線漂移/权限拒絕/容量不足停止相關操作，不使用替代管道繞過限制。

## 5. PR更新條件

納入用途帳列完整、High/Critical已修復或有exact有效接受、必要同來源回歸及cleanup
通過才更新 https://github.com/crispkid/Nomosmart/pull/1。正式用途unknown、缺binary/
final scan/必要回歸、新安全修補待核准都不能略過。中低風險與純測試infra明列延期。

重新核對PR OPEN、分支fix/compose-method1-installer、base main及remote SHA。
允許完成既有main整合commit與本次核准修正commit；逐檔review/stage，不git add .，
不force/main push、不reset/abort/cherry-pick丟使用者修改。未知merge/無關變更/
他人更新就停。提交前核對Secret/私人資料/大檔、CI不會自動部署；不可分離的部署
觸發流程不得靠改保護規則繞過。一般push原分支，保留PR原文/討論並補充本輪說明。

最後重讀remote SHA與PR說明；CI沒有結果或失敗照實回報。不合併、不approve自己、
不auto-merge、不Release/registry push/部署。PR可review不等於完整驗收或發布就緒。

## 6. 檔案、測試與核准

| 檔案 | 用途 |
| --- | --- |
| docs/CHG-301-R2-DELIVERY-SECURITY-* | 安裝用途帳列、exact artifact/hash、完整/延期/缺口結果 |
| backend/scripts/chg301_r2_high_risk.py 或最小用途補充工具 | 保留舊結果；按artifact用途判斷PR門檻，不全域略過CVE |
| backend/tests/test_chg301_r2_high_risk.py及必要matching tests | 用途重疊/未明/缺scan拒絕、歷史核准與目前拒絕、同來源回歸 |
| 本次CHG-301 package/helper/installer範圍 | 只有已定義契約的必要修正；若有則先追蹤再真實回歸 |
| SPECIFICATION / SPEC_CHANGELOG / DEVELOPMENT_PLAN / TEST_PLAN / TRACEABILITY | CMPDEL-001..004、Gate與結果，保留舊報告不改寫PASS |

驗證命令：spec:doctor、spec:trace、plan:doctor、plan:approved、test:plan、
backend:syntax、helm:lint、deploy:config-policy、git diff --check；Compose只用
`COMPOSE_DISABLE_ENV_FILE=1`與harness的`--no-env-resolution --quiet`安全路徑。
source/image檢查使用已核對工具版本、raw Scout/SBOM、Bandit --ignore-nosec、
dependency audit；pytest只執行本次必要真實artifact/CLI案例，不接現行conftest服務。
新增CMPDEL-T01..T08詳TEST_PLAN。本輪文件檢查不算實作或安全驗收。

建議核准文字：**核准 CHG-301 R2 交付程式與正式安裝依賴安全修訂計畫**。
核准後可依此連續檢查、必要契約修正/回歸及條件式PR更新；不再逐個套件問同一
檢查權限。產品相依升級、新安全豁免或超出界線工作仍集中討論。

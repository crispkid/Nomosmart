# CHG-301 R2 交付程式與正式安裝依賴：本輪結果

2026-09-17 Asia/Taipei；核准日期2026-09-16。
規格§10.58 CMPDEL-001..004；[核准計畫](CHG-301-R2-DELIVERY-SECURITY-PLAN.md)；
[機器可讀證據](CHG-301-R2-DELIVERY-SECURITY-EVIDENCE.json)。

## 結論

**部分完成，PR仍未更新；不是發布或部署通過。**

- 16個ARM64候選映像完成全嚴重度掃描及SPDX SBOM；既有Backend、Frontend
  候選沒有High/Critical，但仍不能冒充目前完整交付原始碼的最終映像。
- 14個正式用途依賴候選仍有高風險告警，主要在第三方元件、OS與內嵌runtime。
  需要產品相依升級或精確適用性確認；本輪不具任意升版或新豁免授權。
- 原247案例全部保留，加上歷史核准拒絕及交付範圍/真實報告檢查，共272 PASS。
  這不是全應用coverage、Kubernetes、完整E2E或新版本功能驗收。
- 既有14個Docker容器的狀態/啟動時間/重啟次數、映像與network清單前後一致。
  未建置、未啟動候選、未部署、未改資料、未呼叫Provider、未寫PR。

## 已做的用途盤點

49筆來源宣告；Compose全部profile成功執行安全config驗證。
離線渲染default Chart，以及3份已提交installer範例的foundation/application/
operational階段與2個bundled finalize，共12份render、144個映像使用位置。
包括main/init、bootstrap/migration/finalize Job、CNPG operand。
external-services foundation沒有映像，是實際render結果，不是省略失敗。

兩份公開CloudNativePG/Barman manifest下載後均符合原始SHA與installer固定映像後
SHA。Barman Base64編碼的SIDECAR_IMAGE也經實際解析核對；operator及sidecar
沒有被誤當成客戶自管Kubernetes本體而排除。未執行apply或operator。

純測試kind/node/預載、Cilium、Traefik維持DEFERRED_TEST_INFRA，不重掃或啟用。
已知測試映像ID不在既有14個Docker容器中。本輪正式依賴和舊測試帳列共有38個
High/Critical advisory ID；這38個在正式用途中仍保留未解，**沒有全域排除CVE**。
客戶自管Kubernetes/CNI/CSI/Ingress/cert-manager等維持外部前提，未宣稱已驗證。

## 映像掃描結果

工具Docker Scout1.24.0；固定local image ID或registry ARM64 child digest。
所有16份SBOM的container purl均對上掃描目標；保留全部嚴重度、原始SARIF與SBOM。
Scout未提供可固定的漏洞資料庫revision，保留每條命令及SBOM時間，不稱完全可重現的資料庫。

| 候選元件 | High | Critical | 判讀 |
| --- | ---: | ---: | --- |
| Frontend chg299-v049 | 0 | 0 | 既有候選；目前source/final交付綁定未完成 |
| Backend chg300 | 0 | 0 | 既有候選；不能替代CHG-301新helper的final image |
| Migration chg301-test | 23 | 3 | Alpine、Jackson、Netty等 |
| PostgreSQL standalone chg301-test | 40 | 6 | OS與內附工具相依 |
| RustFS chg301-test | 14 | 4 | 本次raw high來自curl與OpenSSL |
| Keycloak26.0.8 | 61 | 4 | Keycloak、Java相依及OS |
| OpenSearch Compose2.19.1 | 155 | 2 | 舊Compose分支，不能借用Helm結果 |
| OpenSearch Helm2.19.6-s3本機候選 | 51 | 2 | 並非prod範例private-registry digest已驗證 |
| Nginx1.27.5-alpine | 43 | 12 | 正式Compose入口 |
| Redis7.4.2-alpine | 66 | 7 | 多數raw來自內附Go工具及OS，不等於Redis engine已完整掃描 |
| Neo4j5.26.4-community | 24 | 1 | Java相依與OS |
| socat1.8.0.1 | 11 | 1 | 正式debug profile仍屬交付用途 |
| CNPG PostgreSQL18.4 | 15 | 6 | Debian與內附相依 |
| CNPG operator1.30.0 | 8 | 1 | Go1.26.4與gRPC1.81.1 |
| Barman plugin0.13.0 | 14 | 1 | plugin內嵌相依 |
| Barman sidecar0.13.0 | 14 | 1 | 與plugin分開掃描 |

合計539 High＋51 Critical＝590筆「映像×advisory ID」，跨映像去重325個
CVE/GHSA ID。這不是590個互不相同漏洞，也**不是590個已證實可遠端利用的缺陷**。
同一advisory的不同package/位置保留於raw reports。另有587 Medium、147 Low、
38 Unspecified，依核准範圍不修補，但未刪除或改成PASS。

## 原始碼與安全檢查

- 新鮮本機Bandit：LOW90/MEDIUM32/HIGH3；3項精確對上既有
  `CHG301-R2-FTP-20260915`接受及source hash，沒有新增未核准High。
  這只保留原本有限的接受，不擴充為正式環境或其他映像的豁免。
- 本轮新增runner：Bandit HIGH0/MEDIUM0/LOW2，無分析錯誤，未用nosec消音。
- 既有release `source_hygiene`檢查732個已追蹤檔案通過。未追蹤/ignored檔案與
  尚未產生的發佈包不在此結果內；這不是全面Secrets偵測保證。
- npm/PyPI新鮮線上稽核：**BLOCKED_PERMISSION**。權限審查要求明確同意將公開
  相依名稱/版本送至registry.npmjs.org及pypi.org。沒有改管道重試或外傳原始碼。
- 安全的替代檢查：重核舊稽核140檔hash全部相同，保留2026-09-15
  11:45:50UTC的npm production/full與pip production/full零告警歷史結果。
  pip分別54/60個依賴；明確不是今天更新漏洞資料庫的結果。

## 必要測試與程序檢查

272 passed，0failed/0error/0skip，13.91秒；四個測試檔：
`test_chg301_r2_ingress.py`、`test_chg301_r2_node_qualification.py`、
`test_chg301_r2_high_risk.py`、`test_chg301_r2_delivery.py`。
原high-risk runner仍拒絕以新delivery計畫重新執行；測試改為區分真實歷史核准
與目前active scope，沒有放寬舊guard。

通過backend:syntax、helm:lint、deploy:config-policy、Compose全profile安全config。
最終spec:doctor、spec:trace（34 mappings）、plan:doctor、plan:approved、test:plan
及git diff --check全部通過。測試沒有連現行DB或虛構外部服務成功。
第一輪本機Bandit因sandbox禁止ps而中止；保留失敗記錄，經正常權限申請執行
純本機分析後通過。線上稽核的外傳拒絕是另一項仍未解的限制。

## 待討論的修正方向（尚非升級計畫或升級核准）

不建議逐個CVE亂換jar/library，而是按相依來源分組：

1. **正式服務版本**：Redis優先評估同7.4分支的7.4.11；Nginx評估stable1.30.5；
   Keycloak評估26.7.3；Neo4j維持5.26維護分支。先驗TLS、Secret啟動、ACL/
   Sentinel、OIDC/LDAP/group、graph CRUD與資料相容性，不直接升現行部署。
   Redis的[官方7.4安全修正](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisce-7.4-release-notes/)
   也補足本次scanner主要只報gosu/OS的限制；
   [Nginx公告](https://nginx.org/en/security_advisories.html)、
   [Keycloak26.7.3](https://www.keycloak.org/2026/08/keycloak-2673-released)、
   [Neo4j維護紀錄](https://github.com/neo4j/neo4j/wiki/Neo4j-5.26-changelog)
   支持版本評估方向，**未掃候選不可承諾零高風險**。
2. **OS與打包相依**：優先保留PostgreSQL18、RustFS既有產品線，修相容OS patch；
   RustFS raw修復界線為curl8.22.0-r0、OpenSSL3.5.8-r0（scanner建議，仍須供應商
   材料驗證）。Migration須一併看Flyway/JRE/內附driver；
   [Flyway13.7.0](https://documentation.red-gate.com/fd/release-notes-for-flyway-engine-179732572.html)
   已發布，但release notes不等於全部告警已修，MSSQL版本suffix等也需精確判定。
3. **搜尋與operator**：OpenSearch2.19.6本機候選仍有53筆High/Critical，不能只把
   Compose2.19.1升成2.19.6便宣稱完成；保留repository-s3、search/TLS/ACL契約。
   [官方2.19.6維護狀態](https://opensearch.org/releases/)仍需搭配實物掃描。
   CNPG/Barman需處理內嵌Go/gRPC；[Barman0.14.0](https://github.com/cloudnative-pg/plugin-barman-cloud/releases/tag/v0.14.0)
   是可評估候選，但其更新紀錄不能證明覆蓋全部新告警。官方沒有滿足條件的
   artifact時，再討論供應商修補、精確適用性或有界重建，不自行大改operator。

以上方向會影響Dockerfile/Compose/Helm/installer固定digest及必要回歸，需集中
確認後依Gate流程寫修訂實作計畫；本輪沒有偷偷升版或新增風險接受。

## 尚缺證據與PR阻擋

1. 正式依賴590筆raw High/Critical尚未完成修補或精確有效判定。
2. 七個本機候選尚未完整綁定目前交付原始碼；prod範例私有OpenSearch digest
   未取得，沒有借本機tag掃描結果代替。範例placeholder不是實際release artifact。
3. Builder完整物料、其他平台與最終source-bound release候選仍未完成；本輪
   331檔來源快照及12份離線render不是完整可發佈閉包證明。
4. 新鲜線上npm/PyPI稽核外傳需另行明確同意。僅送公開套件名稱/版本到上述
   公開服務；不含原始碼、.env、Secret或私有套件；工具下載走公開官方registry。
5. 全coverage/Kubernetes/E2E與未啟用測試infra維持延期，80%門檻未調低。

本輪不需要清理容器/volume/network，因為沒有建立。raw report留於0700私有run：
`/private/tmp/chg301-r2-delivery-c0j_1wn6`。run最晚截止2026-09-16T21:44:36Z，
不重設；最後記錄歴史測試artifact約3.97GiB，未超80GiB。無VM建置/CLI runtime，
沒有用VM總RAM冒充可用RAM。Git既有merge/staged工作保持原狀，沒有commit/push。

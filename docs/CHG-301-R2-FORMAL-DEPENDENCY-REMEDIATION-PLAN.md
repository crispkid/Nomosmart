# CHG-301 R2 正式安裝依賴修補實作計畫

2026-09-17 Asia/Taipei。Gate 2：Peter「同意」三組修正方向及公開依賴稽核。
Gate 3 written。**Gate 4 approval: APPROVED。** Peter於2026-09-17明確核准
「核准 CHG-301 R2 正式安裝依賴修補實作計畫」。核准前SHA256：
`88548aaf15a24b7b3aac1f549b999f88ab8616c3c4d54de2847cb2c7558de8a4`。
以下版本、資源、安全與停止邊界不變；末段核准文字保留為歷史，不是另一道核准。
規格 §10.58 `CMPUPG-001..004`；延續 `CMPDEL-001..004` 的用途範圍。

## 1. 目標與現況

只修「交付程式＋正式安裝路徑」的 High/Critical，完成必要回歸後才更新原 PR。
不再擴修未啟用的 kind/Cilium/Traefik，不改目前 docker-desktop 部署或資料。
本輪可修改 repository 的安裝版本宣告，與實際套用現有部署是兩件事。

[前次結果](CHG-301-R2-DELIVERY-SECURITY-RESULT.md)：16 個 ARM64 候選中，
14 個有 539 High / 51 Critical image-advisory rows（跨映像 325 個 ID），
不是 590 個不同漏洞或全部可利用。[本次公開依賴稽核](CHG-301-R2-PUBLIC-DEPENDENCY-AUDIT-RESULT.md)
的 npm production/full、pip 54/60 依賴都零告警；Bandit 仍是 3 個既有 FTP 接受。
所以不為了修映像 OS/Java/Go 告警而盲目更動乾淨的 npm/Python 鎖檔。
七個 local 候選尚未完整綁定目前來源，不能用既有 0 High 結果替代 final artifact。

## 2. 一次核准的三組範圍

以下是**優先評估候選，不是已驗證安全版本**。Gate 4 後先解析官方精確
platform/digest、簽章或可信 checksum、完整 SBOM/High/Critical，再決定採用；
每一列記原值、新值、材料來源、相容性與安全差異，不追逐無關最新功能。

| 組別／元件 | 允許的候選邊界 | 必須保留／驗證 |
| --- | --- | --- |
| A Redis | 7.4.2 → 7.4.11；不升 8.x | ACL、Secret、TLS、Sentinel、Celery 使用契約；內附 Go helper/OS 也需處理 |
| A Nginx | 1.27.5 → stable 1.30.5 | edge template、TLS、/identity 與 API 代理路徑、headers、非公開內部端口 |
| A Keycloak | 26.0.8 → 26.7.3 | 現有 theme/helper、OIDC/JWT、LDAP/group、最小權限；不得擴大 hostname/TLS 信任 |
| A Neo4j | 5.26.4 → 5.26 維護 patch，優先查 5.26.30 | Community 授權、Bolt/auth、既有圖譜查寫契約；不升新版產品線 |
| B PostgreSQL standalone / CNPG operand | 保持 18.x（目前 18.4），優先同版本官方更新 digest／同 OS 安全 patch | 兩種 image 分列；driver、非 root/Secret、初始化與資料目錄；不做 major upgrade |
| B RustFS | 保留 1.0.0-beta.10，修相容 OS 套件 | S3/TLS、secret entrypoint、非 root、health；不因掃描改用未核准 preview |
| B Migration | Flyway 13.6 → 優先評估官方 13.7.0 同系列 | SQL V001–V049 bytes/checksum 不變；Java/JDBC/OS 全部掃；validate/migrate/失敗拒絕 |
| B socat debug profile | 保留現有用途，官方同 1.8 系列維護／OS patch | 仍預設關閉；不能把正式交付的選配工具冒充純測試而排除 |
| C OpenSearch | Compose 2.19.1 → 評估 2.19.6；Helm 保持 2.19 系列與 repository-s3 | 兩路各驗 TLS、ACL、索引 mapping、BM25/vector、snapshot plugin；不升 3.x |
| C CNPG operator | 1.30 系列官方安全更新；沒有合格更新就保留未解 | 完整 manifest、CRD/RBAC、image digest、installer hash/fail-closed 不得弱化 |
| C Barman plugin＋sidecar | 0.13 → 評估官方 0.14.0，兩個 image 各自固定與掃描 | manifest/hash、Base64 sidecar、CNPG 相容性、cert-manager 前提、backup contract |

Frontend、Backend/Worker/Beat/bootstrap/readiness 不新增功能或無必要升依賴；
仍須用同一 final source 建立候選、檢查 runtime/build inputs 並完成 CHG-301 helper
必要回歸。它們不能因前次 local image 零 High 就從交付範圍消失。

### 官方研究與不確定性

2026-09-17 查詢以下第一手來源；不是 candidate image 已下載或已掃：

- [Redis 7.4 release notes](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisce-7.4-release-notes/)列 7.4.11 安全更新；engine 公告補足 scanner 的 OS/helper 偏重。
- [Nginx 安全公告](https://nginx.org/en/security_advisories.html)列 1.30.5 修正界線；仍須逐 module 判定，不把所有模組漏洞當已啟用。
- [Keycloak 26.7.3](https://www.keycloak.org/2026/08/keycloak-2673-released)列官方修正；版本改變可能帶來其自有 DB migration，僅能在隔離測試資料上驗證。
- [Neo4j 5.26 changelog](https://github.com/neo4j/neo4j/wiki/Neo4j-5.26-changelog)已列 5.26.30 的依賴安全更新；registry 實際可取得的 Community platform digest 尚待確認。
- [Flyway 13.7.0 release notes](https://documentation.red-gate.com/fd/release-notes-for-flyway-engine-179732572.html)不是全部 Jackson/Netty/JDBC 告警已修證明；版本 suffix 誤比對亦不可未驗即 NA。
- [OpenSearch 維護政策](https://opensearch.org/releases/)列 2.19.6；目前該 local image 仍有 53 筆 High/Critical，不能只改版本字串便結案。
- [CNPG releases](https://cloudnative-pg.io/releases/)可核實 1.30.0；不捏造新版 tag。
- [Barman 0.14.0](https://github.com/cloudnative-pg/plugin-barman-cloud/releases/tag/v0.14.0)列 gRPC 1.82.1，並不能保證滿足既有掃描的較新修復界線。

## 3. 修補方法與停止條件

1. **來源基線**：保留 merge 中 HEAD/MERGE_HEAD、既有 staged/未提交修改；核對
   舊 evidence 和新 source allowlist。帳列含 Compose 全 profiles、12 類既有 Helm
   render、installer CNPG/Barman、main/init/hooks/sidecar 及全部 Dockerfile stage。
2. **正式材料優先**：先官方相容 patch/image；無完整官方 image 修補時，允許現有
   自有 Dockerfile 對原 OS release 的已安裝套件做可追溯 security update，記 solver
   相依閉包，固定 base/platform 與套件版本/checksum。不得跨 distro、加未知套件、
   降版、改成 root、繞簽章或 TLS。不得修改第三方內附 jar 或自行 fork/rebuild operator。
3. **來源與設定同步**：通過候選證據後，同步 Dockerfile、Compose、Helm、安全
   env/example、installer 固定 hash 与相關 contract tests/docs，保留使用者 override。
   已有 private-registry example digest 不可冒充本機 scan；明列 operator 提供 artifact
   的驗證責任，不改為假的已驗 digest。實際交付清單/平台缺證據仍為未完成。
4. **精確判定**：每筆 raw finding 保留 image+package+path+ID，區分 FIXED、既有
   exact valid ACCEPTED、DEFERRED_NONHIGH、UNRESOLVED。重複 CVE 不能跨用途
   消音；未確定適用性不算低風險。新 NA/風險接受只提出證據，需人類另行核准。
5. **分組前進**：某組找不到合格官方材料，停止該組 build/runtime，其他已核准且
   無關聯的工作可完成；最後一次彙整阻擋，不逐個 CVE 要重複確認。

以下情形必須停相關工作並討論：超出表列版本系列/新功能或授權、原生 binary 新
打包形式、需 fork/任意 jar substitution、正式資料遷移、改身份/權限契約、新豁免、
目前環境或遠端分支漂移、權限拒絕、必要真實測試需另建 Kubernetes。不得自動
延長過期接受、藉同名 tag 套舊結果或為通過而排除正式安裝功能。

## 4. 有界執行與不變項

- 新 Gate 4 後開新 run，不重設任何舊 run：6h、最後 10min 不接新工作；
  每 command≤20min、build≤30min，同原因最多 2 次重試，一次一個 build/scan。
- host 靜態 audit 和 Docker VM 分開檢查；VM 作業合計 cap 4CPU/8GiB，須
  核實至少餘留 4CPU/8GiB 及 20% RAM；不以 host/free total 冒充 VM available。
  run≤40GiB、全部歷史測試 artifact≤80GiB、free disk≥100GiB。不能核實就不跑重作業。
- 只建立唯一 run-owned local image/container/network/volume，記 exact IDs、labels
  及 0700 artifact。不覆蓋既有 tag、不 push registry、不掛 Docker socket、不用
  privileged/host network、不掛目前資料。僅必要公開官方材料下載與已同意的公開
  npm/PyPI metadata audit，不傳 code、document、Secret 或 private packages。
- 候選先通過安全門檻，再執行非 root、drop capabilities、no-new-privileges 的
  network-none CLI；需要真實服務的必要回歸只用獨立 internal network/拋棄式資料，
  不呼叫 Provider、不使用正式帳密、預設不 publish port。服務需較高權限時先討論。
- 現行 docker-desktop Kubernetes、14 個既有 Docker 容器、資料、PVC/Secret、
  索引、身分/角色/manifest、Helm revision 都不動；不安裝 operator/建立 K8s Job。
  不建測試叢集或啟用 deferred 測試 infra；也不因缺測試而說通過。
- cleanup 先列 exact run-owned IDs 再刪本輪拋棄式資源；不 prune/down-v/reset。
  保存 reports/失敗記錄。正式回退/部署與持久資料更新另案核准；本計畫沒有授權。

## 5. 檔案與必要回歸

| 檔案／範圍 | 改動與真實證據 |
| --- | --- |
| deploy/{migrations,postgresql,rustfs,keycloak,opensearch}/Dockerfile | 候選 base/patch pins；每個 stage/final SBOM、hash、全部嚴重度；CLI/Secret helper smoke |
| docker-compose.yml、deploy/docker/nomosmart.env.example | 正式預設版本一致、override 保留；安全 config、profile/entrypoint/缺 Secret 拒絕 |
| deploy/helm/nomosmart/values*.yaml、必要 values.schema.json | 相容 image declarations、render/pin tests；不改 API、拓樸或現行 release |
| deploy/installer/nomosmart_installer/{cloudnativepg,barman_cloud}.py、安全 installer examples | 官方 artifact/hash/sidecar 同步；完整 manifest/CRD/RBAC contract；不能以離線 render 冒充 reconcile |
| frontend/Dockerfile、backend/Dockerfile | 原則不升產品依賴；必要 final source-bound build 與既有 helper runtime 驗證 |
| backend/tests/test_chg301_*、test_chg231_deployment_initialization.py、test_chg242_secret_packaging.py；installer/release tests | 保留原測試；只修與核准版本/契約相關的期待值，新增真實材料/執行結果斷言 |
| 既有 chg301_r2_* 工具＋最小修補補充 | 保留歷史 scope 拒絕；新核准只授權新 run，不繞過舊 deadline/guard |
| deploy/README.md、docs/CHG-301-R2-FORMAL-DEPENDENCY-*、五份治理文件 | 舊/新版本、requirements/tests/evidence、未解項、相容與回退風險 |

測試必須使用真實隔離服務，不得用 fake Provider、mock registry 或硬編 success。
保留 272 個 artifact/policy cases；歷史與 current scope 的預期拒絕分開，不能刪失敗。
新增 `CMPUPG-T01..T08` 詳 TEST_PLAN：供應鏈帳列、scope、同來源 final scan、
版本宣告一致、Secret/CLI、DB/identity/search 真實必要回歸、operator 限制、PR 門檻。

需要的 live checks：拋棄式 PostgreSQL 上 Flyway V001–V049 validate/migrate 及
重跑/故意失敗拒絕（不改 SQL）；Redis auth/ACL/基本 queue/Sentinel；RustFS S3/TLS；
Neo4j auth/現有 graph roundtrip；Nginx 真實 upstream/TLS 路由；Keycloak disposable
DB/realm 的 OIDC、LDAP/群組契約。每組只啟動其最少依賴並依資源 cap 排程。
OpenSearch 若採用新候選，另需真實 tiny index 的 text/vector/ACL/snapshot 驗證，
embedding 用已有測試向量檢驗 search contract，不冒稱模型能力或呼叫模型。
CNPG/Barman 不做實際 operator upgrade/reconcile；若版本差異必須靠 K8s 才能
證明必要契約，就列阻擋並提出後續範圍，不將全 K8s 延期拿來掩蓋該必要回歸。

命令：`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:doctor`、
`plan:approved`、`test:plan`、`backend:syntax`、`helm:lint`、`deploy:config-policy`；
Compose 只用 `COMPOSE_DISABLE_ENV_FILE=1` 的 `--no-env-resolution --quiet` 路徑。
source audit 沿用既有工具；Scout 全 severity + SPDX；pytest 使用獨立設定，
不得載入會連現行服務的 conftest。執行前記 exact test commands、候選和來源 hash。
frontend/backend 全應用 80% coverage、完整 E2E/K8s 保持延期、門檻不降低。

## 6. 完成／PR 門檻

每組報告已修數／未解數、實際新 digest/版本、scan 和必要測試結果；未通過不稱完成。
正式交付與 builder/平台/最終來源帳列完整、High/Critical 修復或有精確有效接受、
必要回歸/清理通過，才沿原核准條件更新
[PR #1](https://github.com/crispkid/Nomosmart/pull/1)。任一缺口仍阻擋寫入。
不把掃描通過說成「沒有其他 Bug」或發布驗收通過。

PR 前重讀 remote/head/main/merge/CI：只原 `fix/compose-method1-installer` 分支，
逐檔審查與 stage，保留既有 merge 工作、確認 Secrets/大檔/私人資訊及無自動部署。
僅一般 commit/push 與補充原 PR 說明；不 force/main push、merge、發布、deploy。
遠端改動/未知本地變更/不可分離部署觸發先停。不滿足條件則交付結果與一次性
剩餘決策清單。非高風險、純測試 infra、完整 coverage/K8s 延期明列，不藏進 PASS。

建議核准文字：**核准 CHG-301 R2 正式安裝依賴修補實作計畫**。
核准涵蓋上述相依修改、有限隔離 build/scan/必要回歸和條件式原 PR 更新；
不涵蓋目前環境部署、新風險豁免或超出此版本/資源範圍的工作。

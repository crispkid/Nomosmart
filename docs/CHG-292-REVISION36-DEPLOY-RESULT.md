# CHG-292 revision 36 部署結果

日期：2026-09-09（Asia/Taipei）。規格：10.49，GRAPH-009..013；產品規格未變更。

## 結果

`docker-desktop / nomosmart / nomosmart-local` 已從 revision 35 成功升級至
**revision 36 / deployed**。Helm 寫入開始於 23:10:51；沒有失敗回退或手動重跑。
部署及本地運行／保護基線驗收通過；登入後現有資料圖譜 API/UI 唯讀驗收
已於 2026-09-10 完成，正式發布等完整功能驗收仍不在此次範圍。

Peter 的核准綁定 `CHG-292-REVISION36-DEPLOY-SCOPE.md`，SHA-256：
`1b849edbdabc1aeac3cd7f7f16c60bdd0a7ab3274d4e6fa84cb065843981219f`。
範圍文件未改寫。實際核准紀錄在 `DEVELOPMENT_PLAN.md`。

## 實際部署

| 項目 | 映像／狀態 |
| --- | --- |
| Backend、Worker、Beat main/init、Frontend readiness init、bootstrap | `nomosmart/backend:0.1.0-chg292` |
| Frontend main | `nomosmart/frontend:0.1.0-chg292` |
| Migration | 保留 `nomosmart/migrations:0.1.0-chg288` |
| migration-36 | Complete；23:10:52–23:10:56，1 Pod、0 restart、無失敗 Pod |
| bootstrap-36 | Complete；23:10:52–23:11:01，1 Pod、0 restart、無失敗 Pod |
| 資料庫 | 結構 V047；Flyway 001–048 驗證通過，無新增 migration，未套用 V049 |

實際容器 image IDs 與核准一致（含各 init container）：

- Backend：`sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1`
- Frontend：`sha256:82df26d3807ebc3904826135ae61f10aaf3a6a2a6a5464d2d822638a7935bbd9`
- Migration：`sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab`

寫入前兩次 hidden-Secret server dry-run 均得到 96,181 bytes canonical render：
`fad6bb97fcaeadbccfd90d8b32a3a4a41e578be2ba37a776be7a78f278b32b67`。
部署後 Helm values/manifest 與原 revision 35 比較，差異只有核准的映像、
release annotations、ConfigMap release ID 及兩個 Job 名稱。

```bash
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg292 \
  --set-string image.frontend.tag=0.1.0-chg292 \
  --rollback-on-failure --wait --wait-for-jobs --timeout 15m
```

## 寫入前檢查

revision 35、source HEAD、映像、render、59-table digest、Secret、PVC/PV、
Ingress、NetworkPolicy、supporting workloads 和圖譜／索引均符合固定核准基線。
沒有 queued/running 業務工作、待處理 outbox、broker 工作或即將到期的業務排程。
身分來源與 PostgreSQL 的預期業務差異為零。

使用既有、已配置的 bootstrap 服務設定，只執行 GET/HEAD/Neo4j read：
OpenSearch role/user/mapping 與 ensure payload 相同；runtime 帳密可用；
Neo4j Community runtime user 已存在且可用；S3 bucket 已存在。
Keycloak realm/theme/password-only flow、client redirects、service-account roles、
break-glass profile/group/enable state 均不需修復；OTP execution 與
CONFIGURE_TOTP required action 都為零。使用 PostgreSQL Pod 既有 Keycloak DB
服務連線做唯讀聚合，確認 master realm 原有 1 位人工管理員已停用（enabled=0）。
沒有輸出、另存或輪替任何明文憑證；沒有手動執行 bootstrap ensure/check。

## 允許的 operational 寫入與資料保護

新增項目均已逐筆核對：

- 1 筆 `nomosmart-local-36` bootstrap evidence。
- 3 筆成功的 `trigger_type=deployment` identity sync runs。
- 3 筆一對一對應的 `deployment.identity.reconcile` success audits。

這些由既有 bootstrap ensure/check rollout 路徑產生。`check` 並非純讀取；
既有初始化等待／重入行為不保證 exactly once。本次未人工重跑或加建 Job。
三次同步各記錄 8 users updated、8 groups updated、1 derived role membership
updated；這是同步寫入計數，不是業務欄位或權限變更。三次均 0 users created、
0 users disabled、0 groups created、無 error code。

59 張表中 **52 張完整列雜湊不變**。其餘 7 張精確符合白名單：

- users/external_groups：僅允許 last_synced_at、updated_at；其餘欄位 hash 相同。
- external_group_users：10 組複合鍵／完整關聯相同，僅 created_at 可變。
- role_users：external_sync / break_glass 各 1 組相同，僅 timestamps 可變；
  manual RoleUser 完整列不變。
- 上述三張 append-only operational tables：每一筆舊列 hash 相同，只有新增列。

四張 timestamp-normalized 身分表合併 hash 前後相同：
`73c87b0e535ef49605e42aa5270c3498fc56180cec508da5b7b0c328576acf03`。
Keycloak realm/users/clients/mappers/flow/service-account role hashes 及
OpenSearch 非憑證 security payload hashes 前後相同。

下列均保持不變：

- 1 Project、3 Documents、3 Versions、38 total / 37 active Chunks、11 ChatRecords、
  84 usage events、5 models / 4 undeleted、8 active users / 8 groups。
- 1 Owner、3 Project member rows / 2 人；既有 Editor+Viewer overlap 保留。
- 5 Embedding Builds、113 vectors、0 active manifests / published versions。
- 115 Tags、16 document-tag links、164 chunk-tag links。
- Neo4j 110 nodes / 143 relationships；三個版本 source/target scoped digests。
- OpenSearch UUID/count 26 / 11，以及 mappings/settings/aliases/sequence numbers。
- Schema columns/constraints 和 48 筆 migration history。
- 七組 PVC/PV、全部保護 Secret UID/data、兩個 Ingress UID/allowlist、
  全部舊 audit Jobs、NetworkPolicies、kindnet DaemonSet、supporting workloads。
- HTTPS proxy 原容器 ID/spec、LDAP containers/volumes；掛載陣列順序無語意差異。

沒有圖譜修復、DDL、重建、re-embedding、reindex、manifest switch、Provider
呼叫或資料／角色／專案成員修改。現有未正式發布／legacy graph 狀態刻意保留。

## 健康與 Browser 驗收

23:12:08–23:15:48 共 12 輪、每輪相隔約 20 秒：

- 12/12 通過；`/login`、`/api/backend/health`、`/api/backend/ready` 共 36/36
  trusted HTTPS GET 回應 200，沒有關閉 TLS 驗證。
- Backend loopback ready=200；Redis master、2 replicas、Worker/Beat TTL 正常。
- 全部運行中 Pods Ready；觀察窗口內無新增 restart 或 kindnet netlink errors。
- Frontend 使用實際 `BACKEND_INTERNAL_API_BASE_URL` GET health/ready 均 200。
- 實際設定的 `/identity/realms/nomosmart/.well-known/openid-configuration` 回應 200。
- Chrome 既有 NomoSmart 頁面重新載入後正常顯示登入頁，已保留交接。

Peter 後續回覆「已登入」，已使用原 session 完成現有資料圖譜 API/UI 唯讀驗收。
正式 API 200 / 空圖符合 0 active manifests；未發布文件預覽 API 200，
11 Chunks / 59 Tags / 74 edges，UI 關聯選取與原文顯示正常。操作前後
59 張 PostgreSQL 表及 Neo4j／OpenSearch hashes 全部不變。詳見
`CHG-292-REVISION36-AUTH-READONLY-RESULT.md` 與其安全 JSON 證據。
未擷取 token 或代輸密碼。沒有測試正式發布、建立新文件／關聯或觸發 Provider。

## 證據與治理檢查

- `CHG-292-REVISION36-DEPLOY-PRE-EVIDENCE.json`：寫入前安全快照。
- `CHG-292-REVISION36-DEPLOY-EVIDENCE.json`：實際映像／Jobs、逐表與逐列 hash、
  允許新增列、runtime security、圖譜／索引及 12 輪健康原始安全結果。
- `./HARNESS/harness.sh spec:doctor`：PASS。
- `./HARNESS/harness.sh spec:trace`：PASS，GRAPH-009..013 五項映射完整。
- `./HARNESS/harness.sh plan:approved`：PASS。
- `git diff --check`：PASS。

運行檢查使用 real configured services；沒有以 mock/static check 冒充行為驗收。
診斷腳本曾修正 S3 缺少 bucket 參數、OIDC URL 前綴、Frontend 設定變數名稱、
Kubernetes image `docker.io/` 名稱正規化及 pre/post revision assertion；
修正後仍嚴格檢查真實服務／hash，未改產品或放寬保護門檻。

## 限制

這是已核准 local-only 部署，不是 production release 認證。原本完整 80% coverage、
完整 Backend／其餘 authenticated Browser／正式發布驗收、新映像 scan/SBOM 缺口仍在。
12 輪健康不保證 CNI 永不復發；一般主機 DNS 延迟和缺少 Metrics API 的限制保留。
未執行回退，沒有宣稱已驗證本次實際 rollback，也不宣稱 Helm 可撤銷外部資料寫入。

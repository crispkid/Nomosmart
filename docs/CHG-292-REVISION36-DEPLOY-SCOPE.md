# CHG-292 Docker Desktop revision 36 部署核准範圍

日期：2026-09-09。這是待核准的精確操作範圍，本文件本身不是部署授權。
Peter 若核准，須引用本文件的 SHA-256；核准紀錄另寫入 DEVELOPMENT_PLAN.md，
不要在核准後改寫這份綁定文件。規格 10.49 / GRAPH-009..013 不變。

## 1. 目標與不可變產物

只升級 `docker-desktop` context、`nomosmart` namespace 的 `nomosmart-local`，
從健康且 deployed 的 revision **35** 到 prospective revision **36**。
不是重新建置、不是新環境、不是 CHG-291 V049 migration-second 階段。

| 產物 | 綁定值 |
| --- | --- |
| renderSha256 | `fad6bb97fcaeadbccfd90d8b32a3a4a41e578be2ba37a776be7a78f278b32b67` |
| Backend `nomosmart/backend:0.1.0-chg292` | `sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1` |
| Frontend `nomosmart/frontend:0.1.0-chg292` | `sha256:82df26d3807ebc3904826135ae61f10aaf3a6a2a6a5464d2d822638a7935bbd9` |
| 保留 Migration `nomosmart/migrations:0.1.0-chg288` | `sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab` |
| 原 effective values canonical JSON SHA-256 | `019eeed496ad5f6034258caaa2c1b09ad43c8e294b61fbddcce62bf46f469c57` |
| Source HEAD | `bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3` |

render hash 的算法維持原 Stage A：取 hidden-Secret server dry-run stdout 從
`HOOKS:\n` 到結尾的原 UTF-8 bytes，排除前方變動的 release header；96,181 bytes。
2026-09-09 22:45 前後再次核對 revision、image IDs、保護資源及 health/ready 正常；
又做兩次同範圍 hidden-Secret server dry-run，hash 與非 Secret 差異仍一致，
release 保持 35、沒有 revision-36 Jobs。這些不是未來寫入時的永久基線保證。

## 2. 核准後可執行的部署

```bash
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg292 \
  --set-string image.frontend.tag=0.1.0-chg292 \
  --rollback-on-failure --wait --wait-for-jobs --timeout 15m
```

- Backend、Worker、Beat main/init，Frontend readiness init、bootstrap-36
  使用綁定的 Backend CHG-292；Frontend main 使用綁定的 Frontend CHG-292。
- 保留 `compatibility.schemaContract=forward-v047`，Migration image CHG-288。
  結構仍為 V047，Flyway 已套用至 data-only V048；**不套用 V049 或其他 DDL**。
- Job 僅可新增 `nomosmart-local-migration-36` 與
  `nomosmart-local-bootstrap-36`，使用既有模板；保留全部歷史 audit Jobs。
  允許這次 rollout 正常產生的 ReplicaSets/Pods、Helm revision metadata，以及
  綁定 render 中必要的 release annotations／ConfigMap bootstrap release 35→36。
- bootstrap 保持既有 `keycloakMode=manage`、`deploymentPhase=factory_acceptance`；
  不偷改成其他模式、不省略必要檢查，也不手動重跑 bootstrap／migration。
- migration-36 只驗證並執行目前已套用的 001–048；預期無新的 SQL migration。
  checksum mismatch、缺 migration 或 V049 現身均停止，不 repair 或修改歷史紀錄。

## 3. 必須明確核准的既有 bootstrap 副作用

不能承諾「所有資料列 bytes 完全不變」。本次僅允許下列 operational 寫入，
且所有業務內容、權限與成員關聯集合必須保持不變：

1. 新增 `nomosmart-local-36` bootstrap evidence；既有衝突處理為 no-op。
2. 成功 identity reconciliation 產生 deployment-triggered identity sync run
   與 `deployment.identity.reconcile` audit。既有 Job/程序重試可能重複成功
   reconcile；逐次記錄實際筆數，不承諾整個程序 exactly once，不擴大重試設定。
3. 既有 users/external_groups 僅允許同步造成的 `last_synced_at` / `updated_at`
   更新，不新增、停用或更改任何人的業務欄位。重建原 10 個 external_group_users、
   1 個 `external_sync` RoleUser、1 個 `break_glass` RoleUser；複合主鍵／關聯集合
   保持一致，只允許其 `created_at` / `updated_at` 變動。人工 RoleUser、角色
   定義／permission、LDAP group mapping、Project member/Owner 不得變動。
4. OpenSearch bootstrap 會 PUT 既有 runtime internal user／role／role mapping。
   僅允許重申目前相同憑證與權限；內部 password hash 可能重新生成，不將它誤報
   為 Secret 變更。不可新增額外 principal 或提高／降低權限。
5. Keycloak bootstrap 會重申目前 realm password-only flow/theme 設定、sync service
   的既有 service-account role mappings、既有 break-glass user 設定及其原 group
   membership。允許相同語意的既有 PUT/POST 及必要短期 auth session/internal audit；
   不允許新增使用者／群組／角色關聯、修改密碼、切換啟用狀態、改 LDAP provider/
   mapper、改登入政策或清除原 required actions。預檢需確定沒有 OTP execution/
   CONFIGURE_TOTP 需要清除、break-glass 設定完整且符合當前 mode。舊 bootstrap
   admin 須已停用；不得藉這次部署另外停用／登出任何啟用中的管理員。
6. Neo4j 現有 runtime user 須存在且以現有憑證可用；不批准 CREATE/ALTER USER、
   密碼重設或 schema constraint/index DDL。S3 bucket 須已存在；不批准建立 bucket
   或修改物件。上述 ensure 若需要修復缺失，**在 Helm write 前停止**。

既有 periodic heartbeat 與空 outbox dispatch 可正常運作，但不可人工送工作、
清 queue、重播失敗請求或藉部署觸發 Provider。必要服務內部運行日誌／統計不等於
修改 NomoSmart 業務資料。驗證時應依本節白名單逐欄比對，不能任意忽略整張身分表。

## 4. 保護基線與寫入前停止條件

參照既有安全證據，不讀出或另存明文 Secret／個資／文件全文：

- `CHG-292-REVISION36-PREFLIGHT-EVIDENCE.json` SHA-256
  `9040ccad82dc16000148d050699219c000ac9f52c63aecf8615a5e9cb6ff1dec`。
- `CHG-292-ENVIRONMENT-HEALTH-EVIDENCE.json` SHA-256
  `7c42a89f1c8dbea8e68b9b4260689c7c4fb769e52b267c610743ff34fa7ece26`。
- 原 preflight protected-resource digest
  `3663917ffdeb0337847683471c5aaaf8d9b55b6ed77ab791e4f41c45a936f505`；
  recovery 含 NetworkPolicy 的算法 digest
  `446a14c7a60a177f19e97de6375a5810027424e4a8fee0c61491a10ce4e77613`。
  兩者欄位集合不同，不能混比；部署後扣除本文件明列的 rollout 差異再比。
- 7 組 PVC/PV 綁定（含 spec 的 digest）
  `55080d5ad353b80a91655dd05c0fdbc257b153a8b59032749431aac469e5531e`。
- 受保護 Secret UID `1c97c03f-a53e-4bae-9ad5-c1c22d9aecca`，data SHA-256
  `c5882876a22837d3bd197de252039296784dea00a4ad400aa0d435d23cc1587f`
  （Kubernetes base64 data map 的 sorted compact JSON）。其餘 runtime TLS/CA
  Secret UID/data digests 同證據；不得輪替或改權限。
- Ingress UIDs `ca265ba3-b664-4dd7-ac66-fe50962dfdb2`、
  `fafc437c-9685-4e2f-ba12-59991ef496fa`，兩者 allowlist 仍
  `127.0.0.1/32,10.244.0.0/16`。NetworkPolicy、CNI、proxy、身份與 supporting
  workloads/specs、LDAP containers/volumes 不得更動或順便修復。
- 寫入前 59-table digest 必須仍為
  `9dd711fbc65901f6869dccadde63b9ba77c33b4549ea6fa41456bea6eff94364`；
  如只有可合理解釋的自然 operational 紀錄差異，也先回報並更新核准基線，
  不能將本固定核准自動套到新狀態。部署後僅排除第 3 節明列的實際差異。
- 1 Project、3 Documents、3 Versions、38 total / 37 active Chunks、11 ChatRecords、
  84 usage events、5 models / 4 undeleted、8 active users、8 active external groups、
  5 Embedding Builds、113 vectors、0 active manifests、0 published versions；
  1 Owner、3 Project member rows / 2 人（保留舊 Editor+Viewer overlap，不跑 V049）；
  2 roles、3 RoleUser rows、1 external-group mapping；115 Tags、16 document-tag
  links、164 chunk-tag links 均不因部署變更。
- OpenSearch UUID/count 保留 y9N0ThJdQlyujWvz344KxA = 26、
  41mhbFFZSAqe6HcomzDrDQ = 11；index mapping/settings/aliases/sequence 與向量不變。
  Neo4j 110 nodes / 143 relationships 及 MAAS scoped graph digests 不變；不補同步
  候選／刪除文件，不建立正式 graph 或清除 legacy graph。

正式寫入前重新核對上述基線、兩個 image IDs 與 hidden-Secret render SHA-256，
並以唯讀來源比較確認 identity 業務差異為 0、既有 runtime security 設定與
bootstrap payload 相符。檢查能力不足／權限拒絕／缺少資源時停止，不換額外憑證。
健康復發、revision/render/配置漂移、有 queued/running 的業務或圖譜工作、非空
待處理業務 outbox、來源同步差異、新發布資料，均不得執行 Helm write。

## 5. 部署窗口與回退

核准包含同意部署窗口內不操作文件、標籤、正式發布、成員／角色、模型或 API
問答；暫不執行人工／排程同步。執行者需確認沒有活動業務工作、沒有即將觸發的
業務排程才開始。這不是允許代理人 scale／封鎖 Ingress／更改排程；若需強制隔離，
另行核准。純 read-only 健康／驗收請求可進行。

在這個無業務／graph 寫入窗口內允許 Helm `--rollback-on-failure` 回到已驗證的
revision-35 應用／設定（Helm 可增加自己的 rollback revision metadata）。
**Helm rollback 不會撤銷已完成的 PostgreSQL、Keycloak 或 OpenSearch 副作用**；
保留必要 operational evidence，不做反向資料刪除。既有 migration/bootstrap Jobs
須保留，不建立額外修復 Job，不重新呼叫 Provider。

若觀察到新 CHG-292 正式 graph／業務寫入，或任一語意保護集合發生非預期差異，
立即停止後續操作並回報；不得另外手動、無條件回退至舊 graph writer，也不得
自動清圖或「恢復」資料。需要另提保持新證據的恢復方案。確認 maintenance 前提
無法成立時，不啟動帶自動回退的 Helm 升級；本文件不宣稱有跨服務交易或強制寫入鎖。

## 6. 驗收與排除事項

核准後依序：即時 fail-closed preflight → 升級與等待 Jobs/rollout → 核對實際
image IDs → 可信 HTTPS/ready/OIDC、Worker/Beat/Redis/CNI 連續健康驗收 → 檢查
第 3 節允許副作用與第 4 節保護項目 → 既有登入 session 的 read-only 圖譜 API/UI
檢查（若沒有有效 session，交由使用者登入，不擷取憑證或虛構驗收通過）。
只驗證真實現況與新程式已生效，不為測試新增／發布文件或補同步現有圖譜。

本範圍不含：映像重建、SQL/Neo4j DDL、V049、備份／還原、資料／圖譜修復、
reprocess、re-embed、reindex、manifest switch、Provider/billing query、模型定價
修改、角色／Project 成員變更、LDAP/Keycloak 遷移、CNI/proxy/DNS 設定修改。

這是 **Docker Desktop 受控功能驗收部署**，不是 production release 認證。
核准須明確接受目前已揭露的本地驗收限制：完整 80% coverage、完整 Backend/
authenticated Browser、正式發布驗收與新映像 scan/SBOM 仍未全部通過；不能
豁免正式 release 的安全／測試門檻。環境健康已通過 12 輪，但 CNI 復發的底層
觸發機制未完全證實、一般主機 DNS 解析仍約 5 秒；不得稱為永久穩定保證。

執行結果須報告實際 revision、Job、image IDs、健康／資料保護驗證、允許的
operational 寫入筆數、未完成的驗收，以及 `spec:doctor`、`spec:trace`、
`plan:approved` 等治理檢查結果。未取得本文件 scope hash 綁定的人類核准前，
停止在此，不執行部署。

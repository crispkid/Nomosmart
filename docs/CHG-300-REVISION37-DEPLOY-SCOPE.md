# CHG-300 Docker Desktop revision 37：V049 後更新應用

日期：2026-09-13。Gate 2：Peter 以「接受」確認本機風險例外與短暫停寫。
本文件是新寫出的 Gate 3 精確操作計畫；Gate 4 待核准。核准紀錄另記於
DEVELOPMENT_PLAN.md，不在核准後改寫本文件。不得把乾跑或風險接受當成部署成功。

## 1. 範圍與已接受風險

唯一目標：`docker-desktop / nomosmart / nomosmart-local`，健康 revision 36
升至 prospective revision 37；不是新裝、不是 production release 認證。

Peter 已接受：目前沒有驗證可還原的備份、完整測試/E2E及雙端80% coverage
未完成、新 Backend/Migration 未掃描且弱點未知。維持「不掃描」；不重新
匯出或重播失敗備份、不使用聊天密碼。失敗報告、partial與保管限制保留。
這只豁免本次本機操作的上述阻擋，不把失敗/未執行檢查改成 PASS，不降低
正式發布門檻。既有映像53項 gate 與3×22角色/回退案例只代表其受測範圍。

新操作策略：維護停寫後，先建立**同一個 revision 37 的 Migration Job**，
成功並驗證資料後，再由完整 Helm upgrade 接管該 Job 及更新應用。
這解決普通 Job 與 Deployment 同時提交的順序問題；沒有新增第二套 migration、
更換 stage、刪除 render 內原有 workloads 或改成 hook。此新接管策略是本次
精確計畫需核准的部分，不再詢問已接受的風險。

## 2. 不可變產物

| 項目 | 綁定值 |
| --- | --- |
| render SHA-256 | `41908a8b99d38e76469d84f354a6ce1409b9d2e105fd12bf680a370862d894de` |
| Backend `nomosmart/backend:0.1.0-chg300` | `sha256:21283c4f28bb05cc444c416b8020ddd34719235ba56b8c64d51b42a786392ef2` |
| Frontend `nomosmart/frontend:0.1.0-chg299-v049` | `sha256:3fb90bfc19cf0548ad5bcd3d2db4b5915e6b0d37ed7c381c4dff8e36ae57cd8f` |
| Migration `nomosmart/migrations:0.1.0-chg300` | `sha256:7c8c3625d3e965d9fd1e333ac4f2a55c8c432306312bb19f350baaf6085619e6` |
| chart 檔案雜湊 map 的 canonical SHA-256 | `a89cc8fc02df68693c35f7f59ed004617a3eed32f14fb690d6aea040c5079739` |
| 原 V049 SQL SHA-256 | `b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96` |
| V049 實際 Flyway checksum | `-1579162252`（不同於 SQL SHA-256） |
| 預建 Migration Job 檔案 SHA-256 | `0a0c9121cc646080d6d8c045d1fe4d7fc0c81d91ddca6f313259b84eb32558c2` |

160個候選來源檔案與 CHG-300-IMAGE-VERIFICATION-EVIDENCE.json 相同，三 image IDs
實際 inspect 相同。兩次 hidden-Secret server dry-run canonical bytes 相等。
render 算法：原 UTF-8 stdout 自 `HOOKS:\n` 到結尾，排除前方可變 header，
97,091 bytes。綁定的是內容，不只 tag；任一漂移停止，不自動改用下一 revision。

Job 私有檔案：`/private/tmp/chg300-revision37-plan-6kTUkxCB/migration-37-proposed.json`。
其 spec 與完整 render 中 migration-37 完全相同，只補 namespace 及 Helm
release-name/release-namespace ownership annotations；保留 managed-by label
與 keep annotation。實際 server admission 已通過，但未建立 Job、未驗證
真實 Helm 接管。若既有同名 Job 或 ownership/spec 衝突，停止；禁止 force、
take-ownership、覆寫/刪除重建或用額外 Job 繞過。

## 3. 寫入前必須成立的基線

已唯讀確認（不是未來永久保證）：revision36 deployed、四個應用各1/1 Ready；
PG Pod `nomosmart-local-postgresql-0` UID
`83e48efc-56e4-4cda-81da-e9117acb9ef6`，DB `nomosmart`，Flyway V048 checksum
1657807790、failed=0、V049=0。1 Project、3 Documents、3 Versions、38 Chunks、
11 ChatRecords、8 users、8 external groups、5 Embedding Builds、1 Owner、
3 member rows；MAAS user01=Owner、user02=Editor+Viewer。

- Protected-resource canonical digest：
  `747ee6b2fc741f06d7ab1302c76aa52f508c6a48a8a86f53e3da8260d600eea1`。
- DB properties digest：
  `cfc9912a112e4a56b940f4343062faa4575d1a43e24d8fd191b448a731173e8a`。
- 明列非 Secret live kinds 的 spec/data digest：
  `d6110c180890fbf45c258e4930a1a6eb16023777d4271a1e96b179507aa8a8d8`。
- 7組Bound PVC/PV、37個保護資源、10 NetworkPolicies、3 PDB；無 HPA/CronJob。
  Ingress UID ca265ba3-b664-4dd7-ac66-fe50962dfdb2 與
  fafc437c-9685-4e2f-ba12-59991ef496fa、allowlist 不變。
- DB 工作狀態：pipeline failed1/submission_ready2、graph completed3、outbox
  dispatched37；沒有資料庫記錄中的活動工作。不等於 broker 已確認清空。

核准後、停寫前再驗 identity/images/render/上述保護摘要，並完成以下唯讀檢查：
broker active/reserved/scheduled工作、其他 DB writer/排程、完整業務表與
model/usage/vector/manifest安全摘要、OpenSearch索引/Neo4j圖譜/身分語意摘要。
只讀彙總、hash及必要權限關聯，不輸出個資/文件/聊天/模型key/Secret正文。
停寫後再取同 snapshot 基線供真正 migration 比較；它不是新備份或復原點。
未測項不可套舊值假裝通過。活動工作、未授權 writer、基線漂移、無法安全
驗證或權限拒絕，均在寫入前停止，不新增憑證、不修復環境後繼續。

Secret 採 API metadata-only UID/resourceVersion 保護，不索取整包後過濾；
禁止讀 Helm stored manifest/values 或 encoded release Secret。Helm 本身
使用既有正常認證與 `--hide-secret` server dry-run。保護摘要含 Helm Secret
metadata：部署後只容許新增本次 release/rollback metadata，不能用新增項目
掩蓋原有 runtime Secret 的 UID/resourceVersion 變動。

## 4. 維護與嚴格執行順序

正常嘗試的有界等待：drain最多5分鐘、migration最多15分鐘、Helm最多15分鐘；
恢復健康另最多5分鐘。期間 UI/API可能暫時無法使用。不能保證失敗時40分鐘內
一定恢復；若 DB 狀態不明，保留停寫並回報，不能為準時恢復而重放/強制修復。

1. 通知開始維護；凍結 user/API業務寫入。只縮放四個現有 Deployment：
   `nomosmart-local-beat`、`nomosmart-local-frontend`、`nomosmart-local-backend`、
   `nomosmart-local-worker`。先停Beat、再停Frontend/Backend入口；確認Worker
   沒有執行/保留/排定業務後正常停止Worker。記錄UID與原副本數1；不強殺、
   revoke、清queue或中斷正在執行的工作。5分鐘不能drain則恢復原副本並停止。
   不縮放DB/Redis/Keycloak/OpenLDAP/phpLDAPadmin/OpenSearch/Neo4j/S3/CNI。
2. 四個應用Pod正常終止、無其他 writer 後取得一致性資料摘要；確認仍恰好只需
   移除 MAAS user02 的重複Viewer row。Owner一致性不符或其他角色差異先停止。
3. 檢查 Job 檔案 hash/spec/ownership 及同名不存在；建立唯一
   `nomosmart-local-migration-37`。使用既存非root/Secret references/資源限制，
   原 activeDeadlineSeconds=900、backoffLimit=1 不改。最多執行原001–049；
   不做 repair/clean、V050、SQL改寫、額外人工DML或重試Job。
4. Job Complete後，唯讀驗證V049成功、checksum=-1579162252、無failed history、
   原history不變、唯一constraint/index/comment及Owner parity。member rows
   3→2：user01 Owner、user02 Editor；只刪一列Viewer。migration audit+1、
   history+1，其餘業務/身分/模型/內容/向量/索引摘要相等。未通過不更新應用。
5. 只有上述通過才執行下方完整 Helm upgrade；它接管相同UID/spec的已完成
   migration-37並建立bootstrap-37，然後更新四個Deployment。保留stage、
   全部原有render物件與audit Jobs；不能先套部分chart或用stage省略物件。
6. 驗證實际release/image IDs/Jobs、四個應用各1/1及資料保護後結束維護。
   單次嘗試失敗不自動換revision重跑、建置、改chart或修資料。

```bash
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg300 \
  --set-string image.frontend.tag=0.1.0-chg299-v049 \
  --set-string image.migration.tag=0.1.0-chg300 \
  --set-string compatibility.schemaContract=forward-v049 \
  --set-string migration.requiredVersion=049 \
  --set-string migration.requiredChecksum=-1579162252 \
  --set migration.checkTimeoutSeconds=10 \
  --rollback-on-failure --wait --wait-for-jobs --timeout 15m
```

`checkTimeoutSeconds`必須是integer；不可用set-string或省略讓reuse-values缺欄。
Backend/Worker/Beat main/init、Frontend readiness init及bootstrap使用CHG300，
Frontend main使用CHG299-v049。只新增migration-37/bootstrap-37、正常RS/Pods、
Helm metadata；ConfigMap僅切schemaContract、bootstrap release及3個migration
gate環境值。既存3PDB spec相同；default-deny ingress省略/空list的表示差異
不放寬政策；非Helm-owned PVC/default SA/kube-root-ca不是刪除目標。

## 5. Bootstrap 有界 operational 寫入

保留 `factory_acceptance`、Keycloak `manage` 與既有bootstrap重試上限
backoffLimit=3 / activeDeadlineSeconds=1200；不手動重跑。不能把bootstrap
check当成唯讀：它也可能寫identity reconciliation。允許的副作用只有：

1. `nomosmart-local-37` bootstrap evidence及實際成功identity sync run/audit；
   init/check/既有重試可能多次，記錄真實筆數，不承諾exactly once。
2. 既有users/external_groups同步timestamp；external_group_users及
   external_sync/break_glass RoleUser重新具現化原關聯集合與timestamp。
   不新增/停用使用者、改業務欄位/人工RoleUser/角色permission/group mapping。
   Project關聯僅第4節原V049唯一差異，不允許bootstrap額外改成員。
3. OpenSearch以既有憑證PUT相同runtime user/role/mapping；可重生內部password
   hash但權限/憑證語意不變。不更動索引文件/mapping/settings/alias/vector。
4. Keycloak重申相同password-only realm/flow/theme、service-account roles與
   break-glass profile/group；可有必要短期auth session及internal audit。
   預檢必須無OTP/required-action清除需求、原bootstrap admin已停用。
   不新建使用者/角色關聯、不改密碼/enable/LDAP provider/mapper/登入政策。
5. Neo4j runtime user及S3 bucket必須已存在且可用；不CREATE/ALTER USER、
   schema DDL、建bucket、改object或repair graph。若ensure會需要這些動作，
   在停寫/建Job前停止。

逐欄/關聯集合比對，不忽略整張身分表；保留其他application rows與所有七組
PVC/PV、原Secret、Ingress/allowlist、identity及支援服務、Neo4j/OpenSearch。
不做reprocess/re-embed/reindex/manifest switch/Provider/billing query。

## 6. 失敗與回退

- migration前/drain失敗：恢復原四個副本1，現行revision36/V048不變。
- migration失敗：唯讀確認transaction/history與資料；只有確認仍為原V048且
  原基線相等才恢復舊應用。狀態不明則保留停寫，保存失敗Job，不repair/clean。
- V049完成但Helm尚未寫入或Job接管衝突：不force/delete/recreate；保留V049與
  Job，以原revision36已實測V049相容的CHG292應用/設定恢復原副本，並回報
  應用未升級。這不是SQL rollback，Viewer row不補回。
- Helm rollout失敗：讓`rollback-on-failure`回到已驗證revision36應用/設定，
  可產生Helm rollback revision metadata；保留V049與完成/失敗audit Jobs，
  確認四個副本恢復1。不退到未實測、多角色writer的更舊版本。
- 非預期業務/身分差異、無法恢復健康或部分DDL狀態不明：停止後续並回報；
  不自動整庫還原、不刪除evidence、不重放工作/Provider，不修改資料偽裝PASS。

## 7. 驗收及證據

真實唯讀驗收：V049/history/constraint/角色/基線、兩個Job及image IDs、
Backend health/readiness `migrated:49:-1579162252`、Frontend init與主程式、
Worker/Beat、Backend↔Frontend、host HTTPS與OIDC discovery。
既有登入session可用才做唯讀UI/API；沒有session如實列未驗，不擷取密碼。
不透過新增/刪除/編輯真實資料驗收，不呼叫模型。檢查Job接管後同UID/spec，
證明V049 Complete/data checks早於Deployment template更新，不能只列init PASS。

MIGLOCAL-T01..T06見TEST_PLAN；寫入/驗收目前NOT RUN。即使成功，只回報本機
部署與實際驗證，不宣告全部Bug消除或正式release合格。未知安全/全套測試/
備份還原及真正Job接管風險仍須留在交付報告。此scope核准後才可實際執行。

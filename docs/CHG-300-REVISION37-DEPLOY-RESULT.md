# CHG-300 revision 37 部署結果

日期：2026-09-13（Asia/Taipei）。狀態：**DEPLOYED / ACCEPTANCE PARTIAL**。
`docker-desktop / nomosmart / nomosmart-local` 已由 revision 36 升為 **37**，
Helm exit 0 / deployed。V049 先完成且資料驗證通過，才更新應用。
這是 Peter 已接受風險的本機部署，不是完整測試、資安或正式發布認證。

依據：SPECIFICATION.md §10.57 `MIGLOCAL-001`、`MIGGATE-002`；Peter 後續
「核准」為精確 scope 的 Gate 4。不可變計畫
[DEPLOY-SCOPE](CHG-300-REVISION37-DEPLOY-SCOPE.md) SHA-256：
`2aafb12b21f33f2d71a7c38c3c8df6348515b4d2132d2da7f0f6b5e949a76dc7`。
結構化摘要：[DEPLOY-EVIDENCE](CHG-300-REVISION37-DEPLOY-EVIDENCE.json)。

## 實際版本與順序

| 項目 | 部署結果 |
| --- | --- |
| Backend / Worker / Beat main、各 init、bootstrap | `nomosmart/backend:0.1.0-chg300` |
| Frontend main | `nomosmart/frontend:0.1.0-chg299-v049` |
| Frontend readiness init | `nomosmart/backend:0.1.0-chg300` |
| Migration | `nomosmart/migrations:0.1.0-chg300` |
| Flyway | V049 success；checksum `-1579162252` |
| 四個應用 Deployment | 各 1/1 Ready；main restart count 0 |

三個執行中映像 ID 均符合核准綁定，完整值見 evidence。未重新建置或掃描。

1. 維護開始 20:48:43；四個應用正常停止，20:49:07 完成停寫。
   Worker active/reserved/scheduled、broker queue/unacked 為零；無其他活動 DB writer。
   支援服務未縮放，沒有強殺、清 queue 或撤銷工作。
2. 20:50:24 建立唯一 `nomosmart-local-migration-37`，20:50:29 Complete。
3. 20:50:47 真實資料驗證 PASS：V049、checksum、唯一角色約束、Owner parity
   與有界資料差異。此時尚未更新應用 template。
4. 20:52:19 執行核准的完整 Helm upgrade；20:53:14 exit 0，revision 37 deployed。
   同一 Migration Job UID/spec 成功接管，沒有 force、刪除重建或重跑 migration。
5. `bootstrap-37` 20:52:29 Complete。只新增 migration-37 / bootstrap-37；
   歷史 audit Jobs 保留。回退與故障注入 **NOT EXERCISED**，沒有 DB restore。

Migration UID：`b6c79d7c-2d01-4583-a4f0-2290009a76a0`。
Bootstrap UID：`47c394b8-1761-4d79-9b1d-ebb13c87eade`。
Migration spec SHA-256：`f5542d8ae23bdc45c9df6dad6336d3690db3aed39372b16f8fa0d442153dadd4`。
Render SHA-256：`41908a8b99d38e76469d84f354a6ce1409b9d2e105fd12bf680a370862d894de`。

## 資料與資源驗證

- V049 僅刪除 MAAS user02 的 **一列重複 Viewer**，保留 Editor；user01 保留 Owner。
  成員角色列 3→2，Owner parity errors=0；唯一約束
  `uq_project_members_project_user`、有效索引與註解均已驗證。
  只新增一列 migration audit、一列成功 Flyway history，既有 history 不變。
  這一列不會由 Helm rollback 恢復；任何恢復需另行授權資料變更。
- 停寫 snapshot 覆蓋 62 張表。Migration 後除上述三表外業務摘要不變；
  應用部署後只發生核准的 bootstrap operational 寫入：3 個成功 deployment
  identity sync、3 個 reconcile audit、1 個 release-37 bootstrap evidence，
  以及既有人員/群組同步時間與原關聯重新具現化。逐欄/關聯語意一致，
  沒有新增或停用使用者、改人工角色/權限/群組 mapping 或額外改專案成員。
- 1 Project、3 Documents、3 Versions、38 total/37 active Chunks、11 ChatRecords、
  84 usage events、4 undeleted models、8 users、8 external groups、5 Embedding Builds、
  113 vectors、0 active manifests 保留。
- OpenSearch 兩索引文件數 26/11，index identity、mapping/settings/aliases/seqno
  與安全權限語意比對一致。Neo4j 110 nodes / 143 relationships，完整內容摘要相等。
- 37 個非應用保護資源 UID/spec、7 組 Bound PVC/PV、Ingress UID/allowlist、
  10 NetworkPolicies、3 PDB 及身分/支援服務語意比對通過。
- **Secret 完整保護證據仍有缺口**：前置只保存包含可變 Helm release Secret
  metadata 的整體 hash，沒有逐列 resourceVersion；Helm 更新後無法重建原逐列值，
  因此不能宣稱 runtime Secret resourceVersion 精確相等。metadata-only 補查確認
  7 個 runtime Secret 均早於本次部署建立，記錄的 managedFields 更新也早於預檢，
  歷史明列的 5 個 UID 相同；本次 render 無 Secret，沒有執行 runtime Secret 修改。
  **沒有讀取 Secret 正文，也沒有宣稱 data digest 比對通過。**

## 驗收結果與未完成項

| 案例 | 實際結果 |
| --- | --- |
| MIGLOCAL-T01 | PARTIAL：fresh images/source160/chart/render/revision/writer/data/identity/index guards PASS；逐 Secret resourceVersion 前後證據不完整 |
| MIGLOCAL-T02 | PASS：只正常 drain 四應用；其餘保護資源保留 |
| MIGLOCAL-T03 | PASS：真實 migration Complete + V049/data PASS 早於 Helm template 更新 |
| MIGLOCAL-T04 | PASS：唯一角色、Owner parity、精確一列 Viewer 移除及其餘業務保護 |
| MIGLOCAL-T05 | PASS：相同 Job UID/spec 接管、兩 Job、四應用 images/init/Ready、bootstrap allowlist |
| MIGLOCAL-T06 | PARTIAL：外部服務路徑正常；Backend→Frontend 直連 FAIL；登入後 UI 未測；rollback 未觸發 |

三輪真實檢查均確認 `/login`、`/api/backend/ready`、`/api/backend/health` HTTP 200；
Frontend→Backend 及其代理路徑 HTTP 200。Backend readiness 為
`migrated:49:-1579162252`。補充檢查 OIDC discovery、Redis ping、Worker/Beat
心跳均正常。瀏覽器重新載入登入頁正常，但沒有既有登入 session，故登入後
權限/主要操作畫面 **NOT RUN**；沒有填密碼或儲存任何 UI 變更。

**未通過的內部直連：** Backend→Frontend 三次 ConnectTimeout。唯讀檢查找到
既有 `nomosmart-local-frontend-ingress` 僅允許 ingress-nginx namespace/controller
存取 Frontend 3000，Backend 不在允許來源；default-deny 同樣保留。
兩應用都在 desktop-worker2，不能據此宣稱跨節點 CNI 故障。
這是「要求雙向直連的驗收項」與「保留既有網路隔離」衝突。
原 health.json 的 `all_pass=false` 保留；補測成功沒有覆蓋原 FAIL。
網站路徑與 rollout 正常，未觸發 Helm 自動回退；沒有放寬政策、重啟/修 CNI
或繼續重試被拒路徑。建議後續確認正確驗收路徑，**不是降低隔離來取得 PASS**。

保留的初始失敗/修正：OpenSearch readonly preflight 曾 RemoteProtocolError，
同一唯讀檢查再取一次 PASS，未改服務；首次 health probe 未完成，後續三次
具名 FAIL 均保留。結果整理曾因 image 的 docker.io 前綴、identity status 實際
為 succeeded、歷史 Secret 清單只選列 5 個而停止，核對既有契約後更正比較呈現，
不修改產品/資料、不放寬 image ID 或身分語意比對。

## 驗證命令與保留風險

實際部署命令沿用不可變 scope §4，含 reuse-values、rollback-on-failure、wait、
wait-for-jobs、timeout 15m；實際順序由私有 freeze/create_migration/upgrade 記錄證明。
真實唯讀檢查使用 db_readonly、service_preflight/postflight、postproof、health、
supplement；原始證據私存 `/private/tmp/chg300-revision37-deploy-z5dUrjhQ`，
目錄 0700 / evidence 0600。追溯 SHA-256 見公開的安全摘要 JSON，沒有複製文件、
聊天、模型 key、Secret 正文或整份 Helm release/values 至報告。

治理檢查：`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:doctor`、
`plan:approved`、`test:plan`，以及 `git diff --check` 全部 PASS；JSON 檢查與
不可變 scope hash 重驗亦 PASS。結果記於 evidence；這些不是完整產品測試。
沒有重跑全套產品測試、coverage、資安掃描或 Provider 測試。

無驗證可復原備份、全套測試/E2E/雙端 80% coverage 未結案、新 Backend/Migration
未掃描且風險未知，是已接受但**仍存在**的本機風險。V049 成功不會消除它們。
本輪未 reprocess/re-embed/reindex、未切 manifest、未呼叫 Provider。
部署已完成；後續工作是上述驗收缺口，不是再次部署或重新索取相同部署核准。

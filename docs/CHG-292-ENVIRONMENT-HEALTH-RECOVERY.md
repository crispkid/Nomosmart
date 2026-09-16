# CHG-292 部署前環境健康恢復

日期：2026-09-09。依 Peter 指示「先恢復目前環境的健康狀態，再核准部署」。
本次是既有 revision 35 的環境修復，不是 CHG-292 revision 36 部署核准。
規格 10.49 / GRAPH-009..013、產品程式與 migration 策略不變。

## 範圍與停止條件

- 先唯讀診斷；只針對已定位的既有無狀態元件做最小恢復，操作前驗證精確 identity。
- 不部署、不建置、不建立 Job，不變更資料／索引／權限／Secret／PVC／Ingress，
  不執行 bootstrap、Provider、graph repair、reprocess 或 manifest switch。
- 不放寬 TLS 驗證、allowlist、NetworkPolicy 或探針門檻；不能靠綠色狀態掩蓋失敗。
- 如需更動產品設定、資料或擴大基礎設施範圍，停止並另行核准。

## 初步證據與最小操作

14:22–14:27 UTC 的唯讀檢查：

- Backend health / ready 重新得到 200，所有 dependency healthy；這是當次結果，
  不能消除前次 timeout 或代表已穩定。
- Worker 曾 0/1、累計 204 次重啟，事件明確包含 Sentinel `No master found`
  與 Celery inspect ping timeout，liveness 觸發重啟。當次 Sentinel 查詢能看見
  一個 master 與兩個 replicas；需要持續確認，未改寫 Redis。
- 主機 HTTPS 在 ClientHello 後、收到憑證前 reset，HTTP 則 308。Ingress 到
  Frontend 得到 200。既有 HTTPS 代理內，直接 NodePort 與代理 loopback 都能
  取得伺服器憑證（容器未信任該 CA 而拒絕，沒有停用驗證）。故 HTTPS 的當前
  失敗已縮小至主機至代理的 Docker forwarding 路徑。
- 三個 kindnet 日誌有 netlink 異常，worker2 最密集；尚未據此判定全部故障根因，
  未重啟 CNI、Redis、應用 Pod 或整個 Docker Desktop。

允許的首個恢復操作：只 restart 既有、無掛載的
`nomosmart-local-ingress-https-loopback`，ID
`125e83c8ac297ddebfec6d1b17f44229e326d535ae7249aa92789033a6649891`。
保留 image `alpine/socat:1.8.0.1`、`kind` network、`127.0.0.1:443`、
`TCP:desktop-worker2:30443` 與完整設定摘要。不刪除／重建容器。

## 驗證

操作後檢查容器 identity/spec、可信 TLS 的主機 HTTPS、Frontend→Backend、
Backend readiness、Worker Ready/restart count、Sentinel/Redis 與保護資源摘要。
必須多次通過，不因單次 Ready 就核准部署；若失敗則記錄並繼續限縮或回報阻礙。

## 14:31 UTC 後續診斷與 CNI 修復邊界

HTTPS 代理 14:27:36 UTC 重啟後容器 ID/spec 保持不變，spec SHA-256
`92be0ed0c0734793e80bd35a28ef5e2c6bee4a22b6be939242f8f5a79f046c36`。
初次 HTTPS 仍 timeout，後續曾取得 200，但 Worker Ready 仍波動，故此操作不能
單獨證明健康已恢復。

kindnet 不只出現 receive error，更持續記錄 `failed to set verdict with label`
及 `netlink send: i/o timeout`。Backend→PostgreSQL 的 readonly inventory 連續
兩次失敗；PostgreSQL Pod 內 read-only SQL 正常，graph/outbox/pipeline/identity
活動工作計數均 0。網路引擎異常與跨 Pod 連線間歇失敗相符。

依同一「恢復健康」授權，最小修復為先替換 worker2 的單一 kindnet Pod，
等待 DaemonSet 產生 Ready replacement 再重測。若其他節點持續同類錯誤且健康
仍失敗，才逐一處理已核對的另外兩個成員，不重啟應用或 stateful Pods。

| Node | 原 Pod | 原 UID |
| --- | --- | --- |
| desktop-worker2 | kindnet-dq5w7 | 1772c67a-9b39-4f9e-af16-51f19fab4b83 |
| desktop-worker | kindnet-pps22 | 8245e05c-1100-434b-8408-33701a14672f |
| desktop-control-plane | kindnet-pnbmg | d594bed5-da55-49d0-9cfe-714c7eb51d2c |

每次使用 API UID precondition，且事前事後核對 DaemonSet UID
`58f87511-54ac-4d1e-ae09-0cd2e40f779e` 與 spec SHA-256
`0a31b6f84cc90a656a4c60b15ee8a8c9bd0250c413bcc95b5d33050fc0656f35`。
保護快照（包括 workload、Job、PVC/PV、Ingress、NetworkPolicy、ConfigMap、
runtime Secret digests）SHA-256：
`446a14c7a60a177f19e97de6375a5810027424e4a8fee0c61491a10ce4e77613`。
此與舊 preflight digest 的欄位集合不同，不直接混比。

## 最終結果：既有環境健康恢復；revision 36 仍未部署

2026-09-09 22:36:24–22:40:04（Asia/Taipei），共 12 輪、約四分鐘的連續
驗收 **12/12 通過**。安全證據見 `CHG-292-ENVIRONMENT-HEALTH-EVIDENCE.json`，
檔案 SHA-256：`7c42a89f1c8dbea8e68b9b4260689c7c4fb769e52b267c610743ff34fa7ece26`。

- 主機可信 TLS `/login`、`/api/backend/health`、`/api/backend/ready` 各 12 次，
  合計 **36/36 HTTP 200**。沒有停用憑證驗證、略過 allowlist 或放寬 NetworkPolicy。
- Backend loopback ready 12/12 為 200；Redis 保持 master + 2 replicas，Worker
  與 Beat heartbeat TTL 每輪均有效。所有 runtime Pods 每輪 Ready，UID/restart
  counts 不變；三個 replacement kindnet 每輪均沒有新的 netlink error。
- 額外驗證：Frontend loopback /login、Frontend→Backend health/ready、OIDC
  discovery 均 200；HTTP→HTTPS 仍 308；Backend→Frontend 仍按既有 NetworkPolicy
  被拒絕（TimeoutError），不是待修故障。

實際替換的 CNI Pods：

| Node | 新 Pod | 新 UID |
| --- | --- | --- |
| desktop-worker2 | kindnet-rrhgh | 898d80dc-95ed-4c13-a167-2f715e585e5e |
| desktop-worker | kindnet-znz6d | 8ab9326b-1cdd-45c8-8304-5ae2c5122a46 |
| desktop-control-plane | kindnet-4zc4p | 85ba74c9-a838-46d0-b485-8051386a20b4 |

三個原無狀態 Pod 透過 UID-preconditioned DELETE 移除，已由 DaemonSet 自動重建；
DaemonSet UID/generation/spec 不變且 3/3 Ready。不刪除 DaemonSet、節點、應用
或 stateful Pod。Worker 曾在修復過程由既有 liveness 自動重啟至累計 **205** 次
（Killing event 14:32:07 UTC，restart 14:33:07 UTC）；不是人工 restart。
連續驗收開始後維持 205，其他應用與 Redis/Sentinel 重啟數也未新增。

## 保護基線

- Helm `nomosmart-local` 仍 revision **35 / deployed**；Backend、Worker、Beat
  main/init 與 Frontend readiness init 仍 CHG-291，Frontend main 仍 CHG-291。
  Migration 仍 CHG-288；沒有 migration-36/bootstrap-36，未重新 render 或部署。
- 本輪 protected-resource SHA-256 前後完全相同：
  `446a14c7a60a177f19e97de6375a5810027424e4a8fee0c61491a10ce4e77613`。
  重新執行原 preflight（包含 Ready gate）亦通過；其原算法 digest 仍為
  `3663917ffdeb0337847683471c5aaaf8d9b55b6ed77ab791e4f41c45a936f505`。
- 七組 PVC/PV、runtime Secret UID/data digests、Ingress UID/allowlists、
  NetworkPolicies、workload/Job/config specs 均保留。
- 59 張 PostgreSQL 資料表的 count/full-row digests 與前次盤點及本輪兩次成功
  snapshot 均相同：
  `9dd711fbc65901f6869dccadde63b9ba77c33b4549ea6fa41456bea6eff94364`。
  business subset 為
  `2f558246ff5c7251c36ba7cde7702550f34a6ad4dc5e6d17c90fd308e5d3b4c4`。
  Flyway 保持 V048，沒有 V049；ChatRecords 11、usage 84、vectors 113、零 active
  manifests。PostgreSQL 曾因網路逾時無法取樣；沒有將失敗檢查當成通過，待網路
  恢復後重跑成功，未使用修改資料的補償操作。
- OpenSearch index UUID/count 仍為 y9N0ThJdQlyujWvz344KxA = 26、
  41mhbFFZSAqe6HcomzDrDQ = 11，mapping/settings/aliases/sequence summaries
  不變。Neo4j 仍 110 nodes / 143 edges，metadata/count summaries 不變。
- 最後 graph/outbox/pipeline/identity 無活動業務工作，Redis queues/unacked 均 0。
  沒有人工 ack/replay/dispatch 或呼叫 Provider。
- OpenLDAP/phpLDAPadmin 仍 healthy、原 container IDs、config/mount summaries 與
  兩個 LDAP named volumes 保持不變；沒有讀取卷內個資或輸出憑證。

## 限制與後續

這次已定位並恢復的是現有 kindnet 網路引擎失效／間歇連線問題，並刷新既有
HTTPS Docker forwarding。CHG-292 尚未部署，不是其新程式造成。
更底層的 Docker Desktop／休眠／重啟觸發機制尚未證實；本次有限時間健康驗收
不等於永不復發，也沒有修改 kindnet 版本、探針門檻或系統網路設定。

一般主機 curl 的名稱解析仍約 5 秒（DNS 5.004s、HTTPS total 5.078s），
唯讀 IPv4 對照則 DNS 0.0034s、HTTPS total 0.048s。這是另外的名稱解析延遲，
不是 Backend 五秒處理；未以改 hosts/DNS 或停用 TLS 掩蓋它。
`kubectl top pod` / `kubectl top nodes` 因 Metrics API unavailable 無法取得
用量；Node conditions 沒有 Memory/Disk/PID pressure，不宣稱完整效能／容量驗收。

產品程式、SPECIFICATION.md、SPEC_CHANGELOG.md 確認不變。已同步 Development
Plan、Test Plan 與 Traceability 的恢復紀錄。`spec:doctor`、`spec:trace`、
`plan:approved`、`git diff --check` 通過；沒有重跑 feature suites 或豁免既有
coverage／Browser／image scan/SBOM 缺口。

下一步可準備 revision 36 的獨立精確部署核准；仍須在寫入前重驗 image/render/
基線、界定 bootstrap operational writes 與 rollback 風險。本次沒有授權或執行
Helm write、Job、Migration、資料/圖譜修復、reprocess/re-embed/reindex、
manifest switch 或 Provider 呼叫。

# CHG-300 不掃描部署要求：理解與未決事項

## 2026-09-13 執行完成：revision 37 / V049，驗收部分完成

Peter後續「核准」已批准精確scope。已先完成原V049及資料檢查，再由Helm
接管同一migration-37並更新Backend/Frontend，revision37 deployed、四應用
各1/1Ready。網站HTTPS及OIDC正常；只刪一列重複Viewer，其他業務/索引保留。
驗收尚有既有NetworkPolicy阻擋Backend直連Frontend、逐Secret resourceVersion
前後證據不完整、無登入session未測登入後UI。沒有放寬安全或虛報全過。
結果見[部署報告](CHG-300-REVISION37-DEPLOY-RESULT.md)。下方均為歷史，
不表示仍待核准或尚未部署；已接受備份/完整測試/資安風險仍未消失。

## 2026-09-13 最新：風險與維護已接受，精確執行計畫完成

Peter最新「接受」已確認本次Docker Desktop無合格備份、未完成完整測試/
E2E/coverage、新Backend/Migration未掃描與弱點未知的本機風險例外，以及
短暫維護停寫、先V049後應用、失敗只回退相容應用並保留V049、不自動整庫
還原。下方歷史「集中待確認風險」已解除，不再重問、不掃描、不重做備份。

新Gate3精確計畫：CHG-300-REVISION37-DEPLOY-SCOPE.md。剩餘Gate4是普通
migration Job先建立、驗證後由同revision完整Helm接管的具體新機制及有界
操作範圍；不是缺少一般部署意願。依MIGGATE-002，未核准該策略前不建Job。
已完成兩次相同hidden-Secret server dry-run、三image IDs/160source校驗、
V048與非Secret保護基線；實際freeze/V049/Helm/adoption仍NOT RUN。
詳細實證與未測界線見CHG-300-REVISION37-READONLY-PREFLIGHT.md。

## 2026-09-13 最新：R7 真實備份失敗後要求直接部署

Peter 在已告知「新備份還原驗證失敗、V049會刪除重複低角色、Helm回退不會
恢復被刪角色」後明確要求：`沒關係，請直接部署，包含Backend與Frontend`。
已收到 V049＋Backend/Frontend 部署指示，並理解為本次接受沒有驗證合格
備份的風險；不再重問相同一般部署授權，也不自動延伸R7診斷/重驗/匯出。
既有不掃描指示維持。這不是對下列其他未完成發布門檻的概括豁免。

本輪唯讀確認 revision36 deployed；Backend/Worker/Beat/Frontend各1/1 Ready，
目前應用映像皆CHG-292。三個既存候選tag/ID均與證據相同：

- Backend `nomosmart/backend:0.1.0-chg300`，
  `sha256:21283c4f28bb05cc444c416b8020ddd34719235ba56b8c64d51b42a786392ef2`。
- Frontend `nomosmart/frontend:0.1.0-chg299-v049`，
  `sha256:3fb90bfc19cf0548ad5bcd3d2db4b5915e6b0d37ed7c381c4dff8e36ae57cd8f`。
- Migration `nomosmart/migrations:0.1.0-chg300`，
  `sha256:7c8c3625d3e965d9fd1e333ac4f2a55c8c432306312bb19f350baaf6085619e6`。

集中待確認的範圍：是否接受僅Docker Desktop受控風險例外部署，包含完整
Backend/Frontend coverage未達80%、未結案測試/完整E2E缺口，以及新Backend/
Migration未掃描、弱點狀態未知；不能把舊Migration的4Critical/32High報告
直接歸給新image，也不能宣稱新image已清除。另需允許有界短暫維護停寫，
嚴格先V049/checksum/角色資料驗證，再更新應用；應用失敗只可回退相容
應用並保留V049，不自動整庫還原、repair/clean、改寫migration或恢復低角色。

現行chart仍是普通migration Job，直接helm upgrade不能證明template更新
晚於V049；最終執行機制/維護對象/上限/最新render與保護基線須納入精確
部署scope，不沿用舊revision37 render或擅改stage導致現有workloads被刪。
本輪只有repository及Helm history/deployment/image metadata查閱，沒有
Helm/Kubernetes/資料寫入、Job、停寫、掃描、Provider或映像重建。
在上述例外/維護範圍確認前停止實際變更，不把授權當成部署成功。

以下為先前理解/核准歷史，最新指示以上節為準。

2026-09-13 最新：Peter 無法操作電腦，明確要求改為不加密備份。新的本機
明文保管風險與界線見 `CHG-291-V049-UNENCRYPTED-BACKUP-UNDERSTANDING.md`。
本輪只更新理解，未變更工具、匯出資料或部署；不再要求當下 Pinentry 操作。
以下加密方案是歷史，原核准不自動擴成明文匯出或跳過還原／部署驗收。
Peter 隨後以「接受」確認明文風險及保管界線；新版備份計畫見
`CHG-291-V049-UNENCRYPTED-BACKUP-PLAN.md`。Gate 3 完成、Gate 4 待核准，
包含一次現行備份及隔離還原，不含實際 V049 或應用部署。

## 最新「直接更新應用」與實際相容性檢查

後續澄清：Peter 問「為什麼不更新到v049？」並以「好」確認備份→V049→應用
的方向。下方V048-only待確認問題已取消，不再重複詢問；不掃描指示維持。
目前接續已核准的加密備份準備；工具只有合成資料資格驗證入口，需自己的
Terminal Pinentry，未執行現行匯出／V049／部署。

Peter 隨後指示 `直接更新應用`。尚未據此推定可執行 V049 或其他 DB 寫入。
2026-09-13 唯讀交易確認 `nomosmart` 最新成功 Flyway 為 V048，checksum
`1657807790`、V049 history rows=0、failed rows=0；transaction_read_only=on。
PostgreSQL Pod UID=`83e48efc-56e4-4cda-81da-e9117acb9ef6`，目前 Ready。
現行 ConfigMap 未提供 MIGRATION_REQUIRED_VERSION／CHECKSUM。

CHG-300 verifier 是 operator-bound 可配置契約，不是程式硬編碼必須 V049；
但既定整合發布目標為 V049／`-1579162252`。直接只換 image 且沿用現行設定
會缺少契約；指定既定 V049 又會因 DB 仍 V048 被拒。不能為放行而自動從現行
DB 值推導 expected checksum、移除 verifier 或擅改成 V048 目標。

待確認的是資料庫範圍：是否明確改成「保留 V048、不執行 V049 的僅應用部署」。
若是，需依既定流程界定 V048 契約的來源證據、應用相容性、Jobs／bootstrap
及保護資源的範圍，再寫相應部署計畫；這不是已執行變更。現行服務未動。

2026-09-13，Peter 最新指示：`不掃描，直接部署`。此指示取代先前 Scout
核准問題及隨後被中斷的 `Ok`；不執行 Scout、SBOM 外傳或替代掃描。
已收到部署要求，不重複索取同一項掃描／一般部署授權；但未將此句解讀為
取消加密備份、停寫保護、目標遷移順序或豁免全部既有驗收缺口。

## 本輪唯讀確認

- `docker-desktop` / `nomosmart` / `nomosmart-local` 仍為 deployed revision 36。
- Backend、Worker、Beat、Frontend 均為 CHG-292，副本均 1/1 Ready。
- 現行主要服務 Pod 均 Running/Ready；舊 revision-5 的失敗 audit Pods 保留，
  沒有將它們誤判為此次失敗或刪除。此檢查不是完整 HTTPS／應用驗收。
- CHG-300 Backend ID：`sha256:21283c4f28bb05cc444c416b8020ddd34719235ba56b8c64d51b42a786392ef2`。
- CHG-300 Migration ID：`sha256:7c8c3625d3e965d9fd1e333ac4f2a55c8c432306312bb19f350baaf6085619e6`。
- 僅執行 Helm history、kubectl get deployments/pods、docker image inspect；
  沒有 Kubernetes／Helm 寫入、Job、DB 查詢／修改、備份匯出或 Provider 呼叫。

## 必須分開確認的風險與工作

1. 不掃描：兩個新 ID 的弱點狀態未知；不得宣稱舊 Migration 的 4 Critical／
   32 High 已清除，亦不把未執行的安全檢查標記 PASS。
2. 既有完整驗收：前次全量 Backend／Frontend coverage 未達80%，另有斷言與
   prerequisites／Provider 受阻項；本輪53項 gate 和3×22角色測試不是全量通過。
   若做受控本機驗收部署，需要明確接受這些未完成項，不能稱正式發布合格。
3. 真實資料保護：既定 V049 加密備份及隔離還原尚未完成。密碼須由 Peter
   在自己的本機終端輸入，不能在對話或工具紀錄提供。
4. 部署順序：chart 的 migration 是普通 Job，現有 init gate 會阻擋不符 V049
   的新 main 啟動，但不證明 Deployment template 晚於 migration 更新。
   先 migration 再 application 的具體受控部署方式、停寫窗口、fresh baseline、
   render／image 綁定與回退仍須確認，不能直接套用舊 revision-37 render。

建議理解：僅 Docker Desktop 受控驗收部署，明確記錄未掃描及未完成全量驗收
的風險；保留加密備份、停寫與先 V049 後應用更新的保護，不擴成正式環境放行。
這是部署理解及待確認清單，**不是新的已核准執行計畫或部署成功證明**。
參考 SPECIFICATION.md §10.57 MIGSEC-001、MIGGATE-002、MIGSAFE-001；
CHG-291-INTEGRATED-RELEASE-RESULT.md 與 CHG-291-V049-LIVE-BACKUP-PLAN.md。

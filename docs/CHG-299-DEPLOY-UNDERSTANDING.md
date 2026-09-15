# CHG-299 部署範圍確認（Gate 1）

日期：2026-09-12。Peter 回覆「同意部署」，承接 CHG-299 S3 修正完成及新版
Backend 才會生效的說明。本輪僅進行唯讀核對，沒有建置、dry-run、部署或資料修改。

後續範圍更新：Peter 已以「Ok，往這個方向執行」確認 Backend、Frontend、
Migration 包含 V049 的累積發布方向。以下「保留舊 Migration／V048」是當時
建議，已由 `CHG-291-INTEGRATED-RELEASE-PLAN.md` 取代；歷史現況與核准界線
仍保留。新準備計畫 Gate 4 待核准，尚未因此建置、備份、dry-run 或部署。

## 現況證據

- `helm --kube-context docker-desktop -n nomosmart list --filter '^nomosmart-local$' -o json`：
  nomosmart-local revision 36，status=deployed，chart=nomosmart-0.8.0。
- `kubectl --context docker-desktop -n nomosmart get deployments ...`：Backend、
  Worker、Beat 與 Frontend 都是 CHG-292，Ready/replicas=1/1。
- 四個應用 Pod 都 Running/Ready，restart=0。部分 supporting Pods 有歷史 restart；
  本次未將單次 Pod Ready 快照視為完整健康、CNI 或發布驗收。
- 工作區包含已核准但尚未部署的 CHG-293..299 累積產品／安全修正；直接從工作區
  建置新版 Backend 並不是僅含 CHG-299 的單一檔案 hotfix。
- CHG-299 的116項隔離案例及同步模組80% coverage，不能替代全體
  Backend/Frontend coverage、完整 E2E、新映像掃描或部署前保護基線。
- CHG-293 舊 revision37 render/image bindings 已不適用於後續修改過的來源。
  舊 CHG-294 R2 Frontend 的安全／smoke 證據也不代表新累積候選已驗收。

## 必須確認的範圍

建議以 CHG-293..299 已核准的累積 Backend＋Frontend 修正作為下一候選，
保持原 Migration 映像、V048，不套用V049、不進行既有資料修補、文件重跑、
re-embedding、reindex、manifest switch、角色／專案成員調整或 Provider 呼叫。

這比上一則「新版 Backend 才會生效」涉及更廣的部署內容，不能把「同意部署」
視為已確認這個未呈現的組合。若只要S3修正，需另明確定義基於現行已部署來源的
最小 hotfix，並重新驗證該來源組合，不能套用目前累積來源的測試結果。

請先由 Peter 確認部署組合。未確認前不新增部署 development plan、不建置或執行
feature tests，不將既有 CHG-299 implementation Gate4 當作新部署 Gate4。

## 後續不能略過的界線

確認組合後，依 AGENTS.md 與 SPECIFICATION.md DEPLOY-004/006、FESEC-004
形成明確計畫，再取得 plan approval。保留所有未完成 coverage/E2E gate，不因
本次部署意願自行降門檻或視為風險豁免。

新候選需有來源／映像／安全報告／canonical render 綁定；部署前須重取保護基線、
確認佇列與排程／維護窗口及回退風險。既有 migration/bootstrap 與 rollout init
可能產生 operational identity/bootstrap/audit 寫入，不能聲稱 Helm 升級零資料寫入；
其允許範圍須以本次 fresh baseline 明確界定，而非複用 revision36 的舊雜湊。

本文件是 understanding/discussion 紀錄，不是已批准的執行計畫或部署結果。

## 2026-09-12 後續 V049 討論

Peter 隨後要求先討論 V049，並以 `Ok` 確認先列出實際前後角色名單、
Owner 矛盾不自行修改。已完成唯讀盤點：MAAS/user02 的 Editor+Viewer
預計僅移除Viewer1筆；user01的Owner一致且不變，無缺Owner專案。
詳見 `CHG-291-V049-READONLY-INVENTORY.md`。尚未改寫部署計畫或擴大為
V049 apply／備份／還原／映像建置授權。

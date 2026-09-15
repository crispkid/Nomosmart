# CHG-300 revision 37 唯讀部署規劃結果

2026-09-13。結果：**唯讀規劃檢查通過；尚未部署**。精確執行scope已寫，
新Job預建/Helm接管機制Gate4待核准；Peter已接受的本機風險不再重問。

## 實際完成

- 現行revision36 deployed、四個應用各1/1Ready、PG18.4/V048成功，V049=0。
- 三個既存候選image IDs與160個image證據來源hash相符，沒有重建/掃描。
- 兩次真實hidden-Secret server dry-run相同：97,091bytes，SHA-256
  `41908a8b99d38e76469d84f354a6ce1409b9d2e105fd12bf680a370862d894de`。
- 預建migration-37的spec與完整render相同，補Helm ownership metadata後
  `kubectl create --dry-run=server` admission通過，沒有建立Job。
- 7組PVC/PV及保護資源pre/post摘要相等；10NetworkPolicies、3既存PDB，
  無HPA/CronJob。原非Helm-owned PVC/default SA/kube-root-ca不列為刪除。
  新物件只有migration-37/bootstrap-37；差異欄位詳EVIDENCE.json。
- DB安全計數、migration/Owner角色基線及工作狀態已讀；broker與完整身分/
  索引/模型/向量語意檢查是核准後寫入前的必需條件，未完成者不冒充PASS。

## 保留的失敗與修正過程

最初嘗試讀舊Helm stored manifest，遇Secret kind即assert停止，未输出或保存
Secret payload。將其改成記憶體內過濾的重試被安全審核拒絕；未繞過拒絕。
後續完全移除此路徑與stored values讀取，改成明列非Secret live kinds、
Secret metadata-only及標準hidden-Secret乾跑；此替代方式經審核允許。
不可重新執行舊路徑或宣稱從未遇到Secret內容；報告不含其正文。

安全替代流程第一次乾跑：reuse-values缺新checkTimeoutSeconds欄位，失敗。
第二次：set-string令欄位成字串，被chart integer schema拒絕。
最後使用`--set migration.checkTimeoutSeconds=10`，兩次乾跑通過；修正的是
候選操作參數，沒有修改chart、現行ConfigMap或放寬schema。

## 驗證與限制

`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`
及`git diff --check`全部exit0。`plan:approved`exit1，正確指出新精確機制
Gate4待核准；不是部署測試失敗，也不能寫成已核准。

沒有scale/停寫、Job、Helm write、V049、DB修改、備份重試、Provider或索引修改。
真實Job接管、遷移後資料差異、rollout/rollback及HTTPS驗收尚未執行。
沒有驗證可還原的備份；全套測試/coverage/E2E与新image掃描缺口維持原狀，
Peter只接受本次Docker Desktop風險，不代表production合格。

私有原始規劃證據：`/private/tmp/chg300-revision37-plan-6kTUkxCB`；保留
preflight、nonsecret render物件、Job候選、比較澄清與真實失敗紀錄。
repo只存安全摘要EVIDENCE.json；source/image/SQL/chart/render/Job綁定與
實際可執行/排除範圍以CHG-300-REVISION37-DEPLOY-SCOPE.md為準。

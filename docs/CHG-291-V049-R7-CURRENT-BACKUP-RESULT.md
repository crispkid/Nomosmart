# CHG-291 R7 新一次現行備份與隔離還原

2026-09-13，Peter 以 `Ok` 直接核准上一輪提出的第 2 項：建立一份新的
不加密備份，並完成隔離還原驗證；不套用 V049、不部署。這是已完成
V49-U001..U006/U010..U012 工具的執行授權，沒有新程式/產品行為修改。

## 執行範圍與既有保護

- 唯一來源：docker-desktop / nomosmart / nomosmart-local revision36，
  nomosmart-local-postgresql-0 的 postgresql container，DB nomosmart、V048。
- 使用既有資格 `/private/tmp/v049-backup-plain-r6-dbi2mr3c`，重新驗證其
  24小時有效期、原254PASS報告及來源雜湊；先 prepare-source 取得 <=15分鐘
  fresh binding，再僅一次 backup-unencrypted/accept-unencrypted。
- 新備份只在 `/Users/peter/NomoSmartBackups/V049/` 下新唯一run；0700/0600，
  owner/ACL/NOFOLLOW/不覆寫及所有原上限不變。保留成功與失敗partial，
  至少至後續部署驗收後七天；不自動刪除、不上傳、不產生下載連結。
- 來源唯讀snapshot、完整新archive、六類/raw schema/catalog/profile/member
  comments證據鏈及前後基線；來源不修改、不停寫、不重啟、不套用遷移。
- 固定本機PG image `sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
  pull=never；最多一個本run新容器，network=none、無port/host mounts、
  PG tmpfs2GiB/CPU2/memory4GiB、無持久logs，還原後精確清理自有資源。
- 全量比較、cleanup及現行postflight全部成功才封存可用備份；任何失敗停止，
  不重設已消耗claim、不重播R2歷史archive、不自動另匯出或放寬比對。
- 原不加密風險接受仍有效；不是全平台DR，不含Secret/key、Keycloak/LDAP/
  S3/Neo4j/OpenSearch/Redis備份，不讀/解密應用密鑰。無Provider/映像建置/
  掃描/Kubernetes mutation/Job/V049/Helm部署。

## 來源綁定

- Script SHA：`e42eeb866dfd7fd8db13a5051c699d2b2660352e2663443a04706418a16a56c9`。
- Test SHA：`dd9d88d0f5c8c8c15986b8579731a09e5bd2d794fb567b5f14c244161c086152`。
- 本輪開始 require_qualification PASS；source-binding/export-claimed尚不存在。
- 既有 SPECIFICATION §10.57 行為確認不變；前輪唯讀資格結果獨立保留。

## 結果

**FAILED / NOT USABLE**。fresh prepare-source exit0，隨後真正備份CLI exit1。
已匯出一份新archive，但隔離還原在member-comment precheck失敗；未封存成
可用備份，沒有result.json、restore-proof或成功postflight，不偽造補件。

### 真正執行

```bash
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py \
  --prepare-source --qualification /private/tmp/v049-backup-plain-r6-dbi2mr3c
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py \
  --backup-unencrypted --qualification /private/tmp/v049-backup-plain-r6-dbi2mr3c \
  --binding-sha256 fe7cd20df51f68b6b2933f9e2bd6b8378b8f17b6a66ed192bdb6a2b5548de308 \
  --accept-unencrypted
```

- 新run：`/Users/peter/NomoSmartBackups/V049/run-20260913T120543Z-da508f9c7bd2591a`。
- 私有log：`/private/tmp/v049-r7-current-backup-RMjr4RZ9/prepare-source.log`、
  `backup-cli.log`。只輸出安全狀態/錯誤碼，沒有dump或資料正文。
- 完整匯出來源snapshot為62表、1,341列。這是來源計數，不代表還原全量比對成功。
- `database.partial.dump`：1,213,458 bytes，SHA-256
  `1a5519f24931c87e2c6f52f404aeaccc6777881c857acb15c69dda72aee7b4ef`。
- 來源snapshot/schema/profile/member-comments/new-source/claim證據已保存；
  實際archive bytes/SHA與source envelope一致，0700/0600檢查PASS。

### 失敗位置及目前能確定的事

CLI安全錯誤碼：`member_comments_state_differs`。
`ExtensionMemberComments.precheck`第一個guard要求`actual_state == state`；
在這裡失敗，尚未進入member-comment寫入transaction，沒有執行註解修補。
此guard比較六類完整狀態，不代表已證明「註解內容」本身有錯。

真實member replay紀錄只有`status=ERROR, phase=precheck`；schema-comparison
紀錄只有`catalog.status=ERROR, full_comparison=false`，沒有保存actual_state
或哪一類不同。因此目前不能斷言是raw schema、資料列、sequence、properties、
owner/ACL或large objects差異，更不能把早期R2的schema差異當成本次根因。
這暴露了前置guard失敗時缺乏分類診斷的缺口；原完整比對不可放寬。

### 停止與安全核對

- 單次export claim已消耗，不重設、不重試、不讀/重播R2 archive。
- 原工具finally已精確移除本run容器`v49b-5d48494d5abefd2e`，
  ID `db6465890c52badad1bbb728c5abeb6d9156ee6291ab08b0cc0e4f9d3ed70f68`。
  其隔離tmpfs還原資料隨容器刪除；私有備份/sidecar/失敗證據全部保留。
- 獨立唯讀核驗：該容器不存在、零本工具PG，Docker inventory與建立前完全相等。
- 另做失敗後唯讀現行檢查：identity/protections/member baseline/compatibility
  與fresh binding一致；revision36、V048、V049=0。沒有修復/停寫/修改現行資料。
- 沒有來源匯出重試、第二次還原、Job、Provider、V049或部署。
- 最初獨立核驗helper誤用unbound inventory引發AttributeError，尚未發出
  Docker/現行呼叫；更正只讀呼叫後上述核對全部PASS，沒有重跑備份/還原。

精確摘要/digest見[本輪證據](CHG-291-V049-R7-CURRENT-BACKUP-EVIDENCE.json)。
第1項工具/唯讀資格歷史PASS保留，但本輪實際備份未合格，第2項仍未完成。
下一步需討論有界分類診斷與本新archive的一次隔離重驗；在另行核准前不
修改工具、不重播archive、不新匯出、不以局部PASS允許部署。

## 驗證命令

`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:approved`（含
plan:doctor）、`test:plan`、`git diff --check` 全部 PASS。本機證據摘要與
真正來源/報告/log/claim SHA及失敗狀態交叉核對 PASS。這些文件/證據檢查
不取代真正 `--backup-unencrypted` 的 exit1/還原 FAIL；沒有重跑原254案，
也沒有修改 SPECIFICATION 行為、程式/測試或原失敗報告。

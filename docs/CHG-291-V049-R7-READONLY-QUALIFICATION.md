# CHG-291 R7 現行來源唯讀資格檢查

2026-09-13，Peter 以「同意」直接核准 R7 隔離驗證結案後提出的下一步：
只做 docker-desktop 現行環境唯讀資格檢查，不匯出備份、不套用 V049、不部署。
這是既有 V49-U012/R7 工具的有界執行授權，不是新產品行為或新開發計畫。

## 範圍

- 固定 docker-desktop / nomosmart / nomosmart-local revision 36。
- 使用既有 `--qualify-source-readonly --accept-source-readonly` 入口。
- 來源檢查限既有 allowlist：部署/PG 身分與健康、七組 PVC/PV、資源規格與
  Secret metadata、V048/成員計數、DB 支援條件及 extension/member 相容性。
- SQL 使用唯讀 transaction；不匯出應用資料、函式/COMMENT 正文或 Secret data。
- 本機私有目錄允許新增本次單次 claim、結果、coverage 與成功時 qualified.json。
- 遇不相容、健康/基線漂移或失敗立即停止；不重設/重試已消耗 claim，不修現行環境。
- 不執行 prepare-source、backup、歷史 R2 重播、容器/Job 建立、映像操作、
  資料/索引/權限變更、V049、Helm write 或 Provider 呼叫。

## 執行前綁定

- 合成證據：`/private/tmp/v049-backup-plain-r6-dbi2mr3c`，原 254PASS。
- Script SHA-256：`e42eeb866dfd7fd8db13a5051c699d2b2660352e2663443a04706418a16a56c9`。
- Test SHA-256：`dd9d88d0f5c8c8c15986b8579731a09e5bd2d794fb567b5f14c244161c086152`。
- 既有 require_synthetic 已驗證來源、報告、coverage 及 24 小時有效期；
  readonly claim/result、qualified、source-binding 均尚不存在。

```bash
backend/.venv/bin/python -B backend/scripts/chg291_v049_live_backup.py \
  --qualify-source-readonly \
  --qualification /private/tmp/v049-backup-plain-r6-dbi2mr3c \
  --accept-source-readonly
```

## 結果

**PASS**，2026-09-13 19:54:30–19:54:31 Asia/Taipei；真正 CLI exit0。
唯讀檢查用時 0.9637777805 秒（300 秒上限），來源/protection 前後一致。
原合成報告保持原樣，本次現行證據獨立新增，沒有重跑或重設單次 claim。

- 現行 revision 36 deployed；PG18.4 固定映像 digest/Pod UID 符合。
- V048 checksum 1657807790 成功，V049=0、failed migration=0。
- 1 Project、1 Owner、3 Project member rows；符合既有 MAAS 指定成員基線。
- 7 組 PVC/PV Bound；37 個資源身分/規格與 Secret metadata 前後一致，
  工作負載通過既有 Ready 檢查。不等同完整 HTTPS/OIDC/產品功能驗收。
- pgcrypto1.4/plpgsql1.0、合法 mixed-owner A/B、41 個 members 與註解大小
  metadata 符合 R7；未讀取 COMMENT 正文，未匯出任何應用資料。
- `qualified.json` 已新增，之後以既有 `require_qualification` 獨立重驗
  實際來源/報告 SHA、claim/proof 關聯、有效期及私有 custody：PASS。
- 原 254PASS 的同源報告未變；不是本輪重新執行 254 案。加入本次真正
  唯讀路徑 coverage 後 statements 1622/1878=86.3685%、branches
  221/266=83.0827%、combined 1843/2144=85.9608%，excluded lines=0。
  原 pytest-only 與 CLI+pytest 報告保留，不使用其他輪次報告補分。
- 證據目錄 `/private/tmp/v049-backup-plain-r6-dbi2mr3c`，root0700/報告0600；
  私有 CLI log `/private/tmp/v049-r7-readonly-8ISrFd9f/qualification-cli.log`。
- 摘要與真實報告 digest 見 [唯讀資格證據](CHG-291-V049-R7-READONLY-EVIDENCE.json)。

程式/測試來源完全未變；SPECIFICATION §10.57 V49-U012 行為確認不變。
沒有 prepare-source/source-binding、新 current backup、隔離 current restore、
Kubernetes mutation、Job/container 建立、R2 archive 重播、V049 或部署。
此 PASS 只完成備份工具的現行來源資格，不代表已經存在可用的現行備份。
新一次備份及隔離還原仍需另行核准；資格與原 synthetic proof 均有 24 小時
有效期，未來真正匯出前還必須做 fresh binding 並重新核對保護基線。

## 文件與證據驗證

`./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:approved`（包含
plan:doctor）、`test:plan` 及 `git diff --check` 全部 PASS。另以只讀本機
檔案的獨立重驗確認此摘要的來源/報告/qualified/log digest、coverage、
254 案數、時間及保護基線 digest 與真正結果一致。未再次呼叫現行服務，
未重跑或合成 feature test 結果；本輪只有操作證據及治理文件變更。

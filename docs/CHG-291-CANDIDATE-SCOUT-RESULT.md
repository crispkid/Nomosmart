# CHG-291 三映像安全掃描結果

2026-09-12：掃描與三份 SBOM 已完成；**Migration 未通過 High/Critical 安全門檻，整批仍不可部署。**

Peter 回覆「是」，明確同意 Docker Scout 傳送候選映像套件清單／SBOM 中繼資料。
先前傳輸審核拒絕保留為歷史；本次依補充授權執行，沒有繞過限制。此核准不包含
修正相依套件、重建映像、push、部署、live V049、應用資料修改或 Provider 呼叫。

## 結果

工具：Docker Scout 1.24.0。三者 tag 均為 `0.1.0-chg299-v049`，掃描使用精確的
`local://sha256:…` image ID，不依可移動 tag 決定對象。

| 候選映像 | Critical | High | Medium | Low | 未指定嚴重度 | High/Critical gate | SBOM 套件筆數 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Backend | 0 | 0 | 57 | 9 | 0 | PASS（exit 0） | 341 |
| Frontend | 0 | 0 | 0 | 0 | 0 | PASS（exit 0） | 351 |
| Migration | 4 | 32 | 42 | 2 | 12 | **FAIL（exit 2）** | 501 |

數字是 SARIF finding 紀錄，不是已證實可利用的漏洞數。Migration 的 36 筆
High/Critical 對應 **28 個不重複 advisory IDs**（3 Critical、25 High）；同一
advisory 可能出現在多個套件版本。SPDX 2.3 套件筆數包含 image root。
Backend 尚有中低風險，不能稱為零漏洞；Frontend 零筆限於本次工具／資料庫可檢出的範圍。

## Migration 問題在哪裡

此候選以 `flyway/flyway:13.0.0-alpine` 為基底。掃描指向映像中的作業系統／Java
相依套件，不是 V049 SQL：

- Critical：Netty handler 4.2.14.Final／4.2.15.Final 的 CVE-2026-75595（兩筆），
  以及 Alpine OpenSSL 3.5.7-r0 的 CVE-2026-75803、CVE-2026-63073。
- High：包含 OpenSSL、Netty、Apache HttpComponents、Jackson、MSSQL JDBC、
  SQLite、Expat 等套件；精確 package URL、advisory、位置見機器可讀證據。

報告保留 Scout 提供的 fixed-version 資訊，但尚未驗證升級相容性、實際可利用性
或修補候選。**未自動升級／移除套件，也未修改 Dockerfile 或 SQL。** 下一步應先
討論 Migration 映像安全修正範圍，再依規格與計畫門檻執行。

## 證據與命令

[機器可讀掃描證據](CHG-291-CANDIDATE-SCOUT-EVIDENCE.json) 含三個完整 image IDs、
九個操作的完整命令、exit code、報告與 log SHA-256、全部 High/Critical 明細。
原始 SARIF、SPDX 與 logs 保留在
`/private/tmp/chg291-release-385z05xz/images/`；沒有覆寫前次失敗報告。

實際入口：

```sh
backend/.venv/bin/python -B backend/scripts/chg291_integrated_preparation.py scans \
  --root /private/tmp/chg291-release-385z05xz
```

每個映像各執行一次：

```text
docker --context desktop-linux scout cves --exit-code --only-severity critical,high --format sarif --output <report> local://<exact-image-id>
docker --context desktop-linux scout cves --format sarif --output <report> local://<exact-image-id>
docker --context desktop-linux scout sbom --format spdx --output <report> local://<exact-image-id>
```

全部報告及三份 SBOM 成功產生。orchestrator／全嚴重度報告命令 exit 0 只代表完成，
不會覆蓋 Migration gate exit 2。來源 manifest SHA-256 仍為
`aea6a1ce709e925c6c6396bdcee1c25a7a6fdb7f66644c5fca3e2d6d2e0f0e95`；
三個 tags 的 image IDs 重新核對一致。

## 尚未解除的發布門檻

獨立 lockfile dependency audit 尚未執行；這次 container scan 不替代該項檢查。
部署 migration 順序保護、測試失敗／全來源覆蓋率、需模型的正向測試、加密備份、
完整 protected inventory、exact-image 角色／回退矩陣及完整 E2E 仍依
[整合準備報告](CHG-291-INTEGRATED-RELEASE-RESULT.md) 列為待完成，沒有安全風險豁免。

規格未變：FESEC-004、DEPLOY-004、TEST-002/005；trace V49-I06。
本次只更新授權與驗證證據，未執行部署或修改現行資料。

文件更新後 `./HARNESS/harness.sh spec:doctor`、`spec:trace`、`plan:approved`、
`test:plan` 及 `git diff --check` 均 PASS；兩份 evidence JSON 解析／關鍵狀態檢查
PASS。這些治理檢查不抵銷上述 container gate FAIL，也不是重跑功能／覆蓋率測試。

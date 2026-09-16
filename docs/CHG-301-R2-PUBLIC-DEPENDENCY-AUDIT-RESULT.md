# CHG-301 R2 公開依賴稽核補充結果

2026-09-17 Asia/Taipei。這是 delivery-security 已核准稽核的補充收據，
不是產品依賴升級、部署或 PR 寫入核准。

## 核准與邊界

Peter 以「同意」確認兩項：依三組修正方向撰寫新計畫、不改目前部署；以及
允許把公開套件名稱及版本送至 npm / PyPI 查詢漏洞，接受技術堆疊資訊外傳風險。
不傳原始碼、環境設定、credentials 或私有套件。工具驗證 npm resolved URL
只能為 registry.npmjs.org、Python source 只能為 pypi.org/simple；root project
不送出。scanner 工具從 PyPI/files.pythonhosted.org 下載，hash 鎖定、禁止 source build。
前次權限拒絕保持歷史事實；取得這次明確同意後才經正常權限申請執行，沒有繞過。

既有工具 `backend/scripts/chg301_r2_security.py` 未修改，SHA256：
`fe7629b023b48d819caa98d242923a8ef85d13e84790e0b6cba66f280f4dbd61`。
使用原 delivery 核准及原截止時間 `2026-09-16T21:44:36.946345+00:00`，
沒有重設 6h 時窗或修改已結案 manifest。獨立 child artifact 目錄：
`/private/tmp/chg301-r2-security-gu0ylzpx`（0700，約 73.34 MiB）。
外層限制 20min / 8GiB RSS / free disk≥100GiB；開始時 host free memory 96%。
實際 18.51s、exit 0。沒有 Docker VM 工作，也未宣稱核實 VM 可用資源。

## 真實結果

稽核時間：2026-09-16T16:18:29.243690Z 至 16:18:46.968552Z。

| 檢查 | 結果 |
| --- | --- |
| npm production / full | 兩者全部嚴重度告警均為 0；lock 有 677 個公開 entries |
| pip production | 54 個當前平台適用依賴，0 告警，沒有 skip |
| pip full | 60 個當前平台適用依賴，0 告警，沒有 skip |
| Bandit --ignore-nosec | 3 High、32 Medium、90 Low；3 High 精確符合既有 FTP 接受 |
| 來源 | 140 檔 hash 前後相同；Git HEAD/MERGE_HEAD 未變 |
| 副作用 | Docker/Kubernetes/Provider 操作各 0；沒有產品升級、部署或 PR 寫入 |

uv lock 全部 62 個公開 Python package 先檢查來源；54/60 是實際匯出後的
平台適用清單，不宣稱所有平台已掃。npm 11.12.1、Node v25.9.0（host scanner，
不是產品 runtime）、Python 3.12.10、uv 0.11.8、pip-audit 2.10.1、Bandit 1.9.4。
scanner dependency lock SHA256：
`c8a57d7c4bbdea6101a3a302a6a3e002d7fbf1a4f0560d2112e615c18b8314dd`。

結果為 `PASS_WITH_ACCEPTED_RISK_SCOPED`，不是無風險、映像或正式發布通過。
`CHG301-R2-FTP-20260915` 原本的精確來源/用途接受未擴大、未改成修復；
pip-audit 不提供 severity，本次零告警不需推測級別。未降低測試或掃描門檻。

## 證據定位

| 私有 run 內檔案 | SHA256 |
| --- | --- |
| result.json | e917b6bc35ce1960070251df0f6c18b02126bc85cef5376419596d535299aaf3 |
| npm-production.json / npm-full.json（兩份內容相同） | 6e9d9e5b2313ef523a23483fe8d4d0749fd5b0c7f45d9d4f9fff24f3b45ff4e8 |
| pip-production.json | 9d888a4611c670de2c8fb52ddebc7b6e9577c07bcac189337be5dee65587cb06 |
| pip-full.json | 57feb9a210898632e56f86c5916472f79351d2df6aef1977073c55a2db226c4c |
| bandit.json | e0217035b189909373dd84f1b482ba0a44515a6efecbfc7fa4de7ea6dda644a3 |

前次 manifest SHA256 仍為
`c765eb1d0c49cc896b240a741181c464430649afd9b5460e11e2773a6ee3feb7`。
前次 16 image SARIF/SBOM、590 筆 High/Critical image-advisory rows、272 PASS
都保留為原收據；本次沒有重跑映像掃描或 feature tests。線上 audit 的核准缺口
已解除，但正式映像高風險、final source binding、builder/平台閉包仍未完成。

下一份[正式依賴修補計畫](CHG-301-R2-FORMAL-DEPENDENCY-REMEDIATION-PLAN.md)
僅 Gate 2/3 完成；新修補、建置及功能回歸須等 Gate 4。

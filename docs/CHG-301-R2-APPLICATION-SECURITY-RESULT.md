# CHG-301 R2 Backend／Frontend 應用安全驗證

2026-09-17 Asia/Taipei。CMPAPP-001–004；**APPLICATION_CHECKPOINT_ELIGIBLE_FOR_PR**。
本輪應用安全、必要回歸與清理通過；不是完整發布／部署驗收。
精確映像、來源、報告雜湊與測試收據見
[Application Security Evidence](CHG-301-R2-APPLICATION-SECURITY-EVIDENCE.json)。

## 已確認的修補

- Backend移除未使用的`build-essential`、`libpq-dev`。使用相同Ubuntu24.04、
  uv0.11.33、應用套件鎖檔。先在ARM64、AMD64做無編譯器clean frozen install、
  完整SARIF/SPDX及非root/network-none import/CLI，均通過後才修改正式Dockerfile。
- 先前builder的127High/5Critical隨不需要的標頭相依閉包移除；沒有CVE排除或
  新NOT_AFFECTED判定。兩平台最終Backend runner也完成High0/Critical0和CLI。
- Frontend保持先前核准的npm11.19.1與Node/Alpine安全pins；本輪逐一驗證兩平台
  base、deps、builder、prod-deps、runner，未以ARM64結果代替AMD64。
- 新驗證工具只在lightweight manifest存放報告path/hash/summary。每個command
  保存RSS peak/time/exit/原始輸出；只對目前仍存活且ownership可驗證的子程序
  群組送signal。9個真實程序案例通過，本輪沒有重現舊EPERM。

## 本輪結果

ARM64與AMD64均使用實際獨立建置／掃描／非root CLI收據，非跨平台推定。

| 應用／階段（每個平台） | High / Critical | 其他掃描告警 | 驗證 |
| --- | --- | --- | --- |
| Backend builder | 0 / 0 | Medium44、Low3、Unspecified5 | clean frozen install、import、uv check PASS |
| Backend runner | 0 / 0 | Medium50、Low9 | Python/FastAPI/uvicorn/OpenSSL及原生工具 CLI PASS |
| Frontend base/deps/builder/prod-deps/runner | 0 / 0 | 全severity0 | 各階段實物scan/CLI PASS；Next production build PASS |

- 共14組合格平台／階段；第一個失敗候選另存，不冒充通過。
- npm production/full與pip production54/full60套件的公開audit均0發現。
  這是2026-09-16T16:18:46Z完成、經來源hash相符檢查的歷史重用，不是新線上audit。
- 本輪新跑Backend Bandit（含原先nosec位置）：3項FTP High符合既有精確
  `CHG301-R2-FTP-20260915`接受，未接受High/Critical為0；新驗證工具High為0。
- 最終`verification-attempt2/regression.xml`：**344 PASS，0失敗／錯誤／略過**；
  保留前輪302案例目的，新增安全工具、材料與scope回歸，沒有刪除歷史失敗XML。
- `deployment-contract.xml`：**10 PASS**；Frontend安全依賴契約**4 PASS**及lint PASS。
- `spec:doctor`、`spec:trace`（42 mappings）、`plan:doctor`、`plan:approved`、
  `test:plan`、`backend:syntax`、`helm:lint`、`deploy:config-policy`及安全Compose
  `config --no-env-resolution --quiet`通過。未用現行Secret或服務測試。
- 精確清理**27個暫存映像**（本輪15＋核准前輪12）；每次刪除前核對ID／refs／
  ownership／全部容器nonuse，僅`image rm --no-prune`，不用force。原有14容器、
  網路及98筆映像清單完整恢復；raw證據與既有BuildKit cache保留。
- 1,808個command收據；實測執行樹RSS峰值2,805,514,240 bytes（約2.61GiB），
  低於8GiB界線；新manifest491,484 bytes。未解除資源／權限限制。

本收據產生於PR寫入前。原PR須在fresh remote/source hygiene核對後以普通提交／
推送更新，遠端提交與狀態以[PR #1](https://github.com/crispkid/Nomosmart/pull/1)
為準；不合併、不發布、不部署。

## 真實失敗與修正

第一個ARM64候選成功build/scan/import，但uv的依賴檢查遭拒讀pyproject。
原因是隔離context的`copyfile`在umask077下把repository0644檔案變成0600，
不是應用需要root。改用保留source模式的私有副本後，第二候選完整CLI通過。
沒有chmod repository/system檔案、提升執行身分或刪除失敗紀錄。

舊run的233,685,284-byte manifest與資源／killpg錯誤保留。新run不重播舊PID，
新manifest與最終RSS數值如上。這是新流程量測，**不足以反推
舊失敗當時確切RSS或斷言舊拒絕為誤報**。

精確清理的前兩次dry-run另發現官方拉取映像沒有Labels、Docker將同一個已核准
repo@digest列入RepoTags的格式差異，當時都未刪除映像。修正僅接受既有精確digest，
其他新tag/ref仍拒絕；新增回歸通過後才執行清理。

## 範圍與限制

核准計畫：[Application Security Plan](CHG-301-R2-APPLICATION-SECURITY-PLAN.md)。
私有證據run：`/private/tmp/chg301-r2-application-4khzxbyc`，新6h期限獨立於舊run。

獨立週邊服務、Migration映像、Redis Sentinel既有失敗為
`DEFERRED_PERIPHERAL_BY_USER`，不再阻擋本輪應用PR；不是已修復／不適用。
原先三個FTP明文SAST High僅在exact source/用途符合既有接受時保留並揭露，
**不是漏洞已修復**：操作者選FTP時帳密／資料仍可能以未加密方式傳送。
Medium/Low保留，不擴修。沒有更動應用API、權限、SQL、現行部署或資料，沒有Provider呼叫。

完整80% coverage、E2E及Kubernetes live仍延期，不標PASS；本輪CLI不是完整問答／
API驗收。所有掃描都是固定來源、版本、平台與當時漏洞資料庫的證據，不保證絕對
零風險。新的候選映像已清理，未推送registry或替換部署。

## 技術依據

實際`uv.lock`與clean install是判定依賴必要性的主要證據；官方
[Psycopg安裝說明](https://www.psycopg.org/docs/install)區分binary安裝與source編譯
需求；[uv同步說明](https://docs.astral.sh/uv/concepts/projects/sync/)說明鎖定環境同步。
此處沒有改換資料庫驅動、增加LLM呼叫或更改鎖檔。

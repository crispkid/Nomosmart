# CHG-291 V049 隔離演練結果

> 2026-09-13 CHG-300 更正：發現此輪 Python 容器工作目錄 `/app` 可蓋過
> `/current` 掛載來源；下方兩列「目前累積工作區來源」不能作為新來源通過的
> 證據，回退列也不能證明「新來源測試後」的回退。原始報告與 artifact 保留，
> 不回改歷史結果。已補 safe path 與實際模組路徑 assertion；重跑結果以
> [CHG-300 驗證](CHG-300-VERIFICATION.md) 為準。舊映像及真實 SQL 演練不因此
> 成為新映像或目前累積來源的發布驗收。

日期：2026-09-12，最終測試約 19:54–19:57（Asia/Taipei）。
核准：Peter 對已提出的隔離演練計畫回覆 `Ok`；僅第一關。
計畫：`CHG-291-V049-REHEARSAL-PLAN.md`。
機器證據：`CHG-291-V049-REHEARSAL-EVIDENCE.json`。

## 結論

**本次範圍通過，沒有找到需要改寫 V049 或產品程式的問題。**
這是自建測試資料、真實隔離服務的結果，不是現行 MAAS 已完成備份或遷移。
不宣稱系統沒有其他 Bug，不代表累積版本已通過所有發布 gates。

- 模擬一位 Owner、另一位 Editor+Viewer：只移除多餘 Viewer 一筆，Owner 不變。
- 對 62 個 public tables 的 row count／穩定資料 digest、constraint、column、
  relation ownership/ACL、sequence 狀態做前後比對。除指定 membership、
  migration audit/history 與新 unique constraint/index/comment 外，其他資料不變。
  部分測試表為空，這不是所有業務資料型態的完整災難復原驗收。
- 實際 pg_dump，再 pg_restore 到空白隔離 DB，比對一致。V049 完成後再還原
  原備份，也確實回到 V048 與原始三筆 membership；不是只檢查 dump 檔存在。
- 直接插入第二種角色受 unique constraint 阻擋；Flyway 重跑與另行直接 SQL
  冪等檢查都不重複改資料/audit。正式遷移驗證使用真實 Flyway，沒有跳過 V042。
- 缺 Owner 的專案、真實鎖競爭造成的 lock timeout，均使 V049 中止且沒有部分
  資料、constraint、audit 或成功 migration history 殘留；沒有 repair/clean 掩蓋失敗。
- 真實 PostgreSQL/OIDC/API 驗證單角色替換、舊資料投影不回填、422、stale lock、
  未授權者、唯一/本人 Owner 保護、並行更新及 audit 原子性。

## 測試矩陣

| Backend 執行來源 | 資料庫 | 結果 | 角色判定模組覆蓋率 |
| --- | --- | --- | --- |
| 已安裝 CHG-292 原始映像 | V048 | 22 PASS | 100% |
| 已安裝 CHG-292 原始映像 | V049 | 22 PASS | 100% |
| 目前累積工作區來源 | V048 | 22 PASS | 100% |
| 目前累積工作區來源 | V049 | 22 PASS | 100% |
| 新來源測試後，換回 CHG-292，保留同一 V049 DB | V049 | 22 PASS | 100% |

13 項主測試全部 PASS、無 skip/error（165.80 秒）；其中四個相容性主案例呼叫
上述五組子測試，共110次子測試執行。每組為10項新 live/policy 測試＋12項保留
CHG-291 回歸；不可把這些重複矩陣執行說成110種不同案例。

Coverage scope 僅 `app.security.project_roles`：26/26 statements、4/4 branches，
五組都是100%，使用原80%門檻。**不是整個 Backend/Frontend 的 coverage**。
ASGI TestClient 經真實 SQL 與 Keycloak token/JWKS 執行，沒有 auth dependency
override、mock 或 Provider 替身；不把此結果充作瀏覽器、Ingress、readiness、
bootstrap 或正式 Helm rollout 驗收。

## 映像／來源綁定

- CHG-292 Backend：`sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1`。
- PostgreSQL 18.4：`sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`。
- Keycloak：`sha256:5912dc85fd5fdfb89e7a0bba9d9ffe0624fc385d2846e543a0114c3fb4fddc6a`。
- Flyway：`sha256:f3c8433401abf859ef9022584c8e6111684363ec490f737e749e9a4705ea32d0`。
- V049：`b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96`，未修改。
- 所有工作區 Backend app、SQL migrations 與 runner/test 檔案 SHA-256，以及
  每份 XML／coverage artifact digest，均列在 evidence JSON。
- Current source 測試是將工作區 app 唯讀掛入已安裝 Backend runtime，**沒有建置
  新映像**；未來新映像的依賴、安全掃描及 smoke 還需另行執行。

## 實作與命令

只新增 `backend/scripts/chg291_v049_rehearsal.py`、
`backend/tests/test_chg291_v049_live_rehearsal.py` 及規劃/證據文件。
既有 CHG-291 test、V049 SQL 及產品程式均未改動；保留 CHG-293..299 工作區修改。
SPECIFICATION.md 10.48 PROJECT-012、PROJECT-010 及 MIGRATE-001、DEPLOY-004/006、
TEST-002 不變；changelog 只記錄本次核准與驗證。

已執行：

```sh
./HARNESS/harness.sh plan:approved
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh test:plan
./HARNESS/harness.sh backend:syntax
git diff --check
backend/.venv/bin/python backend/scripts/chg291_v049_rehearsal.py
```

靜態 harness 均通過。Runner 固定 Docker context=desktop-linux、image ID、
run-owned internal network 與明確 test DB allowlist；每次 SQL/migration/API 前
檢查隔離、mount、資源所有權與 source/tool digest。現行 Kubernetes 不參與。
實際 Flyway、pg_dump/pg_restore、pytest 命令構造完整保留在來源檔；操作資料庫、
target、耗時、回傳值、映像與 XML 對應保留在 evidence，不保存密碼與 token。

## 中途問題與處理

1. Docker socket 最初被 sandbox 阻擋；經標準權限申請後才讀取 Docker／執行
   已核准演練，沒有另找繞過管道。
2. 第一輪 PostgreSQL 初始化缺少映像要求的密碼檔，尚未測 V049。改用全新
   測試密碼檔提供，不讀取現行 Secret。
3. 第二輪執行歷史 V042 時缺少它要求的 `nomosmart` role/database。補齊的是
   新容器內的測試初始化；並使用分離的 migration/app 帳號，不跳過或改寫 V042。
   容器內名稱相同不代表連到現行 NomoSmart DB。
4. 初稿 trace table 重複定義既有 requirement IDs，`spec:trace` 正確拒絕。
   已改為引用既有 requirement 的測試群組，未弱化 harness，重跑通過。
5. 前一完整輪13主測試／5×8 API PASS 後，再加入 legacy-read、真實 SQL role
   policy、原有回歸及 coverage；以上述最後一輪結果作為最終證據。

保留中途失敗摘要及早期 evidence digest，不將 setup failure 隱藏為首次即成功。
TestClient 有現有 Starlette/httpx deprecation warning；沒有為消除警告改依賴。

## 清理與限制

最終 run `v49-a604e46bd6ef` 共建立8個容器（3個服務＋5個依序測試容器），
峰值4個容器；1個專用 PostgreSQL volume、1個 internal network，已依精確 ID
及獨占使用檢查清理。自建資料 dump、測試密碼檔與私有 journal 已刪除；留下
不含憑證的結果、XML、coverage。各中途輪也完成精確清理。

前後比對原有14個 Docker 容器的狀態/啟動時間/映像，以及所有既有 images、
volumes、networks 一致；工作區 app/migration hash 一致。未執行 Kubernetes、
Helm、現行DB backup/apply/restore、文件/索引/角色修補、image pull/build 或 Provider。

CHG-292 對本次成員權限範圍的 V049 相容性已通過，但這不是任意舊版本、整套
系統或未來新映像的無條件 rollback 保證。正式資料若出現新 Owner 矛盾仍先停下
人工確認，不因隔離修復案例通過便直接修改現行 Owner。

## 下一步（未獲本次核准）

先確認現行資料備份的目的地、加密與金鑰保管、保留期限，再核准真實備份及
隔離還原驗證。正式遷移前需 fresh baseline／維護窗口／新 recovery point，
三映像的 build/security/smoke、完整發布 gates、fresh Helm render 與精確套用核准。
整體 Frontend/Backend coverage、完整 E2E、Bootstrap/Ingress/Helm 驗收仍未由
本次關閉。Helm rollback 不等於資料還原，且整庫還原會失去備份後的寫入。

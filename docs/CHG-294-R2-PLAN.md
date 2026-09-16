# CHG-294 R2 — Bundled Node OpenSSL Remediation

日期：2026-09-10。**Gate 4 已獲 Peter 核准；repository 修補與隔離驗證已執行。**
repository 分層結果見 [R2 驗證紀錄](CHG-294-R2-VERIFICATION.md)。
2026-09-11 新映像已建置、掃描／SBOM 通過。首次容器測試的網路介面誤判，
經 Peter 核准修正工具後，四項負向測試及完整正向測試均通過；未跳過隔離防護。
Peter 的條件式部署要求已記錄，但 coverage／完整 E2E 門檻未達，故未部署。
最新結果見 [隔離驗證紀錄](CHG-294-R2-ISOLATION-VERIFICATION.md)。

2026-09-11 Peter 另以 `核准` 回覆新版 Frontend 映像建置、容器驗證與安全掃描
的提案，允許執行既有計畫的映像／SBOM 子階段。新 tag 為
`nomosmart/frontend:0.1.0-chg294-r2`。本次不包含 Backend/Migration 重建、
Kubernetes 查詢／dry-run／部署、資料異動或 Provider；不豁免 coverage/E2E。
進度與結果見 [映像準備紀錄](CHG-294-R2-IMAGE-PREPARATION.md)。

Peter 以 `同意` 確認追加 Node 24.21.0，先更新修補計畫、保持目前環境不變。
前次計畫階段沒有改程式、跑功能測試、建置映像或查詢／修改 Kubernetes。
之後 Peter 另以下方精確文字核准 R2 Gate 4；映像與部署仍不在本輪範圍。

## 根因與目標

已建置的 chg294 映像雖然 system OpenSSL 為 3.5.8-r0，Node 24.20.0 內建的
OpenSSL 仍為 3.5.7，且沒有動態連結 system libssl/libcrypto。故升級 apk 套件
不能修補 Node 自身使用的 crypto。掃描通過不等於所有內建程式庫已修補，也
不能反向推論每項上游漏洞在 NomoSmart 都可觸發。

[Node 24.21.0 官方發布紀錄](https://nodejs.org/en/blog/release/v24.21.0)
列明 OpenSSL 3.5.8，並包含 Undici、CA roots 等 runtime 變更。
R2 採此明確目標，不跨 Node major／OS／libc；官方 Alpine 3.24 arm64 映像的
實際可用性與 digest 已於 Gate 4 後核對：index
`sha256:be80f76cf40ec8e42b9bec49f60a55e0660f30af58d3e5a25530785b30ea67e2`；
linux-arm64 manifest
`sha256:c90fbae51ca047f2fda9ea92fb85eb936c08e6df18df7462bb782bad7c6afa3d`。
這是官方 metadata，不是新 NomoSmart 映像實測。

## 修補範圍

1. `frontend/Dockerfile`：共同 base 改為經驗證的 Node 24.21.0 精確 digest。
   保留 UID 10001、啟動方式、四階段共用、設定外部化與三個 crypto 套件目標。
2. 更新既有安全契約測試；必要時把前次 temporary image smoke 保存成可重跑
   helper，讓 Node 版本／內建 OpenSSL／system 套件各自有強制斷言。
3. 只為 R2 增加有界隔離路徑與測試相容，不刪斷言、不放寬 TLS、腳本權限或
   coverage，不增加產品路由、假 API、假登入或假幾何。
4. package.json／package-lock.json 保持完整 byte 相同；Next、React、sharp、
   所有 R1 修補、CHG-293 功能、Backend、Migration、既有資料均不變。

## 驗收

- 官方 runtime／platform／digest 可追溯；不存在或相依漂移即停止。
- 後續 final linux-arm64-musl image 必須實測 Node 24.21.0、內建 OpenSSL
  3.5.8、system crypto 3.5.8-r0。仍是 3.5.7 時不能因掃描零 findings 而放行。
- 真實 PNG/JPEG encode/resize/decode、Next HTTP 最佳化及 AVIF 原始 bytes
  路徑；真實 TLS、OIDC/session/proxy、Markdown/選取框與 CHG-293 回歸。
- 新映像重新掃描／產生 SBOM，保留內建 runtime 與 system 的獨立證據。
- 完整 frontend/backend 各自 80% coverage 與 full E2E 仍是交付門檻；修完 Node
  不代表這些缺口自動完成。缺前提如實 blocked，無風險豁免。

## 分階段授權與停止條件

R2 Gate 4 核准僅啟動 repository 修補與隔離非 Provider 驗證。
新映像建置／掃描／SBOM／dry-run 仍另行核准；建議新 tag 為
`nomosmart/frontend:0.1.0-chg294-r2`，不覆寫既有 chg294 image 與報告。
正式部署再綁定新 image/render、fresh baseline、bootstrap 寫入與 rollback。
不沿用先前 `可以部署` 取代變更後候選的授權。

不包含目前環境／資料／角色群組／專案權限變更、Migration/V049、圖譜修復、
重處理、re-embed、reindex、manifest switch、Provider 或 billing query。
若需要新增修補、改套件、base 不存在、舊 pin 造成降級或真實測試需改產品碼，
先回報並重新確認，不自行擴大。

正式計畫：[DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 首個 CHG-294 R2 區段。
規格：10.51 FESEC-001..004；測試：T01..T20；追蹤：TRACEABILITY.md。
前次結果：[映像準備紀錄](CHG-294-IMAGE-PREPARATION.md)。

已收到 Gate 4 核准文字（2026-09-10）：

`Peter approves CHG-294 R2 Bundled Node OpenSSL Remediation`

## 歷史 Gate 3 驗證（實作核准前）

`spec:doctor`、`spec:trace`（5 項對應）、`plan:doctor`、`test:plan` 與
`git diff --check` 通過。第一次 spec:trace 指出單一狀態欄混合 R1 已實作與
R2 待核准，已將歷史結果移至證據／備註欄，R2 狀態保持 pending 後重驗。
`plan:approved` 預期 exit 1，確認 R2 Gate 4 pending 會阻止實作。

Dockerfile、package、lock、既有安全測試／runtime helper hashes 與本輪開始
完全相同；產品／chart fingerprint 仍為
`578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79`。
沒有 R2 程式／功能測試／映像／Kubernetes／Provider 操作。

# CHG-300 Backend／Migration 映像建置與安全驗證

2026-09-13：Peter 回覆 `Ok，繼續`，直接承接「下一步需另行核准 Backend／Migration
映像建置與安全掃描，再完成其餘發布驗收」。這是既有 CHG-300 計畫的映像階段
核准，不是部署核准；原 Gate 2／Gate 4 不重新推定為任何 live 資料寫入。
範圍：SPECIFICATION.md 10.57 MIGSEC-001、MIGGATE-001/002、MIGSAFE-001。

## 執行界線

權限更新：本機兩映像建置已獲權限工具放行；新 image IDs 的 Docker Scout
metadata 對外傳輸被拒，`Ok，繼續` 不構成該 payload/destination 的具體授權。
掃描命令未執行、未傳送資料。先完成不受影響的本機隔離驗證；外部掃描需
Peter 明確核准這兩個新 image IDs 向 Docker Scout 傳送套件／SBOM metadata。
下列 scan 為原提議範圍，不能把這份文件自行寫成已取得外傳權限。

- 建置 `nomosmart/backend:0.1.0-chg300` 與 `nomosmart/migrations:0.1.0-chg300`，
  linux/arm64、Docker context `desktop-linux`。如標籤已存在則停止，不覆寫。
- 凍結安全來源快照，排除 `.env`、憑證、generated/dependency folders；保存完整
  build input hashes、image ID、log 與 tool version。先核對上一轮來源無漂移。
- 允許 Dockerfile 既定官方 base/package 下載與本機 BuildKit cache；不 push image、
  不掛 Docker socket 到測試容器、不複用現行 volume 或憑證。
- 以既有 Docker Scout 對這兩個精確新 image IDs 產生 SBOM、全嚴重度與
  High/Critical 掃描；掃描會向 Docker Scout 傳送套件/SBOM metadata，不傳送
  應用資料或另上傳映像。權限工具拒絕時停止該步並說明，不繞過。
- 真實自建 PostgreSQL／隔離 runtime smoke，沿用 run-owned receipt 清理。
  最多8個同時存在自有容器、總8 CPU／12GiB，internal network、新憑證，
  只准自建測試 DB。測試原 V001–V049；不做現行資料備份、apply、repair 或 clean。
- Backend 必須測映像內 app，不用 host app 掛載冒充；Migration 必須使用映像內
  SQL、wrapper、JRE/JDBC。記錄 UID、來源 hash、Flyway 版本、checksum、重跑與
  V048 拒絕/V049 接受，保留失敗紀錄，不以舊映像 PASS 替代。
- Frontend main 不重建；不做 Kubernetes/Helm read/write、server dry-run、Job、
  Provider、資料重建／重嵌入／索引切換、角色或會員修改。

## 執行與驗收

1. source/config/harness 校驗、工具與標籤唯讀盤點。
2. 安全快照；先建 Migration 再 Backend，綁定 image ID 與來源。
3. 官方發行版 license/notices 與 runtime/JRE/platform/Secret wrapper smoke；
   沿用 `flyway/flyway` Open Source 版，不切換 Redgate commercial edition，
   不同意新 EULA、不新增 license/token。若出現需額外授權的互動，先討論。
4. 真實隔離 migration/gate 測試，非 root、唯讀 rootfs 與 tmpfs 相容性檢查。
5. 兩個精確映像 Scout SBOM／完整 CVE／High-Critical gate。Medium/Low 也保留；
   不 suppression、不改門檻。若仍有高風險，報告套件與原因，不宣稱可部署。
6. 比對既有資源未改，精確清理僅自建測試容器／volume／network／密碼與 dump。
   保留新建候選映像、所有 log/evidence 與以前映像，不 prune。

既有可重用 runner：`chg291_integrated_preparation.py` 的安全快照／build/scan
模式與 `chg291_v049_rehearsal.py` 的真實資源隔離／cleanup；只新增此階段有界
入口，不改產品、SQL 或驗收門檻。新增具體命令與結果記入本輪驗證文件。

官方依據（2026-09-13）：
- [Flyway Docker](https://documentation.red-gate.com/flyway/reference/usage/flyway-docker)：區分 Open Source 的 `flyway/flyway` 與 `redgate/flyway`。
- [Flyway Open Source](https://documentation.red-gate.com/flyway/reference/usage/flyway-open-source)：官方列出 13.6.0 映像。

完整全端 coverage／E2E、其餘失敗、加密備份／保護基線／停寫窗口、嚴格部署順序與
精確 artifact rollback 仍是發布 gate。即使本階段全部通過，也不自動部署。

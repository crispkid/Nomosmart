# CHG-301 R2：僅 Backend／Frontend 的資安範圍確認

2026-09-17。Peter已明確要求限縮至Backend／Frontend，不再處理週邊軟體。
Peter於2026-09-17以「對」確認下列範圍與驗收門檻，Gate2 confirmed。
本文保留理解紀錄，不是Gate4執行或PR核准。

## 範圍

納入：兩個應用自身程式碼、套件與間接依賴、Node/Python/OpenSSL等隨附
runtime、base OS／原生工具、Dockerfile的builder與runner，以及應用自身
權限／Secret／TLS安全。Backend builder不是獨立週邊，不能借此次排除消音。

排除：獨立資料庫、搜尋／圖譜／物件儲存、Redis、身分服務、edge Nginx、
Migration/Flyway映像、operator及Kubernetes基礎元件的掃描升級修補。
既有告警／Redis故障切換失敗保留並標本次不處理，不再另追逐修補；不稱安全。
先前已做的RustFS變更不自動撤銷，也不再擴修。應用自身已用套件仍在範圍內。

## 現有證據，不是新掃描

依[前輪結果](CHG-301-R2-FORMAL-DEPENDENCY-RESULT.md)及其固定映像：

| 對象 | ARM64掃描結果 | 限制 |
| --- | --- | --- |
| Frontend runner／builder | 所有嚴重度0筆 | 不是其他平台或絕對零風險保證 |
| Backend runner | High0/Critical0；Medium50/Low9 | 有中低告警，不能說所有等級皆0 |
| Backend builder | High127/Critical5 | linux-libc-dev／linux source package適用性未定，不等同正在執行有漏洞核心 |

先前程式碼Bandit的3個FTP High有既有精確人類接受；不能將「已有接受」改稱
「沒有風險」。CLI驗證仍缺證據，程序終止遇權限拒絕；12個run-owned暫存映像
尚保留。排除週邊不會自動補足這些應用驗證／執行保護缺口。

## 已確認的驗收選擇

確認延續先前指示：**只處理High／Critical，未處理者為0；既有有效接受明列；
Medium／Low不擴修**。這與要求所有嚴重度零告警不同，也不可能承諾絕對零風險。

書面計畫見[APPLICATION-SECURITY-PLAN](CHG-301-R2-APPLICATION-SECURITY-PLAN.md)，
只包含應用修補／精確適用性判定／工具安全診斷與必要
驗證清理；依AGENTS.md取得Gate4計畫核准後執行。不沿用舊廣泛計畫
繼續修週邊、不自動推PR／部署、不重試權限拒絕或解除資源限制。

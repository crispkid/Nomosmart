# CHG-421：真 OIDC 測試映像未過掃描的原因

2026-11-07；唯讀根因／方向說明，尚非新映像建置計畫。原CHG-421核准仍有效；未啟動任何IdP／LDAP／應用服務，未呼叫模型或修改8443。

## 已確認的真實結果

固定官方Dex v2.46.1 distroless的linux/arm64映像 `sha256:b394e696bf8c890603724927f86c1c81ffee28bf8279beaaea1c7abc5cb3cf1b`，用已核對工具摘要與當日有效DB實際掃描：24 HIGH、25 MEDIUM、2 LOW、3 UNKNOWN。27個HIGH／UNKNOWN發現列對應22個不同advisory；原掃描完整保留，不把重複套件列誤稱成27個獨立漏洞。

| 位置 | HIGH／UNKNOWN | 查明原因 |
| --- | --- | --- |
| 真正Dex執行檔 | 3／1 | go-jose/v4 v4.1.5、x/net v0.59.0仍在受影響版本；x/crypto v0.57.0有OpenPGP advisory的UNKNOWN。不能把全部發現都歸為沒用到的工具。 |
| 額外gomplate執行檔 | 21／1 | 其獨立靜態Go程式帶較舊Go標準庫及其他依賴，即使Dex主程式更新，這些版本也不會跟著被換掉。當前測試不需設定樣板預處理，但目前官方映像仍有這個檔。 |
| CA套件 | 0／1 | ca-certificates 20250419，掃描記錄修補20250419+deb13u1；UNKNOWN維持UNKNOWN，沒有足夠資料可直接宣稱不受影響。 |

上游go-jose官方advisory確認<=4.1.5受影響，v4.1.6修補；涉及解析不可信RSA JWK時的資源消耗。這可解釋版本發現，不代表已在本測試環境證實可利用。[上游說明](https://github.com/go-jose/go-jose/security/advisories/GHSA-mgcc-cww5-fp2q)

Go官方資料將GO-2026-5932限定到舊OpenPGP套件；目前未做本映像的實際可達性證明，因此不把原UNKNOWN自行改成安全。[官方資料](https://vuln.go.dev/ID/GO-2026-5932.json)

## 建議方向（待人類確認）

只針對測試IdP另建最小映像：以固定官方Dex來源，修補上述Go依賴與CA來源，不攜帶測試不使用的gomplate；不修改Dex認證規則、不放寬TLS／權限、不更動NomoSmart產品或四組已驗交付映像。公開來源、修補差異、工具鏈、摘要、掃描與資源清理須寫入具體補充計畫；新掃描合格後才能跑原六項拒絕，不因重建而重跑已過業務。

這是建議，不是已完成修補或保證下一次掃描通過。沒有下載另一個映像、修改上游或啟動有發現的映像。

## 為何需要確認新增範圍

已核准[CHG-421計畫](CHG-421-REMAINING-CLOSURE-PLAN.md) §A 明定：「不自動下載另一個版本／自行改上游來繞過」。所以修補上游測試映像超出這次固定官方映像清單，不能借一般工具修正自行進行。依[AGENTS.md](../AGENTS.md)：「Do not write a development plan until the human confirms this understanding」，先確認方向後才寫具體補充計畫。其餘已核准的公開材料、來源比對與簽名工作繼續。

原件：本輪 `.artifacts/chg421-8e09c944/security/actual-IdP-vulnerabilities.json`、`IdP-preflight-result.json`、`IdP-blocking-finding-inventory.json`，包含實際scan command／PID／wait／exit與摘要。這是新測試前提受阻，沒有因此把NomoSmart四組映像原零HIGH／CRITICAL改成失敗，也不把OIDC缺證改為通過。

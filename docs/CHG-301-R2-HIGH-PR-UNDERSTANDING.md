# CHG-301 R2：僅高風險修正後更新 PR — 範圍理解

後續狀態：Peter已於2026-09-16明確核准HIGH-PR-PLAN的Gate4；以下保留原Gate1/2
討論歷史。執行結果見[結果](CHG-301-R2-HIGH-PR-RESULT.md)：247項必要回歸通過，
高風險映像修補未完成，PR未更新。未新增風險豁免或擴大核准範圍。

2026-09-16 Asia/Taipei。這是 Gate1 理解／討論紀錄，不是開發計畫或建置核准。
Peter最新指示：「僅處理高風險項目，其餘項目都略過，處理完後就處理PR」。
2026-09-16 Peter對下述唯一確認問題回覆「同意」：Gate 2 confirmed。
完整兩端coverage與Kubernetes實測可暫緩，高風險修正與必要同來源回歸通過後
先更新原PR，明列未完成驗證；不合併、不部署。新Gate3計畫見
CHG-301-R2-HIGH-PR-PLAN.md；該書面計畫的Gate4仍待核准。

## 1. 理解與既有證據

- 高風險包含 High 與 Critical，不只High。先使用已保存的逐映像原始severity；
  另外納入已知containerd Critical補充公告GHSA-p7v4-vr35-mj6f。
- 原node59帳列中50項為High/Critical；12個額外映像有170個高風險映像×ID帳列。
  合併去重為83個原始ID（不含上述補充公告），不是83個已證實可利用漏洞。
- 嚴重度與適用性分開。原node仍有25項High/Critical的適用性未確定；不能因為
  INDETERMINATE就把它當Medium/Low略過。必須修補、證實不適用並依範圍確認，
  或如實列為未完成，不能直接寫FIXED。
- Medium／Low／Unspecified不主動修補或繼續逐项研究，標DEFERRED_BY_SCOPE並保留
  raw/SBOM/來源／日期；不是已修復、正式豁免或已證實安全。修補共同套件順便
  消除低severity可記實際结果，不為低severity額外擴張工作。
- 不只修外層node；涵蓋既定啟用預載映像及CNI/Ingress中高風險項。
  不藉機修改業務API／權限／SQL／現行部署，不擅自升版或fork Kubernetes。
- 最新證據：docs/CHG-301-R2-NODE-QUALIFICATION-EVIDENCE.json。
  舊1個失敗是activeapproval測試契約，不是可默默刪除的資安告警；必要回歸的
  歷史核准／當前拒絕需正確區分，不能放寬guard或偽造全套PASS。

## 2. PR語意與已確認項

2026-09-16唯讀GitHub核對：PR #1仍OPEN、非draft，title
`Fix/compose method1 installer`，head `fix/compose-method1-installer`，base `main`，
headSHA `c261a494283835af57c0e0678afc7ee7e2c0dcc8`，mergeStateStatus=CLEAN，
statusCheckRollup空。CLEAN不是測試通過；未做任何GitHub寫入。
URL：https://github.com/crispkid/Nomosmart/pull/1

「處理PR」建議限定為更新原PR分支與驗證說明，不合併、不直接push main、
不force-push、不發布或部署；推送前重核remote SHA，保留他人變更。

**已確認：高/重大風險修正與必要真實回歸完成後，是否暫緩完整兩端coverage及
Kubernetes實測，先更新原PR，並在PR明列這些未完成驗證？**

- 建議：先更新供review的PR，不宣稱release-ready／完整驗證完成，不合併部署。
- Peter已同意此有限review檢查點；只替代CMPVERIFY-006的完整coverage／Kubernetes
  前置條件，不把這些未完成項變成PASS或免除合併／發布門檻。
- 80%設定、測試檔與安全檢查不為了通過而降低或刪除；延期是揭露缺口，不是PASS。

## 3. Gate 2 已確認，Gate 4 待核准

§10.58 CMPHIGH-001..004：高風險邊界、保留未處理證據、有限PR交付與執行範圍。
Gate2不啟用修補／建置／容器／PR寫入；現有靜態Gate4不能替代新計畫核准。
原批次2026-09-15T20:17:52.088462Z期限不自動重設。新計畫已明訂有界修補、
必要測試、映像／材料、資源與新工作窗口，提交Gate4核准，未開始執行。

本輪只有唯讀盤點、GitHub metadata與理解／規格草案；沒有新掃描、修補、
featuretests、imagebuild、runtime、Provider、Git提交或PR更新。

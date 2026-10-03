# CHG-310 design archive

舊版品牌探索與 v1–v4 海報的可逆歸檔。原始路徑、位元組數、原始及歸檔 SHA-256、保留原因見 [manifest.json](manifest.json)。PNG/SVG 位元組保持原樣；四份舊海報 HTML 僅更新圖片相對路徑，繼續引用 `design/poster/assets/` 的原始素材。

目前 branding-v3、v5 海報與兩份 UX 原型保留原路徑。還原時依 manifest 移回原始路徑，HTML 將 `../../../poster/assets/` 改回 `assets/` 後，檢查 original_sha256。這次歸檔不會節省總儲存空間，也不會清除 Git 歷史。

# CHG-422：保留已發布基底，整合設定改版及六項收尾

2026-11-09。Peter 對具體版本衝突回覆「採用建議：保留 v0.2.3 功能，整合設定改版後續驗」。結合原直接執行六項指示，這是建議整合方向及後續執行的明確授權；同範圍實作與最小補驗直接進行，不重複要求相同核准。Gate1 COMPLETE、Gate2 CONFIRMED、Gate3 WRITTEN、Gate4 APPROVED。發布／push／8443切換仍不在授權內。

## 基線與理解

以已發布且已實際驗證可信簽章／全包原件的 v0.2.3 commit `9b3638a712c55b2611d61266fc5c589b2f96a423` 為基底。既有 LLMOCR／OCRSIM 原生整份PDF、純文字直接讀取、不可變付費收據、文件控制、預算、權限、PROTAUTH及CHG-419風險導向v5均保持。整合 Peter 已核准 SYSUX-001..023 的設定改版與仍適用修補，不整批用舊工作區蓋掉已發布程式。

先前本輪稱CHG-393的資料與候選原件保持；已發布歷史亦有同號393，本整合使用未占用422，兩邊舊編號與已簽原件不改寫。舊本機候選e5da713僅為當時工作區驗收來源，不是0.2.3升級資格。

## Requirements / Design

- REL422-001：保留已發布基底／歷史驗證。以同一既有worktree建立codex/整合分支；舊e5da713分支、原主工作區及兩份歷史保持。不重解釋已發布v5或v4，不採用本輪先前另一套v5草稿。保留已發布可信簽署與真quality policy、case review、完整分母／coverage量測。80%為改善目標；必需功能／未知風險仍阻擋。資安只NomoSmart本身，備份排除，production多主機HA／容量／網路資格仍延期，production_ready=false。
- REL422-002：整合SYSUX。七分類與順序、淺色側欄、卡片標題區隔、垂直單欄、至多兩層、API Key獨立、搜尋定位／草稿保護、identity共用解鎖及既有權限維持。以三方比對提取設定差異，逐衝突依SYSUX和已發布NativeOCR決定，不回復退役parser。模型表單保留已發布原生PDF能力及其進階JSON一致性。
- REL422-003：參數契約與真生效。保留已發布GET欄位／原生budget policy，再增加SYSUX分區revision、default、metadata、部署上限。PATCH只改該區；同區CAS／A→B→A／跨區互不覆寫／無效輸入零寫入；相容PUT同時驗兩區revision及既有OCR hash，缺前提428。general為timezone／form draft；documents為upload／retention／原生單次請求輸出與整份預算。已發布OCR request欄是`ocr_request_max_output_tokens`，不是重新啟用每頁parser；`ocr_page_max_output_tokens`保留既有歷史／相容責任但不成為新可編輯卡片。繁中英文同步。
- REL422-004：移轉與相容。已發布V001..V056／B054原bytes保持。新設定兩表及約束用V057；fresh依真Flyway B054→055→056→057，既有056升級057及重跑驗證，CRC／SHA／release contract一致。不加假的baseline history、不回填歷史rejection expiry。舊PUT需協調升級；回退驗收限定相同資料契約的應用／設定，較舊應用如另驗只業務唯讀且workers停用，不做DB還原／備份或宣稱任意降版可寫。
- REL422-005：原到期與正常派送。原389 job及13:35台北期限完全保持；本輪已正常生成／主管退回的新job於11月10日03:57台北到期，固定一天不改時間。保留舊producer精確來源及真使用帳務，原生化整合不重設它。新來源的排程／派送／清理callable與資料契約需精確比對；可沿用的真功能證據註明依據，不能把舊整套結果或coverage graft成新來源。未知／不同處補真驗。
- REL422-006：獨立真初始化／部署。現有自有同一組服務內增加隔離057 DB／bucket／專案，和待到期舊DB分離；不同broker/result/redis DB隔離工作。舊保留索引仍有相同有效權限，不能由bootstrap重寫共享role pattern破壞原工作。正常bootstrap／目錄同步／首位管理員登入／finalize／HTTPS readiness，真Compose及至多一個owned namespace的Helm install/upgrade/config rollback/uninstall；不動原8443／389資料／cluster全域配置。
- REL422-007：必要驗收及應用安全。沿用已發布同源有效證據，只補受影響／真正缺失項；維持原Junit的FAIL／skip／歷史缺證，不整批排除模組或製造PASS。完整量測真來源／原omit／零來源及原counter，與功能資格分開。NomoSmart依賴／自訂wheel／app build和image／secret/client設定掃描，周邊CVE OUT_OF_SCOPE_BY_USER；既有有效風險接受僅在來源／期限符合時沿用，新High/Critical不代接受。原生化已發布移除的Tesseract/Poppler/Bubblewrap不重新加回。
- REL422-008：最終可審閱候選。0.2.4 metadata、乾淨detached commit、雙架構app image、SHA／SBOM／license、真新舊schema及部署／critical evidence一致；使用已可信operator fingerprint簽最終包並做真驗簽／篡改拒絕。不得借先前候選／0.2.3簽章冒充0.2.4。必要憑證僅既有私有設定／GPG stdin，不入source/argv/env/log。最後發布另確認。

## 執行、資源及界線

同一個private run UUID c3074f88-f75d-49cb-90e9-0cece4464e12與同一owned測試stack／受限3CPU4GiB builder、唯一worktree延續；不再另造第二組周邊。新422 successor lease於本次授權後建立，終點為已存在新job到期＋15分鐘，從現在計小於24小時。轉交時核對CID/label/PID-start／資料和未變時間，停止並記錄舊本輪supervisor，再以新短期限接續；原393 lease不改／不重開closed grant。原389 phase和原16:30台北上界完全不動。資源僅刪本run且ID/UID一致者，0全域prune、0備份、0push。

先比對／凍結來源和細項設計，再在已有唯一worktree整合；以已發布API與DDL為底，採最窄有效修補。原主工作區不reset/clean/stage。所有真測試在隔離services，無mock／fake JWT／模型輸出／成功seed。模型僅必要已核准合成文件：Chat/OCR/Judge Luna6，Embedding專用；已有金鑰與額度沿用，不重問。

## Test Strategy / Handoff

檢查舊移轉逐檔不變、NativeOCR/v5相容、SYSUX native parameter／真API CAS／權限／upload／時間與保留快照，真瀏覽器七分類／草稿／定位／native模型表單；真fresh/056-upgrade、bootstrap/readiness與本機生命週期。原有效結果按來源／assertion對應沿用；先前8個舊parser測試只保留為當時框架結果，退役或仍有效的責任按已發布NativeOCR逐項分帳，不重加工具掩飾風險。

spec:doctor、spec:trace、plan:approved、test:plan與相關frontend lint/build/i18n、backend syntax、真services API/E2E／量測、docker:config、helm:lint、deploy:config-policy、應用offline scan/SBOM/license、可信包驗證與自有cleanup。保存每個原始退出碼／來源／時計／image／沿用與未知項。最後集中列六項狀態、真自然到期、工具修復、殘餘風險、下載產物與僅真正需要的確認；不以量測或metadata當功能完成。

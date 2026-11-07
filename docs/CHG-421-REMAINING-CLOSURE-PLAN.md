# CHG-421：剩餘 OIDC 與最終簽署包合併收尾計畫

**要交付：**沿用 CHG-420 的29個合格情境，只補 OIDC 六項拒絕與最終 v5 簽署／查驗。完整成功後，才交「可供最後發布審查」的本機候選；這次不對外發布、不切8443。

## Status and Gate / Specification Understanding / Human Confirmation

Gate 1 COMPLETE；Gate 2 CONFIRMED。Peter於2026-11-07回覆「同意繼續完成剩餘的項目」，確認新增隔離 OIDC 測試方向及剩餘交付範圍，權威 `docs/CHG-421-GATE2-CONFIRMATION.json`。Gate 3 WRITTEN。

Gate 4 implementation approval: PENDING。

本份合併計畫把必要資源、兩個真issuer實例與原安裝環境封閉後的查驗差異一次列清。核准前只唯讀規格／來源／官方登錄資訊與文件檢查；未下載映像層、掃描新映像、啟動服務、登入、簽署或功能測試。

## Scope / Discussion and Confirmation Items

既有29／31情境、四映像／SBOM／安全、同一PDF全鏈、78表回復與原資料保持沿用。不重跑 Compose／Helm／AD／PDF矩陣、不補覆蓋率比例、不呼叫模型。原 FTP 接受有效範圍、歷史缺證、有限憑證結案與正式平台延期不變。原420資源已正常封閉，不重開舊scope。

本計畫核准同時包含三個明示細節：①同一新官方 Dex 映像的主要／外來issuer兩個實例，第二個僅用於真發行者不符控制；②先對公開材料清單簽名、再對真正新v5包簽名，兩種purpose分開；③最終包以原真Helm收據＋逐檔來源對照及當次Docker唯讀查驗銜接，**取代**原420要求簽署後仍在同一Helm namespace做live inspect。原namespace已不存在，因此不宣稱簽署後又驗過該Helm，不另裝一次來湊收據。這些是本次具體核准的差異，不能由原420核准倒推。

## Diagnosis / 根因與最小解法

1. **OIDC缺證**：舊真Dex正常登入可重用，但不能代替錯issuer／audience／nonce／state／PKCE／replay的拒絕。現行產品已有對應嚴格驗證，沒有已證實的產品漏洞；缺的是取得真issuer與真正負向輸入的前提。
2. **錯issuer要能驗到正確分支**：只改設定中的issuer會先被Discovery拒絕，不能宣稱驗到ID Token issuer。新增同一映像的第二個真issuer，使用明確token_url／jwks_url運輸設定及同一真state／nonce／PKCE，把第二個IdP實際簽出的Token交給期待第一個issuer的產品，應在有效簽章之後拒絕錯issuer；不偽造JWT或攔截成功回應。
3. **錯audience同理**：Dex官方支援 `trustedPeers`／`audience:server:client_id:...`。以真跨client授權取得audience不同的Token，產品應在ID Token驗證階段拒絕，避免把client-secret或授權碼錯誤誤算audience拒絕。[官方說明](https://dexidp.io/docs/configuration/custom-scopes-claims-clients/)。
4. **簽署／驗收相依**：v5組包前要求品質就緒，而包完整性情境又包含簽章。以獨立「材料來源簽名收據」先證明既有key對真來源／映像／SBOM／原安裝與回復材料的簽名可驗，不改原測試包、不製造已簽署發布包的假結果。之後31情境都有真證據，才用原嚴格v5流程重新組包、簽署並驗最終包。最終成功另存包外收尾收據，避免把尚未產生的本包摘要預填進本包。
5. **安裝查驗時間界線**：420的真安裝／一般管理員finalize及verify在環境清理前成立；保留這個時間／UID與原始退出，最終只證明相同runtime／chart／SQL／映像來源，不能從舊capture推論現在仍Running。新Docker只補認證與最後來源檢視，不做第二套安裝驗收。

## Development Plan / Approach / Task Breakdown

### A. 先凍結原件與輸入，再取得合格測試映像

凍結420原31清單、29合格proof、source `835280269010fb90962ef31f088b928a9931196f`、四映像／兩個索引／帳務／DB OID。官方候選為 `ghcr.io/dexidp/dex:v2.46.1-distroless@sha256:db30f7d5bcc837e8b903209a3783c751f38f480309833ec906010918ff6c4002`；按Docker真平台只取一個已列leaf，核對後用既有鎖定Trivy與有效DB掃一次。未處置HIGH／CRITICAL、scan unknown或失敗不得啟動IdP；不沿用舊Dex的風險，也不自動下載另一個版本／自行改上游來繞過。此時其餘可獨立公開材料整理繼續，缺證仍保留。

官方版本／登錄只作真來源證明，不能保證零漏洞。[官方版本原件](https://github.com/dexidp/dex/releases/tag/v2.46.1)。既有35 HIGH的舊Dex不啟動。規劃期只查manifest，尚無本次映像掃描結果。

### B. 一組順序Docker應用槽，六項真正拒絕共用成果

沿原420兩個DB及414 LDAP，建立本輪私有Docker網路與同源API／Frontend／TLS edge，Worker／Beat不啟動。新增主IdP與只供issuer控制的外來IdP；同一固定映像，合計0.5CPU／512MiB。端點／CA／callback／client設定均為測試輸入，保留HTTPS與CA／hostname驗證，不改系統hosts／信任。

LDAP僅唯讀搜尋及user bind。選已同步正常管理員，先核對fixture中的employeeNumber與app employee_id唯一一致；Dex `preferredUsernameAttr=employeeNumber`，以明確immutable employee_id政策映射，不用mail猜人、不增使用者或改目錄。若資料不符，不自動新增／改造人員。參考[Dex LDAP屬性與TLS](https://dexidp.io/docs/connectors/ldap/)。

只在自有app副本準備新測試認證設定／client／必要穩定身分連結；配置是測試輸入，不把seed狀態或直接SQL當驗證／啟用／登入成功。保存原設定列與密文摘要，測後精確復原。真flow、cookie、session、candidate proof、audit都必須由產品實際產生，不預填success。原restore庫只讀；父庫／8443不連入寫入。

| 控制 | 最少真實操作 | 必要證明 |
| --- | --- | --- |
| 正常前提 | 一次正常LDAP背書的真OIDC code flow，取得可登入session，供之後replay共用 | 真/me、既有角色；不是重跑正常矩陣。完成後正常logout，避免已有session掩蓋拒絕。 |
| state | 真flow與真code，callback僅帶不同state | 安全拒絕、無新session；不是任意假code觸發泛用錯誤。未消耗的原flow可供必要正常前提共用。 |
| issuer | 主Discovery合法，真外來IdP發碼／簽名，明確token／JWKS transport指向外來IdP | 產品實際 `id_token_validation`／InvalidIssuer拒絕；另沿現行Discovery相等檢查，不能以先前metadata錯誤代替。 |
| audience | 主IdP兩個真client及限定trustedPeers，請求真跨client audience | 實際Token驗證／InvalidAudience拒絕，不算client認證或code失效。 |
| nonce | 保留真flow／cookie／PKCE，只改送到真IdP的公開nonce參數 | IdP真Token的nonce與產品flow不符，實際Token驗證拒絕。 |
| PKCE | 保留真state／nonce，授權請求只改公開challenge，產品仍用原verifier交換 | 真IdP token endpoint拒絕；產品不建session、不重送同code。 |
| replay | 使用已完成並真正消耗的正常flow／code，再走一次callback | 產品state一次性拒絕，正常logout後不得恢復session；不以fake clock或直接seed consumed_at代替。 |

使用真HTTP driver，敏感URL／codes／tokens／cookies僅記憶體。保存有限狀態、DB flow消耗／session增量、去敏audit stage／cause type及來源／程序wait，不存原始credential或IdP登入表單／trace。錯誤類別不符先修工具／前提，只續失敗或受影響項；已過項不重跑。若發現真產品違反既有規格，先記根因／spec/change/readset，限修必要原呼叫點；新行為或安全例外不自行決定。

### C. 原真Helm收據與新包逐檔銜接，不重新安裝

新增共用唯讀比對工具：讀真420未驗收測試材料的完整清單、真installed值／Pod映像／namespace birth UID、原protocol install/finalize/verify／清理時間與真restore結果，核對最終新包runtime檔、chart、SQL及指定映像逐項相同。來源不同只可列明公開release工具／測試／文件差異；不能放過runtime改變、錯UID／錯映像、缺capture／雜湊。

只做一個真原件正例與兩個明示錯配副本拒絕（錯映像、錯UID/capture）。原始capture不改；輸出明示 `live_namespace_revalidated=false`、原安裝時間與原UID。最終包再做檔案檢查及當次Docker實際掛載／映像／原始應用來源與正常OIDC session的最小唯讀檢視，沿用本輪登入成果，不新增一次登入／審核／模型。

若最終包runtime實際不同而不能證明，保留缺口，不能藉文案接受變更。增加第二次Helm install不含本計畫。

### D. 公開材料簽名、真正v5簽名與最少拒絕控制

先建立一份有限公開材料JSON：明示 `purpose=local-material-source-attestation`、`release_qualified=false`，含clean公開candidate來源、runtime清單／chart／SQL、四映像摘要與SBOM、安全／真安裝／回復證據的雜湊。沿既有可信key `B2FF91C91CF22E60D898C9061A4757FCA7F23B66` 真detached-sign並驗簽；只對一份修改後公開清單副本做拒絕控制。它是來源簽名收據，不是已驗收發布包；原測試包manifest／archive／pending gates都不改。

材料、六項OIDC及其他29項的真proof齊全後，依相同31政策更新品質／測量／回歸統計。已查明的「本輪完整suite未執行」與明確尚待finalization不冒充未知產品故障；真正未審／不明或重要拒絕缺證仍阻擋。原119失敗、669／1850／2576與原counter保持，不改算PASS。

以原 `assemble-reviewed-local` 流程從新clean、detached本機來源組裝真正v5；19gate必須各自有真執行或精確合格重用，不生成空passed收據、不更改v5／v4必要條件。候選source僅於自有公開候選目錄提交，明列差異，不動使用者git狀態／遠端tag。不因新增release工具而重建產品映像；先核對actual Docker COPY與原393／174公開輸入。

真簽署後用既有信任fingerprint查驗最終包，另以一個真payload檔篡改副本確認拒絕，確認未驗測試包／錯purpose不能被接受。source／digest／checksum／SBOM／資料保持／原件閉包及C節對照全部成立後，另存指向最終manifest、包archive與簽章摘要的包外收尾結果。內部preassembly品質就緒不等於最終包完成；**只有這個最後真查驗成功才報可作最後發布審查**。

若GPG要求Pinentry，先保留具體待簽bytes／摘要，只請Peter完成本人操作；不讀／代填passphrase、不換測試key、不匯出private key。一般工具問題依已核准範圍直接修，只重驗受影響控制。

### E. 最終對帳、正常收尾

停止本輪登入後撤銷own session／flow，復原app副本原認證設定、保留新audit及原付費資料；停回LDAP。依label＋birth CID精確移除本輪五個容器／網路、tmpfs與轉送／監護後代，逐個wait。兩DB、八筆用量、S3／兩索引／圖投影與回復材料保留，不作整庫drop／prune。收尾先於期限；沒有未知資源就不碰。

最後只做文件守門、完整來源量測資格與readiness；不產生新counter或全套重跑。保持 `production_ready=false`、平台未資格與未授權發布。只有全部必要條件滿足才結案；否則具體列明剩餘原因／owner，不能把缺證包裝成可發布。

## Exact Resources / Deployment and Configuration Impact

operation `8e09c944-c5d1-4aaa-b0ec-dd5ed51893c2`；精確清單 `CHG-421-RESOURCE-PROPOSAL.json`。

- 0新DB、0namespace／Helm install、0模型；既有app OID31814及restore OID31815與受保護父庫保留。測試IdP用各自tmpfs SQLite，不另開資料庫服務。
- 主要／外來IdP兩個實例使用同一固定官方映像，只需現在Docker native平台，合計0.5CPU／512MiB；連同API／Frontend／edge／既有LDAP最高4.25CPU／4352MiB，原總6CPU／8GiB不增加。主／外來client與issuer不同，無共用session／cookie成功路徑注入。
- 每個新階段開始即凍結最多120分鐘期限，最後10分鐘只清理，閒置30分鐘停app；服務替換先stop／wait再同名建，不併行加開環境或重開420。無新增測試次數／費用總額限制，但每次續驗須有具體新原因，不能盲重送。
- 只綁空閒loopback18520；DNS別名只在本輪Docker網路；不改8443、19443／19444、全域CA／hosts、共享ACL／原密碼。測試設定／TLS private／bind秘密只限既有單欄位記憶體→正常runtime或container tmpfs，不建額外host明文備份。

## Test Strategy / Verification Commands / Traceability

`C421-T01..06` 的精確行為見CASE-PROPOSAL；六條規格 SIGNCLOSE-001..006 對應相同順序。只新增共用OIDC真服務driver與唯讀材料簽名／來源比對工具，路徑及before hashes見SOURCE-PROPOSAL；產品OIDC／sessions、policy31、v4/v5主要validator、installer live verify與Dockerfile預期不改。

規劃只執行 `spec:doctor`、`spec:trace`、`plan:doctor`、`test:plan`；`plan:approved`必須以421仍PENDING拒絕。核准後只新增路徑syntax及上述實際小控制、真六拒絕、材料／最終簽名查驗、最後coverage:check／release:readiness。新映像只掃一次同摘要；新release工具才做直接靜態檢查，不重掃未改應用／不重建四映像／不重跑部署成功矩陣。必要來源資格更新只重算雜湊，不創造命中。

## Risks / Rollback / Acceptance

風險是負向測試停在錯誤層、讓舊capture冒充現在環境、簽名收據誤當發布包、重複計費或清理錯資料。以上分支cause／原時間UID／嚴格purpose／0模型／birth-ID及帳務保護是必要守門。新HIGH／CRITICAL風險不由本計畫自動接受。

回復只撤本輪test config／driver及release工具變更，原420原件／候選／資料保留，8443不變。交付真OIDC分支證據、兩種簽名各自身份、最終包與原安裝同源對照、規格／量測／原suite分帳、最終真查驗、清理／保留帳。未驗材料與歷史缺證始終保留原身份。

依[AGENTS.md](../AGENTS.md)：「do not implement or run feature tests until the human approves the development plan」。Gate2方向已確認；現在只需本份具體合併計畫及三提案的Gate4核准，普通同範圍工具問題不再逐項詢問。

# NomoSmart 登入與目錄管理（認證契約 2）

CHG-363／PROTAUTH-001..012。一般登入選 **OIDC** 或 **LDAP／Windows AD**；使用者、群組及目錄狀態均直接由一個 LDAP／AD 來源同步。NomoSmart 管理自己的角色和專案權限，不需要任何 IdP 的管理 API。

## 先準備什麼

- 一個目錄、唯讀同步帳號、使用者和群組的搜尋範圍、正確的 CA 公開憑證。不要提供 CA 私鑰。
- 每人和每個群組的固定識別碼。一般 LDAP 用 entryUUID；AD 用 objectGUID。DN 和 email 不能取代固定識別碼。
- 一個真正的目錄管理群組，首次安裝時將它映射至 system-admin。請填群組固定 ID，不是群組名稱。
- OIDC 模式另需 issuer、client ID、明確的用戶端驗證方式，以及可驗證的 auth_time／重新登入能力。需要密鑰時，由受限 Secret 提供。
- OIDC claim 必須能對上目錄固定 ID；或由管理員明確綁定 issuer＋sub 到已同步的人員。員工編號只有在企業保證唯一、不重用時才能作共同欄位。

一般 LDAP、AD、OIDC 範例分別在 deploy/docker/auth-bootstrap.example.json、auth-bootstrap.ad.example.json、auth-bootstrap.oidc.example.json。它們只有示範值；替換來源 UUID、主機、DN、CA reference 和管理群組 ID。既有來源 UUID／類型在初始化後不能任意更換。AD 範例是配置說明，**本次尚無真 AD 環境，不能視為已通過 AD 驗收**。

## 設定檔與欄位位置

| 用途 | Compose主機端設定 | Backend原始碼開發設定 |
| --- | --- | --- |
| Bootstrap JSON路徑 | `AUTH_BOOTSTRAP_CONFIG_FILE` | `AUTH_BOOTSTRAP_CONFIGURATION` |
| 公開CA目錄 | `AUTH_CA_DIRECTORY` | `AUTH_TRUST_ROOT` |
| 前版加密keyring | `AUTH_PREVIOUS_KEYS_FILE` | `AUTH_ENCRYPTION_PREVIOUS_KEYS_FILE` |
| 真Bind／OIDC秘密 | `DIRECTORY_BIND_PASSWORD_FILE`／需要時的`OIDC_CLIENT_SECRET_FILE` | 同名`*_FILE`，指向本機私有檔 |

Compose主機路徑會映射為容器內路徑；不要把主機端欄位直接當Backend Settings。Helm以`authentication.*`、bootstrap ConfigMap與runtime Secret提供相同資料。[Backend範例](../backend/.env.example)、[Compose範例](../deploy/docker/nomosmart.env.example)及[Helm values範例](../deploy/installer/protocol-values.example.json)分別適用不同路徑。

一般deployment bootstrap讀整個範例JSON（`configuration`加`admin_group_id`）。若直接使用`protocol_bootstrap initialize --configuration`，該檔案只包含內層configuration，管理群組另用`--admin-group-id`提供；兩種輸入不要混用。`admin_group_id`必須是真群組固定ID。

## OIDC 要在認證服務設定什麼

使用 Authorization Code＋PKCE S256，並登記精確 callback：

```
https://YOUR_APP_ORIGIN/api/backend/auth/oidc/callback
```

一般登入、設定重新驗證與候選登入共用 Backend callback，由伺服器的一次性 flow 區分用途。不要沿用舊 /auth/callback 進行 code exchange。支援 public client、client_secret_basic、client_secret_post；選定方式必須存在於 Discovery。Issuer 必須精確相符，使用 HTTPS，不能停用 TLS 驗證。自訂 discovery／token／JWKS 內網位址必須明確配置、通過部署 allowlist 且使用同一 issuer；不能把舊服務的內網位址帶到新 issuer。

不要求 Keycloak realm、mapper 或 service account。Keycloak 與 Dex 只是本次使用的兩套協定測試服務。Refresh、silent SSO、上游登出目前公開能力均為 false；本地登出會立即撤銷本地 session。

## Docker Compose 安裝順序

1. 依 deploy/docker/nomosmart.env.example 建立未提交的配置，準備基礎設施 Secret、HTTPS、auth bootstrap JSON 與 CA 目錄。AUTH_ENDPOINT_ALLOWED_HOSTS／CIDRS 只放真正核准的主機或網段。
2. 執行既有 migration 服務，目標為 054；全新資料庫可用 B054，既有資料庫套 V054。先停止舊版登入／同步 producer 和 worker，再協調升級前後端與 worker。
3. 執行 deployment-bootstrap（ensure）。它會真讀目錄、同步並綁首位管理群組；onboarding 入口必須限制管理員來源 IP。
4. 讓同步後的一般管理員從網頁登入。OIDC 管理員另須完成「驗證身分並編輯」。
5. 執行 deployment-finalize，再把部署階段改為 operational，驗證 readiness。Emergency 不能代替一般管理員登入驗收。

原資料庫中的 user UUID、角色及歷史保留。舊 keycloak_user_id 作 nullable 歷史欄位，沒有真目錄證據不會猜測移轉配對。需要移轉既有人員時，使用 initialize 的 --migration-bindings 明列內部 user_id、directory_object_id。詳細格式與指令以 CLI --help 及程式輸入驗證為準。不要把原始部署密碼貼到對話或寫入 Git。

Compose與Helm已移除整個Keycloak部署組件，包含選用profile、Theme、入口、產品專屬Secret、DB帳號／資料庫初始化及網路／容量規則。PostgreSQL只初始化NomoSmart所需帳號。外部OIDC服務由企業另行管理，仍可選任何符合支援條件的實作。

## Helm 與安裝工具

使用同一安裝工具的 `--protocol-config` 路徑，範例：deploy/installer/nomosmart-install.protocol.example.toml。設定明確 context、owned namespace、release、installation UUID、非秘密 values JSON 和 chart 目錄。這個路徑使用 operator-managed external services 與既有 runtime Secret，不建立或管理 IdP。

依序使用 plan、install（中斷可 resume）、一般管理員登入、finalize、status／verify。各指令帶相同 --protocol-config。先用 CLI --help 確認命令位置。install 會停在可登入的 onboarding；finalize 以資料庫真實 session 與同步證據檢查，不能用固定成功資料跳過。

authentication.bootstrapConfiguration 使用範例 JSON 的整個物件；endpointAllowedHosts／Cidrs、caSecretName、encryptionKeyId 等由 values 提供。runtime Secret 應包含既有應用 Secret，以及初次 bootstrap 的 DIRECTORY_BIND_PASSWORD、必要時 OIDC_CLIENT_SECRET。這兩個連線密碼只在 bootstrap job 讀取，日常服務改從加密資料庫讀取。Helm 的 Secret values 只允許範例或空值；正式環境用 existingSecret／外部秘密系統。

本機或受限測試網路若需要 Pod 透過 TCP 查詢 DNS，可明確設定 `podDnsOverTcp: true`（預設 false）。這只調整應用 Pod 的解析選項，不變更叢集 DNS。仍須驗證實際 DNS／網路及部署容量；本次使用有短暫中斷的維護式更新，不代表已通過零停機或 HA 驗收。

## 升級既有部署

先整理現有設定，再預覽部署差異。Helm不再接受`keycloak.*`、`global.keycloakPath`、`bootstrap.keycloak*`及產品專屬env／Secret／PostgreSQL欄位；移除這些值與`/identity`入口，使用明確的新版values，不使用`--reuse-values`帶回舊設定。所有公開values profile都已移除該組件。

日後真正套用新版Helm時，原release管理的Keycloak工作負載、Service、Ingress及產品Secret將列入刪除差異。先確認外部IdP接手、資料與憑證保管，再以完整新版values及`--reset-values`預覽／升級；本次沒有執行升級或刪除原資源。

舊版已發布SQL與身分歷史欄位保留。現有Keycloak若仍需使用，先由operator保管其資料／憑證並獨立管理；本次原始碼修改不會操作現有容器、DB或PVC。應用改接外部OIDC時，依本指南重新確認issuer、client、callback及目錄對應。

Docker設定產生器不再建立Keycloak憑證或推測企業issuer。準備真實的`DIRECTORY_BIND_PASSWORD_FILE`；OIDC需要密鑰時再指定`OIDC_CLIENT_SECRET_FILE`。這些是operator管理的私有regular檔，禁止symlink或公開權限。`AUTH_PREVIOUS_KEYS_FILE`預設只可用空JSON範例；真金鑰改用私有檔，不能填進公開範例。首次應用登入使用已同步的一般管理員，沒有固定初始登入密碼。

## 網頁怎麼改設定

系統管理 → 身分來源 → 驗證身分並編輯。解鎖只有 10 分鐘。填寫候選設定，通過真實連線檢查；若改登入模式、OIDC 識別或 OIDC 密鑰，還要以候選設定驗證同一管理員可登入，5 分鐘內套用。失敗保留有效舊設定。重要認證變更會撤銷舊登入，要求重新登入；只改同步時間不會把全部使用者登出。

密碼只提供「保留／替換／清除」，儲存後不顯示原文，使用者的登入密碼不保存。清除必要密碼的候選不能啟用。網頁不能改加密金鑰、啟用 emergency，或變更目錄的來源 UUID。

## 同步時間與登入時間

預設每天 02:00、Asia/Taipei；可改每天的時間、時區及同步範圍，也可按「立即同步」。沒有每五分鐘查目錄，也不因資料超過 30 分鐘就停止登入。目錄異動可能保留至下一次成功同步；需要立即更新就手動同步。

讀取分頁／成員資料不完整時，不發布該次快照，保留最後成功資料並告警。人工停用和目錄停用分開保存；同步不會取消人工停用。群組角色與手動角色取聯集，原專案／Owner 權限規則保留。

一般登入閒置滿 30 分鐘失效；真正在前景點擊、輸入、觸控或捲動會延長。背景更新、單純開著畫面不延長。沒有固定八小時上限。同一瀏覽器分頁共用 session，不同瀏覽器／裝置各自計時。停用帳號、登出及安全設定切換仍會撤銷登入。

## 金鑰輪替與緊急復原

加密連線秘密使用 AES-GCM，context 綁定來源、設定 revision 與用途。金鑰在部署 Secret，資料庫只有密文與 key ID。

建議獨立 AUTH_ENCRYPTION_KEY（64 個十六進位字元）。初次相容可沿用 APP_ENCRYPTION_KEY；之後改用專用認證金鑰，**不要直接輪替共用 APP_ENCRYPTION_KEY**，以免破壞其他功能的密文。

1. 暫停認證設定變更，為 API／worker／bootstrap 同步部署新 AUTH_ENCRYPTION_KEY 和新 AUTH_ENCRYPTION_KEY_ID。
2. AUTH_ENCRYPTION_PREVIOUS_KEYS_FILE 指向受限 JSON：舊 key ID → 舊 32-byte hex key；檔案需 regular file、不得 symlink、禁止群組／其他人讀取。Helm 可透過 previousKeysSecretName 的 init container 複製至私有檔。
3. 在相同部署 Secret 下執行 `python -m app.deployment.protocol_bootstrap rotate-keys`。它重加密連線秘密與仍有效 flow，可重跑。
4. 驗證真連線／登入、確認沒有仍需舊 key 的資料後才移除舊 key。失敗保持舊 key 可讀，不降級成明文。

只有部署人員可用 `python -m app.deployment.protocol_bootstrap emergency-enable --password-file /PRIVATE/NEW_FILE` 產生一次性隨機密碼，檔案需不存在；密碼不印在輸出。啟用窗口 15 分鐘，操作不能延長。完成後執行 emergency-disable；finalize 也會停用。仍有正常權限檢查、audit 和系統內告警。

`restore-last-known-good` 會驗證先前設定的金鑰、真目錄和必要 metadata，再撤銷 session／unlock 並復原設定。這是設定復原，不是資料庫備份還原；回退舊應用版本需要相容 schema／設定與協調部署，不能只換舊 image。

## 維運與驗收界線

注意最後成功同步時間、失敗 run、auth/emergency audit 與告警。Ingress／反向代理不可記錄 callback query、密碼、token 或 session cookie。必須保留 CA／hostname 驗證，不降低 AD 的 LDAP signing／channel binding 政策。

本次測試、缺口與原失敗見 docs/AUTHENTICATION-STATUS.zh-TW.md。真 AD、完整覆蓋率與實際部署驗收未完成時，不能標為可正式發布。

## 角色顯示與AD維運補充

系統使用者列表顯示API回傳的有效系統角色，同一角色合併人工／同步來源。Knowledge Owner旗標與Project Owner關係另列，不當成角色清單；沒有系統管理讀權限的回應不包含全域角色資訊。

AD維護後可由AD主機使用`backend/scripts/ad_readiness.ps1`，指定Domain、ExpectedHost及ExpectedNamingContext，先確認NTDS／Netlogon／DNS、DC discovery與RootDSE同步。選擇提供具受限ACL的CredentialFile時，再指定SentinelDn／ExpectedGuid，工具才會做一次嚴格LDAPS及身分讀回。密碼不放命令列；認證拒絕不自動重試。工具實測及範圍見[AD就緒結果](CHG-369-AD-READINESS-RESULT.json)。

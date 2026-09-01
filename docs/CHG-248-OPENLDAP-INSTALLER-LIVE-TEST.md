# CHG-248 OpenLDAP 一鍵安裝實機測試報告

> **Historical evidence — superseded by CHG-260.** This document records a retired release contract. Do not use its Vault, ClamAV, scan/quarantine, TOTP, credential-uniqueness, image, capacity, checkpoint, recovery, or acceptance instructions for a current installation. Use [`deploy/README.md`](../deploy/README.md) and Specification section 10.17.

- 測試日期：2026-07-29（Asia/Taipei）
- 需求：`DEPLOY-012` / `CHG-248`
- 變更補充：`CHG-248-LIVE-01` 至 `CHG-248-LIVE-05`
- 測試環境：ENV-UAT-001
- 測試型態：既有三節點 RKE2 上的 production-shaped fresh install、失敗續跑、
  Vault Shamir 5/3、OpenLDAP full sync 與角色映射
- 敏感資料：本報告不包含密碼、token、Vault share、TOTP seed、私鑰或 Secret
  明文

## 結論

一鍵安裝器已能從乾淨的 NomoSmart application state 完成全部九個階段：

1. `preflight`
2. `package-and-secrets`
3. `foundation-and-vault`
4. `vault-custody-checkpoint`
5. `migration-bootstrap-and-app`
6. `directory-integration`
7. `totp-checkpoint`
8. `operational-finalization`
9. `verification-receipt`

第六次 fresh journey 的 OpenLDAP full sync、`user01` identity reconciliation、
`nomosmart-uat-admins -> system-admin` external role mapping、Migration Job、
Bootstrap Job、Vault 3/3 Raft 與全部 application workload 均成功。
目錄階段亦已確認：若 `user01` 尚無 OTP，installer 會冪等加入
`CONFIGURE_TOTP`，但不接觸 TOTP seed。

人員已分別完成設計中的 `totp-checkpoint`：

- OpenLDAP `user01` 的首次 OIDC 登入與 TOTP enrollment。
- Keycloak-local break-glass `nomosmart` 的首次改密與 TOTP enrollment。

安裝器隨後以 `resume` 完成 operational finalization，並以獨立 `verify` 再次
驗證實際叢集與公開端點。因此本次結論是：

- OpenLDAP 安裝、同步、群組映射：**通過**。
- Vault Shamir 5/3、bootstrap、root-token revoke：**通過**。
- Application、Migration、Bootstrap、公開 HTTPS：**通過**。
- 無人值守從零到完成：**不適用**，TOTP 與 Vault custody 本來就需要人員互動。
- TOTP、finalization、最終 operational receipt：**通過**。
- 服務狀態：**保持運行，供後續 UAT 使用**。

## 測試目標與固定輸入

| 項目 | 測試值 |
|---|---|
| Kubernetes context | `default` |
| API Server | `https://10.168.1.163:6443` |
| Cluster UID | `b68c2266-7275-424f-a4f6-277297a7c129` |
| Ready nodes | `nms-uat-rke2-01`、`02`、`03` |
| Namespace / Helm release | `nomosmart` / `nomosmart` |
| Public URL | `https://nomosmart-uat.ctbclab.com` |
| OpenLDAP URL | `ldaps://ldap.ldap.svc.cluster.local:636` |
| LDAP base DN | `dc=ldap,dc=ctbclab,dc=com` |
| Keycloak LDAP vendor | `other` |
| LDAP group path | `/ldap` |
| Designated admin | `user01` |
| Admin group | `nomosmart-uat-admins` |
| Vault | bundled、Integrated Raft、Shamir 5/3 |
| StorageClass | `longhorn` |
| Ingress Controller | `kube-system` / `rke2-ingress-nginx` |

開始 fresh journey 前，`nomosmart` Namespace 只保留三個既有輸入 Secret：

- `nomosmart-directory-bind`
- `nomosmart-directory-ca`
- `nomosmart-registry`

OpenLDAP server、`ldap` Namespace、OpenLDAP PVC 與 LDAP directory objects 沒有在
NomoSmart fresh journey 中刪除或重建。

## 第六次測試的主要成功證據

### Installer state

- Helm release revision：`5`
- Helm status：`deployed`
- 完成階段：全部九個 stage
- Deployment phase：`operational`
- Pending checkpoint：無
- Verification receipt：
  `/Users/peter/Documents/NomoSmart-UAT-Handoff/installer-openldap-live/state/verification-receipt.json`

### OpenLDAP 與角色映射

Directory reconciliation Job：

```json
{
  "designated_admin": "user01",
  "group": "nomosmart-uat-admins",
  "mapping_created": true,
  "membership_source": "external_sync",
  "role": "system-admin",
  "status": "ready"
}
```

Job 使用修正版 Backend：

```text
nms-uat-registry.ctbclab.com/nomosmart/backend:
uat-openldap-d1b44d0207a4@
sha256:cf84bd7ff2f54cf92db1504312ac010d7b19d04e71449af87c3cad1203c6bdc1
```

Keycloak 實機資料證明：

- `user01.federationLink` 存在。
- Keycloak built-in DN attribute 是 `LDAP_ENTRY_DN`。
- OpenLDAP DN 可正確寫入 NomoSmart `users.ldap_dn`。
- `auth_source` 為 `ldap`。
- 外部群組衍生的 `RoleUser.source` 為 `external_sync`。

### Vault

- 三個 Pod：全部 `initialized=true`、`sealed=false`。
- Storage：`raft`。
- HA：`ha_enabled=true`。
- Raft peers：`3`。
- KV v2：`complete`。
- Audit：`complete`。
- Kubernetes auth：`complete`。
- Initial root token：`initial_root_token_revoked=true`。
- Custody output：owner-only `0600`，包含五份相異加密 share 與一份加密 initial
  root token；報告與一般 state 不保存明文。

### Application

- Frontend：2/2 Ready，分散於兩個 node。
- Backend：2/2 Ready，分散於兩個 node。
- Worker：2/2 Ready，分散於兩個 node。
- Beat：1/1 Ready。
- Keycloak、PostgreSQL、Redis、RustFS、OpenSearch、Neo4j、ClamAV：Ready。
- Vault：3/3 Ready，分散於三個 node。
- Migration Job：Succeeded。
- Bootstrap Job：Succeeded。
- Directory reconciliation Job：Succeeded。

### 公開 HTTPS

使用 installer package 的 trusted edge CA 從 operator laptop 驗證：

| Endpoint | 結果 |
|---|---|
| `/` | HTTP 200，Frontend HTML |
| `/api/backend/ready` | HTTP 200，`status=ready` |
| `/identity/realms/nomosmart/.well-known/openid-configuration` | HTTP 200，Keycloak OIDC JSON |

### Registry

原先缺少的五個私有 repository 已補推，且 remote manifest digest 與設定檔逐一
相同：

- Frontend
- Migration
- PostgreSQL
- RustFS
- Keycloak

Registry 另包含兩個 CHG-248 OpenLDAP Backend tag。第六次使用較新的
`uat-openldap-d1b44d0207a4`。

## 遇到的問題總表

狀態說明：

- `已修復`：Repository 或 UAT desired state 已修正，重測通過。
- `已緩解`：本次可繼續，但仍建議補正式改善。
- `待改善`：不阻擋目前服務，但 production installer/tooling 應再處理。
- `預期 checkpoint`：安全設計要求的人工作業，不是 defect。

最終分類為：已修復 29 項、已緩解 5 項、待改善 5 項、預期 checkpoint
1 項。該 checkpoint 已由人員完成，但仍保留此分類，因為它是正常安全流程。

| ID | 嚴重度 | 問題 | 根因 | 處置與重測 | 狀態 |
|---|---:|---|---|---|---|
| OLI-001 | High | Public hostname 一開始不可達 | MetalLB pool / public Service 曾被前次清理移除 | 重建 approved address pool 與 ingress LoadBalancer；DNS 解析至 `10.168.1.164` | 已修復 |
| OLI-002 | Medium | 已存在 Namespace 被判定有未知 ConfigMap | Kubernetes 自動建立 `kube-root-ca.crt` | Installer 將該 immutable system ConfigMap 視為允許項；existing Namespace plan 通過 | 已修復 |
| OLI-003 | Medium | Shamir preflight 找不到 `gpg` | Operator laptop 缺必要工具 | 安裝 GnuPG；PGP fingerprint/list-packet preflight 通過 | 已修復 |
| OLI-004 | Critical | 部分 workload 無法拉私有映像 | Chart 只有部分 PodSpec 套用 `imagePullSecrets` | 所有 Deployment、StatefulSet、Job 與 ancillary workload 統一套用 pull secret；Helm render/lint 通過 | 已修復 |
| OLI-005 | Critical | 私有 Registry repository 為空，但 Pod 仍能啟動 | 三節點先前有 containerd cache，造成假成功 | 補推 Frontend、Migration、PostgreSQL、RustFS、Keycloak；逐一比對 remote digest | 已修復 |
| OLI-006 | High | 外部筆電收到 NGINX 403 | Allowed CIDR 只有 `10.168.1.0/24`，實際 operator source 是 `10.212.134.10` | 設定增加 `10.212.134.10/32`；公開 HTTPS 通過 | 已修復 |
| OLI-007 | High | App 經 Ingress 回 504 | NetworkPolicy 假設 `ingress-nginx/ingress-nginx`，RKE2 實際為 `kube-system/rke2-ingress-nginx` | 新增 typed ingress controller namespace/name 參數與 Ready Pod preflight | 已修復 |
| OLI-008 | High | 新 PVC 無法排程 replica | Longhorn `Retain` 留下多輪 Released PV/volume，消耗容量 | 只刪除已盤點、Released、屬於 NomoSmart 的 PV 與 detached volume；LDAP Bound volume 保留 | 已修復 |
| OLI-009 | Medium | 重新 fresh install 被 namespace digest drift 阻擋 | Namespace label/annotation 仍綁前一個 config digest | 驗證後精確移除舊 installer metadata；Rancher Project label 保留 | 已緩解 |
| OLI-010 | Medium | 僅清 Cluster state 後仍有 config mismatch | Ownership 有 local state、Cluster ConfigMap、Namespace metadata 三個平面 | 三個平面都要盤點；晚到 local state 移入 owner-only attempt archive | 已緩解 |
| OLI-011 | Medium | 中斷 wrapper 後留下 installer Lease | 外層 PTY wrapper 收 Ctrl-C，未完整轉送 signal/等待 child finally | 確認 holder PID 不存在且超過 90 秒 TTL 後刪除 Lease | 待改善 |
| OLI-012 | Medium | Foundation 首次偶發 `kubectl returned protected error output` | Vault Pod 剛啟動時，status/exec/cp 發生短暫 race | 等 Pod status-queryable 後 `resume` 成功；公開 PGP key cp 探針通過 | 待改善 |
| OLI-013 | High | Vault 未初始化或 sealed 時 liveness 失敗 | Probe 把安全的 sealed/uninitialized 狀態當成 process failure | 調整 health code 契約；process 活著但未初始化時不重啟 | 已修復 |
| OLI-014 | High | Vault status TLS hostname mismatch | 以 `localhost` 存取，但憑證 SAN 是 Pod DNS | Installer 一律使用 Pod DNS 與 mounted CA | 已修復 |
| OLI-015 | High | Vault init/unseal 指令未穩定信任 CA | CLI address/CA 沒有在每個操作明確指定 | 集中 `_connection_arguments`，每次使用 Pod DNS 與 CA | 已修復 |
| OLI-016 | High | Vault 2.0.3 init JSON 被判為缺 share | 2.0.3 回傳 `unseal_keys_b64`，原解析預期另一欄位 | 支援實際 2.0.3 contract，驗證 5 份相異 encrypted shares | 已修復 |
| OLI-017 | High | GnuPG 無法解開由 PGPy 產生的 custody ciphertext | OpenPGP implementation/packet interoperability 差異 | Custody helper 統一用 PGPy private-key decrypt；明文只留在記憶體 | 已修復 |
| OLI-018 | Medium | 自動化 helper 無 controlling TTY | subprocess PTY 不是完整 controlling terminal | helper 改用 `pty.fork()`；installer 的 `isatty(0)` 通過 | 已修復 |
| OLI-019 | Medium | PGP cleartext 變成 `b'...'` 字串 | PGPy 回傳 bytes，直接 `str()` 破壞 share | bytes 先 UTF-8 decode；3 份 share 格式與相異性驗證通過 | 已修復 |
| OLI-020 | High | `vault operator unseal -` 無法從 stdin 取 key | Vault CLI 把 `-` 當成 literal invalid key | 改為 `vault write -format=json sys/unseal key=-` 且不補 newline | 已修復 |
| OLI-021 | Medium | 第三份 share 後立即查詢仍顯示 sealed | Vault state visibility 有短暫延遲 | 增加 `_wait_unsealed` polling | 已修復 |
| OLI-022 | Medium | Vault 2.0.3 status 沒有 `ha_mode` | CLI JSON contract 版本差異 | 由 `is_self`、`active_time`、`leader_address` 正規化 active/standby | 已修復 |
| OLI-023 | Medium | 非 TTY resume 對已 unsealed Vault 仍要求互動 | TTY check 放在狀態判斷之前 | 僅在實際發現 sealed Pod 時要求 TTY | 已修復 |
| OLI-024 | Medium | Longhorn attach 後 Vault DNS/status 偶發失敗 | Pod 啟動與 DNS/volume attach 競態 | 加入 `_status_eventually` retry | 已修復 |
| OLI-025 | Medium | Keycloak component 無法穩定保存自訂 owner/digest config | Keycloak 會正規化/捨棄未知 component config | Ownership evidence 移至 Kubernetes ConfigMap | 已修復 |
| OLI-026 | High | LDAP group mapper 建立失敗 | `/ldap` parent realm group 尚不存在 | Installer idempotently 建立 group path 後再建 mapper | 已修復 |
| OLI-027 | Medium | Keycloak API 錯誤只看到泛化失敗 | error body 欄位可能是 `errorMessage` 或 `error` | 解析兩種欄位並經 redactor 後輸出安全摘要 | 已修復 |
| OLI-028 | Medium | OpenLDAP 使用者 `cn` 多值警告 | `user01/user02` 的 `cn` 有顯示名稱與 uid 兩個值 | Keycloak 選第一值，full sync 未失敗；建議 directory owner 正規化顯示名稱策略 | 待改善 |
| OLI-029 | Critical | Directory mapping Job 找不到模組 | 原 pinned Backend release artifact 缺 `app.deployment.directory_reconcile` | 重建/push digest-pinned Backend；容器內 import 成功 | 已修復 |
| OLI-030 | Critical | `directory_admin_database_identity_missing` | Keycloak OpenLDAP user 使用 built-in `LDAP_ENTRY_DN`，Backend 只辨識自訂 `ldap_dn` | `CHG-248-LIVE-01` 增加 DN fallback 與 federation-origin；3 tests 通過，實機 Job Succeeded | 已修復 |
| OLI-031 | Medium | Directory Job 已 Failed，但 installer 仍等 complete timeout | `kubectl wait --for=condition=complete` 不會因 Job Failed 提前結束 | 本次由 Job log 找到安全錯誤碼後中斷；建議 installer 同時監看 Failed/Complete | 待改善 |
| OLI-032 | Medium | Docker Desktop build 無法匿名 pull public base image | macOS Keychain `desktop` credential helper 回 `-25293`，一次性空白 config 仍被 Desktop BuildKit 覆蓋 | 改用既有隔離 build VM 的 Podman；映像與 tests 均成功 | 已緩解 |
| OLI-033 | Low | PGPy 顯示 TripleDES/Camellia/CFB deprecation warning | PGPy 相依 cryptography 已宣布舊 cipher API 移除時程 | 不影響本次 decrypt；需升級/替換 PGP tooling 並做 custody regression | 待改善 |
| OLI-034 | Low | Operator laptop 無 `curl` | 本機工具集合與手動 runbook 假設不同 | 改用 installer 同款 Python TLS client，三個 public endpoint 通過 | 已緩解 |
| OLI-035 | — | Installer 停在 TOTP | TOTP seed 必須由人員自己的 authenticator 保管，installer 不應擷取或保存 | 兩個帳號均由人員完成 enrollment；`resume` 與獨立 `verify` 通過 | 預期 checkpoint |
| OLI-036 | High | `user01` 到達 checkpoint 時沒有 `CONFIGURE_TOTP` | Keycloak full sync 不會自動把 OTP enrollment required action 加到新匯入的 federated user | `CHG-248-LIVE-02` 在 full sync 後只對尚無 OTP 的指定管理員冪等加入 `CONFIGURE_TOTP`；實機重跑目錄階段已確認 | 已修復 |
| OLI-037 | High | 兩個 TOTP 均完成後 Backend onboarding probe 仍失敗 | 唯讀 probe 錯用需要一次性 break-glass 初始密碼的完整 bootstrap settings；長駐 Backend 按最小權限設計未注入該 Secret | `CHG-248-LIVE-03` 改用只含一般 runtime 與 finalization admin/group 的最小 settings，並讓 installer 對舊/新 Backend image 使用同一最小權限 probe；4 項 Backend tests、相容 probe、`resume` 與 `verify` 通過 | 已修復 |
| OLI-038 | High | Finalization Job 成功後新 Pods 永遠等不到 bootstrap evidence | Helm revision 3 把 release ID 改成 `nomosmart-3`，但 finalization 刻意不重跑只存在於 application revision 2 的 Bootstrap Job/evidence | `CHG-248-LIVE-04` 由 durable application revision 保存 evidence ID，finalization/operational upgrade 都沿用；revision 5 全部 Pods Ready，Migration/Bootstrap 未重跑，Helm 測試通過 | 已修復 |
| OLI-039 | High | 已成功停用的 break-glass 讓 resume revalidation 失敗 | Finalization side effect 先於 Helm wait 完成，但已完成 TOTP stage 的 revalidation 仍固定要求帳號 enabled | `CHG-248-LIVE-05` 僅在 finalization/operational 路徑允許 disabled；OTP、required actions、角色、login audit、資料庫及 replacement admin 證據仍全部通過，最終 receipt 已產生 | 已修復 |
| OLI-040 | High | 一次性 Backend build archive 初次包含本機 `.env` | 臨時封裝使用過寬的來源範圍，未在傳輸前套用敏感檔 denylist | 檔案清單檢查發現後，在解壓前立即刪除遠端與本機 archive；改以排除 `.env` 的乾淨 archive 重建並測試。正式建置流程仍應強制採用 allowlist／`git archive` 與 pre-transfer secret scan | 已緩解 |

## 重要問題詳細說明

### 1. Registry cache 造成的假成功

這是本次最重要的 production 風險之一。Pod 顯示 Running 並不代表 Registry
可供新節點拉取映像；RKE2 containerd 已有舊 cache 時，即使 repository 為空，
`IfNotPresent` 仍可啟動。

處理方式不是把 `imagePullPolicy` 改成 `Never`，而是把 approved digest artifact
真正推到 Registry，再從 Registry 讀回 raw manifest 計算 SHA-256。五個缺少映像的
remote digest 都與 TOML 完全一致，才判定修復。

### 2. OpenLDAP `LDAP_ENTRY_DN` 相容性

Keycloak 的 generic LDAP importer 不需要自訂 mapper 就會提供：

- `LDAP_ID`
- `LDAP_ENTRY_DN`
- `federationLink`

舊 NomoSmart normalization 只找 `attributes.ldap_dn`，所以使用者雖然是
Keycloak federated user，進入資料庫時仍被標成 `keycloak`，而不是 `ldap`。
角色映射流程刻意只接受 `auth_source=ldap` 的 active user，因此安全地失敗。

修正後的優先順序是：

1. 自訂 `ldap_dn`
2. Keycloak built-in `LDAP_ENTRY_DN`
3. 如果 DN 缺少，但有 `federationLink`，仍保留 LDAP origin

這不降低 group/member 驗證；Job 仍要求 `user01` 是 enabled federated user、
屬於指定 OpenLDAP group，且 DB mapping 來源必須為 `external_sync`。

### 3. Fresh reinstall ownership

Installer 對 drift 的 fail-closed 行為有效，但目前第一版明確不提供 uninstall。
測試人員要重建同一 Namespace 時，必須同時處理：

- owner-only local `state.json`
- Cluster `nomosmart-installer-state` ConfigMap
- Namespace owner/config digest metadata
- installer Lease
- Helm keep-policy Job
- `Retain` PVC/PV/Longhorn volume

任何一項殘留都應阻止新 digest 接管，這是正確的安全預設；但若要把此 installer
用於重複 release rehearsal，應另外設計受審批、會先列 plan 的 reset/uninstall
runbook，不能把強制清理藏在 `install`。

### 4. Vault ceremony 與版本差異

Vault 2.0.3 的 CLI/JSON 行為與原先假設不同，包括：

- init encrypted share 欄位名
- `ha_mode` 缺少
- unseal stdin 介面
- 第三份 share 後狀態可見性延遲

修正後，Shamir 5/3、三節點 unseal、Raft peers、KV v2、audit、Kubernetes auth、
root-token fingerprint 與 revoke 證據均通過。Initial root token 已撤銷。

### 5. 人工 TOTP checkpoint

Installer 不可替人員掃描或保存 TOTP seed，否則 custody 邊界失效。兩個帳號均已
由人員在瀏覽器完成 enrollment；installer 只驗證 credential、required action、
角色、登入 audit 與應用資料庫證據，不讀取 TOTP seed 或 OTP code。

實機檢查曾發現 `user01` 雖已 federation/full sync 成功，卻沒有
`CONFIGURE_TOTP` required action。`CHG-248-LIVE-02` 已修正 installer：

- 已有 OTP credential：不改動。
- 尚無 OTP、但已有 `CONFIGURE_TOTP`：不重複加入。
- 尚無 OTP、也沒有 required action：加入一次 `CONFIGURE_TOTP`。

目錄階段重跑後回報 `user01` 為 federated 且 required action 已設定。完成
enrollment 後，`user01` 與 Keycloak-local break-glass 帳號均具有 OTP
credential，required actions 皆已清除。Finalization 已停用 break-glass，
`user01` 的外部群組管理權限則保持有效。

完成後已執行：

```bash
KUBECONFIG=/Users/peter/Documents/NomoSmart-UAT-Handoff/NomoSmart-UAT-RKE2.kubeconfig \
  deploy/installer/nomosmart-install resume \
  --config /Users/peter/Documents/NomoSmart-UAT-Handoff/installer-openldap-live/env-uat-openldap.toml
```

最終已獨立執行：

```bash
KUBECONFIG=/Users/peter/Documents/NomoSmart-UAT-Handoff/NomoSmart-UAT-RKE2.kubeconfig \
  deploy/installer/nomosmart-install verify \
  --config /Users/peter/Documents/NomoSmart-UAT-Handoff/installer-openldap-live/env-uat-openldap.toml
```

## Repository 修正與測試

本次直接關聯的 Repository 修正包括：

- Installer typed config / preflight：
  - RKE2 ingress controller namespace/name。
  - existing Namespace `kube-root-ca.crt`。
- Helm：
  - 全部 PodSpec 的 `imagePullSecrets`。
  - RKE2 ingress NetworkPolicy selector。
  - Vault sealed/uninitialized health contract。
- Vault：
  - Pod DNS + CA。
  - Vault 2.0.3 JSON/status/unseal 相容性。
  - state visibility retry。
- Directory：
  - `/ldap` group path。
  - safe Keycloak error body。
  - Kubernetes ownership evidence。
  - retry Job naming。
  - federated designated admin 的冪等 `CONFIGURE_TOTP` enforcement。
- Backend：
  - `app.deployment.directory_reconcile` 納入正式映像。
  - `LDAP_ENTRY_DN` / `federationLink` identity normalization。
  - onboarding status 改用不依賴一次性密碼的最小權限 settings。
- Finalization / resume：
  - application revision 的 bootstrap evidence ID 跨 finalization 與
    operational revision 保持穩定。
  - 已完成 TOTP 後，允許 finalization 已停用的 break-glass 冪等續跑，但不放寬
    OTP、角色、登入、資料庫及 replacement administrator 證據。
  - 僅允許符合精確階段與前置證據的 failed Helm finalization revision 恢復。

已執行：

```text
./HARNESS/harness.sh test:installer
# 22 tests, OK

PYTHONPATH=backend backend/.venv/bin/python -m pytest -q -o addopts='' \
  backend/tests/test_chg248_openldap_identity_normalization.py
# 4 tests passed

./HARNESS/harness.sh helm:lint
# PASS

./HARNESS/harness.sh backend:syntax
./HARNESS/harness.sh deploy:config-policy
./HARNESS/harness.sh spec:doctor
./HARNESS/harness.sh spec:trace
./HARNESS/harness.sh plan:approved
# PASS

nomosmart-install verify --config <protected-config>
# verified；Helm revision 5、deployment_phase=operational、pending_checkpoints=[]
```

Governance/deployment focused checks 已重跑通過。Focused Backend tests 以停用
repository-wide coverage addopts 的方式執行；這 4 項 focused tests 不是完整
Backend suite 的 coverage 結果。Installer/OpenLDAP live acceptance 與最終
receipt 已完成；Repository-wide Frontend/Backend 80% release gate 仍是獨立的
產品釋出門檻，不能由本次 focused installer 測試取代。

## 保管與封存

- Attempt 1 至 Attempt 5 均保存於
  `/Users/peter/Documents/NomoSmart-UAT-Handoff/installer-openldap-live-attempt*-20260729`
  owner-only 目錄。
- Attempt 6 的 active config、package、state、custody 位於
  `/Users/peter/Documents/NomoSmart-UAT-Handoff/installer-openldap-live`。
- 設定與保管檔為 `0600`，目錄為 `0700`。
- 本報告不記錄任何 generated credential 明文。

# 本機 Kubernetes 部署：認證契約 2

[English](README.md) · [現行部署指南](../README.md#helm-installation)

Compose及Helm已移除內建認證服務。本機仍需真實的PostgreSQL、Redis、S3／RustFS、OpenSearch、Neo4j與LDAP／AD；只有OIDC登入模式另需外部OIDC服務。資料服務可在本機，但仍由operator明確管理，保留TLS驗證。

## 選擇目前可用路徑

- 協定安裝工具使用`external-services`、既有runtime Secret及綁定installation UUID的目標設定。由[目標TOML](../installer/nomosmart-install.protocol.example.toml)與[values JSON](../installer/protocol-values.example.json)開始。
- 直接使用Helm可部署內建資料服務，但operator須依序完成bootstrap、正常管理員登入及finalize。詳見[Helm操作](../README.md#helm-installation)。
- `values-docker-desktop.yaml`仍保留舊`localDevelopment`／`factory_acceptance`模式。渲染通過不代表能原樣交給採正常onboarding的協定安裝工具，也不代表正式環境或HA資格。
- 目前一鍵入口只用`--protocol-config`及external-services，仍停在一般管理員登入檢查點。舊`prepare-helm.py`、factory及認證契約1範例保留為歷史並排除新版套件。tunnel範例只保留資料服務轉送，不佈建IdP或固定認證代理。

## 準備與驗證

使用明確context與獨立namespace／release。若為了先準備Secret而建立namespace，須以`nomosmart.io/protocol-installation`標示同一installation UUID；不能接管其他安裝的namespace。

核對實際node資源、taint、ingress、StorageClass與儲存容量。同一Docker VM上的多個Kubernetes節點不代表多台主機或儲存容錯；容量要以共享主機計算。確認每個目標node都有相同、已檢視的應用映像。

秘密與私鑰保留在私有operator目錄及Kubernetes Secret。target／values只保存非秘密配置與reference；LDAP Bind及OIDC憑證須對應真帳號。沒有固定應用預設密碼，也不自動建立目錄管理員。

需要時可設定`podDnsOverTcp: true`，只改應用Pod解析選項，不改叢集DNS／CNI或TLS信任。不要為了TCP DNS而啟用舊factory憑證模式。

驗證順序為plan → install／resume → 真實同步管理員登入 → finalize → verify。OIDC管理員另須重新驗證；exit10／action-required表示等待這個登入步驟。中斷後先查status再決定後續寫入。

另驗HTTPS、readiness、權限及真目錄同步；lint／render不等於實機成功。清理只操作精確owned資源，保留外部服務、PVC及其他namespace；應用rollback不等於資料庫還原。

## 證據與歷史

現行驗證與缺口、設定檢查、舊本機說明。2026-10-01驗證僅保留當時結果，不當成目前來源已通過。

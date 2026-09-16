# CHG-293 Backend／Frontend 建置與 revision 37 dry-run

日期：2026-09-10。Stage A 已由 Peter 回覆「核准」；**實際部署未核准**。
核准承接上一則明確問題：建置 CHG-293 Backend、Frontend 映像，執行 revision 37
dry-run；保留 Migration，不實際部署、不修改資料、不呼叫 Provider。
具體 preparation 計畫見 `CHG-293-READONLY-INVENTORY.md` 的下一步。

## 執行計畫與邊界

1. 核對 docker-desktop / nomosmart / nomosmart-local 仍為 revision 36 / deployed，
   Backend／Frontend CHG-292，Migration CHG-288、forward-v047；漂移即停止。
2. 使用現有 Dockerfiles／lockfiles，建置 `nomosmart/backend:0.1.0-chg293` 和
   `nomosmart/frontend:0.1.0-chg293`。固定本機 source fingerprints 與 image IDs；
   不覆寫其他 tags、不 push registry，不建置 Migration 或套用 V049。
3. 使用 --network none、read-only rootfs、非 root、disposable tmpfs 的隔離 image
   smoke，驗證封裝、source/compiled markers、loopback liveness／OpenAPI／login。
   不掛載 live 設定／資料，不把 liveness 冒充 DB readiness 或 authenticated flow。
4. 若現有工具可用，使用本機 image 掃描與 SBOM 工具；工具／權限不可用則如實記錄，
   不登入新帳號、不上傳映像、不擅自修改相依或接受 High/Critical 風險。
5. 兩次 `helm upgrade ... --reuse-values --dry-run=server --hide-secret`，僅覆寫
   Backend／Frontend tags。記憶體內比對目前非 Secret manifests，只容許既有
   release annotations、兩個 revision-scoped Job 名稱、bootstrap release ID 與
   指定 images 改變。canonical render 以 stdout 自 HOOKS 起至尾端 UTF-8 bytes
   SHA-256 計算，兩次必須相同；不輸出／保存 Secret 明文或完整 Helm values。
6. 核對 release／values digest 未變、revision-37 Jobs 仍不存在、現有 workloads
   不變；保存安全結果與尚未完成的 gates。smoke 容器退出自動清除，新映像保留。

只允許本地 build／隔離 smoke／掃描及 server dry-run。禁止 Helm write、Job 建立、
Kubernetes mutation、bootstrap ensure/check、live SQL、role/group/member 寫入、
reprocess、re-embed、reindex、manifest switch、圖譜修復或 Provider。這不豁免完整
80% coverage、全流程 E2E、掃描及實際部署前完整保護基線／bootstrap／rollback 核准。
SPECIFICATION.md 10.50／CHAT-COMPAT-001 未改變，沒有產品行為變更。

## 結果

**Build、isolated smoke、兩次 server dry-run、SBOM 已完成；安全門檻未通過，停止進入部署。**
Frontend 掃描為 4 Critical／8 High，未接受風險、未修改相依。Backend 的同一
High/Critical 掃描為零。Stage A 不能標示為全部通過或可部署。
安全證據：`CHG-293-REVISION37-BUILD-DRYRUN-EVIDENCE.json`。

### 建置產物

| 產物 | Docker inspect image ID |
| --- | --- |
| nomosmart/backend:0.1.0-chg293 | sha256:7a367c11fc6a49825c57826714536832e81a27455130b652b7361d78bc2eec4d |
| nomosmart/frontend:0.1.0-chg293 | sha256:500a02af6d9e318e944a23774bbb432d9cb77d2eb331882860ecf3b3eb712a80 |
| 保留 nomosmart/migrations:0.1.0-chg288 | sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab |

兩個 app images 均 arm64、使用 nomosmart 非 root 帳號。Migration 未建置。
使用目前已核准的 dirty CHG-293 source，HEAD 前後均
`bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3`；產品 source/tree fingerprint 前後均
`578ff4d192c59010a619f519d43156da1188c1fb215272f480ecdb018e2efa79`。
沒有變更 Dockerfiles、dependency locks、產品程式或 chart。

```bash
docker --context desktop-linux build --progress=plain -t nomosmart/backend:0.1.0-chg293 backend
docker --context desktop-linux build --progress=plain -t nomosmart/frontend:0.1.0-chg293 frontend
```

兩個 build exit=0；Frontend optimized build／TypeScript 通過。原 Dockerfiles 的
base tags 不是 digest pins，Backend 此次重新解析 Ubuntu tag 並安裝既有 Dockerfile
指定的 apt 套件；不能宣稱跨日期重建仍 byte-identical。實際 base digest 記於 JSON。
應使用上表本次 image IDs 綁定後續候選，不以 tag 本身當不可變證據。

### 隔離 image smoke

- 兩個容器皆 UID 10001、`--network none --read-only`，只有 64 MiB disposable
  `/tmp` tmpfs；無 host port、live config、Secret 或資料 volume。capabilities 全移除、
  no-new-privileges；沒有額外網路、測試資料庫或 Kubernetes 資源。
- Backend：十個核心模組 source hash 與 repository 相同，包含 Creator identity／
  Editor policy／routes／ORM／validation 及保留的 CHG-292 graph modules。
  None-as-SQL-NULL 設定、作者／能力 response contract、archive 純政策組合通過；
  真正 uvicorn `/api/v1/health`=200，OpenAPI chat/history 與 graph routes 存在。
- Frontend：211 個 compiled JS 中六項 CHG-293 markers 皆存在；真正 Next server
  loopback `/login`=200，回應有 NomoSmart。
- 這些是 packaging／liveness smoke，不是 DB readiness、auth/browser 行為或完整
  ingestion acceptance。未使用假 Provider／service adapter；未呼叫 Provider。
- `--rm` 的兩個 smoke 容器皆已自動移除，最後 label 查詢為空；新 images 保留。

### Revision 37 dry-run

```bash
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg293 \
  --set-string image.frontend.tag=0.1.0-chg293 \
  --dry-run=server --hide-secret --timeout 15m
```

兩次 prospective revision=37，canonical 長度都是 96,181 bytes，SHA-256 一致：

`709e19e1a8865e991406456871fb0ef19d8f45740fb9eac0eb55032ba5c5ab87`

canonical 規則維持本計畫第 5 點。比對排除 Secret objects，不寫出 values/Secret
明文。本次使用既有 Secret reference，render 中 Secret objects=0，不能解釋為
已驗證 live Secret UID/data。

非 Secret manifests 除已核准 image tags、release annotations、兩個 Job 名稱、
ConfigMap bootstrap release 外完全一致。Backend CHG-293 共 8 references：
Backend／Worker／Beat main+init、Frontend init、bootstrap-37；Frontend main 1 個；
Migration CHG-288 1 個。只渲染 migration-37／bootstrap-37，沒有建立或執行。

前後均為 revision 36 / deployed、revision-37 Job count=0。四個 app Deployments
generation=32、Ready=1，仍維持 CHG-292 main/init；完整 effective values hash 為
`5a9b73395ced6bf62da8d9d04bc0155590fc66fbdf0aa57ea3dc53750e980ccd`，deployment spec
hash 為 `7b4dd9596010e46567b4b37409ed9f5cfbd30e43e6098f7b21e521fc417fad91`，皆不變。

### Security scan / SBOM

使用既有 Docker Scout v1.24.0，`local://` 只解析本機 image、不做 registry fallback
或 image push。`security:sbom` exit=0：Backend／Frontend 分別索引 340／347 packages。
`security:containers` exit=2，保留 High/Critical 門檻，沒有新增 exception 或濾掉 base。

| 映像套件（依 Scout） | 本次版本 | Critical | High | 掃描器標示的修復版本 |
| --- | --- | --- | --- | --- |
| Frontend / Next.js | 16.2.12 | 2 | 0 | 16.3.3 |
| Frontend / sharp | 0.35.3 | 0 | 1 | 0.35.4 |
| Frontend / Alpine OpenSSL | 3.5.7-r0 | 2 | 7 | 3.5.8-r0 |
| Backend / 全掃描範圍 | — | 0 | 0 | — |

這是掃描器的 12 項 vulnerability findings，並非已確認可利用或遭入侵；修復版本
尚需核對 maintainer advisory、相依關係與 NomoSmart 相容性，不視為已核准升版方案。
Next.js 的兩項為 CVE-2026-75604、GHSA-2xp9-vwfh-vxw4；其餘 IDs 見 JSON/SARIF。
此階段不修改 package.json、lockfile、Dockerfile 或 production image。

原始報告保留於：

- `/tmp/chg293-build.5fYxc2/security/backend.scout.sarif.json`
- `/tmp/chg293-build.5fYxc2/security/frontend.scout.sarif.json`
- `/tmp/chg293-build.5fYxc2/security/backend.spdx.json`
- `/tmp/chg293-build.5fYxc2/security/frontend.spdx.json`

四份檔案 SHA-256 均記於安全證據 JSON。沒有將 High/Critical 掃描失敗改列 PASS；
先前完整 Frontend／Backend 80% coverage／全流程 E2E 缺口也未被本輪 smoke 取代。

### 治理驗證及下一步

`spec:doctor`、`spec:trace`（六項）、`plan:approved`、`test:plan`、`docker:config`、
`helm:lint`、`deploy:config-policy`、`git diff --check` 通過。沒有執行 live SQL、
bootstrap、Helm write、Kubernetes mutation、role/member/data/index 變更或 Provider。
本次 SPECIFICATION.md／SPEC_CHANGELOG.md 不變：只有既有核准的產物驗證及風險紀錄。

**下一步先由 Peter 決定是否啟動 Frontend 安全相依／base image 修補範圍的規格與
相容性計畫，不直接要求核准部署這個未過安全門檻的 image。** 修補後必須重建、
重新 smoke／掃描／SBOM／dry-run 並產生新 image bindings，不沿用本次 Frontend ID。
即使日後掃描通過，仍須另核對完整保護基線、bootstrap operational writes、維護與
rollback 條件並取得獨立 Stage B 核准；完整 release gates 不自動豁免。

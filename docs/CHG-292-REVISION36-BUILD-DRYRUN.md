# CHG-292 映像建置與 revision 36 dry-run

日期：2026-09-09。Stage A：**通過；實際部署未執行、未核准**。
依 Peter 本次明確核准，只建置 Backend／Frontend CHG-292 映像、執行隔離 image
smoke tests、預演 revision 36，並保留 Migration 與現有 schema contract。

規格：`SPECIFICATION.md` 10.49 / GRAPH-009..013；行動計畫與完整核准原文見
`DEVELOPMENT_PLAN.md` 的 CHG-292 Next operational stage。

## 前置核對與建置來源

- Context：`docker-desktop`；namespace：`nomosmart`；release：`nomosmart-local`。
- 核對前、兩次 dry-run 前及核對後皆為 revision **35 / deployed**。
- 保留 Migration：`nomosmart/migrations:0.1.0-chg288`；保留
  `compatibility.schemaContract=forward-v047`。沒有建立 Migration 映像或執行 SQL。
- 執行前 CHG-292 兩個 image tags 均不存在；沒有覆寫既有映像。
- Source HEAD：`bbaf03850fd83892327c9e47cf3e9f8da7dbc5f3`，建置前後相同，
  產品程式／Dockerfiles／dependency locks 沒有變更。
- Docker context：`desktop-linux`；Helm：`v4.2.3+g43e8b7f`。
- 直接使用原 Dockerfiles 建置，無 registry fallback、無修改 dependency locks。

建置命令：

```bash
docker build --progress=plain -t nomosmart/backend:0.1.0-chg292 backend
docker build --progress=plain -t nomosmart/frontend:0.1.0-chg292 frontend
```

| 映像 | Docker inspect `.Id` |
| --- | --- |
| `nomosmart/backend:0.1.0-chg292` | `sha256:1576f33a536227708f33d02d488533efd66abe2b0425e51d1dd2e17e898eeea1` |
| `nomosmart/frontend:0.1.0-chg292` | `sha256:82df26d3807ebc3904826135ae61f10aaf3a6a2a6a5464d2d822638a7935bbd9` |
| 保留 `nomosmart/migrations:0.1.0-chg288` | `sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab` |

Backend／Frontend 架構都是 arm64，以 `nomosmart` / UID 10001 執行。
上表為實際 Docker inspect image ID，不混用 build log 中的 image config digest。

## 隔離 image smoke tests

兩個 image 各自以 `docker run --rm -i --network none --read-only` 啟動測試程序，
只配置 disposable `/tmp` tmpfs，沒有掛載目前 application data、Secret 或憑證。
測試程式經 stdin 傳入，不修改 image／Pod。只訪問各自 container 的 loopback。

| 檢查 | 結果 |
| --- | --- |
| Backend non-root UID / no `/app/.env` | 通過：10001、無 dotenv 檔。 |
| Backend CHG-292 projection/reconciliation/jobs/schema imports | 通過；`tag_edit_reason`、edge `metadata` 欄位存在。 |
| Backend canonical version/relation/hash invariants | 通過；`tag-graph-v1`、兩種標籤關係、穩定 canonical hash。 |
| Backend 映像內兩個核心模組的 source hash | 與已核准／已盤點的 repository source 完全相符。 |
| Backend 實際 uvicorn `/api/v1/health` | HTTP 200，`{"status":"healthy"}`。 |
| Backend `/openapi.json` scoped graph / paths endpoints | 存在。 |
| Frontend optimized build / TypeScript | Docker build 通過。 |
| Frontend non-root UID / no `/app/.env` | 通過：10001、無 dotenv 檔。 |
| Frontend compiled CHG-292 markers | 掃描 211 個 `.next` JS 檔，5 個必要 markers 均存在。 |
| Frontend 實際 Next server `/login` | HTTP 200，回應包含 NomoSmart。 |

Backend 核對 source SHA-256：

- graph_projection.py：`0420ee9826cb256079660f16ee2ab0821eab4b99704cecf14543be783b0539b6`
- graph_reconciliation.py：`67d21dccd30ab455d08f074d0045d094f5cbb831ec1714c994438191cd17b2af`

上述為 image packaging / import / liveness / compiled-content smoke，不冒充
資料庫 readiness、實際圖譜同步或 authenticated Browser 驗收。沒有使用假的服務
adapter、假的 Provider response 或偽造的健康結果；只檢查服務既有的 liveness。
先前 27 項真實隔離服務整合測試證據另見 `CHG-292-TAG-GRAPH-VERIFICATION.md`，
本階段沒有重跑完整 Backend／Frontend 套件。

兩個 remove-on-exit smoke containers 都已自動清除，label
`nomosmart.change=CHG-292-stageA` 的最後查詢為空；沒有建立測試 network 或 volume。
本機新映像保留供下一階段核准使用。

## 兩次 hidden-Secret server-side dry-run

```bash
helm upgrade nomosmart-local deploy/helm/nomosmart \
  --kube-context docker-desktop -n nomosmart --reuse-values \
  --set-string image.backend.tag=0.1.0-chg292 \
  --set-string image.frontend.tag=0.1.0-chg292 \
  --dry-run=server --hide-secret --timeout 15m
```

兩次 prospective revision 均為 **36**。Canonical hash 規則：截取 Helm stdout 從
`HOOKS:\n` 起至尾端的原始文字，以 UTF-8 bytes 計 SHA-256，排除上方易變的 release
時間／狀態資訊，不任意重排 YAML。兩次 canonical 長度皆為 **96,181 bytes**：

```text
renderSha256=fad6bb97fcaeadbccfd90d8b32a3a4a41e578be2ba37a776be7a78f278b32b67
```

以目前 release manifest 為基準，僅正規化已核准的兩種 app image tags、
35→36 的 deployment-release / installer-revision、兩個 Job 名稱及
ConfigMap `DEPLOYMENT_BOOTSTRAP_RELEASE` 後，**所有非 Secret manifests 完全一致**。
沒有其他 resource set 或欄位差異。Secret 本體由 Helm 隱藏；不是以輸出 Secret 明文
作比對，也不宣稱這個測試驗證了 Secret 的完整 live UID/data 保護基線。

預計 image references：

| 映像 | References | 預計影響 |
| --- | --- | --- |
| Backend CHG-292 | 8 | Backend／Worker／Beat main + init，Frontend readiness init，bootstrap-36。 |
| Frontend CHG-292 | 1 | Frontend main。 |
| Migration CHG-288 | 1 | 既有 migration-36 template，未改 image。 |

預計僅有兩個 revision-scoped Jobs：`nomosmart-local-migration-36`、
`nomosmart-local-bootstrap-36`。**只渲染，未建立或執行**。
ConfigMap 的 bootstrap evidence release 預計為 `nomosmart-local-36`。
Supporting services、Ingress、NetworkPolicy 等非 Secret manifests 無額外變更。

## 核對後狀態及限制

- Release 仍為 revision 35，revision-36 Job count 仍為 **0**。
- 四個 app Deployments 均維持 1 Ready replica，main/init 均維持各自 CHG-291 image。
- 完整 effective Helm values 的 canonical JSON SHA-256 前後均為：
  `019eeed496ad5f6034258caaa2c1b09ad43c8e294b61fbddcce62bf46f469c57`。
  此為 values 摘要，不是全庫資料、PVC、Secret 或 index 的完整 protected baseline。
- 沒有 Helm write、Kubernetes mutation、Job creation、V049 apply、圖譜修復、
  application-data/index change、重處理、Embedding、reindex、manifest switch 或
  Provider call。本階段沒有查詢或修改資料庫／Neo4j／OpenSearch。
- 通過 `spec:doctor`、`spec:trace`、`plan:approved`、`docker:config`、`helm:lint`、
  `deploy:config-policy`、`git diff --check`。
- 全庫 80% coverage、完整 Backend 與 authenticated Browser／正式發布驗收等
  既有缺口仍保留。本階段也未產生新映像的容器掃描／SBOM 證據。
  Stage A 通過不代表 full release acceptance。

## 下一個核准點

Stage B 實際部署仍需另行核准，並重新確認 revision、render/image IDs、實際保護基線、
兩個既有 Job 的行為，以及 rollback／相容性策略。本次不順帶執行 CHG-291 的 V049。
舊版 writer 的 tag-free／候選寫入行為仍須列入 rollback 風險，不能只因 schema 相容就
宣稱 graph contract 可無條件回退。

上次唯讀盤點的已發布補同步目標為空；此結果不是發布、補同步、清除或復活任何候選／
已刪除文件的授權。部署後的正式發布驗收需走正常治理流程並另列資料寫入範圍。

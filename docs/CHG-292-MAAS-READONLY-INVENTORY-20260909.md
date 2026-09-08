# CHG-292 MAAS 唯讀圖譜盤點

## 授權與結論

Peter 已核准：`Peter approves CHG-292 Docker Desktop read-only MAAS tag graph
inventory and comparison only; no data mutation, graph repair, DDL, Job creation,
image build, deployment, re-embedding, reindexing, manifest switch or Provider call.`

本次完成唯讀盤點。**目前 MAAS 沒有已發布版本，也沒有 active manifest，因此沒有
符合 CHG-292「已發布標籤補同步」條件的對象。** Neo4j 並非完全沒有標籤：一份
未發布、已刪除的舊文件仍有 81 個 Tag 節點與 115 條標籤關係，但這不是正式發布證據。
未將候選、失敗或已刪除文件轉成正式圖譜，未清理歷史資料。

規格依據：`SPECIFICATION.md` 10.49，GRAPH-009..013。

## 環境與查詢方式

- Kubernetes context：`docker-desktop`；namespace：`nomosmart`。
- Helm release：`nomosmart-local`，前後均為 revision **35 / deployed**。
- Backend／Frontend：`nomosmart/backend:0.1.0-chg291` /
  `nomosmart/frontend:0.1.0-chg291`；CHG-292 尚未部署。
- Backend Pod：`nomosmart-local-backend-6d6bfbd467-8d8xt`，前後 UID
  `18f0d601-06a5-42ec-80de-1e020fbf8717` 相同。
- Backend image ID：
  `sha256:465a14eee6601d91a419840a951e9cb0347c4c9d7099c4891bd0c78bdf8fcff5`。
- Project：`MAAS`，ID `9e1d3e43-8069-4965-84d1-f5890880b3d4`，
  `status=active`、`work_generation=1`，以 exact name 唯一匹配確認。
- 成功比對時間：2026-09-09 02:22:28 及 02:23:01 Asia/Taipei
  （UTC 2026-09-08 18:22:28 / 18:23:01，時間由執行環境回報）。

透過既有 Backend 執行唯讀程序，使用它正常配置的 PostgreSQL／Neo4j 連線；
未複製、列印或另行取得 Secret。CHG-292 projection/read 模組只載入該程序記憶體，
沒有寫入 Pod 檔案、替換運行程式或重新啟動服務，並停用 Python bytecode 寫入。
沒有載入 FastAPI 主入口或啟動背景工作。

PostgreSQL 連線設定 `default_transaction_read_only=on`，交易使用
`REPEATABLE READ, READ ONLY`，實際確認 `transaction_read_only=on`，最後 rollback。
Neo4j 僅呼叫 `execute_read` 及 scoped MATCH 查詢；未呼叫 reconcile/apply。
目前皆非已發布 scope，因此只用共用 builder/read path 做候選與歷史觀察，**没有繞過
正式 apply 工具的 published/lifecycle guard**。

第一次啟動遇到唯讀查詢字串的 SyntaxError，在連線／查詢前即終止；修正本機臨時
盤點程序並先做語法驗證後，兩次成功執行結果一致。最初 sandbox 阻擋 cluster 連線，
改走核准的工具權限程序後取得唯讀連線；沒有繞過 Kubernetes 或資料庫授權。

## PostgreSQL 現況

| 文件 | 文件狀態 | 版本狀態 | 切片（active / deleted） | 文件標籤關係 | active 切片標籤關係 | published_at |
| --- | --- | --- | --- | --- | --- | --- |
| DOC-000001 | deleted / is_deleted=true | failed | 0 / 0 | 0 | 0 | null |
| DOC-000002 | deleted / is_deleted=true | submission_ready | 26 / 1 | 8 | 107 | null |
| DOC-000003 | inactive / is_deleted=false | submission_ready | 11 / 0 | 8 | 53 | null |

- 共 3 份文件、3 個版本；未刪除文件只有 DOC-000003，目前可以送審，但尚未發布。
- 全專案 canonical Tag rows：115；所有本次讀到的 assignment source 為 `llm`。
- 全專案共 38 個 Chunk rows，其中 37 個 `status=active`。**Chunk 的 active 並不代表
  文件有效或已正式發布**；其中 26 個屬於已刪除的 DOC-000002。
- DOC-000002 的已刪除切片另保留 4 條標籤關係；本次沒有刪除，canonical 有效切片
  graph projection 不納入這 4 條。
- ActiveVersionManifest：0；`published_at IS NOT NULL` 的版本：0。
- GraphSyncJob：DOC-000002 有 3 筆 `completed`。不能以舊 job 狀態替代正式發布證據。
  舊版 `chunk_artifacts.py` 本來會在 candidate reconciliation 呼叫
  `sync_candidate_version` 並建立 completed GraphSyncJob，與本次現象相符；本次未
  以工作狀態推斷任何版本已發布。

精確 scope：

| 文件 | Document ID | Version ID |
| --- | --- | --- |
| DOC-000001 | `86905746-948c-415d-81e7-2ac4c70cf9ec` | `4abdc8c3-5c58-49d3-bbc4-2658b92bf565` |
| DOC-000002 | `af3abea0-8c90-43bf-b367-875fcbb8eb2d` | `98050420-1be2-401c-9209-53ab271681b8` |
| DOC-000003 | `70691d4d-8111-4425-ab64-5e3237e06421` | `ce1c4c6a-ff64-4dfb-9535-fb8c608e8f65` |

## Neo4j 實際差異

| 文件 scope | PostgreSQL 有效切片投影 | Neo4j 觀察 | 解讀 |
| --- | --- | --- | --- |
| DOC-000001 | 3 節點、2 結構邊，無標籤 | 僅共同 Project 節點，無該版本關係 | 失敗且已刪除；不應補成正式圖。 |
| DOC-000002 | 110 節點、143 邊；其中 81 Tag、8 VERSION_HAS_TAG、107 CHUNK_HAS_TAG | 相同節點與邊 identity 集合；0 缺漏、0 額外 | 舊候選圖仍存在，但 metadata 與新契約不一致，且已刪除、未發布。 |
| DOC-000003 | 73 節點、74 邊；其中 59 Tag、8 VERSION_HAS_TAG、53 CHUNK_HAS_TAG | 沒有該 Document/Version/11 個 Chunk 的結構或標籤邊 | 尚未發布，不是「正式發布漏同步」；新設計以 PostgreSQL 提供候選預覽。 |

DOC-000003 的 identity lookup 找到共同 Project 與 27 個已存在的共用 Tag，**這不表示
它有 27 條標籤關係**；其版本 scoped edge count 為 0。這些共享節點不可當作它的已發布
圖譜證據，也不可為補同步而刪除。

DOC-000002 的差異限於比較契約中的 properties／receipt：

- 29 個節點 properties 不同：Project.name；Document.project_id/source_type；
  DocumentVersion.project_id/document_id；26 個 Chunk.project_id/document_version_id。
- 115 條標籤邊 properties 不同：source、created_at、llm_model_id、prompt_version、
  system_prompt_content_hash 各在 107 條切片邊及 8 條版本邊上不同。
- 三個版本皆沒有 CHG-292 graph_source_digest receipt。
- 此處只記錄欄位差異計數，不輸出名稱、原文、prompt、憑證或 Provider response。

三個 scope 都不是 formal sync eligible。比較結果 `ready=false` 指「不符合
CHG-292 正式投影契約」，**不是要求把候選資料立即寫入正式 Neo4j**，也不是既有
OpenSearch 對話功能的健康檢查結果。本次未執行 Provider 或提問測試。

## 可重現摘要

兩次成功讀取的 scoped PostgreSQL metadata/count inventory SHA-256 相同：

`26d7d453deb6339b512ee36fae70cf515668bc419a0b0eff18aabbf38f332e7f`

此摘要只涵蓋本報告的 project、文件／版本狀態、manifest、切片狀態計數、Tag 計數、
assignment source/count 及 graph-job status/count；**不是全部 application rows 或
protected resources 的完整保存證明**。本次未讀取其他專案或模型／身分／向量內容。

| 文件 | Canonical source digest | Neo4j target digest |
| --- | --- | --- |
| DOC-000001 | `f3eff674bbbbceba123e77c289b2b3c1a0f0b846df1ad1e26daddf91f2f9b297` | `f1534bec217373aa012bbaa44cf82e35683ffa02a58f9ebcccaddb4b926db452` |
| DOC-000002 | `e41b2fa1303e9d9fbd8ed9964e7acb0fe8e91f844e46f6a15412f75c9da70ddc` | `96f4bc468ac766c68cf03c639785d390a39040f50da3c533380185377c87ad2c` |
| DOC-000003 | `a4778ab13645d5960d5491256f0c89ca49996b0d3fec40718c1b60d9c3715810` | `3fc7ebcca571c6fc453e3fb80482487903fb36697cf214ca3894954d6557a477` |

以上不是 apply 授權；未發布／已刪除 guard 仍必須拒絕 apply。source/target 摘要在兩次
成功比對中均相同，不宣稱跨資料庫原子快照或未來持續不變。

使用的本機模組 SHA-256：

- graph_projection.py：`0420ee9826cb256079660f16ee2ab0821eab4b99704cecf14543be783b0539b6`
- graph_reconciliation.py：`67d21dccd30ab455d08f074d0045d094f5cbb831ec1714c994438191cd17b2af`

## 後續建議及停止邊界

1. **本次既有已發布資料補同步清單為空。** 保留已刪除文件及其舊圖譜，不藉機清除或
   復活。未發布 DOC-000003 不應透過維運工具繞過送審／發布。
2. 後續可另行核准 Backend／Frontend 映像建置與 hidden-Secret deployment dry-run；
   CHG-292 不需要 SQL migration，應保留目前 Migration image，不順帶套用待處理的
   CHG-291 V049。精確 runtime/image/render baseline 需在該階段重新確認。
3. 實際部署需另行核准；全庫 coverage、完整 Backend 與登入後 Browser acceptance
   等既有驗收缺口並未因這次盤點而解除，參見 CHG-292 實作驗證報告。
4. 在新版部署並通過相應驗證後，DOC-000003 應走正常送審／發布流程，再比對正式
   Neo4j 的 UUID、8 條版本標籤關係及當時 canonical 切片標籤關係。數量以發布當時的
   受核准快照為準，不硬編目前 53 條。此次授權不包含實際送審、發布或資料寫入。
5. 即使圖譜基礎完成，現有對話／API 也不會自動改用 GraphRAG；那是之後的獨立需求。

本次只讀取 cluster/release/Pod identity 與授權範圍的資料，沒有執行任何 apply、DDL、
Job creation、build、deployment、re-embed、reindex、manifest switch 或 Provider call。

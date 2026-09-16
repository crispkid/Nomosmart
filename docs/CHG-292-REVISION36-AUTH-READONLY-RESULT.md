# CHG-292 revision 36 登入後唯讀驗收

日期：2026-09-09 23:34 至 2026-09-10 00:01（Asia/Taipei）。
依 Peter 已核准 revision-36 scope，以及後續「已登入」交接執行。
規格 10.49 / GRAPH-009..013 未變更；沒有產品程式變更或再次部署。

## 結果與證據

使用 Chrome 原有 Chu Peter session，經正常頁面操作觀察真正的 Backend API
回應；未擷取 token、cookie、密碼或另行建立測試登入。

| 唯讀檢查 | 實際結果 |
| --- | --- |
| MAAS 專案正式圖譜 | HTTP 200；API 0 nodes / 0 edges。UI 明確顯示「目前沒有可 serving 的 active published graph」。畫布仍保留 1 個專案佔位節點，並非 Neo4j 正式節點。 |
| 未發布文件 v1.0 預覽 | HTTP 200；73 nodes / 74 edges；node_limit=500，truncated=false。僅目前版本 `ce1c4c6a-ff64-4dfb-9535-fb8c608e8f65`。 |
| 預覽資料組成 | Project / Document / DocumentVersion 各 1、11 Chunks、59 不重複 Tags；53 CHUNK_HAS_TAG、8 VERSION_HAS_TAG、11 VERSION_HAS_CHUNK，其餘兩條為文件結構關聯。 |
| UI 與關聯互動 | 顯示 11 個切片、59 個標籤；OpenTelemetry 技術 ID `b723a77d-19c1-490e-9091-8e0a7766bc89` 只出現為單一標籤，可連到 #8、#11 兩個切片。點選相連 #8 能查看原始顯示 Markdown 與相同 Chunk UUID。 |
| 來源與完整性 | Tag IDs 均為 `tag:<UUID>`、所有 node IDs 唯一、74 條 edges 的兩端都存在。類型／數量符合先前 PostgreSQL canonical inventory。未宣稱逐一比對全部關聯 metadata/hash。 |

上述兩個 GET 路徑與安全結果記錄在
`CHG-292-REVISION36-AUTH-READONLY-EVIDENCE.json`。
未保存完整文件本文、認證 headers、refresh response 或敏感設定。

正式圖譜為空是目前 **0 published versions / 0 active manifests** 的正確結果，
不是自動把候選預覽發布到 Neo4j。文件 GET 的 `allow_preview=True` 路徑在
`published_at is None` 時讀取 PostgreSQL canonical projection；正式讀取
仍需真正 Neo4j projection。這次沒有正式發布、同步或修復 legacy 圖譜。

## 無資料修改驗證

既有唯讀腳本在登入後、頁面操作前與完成操作後執行：

```bash
python3 /tmp/chg292-deploy.6QQQ7Q/run_readonly.py data 36
```

真實服務快照時間為 2026-09-09 15:34:03 與 16:00:34 UTC。
PostgreSQL 使用 READ ONLY transaction；比較結果：

- 59 張表的完整 count/hash 全部一致；合併 SHA-256：
  `83ade9ffbb56ee4c4ecdfa58c82b227b9315bce3fc269b2f99809fb6b1d78b16`。
- 業務表、schema/constraints、使用者／權限、Chat／usage 均未變更。
- Neo4j metadata SHA-256 前後相同：
  `430dfbd5d005a5172e5633acc9bcdd8089b6523c84afd1c57d6af0b9ae138dc7`。
- OpenSearch SHA-256 前後相同：
  `136a8f44c4ff6c5fd98fea7ee6150b5516dbb16bc543f49417f55a4d688d450e`。

沒有 Helm/Kubernetes write、Job、圖譜 repair、角色／成員修改、Provider、
reprocess、re-embed、reindex 或 manifest switch。使用者原頁面保留在圖譜預覽。

## 限制與異常紀錄

一次 native browser-control 呼叫異常等待約 1,400 秒；改用支援的 browser
DOM controls 後操作正常。等待後 host readiness 為 200（約 0.216 秒），
不能據此認定應用程式停機或宣稱修復服務。沒有因此重啟或修改任何服務。

此結果只完成現有 session、現有資料的唯讀部署驗收；不等於完整 T18：
本地無 published version，未演練 published-tag readonly、缺失正式 projection
503、其他身分拒絕路徑或正式發布流程。這些與 full coverage、image scan/SBOM
及 production release gates 仍維持原紀錄，沒有放寬或以靜態檢查替代。

文件更新後 `spec:doctor`、`spec:trace`、`plan:approved` 及
`git diff --check` 均 PASS。核准 scope SHA-256 仍為
`1b849edbdabc1aeac3cd7f7f16c60bdd0a7ab3274d4e6fa84cb065843981219f`。
本次安全 JSON 證據 SHA-256 為
`1a6d029d5884a456978c343dcf85ae01a39e7c81ef56efd736874831b3da73a6`。

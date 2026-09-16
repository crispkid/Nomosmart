# CHG-291 R3：結構差異證據與備份工具修正範圍確認

2026-09-13。回應 Peter「下一步」。本文件為 Gate 1 理解與討論，
Peter 隨後以「繼續」確認此範圍，2026-09-13 **Gate 2 confirmed**；
Gate3見 `docs/CHG-291-V049-R3-PLAN.md`。Peter於2026-09-13要求連續完成準備、
部署前再確認，Gate4已核准；實作及隔離驗證詳見R3結果，範圍未擴大。
依 SPECIFICATION.md §10.57 V49-U002..U007 及 R2 結果提出，
不重用已消耗的 R2 真實 archive restore claim。

## 已知事實

- R2 真實 archive 還原成功，62 表／1,341 列完整內容與原 snapshot 一致；
  properties、參照角色、sequences、large objects 一致，schema hash 不同。
- archive 重建 SQL 與還原後 pg_dump 的 COMMENT 區塊數為11／12；
  這不是原 schema 全文字面的比較，也未證明哪個物件或唯一原因。
- DatabaseState.schema_hash 只保存整體 SHA；collect 未另存完整物件註解、
  extension owner／版本等逐物件證據。參照角色集合相同不能代替 ownership 相同。
- diagnostic_schema 僅產生安全的分類總數；R2 原文只在記憶體，容器已清理，
  不能從現有安全摘要反推出已丟棄的逐物件差異。
- PostgreSQL pg_restore 文件明言工具無法還原 archive 不含的資訊，且其
  no-owner／no-acl 會改變還原權限語意；不能用這些選項換取 PASS。
  來源：[PostgreSQL 18 pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)。

## 建議確認的範圍

1. 僅修改備份／診斷工具、其測試與規格追蹤文件，不修改產品 API、Migration、
   Frontend、應用資料或 Helm。候選需求 V49-U008 須經確認再寫入正式規格。
2. 補足可追溯的逐物件比較，分開辨識定義、註解、owner／ACL、extension
   metadata。保留原 schema hash 作為證據；不以總數、空白正規化或忽略所有
   COMMENT 取代語意正確性。業務內容、完整 SQL／註解原文仍不寫一般 log。
3. 先在自建真實隔離 PostgreSQL 重現有／無／空註解、預設與重新建立的
   物件，以及 extension owner 不同的情況。區分「文字表示差異」與「實際
   還原內容／權限差異」，不要預設真實備份就是 public schema 或 plpgsql 問題。
4. 有證據後才做最小工具修正；物件定義、資料、註解與權限真的不同仍須失敗。
   若需要更動還原權限、增加 SUPERUSER、直接改 system catalog 或改用新
   還原策略，停止提出精確方案，不能隱含於「修正工具」中執行。
5. 新證據格式需明確版本化，缺乏原始證據的舊備份不能自動補造或升格合格。
   原失敗測試保留；以真實修正通過，而非刪除、skip、xfail 或放寬門檻。
   工具完整測試與原80%資格要求保留；此範圍不默認授權為補coverage讀取現行來源。

## 明確不包含

- 讀取現行 Kubernetes／DB、重新備份、讀取／重驗真實 archive 或改其 claim。
- 更改原 FAILED／歷史證據、宣告原備份可用、套用 V049、建立 Job、映像或部署。
- Provider 呼叫、掃描、索引／權限／會員修改、任何現行停寫／資料修補。
- 推定目前 DB 等同原匯出 snapshot，或承諾工具修正後舊備份一定合格。

## 已確認範圍

Peter以「繼續」同意以上「備份工具與自建隔離測試」作為 R3 範圍。
已依序寫開發／測試計畫並提交 Gate 4；不擴大為另一輪真實資料操作。

本理解文件首次交付時僅閱讀程式、規格、既有安全報告與官方公開文件；未執行 feature tests，
未建立容器、未開啟真實 archive、未存取現行服务、未改 Python 程式。

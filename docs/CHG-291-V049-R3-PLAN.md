# CHG-291 R3 Object-level Schema Evidence And Fail-closed Verification

2026-09-13。Peter 以「繼續」確認 R3 理解文件中的「備份工具＋自建隔離
測試」範圍，Gate 2 confirmed。本文件為 Gate 3。Peter 隨後要求「繼續，
一直到部署的那一步停下來跟我確認，中間都不要再停下來了」，核准此書面
計畫，2026-09-13 **Gate 4 approval: APPROVED**。連續執行已核准準備，
實際部署前停下確認；不重複詢問已核准範圍，也不跨越資料／權限保護邊界。

## 1. 結果與邊界

本輪修正已證實的工具缺口：只存整份 schema hash，無法定位逐物件差異，
且缺乏獨立 extension owner／註解證據。不預先宣稱 R2 真實差異是無害註解、
public schema 或 plpgsql，也不承諾原 T15 或既有備份一定轉為合格。

完成後應可指出自建案例中哪個物件的定義、註解、owner、ACL 或 extension
metadata 不同；輸出安全的穩定識別／變更欄位／digest，而非完整 SQL。
保留資料、六類比對、raw schema hash、source drift、資格與清理門檻。
既有 schema hash 不同仍不能自動變 PASS，即使新增 catalog 比對相同。
如要改成另一種合格判定，必須先提供完整覆蓋證據並另議，不臨時忽略差異。

## 2. 修改範圍

- `backend/scripts/chg291_v049_live_backup.py`：新增 SchemaEvidence 概念，
  分離收集、證據驗證、差異計算與安全輸出；沿用 Snapshot、custody、bounded
  process、MemoryPostgres、cleanup 及既有六類 DatabaseState。
- `backend/tests/test_chg291_v049_live_backup.py`：真實 PG／CLI／檔案正負向
  案例與自動 coverage。保留舊案例，不刪除／xfail／skip 既有失敗測試。
- 規格、changelog、plan、test、trace、結果／六項收尾文件。
- 不改其他 product modules、API、DB schema、SQL migration、Frontend、
  Dockerfile／dependency／image、Helm 或 Kubernetes resources。

## 3. 證據資料契約

1. 保留原 `snapshot.json` 六類格式與舊資料讀取路徑。新增獨立私有
   `schema-evidence-v1.json`，不改寫／回填任何舊檔案。
2. sidecar 包含明確 format/version、收集器版本、PG version、同源 tool/test
   與固定 image、原 snapshot canonical SHA、archive SHA/bytes，以及
   completeness 和逐物件分類。由同一 readonly snapshot 收集；不能將不同
   transaction／文件／工具版本的 metadata 拼成原始來源證據。
3. 在 `export_database` 的既有 snapshot 期間收集，完成 archive 後綁定寫入
   sidecar；函式既有 archive/state 回傳形狀盡量不變。新證據以明確參數或
   私有 reader 傳入 verify 路徑，不能從目前 DB 補造舊來源值。
4. 新版本完整資格必須要求同源、完整、hash-bound sidecar；未知 version、
   缺件、替換、部分收集、未知物件 coverage 或來源漂移皆 fail closed。
   歷史版本可讀、可報告 evidence_unavailable，不是可重新宣告合格。
   R2 固定四檔 reader／claim 保留，不因此重新開放真實 archive 操作。
5. raw schema hash 與原六類 evidence 獨立保留。新增逐物件資料不能代替
   完整性檢查，也不能只比新增／刪除數量。
6. sidecar不可只靠自含digest驗證自己。匯出當下在archive handle保留sidecar的
   canonical digest及file identity，verify／finalize重驗；重新計算被改動檔案的
   自含digest或以相同內容替換inode仍拒絕。這是既定替換防護的實作方式，
   不新增可把歷史檔案或跨程序缺證據資料升格合格的入口。

## 4. Catalog 收集與差異方式

- 使用真實 PostgreSQL catalog／pg_get_* 定義取得結構；SQL dump header
  regex 只可作輔助線索，不當作完整 SQL parser 或語意真相。
- 物件鍵為 class／schema／name／必要簽章，OID 僅在同 snapshot 解析成穩定
  關聯；不跨叢集用數值 OID 作物件身分。不可因此丟掉 dependency／owner 關聯。
- 支援面至少涵蓋目前工具宣稱可完整處理的 schema、table／column／partition、
  sequence、view／materialized view、type／domain／enum、routine、constraint、
  index、trigger／rule、policy／RLS、default privilege 及允許的 extension。
  每個覆蓋類別需實際盤點；無法完整描述的類別標記 unsupported／incomplete，
  不靜默排除、不假定空集合、不聲稱完整資格。
- definition digest、comment 的 absent/null/value 狀態與 digest、owner、
  grants／grantor／grant option、extension name/version/schema/owner/member
  identity 與可用的初始物件證據分開記錄。ACL 的預設／顯式狀態和有效 grants
  均保留；不把它們或 extension owner 自動歸一成隔離帳號。
- 比較新增／缺失物件及逐欄位差異。缺少證據顯示 UNAVAILABLE/ERROR，實際
  不同顯示 DIFFERENT。schema text 不同但已覆蓋 catalog 相同只能標記
  representation_difference_candidate，整體仍不得宣告合格。
- private evidence 可含必要 catalog identity；repo／一般 log 使用有界物件
  key digest、類別與變更欄位，不輸出業務物件名稱、SQL、註解、function body、
  單列值或逐列 digest。完整內容只在資料庫端／記憶體計算，不落一般暫存檔。

## 5. 連續執行順序（Gate4核准後）

1. 固定 source/test/image 與本輪唯一私有測試目錄；檢查現有隔離保護。
2. 實作同 snapshot 的物件證據、version/binding、sidecar custody 和安全 diff。
3. 加入自建真實案例，分開重現註解差異與 extension 來源身分差異。
4. 根據證據修正「遺漏證據／錯誤配對／診斷遺失」等工具問題，保留 strict
   compare。物件還原真的不同仍失敗；不藉修測試預期掩飾缺陷。
5. 執行 focused、完整原測試與 coverage，核對 private reports、source binding
   和 exact cleanup；記錄可證明與仍不能證明的事項，停止本輪。

不授權修改 restore owner／ACL 策略、增加還原角色 SUPERUSER、直接 UPDATE
system catalog、過濾／改寫真實 dump、關閉 constraints／triggers 或自動
COMMENT 修補以湊齊差異；如證据顯示需要這些改動，提出精確風險再討論。
測試資料建立時沿用既有隔離 fixture 權限，不能用新的更寬還原權限測成 PASS。

## 6. 測試與驗收

| ID | 真實驗證內容 |
| --- | --- |
| V49-U-T21 | 同 snapshot 的已支援物件 inventory、穩定鍵與逐物件 definitions；實際 column/default/index/constraint/routine/policy 差異可定位，不只比總數 |
| V49-U-T22 | schema/table/column/extension 的有註解、移除、空值、預設差異；定位實際物件及狀態，不預設真實 archive 根因 |
| V49-U-T23 | DB/object/extension owner、直接 grants、grant option、default privileges 的實際差異仍拒絕；保留 T15，不能靠 no-owner/no-acl 通過 |
| V49-U-T24 | version／snapshot／archive／tool/test/image 綁定、舊版缺件／錯誤hash／symlink／替換／不完整／未知物件 fail closed；無回填或原檔覆寫 |
| V49-U-T25 | 惡意 identifier／comment／function body 不成為執行指令或一般 log內容；真正 stream/SQL timeout、大小上限、中斷及清理仍有效 |
| V49-U-T26 | 新 metadata 與原資料／六類／raw-hash／drift gates 一起運作；只有新 metadata 相同但 raw hash 不同仍非合格，DIFFERENT/ERROR 證據於清理前保存 |
| V49-U-T27 | 全套回歸、真實 coverage、來源與報告完整性、exact Docker baseline。原案例／分母與80%門檻不降低；此輪不得觸碰任何現行來源或真實 archive |

使用同一已安裝 image
`sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a`，
Docker context desktop-linux；任何時間最多一個自建 PG、依序 source/restore，
network none、無port／existing volume／Docker socket／host data mount；
2CPU、4GiB memory/swap、pids256、PG tmpfs2GiB／tmp128MiB／run16MiB，
initializer隔離、log none／禁core、fresh合成憑證、exact receipt cleanup。
沿用 source上限256MiB、stream512MiB、單次metadata4MiB、schema32MiB、
SQL10秒／lock2秒、snapshot300秒、還原及比較共用600秒，不重設deadline
無限重试或截斷冒充完整；若測試需要調高資源，先停止說明。

每輪唯一 `/private/tmp/v049-backup-plain-r3-*` 0700，report 0600；
採原真實 pytest/coverage 路徑、關閉 cache，不用 mocks/stubs 或手填成功。
保留 T15 失敗及 human GPG 未執行狀態；不測聊天密碼、不補跑現行 readonly
qualification 取得 coverage。整個備份工具行、分支及合併各80%要求不變，
不足就如實報告；新增邏輯和共用安全邏輯另列量測，但不能替代整體門檻。
缺乏新同源 current readonly 證據時不生成正式 qualified.json，即使局部全PASS。

命令：分別執行 `spec:doctor`、`spec:trace`、`plan:approved`、`test:plan`、
`backend:syntax`、`git diff --check`，再執行 test_chg291_v049_live_backup.py
真實 pytest/coverage（`-k 'not human_gpg'`），保留完整 XML／coverage／cleanup
及 SHA。不直接呼叫會串接現行來源的資格／備份 CLI。

## 7. 禁止事項與交付

不存取現行 Kubernetes／DB／其他現行服務；不讀／重驗 retained archive，
不新增 export、重置 R2 claim、寫原备份目录、不改 FAILED／歷史證據；
不掃描、build/pull images、建 Job、V049、部署、索引、Provider 或使用者權限。
只交付工具與測試差異、合成重現結果、coverage／清理及剩餘根因限制。
此輪不是新復原點或部署許可；六項收尾仍須合格備份及其餘原有門檻。

本輪狀態：Gate4已核准，工具實作及真實隔離回歸已執行。新增31項PASS，
全套93PASS／原T15 FAIL；未通過完整資格，未讀真實archive或現行資料。
詳見 `docs/CHG-291-V049-R3-RESULT.md` 及 EVIDENCE.json。

Gate4核准前的2026-09-13文件檢查：spec:doctor、spec:trace、plan:doctor、test:plan及
git diff --check PASS；plan:approved exit1，明確因R3 Gate4 PENDING停止。
這些是文件檢查，不代表實作、備份資格或部署驗收通過。

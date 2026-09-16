# CHG-301 R2 高風險批次結果

2026-09-16 Asia/Taipei。規格 §10.58 CMPHIGH-001..004。
執行依已核准[計畫](CHG-301-R2-HIGH-PR-PLAN.md)；[機器證據](CHG-301-R2-HIGH-PR-EVIDENCE.json)。

## 結論

**必要回歸已修正並通過；高風險映像修補尚未完成，因此沒有更新 PR。**

- 原211項回歸：重現7FAIL/204PASS，修正後保留全部案例，加上2項目前範圍拒絕檢查。
- 加入34項高風險範圍/真實artifact檢查；最終共247PASS、0FAIL/ERROR/SKIP。
- 新/調整runner的Bandit：0High、0Medium、7Low；原始輸出保留，Low依指示延期，
  未加suppression。這不代表所有候選映像或產品資安都通過。
- Node加12份已盤點映像仍有83個不同High/Critical raw ID，另列1個Critical
  補充公告。按image×ID共221筆未解，**不是已證實221個可利用漏洞**。
- 270筆其他severity只標DEFERRED_BY_SCOPE；未抹除或改成已修復。
- 沒有新漏洞修補成功、建置或掃描候選映像；不能用測試全過代替映像安全通過。

## 已修正的測試問題

舊測試把「當時核准的計畫」與「現在可執行的計畫」混在一起。新計畫成為active時，
安全guard正確拒絕，但舊positive case仍期待成功；另3個archive policy case也被
綁在已退役的執行權限上。

修正方式：

1. 使用真實歷史計畫章節與紀錄時間，驗證當時的接受。
2. 另外驗證目前計畫不能拿舊核准執行；沒有修改guard讓它直接放行。
3. 將archive header/digest的純資料驗證抽成小函式，原受guard保護的實作仍使用
   同一函式。測試直接驗證policy；不造假registry、服務或外部成功。

| 檔案 | 本輪修改 |
| --- | --- |
| backend/scripts/chg301_r2_high_risk.py | 獨立activeplan/hash/期限、唯讀命令範圍、完整raw帳列、官方catalog/tag重核及PR拒絕條件 |
| backend/scripts/chg301_r2_node_qualification.py | 抽出validate_layer_digest/validate_archive_member；原執行核准、時限與非執行限制保留 |
| backend/tests/test_chg301_r2_ingress.py | 歷史接受與當前拒絕分開，不再讓舊接受充當目前核准 |
| backend/tests/test_chg301_r2_node_qualification.py | 相同歷史/當前區分、純archive policy案例、確認退役runner拒絕目前計畫 |
| backend/tests/test_chg301_r2_high_risk.py | 34項真實報告/官方清單及範圍拒絕檢查 |

未修改產品API、Frontend功能、SQL、正式chart或部署設定。

## 高風險為何尚未解決

### 1. 沒找到更高的同系列官方候選

本輪取得每個repo最近30筆官方release紀錄，未找到以下系列更高的相容patch：

| 系列 | 最新觀察到的相容版 | 官方來源 |
| --- | --- | --- |
| kind預建Kubernetes 1.36 | 1.36.4 | [kind v0.33.0](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0) |
| Cilium 1.20 | 1.20.1 | [Cilium v1.20.1](https://github.com/cilium/cilium/releases/tag/v1.20.1) |
| Traefik 3.7 | 3.7.13 | [Traefik v3.7.13](https://github.com/traefik/traefik/releases/tag/v3.7.13) |

另從registry重核Node/Cilium/Operator tag，digest與前輪一致，沒有觀察到同tag
換成新版的情況。這只是有界catalog結果，不聲稱不存在任何未發布映像。

外層OS套件更新不會改變內層Go binary、CoreDNS/etcd/控制平面或CNI相依。
超出minor/major、自行fork/重編Kubernetes不在此次核准內；沒有擅自執行。

### 2. OS可修項尚未建置，不能寫成FIXED

外層原50個高風險ID中，24個屬先前保守的套件版本AFFECTED判定，涉及glibc、
libevent、libssh2、OpenSSL、PCRE2、Perl、SQLite；25項適用性未確定，另1項Perl
32-bit條件已有不適用提案但未獲接受。本輪沒有替換它們或擅自接受判定。

Docker VM總額為8CPU/約31.29GiB，不等於可用餘裕；`kubectl top nodes`回報
`Metrics API not available`，因此沒有證明計畫要求的建置餘裕與工作限額。
沒有為了通過檢查安裝metrics-server、調整VM或停止現有服務。OS payload/solver/
映像建置及最終重掃未執行；原17筆signed-index metadata仍不是完成修補。

### 3. 應用與Ingress證據不能擴大解讀

既有應用dependency/SAST報告的140個來源hash及result hash重新核對一致：npm/pip
production/full當時各0finding；Bandit原本的明列FTP接受與其他raw仍保存。
這是2026-09-15T11:45:50Z的歷史同來源證據，**不是新掃描**，也不能代替尚未
完整完成的候選應用映像掃描。Traefik先前的精確兩項接受没有移植或延長。

## 驗證命令與結果

- 同時執行test_chg301_r2_ingress.py、test_chg301_r2_node_qualification.py及
  test_chg301_r2_high_risk.py：`pytest --noconftest -p no:cacheprovider -c /dev/null`，
  使用原計畫各私有artifact root，未import應用/連Provider；247PASS，13.12秒。
- `bandit --ignore-nosec -f json`兩支runner：exit1，7Low、0Medium/High、無掃描error。
- `./HARNESS/harness.sh spec:doctor`、`spec:trace`（30 mappings）、`plan:doctor`、
  `plan:approved`、`test:plan`、`backend:syntax`、`helm:lint`、`deploy:config-policy`皆PASS。
- `COMPOSE_DISABLE_ENV_FILE=1 ./HARNESS/harness.sh docker:config` PASS；
  harness使用`config --no-env-resolution --quiet`，沒有读取operator.env。
- `git diff --check` PASS。全應用coverage、完整E2E、Kubernetes驗收均未做，依指示延期。

## 保護、清理與證據限制

- 私有run：`/private/tmp/chg301-r2-high-w4fccj_d`，0700；保留約4.4MiB公開metadata/
  帳列/測試log。沒有新容器/網路/映像或短期credential需要刪除，未刪任何現有資源。
- 14個既有容器ID/狀態/啟動時間/重啟數、image inventory、network inventory前後相同。
- 舊source snapshot唯一變更是ingress測試；本輪新/改runner及其他tests另列SHA。
  產品source不變；沒有資料/索引/Secret/角色/Provider操作。
- 首次唯讀Docker連線被sandbox拒絕，取得正常工具權限後才重試，失敗log保留。
- 未量測VM可用RAM；本輪未做重建，不宣稱heavy-work門檻通過。原始掃描時間不變。
- 原計畫與原始scan/JUnit報告均保留，本報告不覆寫舊結果；没有新增高風險豁免。

## PR 狀態與必要的範圍決策

PR #1仍為原head `c261a494283835af57c0e0678afc7ee7e2c0dcc8`；沒有commit/push/PR
description更新、合併或部署。唯讀PR查詢當時沒有GitHub check結果，不能視為綠燈。

Peter已同意延後「完整coverage/Kubernetes實測」，但這次書面計畫仍把已盤點的
**未啟用隔離測試基礎映像High/Critical**列為PR前置。這些尚未解除，所以PR gate拒絕。

若目標改為先交付應用PR，可以另行確認：是否把「尚未啟用的隔離Kubernetes測試
基礎映像修補」也列為延期，保持它們不啟用、保留高風險證據，與NomoSmart應用
候選的安全/必要回歸門檻分開。**尚未獲此範圍核准，未自行採用，也不是風險已消失。**

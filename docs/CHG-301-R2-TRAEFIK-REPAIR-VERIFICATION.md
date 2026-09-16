# CHG-301 R2：固定測試映像的真實修補前檢查

2026-09-15；Peter已明確核准書面修補計畫。結果：**BLOCKED_SCOPE_AND_ANALYSIS**。
沒有建置或啟動controller，沒有Kubernetes／應用資料／Provider／PR操作。
原12advisories的報告原樣保留；不是修補完成或完整R2驗收。

## 實際查到什麼

| 項目 | 實際證據及判定 |
| --- | --- |
| 三個APK | 官方Alpine3.24/aarch64的3.5.8-r0全部可取得。從固定原image取得官方signing key，獨立驗證RSA簽章、control/datahash及signed index的Q1 checksum、版本、架構、大小。沒有額外套件依賴，尚未套用。 |
| 原始OCI內容 | 驗證ARM64 manifest、config、每層blob SHA及未壓縮diffID，在記憶體重建effective rootfs，不啟動或extractall。實際18個APK；`libssl3`與`libcrypto3`為3.5.7-r0，**沒有openssl套件或/usr/bin/openssl**。所有四層也沒有該執行檔。 |
| 與先前SBOM差異 | 原Scout列21個APK entries，包含openssl、alpine-base、pax-utils，不能直接把這份清單當成installed database。保留兩份證據，不自行編造差異成因。先前把openssl當成已安裝套件的規劃假設已被實物檢查否定。 |
| 三套件方案停止 | 原核准是升級既有三套件並保持其餘內容，直接安裝openssl將新增執行檔，與最小修補前提不符。`validate_repair_scope`根據實際installed database回`approved_upgrade_package_absent`。沒有默默新增套件或自行改成兩套件建置。 |
| Traefik binary | SHA綁定的ELF為Linux/ARM64，無PT_DYNAMIC／PT_INTERP；Go build info可讀，編譯Go1.26.8。這不能單獨豁免image中的OpenSSL函式庫漏洞。 |
| OpenPGP GO-2026-5932 | govulncheck1.8.0 JSON exit0且聲稱symbol scan；但`-mode=extract`實際取得**0個symbols**。固定工具原碼binary.go明確在此情況改用module-level、產生所有已知package/symbol占位符。所以報告的七組package/wildcard不是實際可達性證據。**INDETERMINATE，不可認定受利用，也不可認定誤報。** |
| Docker CLI CVE-2025-15558 | binary實際依賴v29.7.2+incompatible，Linux/ARM64；官方advisory描述Windows plugin路徑，Go DB記錄修正於29.2.0+incompatible。僅提議PROPOSED_NOT_AFFECTED，**未套用VEX或風險豁免**。 |

[Docker官方advisory](https://github.com/docker/cli/security/advisories/GHSA-p436-gjf2-799p)、
[Go OpenPGP公告](https://pkg.go.dev/vuln/GO-2026-5932)、
[govulncheck工具文件](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)、
[Alpine APK格式](https://wiki.alpinelinux.org/wiki/Apk_spec)。

## 來源／工具與測試

完整固定hash與來源見[機器證據](CHG-301-R2-TRAEFIK-REPAIR-EVIDENCE.json)。
原image index為f86a2cab…e91259、ARM64 manifest444bb54c…16baa；binary
7415b615…8788ca；三個APK、tool module與binary SHA均已记录，不使用latest。
原dirty來源manifest與最後比較，只有本次test runner/tests變動，產品來源不變。
govulncheck用既有Go1.26.5＋GOTOOLCHAIN=local私有安裝，沒有改host Go或應用依賴。

| 驗證範圍 | 結果 |
| --- | --- |
| 原28guard＋新30真實artifact/policy/CLI guard | **58 PASS，0FAIL，0SKIP，5.06秒**；沒有mock scanner或偽造成功簽章。 |
| CMPPATCH-T01/T02 | 固定OCI/APK、路徑拒絕、錯誤manifest/key、簽章/datahash、版本/架構/額外dependency拒絕等已證明。原image沒有whiteout；所有複雜layer edge cases尚未完整驗收。 |
| CMPPATCH-T03/T06 | 真實binary/Go分析與不足能力拒絕已證明；保留raw告警。修補後image重掃NOT RUN，不能標FIXED。 |
| CMPPATCH-T04/T05 | 離線建置、builder sandbox／資源強制限制及修補後rootfs/config差異驗證NOT RUN；scope gate先阻擋。沒有建立Dockerfile以暗示可建置。 |
| CMPPATCH-T07 | 局部guard通過；controller version/help smoke NOT RUN。 |
| CMPPATCH-T08 | 未核准phase／缺opt-in／錯誤approval拒絕，精確cleanup與原基線比對已完成；完整build failure cleanup待後續。 |
| 完整R2 | Frontend/Backend全來源80%、完整suite、Kubernetes/TLS/OIDC/NetworkPolicy及PR更新仍未完成。 |

最終測試命令（isolated pytest9.0.3，停用自動plugins、不讀app conftest）：

```text
env -i PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  PYTHONPYCACHEPREFIX=/private/tmp/chg301-r2-repair-tests-cynqgZ/pycache
  CHG301_R2_CANDIDATE_EVIDENCE=/private/tmp/chg301-r2-traefik-vtkgc8jt
  CHG301_R2_REPAIR_EVIDENCE=/private/tmp/chg301-r2-repair-8tn60fwz
  /private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python -m pytest
  -c /dev/null --rootdir=. --noconftest -p no:cacheprovider
  --basetemp=/private/tmp/chg301-r2-repair-tests-cynqgZ/cases
  --junitxml=/private/tmp/chg301-r2-repair-tests-cynqgZ/junit.xml
  -q backend/tests/test_chg301_r2_ingress.py
```

前置一次Buildx自訂template不支援Driver欄位；已改讀JSON並僅保存去敏感識別，
同原因修正重試一次成功。失敗證據保留於private repair-c5vyorw8，沒有隱藏失敗。
完成source/inspect/analyze/assess/cleanup階段，repair/rescan/smoke仍拒絕執行。
收尾`spec:doctor`、`spec:trace`（21個active需求）、`plan:doctor`、
`plan:approved`、`test:plan`與`git diff --check`全部通過。
規格§10.58 CMPPATCH只完成上述部分，不將局部guard成功標成release PASS。

## 清理與現行環境

精確移除本輪新增且無容器使用的Traefik digest引用，以及約166MiB私有Go編譯cache；
未force/prune，不刪任何原有image/cache/network。保留0700目錄中的公開APK/OCI/
非執行binary、工具來源與報告供重現。這些公開暫存可重新下載，不影響資料復原。
容量probe已精確移除；最後14個原容器的ID/status/start/restart數、網路及image
inventory與原基線相同。沒有建置器/VM/current Kubernetes設定更動。

## 需要確認的最小調整（尚未執行）

後續Peter已回覆「同意」確認以下範圍（Gate2）。
[兩函式庫修訂計畫](CHG-301-R2-TWO-LIBRARY-PLAN.md)現已獲Peter明確核准，Gate4 APPROVED；
此補記不改寫本報告原始測試／停點證據，也不代表已執行新的修補。

建議把修補範圍改為**只升級實際存在的libssl3與libcrypto3至3.5.8-r0**，
不新增openssl指令；OpenPGP仍維持阻擋，不豁免、不啟動controller。
確認方向後再更新原計畫的兩套件範圍與驗證條件。查明OpenPGP需可追溯同一binary
build的符號／來源證據，不能用main、strings無命中或另一個重編binary替代證明。

最新唯讀發現：保留world的apk離線升級需要本機signed index；原材料清單只有
recipe與兩APK，尚不能額外带入索引。已在兩函式庫計畫§6記錄固定來源、索引SHA
及待確認的有限材料調整。沒有建置、改runner/tests或覆寫本報告的58PASS實物證據。

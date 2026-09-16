# CHG-301 R2：兩函式庫修補與驗證結果

2026-09-16（Asia/Taipei）。本輪狀態：**LIBRARIES_REPAIRED_SECURITY_BLOCKED**。
已完成核准的兩函式庫修補、真實逐檔比對、完整Scout/SPDX重掃及94項guard回歸。
**這不是Traefik服務安全放行、Kubernetes驗收通過或完整R2完成。**
核准範圍：[官方索引補充計畫](CHG-301-R2-SIGNED-INDEX-PLAN.md)；
完整SHA／測試／清理紀錄：[machine evidence](CHG-301-R2-TWO-LIBRARY-EVIDENCE.json)。

## 修補結果

| 項目 | 結果 |
| --- | --- |
| libcrypto3、libssl3 | 均由3.5.7-r0升級至固定官方3.5.8-r0；RSA簽章、SHA256、signed index/Q1綁定通過。 |
| 實際套件 | 仍為原18個套件，其他版本及其完整安裝metadata不變；沒有安裝openssl或新增/usr/bin/openssl。 |
| 有效rootfs | 只改7個已簽章函式庫檔案與`lib/apk/db/installed`，共8個path；沒有額外檔案／owner／mode差異。 |
| 原始設定 | world、CA trust、Traefik binary、entrypoint、runtime config及repository設定全部不變。 |
| 歷史layers | 原4層保留；沒有squash、ignore-base或隱藏原層。 |
| 建置隔離 | 真實RUN驗證1CPU、2GiB cgroup硬限制；只有loopback啟用／IP／route，RUN與apk均禁用網路。沒有host/insecure entitlement或Secret mount。 |

唯一保留測試映像：

```text
nomosmart-test/traefik:3.7.13-chg301-r2-say0hh9k
sha256:5043ce31721c19e4a3a18afd60f449a7c842d46a52ec1ed6d7fdfb84a68cf7cd
```

這是local-only衍生測試映像，不是官方新發行或正式部署核准。Image ID與manifest
digest相同，platform為linux/arm64；實際build metadata及saved OCI交叉驗證。

7個變更library：`libcrypto.so.3`、`libssl.so.3`、engines-3內的afalg/capi/
loader_attic/padlock及ossl-modules/legacy。逐檔前後SHA／uid／gid／mode見機器證據。
CA trigger確實執行，但最後CA檔案、symlink及metadata沒有差異。

## 安全掃描：10項已修補，2項仍阻擋

| Raw severity | 修補前 | 修補後 |
| --- | ---: | ---: |
| Critical | 2 | 0 |
| High | 8 | 1 |
| Medium | 1 | 0 |
| Unspecified | 1 | 1 |
| Advisory合計 | 12 | 2 |

完整Scout1.24.0 SARIF/SPDX與實際library內容共同證明原10項OpenSSL告警已移除，
沒有新增告警。未使用ignore-base、suppressions或VEX，原始掃描與lower-layer證據保留。
Scanner SBOM依然列出openssl source entry，但實際installed packageDB與rootfs均
沒有openssl套件／執行檔；不把SBOM entry誤稱新安裝套件，也不臆測差異成因。

| 剩餘項目 | 判定與限制 |
| --- | --- |
| CVE-2025-15558（High） | 仍為PROPOSED_NOT_AFFECTED。原公開公告的Windows條件與修正版資訊、此binary的Linux/ARM64及docker/cli29.7.2證據保留。尚未取得具體排除／VEX核准，不自動忽略。 |
| GO-2026-5932（Unspecified） | OpenPGP仍INDETERMINATE。同一Traefik binary的symbol extraction為0，不能證明安全或可利用；此次library修補沒有改變這點。 |

因此**沒有執行Traefik version/help、沒有啟動服務或建立測試Kubernetes叢集**。
後續需處理上述判定／證據問題，不能因OpenSSL已修補就視為整份映像安全。

## 測試與靜態檢查

- 最終 **94 PASS、0 FAIL、0 ERROR、0 SKIP，10.84秒**。pytest9.0.3，停用
  自動plugins及app conftest；使用真實官方OCI/APK/index、實際建置／scan及檔案。
- 原58PASS歷史證據保留，未刪除案例或降低80%門檻；新增exact context、錯誤key/
  digest、只升級兩套件、solver額外變更拒絕、原檔／config變造拒絕、optional
  config-digest exporter、目前核准不可被舊APPROVED代替等案例。
- 建置前72PASS／11deselected只測prebuild guards；後續83PASS、92PASS後再加入
  SHA256/Q1 guard成94PASS。最終全套沒有deselection或skip。
- Bandit1.9.4全檔、`--ignore-nosec`：初掃2High/1Medium/8Low。Q1 helper已補強為
  **自身先強制檢核完整APK的核准SHA256**，之後SHA1僅產生舊索引識別碼，不能作
  安全接受依據；錯誤bytes或未核准檔名會在SHA1計算前拒絕。重掃0High/1Medium/
  8Low，兩份raw結果都保留，不是風險豁免或只加nosec。原RSA-SHA1簽章相容性
  Medium及subprocess相關Low仍在報告內；raw exit1不被宣稱全零告警。
- 這94項是本次artifact／tool guard測試，**不是Frontend/Backend全來源coverage**。
  完整80%、產品critical flows、Kubernetes/TLS/OIDC/NetworkPolicy及完整R2仍未完成。

最終測試命令：

```text
env -i PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1
  CHG301_R2_CANDIDATE_EVIDENCE=/private/tmp/chg301-r2-traefik-vtkgc8jt
  CHG301_R2_REPAIR_EVIDENCE=/private/tmp/chg301-r2-repair-8tn60fwz
  CHG301_R2_TWO_LIBRARY_EVIDENCE=/private/tmp/chg301-r2-two-lib-say0hh9k
  /private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python -B -m pytest
  -c /dev/null --rootdir=. --noconftest -p no:cacheprovider
  --basetemp=/private/tmp/chg301-r2-two-library-tests-PfzvUt/final-cases
  --junitxml=/private/tmp/chg301-r2-two-library-tests-PfzvUt/junit-final.xml
  -q backend/tests/test_chg301_r2_ingress.py
```

## 沒有隱藏的中途失敗

| 階段 | 真實結果與處理 |
| --- | --- |
| 5u6hmsd9 | Buildx重複回傳完全相同builder row，guard先拒絕，未build。只合併完全相同JSON；不同內容仍拒絕，固定worker ID再核對。 |
| nmz39q4_、gp0o0w3x | 兩次RUN先停在過度嚴格的「介面名稱只有lo」檢查，沒有apk操作。第二次證明CPU/記憶體限制正確，名稱差異是未連線的kernel tunnel devices。 |
| say0hh9k | 改驗真實UP介面／address／route均只限loopback，保留network=none與同一資源限制。第三次build成功，只升級兩函式庫；world不變。 |
| 同一映像的驗證續跑 | Buildx沒有輸出optional config digest，原reader保守停止。改由實際manifest descriptor／platform／digest及saved OCI config blob鏈驗證，**沒有重建映像**，後續diff及重掃通過。 |

所有失敗／成功result與source SHA保留，未覆寫舊evidence。三次實際build只有一次
成功，沒有超過同原因兩次修正重試；整批仍沿用原6小時期限，未重置run budget。

## 清理與現行環境

三次build的私有四檔context已精確刪除；公開原始材料與recipe仍保留，可重建。
所有本輪容量probe已移除。原有 **14個容器**的ID、status、started/restart紀錄及
原網路保持一致；沒有刪除原映像，只新增上列一個明確保留test tag。
保留既有BuildKit cache及原始證據，不做prune。可用磁碟觀測差約227MiB，遠低於
80GiB增量上限；這是整體VM可用量差，不假稱全部都是本task的精確使用量。
最後仍有超過100GiB可用磁碟、所需CPU／RAM餘裕，probe收尾正常。

Kubernetes／Helm／PR／Provider／image push／應用資料操作均為0。
產品來源受保護檔案SHA保持相同。沒有動現行部署、Secret、PVC、角色或索引。

## 規格與變更檔案

滿足§10.58 CMPPATCH-002本次bounded repair及T02/T04/T05/T09/T10；
CMPPATCH-003/004保留未解安全與後續release gate，不將部分驗證標為完整PASS。

- `backend/scripts/chg301_r2_ingress.py`：active approval、兩材料/索引guard、
  guarded repair／verify-built、exact cleanup、raw scan及SHA256前置Q1辨識。
- `deploy/test/chg301-r2-traefik/Dockerfile`：固定base、離線solver與兩library升級，
  真實網路／cgroup／world檢核；不是production Dockerfile。
- `backend/tests/test_chg301_r2_ingress.py`：94個真實artifact／CLI及變造拒絕案例。
- 規格、changelog、development/test plans、traceability及本報告／JSON：核准與證據。

收尾治理命令：`spec:doctor`、`spec:trace`、`plan:doctor`、`plan:approved`、
`test:plan`、`git diff --check`及evidence JSON解析全部通過；spec:trace為21個active
需求映射。結果另記於active plan，不等同應用release驗收。

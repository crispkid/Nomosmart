# CHG-293 Frontend 安全修補研究（尚未核准實作）

日期：2026-09-10。承接 Peter 同意先研究修補 Next.js、sharp、OpenSSL。
本文件是規格理解與討論材料，不是已核准的開發或部署計畫。

## 結論與範圍

建議只處理 Frontend 的安全相依與容器基底，保留 CHG-293 已核准產品行為、
Backend／Migration、schema、資料、權限及索引。本輪只有唯讀研究及本研究文件；
未安裝套件、修改 lockfile／Dockerfile／程式、啟動容器、重建、部署或呼叫 Provider。

依據 `SPECIFICATION.md` 的 DEPSEC-002，原安全門檻維持失敗，不新增風險豁免。
規格與 SPEC_CHANGELOG.md 本輪不變；新修補範圍須先確認 Gate 2，再寫正式開發計畫
並取得 Gate 4。映像建置／dry-run 與實際部署仍須各自取得範圍核准。

| 套件／層 | 現有候選 | 本次已核對的最低修補目標 |
| --- | --- | --- |
| Next.js | 16.2.12 | 16.3.3；eslint-config-next 同步對齊 16.3.3 |
| sharp override | 0.35.3 | 0.35.4；同步更新 native/libvips lock entries |
| Alpine 3.24 OpenSSL family | openssl、libssl3、libcrypto3 均 3.5.7-r0 | 同分支 3.5.8-r0；確認 final image 實際安裝版本 |

以上是針對現有命中的最低修補版本，不是「最新」或「無其他漏洞」保證。
後續以當時公告、完整 dependency/image 掃描及真實回歸結果判定，不只看版本字串。

## 本機依據與問題來源

- `frontend/package.json`／`package-lock.json`：Next.js 與 eslint-config-next 為
  16.2.12 系列，且 **overrides.sharp 明確鎖在 0.35.3**。只升 Next.js 不會解除
  這個 override，也不能依賴重建自動升級 npm ci 的鎖定結果。
- `frontend/Dockerfile`：deps、builder、prod-deps、runner 四階段都使用浮動
  `node:24-alpine`，沒有 OpenSSL 修補步驟。此次 build 的 base digest 為
  `sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf`。
  更新 npm 相依不會修補 OS 套件；重用浮動 tag 也不能證明取得 patched base。
- 已保存 Frontend SBOM 顯示 Node 24.20.0、Next 16.2.12、sharp 0.35.3，三個
  OpenSSL 套件均 3.5.7-r0。這不是本輪新建置或新掃描的結果。
- `frontend/next.config.ts` 未自訂 images 設定；在 `frontend/src`、該設定檔及
  `frontend/public` 搜尋 next/image、/_next/image、remotePatterns、unoptimized、
  AVIF 或 sharp import 未命中。**不能據此認定 image optimizer route 已停用或
  無法被呼叫**；本輪沒有向環境送出圖片最佳化／攻擊測試請求。
- 既有 App Router auth routes 包含 exchange、refresh、logout 等；框架升級必須
  保留 OIDC/session、安全 cookie、API proxy 與 CHG-293 授權／共享紀錄契約。

候選 image ID 與完整掃描證據沿用
`CHG-293-REVISION37-BUILD-DRYRUN.md`／`CHG-293-REVISION37-BUILD-DRYRUN-EVIDENCE.json`。
前一次讀取的 live release 為 revision 36；本輪沒有重新查詢 Kubernetes，不能把
歷史基線當成未來部署當下的即時狀態。

## 官方公告核對與實際曝險界線

### Next.js

官方 2026-08-25 公告以 16.3.3 修補兩項問題：

- CVE-2026-75604：Windows filesystem 特定 Router 組合的 RCE；官方明確指出
  Linux／macOS 不受此項影響。目前 Linux/arm64 候選不符合這項 Windows 前提。
- GHSA-2xp9-vwfh-vxw4：圖片最佳化處理不可信 AVIF 的上游弱點；修補版本暫停
  AVIF 最佳化，屬必須留意的相容性變化。不應為恢復 AVIF 而撤銷安全修補。

來源：[Next.js 官方安全發布](https://nextjs.org/blog/august-2026-security-release)、
[Windows 個別公告](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36)、
[Image Optimization 個別公告](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)。

### sharp

GHSA-rgj7-g3m4-5g8c 的修補版為 0.35.4，官方預編譯套件包含 libheif 1.23.2。
公告區分 upstream/glibc 特定條件與 sharp 本身的 High 評級；不能把 Linux/musl
直接宣稱為已證實可利用，也不能以不是 glibc 為由忽略不可信圖片處理風險。
來源：[sharp 官方公告](https://github.com/lovell/sharp/security/advisories/GHSA-rgj7-g3m4-5g8c)。

### OpenSSL / Alpine

Alpine 3.24 官方 secdb 把原掃描九項 OpenSSL 命中全部列在 3.5.8-r0 的修補集合，
且 aarch64 套件頁已列出 3.5.8-r0。本輪僅查詢 metadata，未下載或執行 apk。
來源：[Alpine secdb](https://secdb.alpinelinux.org/v3.24/main.json)、
[Alpine ARM64 套件頁](https://pkgs.alpinelinux.org/package/v3.24/main/aarch64/openssl)。

| CVE | 原 Scout 評級 | OpenSSL 官方評級 |
| --- | --- | --- |
| CVE-2026-14456 | High | Low |
| CVE-2026-14457 | High | Low |
| CVE-2026-18798 | High | Moderate |
| CVE-2026-54874 | High | Low |
| CVE-2026-63072 | High | Moderate |
| CVE-2026-63073 | Critical | Low |
| CVE-2026-63075 | High | Low |
| CVE-2026-63076 | High | Moderate |
| CVE-2026-75803 | Critical | Low |

官方適用條件包含 QUIC、DTLS、CMS、CMP、RPK 或特定 EVP 呼叫，不能只因套件存在
就宣稱每項均可由網站利用。本輪未證明所有呼叫路徑可達／不可達。
來源：[OpenSSL 2026-08-25 公告](https://openssl-library.org/news/secadv/20260825.txt)、
[OpenSSL 2026-08-13 公告](https://openssl-library.org/news/secadv/20260813.txt)。

原報告 **4 Critical／8 High** 是掃描器 finding 數，不是 12 個獨立、已確認可利用
的攻擊入口，也不是遭入侵證據。評級差異與平台前提保留為說明；不更改原 SARIF、
不自行新增 VEX/suppression、不降低門檻。目標仍是以正式修補及重掃描解除 gate。

## 相容性：已確認與待確認

2026-09-10 唯讀 GET 官方 npm registry（未使用 npm install）結果：

- [next@16.3.3 metadata](https://registry.npmjs.org/next/16.3.3)：Node >=20.9.0，
  React／React DOM 接受 ^19.0.0；optional sharp ^0.35.3，可容納 0.35.4。
  @next/env、各平台 SWC 都應隨解析對齊 16.3.3。
- [eslint-config-next@16.3.3 metadata](https://registry.npmjs.org/eslint-config-next/16.3.3)：
  ESLint >=9.0.0、TypeScript >=3.3.1；Next ESLint plugin 為 16.3.3。
- [sharp@0.35.4 metadata](https://registry.npmjs.org/sharp/0.35.4)：Node >=20.9.0；
  linuxmusl-arm64 native package 0.35.4、對應 libvips package 1.3.3。

目前 Node 24、React/React DOM 19.2.3、ESLint 9、TypeScript 5 的宣告範圍相容；
這只代表 dependency contract，不是 runtime 測試通過或所有相依皆安全。
本範圍不要求另升 React、不改 rendering framework、不整批 npm update/audit fix。

容器方面建議保持 Node 24／Alpine 3.24／musl／arm64，四個 build stages 使用
一致的明確 base。優先核對官方 patched base 的實際 packages 並固定 digest；
若可用 base 仍含舊 OpenSSL，才在明確核准的共同 base stage 有界升級 OpenSSL
family 及必要相依。不要無範圍 apk upgrade，也不要切換成 Debian 以消除掃描名稱。
**本輪尚未選定新的 base digest**，不能宣稱任何目前浮動 tag 已修復。

Node runtime 所使用的 OpenSSL 也須獨立核對，不能只查 apk/openssl CLI 版本。
後續隔離 smoke 應記錄 `process.versions.openssl` 與實際 dynamic linkage；若發現
Node 本身需額外安全升級而超出本範圍，先提出差異，不自行擴大。
版本讀取依據：[Node.js process.versions](https://nodejs.org/api/process.html#processversions)。

## 建議討論的最小變更與驗收範圍（非已核准計畫）

預期檔案只包括 Frontend package.json、package-lock.json、Dockerfile，以及相關
測試與治理文件。保持 CHG-293 Editor CRUD／archive deny、creator-only chat
mutations、共享唯讀紀錄與作者名稱的行為；不修改 API/schema 或既有資料。

修補範圍若獲同意，正式計畫需涵蓋：

- lockfile 有界差異檢查，無殘留 sharp 0.35.3；clean npm ci、lint、build。
- 真實 Node/Next/native sharp 啟動與 PNG/JPEG 安全測試圖片處理；明確檢查
  AVIF 拒絕或官方停用行為，不送出漏洞 payload、不恢復未修補路徑。
- OIDC 登入／refresh／登出、SSR/API proxy，以及 Markdown、引用與 CHG-293
  Editor/Owner/Viewer、跨使用者歷史讀取與作者限制的真實隔離服務回歸。
- frontend 與必要 backend 回歸、coverage、E2E；不能以 stub/mock 或 image
  liveness 冒充功能 PASS。既有全域 80% coverage／完整 E2E 缺口仍是 open gates。
- 核准建置後重新產生 SBOM／High-Critical scan／隔離 smoke／兩次 canonical
  server dry-run。新 Frontend ID/render hash 必須重新綁定，不能重用舊部署摘要。
- 後續部署另核對 baseline、bootstrap 的實際 operational writes、maintenance／
  rollback 風險；不授權 V049、資料修復、權限寫入、reprocess／index 或 Provider。

目前待 Peter 確認：是否以「僅修補 Frontend 安全相依與基底、保留產品行為，
接受官方 AVIF 安全限制並做回歸」作為 Gate 2 範圍。確認後才撰寫正式修補計畫。

## 本輪驗證紀錄

已讀本機 manifests／Dockerfile／Next config／SBOM／SARIF／DEPSEC-002，並以
官方 advisory、registry、Alpine metadata 交叉核對。本輪沒有跑產品 feature tests，
沒有重新掃描，也沒有使用攻擊 PoC。最初受限 shell DNS 查詢失敗，經核准的
唯讀外部 metadata 查詢成功；不能把前者的空輸出當查證成功。

本輪文件使用 `git diff --check` 與新文件的 `git diff --no-index --check` 檢查；
新相依組合與新映像均尚未產生、尚未驗證。

## 後續 Gate 2 確認（2026-09-10）

Peter 隨後以 `OK` 回覆研究結論的明確 Gate 2 問題，確認本研究的有界修補範圍。
正式修補獨立編為 CHG-294；規格 10.51、DEVELOPMENT_PLAN.md、TEST_PLAN.md 與
TRACEABILITY.md 已建立 Gate 3 文件，摘要見 `CHG-294-PLAN.md`。Gate 4 尚未核准，
未修改相依、Dockerfile 或產品程式；本節不覆寫上面的歷史研究／掃描證據。

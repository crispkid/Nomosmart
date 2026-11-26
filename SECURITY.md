# Security Policy / 資安政策

[English](#english) | [繁體中文](#繁體中文)

## English

### Supported versions

Security fixes are released for the **latest published version** only. Older versions
receive fixes by upgrading; see [UPGRADING.md](UPGRADING.md). The latest version is shown
on the [Releases page](https://github.com/crispkid/Nomosmart/releases/latest).

### Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub:
[Report a vulnerability](https://github.com/crispkid/Nomosmart/security/advisories/new)
(Security tab → Report a vulnerability).

Do not open a public issue, pull request or discussion for a security problem, and do not
include real credentials, tokens or customer documents in a report.

A helpful report includes:

- the affected version and deployment type (Docker Compose or Helm);
- the affected component or endpoint;
- steps to reproduce, and what an attacker could do;
- any logs or screenshots, with secrets removed.

### What happens next

1. We acknowledge the report and may ask for more details through the private advisory.
2. We confirm whether it is a vulnerability in NomoSmart and assess its severity.
3. We prepare a fix in a new release and describe it in the [changelog](CHANGELOG.md)
   under **Security**.
4. We publish the advisory after the fixed release is available, and credit the reporter
   unless they prefer otherwise.

### Scope

This policy covers the NomoSmart application, its images and its installation tooling in
this repository. Third-party services that NomoSmart connects to (identity providers,
databases, model services and others) follow their own vendors' policies.

## 繁體中文

### 支援的版本

只有**最新發佈的版本**會收到安全性修正。舊版請升級取得修正，步驟見
[UPGRADING.zh-TW.md](UPGRADING.zh-TW.md)。最新版本見
[Releases 頁面](https://github.com/crispkid/Nomosmart/releases/latest)。

### 回報漏洞

請透過 GitHub **私下**回報：
[回報漏洞](https://github.com/crispkid/Nomosmart/security/advisories/new)
（Security 分頁 → Report a vulnerability）。

請不要用公開的 issue、pull request 或 discussion 回報資安問題，也不要在回報中附上真實的
帳號密碼、Token 或客戶文件。

建議提供：

- 受影響的版本與部署方式（Docker Compose 或 Helm）；
- 受影響的元件或端點；
- 重現步驟，以及攻擊者可以做到什麼；
- 相關日誌或截圖（請先移除機密資訊）。

### 後續處理

1. 我們會回覆收到回報，必要時透過私密通報詢問更多細節。
2. 確認是否為 NomoSmart 的漏洞，並評估嚴重程度。
3. 在新版本中修正，並寫在[更新紀錄](CHANGELOG.zh-TW.md)的「安全性」分類。
4. 修正版發佈後公開通報；除非回報者不希望具名，否則會註明回報者。

### 範圍

本政策涵蓋這個儲存庫中的 NomoSmart 應用程式、映像與安裝工具。NomoSmart 連接的第三方服務
（身分提供者、資料庫、模型服務等）依各自廠商的政策處理。

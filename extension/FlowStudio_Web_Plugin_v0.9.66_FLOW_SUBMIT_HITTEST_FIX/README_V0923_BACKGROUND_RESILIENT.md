# Flow Studio Web Plugin v0.9.28

本版只加强外围稳定性、连接、任务去重和 Google 任务源读取，**不重写原上传/下载核心**。

主要变化：

- Chrome Flow 标签页 best-effort `autoDiscardable=false`。
- 已 discard 的 Flow tab 尝试后台 reload 自愈。
- content page 每 2.2 秒唤醒 service worker；background 每 1.2 秒维护 Studio 连接。
- 401/403 自动丢弃旧 token，重新 heartbeat 并重试本地请求。
- “找不到生成按钮”递增等待重扫 DOM：1.5 / 3 / 5 / 8 / 12 秒。
- 不重试 `SUBMISSION_UNCONFIRMED` 等不确定状态，避免重复点击。
- `chrome.storage.local + sessionStorage` 持久 dispatch ledger，已确认提交任务重连后不再次提交。
- Flow tab 状态区分 complete / background / loading / discarded / recovering。
- Google Sheets / Drive 任务源通过当前登录态读取；素材返回 HTML 登录页时明确报错。
- Local bridge 仍固定 `http://127.0.0.1:17831`。

受保护、未修改：`downloads.js`、`page-engine.js`、`result-core.js`、`styles.css`。

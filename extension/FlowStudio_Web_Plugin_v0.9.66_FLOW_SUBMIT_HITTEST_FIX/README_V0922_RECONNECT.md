# Flow Studio Web Plugin v0.9.22

这是 V0.13.2 的配套网页插件。

重点变化：
- 不依赖插件编号识别任务，仍以 Studio 下发的 `channel_key + command_id + task_name + expected filename` 为准。
- 支持浏览器 A / B 通道池。
- Studio 重启、localhost token 失效、service worker 唤醒后自动重连。
- 401/403 自动重新 heartbeat 获取 token 并重试。
- 持久 outbox 在断线恢复后继续补发事件。
- 完整运行日志继续保存在 `chrome.storage.local`，可从插件导出诊断 JSON。
- 原上传 / 下载核心未重写。

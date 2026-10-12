# v0.9.48 Confirmed Submit Gate

- “已提交”不再由点击前登记产生；只有拿到 Flow 新生成视频 ID 后才形成 confirmed/submitted 证据。
- Flow 按钮点击但没有产生生成请求时返回 `FLOW_SUBMISSION_NOT_STARTED`，允许安全重试，不进入“已提交”。
- 真正已经发起请求但未确认时进入 `uncertain` 恢复态，不重复点击。
- 兼容清理 v0.9.47 及更早版本在点击前写入的 stale `submitted_at` 标记；超过 90 秒且无法恢复 Flow 视频身份时才重新武装。
- 保留 v0.9.47 调度真值、v0.9.46 MATERIAL 附件硬门、上传 watchdog、下载与跨波次间隔。

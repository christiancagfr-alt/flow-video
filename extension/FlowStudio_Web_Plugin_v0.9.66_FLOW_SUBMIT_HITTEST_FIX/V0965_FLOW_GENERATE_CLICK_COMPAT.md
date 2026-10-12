# v0.9.65 Flow Generate 点击兼容修复

基线：v0.9.62 BACKGROUND_UPLOAD_READY_FIX。

仅增量修改 page-engine.js 的 Flow composer / Generate 点击层：

- Generate 按钮由单一 selector 改为多 selector fallback。
- prompt 内部 signal 写入后，向当前 rendered editor 发送 input/change 同步事件。
- 点击前强制重新扫描当前 Angular DOM，避免使用失效旧节点。
- 点击动作改为 pointerdown/mousedown/pointerup/mouseup + 单次 native click。
- 不做自动二次 click，避免重复生成。
- 增加 CLICK_SCAN / CLICK_ATTEMPT 诊断日志。
- 提示词已写入但按钮仍 disabled 时返回 FLOW_COMPOSER_STATE_NOT_SYNCED。

未修改：调度器、上传、下载、Bridge、任务队列、质检、返工、任务确认、防重复提交、素材/帧模式核心逻辑。

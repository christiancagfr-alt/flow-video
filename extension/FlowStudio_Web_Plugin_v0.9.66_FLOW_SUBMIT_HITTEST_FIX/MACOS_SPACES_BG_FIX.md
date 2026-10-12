# macOS Spaces 后台持续执行补丁

- 仅修改后台生命周期恢复。
- Flow 窗口放到其他 macOS Space 后，如 Chrome 将任务标签标记为 frozen，Service Worker 使用 CDP `Page.setWebLifecycleState(active)` 原地恢复。
- 同时触发 `Emulation.setFocusEmulationEnabled(true)` 和插件 BACKGROUND_WAKE。
- 不聚焦 Chrome 窗口，不主动切换用户当前 Space。
- 保留图片全量 READY 门槛、上传重试、提交间隔、任务绑定、FRAME/MATERIAL 与下载逻辑。

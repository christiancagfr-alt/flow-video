# v0.9.47 Scheduler Truth + Zombie Job Reconciliation

- 修复后台通道心跳始终 `idle_channel=true` 的错误语义。
- Heartbeat 现在使用当前 tab 实际绑定的 Bridge Job，忙时回传真实 `command_id`，空闲时才回传 `idle_channel=true`。
- 保留 v0.9.46 的上传 watchdog、MATERIAL 附件硬门、下载、恢复、跨波次提交间隔等逻辑。

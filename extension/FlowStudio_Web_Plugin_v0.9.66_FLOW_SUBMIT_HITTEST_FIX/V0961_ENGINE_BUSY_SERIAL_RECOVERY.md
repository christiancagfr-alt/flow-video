# v0.9.61 — ENGINE_BUSY SERIAL RECOVERY

- `ENGINE_BUSY` 不再直接计为任务失败。
- 当上一条 Flow 原生提交仍在等待确认时，下一条任务按 0.8/1.5/2.5/4/6.5/10/15/20/25 秒阶梯等待执行器释放。
- 等待期间记录 `engine_busy_waiting`，不会触发真正错误计数。
- 如果 Studio 已取消当前 command，则立即停止等待，避免旧任务在执行器释放后误提交。
- MATERIAL 原生素材选择、固定 8 秒、FRAME 逻辑、提交间隔、下载与恢复逻辑保持不变。

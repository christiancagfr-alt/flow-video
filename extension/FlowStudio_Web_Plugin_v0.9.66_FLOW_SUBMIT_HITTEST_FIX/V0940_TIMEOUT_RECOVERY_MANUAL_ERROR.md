# v0.9.40 Timeout Recovery + Manual Error Isolation

- `MAIN_ENGINE_TIMEOUT` / `SUBMISSION_UNCONFIRMED` are recoverable states, not generation failures.
- Never click Generate again for an uncertain submission. Recover the original generation identity first.
- Pending identities are rechecked in the background every 10 seconds.
- One failed segment no longer pauses the entire batch; later segments continue.
- Only deterministic/explicit errors emit `generation_task_status: failed`.
- True errors are left to Flow Studio `运行任务 / 重试` for manual handling.

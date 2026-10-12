# v0.9.46 Upload Watchdog + Material Hard Gate

- Prevent generic “已继续：生成队列恢复提交” control heartbeats from overwriting real upload/submission status.
- Add 35s no-progress upload watchdog. It releases a stuck upload gate, rescans fresh Flow DOM, and returns to the verified retry path instead of occupying the Studio channel forever.
- MATERIAL mode now requires fresh per-task attachment evidence; stale reference state from the previous task is rejected.
- MATERIAL mode requires three consecutive attachment checks immediately before Generate is clicked. If the image disappears after prompt writing or Flow rerender, generation is blocked and the image is re-selected/revalidated instead of allowing prompt-only generation.
- Plugin emits `preparing` before hard validation; Studio does not count that as submitted/generating.

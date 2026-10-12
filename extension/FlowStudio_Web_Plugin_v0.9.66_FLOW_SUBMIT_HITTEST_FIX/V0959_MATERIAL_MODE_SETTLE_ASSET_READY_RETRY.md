# v0.9.59 — MATERIAL MODE SETTLE + ASSET READY RETRY

- 不再把 `FLOW_MODE_NOT_STABLE_BEFORE_MATERIAL_SELECT:VIDEO_REFERENCES` 作为素材任务的前置硬失败。
- 素材模式在 clear/configure 后最多 3 轮重新断言 `VIDEO_REFERENCES`，即使短暂读不到稳定值也继续执行 Flow 原生 `select(item)`，并在选择后再次确认/修正模式。
- 正式 IMAGE asset 就绪判断不再强依赖可解析 preview URL；只要同一 Flow IMAGE 记录稳定存在、非 loading、无 error 且有正式 id，即允许原生选择。
- 显式 loading/error 仍会阻止生成；FRAME 路径未改。
- MATERIAL 继续固定 8 秒。

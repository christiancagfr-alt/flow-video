# v0.9.56 — MATERIAL 原生素材绑定（取消 @）+ 固定 8 秒

本版以 v0.9.52 的 MATERIAL 原生 Flow IMAGE asset 绑定链为基线，取消 v0.9.53–v0.9.55 引入的 `@ Ingredient` 输入/菜单选择链。

## MATERIAL 挂图
- 图片仍先作为 Flow 正式 IMAGE asset 上传并识别。
- 切换到 `VIDEO_REFERENCES` 后，复用与 FRAME 同源的 `select(item)` 原生素材选择链，将已上传 asset 绑定到当前素材引用。
- 禁止本地文件直接拖入 MATERIAL composer，避免灰色感叹号附件。
- 保留最终 generation request 的精确 reference binding gate；没有真实 reference 绑定时禁止提交。

## 时长
- MATERIAL 固定 8 秒。
- MATERIAL 不读取、不写入 duration signal，不操作时长选择器。
- FRAME 原有 4/6/8 秒逻辑保持不变。

# v0.9.63 Post-upload image existence gate

仅增量修改上传后放行条件，不改调度、下载、提交间隔、任务绑定。

- 上传动作完成不再等于图片可生成。
- Flow 媒体目录中的 IMAGE 占位项若仍为 uploading/pending/processing/error，不计为已上传。
- 图片必须在 Flow 内部媒体目录中处于可用状态，并连续两次扫描稳定存在，且页面不再处于上传中，才允许 READY。
- 正式第 1 次提交前再次执行两次实时媒体目录确认；未通过时不会 claim 命令，也不会计入生成尝试。
- FRAME 与 MATERIAL 均在选择参考图前等待 Flow 正式图片资产 ready，防止占位项进入生成链路。

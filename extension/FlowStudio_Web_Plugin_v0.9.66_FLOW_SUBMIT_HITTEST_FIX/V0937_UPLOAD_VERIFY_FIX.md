# v0.9.37 上传强验证恢复

仅修改网页插件上传链路，未改中央任务调度、下载、结果绑定、生成队列等核心逻辑。

- 修复 v0.9.36 在拖放真正发送前就永久标记“已发送”，导致无效 drop 后不再重试的问题。
- 上传后以 Flow 内部媒体列表为真实成功依据，不再把 dispatch 成功当作上传成功。
- 首次保持原 Chrome Debugger 原生拖放方式。
- 未验证成功时，12 秒后允许有限重试；第二次起优先尝试 Flow 文件 input，再回退到重新定位后的原生拖放。
- 若 Flow 的“上传/处理中”状态长时间卡死，30 秒后允许验证性恢复尝试。
- 每张缺失图片最多自动尝试 3 次；仍未出现则明确上报最终失败，不再无限“正在上传”。
- 新增上传阶段日志：upload_target_found / file_attached / drop_dispatched / flow_media_detected / media_upload_failed_final。

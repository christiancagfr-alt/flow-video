# v0.9.61 BG3 增量修复

仅修改网页插件，不改 Studio 调度、下载、返工、数据库或任务顺序。

## 全图片上传硬门槛
- READY 必须以本批次全部原始应有图片为准。
- 开始提交前再次读取 Flow 内部媒体目录做最终 preflight。
- 任意图片缺失时，禁止 claim、禁止点击 Generate，回到扫描/上传阶段。
- 不恢复素材模式提交成功检查或素材绑定保护。

## 后台持续执行
- hidden 页等待通过 MessageChannel 断开链式 timer，降低 Chrome 后台定时器严重降频。
- MAIN 页面持有插件专用 shared Web Lock，避免 Energy Saver 对活动 Flow 工作页进行冻结。
- background service worker 每 30 秒 alarm 兜底；有活动任务时发送 FS_BACKGROUND_WAKE。
- 检测 tab.frozen，仅对活动任务标签请求 active:true 解冻，不聚焦窗口，不主动切换 macOS Space。
- 保留 autoDiscardable:false 与 discarded reload。

## 未修改
提交顺序/间隔、generation_count、防重复提交、任务 claim、素材模式 8 秒、上传 3 次上限、下载与结果绑定主链路。

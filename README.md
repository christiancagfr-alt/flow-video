# Flow Studio 0.13.5.106

Windows 本地任务、提示词、Flow 视频生成与达芬奇剪辑工作台。

## Windows 便携版

从本仓库 Releases 下载 `FlowStudio-0.13.5.106-Windows-x64.zip`，完整解压到可写目录，双击 **Flow Studio.vbs** 启动。已包含 Python 3.13.16 和运行依赖，无需安装 Python。正常启动不显示终端；诊断信息保存在本地 `data/logs/`。

支持 Windows 10/11 x64。首次启动是空白任务库，需要设置任务来源并授权 Google。Google OAuth 使用桌面应用客户端 JSON；服务账号文件不是桌面 OAuth 客户端。Windows 刷新凭据使用当前账户的 DPAPI 加密，换电脑或 Windows 账户后需重新授权。

Chrome 扩展：打开 `chrome://extensions`，启用开发者模式，加载解压后的 `extension/FlowStudio_Web_Plugin_v1.8.3_IDENTITY_ALIAS_DOWNLOAD` 文件夹。目录名保留兼容性，实际插件版本为 **1.8.6**。关闭旧版本扩展，避免重复接收任务。

达芬奇、Chrome、账户及付费模型权限需自行准备。可选 FFmpeg/Whisper/Remotion 工作流的外部工具和工程不包含在本包内。达芬奇自动化依赖其版本、脚本权限、窗口和菜单状态。

## 数据与安全边界

- 发布包不含原工作目录的任务、素材、账号、OAuth 文件或日志。旧数据如需迁移，请先备份，再在本地处理，不要上传到 GitHub。
- 图片网址只允许公网 HTTP/HTTPS，每次重定向都会重新检查地址。内网图片请先导入本地。
- 视频及辅助图片下载回执只接受系统 Downloads 或软件设置的下载目录。自定义 Chrome 下载位置须同步配置到软件。
- 本地桥接服务只监听回环地址。仍信任同一用户的本地程序和已安装扩展；不要在不可信环境中开放端口。
- API Key 可通过软件设置存入系统凭据库，或设置 `OPENAI_API_KEY`。`.env.example` 仅说明变量名，软件不会自动加载 `.env`。

## 本次修复

加固本地 HTTP、扩展消息来源、文件读取与下载路径；Windows OAuth 加密；锁定并升级依赖。恢复 MATERIAL 素材模式与辅助结束帧链路，辅助图必须有原生 2K/4K 下载回执和实际尺寸验证。增加便携运行环境及无终端启动入口。

功能测试使用隔离数据库与模拟服务，未使用真实账户执行付费 Flow 生成或真实达芬奇切刀导出。网页结构、模型权限和达芬奇现场兼容性仍需实际账号验证，不能把单元测试等同于完整生产验收。

## 源码与验证

Python 运行依赖固定在 `requirements-release.lock`（42 项）。Windows 源码启动可用 `Flow Studio.vbs` 创建环境；已有旧环境不会自动强制升级，建议新目录安装。开发测试另需 `lupa==2.8`（只用于 Lua 测试），插件测试需要 Node.js。

```powershell
python -m unittest discover -s tests
```

扩展 `tests/*.cjs` 可逐个用 Node.js 执行。`scripts/build_windows_portable.py` 从 Python/PyPI 官方站点下载并校验哈希，构建目录为 `build/FlowStudio-Windows`。发布时必须使用源码白名单，不得把含测试数据的整个工作目录压缩上传。

详见 [安全审核报告](SECURITY_AUDIT.md)。发行版 `RUNTIME_MANIFEST.json` 列出 Python 和所有运行 wheel 的 SHA-256；Python 自带许可证及依赖包的 dist-info 许可证随运行环境保留。第三方组件各自遵循其原许可证，仓库并未替它们重新授权。

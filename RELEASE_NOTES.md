Flow Studio 0.13.5.110

- 修复 Windows Bridge 回复中的 CRLF 换行符混入任务路径，造成任务读取、错误归档失败并退出的问题。
- 内部 Windows 助手移出达芬奇脚本菜单，避免直接运行时出现缺少 --request 参数的错误。
- 达芬奇启动增加安装位置注册表检测，支持非默认安装目录；Windows 设置中可手动选择 Resolve.exe。
- 保留 0.13.5.109 的紧凑界面、主题对比度、滚轮防误操作和视频包装流程改进。
- 本地 129 项回归测试通过，包含真实 Windows Lua 文件/进程通信、模拟达芬奇接口的当日项目创建和持续心跳测试。真实达芬奇一键控制仍需在已安装达芬奇的 Windows 设备上验证。

升级后请关闭并重新打开达芬奇，再在 Flow Studio 中唤醒，确保旧 Lua Bridge 缓存卸载。首次更新脚本后若达芬奇菜单尚未刷新，请再次重开达芬奇。不要直接运行 windows_resolve_runtime.py。

统一 Flow Studio 图标与版本显示，新增检查更新、下载安装包、SHA-256 校验及退出安装提示。

- Windows x64：下载 Setup.exe，按向导安装。
- Apple 芯片：下载 macOS-arm64.dmg；Intel：下载 macOS-x86_64.dmg。打开后将 Flow Studio 拖入 Applications。
- Ubuntu 22.04/24.04、Debian 系 x64：下载 Linux-amd64.deb，通过系统软件安装器安装。

安装包内置 Python。安装版数据独立保存，升级或替换应用不覆盖数据。旧便携目录的任务不会自动搬迁，请先备份；原目录仍可使用。

软件底部显示版本号，点击“检查更新”可下载适合当前平台的正式版；下载完成后确认退出，由系统打开安装程序。Mac DMG 仍需要拖动替换，Linux 由软件安装器确认权限。

Windows 未进行 Authenticode 签名，Mac 未进行 Apple Developer ID 签名和公证，系统可能提示未知发布者。不要关闭系统整体安全检查。

Linux 首次提供桌面兼容版；任务、提示词、浏览器扩展和 Qt 界面纳入适配，达芬奇窗口自动点击尚未支持，需手动运行相应脚本。真实 Flow 付费生成与达芬奇业务全流程仍须在用户环境验证。

统一 Flow Studio 图标与版本显示，新增检查更新、下载安装包、SHA-256 校验及退出安装提示。

- Windows x64：下载 Setup.exe，按向导安装。
- Apple 芯片：下载 macOS-arm64.dmg；Intel：下载 macOS-x86_64.dmg。打开后将 Flow Studio 拖入 Applications。
- Ubuntu 22.04/24.04、Debian 系 x64：下载 Linux-amd64.deb，通过系统软件安装器安装。

安装包内置 Python。安装版数据独立保存，升级或替换应用不覆盖数据。旧便携目录的任务不会自动搬迁，请先备份；原目录仍可使用。

软件底部显示版本号，点击“检查更新”可下载适合当前平台的正式版；下载完成后确认退出，由系统打开安装程序。Mac DMG 仍需要拖动替换，Linux 由软件安装器确认权限。

Windows 未进行 Authenticode 签名，Mac 未进行 Apple Developer ID 签名和公证，系统可能提示未知发布者。不要关闭系统整体安全检查。

Linux 首次提供桌面兼容版；任务、提示词、浏览器扩展和 Qt 界面纳入适配，达芬奇窗口自动点击尚未支持，需手动运行相应脚本。真实 Flow 付费生成与达芬奇业务全流程仍须在用户环境验证。

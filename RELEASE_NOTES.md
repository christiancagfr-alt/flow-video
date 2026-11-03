# Flow Studio 1.1.16 · Windows x64

以本地代码为基线发布，不合并远程新功能。随包扩展版本 0.9.69。

- 更新 Pillow、Qt/PySide6、certifi、pyasn1、PyAV 与 FFmpeg，锁定 Remotion 依赖。
- 修复优化模式下的安装校验、错误信息脱敏和 Windows 清理路径/回收站处理。
- 兼容 FFmpeg 9 的字幕水印与 H.264、ProRes、VP9 导出。
- Windows CI 强制执行内嵌 Python 测试、桌面启动、静默安装和三种视频输出检查。

安装文件为 Windows x64 Setup.exe，附 SHA-256 校验文件。构建不包含本地账号、数据库或密钥。未提供代码签名证书，Windows 可能显示未知发布者提示。

安全取舍已由开发者接受：保留 Chrome 扩展自动连接；不将已被恶意脚本控制的 Flow 页面视为可信自动化环境。完整审核和剩余风险见 SECURITY_AUDIT_2026-11-03.md。

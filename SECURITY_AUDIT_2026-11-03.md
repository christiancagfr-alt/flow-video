# 2026-11-03 本地源码发布安全复核

目标：Flow Studio 1.1.16 Windows x64；扩展 manifest 0.9.69。以本地源码为准，不合并远程主分支功能。下面记录本次新增发现；旧报告仅作为历史记录，不代表当前依赖结论。

## 范围与方法

Python 3.13 / PySide6 / SQLite 桌面、Chrome Manifest V3 JavaScript 扩展、DaVinci Lua、Remotion/React 与 FFmpeg/ASR。审查发行源码白名单，静态检查 Python 185 个文件及 JS/Lua/脚本；人工重点检查 HTTP/IPC、鉴权、URL 下载、路径/压缩包、SQL、子进程、凭据、扩展消息和发布流程。对配置、示例、文档及扫描到的压缩包成员执行凭据模式扫描。未对第三方二进制逐行审计，未用真实账号进行攻击或付费生成。

原依赖盘点为 75 个 Python 名称/版本组合、297 个 npm 安装路径；Windows 主运行锁 42 项。逐项检索公告并以 OSV / pip-audit / npm audit 交叉核对。新 npm 锁包含平台可选依赖，其包数与旧安装树并非直接可比。本次本地根目录没有 Git 历史；不能证明历史从未泄露。远程源码只作比较，旧扩展与旧构建产物不复制到新版。

## 问题汇总

| 编号 | 类别 | 严重级别 | 位置 | 状态 |
|---|---|---|---|---|
| N01 | 依赖 | Critical | requirements-release.lock:4；macOS/Linux 同名锁 | 已修复 |
| N02 | 依赖 | High | requirements-release.lock:25 | 已修复（已批准大版本升级） |
| N03 | 依赖 | High | requirements-release.lock:29 | 已修复 |
| N04 | 依赖 | Medium | requirements-asr.txt:12 | 已修复 |
| N05 | 依赖 | High | scripts/remotion-runtime/package-lock.json | 已修复 |
| N06 | 依赖 | High | requirements-release.lock:1；requirements-asr.txt:6；scripts/packaging_components.py:105 | 已升级；原生子组件覆盖仍待确认 |
| N07 | 代码 | Medium | scripts/install_update.py:13；scripts/build_linux.py；scripts/build_macos.py | 已修复 |
| N08 | 代码 | Medium | app/services/redaction.py:3；credential_pool.py:76；local_bridge.py:239；main.py:22 | 已修复 |
| N09 | 代码 | Medium | app/services/clear_all_history.py:34、72 | 已修复 |
| R01 | 代码 | Medium | app/services/bridge_security.py；local_bridge.py 的 /heartbeat | 建议关注：开发者明确接受风险 |
| R04 | 代码 | Medium | extension/FlowStudio_Web_Plugin_v0.9.66_FLOW_SUBMIT_HITTEST_FIX/page-engine.js 自定义事件入口 | 建议关注：开发者明确接受风险 |
| R06 | 依赖 | Low | 原生 Qt/Chromium/FFmpeg 及 ASR 动态下载 | 建议关注，待确认 |
| K05 | 密钥 | Low | .gitignore；.env.example；发行白名单 | 建议关注：本次模式扫描无新凭据命中，历史未证明安全 |

## 修复、风险与利用条件

- N01：certifi 2026.7.22 → 2026.10.23，移除有问题的信任根。应用使用 HTTPS 客户端，攻击者如能取得受影响 CA 签发的证书并控制网络路径可能冒充服务。公告修复下限 2026.10.18：[官方 GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。
- N02：Pillow 12.3.0 → 13.0.0。手动素材、水印会解码图片，不可信图像可触发内存破坏。开发者已批准大版本升级；PNG/JPEG、动画水印、字幕和视频输出已回归。[OpenJPEG 公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-78g4-xqwv-q3g8)、[13.0.0 发布说明](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)。
- N03：pyasn1 0.6.4 → 0.6.5，修复恶意 ASN.1 输入的资源耗尽问题。间接用于认证；未证明本项目允许攻击者直接控制解析入口，业务可达性待确认。[GHSA-9m75-vc3g-4x39](https://github.com/advisories/GHSA-9m75-vc3g-4x39)。
- N04：ASR 明确固定 filelock 4.2.7，防止模型缓存锁落入旧 Windows ACL/竞态版本。利用需本机恶意进程及可干预锁路径的权限。[上游 Windows 公告](https://github.com/tox-dev/filelock/security/advisories/GHSA-8mx5-7m5m-r77g)。
- N05：Remotion 4.0.540 与 React/ReactDOM 19.2.0 写入精确 package.json/package-lock.json，并改用 npm ci，移除旧树的 zod/fast-uri 漏洞版本。不可信输入到受影响解析器可能耗尽资源；具体渲染配置入口可达性未全部证明。[zod 公告](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)。React 服务端组件公告不应算到本项目客户端 React：未安装 react-server-dom-*。
- N06：PySide6/Shiboken/Addons/Essentials 6.11.2 → 6.11.3；PyAV 19.0.1 → 19.0.2；imageio-ffmpeg 0.6.0 → 0.8.1（FFmpeg 9.0，经批准）。修复 FFmpeg 9 移除 filter_complex_script 参数造成的导出失败，改为 -/filter_complex；VP9 显式 yuv420p。Qt3D/QDom/QCbor 等受影响入口未发现业务使用，但不能由 Python 扫描证明内置 C/C++ 库无漏洞。[Qt 漏洞表](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products)、[PyAV 发布说明](https://github.com/PyAV-Org/PyAV/releases)、[imageio-ffmpeg 发布说明](https://github.com/imageio/imageio-ffmpeg/releases)。
- N07：校验和失败由 assert 改为显式异常。Python -O 会删除 assert，原先在优化模式下可跳过下载包摘要核验；利用还需替换下载文件或缓存。增加 -O 回归，安装器摘要失败必须退出。
- N08：识别含连字符的 API header、Cookie、签名 URL、Google/Groq/HuggingFace 密钥及引用形式的敏感字段；主异常弹窗、凭据健康状态持久化、桥接错误字段统一脱敏。利用需获得错误响应、日志或本地状态文件。保留正常 token 引导响应，避免误删业务协议字段。第三方原生 stdout/stderr 仍可能包含用户内容，不能保证全部脱敏。
- N09：路径检查改为解析真实路径后的组件比较，Windows 测试覆盖大小写和反斜杠，拒绝兄弟前缀及越界路径；Windows 使用系统回收站，失败不回退到错误的 macOS .Trash 路径。风险为清理功能对路径边界判断错误导致误处理文件，通常要求恶意或异常本地路径输入。

另修复已有回归揭示的“手动段落类型仍标记 sheet_color”来源字段错误；测试适配本地现有任务分组、发布波次、扩展版本与原生点击逻辑，没有引入远程功能。扩展测试补全素材预扫描、恢复记录、原生点击模拟，保留上传上限、重复提交和点击目标断言。构建白名单加入 npm 锁，并在全新工作区创建 audit 目录。

## 已决定的取舍

1. R01：任意已安装 Chrome 扩展可经 /heartbeat 领取桥接令牌。恶意扩展因而能调用桥接授权操作。开发者选择保持自动连接并接受此风险；本次不增加配对。后续建议扩展固定身份配对/用户授权，届时需要调整安装体验。
2. R04：已被恶意脚本控制的 Flow 页面可伪造 MAIN-world 自动化事件。开发者选择保留自动化并接受风险；这种页面不在当前安全边界内。后续重做消息协议和敏感动作授权。
3. Pillow 与 FFmpeg 大版本升级均已批准。没有待回复的升级问题。

## 密钥与供应链

未发现新的硬编码凭据候选；.env、data、数据库、日志、token/secret JSON、私钥与本次私有审核证据均被忽略或排除。发行只从白名单复制源文件，不打包开发目录中的账号/缓存/旧运行库。.env.example 只含变量名。Windows 凭据通过 DPAPI，macOS/Linux 通过系统凭据库；不擅自轮换现有账号。

**任何已经提交或泄露过的真实密钥必须到对应平台作废并重新生成；删除代码不等于撤销密钥。** 本次未发现需立即轮换的新证据。

Windows CI 仅从本地发布分支触发；第三方 Actions 固定提交 SHA，checkout 不保留凭据，构建作业只读，发布作业才授予 contents:write；不用 pull_request_target，不把不可信事件字段插入 shell。Python runtime 固定摘要，wheel 下载验证 PyPI 元数据中的 SHA-256，npm 锁含 integrity；这仍信任上游发布账号与 HTTPS。ASR 传递依赖、模型快照和 Node latest-v22.x 尚非完全离线锁定；实际构建版本应记录，后续建议补全 SBOM/离线镜像。

未发现可确认仿冒包。google-api-python-client 处维护模式但仍安全支持；pywinauto 0.6.9 更新频率较低，应持续关注，不据此断言 EOL。Qt Multimedia 内部 FFmpeg 与独立导出 FFmpeg 是不同组件，升级后者不能证明前者已修复。Chromium 与原生库的完整 CVE 映射待确认。

Windows 首轮原生测试揭示连接池持有临时 SQLite 文件，导致 Windows 删除测试目录时报 WinError 32。测试夹具现在仅关闭所属临时目录中的闲置数据库和素材注册表连接，再清理目录；保留生产连接池与测试断言，不忽略删除错误。另固定 Git 文本换行为 LF，避免 Windows CRLF 破坏源码契约测试。

## 验证结果

- macOS 独立修复环境：Python 207 项通过，11 项跳过（平台或可选集成）；扩展 Node 47 项通过；根目录 JS 1 项通过、2 项因未发行 v1.8.3 扩展而明确跳过；桌面图标、版本、更新对话框启动通过。
- FFmpeg 9.0 实际执行带音频/字幕/PNG 水印的 320×180 两秒样片：H.264 / ProRes / VP9 均成功，时长与尺寸核验通过；Pillow PNG/JPEG 及动画图像处理通过。
- 修复后 Windows 42 项锁与 ASR 清单 pip-audit 无已知漏洞；新 npm 锁 npm audit 无已知漏洞。无命中不等于无未知漏洞或原生库漏洞。
- Windows 原生安装、内嵌 Python 测试、安装后 UI 和三编码回归由 windows-local-release.yml 强制执行，全部成功才上传并发布。写报告时待 CI 完成，不能把本机 macOS 结果当成 Windows 通过。
- 原本地 bundled-components 保留未覆盖，避免破坏正在使用的环境；Windows 发行构建会从新锁重建。旧包仍可能含上述旧依赖，不作为新发行物。

## 依赖版本清单

下表列出所有声明的 Python 直接及锁定间接依赖；重复平台版本分别列出。PySide6、Google API/auth、keyring、psutil、pywinauto、Pillow、pywin32 为应用主要直接依赖，ASR 清单为可选直接依赖；其余为锁定间接依赖/平台支持。完整 npm 实际锁见 scripts/remotion-runtime/package-lock.json。

| 清单 | 名称 | 修复后版本 |
|---|---|---|
| requirements-release.lock | PySide6 | 6.11.3 |
| requirements-release.lock | PySide6_Addons | 6.11.3 |
| requirements-release.lock | PySide6_Essentials | 6.11.3 |
| requirements-release.lock | certifi | 2026.10.23 |
| requirements-release.lock | cffi | 2.1.1 |
| requirements-release.lock | charset-normalizer | 3.5.2 |
| requirements-release.lock | comtypes | 1.4.17 |
| requirements-release.lock | cryptography | 50.0.2 |
| requirements-release.lock | google-api-core | 2.42.0 |
| requirements-release.lock | google-api-python-client | 2.201.0 |
| requirements-release.lock | google-auth | 2.61.0 |
| requirements-release.lock | google-auth-httplib2 | 0.4.4 |
| requirements-release.lock | google-auth-oauthlib | 1.5.0 |
| requirements-release.lock | googleapis-common-protos | 1.75.5 |
| requirements-release.lock | httplib2 | 0.32.0 |
| requirements-release.lock | idna | 3.20 |
| requirements-release.lock | jaraco.classes | 3.4.0 |
| requirements-release.lock | jaraco.context | 6.1.2 |
| requirements-release.lock | jaraco.functools | 4.6.0 |
| requirements-release.lock | keyring | 25.7.0 |
| requirements-release.lock | more-itertools | 11.1.0 |
| requirements-release.lock | oauthlib | 4.0.0 |
| requirements-release.lock | opentelemetry-api | 1.45.1 |
| requirements-release.lock | packaging | 26.3 |
| requirements-release.lock | pillow | 13.0.0 |
| requirements-release.lock | proto-plus | 1.29.0 |
| requirements-release.lock | protobuf | 6.33.6 |
| requirements-release.lock | psutil | 7.2.2 |
| requirements-release.lock | pyasn1 | 0.6.5 |
| requirements-release.lock | pyasn1_modules | 0.4.2 |
| requirements-release.lock | pycparser | 3.11 |
| requirements-release.lock | pyparsing | 3.3.3 |
| requirements-release.lock | pywin32 | 312 |
| requirements-release.lock | pywin32-ctypes | 0.2.3 |
| requirements-release.lock | pywinauto | 0.6.9 |
| requirements-release.lock | requests | 2.34.2 |
| requirements-release.lock | requests-oauthlib | 2.0.0 |
| requirements-release.lock | shiboken6 | 6.11.3 |
| requirements-release.lock | six | 1.17.0 |
| requirements-release.lock | typing_extensions | 4.16.0 |
| requirements-release.lock | uritemplate | 4.2.0 |
| requirements-release.lock | urllib3 | 2.8.0 |
| requirements-macos.lock | PySide6 | 6.11.3 |
| requirements-macos.lock | PySide6_Addons | 6.11.3 |
| requirements-macos.lock | PySide6_Essentials | 6.11.3 |
| requirements-macos.lock | certifi | 2026.10.23 |
| requirements-macos.lock | cffi | 2.1.1 |
| requirements-macos.lock | charset-normalizer | 3.5.2 |
| requirements-macos.lock | cryptography | 50.0.2 |
| requirements-macos.lock | google-api-core | 2.42.0 |
| requirements-macos.lock | google-api-python-client | 2.201.0 |
| requirements-macos.lock | google-auth | 2.61.0 |
| requirements-macos.lock | google-auth-httplib2 | 0.4.4 |
| requirements-macos.lock | google-auth-oauthlib | 1.5.0 |
| requirements-macos.lock | googleapis-common-protos | 1.75.5 |
| requirements-macos.lock | httplib2 | 0.32.0 |
| requirements-macos.lock | idna | 3.20 |
| requirements-macos.lock | jaraco.classes | 3.4.0 |
| requirements-macos.lock | jaraco.context | 6.1.2 |
| requirements-macos.lock | jaraco.functools | 4.6.0 |
| requirements-macos.lock | keyring | 25.7.0 |
| requirements-macos.lock | more-itertools | 11.1.0 |
| requirements-macos.lock | oauthlib | 4.0.0 |
| requirements-macos.lock | opentelemetry-api | 1.45.1 |
| requirements-macos.lock | packaging | 26.3 |
| requirements-macos.lock | pillow | 13.0.0 |
| requirements-macos.lock | proto-plus | 1.29.0 |
| requirements-macos.lock | protobuf | 6.33.6 |
| requirements-macos.lock | psutil | 7.2.2 |
| requirements-macos.lock | pyasn1 | 0.6.5 |
| requirements-macos.lock | pyasn1_modules | 0.4.2 |
| requirements-macos.lock | pycparser | 3.11 |
| requirements-macos.lock | pyparsing | 3.3.3 |
| requirements-macos.lock | requests | 2.34.2 |
| requirements-macos.lock | requests-oauthlib | 2.0.0 |
| requirements-macos.lock | shiboken6 | 6.11.3 |
| requirements-macos.lock | six | 1.17.0 |
| requirements-macos.lock | typing_extensions | 4.16.0 |
| requirements-macos.lock | uritemplate | 4.2.0 |
| requirements-macos.lock | urllib3 | 2.8.0 |
| requirements-macos.lock | pyobjc-core | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-Cocoa | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-AVFoundation | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-AVKit | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-CoreMedia | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-CoreAudio | 12.2.2 |
| requirements-macos.lock | pyobjc-framework-Quartz | 12.2.2 |
| requirements-linux.lock | PySide6 | 6.11.3 |
| requirements-linux.lock | PySide6_Addons | 6.11.3 |
| requirements-linux.lock | PySide6_Essentials | 6.11.3 |
| requirements-linux.lock | certifi | 2026.10.23 |
| requirements-linux.lock | cffi | 2.1.1 |
| requirements-linux.lock | charset-normalizer | 3.5.2 |
| requirements-linux.lock | cryptography | 50.0.2 |
| requirements-linux.lock | google-api-core | 2.42.0 |
| requirements-linux.lock | google-api-python-client | 2.201.0 |
| requirements-linux.lock | google-auth | 2.61.0 |
| requirements-linux.lock | google-auth-httplib2 | 0.4.4 |
| requirements-linux.lock | google-auth-oauthlib | 1.5.0 |
| requirements-linux.lock | googleapis-common-protos | 1.75.5 |
| requirements-linux.lock | httplib2 | 0.32.0 |
| requirements-linux.lock | idna | 3.20 |
| requirements-linux.lock | jaraco.classes | 3.4.0 |
| requirements-linux.lock | jaraco.context | 6.1.2 |
| requirements-linux.lock | jaraco.functools | 4.6.0 |
| requirements-linux.lock | keyring | 25.7.0 |
| requirements-linux.lock | more-itertools | 11.1.0 |
| requirements-linux.lock | oauthlib | 4.0.0 |
| requirements-linux.lock | opentelemetry-api | 1.45.1 |
| requirements-linux.lock | packaging | 26.3 |
| requirements-linux.lock | pillow | 13.0.0 |
| requirements-linux.lock | proto-plus | 1.29.0 |
| requirements-linux.lock | protobuf | 6.33.6 |
| requirements-linux.lock | psutil | 7.2.2 |
| requirements-linux.lock | pyasn1 | 0.6.5 |
| requirements-linux.lock | pyasn1_modules | 0.4.2 |
| requirements-linux.lock | pycparser | 3.11 |
| requirements-linux.lock | pyparsing | 3.3.3 |
| requirements-linux.lock | requests | 2.34.2 |
| requirements-linux.lock | requests-oauthlib | 2.0.0 |
| requirements-linux.lock | shiboken6 | 6.11.3 |
| requirements-linux.lock | six | 1.17.0 |
| requirements-linux.lock | typing_extensions | 4.16.0 |
| requirements-linux.lock | uritemplate | 4.2.0 |
| requirements-linux.lock | urllib3 | 2.8.0 |
| requirements-linux.lock | SecretStorage | 3.5.0 |
| requirements-linux.lock | jeepney | 0.9.0 |
| requirements-asr.txt | faster-whisper | 1.2.1 |
| requirements-asr.txt | ctranslate2 | 4.8.2 |
| requirements-asr.txt | onnxruntime | 1.31.0; sys_platform != "darwin" or platform_machine != "x86_64" |
| requirements-asr.txt | onnxruntime | 1.23.2; sys_platform == "darwin" and platform_machine == "x86_64" |
| requirements-asr.txt | av | 19.0.2 |
| requirements-asr.txt | numpy | 2.5.4 |
| requirements-asr.txt | tokenizers | 0.23.3 |
| requirements-asr.txt | huggingface-hub | 2.2.0 |
| requirements-asr.txt | filelock | 4.2.7 |

关键 npm 实际版本（其余见锁）：

| 包 | 版本 |
|---|---|
| remotion | 4.0.540 |
| @remotion/cli | 4.0.540 |
| react | 19.2.0 |
| react-dom | 19.2.0 |
| zod | 4.6.7 |
| fast-uri | 3.1.9 |
| webpack | 5.112.2 |
| ajv | 8.20.0 |

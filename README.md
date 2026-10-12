# Flow Studio 0.13.5.107

## 视频包装新增功能（当前源码，尚未发布安装包）

“识别 / 校对”支持当前视频或批量识别字幕、逐条修改时间和文字、批量粘贴文案校对、导出 SRT。批量套用包装样式保留每条视频各自的字幕。识别支持本地 Whisper，以及 Groq、ElevenLabs、Gladia、Gemini；云端识别需要自己的 API Key，音频会发送到所选服务，费用由对应服务计算。密钥保存在系统凭据库，不写入工程文件。

侧边栏“组件管理”集中提供组件检查、本地识别组件安装、模型下载/重试、FFmpeg 和 Remotion 自动安装，以及云端识别密钥配置。组件安装在软件数据目录；自动安装渲染引擎会准备 Node（缺少时）、Remotion 和所需浏览器，也可选择已有工程。本地识别音频不上传到云端，完整模型缓存下载成功后可离线使用。网络中断时可重试模型下载，已有完整缓存保留。

字幕新增 45 个 Reels 预设及字体、颜色、位置等调整。输出支持常用画幅、720p/1080p/2K/4K、帧率，以及 MP4/H.264、MOV/ProRes、WebM/VP9。可批量设置序号、前后缀、标题和日期命名，已有同名文件会自动避让。

水印支持多层图片、GIF 和视频，分别设置位置、透明度与大小，图片/GIF 可选去黑白底。原有标题文字、B-roll、片头片尾保留。“预览成片效果”按当前播放位置渲染完整图层；播放器中的快速字幕预览用于日常调整。工作台顶部操作合为一排，默认打开字幕设置，分类按钮快速切换。底部时间轴显示按时长排列的视频、原音频、字幕、标题、水印、B-roll 和片头片尾；点击字幕可选中文案并定位原视频。片头片尾实际画面通过成片预览查看。

已在 Windows 隔离环境验证本地语音识别、三种实际视频输出和成片静帧预览。云端付费识别未做真实账号调用；此次新增功能尚未在 macOS/Linux 实机验证。来源与适配说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

最新版提供统一图标、界面版本号和“检查更新”。在 Releases 下载 Windows Setup.exe、Mac（arm64 / x86_64）DMG 或 Linux amd64 DEB。安装包内置 Python。Linux 适配 Ubuntu 22.04/24.04 和 Debian 系 x64，需有桌面环境及系统软件安装器；达芬奇窗口自动点击暂需手动操作。

更新：点击侧栏底部版本按钮 → 检查更新 → 下载安装包 → 校验通过后“退出并安装”。Windows 打开安装向导，Mac 打开 DMG 后拖入 Applications 替换，Linux 打开系统安装器。所有安装行为均由用户确认，不自动强制结束任务。

安装版数据目录：Windows `%LOCALAPPDATA%/FlowStudio/data`，Mac `~/Library/Application Support/FlowStudio/data`，Linux `${XDG_DATA_HOME:-~/.local/share}/FlowStudio/data`。旧源码和 Windows 便携版仍使用原目录数据，不会自动搬迁。安装、卸载和升级都不主动删除用户数据。

三种系统使用同一 SVG 图标生成 PNG/ICO/ICNS。构建工作流为 `.github/workflows/installers.yml`，所有平台测试通过后才发布正式版本。安装包尚无商业代码签名/Apple 公证，系统可能提示未知发布者。更新信任官方 GitHub 仓库的 HTTPS 元数据与 SHA-256，不等同于独立签名验证。

以下为原便携版使用与审核说明，版本化审核报告仅描述其标注的审核版本。


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

## macOS Apple Silicon / Intel

GitHub Actions 的 **Build macOS Apple Silicon and Intel** 工作流分别在 `macos-15`（arm64）和 `macos-15-intel`（x86_64）运行。两种构建都通过依赖检查、单元测试、原生媒体框架导入、界面启动与重新解压后的启动验证后，自动附加到 v0.13.5.106 发布页。

下载名称含 `macOS-arm64` 的包用于 Apple M 系列；`macOS-x86_64` 用于 Intel。要求 macOS 13 或更新版本。解压后把 **Flow Studio.app** 放到应用程序目录，双击启动，无需安装 Python，不打开终端。软件未进行 Apple Developer ID 签名和公证；首次启动可能需要在“系统设置 → 隐私与安全性”允许打开。不要全局关闭系统安全检查。

Mac 包内含 Python 3.13.16（Astral python-build-standalone 20261009，固定 SHA-256）、Qt 和 PyObjC。运行依赖单独固定在 `requirements-macos.lock`；Intel 缺少 cryptography 50.0.2 的预编译 wheel，因此在 GitHub Mac 运行器上编译同一版本。内置环境不依赖本机 Homebrew。运行版本与包列表保存在应用内部 `Contents/Resources/RUNTIME_MANIFEST.json`。

Mac 应用数据与日志位于 `~/Library/Application Support/FlowStudio/data`，更新应用不会覆盖它们。源码直接运行仍保留原目录布局。旧 Windows DPAPI 凭据不能直接迁移到 Mac，需重新授权 Google。Mac OAuth 文件采用用户读写权限限制，未声称有 Windows DPAPI 加密。达芬奇自动控制可能需要系统的辅助功能与自动化授权，真实 Flow/达芬奇业务流程仍须在用户环境验证。

扩展在应用内部 `Contents/Resources/extension`，可通过 Finder“显示包内容”找到并加载。构建使用的第三方 Actions 固定到提交 SHA，构建阶段仅有只读权限，发布阶段才有上传附件权限。工作流只接受手动启动，不运行不可信 PR 的发布脚本。


### 视频包装组件与批量执行

- 组件管理顶部显示状态、耗时和日志；检查、安装、模型下载在独立进程运行，可停止。网络错误会保留模型缓存并最多尝试三次；这不能代替修复代理或网络连接。
- 字幕服务在组件管理里批量配置密钥，GPT 在 AI 设置里批量配置。每行一个，最多 20 个，去重后替换所选服务的列表；凭据仅存于系统凭据库。任务依次轮询，状态查询不消耗轮询位置。临时输入或 API 环境变量中的单密钥优先。不会因为请求超时自动换密钥重复提交付费请求。
- 批量渲染逐项执行，单项并发为 1，视频解码线程为 1，两类视频缓存分别限制为 128 MiB（不是整个进程的内存上限）。低内存时最多等待 5 分钟再决定跳过，后台进程降低优先级，15 分钟没有输出会终止该项并由队列继续处理后续任务。
- 原生 Windows/macOS/Linux 构建脚本使用安装包自己的 Python 下载字幕依赖、FFmpeg、Node、Remotion、浏览器和 base 模型到独立的 `bundled-components` 目录；不会复制开发电脑的 data、日志或密钥。任何预装步骤失败都会终止构建。首次组件操作在后台复制到用户可写目录；medium/large 模型仍按需下载。新增预装流程尚需三平台 CI 完整验证，旧安装包不会自动获得这些组件。


### 原生快速渲染与编辑布局

视频包装的“参数 → 渲染方式”提供自动（优先 FFmpeg）、FFmpeg CPU、Remotion 兼容。新任务默认使用 Reels 白字样式；旧模板的 CSS 字幕、连续滚动和旧水印会明确转到兼容路径，不会静默替换已有样式。Reels 透明字幕通过有完整空白间隔的 PNG 时间序列交给 FFmpeg，免去 Chromium 和中间 MOV 编码。支持标题、B-roll、图片/GIF/视频水印、片头片尾和音频拼接；未知视频时长由后台探测，不再默认按 30 秒截断。

H.264 自动模式会实际探测 NVIDIA NVENC，使用 p5/CQ16；不可用时使用两线程 CPU veryfast/CRF16。输出分辨率和帧率遵循界面参数，高画质重编码不是数学无损。滤镜线程固定为 1，任务串行，失败有详情，用户可停止。FFmpeg 路径和 Remotion 路径分别检查可用内存；任一任务长时间无输出会停止该项。

工作台保留左任务、中预览、右设置、下时间轴；导入和模板次要操作收进菜单，空的附加时间轨隐藏。组件页分成渲染、字幕识别、API 密钥和兼容引擎四页，详情默认折叠。

本机验证：用户提供的 `D:\合成\001.mp4` 前 30 秒，1080×1920/30fps，NVIDIA CQ16，含 Reels 字幕，耗时 44.64 秒，进程树 RSS 峰值 535.2 MiB。顶部无字幕区域与源视频的 SSIM 为 0.99558，仅用于检查编码质量，不代表整段有字幕画面完全相同。已验证组合导出、字幕前后空白、中文标题和成片预览；这是 Windows 单机样本，不能保证所有机器/长队列的相同速度或零故障。

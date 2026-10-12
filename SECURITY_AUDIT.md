# Flow Studio 安全审核报告

审核日期：2026-10-10 至 2026-10-12。当前源码版本：1.0.0；随包扩展：0.9.66。2026-10-11 报告中的 0.13.5.106 / 1.8.6 记录仍保留。

## 1. 项目概况与范围

Python/PySide6 桌面 UI、SQLite、本地 HTTP 桥接、Google OAuth/Sheets/Drive、OpenAI Responses 客户端、Chrome Manifest V3 扩展、达芬奇 Lua/Windows 自动化。原直接依赖清单 7 项；按实际运行导入补计 Pillow 与 pywin32 共 9 项，发行锁定运行分发包共 42 项。Node 仅运行无 npm 依赖的扩展回归测试，未发现发行源码的 npm/go/cargo/maven/Pod 依赖清单或 CI 工作流。

对发行白名单逐文件进行静态危险模式筛查和凭据扫描，人工重点审阅 HTTP、文件、凭据、扩展消息、进程调用、SQL 与生成调度边界，并检查本地数据中的凭据候选。旧插件副本、旧构建物及共享开发环境单独排除，不作为发行物。未分析第三方二进制内部实现，未做真实账号攻击测试、付费生成或达芬奇现场端到端验证。未初始化 Git 的原目录不存在可审查的本地 Git 历史；不能据此证明历史从未泄露。

## 2. 问题汇总

严重级别是本项目风险评估，依赖项同时参考公告；利用通常需要不可信网页、任务内容、响应或具有桥接访问权的本地程序。

| 编号 | 类别 | 严重级别 | 位置 | 状态 | 风险与修复 |
|---|---|---|---|---|---|
| D01 | 依赖 | High | requirements-release.lock:27 | 已修复 | protobuf 4.25.9 → 6.33.6；嵌套 Any/ParseDict 拒绝服务，未发现业务直接调用受影响入口。 |
| D02 | 依赖 | High | requirements-release.lock:15 | 已修复 | httplib2 0.31.2 → 0.32.0；不可信压缩响应可耗尽内存，Google HTTP 客户端使用该库。 |
| D03 | 依赖 | High | requirements-release.lock:29 | 已修复 | pyasn1 0.6.3 → 0.6.4；ASN.1/OID 恶意输入消耗资源，间接用于 Google 认证，实际攻击输入可达性待确认。 |
| D04 | 依赖 | Medium | requirements-release.lock:22 | 已修复 | OAuthlib 3.3.1 → 4.0.0；PKCE 服务端验证时序问题，本软件为 OAuth 客户端，未发现受影响服务端入口。 |
| D05 | 依赖 | Medium | requirements-release.lock:16 | 已修复 | idna 3.11 → 3.20；恶意域名编码的拒绝服务。 |
| C01 | 代码 | High | app/services/local_bridge.py:244 | 已修复 | 恶意网页跨源访问及 DNS rebinding；校验 Host/Origin、取消通配 CORS、精确匹配免鉴权接口。 |
| C02 | 代码 | High | app/services/bridge_security.py:15 | 已修复 | 掌握桥接令牌后可能读取任意文件；现在仅允许已发布任务引用的媒体文件。 |
| C03 | 代码 | Medium | app/services/pre_gpt_pipeline.py:1333 | 已修复 | 本地管理接口遭跨站请求；限制来源、JSON 类型和请求体大小，拒绝跨站修改。 |
| C04 | 代码 | Medium | extension/FlowStudio_Web_Plugin_v1.8.3_IDENTITY_ALIAS_DOWNLOAD/background.js | 已修复 | 后台消息可能被不符合预期的页面触发；所有后台监听器校验自身扩展 ID 和 Flow 来源。 |
| C05 | 代码 | High | app/services/task_intake.py:258 | 已修复 | 伪造素材文件名可能越界写入；限制为文件 basename，拒绝分隔符/冒号，限制并校验 Base64。 |
| C06 | 代码 | Medium | app/services/redaction.py:3 | 已修复 | 结构化日志可能包含令牌；递归脱敏敏感字段、Bearer、API Key 与 OAuth 查询凭据，主异常栈也脱敏。 |
| C07 | 代码 | Medium | app/services/public_download.py:9 | 已修复 | 恶意任务图片网址可探测内网；公网地址校验、DNS IP 固定、每跳检查、限制响应体与跳转次数，保留 TLS 主机验证。 |
| C08 | 代码 | High | app/services/workflow.py:49 | 已修复 | 伪造回执可能移动或清理下载目录之外的视频；解析真实路径后限制在配置下载根目录内；辅助图同样受限。 |
| K01 | 密钥 | Medium | app/services/credential_file.py:5 | 已修复 | 本地 OAuth 刷新凭据原为明文；Windows DPAPI 加密，旧文件在下次读取时自动迁移。 |
| K02 | 密钥 | High | .gitignore:4; scripts/build_windows_portable.py:43 | 已修复 | 直接压缩工作目录可能发布真实凭据、数据库和日志；忽略规则加源码白名单，发行包单独扫描。 |
| K03 | 密钥 | High | app/services/credential_file.py | 已修复 | macOS/Linux 曾把 Google 刷新令牌明文写入 `google_token.json`。现在写入系统凭据库，回读一致后才把本地文件换成不含令牌的指针；凭据库失败则报错并保留原文件。 |
| C09 | 代码 | Medium | extension/FlowStudio_Web_Plugin_v0.9.66_FLOW_SUBMIT_HITTEST_FIX/downloads.js | 已修复 | 下载消息监听器未校验扩展 ID 与 `https://flow.google.com` 来源。已与其他后台监听器使用同一校验。 |
| C10 | 代码 | Low | extension/.../content.js 媒体地址 | 已修复 | 面板图片地址只接受 http、https、blob，避免 `javascript:` 一类地址进入 `img src`。 |
| C11 | 代码 | Low | scripts/packaging_components.py Node 压缩包 | 已修复 | Windows Node 压缩包改为逐项校验路径后写出，不再整包 `extractall`。 |
| R01 | 代码 | Medium | app/services/bridge_security.py:7 | 建议关注 | 桥接仍信任任意已安装 Chrome 扩展及本机同用户进程；严格固定扩展 ID/配对会改变安装流程，本次未加入。 |
| R02 | 依赖 | Low | requirements-release.lock:35 | 建议关注 | pywinauto 0.6.9 更新频率偏低；上游 datafilename 反序列化风险入口未被本项目调用。 |
| R03 | 代码 | Low | app/services/quiet_runtime.py:26 | 建议关注 | 原生组件 stderr 直接落本地日志，无法保证所有第三方输出都脱敏；日志和任务素材不随发行版发布。 |

## 3. 依赖核查与修复依据

原共享开发环境扫描有 92 条漏洞记录（含重复记录及不相关包），不能说本项目有 92 个漏洞。独立发行锁文件的 pip-audit 输出为 42 项、已知漏洞 0；原始发行扫描结果随源码的 `audit/release-audit.json` 保存。零命中只代表查询时公开数据库结果，不覆盖未知漏洞和 Qt 等原生子组件。构建 wheel 来源及 SHA-256 记录在 `audit/wheel-manifest.json` 和便携版 `RUNTIME_MANIFEST.json`。

- protobuf：[GHSA-7gcm-g887-7qv7](https://github.com/advisories/GHSA-7gcm-g887-7qv7)，修复分支 5.29.6 / 6.33.5；本次 6.33.6。扫描代码未发现直接使用受影响 ParseDict 入口。
- httplib2：[GHSA-j5g9-f88f-gfj3](https://github.com/advisories/GHSA-j5g9-f88f-gfj3)，High，修复 0.32.0；Google API 链路使用，攻击需控制或影响返回的压缩响应。
- pyasn1：[OID 资源耗尽公告](https://github.com/advisories/GHSA-8ppf-4f7h-5ppj)、[相关公告一](https://github.com/advisories/GHSA-m4p7-r5rc-7g4j)、[相关公告二](https://github.com/advisories/GHSA-hm4w-wwcw-mr6r)，固定 0.6.4。未证明认证输入可被外部攻击者直接控制。
- OAuthlib：[GHSA-xpv3-w29h-x7cv](https://github.com/advisories/GHSA-xpv3-w29h-x7cv)，Medium，修复 4.0.0。本项目使用 OAuth 客户端，不是公告中的授权服务器。
- idna：[GHSA-65pc-fj4g-8rjx](https://github.com/advisories/GHSA-65pc-fj4g-8rjx)，Medium，修复 3.15，本次 3.20。

protobuf 与 OAuthlib 的大版本升级经开发者批准，只在独立发行环境完成。其他精确版本见下表；没有用原共享环境整体冻结代替项目依赖分析。

直接依赖逐项检索官方公告/维护状态：

| 直接依赖 | 当前结论 | 官方依据 |
|---|---|---|
| PySide6 | 升至 6.11.2；pip 扫描不等于 Qt 内置 C/C++ 库完整审计，待确认原生组件映射 | [安全说明](https://doc.qt.io/qtforpython-6/security/index.html) |
| google-api-python-client | 2.201.0，维护模式并不等于停止安全维护 | [安全公告](https://github.com/googleapis/google-api-python-client/security/advisories) |
| google-auth | 2.61.0，原仓库迁移到 monorepo，不判定为弃用包 | [官方迁移仓库](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-auth) |
| google-auth-oauthlib | 1.5.0，与 OAuthlib 4.0.0 测试兼容 | [官方 changelog](https://github.com/googleapis/google-cloud-python/blob/main/packages/google-auth-oauthlib/CHANGELOG.md) |
| keyring | 25.7.0，查询未命中该版本公开漏洞；Windows 使用系统凭据库 | [安全政策](https://github.com/jaraco/keyring/security) |
| pywinauto | 0.6.9，低更新频率；datafilename pickle 风险入口未使用，未编造 CVE | [上游问题](https://github.com/pywinauto/pywinauto/issues/1481) |
| psutil | 7.2.2；历史 GHSA-qfc5-mcwq-26q8 的修复版本为 5.6.6，当前不在影响范围 | [公告](https://github.com/advisories/GHSA-qfc5-mcwq-26q8) |
| Pillow | 12.3.0；此次扫描未命中，核对官方近期公告 | [安全公告](https://github.com/python-pillow/Pillow/security/advisories) |
| pywin32 | 312；用于 Windows UI 和 DPAPI；未调用 Pythonwin 编辑器组件 | [官方变更记录](https://github.com/mhammond/pywin32/blob/main/CHANGES.md) |

发行 Python 为官方 [3.13.16](https://www.python.org/downloads/release/python-31316/)，没有把旧开发环境 3.12.9 打入包。未发现可确认的仿冒包；未把仓库迁移或低更新频率等同于正式停止维护。

### 全部运行依赖实际版本

| 分发包 | 精确版本 | 用途分类 |
|---|---|---|
| PySide6 | 6.11.2 | 直接 |
| PySide6_Addons | 6.11.2 | 间接/运行组件 |
| PySide6_Essentials | 6.11.2 | 间接/运行组件 |
| certifi | 2026.7.22 | 间接/运行组件 |
| cffi | 2.1.1 | 间接/运行组件 |
| charset-normalizer | 3.5.2 | 间接/运行组件 |
| comtypes | 1.4.17 | 间接/运行组件 |
| cryptography | 50.0.2 | 间接/运行组件 |
| google-api-core | 2.42.0 | 间接/运行组件 |
| google-api-python-client | 2.201.0 | 直接 |
| google-auth | 2.61.0 | 直接 |
| google-auth-httplib2 | 0.4.4 | 间接/运行组件 |
| google-auth-oauthlib | 1.5.0 | 直接 |
| googleapis-common-protos | 1.75.5 | 间接/运行组件 |
| httplib2 | 0.32.0 | 间接/运行组件 |
| idna | 3.20 | 间接/运行组件 |
| jaraco.classes | 3.4.0 | 间接/运行组件 |
| jaraco.context | 6.1.2 | 间接/运行组件 |
| jaraco.functools | 4.6.0 | 间接/运行组件 |
| keyring | 25.7.0 | 直接 |
| more-itertools | 11.1.0 | 间接/运行组件 |
| oauthlib | 4.0.0 | 间接/运行组件 |
| opentelemetry-api | 1.45.1 | 间接/运行组件 |
| packaging | 26.3 | 间接/运行组件 |
| pillow | 12.3.0 | 直接 |
| proto-plus | 1.29.0 | 间接/运行组件 |
| protobuf | 6.33.6 | 间接/运行组件 |
| psutil | 7.2.2 | 直接 |
| pyasn1 | 0.6.4 | 间接/运行组件 |
| pyasn1_modules | 0.4.2 | 间接/运行组件 |
| pycparser | 3.11 | 间接/运行组件 |
| pyparsing | 3.3.3 | 间接/运行组件 |
| pywin32 | 312 | 直接 |
| pywin32-ctypes | 0.2.3 | 间接/运行组件 |
| pywinauto | 0.6.9 | 直接 |
| requests | 2.34.2 | 间接/运行组件 |
| requests-oauthlib | 2.0.0 | 间接/运行组件 |
| shiboken6 | 6.11.2 | 间接/运行组件 |
| six | 1.17.0 | 间接/运行组件 |
| typing_extensions | 4.16.0 | 间接/运行组件 |
| uritemplate | 4.2.0 | 间接/运行组件 |
| urllib3 | 2.8.0 | 间接/运行组件 |

## 4. 代码与凭据检查说明

SQL 查询的用户值使用参数绑定；动态表名/字段路径重点检查了固定集合来源。没有确认可利用的 SQL/NoSQL 注入；并不代表未来新增路径自动安全。Windows 自动化使用参数数组和受控命令解析，不通过 shell 执行任务文案；进程结束校验 PID 创建时间和所属记录。没有发行 Electron/nodeIntegration/WebView 远程页面，未发现本项目执行不可信 pickle 或 eval 的调用链。归档构建限制解压路径，阻止 `..`、绝对路径、冒号和反斜杠逃逸。HTTP 下载未关闭 TLS 校验，公网图片 DNS 检查后固定连接 IP，证书验证仍使用原始主机名。

扩展没有新增远程脚本执行；MAIN world 与 Flow 页面共享信任边界，Flow 自身被攻陷不属于跨源检查可隔离的情况。`debugger` 用于既有 UI 提交与自动化，`downloads` 用于下载回执，Google 域名权限用于素材和表格；未擅自删除这些功能权限。安装者需理解其权限范围。没有可审查的 GitHub Actions 工作流，因此没有发现 pull_request_target 或第三方 Action 固定版本问题。

本地发现 Google OAuth 文件包含有效格式的 refresh_token/client_secret 字段，报告不写出值。未在发行白名单扫描中发现真实硬编码 API Key/私钥；数据库字段扫描未命中凭据模式，这不等于对所有任意格式密钥的证明。Google desktop client_secret 本身不能替代用户 refresh_token；两者仍都排除发布。API Key 继续采用环境变量或系统凭据库；`.env.example` 仅列变量名。

**凡已提交或分享过的密钥，必须在对应平台撤销并重新生成；仅删代码无效。** 此次未证明它们已公开泄露，也未擅自轮换。DPAPI 仅保护其他账户/离线读取，无法防止同一 Windows 用户权限下的恶意进程。原 OAuth 明文在新版下次加载时迁移，不能声称旧目录当前已全部加密。

## 5. 功能恢复与验证

恢复缺失的 camera_aux、辅助图规划、原生 2K/4K 下载确认、实际图片尺寸检查、首尾帧请求检查和 MATERIAL 模式；没有通过删除原功能测试来掩盖缺失。Qt 文件选择器及导出确认框替代便携 Python 不包含的 tkinter。便携启动优先使用自带 pythonw，源代码本地运行仍保留。

验证：隔离便携 Python 的 unittest 81 项通过（包含真实回环 HTTP、DPAPI 测试和 Lua 行为测试）；扩展 32 个回归测试文件通过；界面构造/渲染烟雾测试通过。Lua 测试额外使用 lupa 2.8，不作为运行依赖打包。测试不消耗真实模型额度，网络/网页与达芬奇交互大部分模拟。未宣称真实 Flow 网页的所有 DOM、2K 菜单和达芬奇版本已逐一验证。

## 6. 已批准取舍、剩余风险与建议

开发者已批准：独立环境大版本依赖升级、恢复原功能后发布、Windows 便携包、公网图片限制及配置下载根目录限制。以上已经实施，无待批准的发布阻断选项。

建议后续考虑桥接固定扩展 ID 或一次性配对（需安装流程设计）；目前信任本机同用户及已安装扩展。任务源 CSV 等非图片 URL 的使用仍应只配置可信来源。Qt/FFmpeg/Chromium 等原生组件的细粒度 SBOM/CVE 映射、Chrome/Resolve/可选外部工具具体版本审计均为**待确认**，不纳入 pip 零漏洞结论。UI 页面适配及真实账号全流程验收也为**待确认**。

发布应只从白名单 staging 生成源码和便携压缩包，附 SHA-256，并对 ZIP 文件清单与凭据模式再次检查。不要上传原始环境扫描、原始运行日志、截图中的任务信息或数据库。未来依赖升级仍需重新执行审计及功能测试。

## 7. 2026-10-12 复核

复核范围是当前源码、`requirements-release.lock`、`requirements-macos.lock`、`requirements-linux.lock`、`requirements-asr.txt`、`.github/workflows/installers.yml` 和 0.9.66 扩展运行文件。`build/`、`dist/`、`data/` 不作为发行物。本地原始扫描留在 `audit/local-2026-10-12/`，该目录已被 `.gitignore` 排除。

依赖：发行锁中的 urllib3 2.8.0 已包含 2026-09-15 公告的三项修复（GHSA-8988-9cw3-xx77、GHSA-vxq7-64xx-v4gw、GHSA-gh4c-6fx4-qh6g），当前版本不在受影响范围内。Pillow 12.3.0 是官方说明中上述 2026 年图像解析问题的修复版本。oauthlib 4.0.0、httplib2 0.32.0、protobuf 6.33.6、pyasn1 0.6.4、idna 3.20 仍高于此前记录的修复线。psutil 7.2.2 的公开页面未列出影响该版本的漏洞。Qt CVE-2025-4211 的修复版本早于 PySide6 6.11.2；PySide6 / FFmpeg / Chromium 的完整原生映射仍为**待确认**。未发现需要大版本升级才能修复的 Critical / High 项，因此没有改锁文件。pywinauto 0.6.9 仍是低更新频率，且本项目未调用其 datafilename 反序列化入口。

密钥：工作区 `data/google_token.json` 被 `/data/` 与 `*token*.json` 忽略。本次没有读取或记录其中的值。若该文件或任何 API Key 曾经离开这台电脑，必须在对应平台作废并重新生成；只改代码不够。

插件：Windows、macOS、Linux 构建都只复制 0.9.66 的运行文件。`REPLACE.txt` 说明以后可以直接替换该目录。1.8.3 源码目录仍在仓库里，三个平台的打包脚本都会跳过它，安装包不再附带。

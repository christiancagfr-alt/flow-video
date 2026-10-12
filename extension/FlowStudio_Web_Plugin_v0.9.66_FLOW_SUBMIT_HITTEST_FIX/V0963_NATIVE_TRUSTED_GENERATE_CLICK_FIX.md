# v0.9.63 Flow 原生可信点击修复

- 不改调度器、上传、下载、任务状态、素材绑定、恢复逻辑。
- Flow Generate DOM 已能正确定位，但 JS click 只产生视觉按压且未发起生成时，改为复用插件现有 chrome.debugger 通道。
- 新增 `Input.dispatchMouseEvent` 在 Generate 按钮中心发送浏览器级 mouseMoved / mousePressed / mouseReleased。
- MAIN world 通过 CustomEvent -> content script -> background.js 桥接。
- 若原生点击桥不可用，才回退旧 safeGenerateClick，避免直接中断。
- 不增加 manifest 权限：`debugger` 权限原版本已存在并用于原生拖图。

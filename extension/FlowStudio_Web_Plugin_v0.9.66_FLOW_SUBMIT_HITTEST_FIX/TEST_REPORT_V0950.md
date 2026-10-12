# v0.9.50 定向测试报告

本版在原有 24 个插件回归测试基础上新增 `v0950_exact_reference_binding_gate.test.cjs`，共 25 个测试脚本全部通过。

新增定向用例覆盖：
- 当前图片位于 `referenceMedia` 分支：允许；
- 图片 ID 仅存在于 cache：阻止；
- 图片 ID 仅存在于 history reference：阻止；
- 当前 generation media + IMAGE + prompt 局部绑定：允许；
- MATERIAL 请求出现 VIDEO_FRAMES：阻止；
- URL encoded `f.req` 中的局部 VIDEO_REFERENCES tuple：允许；
- reference marker、prompt 与图片 ID 分散在不同请求分支：阻止；
- 仅允许来自“当前选中附件指纹”的别名作为绑定身份；
- 指纹别名仅存在于 library/cache：阻止。

同时保留并通过：上传重试上限、READY gate、提交确认门禁、下载绑定、防重复提交、调度自动补位、跨波次间隔、失败回流等既有测试。

说明：这些是插件代码级/模拟请求结构回归测试；未使用用户真实 Flow 账号执行付费生成。因此真实 Flow 页面若再次改变内部请求结构，插件会按 fail-closed 策略阻止 MATERIAL 提交并在诊断中留下 proof reason，而不会静默降级为文生视频。

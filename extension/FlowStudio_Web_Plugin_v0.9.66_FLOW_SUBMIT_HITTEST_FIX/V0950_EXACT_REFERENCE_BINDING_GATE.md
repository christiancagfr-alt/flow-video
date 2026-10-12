# v0.9.50 Exact Reference Binding Gate

## 问题根因
v0.9.49 已经在真实 Flow fetch/XHR 请求边界阻止“完全不含素材 ID”的请求，但其判断仍然过宽：只要整个请求负载任意位置出现当前图片 ID，就可能被视为“素材已带上”。Flow 请求中同一图片 ID 可能同时存在于素材库、缓存、历史状态、预览/缩略图等非生成输入分支，因此会产生假阳性：插件放行，但实际 generation input 并没有 reference material，最终变成文生视频。

## v0.9.50 修复
1. **从“ID 出现”升级为“绑定关系证明”**
   - 必须证明当前任务图片 ID/绑定 ID 位于本次 generation request 的 reference/material/input-media 语义分支内；
   - 仅出现在 cache/history/library/catalog/thumbnail/preview 等分支时明确拒绝；
   - 位置式/压缩数组请求要求图片 ID 与 VIDEO_REFERENCES/IMAGE/当前 prompt 在同一局部请求子树内，不接受“在请求不同位置分别出现”。

2. **绑定指纹来自当前刚选中的素材对象**
   - 点击生成前，从当前 composer/editor 或实际选中 reference signal 中抓取本次图片的附件子对象；
   - 提取该附件对象的精确身份集合，网络门禁只信任这批身份；
   - 不再把素材库对象的任意别名当成充分证据。

3. **最终模式复核**
   - 素材稳定 3 次后、点击 Generate 之前再次确认当前模式仍为 VIDEO_REFERENCES；
   - 请求体如果出现 VIDEO_FRAMES/FIRST_FRAME 证据，MATERIAL 请求直接阻止。

4. **更完整的请求解析**
   - 支持 JSON、URLSearchParams/FormData、ArrayBuffer/TypedArray，以及 Flow 常见的 URL-encoded `f.req`/batchexecute 封装；
   - 无法解析或无法证明绑定关系时 fail-closed：不发送，不降级成文生视频。

5. **诊断增强**
   - 成功放行会记录 proof kind/path/score；
   - 阻止会记录 proof reason 与实际看到的素材身份，便于下一次拿诊断包直接定位 Flow 请求结构变化。

## 安全重试
下列错误都继续进入现有安全重挂图重试链：
- REFERENCE_MATERIAL_BINDING_FINGERPRINT_NOT_FOUND
- REFERENCE_MATERIAL_NOT_BOUND_IN_GENERATION_REQUEST
- REFERENCE_MATERIAL_REQUEST_UNVERIFIABLE
- FLOW_MODE_CHANGED_BEFORE_SUBMIT

原则仍然是：**MATERIAL 没有当前任务的真实 reference binding 证明，就绝不让生成请求离开浏览器。**

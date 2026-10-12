# Web Plugin v0.9.23 测试报告

- manifest JSON：PASS
- Node syntax：background.js / content.js / downloads.js / page-engine.js / result-core.js 全部 PASS
- 与 v0.9.22 基线 byte compare：
  - downloads.js UNCHANGED
  - page-engine.js UNCHANGED
  - result-core.js UNCHANGED
  - styles.css UNCHANGED

尚未在本环境执行真实 Google Flow 多账号、多 tab、最小化数小时压力测试；需要用户 Mac 实机验收。

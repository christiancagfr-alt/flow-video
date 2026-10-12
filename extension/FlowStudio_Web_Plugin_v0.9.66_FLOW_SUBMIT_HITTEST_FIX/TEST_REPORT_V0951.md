# Flow Studio Web Plugin v0.9.51 test report

- JavaScript syntax checks: PASS (`content.js`, `page-engine.js`).
- Existing regression suite: 25 legacy/current tests PASS.
- New v0.9.51 MATERIAL direct-attachment regression: PASS.
- Total test scripts: 26 / 26 PASS.

New coverage verifies that MATERIAL:
- keeps the same Flow native image-selection primitive used by FRAME;
- falls back to the proven local-file native drag transport, targeted at the active composer;
- has composer-scoped file-input and synthetic-drag fallbacks;
- accepts only fresh active reference evidence after direct attachment;
- preserves the v0.9.50 exact request binding gate.

No live paid Flow generation was executed by the test suite.

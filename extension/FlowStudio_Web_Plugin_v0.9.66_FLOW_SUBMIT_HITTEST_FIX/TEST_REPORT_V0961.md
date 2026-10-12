# v0.9.61 Test Report

- JavaScript syntax checks: content.js / page-engine.js / background.js passed.
- Plugin regression tests: 33 passed, 0 failed.
- New coverage: ENGINE_BUSY is treated as transient executor contention and retried with serialized backoff; cancelled commands abort before retrying.

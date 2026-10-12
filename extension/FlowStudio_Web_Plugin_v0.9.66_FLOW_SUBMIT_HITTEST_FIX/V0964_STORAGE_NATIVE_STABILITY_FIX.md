# v0.9.64 Storage + Native Click Stability Fix

Incremental changes only:

- Recovery-state persistence can no longer abort a Flow generation when sessionStorage quota is exceeded.
- Old `flowStudioPending935:*` records are cleaned before one retry; if storage still fails, submission continues and existing request-observation gates remain authoritative.
- A Flow tab whose debugger session was detached is no longer permanently blocked by `BACKGROUND_GUARD_DISMISSED`; the next native action attempts to reacquire the debugger session.
- No scheduler, upload, download, task-state, material/frame-mode, or result-binding logic was intentionally changed.

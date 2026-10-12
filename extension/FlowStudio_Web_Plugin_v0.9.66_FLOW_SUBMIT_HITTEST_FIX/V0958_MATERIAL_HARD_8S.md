# v0.9.58 — MATERIAL HARD 8S

- MATERIAL / VIDEO_REFERENCES no longer leaves Flow's hidden duration state untouched.
- Even when Flow hides the duration picker, the plugin explicitly writes the internal duration signal to 8 before binding the asset.
- After asset selection it verifies the duration is still 8 and repairs it once if Flow retained a previous FRAME 4/6-second value.
- FRAME duration behavior is unchanged.
- MATERIAL binding protection remains relaxed as requested.

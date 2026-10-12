# v0.9.41 FRAME / MATERIAL

- Read per-task `generation_mode` from Flow Studio.
- `FRAME` maps to Flow `VIDEO_FRAMES` (first-frame image).
- `MATERIAL` maps to Flow `VIDEO_REFERENCES` (reference material).
- Generation mode participates in task-wave identity so a mode revision cannot be mistaken for the old wave.
- Existing timeout recovery, duplicate protection, upload, download and result binding logic remain unchanged.

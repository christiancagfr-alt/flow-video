# v0.9.57 — CONFIRMED INTERVAL + RELAXED MATERIAL

- MATERIAL keeps Flow-native uploaded-asset `select(item)` binding.
- Removed fail-closed exact material binding/network-request protection and material binding retry loop.
- MATERIAL remains fixed at 8 seconds.
- Submission spacing is now re-armed from the actual confirmed/uncertain submission outcome, so a one-task wave cannot clear and immediately fire the next wave.
- Existing upload/download/recovery/channel logic is unchanged.

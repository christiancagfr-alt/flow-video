# v0.9.52 Native Flow Asset Material Binding

## Root cause

v0.9.51 could drop a local file directly into the VIDEO_REFERENCES composer as a fallback. Flow may render that drop immediately, but the attachment can remain a transient upload placeholder and turn grey with an exclamation mark because it never becomes a valid Flow reference asset.

## Fix

MATERIAL now follows the stable part of FRAME mode:

1. The image must already exist as a completed Flow `IMAGE` asset.
2. The live catalog entry is re-read and must have a resolved remote media URL and no loading/error flags.
3. `VIDEO_REFERENCES` is set first and must remain stable across consecutive checks.
4. The same Flow-native `select(item)` primitive used by FRAME is used to bind the formal asset.
5. Binding is retried at most 3 times. Between attempts the composer is cleared and MATERIAL settings are rebuilt.
6. No local `File`, debugger drag, composer file input, or synthetic drag is used for MATERIAL binding.
7. Prompt writing preserves the native reference object. If prompt writing loses the reference, the same native-asset binding routine runs again.
8. v0.9.50 exact request-level binding verification remains the final fail-closed gate.

FRAME behavior, workspace upload, downloads, scheduling and result binding are unchanged.

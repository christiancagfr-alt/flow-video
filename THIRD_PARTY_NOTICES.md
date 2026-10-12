# Third-party source adaptations

## video-toolkit / Reels editor

Source: https://github.com/christiancagfr-alt/video-toolkit

Reference commit: `6ada5903a7d927414eb2d9986036f3566b3f0303` (v1.7.71).

At the project owner's request, selected subtitle recognition, proofreading,
caption layout, painter, language rules, and preset components were adapted
for Flow Studio. They are in `app/services/reels/` and
`app/ui/packaging_proofread.py`. The upstream sources include `app.py`,
`modules/dynamic_caption_page.py`, `modules/caption_qt_burn.py`,
`modules/caption_rich.py`, `modules/language_style.py`, and
`modules/text_rules.py`. Existing source comments and attribution are retained.

Adaptations include isolated recognition processes, system credential storage,
Flow Studio project persistence, shared preview/export painting, deterministic
caption emphasis, PCM input compatibility, Remotion overlay integration, and native FFmpeg composition in
`app/services/packaging_ffmpeg.py`, following the upstream timed Qt PNG
caption-track approach.
Flow Studio's existing titles, B-roll, intro and outro remain in its renderer.

No repository-wide LICENSE file was found at the reference commit. This notice
does not assign a new license to the upstream code or imply unrestricted
redistribution rights. Upstream authors retain their rights.

Optional recognition packages and the separately installed Remotion engine
retain their own licenses. Speech models are downloaded separately and retain
their respective model terms. No model weights or third-party runtime binaries
are included in these adapted source files.

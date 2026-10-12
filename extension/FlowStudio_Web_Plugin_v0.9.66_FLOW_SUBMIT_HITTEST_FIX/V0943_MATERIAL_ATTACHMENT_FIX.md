# v0.9.43 MATERIAL attachment fix

- VIDEO_REFERENCES always selects the current task image; stale retained reference state is not used to skip placement.
- Prompt writes preserve non-text composer blocks so a material/reference chip is not erased.
- After prompt write the reference is re-verified. If it disappeared, the plugin re-selects the image once and preserves the media block while rewriting text.
- VIDEO_FRAMES first-frame behavior remains unchanged.

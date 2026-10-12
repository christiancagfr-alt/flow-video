# v0.9.51 FRAME-like MATERIAL direct attachment

Root cause addressed:

- FRAME mode has a reliable image-delivery path, but MATERIAL previously relied mainly on Flow's internal `select(item)`/Angular reference state.
- In some Flow renders the image existed in the library but never became a real `VIDEO_REFERENCES` composer attachment.
- v0.9.50 correctly blocked prompt-only requests, but blocking alone could not create the missing attachment.

v0.9.51 changes only MATERIAL attachment recovery:

1. MATERIAL still tries the same native Flow image-selection primitive used by FRAME first.
2. If no real reference appears quickly, the plugin reuses the proven local-file delivery stack used by image upload (Chrome debugger native drag -> scoped composer file input -> synthetic drag fallback).
3. The destination is the active generation composer, not the general Flow workspace.
4. After direct attachment, the page adapter accepts only a newly-created same-name media identity or a fresh active IMAGE reference record. Old library/cache rows are not proof.
5. Only after the reference survives the existing stability gate is the prompt written/submitted.
6. v0.9.50 exact request binding gate remains unchanged as the final fail-closed boundary.

FRAME behavior, workspace batch upload, downloads, scheduling and result binding are unchanged.

"""Called by native builders using the packaged Python ABI, never copy user data."""
import json
import os
import shutil
import subprocess
from pathlib import Path


def bundle(application, python):
    application = Path(application).resolve()
    destination = application / 'bundled-components'
    if destination.exists():
        if destination.resolve().parent != application: raise ValueError('Unsafe staging directory')
        shutil.rmtree(destination)
    env = dict(os.environ, FLOWSTUDIO_DATA_DIR=str(destination), FLOWSTUDIO_BUNDLE_NODE='1',
               PYTHONDONTWRITEBYTECODE='1', HF_HUB_DISABLE_XET='1')
    script = application / 'scripts/packaging_components.py'
    for action in ('asr', 'ffmpeg', 'remotion', 'model'):
        subprocess.run([str(python), '-X', 'utf8', str(script), action, 'base'],
                       cwd=application, env=env, check=True, timeout=1800)
    root = destination / 'packaging'
    names = ['node','remotion','models','asr-libs','ffmpeg-libs']
    for path in root.iterdir():
        if path.name not in names:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
    for cache in list(root.rglob('__pycache__')): shutil.rmtree(cache)
    # A failed download must fail the build, never produce a nominal offline installer.
    if not any((root/'models').rglob('model.bin')): raise RuntimeError('Missing base model')
    (destination/'manifest.json').write_text(json.dumps({'components':names,'model':'base'}), 'utf-8')

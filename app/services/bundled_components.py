"""Restore clean, native build assets into writable per-user component storage."""
import json
import shutil
import uuid
from pathlib import Path
from app.services.app_paths import APP_ROOT, data_dir


def restore(components=None):
    source = APP_ROOT / 'bundled-components/packaging'
    manifest = source.parent / 'manifest.json'
    if not manifest.is_file(): return
    target = data_dir() / 'packaging'
    target.mkdir(parents=True, exist_ok=True)
    for name in json.loads(manifest.read_text('utf-8'))['components']:
        if name not in ('node','remotion','models','asr-libs','ffmpeg-libs'):
            raise ValueError('Invalid bundled component')
        if components is not None and name not in components:continue
        destination = target / name
        # Preserve independently installed/upgraded components.
        if destination.exists(): continue
        staging = target / (name + '.restoring-' + uuid.uuid4().hex)
        print('正在准备预装组件：' + name, flush=True)
        try:
            shutil.copytree(source / name, staging)
            try: staging.rename(destination)
            except OSError:
                if not destination.is_dir(): raise
        finally:
            if staging.is_dir() and staging.resolve().parent == target.resolve():
                shutil.rmtree(staging)

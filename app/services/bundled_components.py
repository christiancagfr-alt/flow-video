"""Restore clean, native build assets into writable per-user component storage."""
import json
import platform
import shutil
import sys
import uuid
from pathlib import Path
from app.services.app_paths import APP_ROOT, data_dir


def restore(components=None):
    source = APP_ROOT / 'bundled-components/packaging'
    manifest = source.parent / 'manifest.json'
    if not manifest.is_file(): return
    target = data_dir() / 'packaging'
    target.mkdir(parents=True, exist_ok=True)
    is_x86_mac = (sys.platform == 'darwin' and platform.machine().lower() == 'x86_64')
    for name in json.loads(manifest.read_text('utf-8'))['components']:
        if name not in ('node','remotion','models','asr-libs','ffmpeg-libs'):
            raise ValueError('Invalid bundled component')
        if components is not None and name not in components:continue
        src_dir = source / name
        if is_x86_mac and name == 'asr-libs' and (source / 'asr-libs-x86_64').is_dir():
            src_dir = source / 'asr-libs-x86_64'
        elif is_x86_mac and name in ('node', 'remotion') and not (source / f'{name}-x86_64').is_dir():
            continue
        destination = target / name
        # Preserve independently installed/upgraded components.
        if destination.exists(): continue
        staging = target / (name + '.restoring-' + uuid.uuid4().hex)
        print('正在准备预装组件：' + name, flush=True)
        try:
            shutil.copytree(src_dir, staging)
            try: staging.rename(destination)
            except OSError:
                if not destination.is_dir(): raise
        finally:
            if staging.is_dir() and staging.resolve().parent == target.resolve():
                shutil.rmtree(staging)

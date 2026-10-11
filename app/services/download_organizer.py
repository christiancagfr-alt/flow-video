from __future__ import annotations
from pathlib import Path
import os
import re
import shutil
from app.core import repository as repo


def safe(value):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(value or '').strip()).strip('. ')
    return text[:90] or '未命名'


def organize(path, meta, event):
    src = Path(path).expanduser()
    root = Path(repo.get_setting('flow_download_root', str(Path.home() / 'Downloads' / 'FlowStudio'))).expanduser()
    folder = root / safe(meta.get('work_date')) / safe(meta.get('recipient_name')) / safe(meta.get('host_name')) / f"视频_{int(meta.get('video_seq') or 0):02d}"
    folder.mkdir(parents=True, exist_ok=True)
    retry = int(meta.get('flow_retry_count') or 0)
    round_no = int(event.get('round') or 1)
    base = f"{int(meta.get('video_seq') or 0):02d}-{int(meta.get('seg_seq') or 0):02d}"
    if retry:
        base += f"_retry{retry:02d}"
    if round_no > 1:
        base += f"_r{round_no}"
    dst = folder / (base + (src.suffix.lower() or '.mp4'))
    if src.resolve() == dst.resolve():
        return str(dst)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return str(dst)
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))
    return str(dst)

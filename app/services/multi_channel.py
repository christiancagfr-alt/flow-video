from __future__ import annotations
from pathlib import Path
import hashlib
from app.core import repository as repo


def ensure_for_host(host_id):
    count = repo.flow_channel_count(host_id)
    rework = repo.flow_rework_enabled(host_id)
    repo.ensure_flow_channels(host_id, count, rework)
    return list(repo.list_flow_channels(host_id=host_id, enabled_only=True))


def normal_channels(host_id):
    return [c for c in ensure_for_host(host_id) if c['role'] == 'normal']


def rework_channel(host_id):
    return next((c for c in ensure_for_host(host_id) if c['role'] == 'rework'), None)


def distribute(tasks, channels):
    channels = list(channels)
    out = {int(c['id']): [] for c in channels}
    if not channels:
        return out
    ordered = sorted(tasks, key=lambda t: (int(t['video_seq']), int(t['seg_seq'])))
    for i, task in enumerate(ordered):
        out[int(channels[i % len(channels)]['id'])].append(task)
    return out


def unique_images(tasks):
    seen, out = set(), []
    for task in tasks:
        path = str(task['image_path'] or '')
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def image_payload(paths):
    files, parts = [], []
    for image_path in paths:
        pp = Path(image_path)
        try:
            st = pp.stat()
            size, mtime = int(st.st_size), int(st.st_mtime_ns)
        except OSError:
            size, mtime = -1, -1
        files.append({'path': str(image_path), 'name': pp.name, 'size': size, 'mtime_ns': mtime})
        parts.append(f'{pp.name.lower()}|{size}|{mtime}')
    fp = hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:24]
    return files, fp


def record_event(event):
    cid = int(event.get('channel_id') or 0)
    if not cid:
        return
    typ = str(event.get('type') or '')
    repo.touch_flow_channel(cid, typ)
    if typ in {'upload_precheck', 'media_upload_started', 'media_upload_dispatched'}:
        repo.set_flow_channel_runtime(cid, 'uploading', command_id=event.get('command_id'), fingerprint=event.get('image_set_id'), total=event.get('total'))
    elif typ in {'media_match_progress', 'upload_flow_progress'}:
        repo.set_flow_channel_runtime(cid, 'uploading', uploaded=event.get('recognized', event.get('matched', 0)), total=event.get('total'))
    elif typ in {'media_ready', 'upload_verified'}:
        repo.set_flow_channel_runtime(cid, 'verified', command_id=event.get('command_id'), fingerprint=event.get('image_set_id'), uploaded=event.get('total', event.get('matched', 0)), total=event.get('total'), verified=True, error='')
    elif typ in {'upload_stopped', 'upload_verification_failed', 'media_upload_dispatch_failed'}:
        repo.set_flow_channel_runtime(cid, 'failed', error=str(event.get('error') or event.get('message') or '上传失败'))
    elif typ in {'generation_batch_finished', 'generation_paused'}:
        if repo.get_flow_channel_task_command(cid) == str(event.get('command_id') or ''):
            repo.set_flow_channel_task_command(cid, '')

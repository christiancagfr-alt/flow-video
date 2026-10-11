"""Validated auxiliary endpoints; never unlock a video from a thumbnail receipt."""
import json
import re
import shutil
from pathlib import Path
from app.core import database
from app.services import broll_presets


def meets_2k(width, height):
    return min(width, height) >= 1024 and max(width, height) >= 2048


def resolve(task):
    task = dict(task)
    plan = broll_presets.get_video_plan(str(task['video_id'])) or {}
    item = next((x for x in plan.get('video_plan', []) if str(x.get('SEGMENT_ID')) == str(task['segment_id'])), {})
    binding = item.get('IMAGE_BINDING') or {}
    endpoint = binding.get('END_IMAGE')
    if not endpoint:
        if (item.get('camera_motion') or {}).get('requires_aux_image'):
            raise RuntimeError('AUX_PLAN_MISSING: 请补充辅助结束帧规划')
        return task, {}
    if not re.fullmatch(r'SHOT_[0-9]+', str(endpoint)):
        raise ValueError('INVALID_AUX_SHOT_ID')
    with database.connect() as con:
        row = con.execute("SELECT * FROM asset_jobs WHERE video_id=? AND job_type='CAMERA_AUX_IMAGE' AND job_id=? ORDER BY id DESC LIMIT 1", (task['video_id'], endpoint)).fetchone()
    if not row or row['status'] != 'READY':
        raise RuntimeError('AUX_IMAGE_PENDING: 等待辅助结束帧图片')
    if row['download_method'] != 'flow_native_button' or not meets_2k(row['image_width'], row['image_height']):
        raise RuntimeError('REQUIRES_NATIVE_2K: 辅助图需要原生 2K 下载回执')
    path = Path(row['local_path'])
    if not path.is_file():
        raise RuntimeError('AUX_IMAGE_MISSING: 辅助图片不存在')
    task.update(end_image_path=str(path), camera_motion=item.get('camera_motion'), generation_mode='FRAME')
    return task, {endpoint: str(path)}


def accept(event):
    if str(event.get('task_type') or '').upper() != 'CAMERA_AUX_IMAGE':
        return False
    if event.get('type') not in ('image_download_started','image_download_completed'):return False
    sid = int(event.get('segment_id') or 0)
    with database.connect() as con:
        segment = con.execute('SELECT * FROM flow_segments WHERE id=?', (sid,)).fetchone()
        if not segment or str(segment['generation_command'] or '') != str(event.get('command_id') or ''):
            return True
        vid = int(segment['video_id'])
        if vid != int(event.get('video_id') or 0):
            raise ValueError('AUX_VIDEO_ID_MISMATCH')
        shot = str(event.get('shot_id') or '')
        if not re.fullmatch(r'SHOT_[0-9]+', shot) or not str(segment['foreign_text']).startswith('[辅助图] '+shot+':'):
            raise ValueError('AUX_SHOT_ID_MISMATCH')
        ready = con.execute("SELECT * FROM asset_jobs WHERE video_id=? AND job_type='CAMERA_AUX_IMAGE' AND job_id=? AND status='READY'", (vid, shot)).fetchone()
        if ready and Path(ready['local_path']).is_file():
            return True
        if event.get('type') != 'image_download_completed':
            return True
        if event.get('download_method') != 'flow_native_button' or str(event.get('resolution')).upper() not in ('2K', '4K'):
            raise ValueError('AUX_NATIVE_2K_RECEIPT_REQUIRED')
        source = Path(str(event.get('output_path') or ''))
        if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('AUX_IMAGE_FILE_MISSING')
        # Delete only the application's exact incoming directory after durable archive.
        incoming_parts = ('FlowStudio', '.incoming', f'VIDEO_{vid}', 'CAMERA_AUX')
        from app.services.workflow import managed_download_path
        if not managed_download_path(source) or tuple(source.resolve().parent.parts[-4:]) != incoming_parts:
            raise ValueError('AUX_INCOMING_PATH_REQUIRED')
        from PySide6.QtGui import QImageReader
        image = QImageReader(str(source)).read()
        if image.isNull() or not meets_2k(image.width(), image.height()):
            raise ValueError('AUX_REAL_2K_REQUIRED')
        target = database.DB_PATH.parent / 'assets' / 'camera_aux' / f'video_{vid}' / (shot + source.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        shutil.copyfile(source, temporary)
        temporary.replace(target)
        con.execute("""INSERT INTO asset_jobs(video_id,source_url,job_type,job_id,status,local_path,image_width,image_height,download_method)
          VALUES(?,?,'CAMERA_AUX_IMAGE',?,'READY',?,?,?,'flow_native_button')
          ON CONFLICT(video_id,source_url,asset_index) DO UPDATE SET status='READY',local_path=excluded.local_path,
          image_width=excluded.image_width,image_height=excluded.image_height,download_method=excluded.download_method""",
          (vid, 'camera_aux:'+shot, shot, str(target), image.width(), image.height()))
        con.execute("UPDATE flow_segments SET flow_status='已完成',flow_output_path=?,flow_error='' WHERE id=?", (str(target), sid))
        con.execute("UPDATE flow_dispatches SET status='detected',stage='COMPLETED',error='' WHERE segment_id=? AND command_id=?",(sid,event.get('command_id')))
    source.unlink(missing_ok=True)
    return True

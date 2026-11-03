"""Selective re-export of videos that were already exported.

Re-uses the existing FINISH_BATCH export-only path of the Resolve bridge. Nothing is
cleaned or deleted on the timeline; only the chosen videos get a fresh render.

Safety rules
- The old MP4 is renamed to ``*.reexport-bak`` first and only removed after the new
  file is confirmed. If the render fails, the old file is put back.
- The per-video export receipt is moved aside so the bridge renders that video again.
- Other videos in the same batch are never touched (the job carries ``only_video_ids``).
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from app.core import database
from app.core.naming import resolve_export_filename
from app.services import resolve_daily as daily

BACKUP_SUFFIX = '.reexport-bak'
_PENDING_TIMEOUT = 6 * 3600


def _dir():
    return daily.bridge_root() / 'v0_5_0' / 'reexport'


def expected_output(payload, index):
    path = Path(payload[f'v{index}_output_dir']) / resolve_export_filename(payload[f'v{index}_final_filename'])
    if path.suffix.lower() != '.mp4':
        path = path.with_name(path.name + '.mp4')
    return path


def _locate(day, video_id):
    with database.connect() as con:
        row = con.execute(
            "SELECT r.batch_id,r.attempt_id,r.payload_path FROM davinci_video_state s "
            "JOIN davinci_batches b ON b.batch_id=s.batch_id "
            "JOIN davinci_autoedit_runs r ON r.batch_id=s.batch_id "
            "WHERE s.video_id=? AND b.work_date=? AND b.status='COMPLETED' ORDER BY b.rowid DESC LIMIT 1",
            (int(video_id), day)).fetchone()
    if not row:
        raise ValueError(f'视频 {video_id} 找不到对应的已完成剪辑批次，无法重新导出。')
    payload = daily.read_pairs(Path(row['payload_path']))
    count = int(payload.get('video_count', '0') or 0)
    for i in range(1, count + 1):
        if payload.get(f'v{i}_id') == str(video_id):
            return {'batch_id': row['batch_id'], 'attempt_id': row['attempt_id'],
                    'payload_path': row['payload_path'], 'output': str(expected_output(payload, i))}
    raise ValueError(f'视频 {video_id} 不在批次清单中，无法重新导出。')


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def _records():
    folder = _dir()
    if not folder.is_dir():
        return []
    out = []
    for file in sorted(folder.glob('*.json')):
        try:
            out.append((file, json.loads(file.read_text(encoding='utf-8'))))
        except (OSError, ValueError):
            continue
    return out


def pending_count(day=None):
    return sum(1 for _f, rec in _records() if rec.get('status') == 'PENDING' and (day is None or rec.get('day') == day))


def _restore(entry):
    """Put the old file back unless a verified new one already exists."""
    out = Path(entry['output'])
    backup = Path(entry['backup'])
    try:
        if backup.is_file():
            if out.is_file() and out.stat().st_size > 0:
                backup.unlink()
            else:
                out.unlink(missing_ok=True)
                backup.replace(out)
    except OSError:
        pass
    receipt = Path(entry['receipt'])
    prev = Path(entry['receipt_prev'])
    try:
        if prev.is_file():
            if not receipt.is_file():
                prev.replace(receipt)
            else:
                prev.unlink()
    except OSError:
        pass


def _set_video(video_id, status, output=None):
    with database.connect() as con:
        if output is None:
            con.execute('UPDATE videos SET edit_status=? WHERE id=?', (status, int(video_id)))
        else:
            con.execute('UPDATE videos SET edit_status=?,edit_output_path=? WHERE id=?', (status, output, int(video_id)))


def submit(day, video_ids):
    from app.services import resolve_autoedit
    ids = sorted({int(v) for v in video_ids or []})
    if not ids:
        raise ValueError('请先选择要重新导出的视频。')
    state = daily.snapshot()
    if not state.get('alive') or 'FINISH_BATCH' not in state.get('capabilities', '').split(','):
        raise ValueError('达芬奇 Bridge 未连接。请先唤醒达芬奇（打开该日期的项目和对应时间线）。')
    if (state.get('stage') not in ('READY', 'WAITING_USER_REVIEW', 'ERROR')
            or state.get('project') != 'FlowStudio-' + day
            or not daily.is_valid_day_timeline(day, state.get('timeline', ''))):
        raise ValueError('请先唤醒所选日期的项目和对应时间线，并等待当前操作结束。')
    if pending_count() or any(daily.read_pairs(p).get('action') == 'FINISH_BATCH'
                              for p in (daily.bridge_root() / 'v0_5_0/commands').glob('*.job')):
        raise ValueError('上一次导出还在进行，请等它结束后再提交。')
    with database.connect() as con:
        busy = con.execute('SELECT 1 FROM davinci_batches WHERE work_date=? AND status IN (%s) LIMIT 1'
                           % ','.join('?' * len(resolve_autoedit.RUNNING_CROSS_TIMELINE)), (day, *resolve_autoedit.RUNNING_CROSS_TIMELINE)).fetchone()
    if busy:
        raise ValueError('当前有正在执行的剪辑或渲染批次，请等它结束后再重新导出已完成视频。')

    groups = {}
    for vid in ids:
        loc = _locate(day, vid)
        groups.setdefault(loc['batch_id'], {'loc': loc, 'ids': []})['ids'].append(vid)
    for _bid, grp in groups.items():
        pl = daily.read_pairs(Path(grp['loc']['payload_path']))
        expected_tl = pl.get('timeline_name') or ('MAIN-' + day)
        if state.get('timeline') != expected_tl:
            raise ValueError(f'所选视频位于时间线「{expected_tl}」，请先切换到对应时间线并点击「唤醒达芬奇」后再重新导出。')

    prepared = []
    try:
        for batch_id, group in groups.items():
            loc = group['loc']
            base = Path(loc['payload_path']).parent
            payload = daily.read_pairs(Path(loc['payload_path']))
            count = int(payload.get('video_count', '0') or 0)
            index = {payload.get(f'v{i}_id'): i for i in range(1, count + 1)}
            entries = []
            for vid in group['ids']:
                out = expected_output(payload, index[str(vid)])
                entry = {
                    'video_id': vid, 'status': 'PENDING', 'output': str(out),
                    'backup': str(out) + BACKUP_SUFFIX,
                    'receipt': str(base / f'export_{vid}.ini'),
                    'receipt_prev': str(base / f'export_{vid}.ini.prev'),
                    'old_status': '已导出', 'message': '',
                }
                with database.connect() as con:
                    row = con.execute('SELECT edit_status,edit_output_path FROM videos WHERE id=?', (vid,)).fetchone()
                entry['old_output'] = str(row['edit_output_path'] or '') if row else ''
                if row and str(row['edit_status'] or ''):
                    entry['old_status'] = str(row['edit_status'])
                if out.is_file():
                    Path(entry['backup']).unlink(missing_ok=True)
                    out.replace(entry['backup'])
                receipt = Path(entry['receipt'])
                if receipt.is_file():
                    Path(entry['receipt_prev']).unlink(missing_ok=True)
                    receipt.replace(entry['receipt_prev'])
                entries.append(entry)
                prepared.append(entry)
            request = uuid.uuid4().hex
            record = {'request_id': request, 'day': day, 'batch_id': batch_id, 'status': 'PENDING',
                      'created': time.time(), 'entries': entries, 'message': ''}
            _write(_dir() / (request + '.json'), record)
            for entry in entries:
                _set_video(entry['video_id'], '导出中')
            from app.services import scripture_subtitles
            sub_vids = scripture_subtitles.resolve_batch_subtitle_video_ids(
                batch_id, attempt_dir=base, video_ids=group['ids']
            )
            daily.atomic_pairs(daily.bridge_root() / 'v0_5_0/commands' / (request + '.job'), {
                'action': 'FINISH_BATCH', 'request_id': request, 'batch_id': batch_id,
                'attempt_id': loc['attempt_id'], 'payload_path': loc['payload_path'], 'work_date': day,
                'finish_mode': 'export', 'only_video_ids': ','.join(str(v) for v in group['ids']),
                'subtitle_video_ids': ','.join(str(v) for v in sub_vids),
            })
    except Exception:
        for entry in prepared:
            _restore(entry)
            _set_video(entry['video_id'], entry.get('old_status') or '已导出', entry.get('old_output') or None)
        raise
    return {'submitted': True, 'count': len(ids), 'batches': len(groups),
            'detail': f'已提交 {len(ids)} 个视频重新导出'}


def _job_state(request):
    root = daily.bridge_root() / 'v0_5_0'
    if (root / 'commands' / (request + '.job')).exists():
        return 'QUEUED', ''
    if (root / 'error' / (request + '.job')).exists():
        try:
            text = (root / 'error' / (request + '.job.txt')).read_text(encoding='utf-8').strip()
        except OSError:
            text = ''
        return 'ERROR', text[-200:]
    if (root / 'done' / (request + '.job')).exists():
        return 'DONE', ''
    return 'GONE', ''


def sync():
    for file, rec in _records():
        if rec.get('status') != 'PENDING':
            continue
        job, error_text = _job_state(rec['request_id'])
        finished = job in ('ERROR', 'DONE') or (job == 'GONE' and time.time() - float(rec.get('created') or 0) > 300)
        changed = False
        for entry in rec['entries']:
            if entry['status'] != 'PENDING':
                continue
            out = Path(entry['output'])
            receipt = daily.read_pairs(Path(entry['receipt']))
            if (receipt.get('status') == 'COMPLETE' and receipt.get('video_id') == str(entry['video_id'])
                    and out.is_file() and out.stat().st_size > 0):
                _set_video(entry['video_id'], '已导出', str(out))
                Path(entry['backup']).unlink(missing_ok=True)
                Path(entry['receipt_prev']).unlink(missing_ok=True)
                entry['status'] = 'OK'
                changed = True
            elif finished:
                if receipt.get('status') == 'SKIPPED':
                    entry['message'] = '时间线上找不到这个视频（可能已被删除），没有重新导出'
                elif job == 'ERROR':
                    entry['message'] = error_text or '达芬奇导出出错'
                else:
                    entry['message'] = '导出没有完成'
                _restore(entry)
                _set_video(entry['video_id'], entry.get('old_status') or '已导出', entry.get('old_output') or None)
                entry['status'] = 'FAILED'
                changed = True
        if all(e['status'] != 'PENDING' for e in rec['entries']):
            ok = sum(1 for e in rec['entries'] if e['status'] == 'OK')
            bad = len(rec['entries']) - ok
            rec['status'] = 'DONE'
            rec['message'] = f'重新导出完成：成功 {ok} 个' + (f'，失败 {bad} 个' if bad else '')
            rec['finished'] = time.time()
            changed = True
        if changed:
            _write(file, rec)


def last_message(day, within=3600):
    """Most recent finished re-export summary for the date, or '' when none."""
    best = None
    for _f, rec in _records():
        if rec.get('status') == 'DONE' and rec.get('day') == day and time.time() - float(rec.get('finished') or 0) < within:
            if best is None or rec.get('finished', 0) > best.get('finished', 0):
                best = rec
    if not best:
        return ''
    fails = [e['message'] for e in best['entries'] if e['status'] == 'FAILED' and e.get('message')]
    return best['message'] + (' · ' + fails[0] if fails else '')

"""Durable generation receipts and the download -> review -> edit handoff."""
import json
import time
from pathlib import Path
from app.core.database import connect
from app.core import repository as repo
from app.services import download_organizer
from app.services import runtime_log
from app.services import selected_resubmission

EVENTS = {'generation_task_failed', 'generation_task_status', 'video_download_started', 'video_download_completed',
          'video_download_failed'}

def _row_get(row, key, default=None):
    """sqlite3.Row/dict compatible safe accessor for mixed-version user databases."""
    try:
        if row is None:
            return default
        if hasattr(row, 'keys') and key not in row.keys():
            return default
        value = row[key]
        return default if value is None else value
    except (KeyError, IndexError, TypeError):
        return default

def _mark_dispatch_with_connection(con, segment_id, command_id, round_no, status, error=''):
    """Update dispatch inside the caller transaction; avoids nested SQLite writers."""
    import time as _time
    stage={'planned':'QUEUED','queued':'QUEUED','submitted':'SUBMITTED','downloading':'DOWNLOADING','detected':'QC_PENDING','failed':'FAILED'}.get(str(status),str(status).upper())
    con.execute("""UPDATE flow_dispatches SET status=?,error=?,stage=?,last_update_at=?,
                submitted_at=CASE WHEN ?='submitted' THEN CURRENT_TIMESTAMP ELSE submitted_at END
                WHERE segment_id=? AND command_id=? AND round_no=?""",
                (status,error or '',stage,_time.time(),status,int(segment_id),str(command_id),int(round_no or 1)))

def register_jobs(jobs):
    with connect() as con:
        for job in jobs:
            if not job.get('dispatch_tasks') or not job.get('command_id'):
                continue
            for task in job.get('tasks', []):
                sid = int(task['segment_id'])
                if selected_resubmission.obsolete(con,sid,job['command_id']):continue
                con.execute("""UPDATE flow_segments SET generation_command=?, flow_status='已准备',
                    flow_error='', flow_channel_key=? WHERE id=? AND generation_command<>?""",
                    (job['command_id'], str(job.get('channel_key') or ''), sid, job['command_id']))
                con.execute('DELETE FROM flow_redo WHERE segment_id=?', (sid,))


def managed_download_path(path):
    """Only configured download roots can be moved or removed by receipts."""
    try:
        path = Path(path).expanduser().resolve()
        roots = [Path.home() / 'Downloads']
        for key in ('flow_channel_download_root', 'flow_download_root'):
            value = repo.get_setting(key, '').strip()
            if value: roots.append(Path(value).expanduser())
        return any(path.is_relative_to(root.resolve()) and path != root.resolve() for root in roots)
    except (OSError, ValueError):
        return False


def _discard_obsolete_download_path(con, path_value, command_id, segment_id=0, exact_receipt=False):
    """Best-effort cleanup for a late file from an explicitly invalidated command.

    Never delete a file that is currently referenced or whose filename is awaited by
    another active dispatch; in ambiguous cases the receipt is ignored but the file is
    left untouched for safety.
    """
    cmd=str(command_id or '').strip()
    if not cmd or not (selected_resubmission.obsolete(con,segment_id,cmd) or con.execute("SELECT 1 FROM flow_obsolete_commands WHERE command_id=?",(cmd,)).fetchone()):
        return False
    try:
        path=Path(str(path_value or '')).expanduser()
        if not path.is_absolute() or not path.is_file() or not managed_download_path(path): return False
        text=str(path)
        cleanup_key=f'obsolete-cleanup:{cmd}:{segment_id}:{path.resolve()}'
        if con.execute('SELECT 1 FROM flow_receipts WHERE event_id=?',(cleanup_key,)).fetchone():return True
        if con.execute("SELECT 1 FROM flow_segments WHERE flow_output_path=? LIMIT 1",(text,)).fetchone(): return False
        if con.execute("SELECT 1 FROM flow_outputs WHERE output_path=? LIMIT 1",(text,)).fetchone(): return False
        if not exact_receipt and con.execute("SELECT 1 FROM flow_dispatches WHERE command_id<>? AND expected_filename=? AND status IN ('planned','queued','submitted','downloading') LIMIT 1",(cmd,path.name)).fetchone():
            return False
        if path.suffix.lower() not in ('.mp4','.mov','.m4v','.webm','.mkv','.avi'): return False
        path.unlink()
        con.execute('INSERT OR IGNORE INTO flow_receipts(event_id,payload) VALUES(?,?)',(cleanup_key,json.dumps({'deleted_obsolete_path':text})))
        runtime_log.log('obsolete_download_deleted',level='INFO',command_id=cmd,path=text)
        return True
    except Exception as exc:
        runtime_log.log('obsolete_download_delete_failed',level='WARNING',command_id=cmd,path=str(path_value or ''),error=str(exc))
        return False

def accept(event):
    """Commit before HTTP ACK. Duplicate and old-command receipts are harmless."""
    from app.services import camera_aux
    if camera_aux.accept(event):return True
    if event.get('type') not in EVENTS:
        return False
    sid = int(event.get('segment_id') or 0)
    cmd = str(event.get('command_id') or '')
    key = event.get('event_id') or json.dumps(event, sort_keys=True, ensure_ascii=False)
    pool_enabled = repo.get_setting('flow_channel_pool_enabled','1') == '1'
    resolved_path = resolve_download_path(event) if event.get('type') == 'video_download_completed' else ''
    with connect() as con:
        row = con.execute('''SELECT fs.*, v.host_id, v.seq video_seq, h.name host_name,
            r.name recipient_name, r.work_date
            FROM flow_segments fs JOIN videos v ON v.id=fs.video_id
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            WHERE fs.id=?''', (sid,)).fetchone()
        if selected_resubmission.obsolete(con,sid,cmd):
            if event.get('type')=='video_download_completed' and not resolved_path:
                con.execute("INSERT INTO flow_pending_downloads(event_id,payload,last_attempt) VALUES(?,?,?) ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload,last_attempt=excluded.last_attempt",(key,json.dumps(event,ensure_ascii=False),time.time()))
            else:
                con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?',(key,))
                if resolved_path:
                    reported=str(event.get('output_path') or event.get('local_path') or event.get('download_path') or '')
                    exact=bool(reported and Path(reported).is_absolute() and Path(reported).resolve()==Path(resolved_path).resolve())
                    _discard_obsolete_download_path(con,resolved_path,cmd,sid,exact_receipt=exact)
            return False
        # Upgrade only legacy completed records without a local file. Never revive a rejected attempt.
        if row and cmd and not row['generation_command'] and row['flow_status']=='已完成' and not row['flow_output_path'] and not con.execute('SELECT 1 FROM flow_redo WHERE segment_id=?',(sid,)).fetchone() and row['host_id']==int(event.get('host_id') or 0):
            con.execute('UPDATE flow_segments SET generation_command=? WHERE id=?',(cmd,sid))
            row=con.execute('''SELECT fs.*,v.host_id,v.seq video_seq,h.name host_name,r.name recipient_name,r.work_date FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id WHERE fs.id=?''',(sid,)).fetchone()
        if not row or not cmd or row['generation_command'] != cmd or row['host_id'] != int(event.get('host_id') or 0):
            con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?', (key,))
            if event.get('type') == 'video_download_completed' and resolved_path:
                _discard_obsolete_download_path(con, resolved_path, cmd, sid)
            runtime_log.log('download_receipt_ignored', level='WARNING', segment_id=sid, command_id=cmd, reason='missing task or stale command/host')
            return False
        if event.get('type') != 'video_download_completed' and con.execute('SELECT 1 FROM flow_receipts WHERE event_id=?', (key,)).fetchone():
            return False
        typ = event['type']
        if typ=='generation_task_failed': event=dict(event,state='failed'); typ='generation_task_status'
        if typ == 'video_download_completed':
            media_key = str(event.get('media_id') or event.get('download_id') or '')
            conflict=con.execute('SELECT segment_id FROM flow_outputs WHERE media_id=? AND segment_id<>? LIMIT 1',(media_key,sid)).fetchone() if media_key else None
            if not conflict and resolved_path:
                conflict=con.execute('SELECT segment_id FROM flow_outputs WHERE output_path=? AND segment_id<>? LIMIT 1',(str(Path(resolved_path).expanduser()),sid)).fetchone()
            if conflict:
                con.execute("UPDATE flow_segments SET flow_error='结果归属冲突：该视频已绑定其他片段，暂停进入质检' WHERE id=?",(sid,))
                runtime_log.log('result_identity_conflict',level='ERROR',segment_id=sid,other_segment=conflict[0],command_id=cmd)
                return False
            prior = con.execute('SELECT output_path FROM flow_outputs WHERE segment_id=? AND command_id=? AND media_id=?', (sid,cmd,media_key)).fetchone() if media_key else None
            if prior and Path(prior['output_path']).is_file():
                con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?', (key,))
                return False
            # Chrome may report completion before a usable absolute filesystem path is
            # available to the native app.  Do NOT fail the receipt in that case: the
            # lightweight folder watcher will bind the exact expected filename shortly.
            local = resolved_path
            path = Path(local).expanduser() if local else None
            readable = bool(path and path.is_absolute() and path.is_file())
            if readable:
                try:
                    readable = path.stat().st_size > 0
                except OSError:
                    readable = False
            if not readable:
                con.execute("INSERT INTO flow_pending_downloads(event_id,payload,last_attempt) VALUES(?,?,?) ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload,last_attempt=excluded.last_attempt",
                            (key,json.dumps(event,ensure_ascii=False),time.time()))
                try:
                    _mark_dispatch_with_connection(con, sid, cmd, int(event.get('round') or 1), 'downloading', '等待本地文件识别')
                except Exception:
                    pass
                runtime_log.log('plugin_download_completed_waiting_local_path', level='INFO', segment_id=sid,
                                command_id=cmd, channel=event.get('channel_key',''), reported_path=local)
            else:
                con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?', (key,))
                # Browser receipts and the folder watcher may use /var vs /private/var
                # aliases. Compare real paths before any QC/status write.
                existing = next((r for r in con.execute('SELECT id,output_path FROM flow_outputs WHERE segment_id=? AND command_id=?', (sid,cmd)) if r['output_path'] and Path(r['output_path']).expanduser().resolve()==path.resolve()), None)
                if existing:
                    return False
                pool_mode = pool_enabled and bool(event.get('channel_key'))
                if not pool_mode:
                    raw_channel = event.get('channel_id') or 0
                    try:
                        numeric_channel = int(raw_channel)
                    except (TypeError, ValueError):
                        numeric_channel = 0
                    if numeric_channel:
                        local = download_organizer.organize(str(path), dict(row), event)
                        path = Path(local)
                media = str(event.get('media_id') or event.get('download_id') or f"plugin:{event.get('channel_key','')}:{path.name}")
                if media and not media.startswith('local:') and not media.startswith('plugin:'):
                    con.execute("DELETE FROM flow_outputs WHERE segment_id=? AND command_id=? AND (media_id LIKE 'local:%' OR media_id LIKE 'plugin:%')", (sid, cmd))
                con.execute('INSERT INTO flow_outputs (segment_id,command_id,media_id,output_path,qc_status) VALUES (?,?,?,?,?) ON CONFLICT(segment_id,command_id,media_id) DO UPDATE SET output_path=excluded.output_path',
                            (sid,cmd,media,str(path),'待质检'))
                if _row_get(row, 'qc_status', '待质检') != '通过':
                    con.execute("UPDATE flow_segments SET flow_status='已完成', flow_output_path=?, flow_output_url='', qc_status='待质检', flow_error='', flow_completed_at=CURRENT_TIMESTAMP WHERE id=?",
                                (str(path),sid))
                try:
                    _mark_dispatch_with_connection(con, sid, cmd, int(event.get('round') or 1), 'detected', '')
                except Exception:
                    pass
                runtime_log.log('plugin_download_completed_entered_qc', segment_id=sid, command_id=cmd,
                                channel=event.get('channel_key',''), path=str(path), size=path.stat().st_size)
        elif row['flow_status'] != '已完成':
            dispatch_round = int(event.get('round') or 1)
            if typ == 'video_download_started':
                # Do not expose a transient “下载中” state in Studio.  Keep the previous
                # generation state until Chrome confirms the file is completely written.
                status, error = row['flow_status'], ''
                try: _mark_dispatch_with_connection(con, sid, cmd, dispatch_round, 'downloading', '')
                except Exception: pass
            elif typ == 'video_download_failed':
                status, error = '下载失败', str(event.get('error') or event.get('message') or 'Flow 未返回下载失败原因')
                try: _mark_dispatch_with_connection(con, sid, cmd, dispatch_round, 'failed', error)
                except Exception: pass
            else:
                state = str(event.get('state') or '')
                # V0.13.5.85: only a *confirmed* Flow acceptance may become SUBMITTED.
                # Older builds marked the dispatch submitted as soon as the plugin emitted
                # `running`/`preparing` (before the Generate click/network acceptance).  The
                # scheduler then released the channel slot and replaced the active Bridge job,
                # leaving Studio rows as “已提交” even though Flow never started anything.
                status = {'success':'生成中', 'running':'已准备', 'uncertain':'已准备', 'preparing':'已准备', 'failed':'失败'}.get(state,'已准备')
                error = '\n'.join(dict.fromkeys(str(event.get(k)) for k in ('error','message') if event.get(k))) if status == '失败' else ''
                if status == '失败' and not error:error='Flow 未返回具体失败原因'
                dispatch_status = 'submitted' if state == 'success' else ('failed' if state == 'failed' else 'queued')
                try:
                    _mark_dispatch_with_connection(con, sid, cmd, dispatch_round, dispatch_status, error)
                except Exception:
                    pass
                # A delayed running receipt must not undo download progress.
                if row['flow_status'] in ('下载中','下载失败') and status != '失败':
                    status = row['flow_status']
            if typ=='generation_task_status' and event.get('state') in ('running','success') and row['flow_status'] in ('待生成','已准备'):
                con.execute('UPDATE flow_segments SET flow_attempts=flow_attempts+1,flow_submitted_at=CURRENT_TIMESTAMP WHERE id=?',(sid,))
            con.execute('UPDATE flow_segments SET flow_status=?,flow_error=? WHERE id=?', (status,error,sid))
            runtime_log.log('task_runtime_state', segment_id=sid, command_id=cmd, channel=event.get('channel_key',''), round=dispatch_round,
                            event_type=typ, state=event.get('state',''), flow_status=status, error=error)
        if typ=='generation_task_status' and event.get('state')=='failed' and row['flow_status']!='已完成':
            # Flow "unusual activity" rejection just reported for this channel: not a task fault, do not count.
            try:
                from app.services import pause_control
                _risk=pause_control.recent_unusual(str(event.get('channel_key') or row['flow_channel_key'] or ''))
            except Exception:
                _risk=False
            inserted=0 if _risk else con.execute('INSERT OR IGNORE INTO flow_failure_attempts VALUES(?,?,?,?)',
                (sid,cmd,str(event.get('message') or event.get('error') or '生成失败'),time.time())).rowcount
            if inserted:
                con.execute('INSERT OR IGNORE INTO flow_recovery(segment_id) VALUES(?)',(sid,))
                con.execute('UPDATE flow_recovery SET failures=failures+1,blocked=CASE WHEN failures+1>=3 THEN 1 ELSE 0 END,notified=CASE WHEN failures<3 AND failures+1>=3 THEN 0 ELSE notified END,queued=0,preferred_channel=? WHERE segment_id=?',(str(event.get('channel_key') or row['flow_channel_key'] or ''),sid))
        elif typ=='video_download_completed' and readable:
            con.execute('DELETE FROM flow_recovery WHERE segment_id=?',(sid,))
        con.execute('INSERT OR IGNORE INTO flow_receipts(event_id,payload) VALUES (?,?)', (key,json.dumps(event,ensure_ascii=False)))
    return readable if typ == 'video_download_completed' else True

def review(ids, status, note=''):
    with connect() as con:
        return _review(con, ids, status, note)

def _review(con, ids, status, note=''):
    if status not in ('通过','退回','画面处理'):
        raise ValueError('无效质检状态')
    videos=set()
    for sid in ids:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(int(sid),)).fetchone()
        if not row or row['flow_status']!='已完成' or not Path(row['flow_output_path']).is_file():
            raise ValueError('只能审核已下载、可读取的视频片段')
        videos.add(row['video_id'])
        con.execute('UPDATE flow_outputs SET qc_status=? WHERE segment_id=? AND output_path=?',
                    (status,sid,row['flow_output_path']))
        con.execute('UPDATE flow_segments SET qc_status=?,qc_note=?,qc_reject_reason=?,qc_decided_at=CURRENT_TIMESTAMP WHERE id=?',(status,note,note if status=='退回' else '',sid))
        meta=con.execute('''SELECT r.name recipient_name,h.name host_name,v.performance_mode,fs.prompt FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id WHERE fs.id=?''',(int(sid),)).fetchone()
        if meta:
            con.execute('''INSERT INTO qc_decisions(segment_id,decision,reason,recipient_name,host_name,performance_mode,prompt_snapshot)
                           VALUES(?,?,?,?,?,?,?)''',(int(sid),status,note if status=='退回' else '',meta['recipient_name'] or '',meta['host_name'] or '',meta['performance_mode'] or 'TALKING',meta['prompt'] or ''))
        if status=='退回':
            con.execute("""UPDATE flow_segments SET generation_command='',flow_status='待生成',
                flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',flow_retry_count=flow_retry_count+1 WHERE id=?""",(sid,))
            con.execute('INSERT OR IGNORE INTO flow_redo(segment_id) VALUES (?)',(sid,))
    for vid in videos:
        reconcile_video_qc(vid, con)
    return len(ids)

def redo_ids(*, work_date=None):
    if work_date is None:
        with connect() as con:
            return {r[0] for r in con.execute('SELECT segment_id FROM flow_redo')}
    from app.core.work_dates import read_connection
    with read_connection(work_date) as con:
        return {r[0] for r in con.execute('SELECT segment_id FROM flow_redo')}


def review_outputs(output_ids, status, note=''):
    # Resolve and bind the exact previewed revision before accepting the review.
    video_ids = set()
    with connect() as con:
        resolved = []
        for oid in output_ids:
            row = con.execute("""SELECT fo.*,fs.generation_command,fs.video_id FROM flow_outputs fo
                JOIN flow_segments fs ON fs.id=fo.segment_id WHERE fo.id=?""",(int(oid),)).fetchone()
            if not row or row['command_id'] != row['generation_command'] or not Path(row['output_path']).is_file():
                raise ValueError('该结果已过期或文件不可读取，请刷新质检列表')
            resolved.append(row)
            video_ids.add(int(row['video_id']))
        # Selecting alternative renders of one segment in the same action is ambiguous.
        if len({r['segment_id'] for r in resolved}) != len(resolved):
            raise ValueError('同一片段的多个版本请逐个审核')
        for row in resolved:
            con.execute('UPDATE flow_segments SET flow_output_path=? WHERE id=?',
                        (row['output_path'],row['segment_id']))
        count = _review(con, [r['segment_id'] for r in resolved],status,note)
    # V0.13.5: stop at the editing-ready gate. DaVinci integration is intentionally deferred.
    return count


def accept_channel_file(dispatch, path):
    """Authoritative local-folder handoff: exact expected filename -> segment -> QC."""
    p=Path(path).expanduser()
    if not p.is_file() or p.stat().st_size<=0:
        raise ValueError('通道下载文件不可读取：'+str(path))
    d=dict(dispatch); sid=int(d['segment_id']); cmd=str(d['command_id']); round_no=int(d.get('round_no') or 1)
    with connect() as con:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if selected_resubmission.obsolete(con,sid,cmd):
            _discard_obsolete_download_path(con,str(p),cmd,sid)
            return False
        if not row or str(row['generation_command'] or '')!=cmd:
            repo.update_dispatch(int(d['id']),status='stale',download_path=str(p),error='任务命令已更新',detected=True)
            runtime_log.log('channel_file_stale',level='WARNING',segment_id=sid,command_id=cmd,path=str(p))
            return False
        media=f"local:{d['channel_key']}:{p.name}"
        if not con.execute('SELECT 1 FROM flow_outputs WHERE segment_id=? AND command_id=? AND output_path=?', (sid,cmd,str(p))).fetchone():
            con.execute("INSERT OR IGNORE INTO flow_outputs(segment_id,command_id,media_id,output_path,qc_status) VALUES(?,?,?,?, '待质检')",
                        (sid,cmd,media,str(p)))
        if row['qc_status']!='通过':
            con.execute("UPDATE flow_segments SET flow_status='已完成',flow_output_path=?,flow_output_url='',qc_status='待质检',flow_error='',flow_completed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (str(p),sid))
    repo.update_dispatch(int(d['id']),status='detected',download_path=str(p),error='',detected=True)
    runtime_log.log('channel_file_detected',segment_id=sid,channel=d['channel_key'],command_id=cmd,
                    round=round_no,task_name=d['task_name'],path=str(p),size=p.stat().st_size)
    return True


def resolve_download_path(event):
    """Use Chrome's absolute path, or exact relative filename within known roots."""
    from urllib.parse import urlparse, unquote
    reported = str(event.get('output_path') or event.get('local_path') or event.get('download_path') or '').strip()
    if reported.startswith('file://'):
        reported = unquote(urlparse(reported).path)
    roots = [Path.home()/'Downloads']
    for key in ('flow_channel_download_root','flow_download_root'):
        value = repo.get_setting(key,'').strip()
        if value:
            roots.append(Path(value).expanduser())
    candidates = []
    if reported:
        p = Path(reported).expanduser()
        if p.is_absolute(): candidates.append(p)
    relative = str(event.get('filename') or '').strip()
    for value in (relative, reported if reported and not Path(reported).is_absolute() else ''):
        p = Path(value)
        if not value or p.is_absolute() or '..' in p.parts:
            continue
        for root in roots:
            candidates.append(root/p)
            if p.parts and p.parts[0] == 'FlowStudio_Channels':
                candidates.append(root/Path(*p.parts[1:]))
    for p in candidates:
        try:
            if managed_download_path(p) and p.suffix.lower() in {'.mp4','.mov','.m4v','.webm'} and p.is_file() and p.stat().st_size > 0:
                return str(p.resolve())
        except OSError:
            continue
    return ''


def recover_pending_downloads(limit=100):
    """Retry persisted receipts in the background, including across app restarts."""
    with connect() as con:
        events = con.execute('SELECT event_id,payload FROM flow_pending_downloads ORDER BY last_attempt,event_id LIMIT ?', (limit,)).fetchall()
    changed = False
    for row in events:
        try:
            event = json.loads(row['payload'])
            event['event_id'] = row['event_id']
            changed = accept(event) or changed
        except Exception as exc:
            with connect() as con:
                con.execute('UPDATE flow_pending_downloads SET last_attempt=? WHERE event_id=?', (time.time(),row['event_id']))
            runtime_log.log('download_recovery_failed', level='WARNING', error=str(exc), event_id=row['event_id'])
    return changed


def get_active_segments(con, video_id):
    """
    获取当前视频真正有效的片段。
    必须排除撤销、作废、历史重试和替换图片前的过时片段。
    这里使用 _current_edit_segments(con, [video_id]) 作为基础，再做严格校验。
    """
    from app.core.repository import _current_edit_segments
    # _current_edit_segments already filters by generation_command matching flow_output
    # and handles 'current_passed'.
    # We will refine it to strictly return active segments.
    rows = _current_edit_segments(con, [video_id])
    
    # In Flow Studio, a segment is only truly active if it has not been marked as '已撤销' or '已作废'
    active_rows = []
    for row in rows:
        st = str(row.get('status') or '')
        qs = str(row.get('qc_status') or '待质检')
        # We assume _current_edit_segments already brings the most recent row per segment.
        # But we must exclude invalid ones.
        if st in ('已撤销', '已作废'):
            continue
        active_rows.append(row)
    return active_rows

def ensure_auto_edit_task(con, video_id):
    """
    如果不存在处理中或已完成的任务，则创建 AUTO_EDIT_PENDING (待剪辑)
    """
    # Check for pending/processing/done tasks in editing_history
    existing = con.execute('''
        SELECT id FROM editing_history
        WHERE video_id=? AND status IN ('待处理', '处理中', '已完成', 'AUTO_EDIT_PENDING', 'AUTO_EDIT_PROCESSING', 'AUTO_EDIT_DONE')
    ''', (video_id,)).fetchone()
    
    if existing:
        from app.services.runtime_log import log
        log('QC_AUTO_EDIT', task='ALREADY_EXISTS', video_id=video_id)
        return
        
    con.execute('''
        INSERT INTO editing_history(video_id, status)
        VALUES (?, '待处理')
    ''', (video_id,))
    from app.services.runtime_log import log
    log('QC_AUTO_EDIT', task='CREATED', video_id=video_id)

def reconcile_video_qc(video_id, con_passed=None):
    """
    统一下游流转判断：计算当前实际有效片段与应有数量，如果全部PASS，进入自动剪辑。
    """
    from app.core.database import connect
    from app.services.runtime_log import log
    
    def _do_reconcile(con):
        # Get expected segments count for the video
        # A video's expected segments is the total number of flow_segments 
        # belonging to the current version. Usually we can check the total count of distinct seg_seq.
        # But to be precise, let's get the max seg_seq or count distinct.
        v_meta = con.execute('''
            SELECT v.edit_status, v.seq, h.name as anchor, r.name as recipient
            FROM videos v
            JOIN hosts h ON v.host_id = h.id
            JOIN recipients r ON h.recipient_id = r.id
            WHERE v.id=?
        ''', (video_id,)).fetchone()
        
        if not v_meta: return
        
        # In Flow Studio, a video can have multiple flow_segments due to rework, but they share the same seg_seq.
        # Expected segments = count of distinct seg_seq for this video_id where it wasn't cancelled completely.
        # Wait, the exact number of segments for a video is just the count of distinct seg_seq.
        expected_count = con.execute('''
            SELECT COUNT(DISTINCT seg_seq) FROM flow_segments WHERE video_id=? AND status NOT IN ('已撤销', '已作废')
              AND NOT (seg_seq>=1000 AND foreign_text LIKE '[LEGACY_AUX]%')
        ''', (video_id,)).fetchone()[0]
        
        active_segments = get_active_segments(con, video_id)
        
        # Consolidate by seg_seq to avoid duplicates from old retries.
        active_dict = {}
        for s in active_segments:
            seq = s['seg_seq']
            if seq not in active_dict or s['id'] > active_dict[seq]['id']:
                active_dict[seq] = s
        
        active_count = len(active_dict)
        
        passed_count = sum(1 for s in active_dict.values() if s.get('material_valid') or str(s.get('qc_status')) == '通过')
        pending_count = sum(1 for s in active_dict.values() if str(s.get('qc_status')) == '待质检')
        rework_count = sum(1 for s in active_dict.values() if str(s.get('qc_status')) == '退回')
        
        log_info = {
            'video_id': video_id,
            'recipient': v_meta['recipient'],
            'anchor': v_meta['anchor'],
            'video_no': f"{v_meta['seq']:02d}",
            'expected_segments': expected_count,
            'active_segments': active_count,
            'passed_segments': passed_count,
            'pending_segments': pending_count,
            'rework_segments': rework_count,
            'video_status_before': v_meta['edit_status']
        }

        if active_count == expected_count and passed_count == expected_count and expected_count > 0:
            # We are done!
            if v_meta['edit_status'] in ('待准备', '等待片段', '素材待齐', '等待剪辑', '需要画面处理', '待剪辑'):
                con.execute("UPDATE videos SET edit_status='待剪辑' WHERE id=? AND edit_status IN ('待准备', '等待片段', '素材待齐', '等待剪辑', '需要画面处理')", (video_id,))
                ensure_auto_edit_task(con, video_id)
            log('QC_COMPLETE_CHECK', **log_info, video_status_after='待剪辑', result='QC_DONE')
        else:
            reason = 'ACTIVE_SEGMENT_COUNT_MISMATCH' if active_count != expected_count else 'SEGMENT_NOT_PASSED'
            # If it was marked as QC_DONE but now it's not, revert it to '素材待齐'
            if v_meta['edit_status'] == '待剪辑':
                con.execute("UPDATE videos SET edit_status='素材待齐' WHERE id=?", (video_id,))
            log('QC_NOT_COMPLETE', **log_info, reason=reason)
            
    if con_passed:
        _do_reconcile(con_passed)
    else:
        with connect() as con:
            _do_reconcile(con)

def run_background_qc_reconcile():
    """
    后台兜底检查，每 15-30s 执行，仅扫描 QC 队列中的任务
    """
    from app.core.database import connect
    with connect() as con:
        # Find all videos currently in some active QC/rework phase but not yet 待剪辑 or 已剪辑
        videos = con.execute('''
            SELECT id FROM videos 
            WHERE edit_status NOT IN ('待剪辑', '处理中', '已完成', '已发布')
            AND EXISTS (SELECT 1 FROM flow_segments WHERE video_id=videos.id AND qc_status IN ('待质检', '退回', '通过'))
        ''').fetchall()
        
    for v in videos:
        reconcile_video_qc(v['id'])


"""Explicit retries and durable bounded failure recovery. No historical receipts reused."""
from app.core import repository as repo
from app.core.database import connect


def queue_failures():
    # Confirmed generation failures are manual-only. Never auto-resubmit them.
    # Clean only legacy uncertainty text written by older builds; do not touch
    # real generation/download failures.
    annotate_stalled()
    with connect() as con:
        con.execute("""UPDATE flow_segments SET flow_error=''
            WHERE flow_status IN ('已准备','已提交','生成中') AND (
                flow_error LIKE '%MAIN_ENGINE_TIMEOUT%' OR
                flow_error LIKE 'SUBMISSION_UNCONFIRMED%' OR
                flow_error LIKE '%提交回执超过3分钟未确认%' OR
                flow_error LIKE '%生成结果超过15分钟未确认%')""")
    return 0


def reset_task(sid,bridge,prompt=None,preferred_channel=None,allow_running_prompt=False):
    if prompt is not None and not prompt.strip():raise ValueError('提示词不能为空')
    if preferred_channel is not None and preferred_channel!='':
        channels={str(c['channel_key']) for c in repo.list_channel_pool(enabled_only=True) if c['collection_url']}
        if preferred_channel not in channels:raise ValueError('所选通道已移除或未设置链接')
    # A running batch is reset as a unit only when it contains this sole pending task.
    with connect() as con:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not row or row['flow_status'] in ('已完成','已放弃'):raise ValueError('任务已完成、已放弃或不存在，不能重复生成')
        if prompt is not None and not allow_running_prompt and row['flow_status'] not in ('待生成','失败','下载失败'):
            raise ValueError('任务已开始运行，请等待本次运行结束再修改提示词')
        cmd=str(row['generation_command'] or '');channel=str(row['flow_channel_key'] or '')
        others=con.execute("SELECT 1 FROM flow_segments WHERE generation_command=? AND id<>? AND flow_status NOT IN ('已完成','失败','下载失败','已放弃') LIMIT 1",(cmd,sid)).fetchone() if cmd else None
    if cmd and bridge is not None:
        if others:bridge.remove_task_from_command(cmd,sid)
        else:bridge.cancel_host_commands([cmd])
    target_channel=channel if preferred_channel is None else str(preferred_channel)
    with connect() as con:
        current=con.execute('SELECT generation_command,flow_status FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not current or str(current[0] or '')!=cmd or current[1] in ('已完成','已放弃'):raise ValueError('任务状态已改变，请刷新后再试')
        if cmd:
            con.execute('INSERT OR IGNORE INTO flow_obsolete_segments(segment_id,command_id) VALUES(?,?)',(int(sid),cmd))
        con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED' WHERE command_id=? AND segment_id=?",(cmd,sid))
        con.execute("UPDATE flow_dispatches SET error='人工重置已接管' WHERE segment_id=? AND status='cancelled' AND error LIKE '自动恢复:%'",(sid,))
        con.execute("UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_error='',flow_channel_key=?,flow_retry_count=flow_retry_count+1 WHERE id=?",(target_channel,sid))
        if prompt is not None:
            if not prompt.strip():raise ValueError('提示词不能为空')
            con.execute('UPDATE flow_segments SET prompt=? WHERE id=?',(prompt.strip(),sid))
        con.execute('INSERT OR REPLACE INTO flow_recovery(segment_id,failures,blocked,notified,queued,preferred_channel) VALUES(?,0,0,0,0,?)',(sid,target_channel))
        _route_retry(con,sid)
        if not others and channel:
            con.execute("UPDATE flow_channel_pool SET task_command_id='',quarantine_until=0,health_status='healthy',upload_state='idle' WHERE channel_key=? AND (task_command_id=? OR task_command_id='')",(channel,cmd))
    return target_channel


def reset_tasks_batch(candidates, bridge, day=None, allow_running_prompt=False):
    """Batch-reset failed, upload-skipped, or stuck running tasks in a single transaction."""
    import json
    from app.core import work_dates
    items = []
    seen = set()
    for item in (candidates or []):
        sid = int(item[0])
        if sid in seen:
            continue
        seen.add(sid)
        pref = item[1] if len(item) > 1 else None
        prompt = item[2] if len(item) > 2 else None
        items.append((sid, pref, prompt))
    if not items:
        return {'ok': [], 'errors': [], 'reset_running': 0, 'released_channels': []}

    canon_day = work_dates.canonical(day) if day else None
    enabled_channels = {str(c['channel_key']) for c in repo.list_channel_pool(enabled_only=True) if c['collection_url']}

    planned = []
    errors = []
    with connect() as con:
        for sid, pref, prompt in items:
            if prompt is not None and not str(prompt).strip():
                errors.append(f'{sid}: 提示词不能为空')
                continue
            if pref is not None and pref != '' and str(pref) not in enabled_channels:
                errors.append(f'{sid}: 所选通道已移除或未设置链接')
                continue
            row = con.execute('SELECT * FROM flow_segments WHERE id=?', (sid,)).fetchone()
            if not row:
                errors.append(f'{sid}: 任务不存在')
                continue
            if canon_day and work_dates.video_work_date(con, row['video_id']) != canon_day:
                errors.append(f'{sid}: 任务不属于当前工作日期')
                continue
            if row['flow_status'] in ('已完成', '已放弃'):
                errors.append(f'{sid}: 任务{row["flow_status"]}，已跳过')
                continue
            if prompt is not None and not allow_running_prompt and row['flow_status'] not in ('待生成', '失败', '下载失败'):
                errors.append(f'{sid}: 运行中任务未开启改词重置')
                continue
            planned.append((
                sid,
                pref,
                prompt,
                str(row['generation_command'] or ''),
                str(row['flow_channel_key'] or ''),
                str(row['flow_status'] or ''),
            ))

        if not planned:
            return {'ok': [], 'errors': errors, 'reset_running': 0, 'released_channels': []}

        planned_sids = {p[0] for p in planned}
        cmds = {p[3] for p in planned if p[3]}
        cmd_has_outside_active = {}
        for cmd in cmds:
            rem = con.execute(
                "SELECT id FROM flow_segments WHERE generation_command=? AND flow_status NOT IN ('已完成','失败','下载失败','已放弃')",
                (cmd,),
            ).fetchall()
            cmd_has_outside_active[cmd] = any(int(r[0]) not in planned_sids for r in rem)

    full_cancel_cmds = [cmd for cmd, has_other in cmd_has_outside_active.items() if not has_other]
    if bridge is not None:
        if full_cancel_cmds:
            bridge.cancel_host_commands(full_cancel_cmds)
        for sid, _pref, _prompt, cmd, _ch, _st in planned:
            if cmd and cmd_has_outside_active.get(cmd):
                bridge.remove_task_from_command(cmd, sid)

    ok = []
    reset_running = 0
    released_channels = set()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for sid, pref, prompt, cmd, orig_ch, orig_st in planned:
            cur = con.execute('SELECT generation_command, flow_status FROM flow_segments WHERE id=?', (sid,)).fetchone()
            if not cur or str(cur[0] or '') != cmd or cur[1] in ('已完成', '已放弃'):
                errors.append(f'{sid}: 任务状态刚刚变化，已跳过')
                continue
            target_ch = orig_ch if pref is None else str(pref)
            if cmd:
                con.execute('INSERT OR IGNORE INTO flow_obsolete_segments(segment_id,command_id) VALUES(?,?)', (sid, cmd))
            con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED' WHERE command_id=? AND segment_id=?", (cmd, sid))
            con.execute("UPDATE flow_dispatches SET error='人工重置已接管' WHERE segment_id=? AND status='cancelled' AND error LIKE '自动恢复:%'", (sid,))
            con.execute(
                "UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_error='',flow_channel_key=?,flow_retry_count=flow_retry_count+1 WHERE id=?",
                (target_ch, sid),
            )
            if prompt is not None:
                con.execute('UPDATE flow_segments SET prompt=? WHERE id=?', (str(prompt).strip(), sid))
            con.execute(
                'INSERT OR REPLACE INTO flow_recovery(segment_id,failures,blocked,notified,queued,preferred_channel) VALUES(?,0,0,0,0,?)',
                (sid, target_ch),
            )
            _route_retry(con, sid)
            if orig_st in ('已准备', '已提交', '生成中', '下载中'):
                reset_running += 1
            if orig_ch and (not cmd or not cmd_has_outside_active.get(cmd)):
                con.execute(
                    "UPDATE flow_channel_pool SET task_command_id='',quarantine_until=0,health_status='healthy',upload_state='idle' "
                    "WHERE channel_key=? AND (task_command_id=? OR task_command_id='')",
                    (orig_ch, cmd),
                )
                released_channels.add(orig_ch)
            ok.append(sid)

        if ok and con.execute("SELECT 1 FROM sqlite_master WHERE name='flow_pending_downloads'").fetchone():
            ok_set = set(ok)
            for p_row in con.execute('SELECT event_id, payload FROM flow_pending_downloads').fetchall():
                try:
                    payload = json.loads(p_row['payload'] or '{}')
                    if int(payload.get('segment_id') or 0) in ok_set:
                        con.execute('DELETE FROM flow_pending_downloads WHERE event_id=?', (p_row['event_id'],))
                except Exception:
                    continue

    return {
        'ok': ok,
        'errors': errors,
        'reset_running': reset_running,
        'released_channels': sorted(released_channels),
    }


def preferred_channels(tasks):
    with connect() as con:
        return {r['segment_id']:r['preferred_channel'] for r in con.execute('SELECT * FROM flow_recovery WHERE blocked=0') if r['segment_id'] in {t['segment_id'] for t in tasks}}


def recover_unsubmitted(command):
    if not command:return
    with connect() as con:
        rows=con.execute("""SELECT fs.id,fs.flow_channel_key FROM flow_segments fs WHERE fs.generation_command=?
            AND fs.flow_status='已准备' AND NOT EXISTS(SELECT 1 FROM flow_dispatches d WHERE d.segment_id=fs.id AND d.command_id=? AND d.status IN ('submitted','downloading','detected'))""",(command,command)).fetchall()
        for sid,key in rows:
            con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED' WHERE segment_id=? AND command_id=?",(sid,command))
            con.execute("UPDATE flow_segments SET generation_command='',flow_status='待生成' WHERE id=?",(sid,))
            _route_retry(con,sid)
            con.execute('INSERT OR IGNORE INTO flow_recovery(segment_id,preferred_channel) VALUES(?,?)',(sid,''))


_last_watchdog = 0.0
def annotate_stalled():
    import time
    from app.services import runtime_log
    global _last_watchdog
    now=time.monotonic()
    if now-_last_watchdog<30:return
    _last_watchdog=now
    # Long waits are diagnostics only; timeout alone is not a true Flow failure.
    with connect() as con:
        submitted=con.execute("""SELECT COUNT(*) FROM flow_segments WHERE flow_status='已提交' AND generation_command<>''
            AND flow_submitted_at < datetime('now','-3 minutes')""").fetchone()[0]
        generating=con.execute("""SELECT COUNT(*) FROM flow_segments WHERE flow_status='生成中' AND generation_command<>''
            AND flow_submitted_at < datetime('now','-15 minutes')""").fetchone()[0]
    if submitted or generating:
        runtime_log.log('flow_uncertain_watchdog',submitted_waiting=int(submitted or 0),generation_waiting=int(generating or 0),
                        message='仅记录等待状态；未凭超时判定失败，也不会自动重复生成')


def _route_retry(con,sid):
    row=con.execute('SELECT qc_status FROM flow_segments WHERE id=?',(sid,)).fetchone()
    if row and row[0]=='退回':
        con.execute('INSERT OR IGNORE INTO flow_redo(segment_id) VALUES(?)',(sid,))
    else:
        con.execute('DELETE FROM flow_redo WHERE segment_id=?',(sid,))

def restore_normal_tasks(*, work_date=None):
    """Only unassigned waiting tasks without a QC rejection return to normal scheduling.

    When a Flow workspace date is supplied, only that date is touched; historical redo rows
    remain isolated and cannot be changed merely because today's automatic dispatcher ticks.
    """
    with connect() as con:
        if work_date is None:
            ids=[r[0] for r in con.execute("""SELECT fs.id FROM flow_segments fs JOIN flow_redo r ON r.segment_id=fs.id
                WHERE fs.flow_status='待生成' AND COALESCE(fs.generation_command,'')=''
                AND COALESCE(fs.qc_status,'')<>'退回'""").fetchall()]
        else:
            ids=[r[0] for r in con.execute("""SELECT fs.id FROM flow_segments fs
                JOIN flow_redo r ON r.segment_id=fs.id
                JOIN videos v ON v.id=fs.video_id
                JOIN hosts h ON h.id=v.host_id
                JOIN recipients rc ON rc.id=h.recipient_id
                WHERE rc.work_date=?
                  AND fs.flow_status='待生成' AND COALESCE(fs.generation_command,'')=''
                  AND COALESCE(fs.qc_status,'')<>'退回'""", (str(work_date),)).fetchall()]
        if not ids:
            return 0
        for sid in ids:
            con.execute('DELETE FROM flow_redo WHERE segment_id=?',(sid,))
    return len(ids)


def abandon_task(sid,bridge,day,reason='用户放弃任务'):
    """Explicitly retire one task; retain files and reject old command receipts."""
    from app.core import work_dates
    with connect() as con:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not row or work_dates.video_work_date(con,row['video_id'])!=day:raise ValueError('任务日期已改变，请刷新')
        if row['flow_status']=='已完成':raise ValueError('该任务已完成，不能在这里放弃')
        command=row['generation_command'] or '';channel=row['flow_channel_key'] or ''
    if command and bridge is not None:bridge.remove_task_from_command(command,sid)
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        current=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not current or current['generation_command']!=row['generation_command'] or current['flow_status']=='已完成':
            raise ValueError('任务状态刚刚变化，请刷新后再试')
        con.execute('CREATE TABLE IF NOT EXISTS flow_task_actions(id INTEGER PRIMARY KEY,segment_id INTEGER,action TEXT,detail TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        con.execute("INSERT INTO flow_task_actions(segment_id,action,detail) VALUES(?,'放弃',?)",(sid,current['flow_error'] or reason))
        con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error=? WHERE segment_id=? AND command_id=?",(reason,sid,command))
        con.execute("UPDATE flow_segments SET flow_status='已放弃',prompt_review_status='已放弃',generation_command='',flow_error=? WHERE id=?",(reason+'；原错误：'+(current['flow_error'] or '未提供'),sid))
        con.execute('DELETE FROM flow_redo WHERE segment_id=?',(sid,))
        con.execute('INSERT OR REPLACE INTO flow_recovery(segment_id,failures,blocked,notified,queued,preferred_channel) VALUES(?,0,1,1,0,?)',(sid,channel))
        con.execute("UPDATE videos SET edit_status='已放弃' WHERE id=? AND COALESCE(edit_status,'') NOT IN ('已导出','已完成')",(int(current['video_id']),))
        if command and not con.execute("SELECT 1 FROM flow_segments WHERE generation_command=? AND flow_status NOT IN ('已完成','失败','下载失败','已放弃')",(command,)).fetchone():
            con.execute("UPDATE flow_channel_pool SET task_command_id='' WHERE channel_key=? AND task_command_id=?",(channel,command))
    return True


def video_abandon_scope(sid):
    """Describe the whole-video abandon: (video_id, seq, host, [segment ids to abandon], completed_count)."""
    with connect() as con:
        row=con.execute('SELECT fs.video_id,v.seq,h.name FROM flow_segments fs JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id WHERE fs.id=?',(sid,)).fetchone()
        if not row:raise ValueError('任务不存在，请刷新')
        rows=con.execute("SELECT id,flow_status FROM flow_segments WHERE video_id=? AND seg_seq<1000 AND status NOT IN ('已撤销','已作废')",(row['video_id'],)).fetchall()
    ids=[int(r['id']) for r in rows if r['flow_status'] not in ('已完成','已放弃')]
    if int(sid) not in ids:ids.insert(0,int(sid))
    done=sum(1 for r in rows if r['flow_status']=='已完成')
    return int(row['video_id']),int(row['seq']),str(row['name']),ids,done


def abandon_video(sid,bridge,day):
    """Abandoning one segment discards the whole complete video: no sibling segment is generated any more."""
    video_id,seq,host,ids,_done=video_abandon_scope(sid)
    ordered=[int(sid)]+[i for i in ids if i!=int(sid)]
    abandoned=0;failed=[]
    for index,segment in enumerate(ordered):
        reason='用户放弃任务' if index==0 else f'同一视频（{host} 第 {seq:02d} 号）已被放弃，整条视频作废'
        try:
            abandon_task(segment,bridge,day,reason);abandoned+=1
        except ValueError as exc:
            if index==0:raise
            failed.append((segment,str(exc)))
    with connect() as con:
        con.execute("UPDATE videos SET edit_status='已放弃' WHERE id=?",(video_id,))
        con.execute("UPDATE flow_segments SET flow_status='已放弃',prompt_review_status='已放弃' WHERE video_id=? AND seg_seq<1000",(video_id,))
    return {'video_id':video_id,'seq':seq,'host':host,'abandoned':abandoned,'failed':failed}


def abandon_videos_from_editing(video_ids, bridge, day, reason='自动剪辑页手动放弃任务'):
    """Abandon one or more whole videos directly from the editing queue, even if some/all segments already completed Flow."""
    from app.core import work_dates
    vids = list(dict.fromkeys(int(v) for v in (video_ids or []) if v is not None))
    if not vids:
        return {'abandoned_videos': 0, 'skipped_videos': []}
    canon_day = work_dates.canonical(day)
    blocked_statuses = {'剪辑中', '自动剪辑中', '已导入DaVinci', '待导出', '导出中', '已导出', '已完成'}
    target_vids = []
    skipped_vids = []
    pending_sids = []
    with connect() as con:
        for vid in vids:
            vrow = con.execute('SELECT id, edit_status FROM videos WHERE id=?', (vid,)).fetchone()
            if not vrow or work_dates.video_work_date(con, vid) != canon_day:
                skipped_vids.append(vid)
                continue
            if str(vrow['edit_status'] or '') in blocked_statuses:
                skipped_vids.append(vid)
                continue
            target_vids.append(vid)
            srows = con.execute(
                "SELECT id, flow_status FROM flow_segments WHERE video_id=? AND seg_seq<1000 AND status NOT IN ('已撤销','已作废')",
                (vid,),
            ).fetchall()
            for sr in srows:
                if str(sr['flow_status'] or '') not in ('已完成', '已放弃'):
                    pending_sids.append(int(sr['id']))
    for sid in pending_sids:
        try:
            abandon_task(sid, bridge, canon_day, reason)
        except ValueError:
            pass
    if target_vids:
        with connect() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('CREATE TABLE IF NOT EXISTS flow_task_actions(id INTEGER PRIMARY KEY,segment_id INTEGER,action TEXT,detail TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
            for vid in target_vids:
                first_seg = con.execute('SELECT id FROM flow_segments WHERE video_id=? AND seg_seq<1000 ORDER BY seg_seq,id LIMIT 1', (vid,)).fetchone()
                if first_seg and int(first_seg['id']) not in pending_sids:
                    con.execute("INSERT INTO flow_task_actions(segment_id,action,detail) VALUES(?,'放弃',?)", (int(first_seg['id']), reason))
                con.execute("UPDATE videos SET edit_status='已放弃' WHERE id=?", (vid,))
                con.execute("DELETE FROM flow_redo WHERE segment_id IN (SELECT id FROM flow_segments WHERE video_id=? AND seg_seq<1000)", (vid,))
                con.execute(
                    "UPDATE flow_segments SET flow_status='已放弃', prompt_review_status='已放弃', generation_command='' WHERE video_id=? AND seg_seq<1000",
                    (vid,),
                )
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
                    con.execute("DELETE FROM davinci_video_state WHERE video_id=?", (vid,))
    return {'abandoned_videos': len(target_vids), 'skipped_videos': skipped_vids}


def abandon_videos_batch(segment_ids, bridge, day):
    """Abandon unique whole videos corresponding to one or more selected segment IDs."""
    seen_videos = set()
    ordered_rep_sids = []
    with connect() as con:
        for sid in (segment_ids or []):
            row = con.execute('SELECT id, video_id FROM flow_segments WHERE id=?', (int(sid),)).fetchone()
            if row and int(row['video_id']) not in seen_videos:
                seen_videos.add(int(row['video_id']))
                ordered_rep_sids.append(int(row['id']))
    abandoned_videos = 0
    abandoned_segments = 0
    failed = []
    for rep_sid in ordered_rep_sids:
        try:
            res = abandon_video(rep_sid, bridge, day)
            abandoned_videos += 1
            abandoned_segments += int(res.get('abandoned') or 0)
            for item in (res.get('failed') or []):
                failed.append(item)
        except Exception as exc:
            failed.append((rep_sid, str(exc)))
    return {
        'abandoned_videos': abandoned_videos,
        'abandoned_segments': abandoned_segments,
        'failed': failed,
    }


def _parse_utc_ts(value) -> float:
    from datetime import datetime, timezone
    s = str(value or '').strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def format_elapsed_cn(seconds: int) -> str:
    sec = max(0, int(seconds or 0))
    if sec < 60:
        return f'{sec}秒'
    mins, rem = divmod(sec, 60)
    if mins < 60:
        return f'{mins}分{rem:02d}秒' if mins < 10 and rem > 0 else f'{mins}分钟'
    hrs, rmins = divmod(mins, 60)
    return f'{hrs}小时{rmins:02d}分'


def classify_runtime_segment(seg: dict, stall_minutes: int = 10) -> dict:
    """Compute stall state, category, badge text, and tone for a runtime segment."""
    from app.ui.task_error_view import error_view, needs_prompt, upload_skipped

    status = str(seg.get('flow_status') or '待生成')
    cmd = str(seg.get('generation_command') or '')
    elapsed = int(seg.get('elapsed_seconds') or 0)
    rel_wait = int(seg.get('release_wait_seconds') or 0)
    retry_cnt = int(seg.get('flow_retry_count') or 0)
    rec_state = seg.get('recovery_state') or {}
    label, hist_cnt, reason, detail = error_view(seg, rec_state)

    gen_thresh = max(120, int(stall_minutes or 10) * 60)
    sub_thresh = min(180, gen_thresh) if stall_minutes >= 3 else gen_thresh

    is_stalled = False
    if status in ('失败', '下载失败'):
        if needs_prompt(seg):
            category = 'needs_prompt'
            tone = 'prompt'
            badge = '📝 需改词'
        elif upload_skipped(seg):
            category = 'upload_skipped'
            tone = 'upload'
            badge = '🖼 上传跳过'
        else:
            category = 'failed'
            tone = 'failed'
            badge = f'⚠ {status}' + (f' · {retry_cnt}次' if retry_cnt > 0 else '')
    elif status == '待生成' and not cmd:
        category = 'queued_retry'
        tone = 'queued'
        badge = f'↻ 排队' + (f' ({retry_cnt}次)' if retry_cnt > 0 else '')
        reason = '已重置，等待空闲通道自动领取'
    else:
        if rel_wait > 0:
            is_stalled = False
        elif status in ('已准备', '待生成', '已提交'):
            is_stalled = elapsed >= sub_thresh
        elif status in ('生成中', '下载中'):
            is_stalled = elapsed >= gen_thresh

        dur_txt = format_elapsed_cn(elapsed) if elapsed > 0 else ''
        if is_stalled:
            category = 'stalled'
            tone = 'stalled'
            badge = f'⏳ 卡 {dur_txt}' if dur_txt else f'⏳ {status}·卡住'
            if not reason:
                reason = (
                    '已提交超时未进入生成，建议点右侧 ↻ 换空闲通道重试'
                    if status in ('已准备', '已提交')
                    else '生成/下载耗时过长，建议点右侧 ↻ 换空闲通道重试'
                )
        else:
            category = 'running'
            tone = 'running'
            if rel_wait > 0:
                badge = f'🕒 错峰 {rel_wait}秒'
                reason = '浏览器错峰排队释放中'
            else:
                badge = f'● {status}' + (f' · {dur_txt}' if dur_txt else '')
                if not reason:
                    reason = '正在网页通道执行中'

    return {
        'category': category,
        'tone': tone,
        'is_stalled': is_stalled,
        'badge': badge,
        'label': label,
        'history_failures': int(hist_cnt or 0),
        'reason': reason,
        'detail': detail,
    }


def runtime_snapshot_for_date(day=None):
    """Build grouped Recipient -> Host -> Video -> Segment snapshot for RuntimeTasksDialog."""
    import time
    from app.core import work_dates

    target_day = work_dates.canonical(day or work_dates.active())
    now_ts = time.time()
    try:
        stall_min = max(2, int(repo.get_setting('flow_runtime_stall_minutes', '10') or 10))
    except Exception:
        stall_min = 10

    all_rows = [dict(r) for r in repo.list_flow_tasks(work_date=target_day)]
    host_totals = {}
    rec_totals = {}
    for r in all_rows:
        hid = int(r.get('host_id') or 0)
        rid = int(r.get('recipient_id') or 0)
        done = str(r.get('flow_status') or '') == '已完成' or bool(str(r.get('flow_output_path') or '').strip())
        hb = host_totals.setdefault(hid, {'total': 0, 'done': 0})
        hb['total'] += 1
        if done:
            hb['done'] += 1
        rb = rec_totals.setdefault(rid, {'total': 0, 'done': 0})
        rb['total'] += 1
        if done:
            rb['done'] += 1

    rows = [
        r for r in all_rows
        if r['flow_status'] not in ('已完成', '已放弃')
        and (
            r['flow_status'] in ('失败', '下载失败')
            or r['generation_command']
            or r['flow_error']
            or int(r['flow_retry_count'] or 0) > 0
        )
    ]
    ids = {int(r['segment_id']) for r in rows}

    states = {}
    latest_disp = {}
    disp_errors = {}
    if ids:
        marks = ','.join('?' * len(ids))
        id_params = list(ids)
        with connect() as con:
            for r in con.execute(f'SELECT * FROM flow_recovery WHERE segment_id IN ({marks})', id_params):
                states[int(r['segment_id'])] = dict(r)
            for r in con.execute(
                f'SELECT segment_id, command_id, status, stage, error, created_at, submitted_at, release_at, last_update_at '
                f'FROM flow_dispatches WHERE segment_id IN ({marks}) ORDER BY id',
                id_params,
            ):
                sid = int(r['segment_id'])
                d = dict(r)
                latest_disp[sid] = d
                if str(d.get('error') or '').strip():
                    disp_errors[sid] = str(d['error'])

    channels_raw = [dict(c) for c in repo.list_channel_pool(enabled_only=True) if str(c['collection_url'] or '').strip()]
    channels = []
    for c in channels_raw:
        ck = str(c['channel_key'])
        busy_cmd = str(c.get('task_command_id') or '').strip()
        seen_age = (now_ts - float(c['last_seen'])) if c.get('last_seen') else 999999.0
        online = seen_age < 25.0
        channels.append({
            'channel_key': ck,
            'role': str(c.get('role') or 'normal'),
            'busy': bool(busy_cmd),
            'online': online,
            'health': str(c.get('health_status') or 'healthy'),
        })

    rec_map = {}
    rec_order = []
    for row in rows:
        sid = int(row['segment_id'])
        if not row.get('flow_error') and row['flow_status'] in ('失败', '下载失败'):
            row['flow_error'] = disp_errors.get(sid, '')

        disp = latest_disp.get(sid) or {}
        rec_state = states.get(sid) or {}
        status = str(row.get('flow_status') or '待生成')
        cmd = str(row.get('generation_command') or '')

        rel_ts = float(disp.get('release_at') or 0.0) if cmd and disp.get('command_id') == cmd else 0.0
        rel_wait = 0
        started_ts = 0.0
        if status in ('生成中', '下载中', '已提交'):
            started_ts = (
                _parse_utc_ts(row.get('flow_submitted_at'))
                or (
                    _parse_utc_ts(disp.get('submitted_at'))
                    if (not cmd or disp.get('command_id') == cmd)
                    else 0.0
                )
                or (rel_ts if rel_ts > 0 else 0.0)
                or (_parse_utc_ts(disp.get('created_at')) if (not cmd or disp.get('command_id') == cmd) else 0.0)
            )
        elif cmd and status in ('已准备', '待生成'):
            if rel_ts > now_ts + 1.0:
                rel_wait = int(round(rel_ts - now_ts))
            else:
                c_ts = _parse_utc_ts(disp.get('created_at')) if disp.get('command_id') == cmd else 0.0
                started_ts = max(rel_ts, c_ts) if (rel_ts or c_ts) else _parse_utc_ts(row.get('flow_submitted_at'))

        elapsed_sec = max(0, int(now_ts - started_ts)) if started_ts > 0 and now_ts >= started_ts else 0

        seg_item = {
            **row,
            'segment_id': sid,
            'video_id': int(row.get('video_id') or 0),
            'video_seq': int(row.get('video_seq') or 0),
            'seg_seq': int(row.get('seg_seq') or 0),
            'host_id': int(row.get('host_id') or 0),
            'recipient_id': int(row.get('recipient_id') or 0),
            'flow_channel_key': str(row.get('flow_channel_key') or ''),
            'preferred_channel': str(rec_state.get('preferred_channel') or ''),
            'recovery_state': rec_state,
            'elapsed_seconds': elapsed_sec,
            'release_wait_seconds': rel_wait,
        }
        seg_item.update(classify_runtime_segment(seg_item, stall_min))

        rid = seg_item['recipient_id']
        hid = seg_item['host_id']
        vid = seg_item['video_id']
        if rid not in rec_map:
            rt = rec_totals.get(rid) or {'total': 0, 'done': 0}
            rec_map[rid] = {
                'recipient_id': rid,
                'recipient_name': str(row.get('recipient_name') or '未命名接收人'),
                'total_all_segments': rt['total'],
                'done_all_segments': rt['done'],
                'hosts_map': {},
                'hosts_order': [],
            }
            rec_order.append(rid)
        r_bucket = rec_map[rid]
        if hid not in r_bucket['hosts_map']:
            ht = host_totals.get(hid) or {'total': 0, 'done': 0}
            r_bucket['hosts_map'][hid] = {
                'host_id': hid,
                'host_name': str(row.get('host_name') or '未命名主播'),
                'image_path': str(row.get('image_path') or ''),
                'total_all_segments': ht['total'],
                'done_all_segments': ht['done'],
                'videos_map': {},
                'videos_order': [],
            }
            r_bucket['hosts_order'].append(hid)
        h_bucket = r_bucket['hosts_map'][hid]
        if not h_bucket['image_path'] and row.get('image_path'):
            h_bucket['image_path'] = str(row.get('image_path') or '')
        if vid not in h_bucket['videos_map']:
            h_bucket['videos_map'][vid] = {
                'video_id': vid,
                'video_seq': seg_item['video_seq'],
                'image_path': str(row.get('image_path') or ''),
                'segments': [],
            }
            h_bucket['videos_order'].append(vid)
        h_bucket['videos_map'][vid]['segments'].append(seg_item)

    recipients_out = []
    for rid in rec_order:
        rb = rec_map[rid]
        hosts_out = []
        for hid in rb['hosts_order']:
            hb = rb['hosts_map'][hid]
            videos_out = [hb['videos_map'][vid] for vid in hb['videos_order']]
            hosts_out.append({
                'host_id': hb['host_id'],
                'host_name': hb['host_name'],
                'image_path': hb['image_path'],
                'total_all_segments': hb['total_all_segments'],
                'done_all_segments': hb['done_all_segments'],
                'videos': videos_out,
            })
        recipients_out.append({
            'recipient_id': rb['recipient_id'],
            'recipient_name': rb['recipient_name'],
            'total_all_segments': rb['total_all_segments'],
            'done_all_segments': rb['done_all_segments'],
            'hosts': hosts_out,
        })

    return {
        'work_date': target_day,
        'stall_minutes': stall_min,
        'channels': channels,
        'recipients': recipients_out,
    }

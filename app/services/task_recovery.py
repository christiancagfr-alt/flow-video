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


def reset_task(sid,bridge,prompt=None,preferred_channel=None):
    if prompt is not None and not prompt.strip():raise ValueError('提示词不能为空')
    if preferred_channel is not None:
        channels={str(c['channel_key']) for c in repo.list_channel_pool(enabled_only=True) if c['collection_url']}
        if preferred_channel not in channels:raise ValueError('所选通道已移除或未设置链接')
    # A running batch is reset as a unit only when it contains this sole pending task.
    with connect() as con:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not row or row['flow_status'] in ('已完成','已放弃'):raise ValueError('任务已完成、已放弃或不存在，不能重复生成')
        if prompt is not None and row['flow_status'] not in ('待生成','失败','下载失败'):raise ValueError('任务已开始运行，请等待本次运行结束再修改提示词')
        cmd=row['generation_command'];channel=row['flow_channel_key']
        others=con.execute("SELECT 1 FROM flow_segments WHERE generation_command=? AND id<>? AND flow_status NOT IN ('已完成','失败','下载失败') LIMIT 1",(cmd,sid)).fetchone() if cmd else None
    if cmd:
        if others:bridge.remove_task_from_command(cmd,sid)
        else:bridge.cancel_host_commands([cmd])
    with connect() as con:
        current=con.execute('SELECT generation_command,flow_status FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not current or current[0]!=cmd or current[1]=='已完成':raise ValueError('任务状态已改变，请刷新后再试')
        con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED' WHERE command_id=? AND segment_id=?",(cmd,sid))
        con.execute("UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_error='',flow_retry_count=flow_retry_count+1 WHERE id=?",(sid,))
        if prompt is not None:
            if not prompt.strip():raise ValueError('提示词不能为空')
            con.execute('UPDATE flow_segments SET prompt=? WHERE id=?',(prompt.strip(),sid))
        con.execute('INSERT OR REPLACE INTO flow_recovery(segment_id,failures,blocked,notified,queued,preferred_channel) VALUES(?,0,0,0,0,?)',(sid,preferred_channel if preferred_channel is not None else channel))
        _route_retry(con,sid)
        if not others:con.execute("UPDATE flow_channel_pool SET task_command_id='',quarantine_until=0,health_status='healthy',upload_state='idle' WHERE channel_key=? AND (task_command_id=? OR task_command_id='')",(channel,cmd))
    return channel


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
    if work_date is None:
        with connect() as con:
            ids=[r[0] for r in con.execute("""SELECT fs.id FROM flow_segments fs JOIN flow_redo r ON r.segment_id=fs.id
                WHERE fs.flow_status='待生成' AND COALESCE(fs.generation_command,'')=''
                AND COALESCE(fs.qc_status,'')<>'退回'""").fetchall()]
    else:
        from app.core.work_dates import read_connection
        with read_connection(work_date) as con:
            ids=[r[0] for r in con.execute("""SELECT fs.id FROM flow_segments fs JOIN flow_redo r ON r.segment_id=fs.id
                WHERE fs.flow_status='待生成' AND COALESCE(fs.generation_command,'')=''
                AND COALESCE(fs.qc_status,'')<>'退回'""").fetchall()]
    if not ids:return 0
    with connect() as con:
        for sid in ids:con.execute('DELETE FROM flow_redo WHERE segment_id=?',(sid,))
    return len(ids)


def abandon_task(sid,bridge,day):
    """Explicitly retire one task; retain files and reject old command receipts."""
    from app.core import work_dates
    with connect() as con:
        row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not row or work_dates.video_work_date(con,row['video_id'])!=day:raise ValueError('任务日期已改变，请刷新')
        if row['flow_status']=='已完成':raise ValueError('该任务已完成，不能在这里放弃')
        command=row['generation_command'] or '';channel=row['flow_channel_key'] or ''
    if command:bridge.remove_task_from_command(command,sid)
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        current=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
        if not current or current['generation_command']!=row['generation_command'] or current['flow_status']=='已完成':
            raise ValueError('任务状态刚刚变化，请刷新后再试')
        con.execute('CREATE TABLE IF NOT EXISTS flow_task_actions(id INTEGER PRIMARY KEY,segment_id INTEGER,action TEXT,detail TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        con.execute("INSERT INTO flow_task_actions(segment_id,action,detail) VALUES(?,'放弃',?)",(sid,current['flow_error'] or '用户主动放弃'))
        con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error='用户放弃任务' WHERE segment_id=? AND command_id=?",(sid,command))
        con.execute("UPDATE flow_segments SET flow_status='已放弃',prompt_review_status='已放弃',generation_command='',flow_error=? WHERE id=?",('用户放弃任务；原错误：'+(current['flow_error'] or '未提供'),sid))
        con.execute('DELETE FROM flow_redo WHERE segment_id=?',(sid,))
        con.execute('INSERT OR REPLACE INTO flow_recovery(segment_id,failures,blocked,notified,queued,preferred_channel) VALUES(?,0,1,1,0,?)',(sid,channel))
        if command and not con.execute("SELECT 1 FROM flow_segments WHERE generation_command=? AND flow_status NOT IN ('已完成','失败','下载失败','已放弃')",(command,)).fetchone():
            con.execute("UPDATE flow_channel_pool SET task_command_id='' WHERE channel_key=? AND task_command_id=?",(channel,command))
    return True

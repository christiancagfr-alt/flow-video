"""Explicit selected-segment revision replacement, never whole-channel cancellation."""
from app.core import database, repository as repo, work_dates


def obsolete(con, sid, cmd):
    return bool(cmd and con.execute('SELECT 1 FROM flow_obsolete_segments WHERE segment_id=? AND command_id=?',(int(sid),str(cmd))).fetchone())


def refresh_classification(video_id, mode, asset_path, created_at):
    mode='PRAYING' if mode=='PRAYING' else 'TALKING'
    with database.connect() as con:
        if work_dates.video_work_date(con,video_id)!=work_dates.canonical(created_at):return False
        row=con.execute('SELECT performance_mode, image_path FROM videos WHERE id=?',(video_id,)).fetchone()
        if not row:return False
        if row[0]==mode:
            if asset_path and str(row[1] or '')!=str(asset_path):
                con.execute("UPDATE videos SET image_path=?,asset_status='已准备' WHERE id=?",(asset_path,video_id))
                return True
            return False
        con.execute("UPDATE videos SET performance_mode=?,image_path=?,asset_status='已准备' WHERE id=?",(mode,asset_path or '',video_id))
        # Keep paid/generated prompts for review, but return them to the GPT work queue.
        # Running Flow requests already have their own immutable payload.
        con.execute("UPDATE flow_segments SET prompt_review_status='待检查' WHERE video_id=?",(video_id,))
        return True


def replace(ids, day, prompt_overrides=None):
    import json
    ids=list(dict.fromkeys(int(x) for x in ids))
    if not ids:return {'submitted':0,'new_submitted':0,'replaced':0,'deleted_files':0,'delete_failures':[]}
    paths=[]
    new_submitted=0
    replaced=0
    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rows=[]
        for sid in ids:
            row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
            if not row or work_dates.video_work_date(con,row['video_id'])!=work_dates.canonical(day):
                raise ValueError('所选任务不存在或不属于当前工作日期，请刷新后重试。')
            row=dict(row)
            if sid in (prompt_overrides or {}) and str((prompt_overrides or {})[sid] or '').strip():
                row['prompt']=str(prompt_overrides[sid]).strip()
            if not str(row['prompt'] or '').strip():raise ValueError('所选任务有空提示词，请先生成或填写并保存。')
            rows.append(row)
        sid_set={int(r['id']) for r in rows}
        for row in rows:
            sid=int(row['id'])
            commands={str(row['generation_command'] or '').strip()} - {''}
            if str(row['flow_output_path'] or '').strip():
                paths.append(row['flow_output_path'])
            for old in con.execute('SELECT command_id,output_path FROM flow_outputs WHERE segment_id=?',(sid,)):
                if str(old[0] or '').strip(): commands.add(str(old[0]).strip())
                if str(old[1] or '').strip(): paths.append(old[1])
            for old in con.execute('SELECT command_id,download_path FROM flow_dispatches WHERE segment_id=?',(sid,)):
                if str(old[0] or '').strip(): commands.add(str(old[0]).strip())
                if str(old[1] or '').strip(): paths.append(old[1])
            had_downstream=bool(
                commands
                or str(row['flow_output_path'] or '').strip()
                or str(row['flow_status'] or '') not in ('','待生成')
                or str(row['qc_status'] or '待质检')!='待质检'
                or str(row['prompt_review_status'] or '')=='已提交'
            )
            if had_downstream:
                replaced+=1
            else:
                new_submitted+=1
            for cmd in commands:
                if cmd:con.execute('INSERT OR IGNORE INTO flow_obsolete_segments(segment_id,command_id) VALUES(?,?)',(sid,cmd))
            con.execute("UPDATE flow_dispatches SET status='stale',error='GPT选中任务重新提交，旧版本作废' WHERE segment_id=?",(sid,))
            for table in ('flow_outputs','flow_redo','flow_failure_attempts','flow_recovery','speech_analysis','local_qc_results','ai_qc_results','qc_decisions'):
                con.execute(f'DELETE FROM {table} WHERE segment_id=?',(sid,))
            new_status='已生成' if str(row.get('status') or '') in ('文案已改','待处理','') else str(row.get('status') or '已生成')
            con.execute("""UPDATE flow_segments SET prompt=?,status=?,generation_command='',flow_status='待生成',flow_output_path='',flow_output_url='',
                flow_error='',flow_channel_key='',flow_attempts=0,flow_retry_count=0,flow_submitted_at='',flow_completed_at='',
                qc_status='待质检',qc_note='',qc_reject_reason='',qc_decided_at='',
                prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP WHERE id=?""",(row['prompt'],new_status,sid))
            con.execute('INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)',(sid,row['prompt']))
            # The containing video must wait for its replacement segment before editing.
            con.execute("UPDATE videos SET edit_status='等待片段' WHERE id=?",(row['video_id'],))
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='davinci_video_state'").fetchone():
                con.execute("DELETE FROM davinci_video_state WHERE video_id=?",(row['video_id'],))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='flow_pending_downloads'").fetchone():
            for p_row in con.execute("SELECT event_id,payload FROM flow_pending_downloads").fetchall():
                try:
                    payload=json.loads(p_row['payload'] or '{}')
                    if int(payload.get('segment_id') or 0) in sid_set:
                        con.execute("DELETE FROM flow_pending_downloads WHERE event_id=?",(p_row['event_id'],))
                except Exception:
                    continue
        protected=[x[0] for x in con.execute("SELECT flow_output_path FROM flow_segments WHERE flow_output_path<>'' UNION SELECT output_path FROM flow_outputs WHERE output_path<>''")]
        deleted,failures=repo._safe_remove_exact_files(paths,protected)
    try:
        repo.release_finished_channel_commands()
    except Exception:
        pass
    return {'submitted':len(ids),'new_submitted':new_submitted,'replaced':replaced,'deleted_files':len(deleted),'delete_failures':failures}

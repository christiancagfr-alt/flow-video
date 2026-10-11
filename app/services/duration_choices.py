"""Explicit per-dialogue duration decisions; splitting preserves unrelated task IDs."""
import json
from app.core.database import connect
from app.core import repository as repo
from app.services.text_processing import flow_timing
from app.services.speech_preparation import rebalance_segments, timing_metadata


def timing(task):
    text=str(task['foreign_text'] or '')
    result=flow_timing(text)
    with connect() as con:
        row=con.execute('''SELECT dc.dialogue,dc.force_submit,COALESCE(dc.duration,0) duration,COALESCE(dc.locked,0) locked,
                                  COALESCE(fs.timing_status,'') timing_status,COALESCE(fs.manual_text_lock,0) manual_text_lock
                           FROM flow_segments fs LEFT JOIN flow_duration_choices dc ON dc.segment_id=fs.id
                           WHERE fs.id=?''',(task['segment_id'],)).fetchone()
    valid_choice=bool(row and row['dialogue']==text)
    stored=str(row['timing_status'] or '') if row else ''
    integrity_failed=(stored=='INTEGRITY_FAILED')
    if not integrity_failed and valid_choice and int(row['locked'] or 0) and int(row['duration'] or 0) in (4,6,8):
        result['duration']=int(row['duration'])
        result['needs_split']=False
        result['timing_status']='MANUAL_DURATION_LOCK'
    elif integrity_failed:
        # Integrity failure is never bypassed by a duration choice. The user must repair the
        # spoken text/segmentation first so the exact-text invariant can be re-established.
        result['timing_status']='INTEGRITY_FAILED'
    elif stored=='UNSPLITTABLE' and result['needs_split']:
        result['timing_status']='UNSPLITTABLE'
    result['force_submit']=bool(valid_choice and row['force_submit'] and not integrity_failed) if row else False
    result['manual_text_lock']=bool(row and row['manual_text_lock'])
    result['manual_duration_lock']=bool(valid_choice and row['locked'] and not integrity_failed) if row else False
    result['submission_blocked']=bool(integrity_failed or (result['needs_split'] and not result['force_submit'] and not result['manual_duration_lock']))
    return result


def unresolved(tasks):
    """Return tasks that must not be silently submitted to Flow.

    Uses one batch DB read so the auto scheduler gets a cheap eligibility gate rather than a
    per-task database scan. Integrity failures are always blocked; an explicit human duration
    lock may override only an UNSPLITTABLE/overlong duration condition.
    """
    items=list(tasks)
    if not items:
        return []
    ids=[int(t['segment_id']) for t in items]
    placeholders=','.join('?' for _ in ids)
    with connect() as con:
        rows=con.execute(f'''SELECT fs.id segment_id,COALESCE(fs.timing_status,'') timing_status,
                                    dc.dialogue,COALESCE(dc.force_submit,0) force_submit,
                                    COALESCE(dc.duration,0) duration,COALESCE(dc.locked,0) locked
                               FROM flow_segments fs
                               LEFT JOIN flow_duration_choices dc ON dc.segment_id=fs.id
                              WHERE fs.id IN ({placeholders})''',ids).fetchall()
    state={int(r['segment_id']):r for r in rows}
    blocked=[]
    for task in items:
        row=state.get(int(task['segment_id']))
        stored=str(row['timing_status'] or '') if row else ''
        if stored=='INTEGRITY_FAILED':
            blocked.append(task)
            continue
        check=flow_timing(str(task['foreign_text'] or ''))
        if not check['needs_split']:
            continue
        valid=bool(row and row['dialogue']==str(task['foreign_text'] or ''))
        explicit_override=bool(valid and (int(row['force_submit'] or 0) or (int(row['locked'] or 0) and int(row['duration'] or 0) in (4,6,8))))
        if not explicit_override:
            blocked.append(task)
    return blocked


def apply(tasks, mode):
    if mode not in ('split','force'):raise ValueError('无效时长处理方式')
    ids=[int(t['segment_id']) for t in tasks]
    added=[]
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for sid in ids:
            raw=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
            if not raw:raise ValueError('任务已变化，请刷新')
            r=dict(raw);text=r['foreign_text'] or ''
            check=flow_timing(text)
            if not check['needs_split']:continue
            if r['generation_command'] or r['flow_output_path']:
                raise ValueError('请先在运行任务窗口重置此任务，再选择时长处理方式')
            if mode=='force':
                # Existing explicit user override is kept as the manual duration lock.
                con.execute('''INSERT INTO flow_duration_choices(segment_id,dialogue,force_submit,duration,locked)
                               VALUES(?,?,1,8,1)
                               ON CONFLICT(segment_id) DO UPDATE SET dialogue=excluded.dialogue,force_submit=1,duration=8,locked=1''',(sid,text))
                continue
            if int(r.get('manual_text_lock') or 0):
                con.execute("UPDATE flow_segments SET timing_status='UNSPLITTABLE' WHERE id=?",(sid,))
                raise ValueError('⚠️ 时长超限 · 当前片段已人工调整/锁定，自动算法不会覆盖，请人工调整。')

            parts,status=rebalance_segments([text])
            if status!='OK' or len(parts)<2 or any(flow_timing(p)['needs_split'] for p in parts):
                con.execute("UPDATE flow_segments SET timing_status='UNSPLITTABLE' WHERE id=?",(sid,))
                raise ValueError('⚠️ 时长超限 · 需要人工调整：没有可安全使用的自然语义断点。')
            # Do not renumber existing siblings: their filename/dispatch order may already be in use.
            # Display sequences get inserted only when no later sibling has been dispatched.
            later=con.execute('SELECT * FROM flow_segments WHERE video_id=? AND seg_seq>? ORDER BY seg_seq DESC',(r['video_id'],r['seg_seq'])).fetchall()
            if any(x['generation_command'] or x['flow_output_path'] for x in later):
                raise ValueError('后续片段已经生成，无法更改片段顺序；请先重置后续片段或人工调整')
            if any(int(x['manual_text_lock'] or 0) for x in later):
                raise ValueError('后续存在人工锁定片段，自动算法不会改变其顺序；请人工调整当前片段')
            con.execute('INSERT INTO flow_split_history(video_id,segment_id,original_json) VALUES(?,?,?)',(r['video_id'],sid,json.dumps(r,ensure_ascii=False)))
            for x in later:con.execute('UPDATE flow_segments SET seg_seq=? WHERE id=?',(x['seg_seq']+len(parts)-1,x['id']))
            preferred=con.execute('SELECT preferred_channel FROM flow_recovery WHERE segment_id=?',(sid,)).fetchone()
            redo=con.execute('SELECT 1 FROM flow_redo WHERE segment_id=?',(sid,)).fetchone()
            for i,part in enumerate(parts):
                prompt=r['prompt'].replace(text,part) if text in r['prompt'] else r['prompt']
                prompt+='\n\nSpoken dialogue for this clip ONLY (do not speak other dialogue): '+json.dumps(part,ensure_ascii=False)
                meta=timing_metadata(part,'OK')
                if i==0:
                    child=sid
                    con.execute("""UPDATE flow_segments SET foreign_text=?,prompt=?,flow_error='',estimated_speech_duration=?,flow_duration_seconds=?,timing_status='OK',manual_text_lock=0 WHERE id=?""",
                                (part,prompt,meta['estimated_speech_duration'],meta['flow_duration_seconds'],sid))
                else:
                    cur=con.execute("""INSERT INTO flow_segments(video_id,seg_seq,foreign_text,prompt,status,segment_rule,prompt_review_status,prompt_submitted_at,
                                                estimated_speech_duration,flow_duration_seconds,timing_status,manual_text_lock)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,0)""",(r['video_id'],r['seg_seq']+i,part,prompt,r['status'],r['segment_rule'],r['prompt_review_status'],r['prompt_submitted_at'],
                                                           meta['estimated_speech_duration'],meta['flow_duration_seconds'],'OK'))
                    child=cur.lastrowid;added.append(child)
                if redo:con.execute('INSERT OR IGNORE INTO flow_redo(segment_id) VALUES(?)',(child,))
                if preferred:con.execute('INSERT OR REPLACE INTO flow_recovery(segment_id,preferred_channel) VALUES(?,?)',(child,preferred[0]))
        wanted=set(ids+added)
    return [dict(t) for t in repo.list_flow_tasks() if int(t['segment_id']) in wanted]


def dispatch_timing(task):
    """Transport stored video duration; never estimate or gate spoken text here.

    Upstream text preparation keeps its existing checks. The generation center
    only submits the approved task and preserves an explicit 4/6/8-second choice.
    """
    task = dict(task)
    try:
        duration = int(task.get('flow_duration_seconds') or 8)
    except (TypeError, ValueError):
        duration = 8
    locked = False
    with connect() as con:
        row = con.execute('SELECT dialogue,duration,locked FROM flow_duration_choices WHERE segment_id=?',
                          (task['segment_id'],)).fetchone()
    if row and row['dialogue'] == str(task.get('foreign_text') or '') and row['locked'] and row['duration'] in (4, 6, 8):
        duration, locked = int(row['duration']), True
    if duration not in (4, 6, 8):
        duration = 8
    return {'duration': duration, 'needs_split': False, 'force_submit': True,
            'submission_blocked': False, 'manual_duration_lock': locked,
            'manual_text_lock': bool(task.get('manual_text_lock'))}

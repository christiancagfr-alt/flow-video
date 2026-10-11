"""Eye state is metadata; never inject markers into source copy."""
import json
from app.services.sheet_style import runs, color_rgb

OPEN_EYE_PROMPT = (
    "Edit the supplied reference photo. Keep exactly the same person, face identity, age, "
    "skin tone, hairstyle, clothing, pose, hands, background, framing and lighting. "
    "Change only the eyes: both eyes naturally open, looking directly toward the camera. "
    "Preserve realistic anatomy and the original expression. Mouth relaxed. "
    "Do not add text, objects or another person. Produce one photorealistic reference image."
)


def blocks(snapshot, fallback='PRAYING'):
    if not snapshot or snapshot.get('local_override'): return []
    raw = snapshot.get('text', '').encode('utf-16-le')
    result = []
    for start, end, fmt in runs(snapshot):
        text = raw[start*2:end*2].decode('utf-16-le')
        color = color_rgb(fmt, snapshot.get('theme', {})) or {}
        r,g,b = (float(color.get(k, 0)) for k in ('red','green','blue'))
        mode = 'TALKING' if r >= .45 and r > g * 1.5 and r > b * 1.5 else ('PRAYING' if max(r,g,b) <= .35 else fallback)
        if result and result[-1][1] == mode:
            result[-1] = (result[-1][0] + text, mode)
        else: result.append((text, mode))
    return result


def reference_mode(styles, fallback='TALKING'):
    parts = blocks(styles.get('外文内容', {}), fallback)
    modes = {mode for text, mode in parts if text.strip()}
    return 'PRAYING' if 'PRAYING' in modes else ('TALKING' if modes else fallback)


def prepare(snapshot, prepare_text, fallback='TALKING'):
    parts = blocks(snapshot, fallback)
    lines, modes, timings, spoken = [], [], [], []
    for text, mode in parts:
        if not text.strip(): continue
        prepared = prepare_text(text)
        if not prepared.integrity_ok: raise ValueError('颜色分段的文案完整性校验失败，已保留原文')
        spoken.append(prepared.spoken_text)
        lines.extend(prepared.segments)
        modes.extend([mode] * len(prepared.segments))
        timings.extend(prepared.timings)
    return lines, modes, timings, ' '.join(spoken)


def save_modes(video_id, lines, modes, connection=None):
    from app.core import database, work_dates
    from contextlib import nullcontext
    if len(lines) != len(modes) or any(m not in ('TALKING','PRAYING') for m in modes):
        raise ValueError('颜色分类与片段不匹配')
    with (nullcontext(connection) if connection is not None else database.connect()) as con:
        rows = con.execute('SELECT id,foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq', (video_id,)).fetchall()
        if [r['foreign_text'].strip() for r in rows] != [x.strip() for x in lines]:
            return False
        data = {'work_date':work_dates.video_work_date(con, video_id), 'source':'sheet_color',
                'segments':{str(r['id']):{'text':r['foreign_text'],'mode':mode} for r,mode in zip(rows,modes)}}
        con.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (f'segment_eye_types:{video_id}',json.dumps(data,ensure_ascii=False)))
    return True


def enrich_job(job):
    """All dispatch entry points, including rework, share the same prerequisite."""
    from app.core import database
    from app.services.performance_types import _all_choices, selected_mode
    tasks = job.get('tasks') or []
    ids = [int(t['segment_id']) for t in tasks if t.get('segment_id')]
    if not ids: return job
    with database.connect() as con:
        rows = con.execute('SELECT fs.id segment_id,fs.video_id,fs.foreign_text,v.performance_mode '
                           'FROM flow_segments fs JOIN videos v ON v.id=fs.video_id '
                           'WHERE fs.id IN ('+','.join('?' for _ in ids)+')', ids).fetchall()
        saved = _all_choices(con)
        modes = {r['segment_id']:selected_mode(saved.get(r['video_id'],{}),r) or r['performance_mode'] for r in rows}
    result = dict(job)
    result['tasks'] = [{**t, 'open_eye_prompt': OPEN_EYE_PROMPT if modes.get(int(t.get('segment_id') or 0)) == 'TALKING' else ''} for t in tasks]
    return result


def reconcile_saved_colors(day):
    """Backfill old unstarted tasks from saved source styles, without reading Google."""
    from app.core import database, repository as repo, work_dates
    from app.services import sheet_style, performance_types
    from app.services.reflow_rules import prepare_configured_speech
    result = {'updated':0, 'skipped':0}
    with database.connect() as con:
        sheet_style.ensure_table(con)
        videos = [dict(r) for r in con.execute('SELECT v.id,v.original_script,v.performance_mode,s.payload FROM videos v JOIN video_source_styles s ON s.video_id=v.id')
                  if work_dates.video_work_date(con,r['id']) == day]
        saved = performance_types._all_choices(con)
    for video in videos:
        vid=video['id'];source=json.loads(video['payload']).get('外文内容',{})
        if not source or source.get('local_override') or ''.join(source.get('text','').split()) != ''.join((video['original_script'] or '').split()):
            result['skipped']+=1;continue
        with database.connect() as con:
            rows=con.execute('SELECT id segment_id,foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq',(vid,)).fetchall()
        snapshots=sheet_style.segment_snapshots(vid)
        modes=[]
        for row in rows:
            found={mode for text,mode in blocks(snapshots.get(row['segment_id']),video['performance_mode']) if text.strip()}
            if len(found)!=1: break
            modes.append(next(iter(found)))
        lines=[r['foreign_text'] for r in rows];timings=None
        if len(modes)!=len(rows) or not rows:
            lines,modes,timings,_=prepare(source,lambda text:prepare_configured_speech(text,max_chars=int(repo.get_setting('default_wrap','18') or 18)),video['performance_mode'])
        elif all(performance_types.selected_mode(saved.get(vid,{}),r)==m for r,m in zip(rows,modes)):
            continue
        if repo.sync_flow_segments(vid,lines,edit_unstarted=True,timing_meta=timings):
            save_modes(vid,lines,modes);result['updated']+=1
        else: result['skipped']+=1
    return result

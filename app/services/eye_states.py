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


def blocks(snapshot, fallback='TALKING'):
    if not snapshot or snapshot.get('local_override'): return []
    fallback=snapshot.get('base_mode',fallback)
    # Only an explicitly closed-eye script uses red/black as segment metadata.
    if fallback != 'PRAYING':return [(snapshot.get('text',''),'TALKING')]
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
    # The neighbouring requirement column determines the script type, not ink.
    return fallback


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
    from app.core import database, repository as repo
    from app.services.performance_types import _all_choices, selected_mode
    tasks = job.get('tasks') or []
    ids = [int(t['segment_id']) for t in tasks if t.get('segment_id')]
    result = dict(job)
    job_host_id = int(job.get('host_id') or 0)
    if not ids:
        if job_host_id > 0:
            ratio = repo.get_host_aspect_ratio(job_host_id)
            result['aspect_ratio'] = ratio
            result['aspectRatio'] = ratio
            result['video_aspect_ratio'] = ratio
        return result
    with database.connect() as con:
        rows = con.execute("SELECT fs.id segment_id,fs.video_id,fs.foreign_text,COALESCE(fs.video_model,'') video_model,v.performance_mode,v.host_id "
                           'FROM flow_segments fs JOIN videos v ON v.id=fs.video_id '
                           'WHERE fs.id IN ('+','.join('?' for _ in ids)+')', ids).fetchall()
        saved = _all_choices(con)
        modes = {r['segment_id']:selected_mode(saved.get(r['video_id'],{}),r) or r['performance_mode'] for r in rows}
        seg_hosts = {int(r['segment_id']): int(r['host_id'] or 0) for r in rows}
        seg_models = {int(r['segment_id']): repo.normalize_segment_video_model(r['video_model']) for r in rows}
    host_ids = {int(t.get('host_id') or seg_hosts.get(int(t.get('segment_id') or 0), 0) or job_host_id) for t in tasks}
    host_ids.discard(0)
    if job_host_id > 0:
        host_ids.add(job_host_id)
    host_ratios = {hid: repo.get_host_aspect_ratio(hid) for hid in host_ids}
    enriched_tasks = []
    task_ratios = []
    for t in tasks:
        sid = int(t.get('segment_id') or 0)
        hid = int(t.get('host_id') or seg_hosts.get(sid, 0) or job_host_id)
        ratio = host_ratios.get(hid) or repo.normalize_aspect_ratio(t.get('aspect_ratio') or job.get('aspect_ratio') or '9:16')
        task_ratios.append(ratio)
        vmodel = repo.normalize_segment_video_model(t.get('video_model') or t.get('videoModel') or seg_models.get(sid, ''))
        t_out = {
            **t,
            'host_id': hid or t.get('host_id'),
            'aspect_ratio': ratio,
            'aspectRatio': ratio,
            'open_eye_prompt': OPEN_EYE_PROMPT if modes.get(sid) == 'TALKING' else '',
        }
        if vmodel:
            t_out['video_model'] = vmodel
            t_out['videoModel'] = vmodel
            if vmodel == 'flow_omni':
                t_out['duration'] = 8
        enriched_tasks.append(t_out)
    result['tasks'] = enriched_tasks
    job_ratio = (
        host_ratios.get(job_host_id)
        or (task_ratios[0] if task_ratios else None)
        or repo.normalize_aspect_ratio(job.get('aspect_ratio') or '9:16')
    )
    result['aspect_ratio'] = job_ratio
    result['aspectRatio'] = job_ratio
    result['video_aspect_ratio'] = job_ratio
    settings = dict(result.get('settings') or {})
    settings['aspect_ratio'] = job_ratio
    settings['aspectRatio'] = job_ratio
    result['settings'] = settings
    return result


_reconciled_video_cache = {}


def _sig_digest(sig):
    import hashlib
    return hashlib.sha1(repr(sig).encode('utf-8', 'surrogatepass')).hexdigest()


def _ensure_reconcile_table(con):
    # Persistent "already reconciled" marker so a restart does not redo ~100 ms of
    # speech reflow per video just to confirm that nothing changed.
    con.execute('CREATE TABLE IF NOT EXISTS eye_reconcile_cache(video_id INTEGER PRIMARY KEY, sig TEXT NOT NULL)')


def _remember_reconciled(vid, cache_sig):
    from app.core import database
    _reconciled_video_cache[vid] = cache_sig
    try:
        with database.connect() as con:
            _ensure_reconcile_table(con)
            con.execute('INSERT INTO eye_reconcile_cache(video_id,sig) VALUES(?,?) ON CONFLICT(video_id) DO UPDATE SET sig=excluded.sig',
                        (int(vid), _sig_digest(cache_sig)))
    except Exception:
        pass


def reconcile_saved_colors(day):
    """Backfill old unstarted tasks from saved source styles, without reading Google."""
    from app.core import database, repository as repo, work_dates
    from app.services import sheet_style, performance_types
    from app.services.reflow_rules import prepare_configured_speech
    result = {'updated':0, 'skipped':0}
    with database.connect() as con:
        sheet_style.ensure_table(con)
        _ensure_reconcile_table(con)
        dates = work_dates.recipient_dates(con)
        videos = [dict(r) for r in con.execute(
            'SELECT v.id,v.original_script,v.performance_mode,h.recipient_id,s.payload '
            'FROM videos v JOIN hosts h ON h.id=v.host_id JOIN video_source_styles s ON s.video_id=v.id'
        ) if dates.get(r['recipient_id']) == day]
        if not videos:
            return result
        vids = [int(v['id']) for v in videos]
        saved = performance_types._all_choices(con, only_video_ids=vids)
        rows_by_vid = {}
        if len(vids) <= 400:
            vp = ','.join('?' for _ in vids)
            seg_rows = con.execute(f'SELECT id segment_id,video_id,foreign_text,COALESCE(manual_text_lock,0) manual_text_lock FROM flow_segments WHERE video_id IN ({vp}) ORDER BY video_id,seg_seq', vids).fetchall()
        else:
            seg_rows = con.execute('SELECT id segment_id,video_id,foreign_text,COALESCE(manual_text_lock,0) manual_text_lock FROM flow_segments ORDER BY video_id,seg_seq').fetchall()
        for sr in seg_rows:
            rows_by_vid.setdefault(int(sr['video_id']), []).append(sr)
        vp = ','.join('?' for _ in vids)
        persisted = {int(r[0]): str(r[1]) for r in con.execute(
            f'SELECT video_id,sig FROM eye_reconcile_cache WHERE video_id IN ({vp})', vids).fetchall()} if len(vids) <= 400 else {
            int(r[0]): str(r[1]) for r in con.execute('SELECT video_id,sig FROM eye_reconcile_cache').fetchall()}
    for video in videos:
        vid = int(video['id'])
        rows = rows_by_vid.get(vid, [])
        seg_sig = tuple((int(r['segment_id']), str(r['foreign_text'] or ''), int(r['manual_text_lock'] or 0)) for r in rows)
        saved_vid = saved.get(vid, {})
        saved_sig = tuple((int(r['segment_id']), performance_types.selected_mode(saved_vid, r)) for r in rows)
        cache_sig = (day, video['original_script'], video['performance_mode'], video['payload'], seg_sig, saved_sig)
        if _reconciled_video_cache.get(vid) == cache_sig:
            continue
        if persisted.get(vid) == _sig_digest(cache_sig):
            _reconciled_video_cache[vid] = cache_sig
            continue
        if any(int(r['manual_text_lock'] or 0) for r in rows):
            result['skipped']+=1
            _remember_reconciled(vid, cache_sig)
            continue
        source=json.loads(video['payload']).get('外文内容',{})
        if not source or source.get('local_override') or ''.join(source.get('text','').split()) != ''.join((video['original_script'] or '').split()):
            result['skipped']+=1
            _remember_reconciled(vid, cache_sig)
            continue
        snapshots=sheet_style.segment_snapshots(vid)
        modes=[]
        for row in rows:
            found={mode for text,mode in blocks(snapshots.get(row['segment_id']),video['performance_mode']) if text.strip()}
            if len(found)!=1: break
            modes.append(next(iter(found)))
        lines=[r['foreign_text'] for r in rows];timings=None
        if len(modes)!=len(rows) or not rows:
            lines,modes,timings,_=prepare(source,lambda text:prepare_configured_speech(text,max_chars=int(repo.get_setting('default_wrap','18') or 18)),video['performance_mode'])
            # Identical text + identical eye types: nothing to write. Previously this
            # case rewrote every row on each visit and then dropped the cache, so the
            # same ~5 s of reflow ran again on every switch to the GPT page.
            if rows and [str(x).strip() for x in lines]==[str(r['foreign_text'] or '').strip() for r in rows] \
                    and all(performance_types.selected_mode(saved_vid,r)==m for r,m in zip(rows,modes)):
                _remember_reconciled(vid, cache_sig)
                continue
        elif all(performance_types.selected_mode(saved_vid,r)==m for r,m in zip(rows,modes)):
            _remember_reconciled(vid, cache_sig)
            continue
        if repo.sync_flow_segments(vid,lines,edit_unstarted=True,timing_meta=timings):
            save_modes(vid,lines,modes);result['updated']+=1
            _reconciled_video_cache.pop(vid, None)
        else:
            result['skipped']+=1
            _remember_reconciled(vid, cache_sig)
    return result

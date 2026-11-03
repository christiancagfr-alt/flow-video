"""Read source eye-state instructions without changing Sheet row selection rules."""
import re


def is_mixed_requirement(value):
    text=re.sub(r'\s+','',str(value or ''))
    text=re.sub(r'(?:不(?:要|用|能|可)?|禁止)(?:睁眼|闭眼)','',text)
    return ('睁眼' in text and '闭眼' in text) or bool(re.search(r'睁[/／、和与]?闭眼.*(?:混合|交替)|(?:混合|交替).*睁[/／、和与]?闭眼',text))



def choices(con, video_id):
    import json
    from app.core import work_dates
    day=work_dates.video_work_date(con,video_id)
    saved=con.execute('SELECT value FROM app_settings WHERE key=?',(f'segment_eye_types:{int(video_id)}',)).fetchone()
    try:
        data=json.loads(saved[0]) if saved else {}
        return {key:{**value,'source':value.get('source',data.get('source','manual'))} for key,value in data.get('segments',{}).items() if isinstance(value,dict)} if data.get('work_date')==day else {}
    except (ValueError,TypeError,AttributeError):return {}


def selected_mode(saved, row):
    value=saved.get(str(row['segment_id']),{})
    if not isinstance(value,dict):return None
    saved_txt=str(value.get('text') or '').strip()
    row_txt=str(row['foreign_text'] or '').strip()
    if saved_txt and saved_txt!=row_txt:
        if re.findall(r'\w+',saved_txt.lower())!=re.findall(r'\w+',row_txt.lower()):
            return None
    mode=value.get('mode')
    return mode if mode in ('TALKING','PRAYING') else None


def _all_choices(con, video_dates=None, only_video_ids=None):
    import json
    from app.core import work_dates
    vids = sorted({int(v) for v in (only_video_ids or []) if v is not None}) if only_video_ids is not None else None
    if vids is not None:
        if not vids:
            return {}
        if len(vids) <= 400:
            keys = [f'segment_eye_types:{vid}' for vid in vids]
            placeholders = ','.join('?' for _ in keys)
            settings = con.execute(f"SELECT key,value FROM app_settings WHERE key IN ({placeholders})", keys).fetchall()
        else:
            settings = con.execute("SELECT key,value FROM app_settings WHERE key LIKE 'segment_eye_types:%'").fetchall()
    else:
        settings = con.execute("SELECT key,value FROM app_settings WHERE key LIKE 'segment_eye_types:%'").fetchall()
    if not settings:
        return {}
    if video_dates is None:
        dates = work_dates.recipient_dates(con)
        if vids is not None and len(vids) <= 400:
            vp = ','.join('?' for _ in vids)
            video_dates = {r['id']: dates.get(r['recipient_id']) for r in con.execute(f'SELECT v.id,h.recipient_id FROM main.videos v JOIN main.hosts h ON h.id=v.host_id WHERE v.id IN ({vp})', vids)}
        else:
            video_dates = {r['id']: dates.get(r['recipient_id']) for r in con.execute('SELECT v.id,h.recipient_id FROM main.videos v JOIN main.hosts h ON h.id=v.host_id')}
    result={}
    for row in settings:
        try:
            vid=int(row['key'].split(':')[1]);data=json.loads(row['value'])
            if isinstance(data,dict) and data.get('work_date')==video_dates.get(vid) and isinstance(data.get('segments'),dict):result[vid]={key:{**value,'source':value.get('source',data.get('source','manual'))} for key,value in data['segments'].items() if isinstance(value,dict)}
        except (ValueError,TypeError):pass
    return result


def apply_choices(con, rows):
    """Batch metadata lookup; preserve sqlite.Row compatibility without per-row SQL."""
    import sqlite3
    if not rows:return rows
    vids = [r['video_id'] for r in rows if r and r['video_id'] is not None]
    cache=_all_choices(con, only_video_ids=vids)
    columns=list(rows[0].keys())+['segment_type_manual','segment_type_source']
    cursor=con.execute('SELECT '+','.join('NULL AS "'+k+'"' for k in columns))
    result=[]
    for row in rows:
        mode=selected_mode(cache.get(row['video_id'],{}),row)
        values=dict(row);values['segment_type_manual']=bool(mode)
        values['segment_type_source']=cache.get(row['video_id'],{}).get(str(row['segment_id']),{}).get('source','manual') if mode else 'unclassified'
        if mode:
            values['performance_mode']=mode;values['prompt_template_snapshot']=''
        result.append(sqlite3.Row(cursor,tuple(values[k] for k in columns)))
    return result


def save_segment_types(video_id, lines, modes, day):
    import json
    from app.core import database,work_dates
    if len(lines)!=len(modes) or any(m not in ('TALKING','PRAYING') for m in modes):raise ValueError('每个片段请选择睁眼或闭眼')
    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if work_dates.video_work_date(con,video_id)!=work_dates.normalize_scope(day):raise ValueError('任务日期已变化，请重新打开编辑窗口')
        rows=con.execute('SELECT id segment_id,foreign_text FROM flow_segments WHERE video_id=? ORDER BY seg_seq',(video_id,)).fetchall()
        if [r['foreign_text'].strip() for r in rows]!=lines:raise ValueError('分段已变化，请重新打开编辑窗口')
        data={'work_date':day,'segments':{str(row['segment_id']):{'text':row['foreign_text'],'mode':mode} for row,mode in zip(rows,modes)}}
        con.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(f'segment_eye_types:{int(video_id)}',json.dumps(data,ensure_ascii=False)))


def confirmed_videos(con, video_dates, only_video_ids=None):
    vids = sorted({int(v) for v in (only_video_ids or []) if v is not None}) if only_video_ids is not None else None
    if vids is not None and not vids:
        return set()
    cache = _all_choices(con, video_dates, only_video_ids=vids)
    seen = set()
    unconfirmed = set()
    if vids is not None and len(vids) <= 400:
        vp = ','.join('?' for _ in vids)
        rows = con.execute(f'SELECT id segment_id,video_id,foreign_text FROM flow_segments WHERE video_id IN ({vp})', vids)
    else:
        rows = con.execute('SELECT id segment_id,video_id,foreign_text FROM flow_segments')
    for row in rows:
        vid = row['video_id']
        seen.add(vid)
        if not selected_mode(cache.get(vid, {}), row):
            unconfirmed.add(vid)
    return seen - unconfirmed

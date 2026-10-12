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
    if value.get('text')!=row['foreign_text']:return None
    mode=value.get('mode')
    return mode if mode in ('TALKING','PRAYING') else None


def _all_choices(con, video_dates=None):
    import json
    from app.core import work_dates
    settings=con.execute("SELECT key,value FROM app_settings WHERE key LIKE 'segment_eye_types:%'").fetchall()
    if not settings:return {}
    if video_dates is None:
        dates=work_dates.recipient_dates(con)
        video_dates={r['id']:dates.get(r['recipient_id']) for r in con.execute('SELECT v.id,h.recipient_id FROM main.videos v JOIN main.hosts h ON h.id=v.host_id')}
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
    cache=_all_choices(con)
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


def confirmed_videos(con, video_dates):
    cache=_all_choices(con,video_dates);seen=set();unconfirmed=set()
    for row in con.execute('SELECT id segment_id,video_id,foreign_text FROM flow_segments'):
        vid=row['video_id'];seen.add(vid)
        if not selected_mode(cache.get(vid,{}),row):unconfirmed.add(vid)
    return seen-unconfirmed

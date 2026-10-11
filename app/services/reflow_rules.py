"""Explicit, date-scoped reflow of unsubmitted copy. Never dispatches work."""
from dataclasses import asdict
import json
from app.core import database, repository as repo, work_dates
from app.services.speech_preparation import ReflowPolicy, prepare_swahili_speech

KEY='editable_reflow_rules_v1'
DEFAULTS=dict(max_chars=18, **asdict(ReflowPolicy()))


def validate(value):
    result={**DEFAULTS, **value}
    if type(result['max_chars']) is not int or not 1<=result['max_chars']<=100000:
        raise ValueError('参考字符数必须在 1～100000 之间')
    if type(result['min_tail_words']) is not int or not 1<=result['min_tail_words']<=10:
        raise ValueError('句尾最少词数必须在 1～10 之间')
    allowed=set('.!?。！？,;:，；：')
    for key in ('sentence_marks','clause_marks'):
        text=str(result[key])
        if len(text)>24 or any(ch not in allowed for ch in text):
            raise ValueError('断句标点仅支持 . ! ? 。！？ , ; : ，；：，可留空')
        result[key]=''.join(dict.fromkeys(text))
    for key in ('preserve_newlines','swahili_boundaries'):
        if type(result[key]) is not bool:raise ValueError('开关值无效')
    # V0.13.5.91: fixed Swahili instruction. Existing line breaks never lock segmentation, and
    # the complete natural punctuation set is always available for punctuation-only splitting.
    result['preserve_newlines']=False
    result['sentence_marks']='.!?。！？'
    result['clause_marks']=';:；：,，'
    return {key:result[key] for key in DEFAULTS}


def load():
    saved=repo.get_setting(KEY,'')
    value=json.loads(saved) if saved else dict(DEFAULTS)
    value['max_chars']=int(repo.get_setting('default_wrap',str(value.get('max_chars',18))) or 18)
    return validate(value)


def prepare_with_rules(text, config):
    config=validate(config)
    return prepare_swahili_speech(text,max_chars=config['max_chars'],rules=ReflowPolicy(**{k:v for k,v in config.items() if k!='max_chars'}))


def prepare_configured_speech(text,max_chars=None):
    saved=repo.get_setting(KEY,'')
    if not saved:return prepare_swahili_speech(text,max_chars=max_chars)
    config=load()
    if max_chars is not None:config['max_chars']=int(max_chars)
    return prepare_with_rules(text,config)


def _source(video):
    current=video['script'] or ''
    production=video['production_script'] or current
    return video['original_script'] if video['original_script'] and ''.join(current.split())==''.join(production.split()) else current


def apply(config,day,progress=None):
    config=validate(config);day=work_dates.normalize_scope(day)
    with work_dates.read_connection(day) as con:
        ids=[r[0] for r in con.execute('SELECT id FROM videos ORDER BY id')]
    with database.connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS script_reflow_history(
            id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL, work_date TEXT NOT NULL,
            before_json TEXT NOT NULL, rules_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        for key,value in [(KEY,json.dumps(config,ensure_ascii=False)),('default_wrap',str(config['max_chars']))]:
            con.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
    result=dict(changed=0,unchanged=0,skipped=0,reset_prompts=0,details=[],work_date=day)
    rules_json=json.dumps(config,ensure_ascii=False)
    for index,vid in enumerate(ids):
        # Each video uses a short write transaction; the scheduler stays responsive.
        with database.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            video=con.execute('SELECT * FROM videos WHERE id=?',(vid,)).fetchone()
            if not video or work_dates.video_work_date(con,vid)!=day:
                result['skipped']+=1;continue
            try:
                rows=repo._assert_prompt_copy_editable(con,vid)
                if any(r['qc_status']!='待质检' or r['flow_output_path'] or r['flow_output_url'] or r['status'] in ('生成中','处理中','请求中') for r in rows):
                    raise ValueError('片段已有活动或质检状态')
            except ValueError as exc:
                result['skipped']+=1
                if len(result['details'])<100:result['details'].append(f'视频 {vid}：{exc}')
                continue
            source=_source(video)
            if not source.strip():result['unchanged']+=1;continue
            prepared=prepare_with_rules(source,config)
            if not prepared.integrity_ok:raise ValueError(f'视频 {vid} 文本完整性校验失败，已保留原文')
            raw_lines=list(prepared.segments)
            lines = []
            modes = []
            for raw in raw_lines:
                if "[TALKING]" in raw:
                    modes.append("TALKING")
                    cleaned = raw.replace("[TALKING]", "").replace("[/TALKING]", "")
                    lines.append(cleaned)
                else:
                    modes.append("PRAYING" if video["performance_mode"] == "PRAYING" else "TALKING")
                    cleaned = raw.replace("[TALKING]", "").replace("[/TALKING]", "")
                    lines.append(cleaned)
                    
            from app.services import eye_states
            color_modes = []
            has_styles = con.execute("SELECT 1 FROM sqlite_master WHERE name='video_source_styles'").fetchone()
            style_row = con.execute('SELECT payload FROM video_source_styles WHERE video_id=?',(vid,)).fetchone() if has_styles else None
            snapshot = json.loads(style_row[0]).get('外文内容',{}) if style_row else {}
            if snapshot and not snapshot.get('local_override') and ''.join(snapshot.get('text','').split()) == ''.join(source.split()):
                lines, color_modes, _, _ = eye_states.prepare(snapshot,lambda text:prepare_with_rules(text,config),video['performance_mode'])
            if [r['foreign_text'] for r in rows]==lines:
                if color_modes: eye_states.save_modes(vid,lines,color_modes,con)
                result['unchanged']+=1;continue
            con.execute('INSERT INTO script_reflow_history(video_id,work_date,before_json,rules_json) VALUES(?,?,?,?)',
                        (vid,day,json.dumps({'video':dict(video),'segments':[dict(r) for r in rows]},ensure_ascii=False),rules_json))
            by_seq={int(r['seg_seq']):r for r in rows}
            for seq,line in enumerate(lines,1):
                old=by_seq.get(seq)
                if old and old['foreign_text']==line:continue
                if old:
                    sid=int(old['id']);result['reset_prompts']+=bool(old['prompt'])
                    repo._reset_prompt_after_copy_change(con,sid,line)
                    con.execute('DELETE FROM flow_duration_choices WHERE segment_id=?',(sid,))
                else:
                    cursor=con.execute('INSERT INTO flow_segments(video_id,seg_seq,foreign_text,manual_text_lock) VALUES(?,?,?,1)',(vid,seq,line))
                    repo._reset_prompt_after_copy_change(con,cursor.lastrowid,line)
            for row in rows:
                if int(row['seg_seq'])>len(lines):
                    result['reset_prompts']+=bool(row['prompt'])
                    con.execute('DELETE FROM flow_duration_choices WHERE segment_id=?',(row['id'],))
                    con.execute('DELETE FROM flow_segments WHERE id=?',(row['id'],))
            con.execute('UPDATE videos SET original_script=?,script=?,production_script=? WHERE id=?',(source,'\n'.join(lines),prepared.spoken_text,vid))
            if color_modes: eye_states.save_modes(vid,lines,color_modes,con)
            result['changed']+=1
        if progress:progress(index+1,len(ids))
    return result

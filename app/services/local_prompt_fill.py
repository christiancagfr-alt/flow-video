"""Local prompt entry: no network or API usage."""
import csv
import io
import json
import re
from app.core import database, repository as repo, work_dates

KEY='direct_prompt_templates_v1'
BUILTINS=[
 {'name':'通用人物讲话（按任务自动睁闭眼）','body':'Use the reference image to preserve the same person, clothing, lighting and background. {眼睛要求} Natural restrained body movements and accurate lip sync. Speak exactly the following dialogue without additions: "{文案}". No subtitles, on-screen text or background music.'},
 {'name':'固定中景（按任务自动睁闭眼）','body':'A stable medium shot of the same person as the reference image. Keep the camera fixed and preserve identity and background. {眼睛要求} Speak naturally with accurate lip sync: "{文案}". No additional dialogue, captions, text or music.'}
]


def templates():
    try: saved=json.loads(repo.get_setting(KEY,'[]'))
    except (ValueError,TypeError): saved=[]
    if not isinstance(saved,list):saved=[]
    return BUILTINS+[x for x in saved if isinstance(x,dict) and x.get('name') and x.get('body')]


def save_template(name,body):
    name=name.strip();body=body.strip()
    if not name or not body:raise ValueError('请填写模板名称和内容。')
    if name in {t['name'] for t in BUILTINS}:raise ValueError('请使用新的名称保存自定义模板。')
    saved=[t for t in templates()[len(BUILTINS):] if t['name']!=name]
    saved.append({'name':name,'body':body})
    repo.set_setting(KEY,json.dumps(saved,ensure_ascii=False))


def parse_manual(text,separator=False):
    if not text.strip():return []
    if separator:
        rows=re.split(r'^\s*---\s*$',text,flags=re.MULTILINE)
    else:
        records=list(csv.reader(io.StringIO(text),delimiter='\t'))
        if any(len(row)>1 for row in records):raise ValueError('请只复制一列提示词；多行提示词也可选择 --- 分隔方式。')
        rows=[row[0] if row else '' for row in records]
    if any(not row.strip() for row in rows):raise ValueError('存在空白提示词，请补齐或删除空白行，避免错位。')
    return [row.strip() for row in rows]


def render(body,task):
    eye='Keep both eyes naturally open from the first frame throughout this speaking clip.' if task['performance_mode']=='TALKING' else 'Keep both eyes closed throughout this prayer clip.'
    values={'文案':task['foreign_text'],'主播':task['host_name'],'任务ID':f"{task['video_seq']:02d}-{task['seg_seq']:02d}",
            '类型':'闭眼祷告' if task['performance_mode']=='PRAYING' else '睁眼说话','眼睛要求':eye}
    if '{文案}' not in body:raise ValueError('模板中需要包含 {文案}，以自动填入每个片段的对白。')
    # One pass: braces in dialogue are literal, never expanded again.
    return re.sub(r'\{(文案|主播|任务ID|类型|眼睛要求)\}',lambda m:str(values[m[1]] or ''),body).strip()


def save(mapping,expected,day,source,template_name=''):
    if source not in ('手动批量','模板套用'):raise ValueError('未知填写方式')
    if not mapping:raise ValueError('没有可保存的提示词')
    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for sid,prompt in mapping.items():
            row=con.execute('SELECT * FROM flow_segments WHERE id=?',(sid,)).fetchone()
            old=expected.get(sid)
            if not row or not old or work_dates.video_work_date(con,row['video_id'])!=day:
                raise ValueError('任务或工作日期已变化，请关闭窗口后重新打开。')
            if row['foreign_text']!=old['foreign_text'] or (row['prompt'] or '')!=(old['prompt'] or ''):
                raise ValueError('文案或提示词已变化，请关闭窗口后重新预览。')
            if not prompt.strip():raise ValueError('不能保存空提示词。')
            if row['generation_command'] or row['flow_output_path'] or row['prompt_review_status']=='已提交' or row['qc_status']!='待质检' or row['status'] in ('生成中','处理中','请求中'):
                raise ValueError('包含已进入生产或正在生成的任务，本次未保存。')
            for table in ('flow_outputs','flow_redo','flow_recovery','flow_dispatches'):
                if con.execute('SELECT 1 FROM '+table+' WHERE segment_id=?',(sid,)).fetchone():
                    raise ValueError('包含已有生产记录的任务，本次未保存。')
        con.execute('CREATE TABLE IF NOT EXISTS prompt_fill_sources(segment_id INTEGER PRIMARY KEY,source TEXT,template_name TEXT,updated_at TEXT)')
        for sid,prompt in mapping.items():
            con.execute("UPDATE flow_segments SET prompt=?,status='已自定义',prompt_review_status='待检查',model=CASE WHEN coalesce(model,'')='' THEN ? ELSE model END WHERE id=?",(prompt.strip(),source,sid))
            con.execute('INSERT OR REPLACE INTO prompt_fill_sources VALUES(?,?,?,CURRENT_TIMESTAMP)',(sid,source,template_name))
    return len(mapping)

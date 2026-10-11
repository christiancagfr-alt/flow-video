"""Read-only complete-video cohort totals; backlog spans every work date."""
from collections import defaultdict
from pathlib import Path
import math,struct,time
from app.core import database,work_dates
_CACHE={}
def completed(row):
    return row.get('edit_status') in ('已导出','已完成') or row.get('upload_status') in ('已上传','已交付')
def movie_duration(path):
    """Read MP4/MOV movie-header duration without decoding or modifying the file."""
    try:
        p=Path(path);st=p.stat();key=(str(p),st.st_size,st.st_mtime_ns)
        cached=_CACHE.get(key)
        if cached and (cached[0] is not None or time.monotonic()-cached[1]<60):return cached[0]
        def scan(f,end):
            while f.tell()+8<=end:
                start=f.tell();header=f.read(8);size,kind=struct.unpack('>I4s',header);header_size=8
                if size==1:
                    size=struct.unpack('>Q',f.read(8))[0];header_size=16
                elif size==0:size=end-start
                if size<header_size or start+size>end:return None
                if kind==b'moov':return scan(f,start+size)
                if kind==b'mvhd':
                    data=f.read(min(size-header_size,40));version=data[0]
                    if version==0:scale,duration=struct.unpack_from('>II',data,12)
                    elif version==1:scale,duration=struct.unpack_from('>IQ',data,20)
                    else:return None
                    if not scale or duration in (0,0xffffffff,0xffffffffffffffff):return None
                    return duration/scale
                f.seek(start+size)
            return None
        with p.open('rb') as f:value=scan(f,st.st_size)
        if len(_CACHE)>4000:_CACHE.clear()
        _CACHE[key]=(value,time.monotonic());return value
    except (OSError,ValueError,IndexError,struct.error):return None

def summarize(rows,day,duration_reader=movie_duration):
    cohort=[r for r in rows if r['work_date']==day]
    people=defaultdict(lambda:dict(total=0,completed=0,seconds=0.,duration_missing=0,backlog=0))
    for r in rows:
        if not completed(r):people[str(r.get('recipient_name') or '未命名')]['backlog']+=1
    seconds=0.;missing=0;done=0
    for r in cohort:
        person=people[str(r.get('recipient_name') or '未命名')];person['total']+=1
        if completed(r):
            done+=1;person['completed']+=1
            duration=duration_reader(str(r.get('edit_output_path') or ''))
            if duration is None or not math.isfinite(duration) or duration<=0:missing+=1;person['duration_missing']+=1
            else:seconds+=duration;person['seconds']+=duration
    recipients=[]
    for name,p in people.items():
        if not p['total'] and not p['backlog']:continue
        recipients.append(dict(p,recipient_name=name,unfinished=p['total']-p['completed'],rate=p['completed']/p['total'] if p['total'] else 0.))
    return dict(day=day,total=len(cohort),completed=done,unfinished=len(cohort)-done,rate=done/len(cohort) if cohort else 0.,seconds=seconds,duration_missing=missing,
                backlog=sum(not completed(r) for r in rows),recipients=sorted(recipients,key=lambda r:(-r['total'],-r['backlog'],r['recipient_name'])))

def snapshot(day):
    con=database.connect()
    try:
        con.execute('PRAGMA query_only=ON');dates=work_dates.recipient_dates(con)
        rows=[dict(r) for r in con.execute('SELECT v.id video_id,v.edit_status,v.edit_output_path,v.upload_status,h.recipient_id,r.name recipient_name FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id')]
        for r in rows:r['work_date']=dates[r['recipient_id']]
        sources={(r['source_task_id'],str(r['source_row'])):r['video_id'] for r in con.execute('SELECT source_task_id,source_row,video_id FROM source_tasks')}
    finally:con.close()
    # Include source tasks still waiting for materials/promotion, without counting linked videos twice.
    from app.services import pre_gpt_pipeline as intake
    import sqlite3
    if intake.DB_FILE.is_file():
        with sqlite3.connect(intake.DB_FILE.resolve().as_uri()+'?mode=ro',uri=True) as c:
            c.row_factory=sqlite3.Row
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'tasks','production_links'}<=tables:
                known={r['video_id'] for r in rows}
                for task in c.execute('SELECT t.*,p.video_id FROM tasks t LEFT JOIN production_links p ON p.task_id=t.id WHERE t.sheet_row>0'):
                    source=intake._source_task_key(task['spreadsheet_id'],task['gid'],task['content_key'])
                    linked=task['video_id'] or sources.get((source,str(task['sheet_row'])))
                    if linked in known or not (task['chinese_text'] or task['foreign_text']):continue
                    rows.append(dict(video_id='intake:'+str(task['id']),recipient_name=task['recipient'],work_date=work_dates.canonical(task['created_at']) or work_dates.LEGACY,edit_status='',upload_status='',edit_output_path=''))
    return summarize(rows,day)

"""Read-only date view of intake plus durable Studio tasks removed from the source sheet."""
import sqlite3
from pathlib import Path
from app.core import work_dates
from app.services import pre_gpt_pipeline as intake
from app.services.file_filters import is_ignored_system_path
from app.services.performance_types import is_mixed_requirement

def _read_intake():
    if not intake.DB_FILE.is_file():return [],{}
    con=sqlite3.connect(intake.DB_FILE.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    try:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'tasks','groups_tbl'}<=tables:return [],{}
        tasks=[dict(r) for r in con.execute('SELECT * FROM tasks')]
        groups={r['group_key']:dict(r) for r in con.execute('SELECT * FROM groups_tbl')}
        return tasks,groups
    finally:con.close()

def snapshot(day=None):
    day=day or work_dates.active(); raw,metadata=_read_intake()
    links={}
    if intake.DB_FILE.is_file():
        with sqlite3.connect(intake.DB_FILE) as icon:
            if icon.execute("SELECT 1 FROM sqlite_master WHERE name='production_links'").fetchone():links=dict(icon.execute('SELECT task_id,video_id FROM production_links'))
    with work_dates.read_connection() as con:
        dates=work_dates.recipient_dates(con)
        from app.services.performance_types import confirmed_videos
        videos={r['video_id']:dict(r) for r in con.execute('SELECT v.*,v.id video_id,h.id host_id,h.name host_name,r.id recipient_id,r.name recipient_name FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id')}
        confirmed=confirmed_videos(con,{vid:dates[v['recipient_id']] for vid,v in videos.items()})
        sources={(r['source_task_id'],str(r['source_row'])):r['video_id'] for r in con.execute('SELECT * FROM source_tasks')}
    if intake.DB_FILE.is_file():
        with sqlite3.connect(intake.DB_FILE) as icon:
            tables={r[0] for r in icon.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'intake_view_state' in tables and icon.execute('SELECT 1 FROM intake_view_state WHERE day=? AND hidden=1',(day,)).fetchone():
                return [],[],set(dates.values())
    represented=set(); groups={}; tasks=[];all_dates=set()
    for t in raw:
        if int(t["sheet_row"])<=0:continue
        sid=intake._source_task_key(t['spreadsheet_id'],t['gid'],t.get('content_key',''))
        vid=links.get(t['id']) or sources.get((sid,str(t['sheet_row'])));v=videos.get(vid)
        task_day=dates[v['recipient_id']] if v else (work_dates.canonical(t.get('created_at')) or work_dates.LEGACY)
        if t.get('foreign_text') or t.get('chinese_text'):all_dates.add(task_day)
        if task_day!=day:continue
        if v:represented.add(vid)
        key=t['group_key'];m=metadata.get(key,{})
        g=groups.setdefault(key,dict(
            group_key=key,recipient=t['recipient'],anchor_name=t['anchor_name'],
            recipient_id=(v.get('recipient_id') if v else None),host_id=(v.get('host_id') if v else None),
            drive_url=m.get('drive_url',''),local_dir=m.get('local_dir',''),talking=0,praying=0,
            images=m.get('image_count',0),status=m.get('status','IMPORTED'),message=m.get('message',''),archived=False
        ))
        if is_mixed_requirement(t.get('requirement')):g['_mixed_source']=True
        if vid not in confirmed:g['_type_unconfirmed']=True
        # A group may be encountered before one of its rows has been promoted to Studio.
        # Once a linked production row exists, expose the durable Studio IDs so Task Center
        # can open the existing script/image editor without going through the old Home page.
        if v:
            g['recipient_id']=v.get('recipient_id')
            g['host_id']=v.get('host_id')
        effective_mode=t['mode']
        g['praying' if effective_mode=='PRAYING' else 'talking']+=1
        task_asset = str(t.get('matched_asset_path') or '')
        if task_asset and is_ignored_system_path(Path(task_asset)):
            task_asset = ''
        tasks.append(dict(
            id=t['id'],group_key=key,sheet_row=t['sheet_row'],recipient=t['recipient'],anchor_name=t['anchor_name'],
            recipient_id=(v.get('recipient_id') if v else None),host_id=(v.get('host_id') if v else None),
            video_id=(v.get('video_id') if v else None),mode=effective_mode,chinese=t['chinese_text'],
            foreign=t['foreign_text'],asset=task_asset,status=t['status']
        ))
    for vid,v in videos.items():
        if dates[v['recipient_id']]!=day or vid in represented:continue
        key=f"studio:{v['recipient_id']}:{v['host_id']}"
        image=v.get('image_path') or ''
        if image and is_ignored_system_path(Path(image)):
            image=''
        g=groups.setdefault(key,dict(
            group_key=key,recipient=v['recipient_name'],anchor_name=v['host_name'],
            recipient_id=v['recipient_id'],host_id=v['host_id'],drive_url='',
            local_dir=str(Path(image).parent) if image else '',talking=0,praying=0,images=0,
            status='READY_FOR_GPT',message='已保存的生产任务',archived=True
        ))
        g['praying' if v.get('performance_mode')=='PRAYING' else 'talking']+=1
        g['images']+=bool(image)
        tasks.append(dict(
            id=f'studio:{vid}',group_key=key,sheet_row=v['seq'],recipient=v['recipient_name'],anchor_name=v['host_name'],
            recipient_id=v['recipient_id'],host_id=v['host_id'],video_id=vid,mode=v.get('performance_mode'),
            chinese=v.get('chinese_script',''),foreign=v.get('script',''),asset=image,status=v.get('edit_status','')
        ))
    for g in groups.values():g['mixed_requirement']=bool(g.pop('_mixed_source',False) and g.get('_type_unconfirmed'));g.pop('_type_unconfirmed',None)
    return list(groups.values()),tasks,all_dates

def list_groups():return snapshot()[0]
def list_tasks():return snapshot()[1]
def task_dates():return snapshot()[2]

"""Phase 2 batch imports. Resolve operations execute only in internal Lua."""
from __future__ import annotations
import json
import os
import time
import uuid
from datetime import date
from pathlib import Path
from app.core import database, repository as repo
from app.core.naming import final_filename
from app.services import resolve_daily as daily
from app.services.davinci_workflow import _safe_name

BUSY = ('IMPORTING','IMPORT_ERROR','AUTOEDIT_QUEUED','ANALYSIS_ERROR','CUTTING_ERROR','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING','WAITING_USER_REVIEW','FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR')


def ensure_schema():
    with database.connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS davinci_batches (
          batch_id TEXT PRIMARY KEY, work_date TEXT NOT NULL, project_name TEXT NOT NULL,
          timeline_name TEXT NOT NULL, status TEXT NOT NULL, video_count INTEGER NOT NULL,
          batch_start_frame INTEGER, batch_end_frame INTEGER, manifest_path TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          error_message TEXT DEFAULT '', request_id TEXT DEFAULT '', imported_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS davinci_video_state (
          batch_id TEXT NOT NULL, video_id INTEGER NOT NULL, timeline_imported INTEGER DEFAULT 0,
          timeline_start_frame INTEGER, timeline_end_frame INTEGER, source_batch_id TEXT,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(batch_id,video_id));
        ''')


def latest(day):
    ensure_schema()
    with database.connect() as con:
        row=con.execute("SELECT * FROM davinci_batches WHERE work_date=? AND status!='PROJECT_REBUILT' ORDER BY created_at DESC,rowid DESC LIMIT 1",(day,)).fetchone()
        return dict(row) if row else None


def _log(batch_id, detail):
    folder=daily.bridge_root()/'logs'/batch_id
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'import.log').open('a',encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+detail+'\n')
    from app.services.app_paths import data_dir
    app_log=data_dir()/'logs/davinci-workflow.log'
    app_log.parent.mkdir(parents=True,exist_ok=True)
    with app_log.open('a',encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' batch_id='+batch_id+' action=IMPORT_BATCH '+detail+'\n')


def prepare_manifest(day):
    day = date.fromisoformat(day).isoformat()
    queue=[dict(r) for r in repo.list_edit_queue(work_date=day) if r['editing_stage']=='READY_TO_EDIT']
    queue.sort(key=lambda r:(int(r['recipient_id']),int(r['host_id']),int(r['video_seq']),int(r['video_id'])))
    if not queue:return None
    ids=[int(r['video_id']) for r in queue]
    if len(set(ids))!=len(ids):raise ValueError('完整视频身份重复，停止导入。')
    # Eligibility belongs exclusively to the existing repository functions.
    parts=[dict(r) for r in repo.list_edit_source_segments(ids)]
    # 协议硬约束：遗留数据废弃，绝不进入剪辑清单。
    parts=[p for p in parts if int(p['seg_seq'])<1000 and Path(str(p['flow_output_path'] or '')).suffix.lower() in ('.mp4','.mov','.m4v','.webm')]
    grouped={vid:[] for vid in ids}
    seen=set()
    for part in parts:
        sid=int(part['segment_id']);vid=int(part['video_id'])
        if sid in seen or vid not in grouped:raise ValueError('片段身份重复或不属于当前批次。')
        seen.add(sid);grouped[vid].append(part)
    raw=repo.get_setting('edit_root_path','').strip()
    if not raw:raise ValueError('请先在系统设置中设置剪辑路径根目录。')
    root=Path(raw).expanduser().resolve()
    batch_id=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:12]
    values={'action':'IMPORT_BATCH','batch_id':batch_id,'work_date':day,'video_count':len(queue),
            'project_name':'FlowStudio-'+day,'timeline_name':'MAIN-'+day,'group_gap_frames':50}
    with database.connect() as con:
        scripts={int(r['id']):r['chinese_script'] for r in con.execute('SELECT id,chinese_script FROM videos')}
    for index,row in enumerate(queue,1):
        vid=int(row['video_id']);segments=sorted(grouped[vid],key=lambda r:int(r['seg_seq']))
        if not segments or len(segments)!=int(row['segment_count']):
            raise ValueError(f'视频 {vid} 的待剪辑素材已变化，请刷新后再导入。')
        seq=[int(s['seg_seq']) for s in segments]
        if seq!=list(range(1,len(seq)+1)):raise ValueError(f'视频 {vid} 的片段顺序无效。')
        output=root/'Exports'/day/_safe_name(row['recipient_name'])/_safe_name(row['host_name'])
        output.mkdir(parents=True,exist_ok=True)
        probe=output/('.flowstudio-write-'+uuid.uuid4().hex)
        try:probe.write_bytes(b'')
        finally:probe.unlink(missing_ok=True)
        prefix=f'v{index}_'
        values.update({prefix+'id':vid,prefix+'seq':row['video_seq'],prefix+'recipient':row['recipient_name'],
                       prefix+'host':row['host_name'],prefix+'segment_count':len(segments),prefix+'output_dir':str(output),
                       prefix+'final_filename':final_filename(int(row['video_seq']),'ZB',row['recipient_name'],row['host_name'],repo.default_creator(),scripts.get(vid) or '',row['work_date'])})
        for j,segment in enumerate(segments,1):
            path=Path(segment['flow_output_path']).expanduser().resolve()
            if not path.is_file() or not os.access(path,os.R_OK):raise ValueError(f'片段文件不可读：{path}')
            with path.open('rb') as f:
                if not f.read(1):raise ValueError(f'片段文件为空：{path}')
            values[prefix+f's{j}_id']=int(segment['segment_id'])
            values[prefix+f's{j}_path']=str(path)
            from app.services.clip_transform import for_source
            transform=for_source(int(segment['segment_id']),segment['flow_output_path'])
            for key,value in transform.items():values[prefix+f's{j}_transform_'+key]=value
            
        # Attach BROLL_PLAN if available
        import json
        with database.connect() as con:
            broll_row = con.execute("SELECT broll_plan FROM video_enhancement_plans WHERE video_id=?", (vid,)).fetchone()
            if broll_row and broll_row[0]:
                broll_plan = json.loads(broll_row[0] or "[]")
                # Find corresponding QC_PASSED files
                broll_items = []
                for broll in broll_plan:
                    b_id = broll.get("BROLL_ID")
                    if not b_id: continue
                    asset_row = con.execute("SELECT local_path FROM asset_jobs WHERE video_id=? AND job_type IN ('BROLL_VIDEO', 'BROLL_IMAGE') AND job_id=? AND status='READY' ORDER BY id DESC LIMIT 1", (vid, b_id)).fetchone()
                    if asset_row and asset_row[0]:
                        broll["file_path"] = asset_row[0]
                        broll_items.append(broll)
                if broll_items:
                    values[prefix+'broll_plan'] = json.dumps(broll_items, ensure_ascii=False)
                    
    for key,val in values.items():
        if any(c in str(val) for c in '\r\n\x00'):raise ValueError(f'参数含非法换行：{key}')
    return values


def submit(day):
    day = date.fromisoformat(day).isoformat()
    ensure_schema();daily.reconcile_rebuilt_timeline(day);sync_results()
    st=daily.snapshot()
    if not st.get('alive') or 'IMPORT_BATCH' not in st.get('capabilities','').split(','):
        raise ValueError('请先安装本版 Bridge 并唤醒达芬奇。')
    if st.get('stage') not in ('READY','ERROR','WAITING_USER_REVIEW') or st.get('project')!='FlowStudio-'+day or st.get('timeline')!='MAIN-'+day:
        raise ValueError('请先唤醒当天项目和主时间线，或等待当前操作结束。')
    with database.connect() as con:
        active=con.execute('SELECT * FROM davinci_batches WHERE work_date=? AND status IN (%s) ORDER BY rowid DESC LIMIT 1'%','.join('?'*len(BUSY)),(day,*BUSY)).fetchone()
    if active:
        if active['status']!='IMPORT_ERROR' or active['work_date']!=day:
            raise ValueError('当前批次尚未结束，不能导入新批次。')
        manifest=Path(active['manifest_path']);values=daily.read_pairs(manifest)
        if not values:raise ValueError('原批次清单丢失，停止重试。')
        batch_id=active['batch_id']
    else:
        values=prepare_manifest(day)
        if not values:return {'submitted':False,'detail':'当前没有待剪辑的完整视频。'}
        batch_id=values['batch_id']
        manifest=daily.bridge_root()/'v0_5_0/batches'/batch_id/'manifest.ini'
        daily.atomic_pairs(manifest,values)
        with database.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM davinci_batches WHERE work_date=? AND status IN (%s)'%','.join('?'*len(BUSY)),(day,*BUSY)).fetchone():
                raise ValueError('另一个批次已开始，请等待完成。')
            con.execute('INSERT INTO davinci_batches(batch_id,work_date,project_name,timeline_name,status,video_count,manifest_path) VALUES(?,?,?,?,?,?,?)',
                        (batch_id,day,values['project_name'],values['timeline_name'],'IMPORTING',int(values['video_count']),str(manifest)))
            con.executemany('INSERT INTO davinci_video_state(batch_id,video_id) VALUES(?,?)',[(batch_id,int(values[f'v{i}_id'])) for i in range(1,int(values['video_count'])+1)])
    request_id=uuid.uuid4().hex
    job=daily.bridge_root()/'v0_5_0/commands'/(request_id+'.job')
    with database.connect() as con:
        con.execute("UPDATE davinci_batches SET status='IMPORTING',error_message='',request_id=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(request_id,batch_id))
    _log(batch_id,f'准备提交 request={request_id} videos={values["video_count"]}')
    try:
        daily.atomic_pairs(job,{'action':'IMPORT_BATCH','request_id':request_id,'batch_id':batch_id,'manifest_path':str(manifest),'work_date':day})
    except Exception as exc:
        with database.connect() as con:con.execute("UPDATE davinci_batches SET status='IMPORT_ERROR',error_message=? WHERE batch_id=?",(str(exc),batch_id))
        raise
    _log(batch_id,f'已提交 request={request_id} videos={values["video_count"]}')
    return {'submitted':True,'batch_id':batch_id,'detail':f'正在导入 {values["video_count"]} 个完整视频'}


def sync_results():
    ensure_schema()
    with database.connect() as con:
        batches=[dict(r) for r in con.execute("SELECT * FROM davinci_batches WHERE status IN ('IMPORTING','IMPORT_ERROR')")]
    st=daily.snapshot()
    for batch in batches:
        bid=batch['batch_id'];folder=daily.bridge_root()/'v0_5_0/batches'/bid
        result=daily.read_pairs(folder/'result.ini')
        if result.get('batch_id')==bid and result.get('status')=='IMPORTED':
            count=int(batch['video_count'])
            if int(result.get('video_count',-1))!=count or int(result['imported_count'])+int(result['skipped_count'])!=count:
                raise ValueError('导入回执视频数量不匹配')
            # Validate all identities before changing any business status.
            manifest=daily.read_pairs(Path(batch['manifest_path']))
            rows=[]
            for i in range(1,count+1):
                prefix=f'v{i}_';vid=int(manifest[prefix+'id'])
                if result.get(prefix+'id')!=str(vid):raise ValueError('导入回执身份不匹配')
                start,end=int(result[prefix+'start']),int(result[prefix+'end'])
                if end<=start:raise ValueError('导入回执范围无效')
                rows.append((start,end,result.get(prefix+'source_batch',bid),bid,vid))
            with database.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                con.executemany('UPDATE davinci_video_state SET timeline_imported=1,timeline_start_frame=?,timeline_end_frame=?,source_batch_id=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=? AND video_id=?',rows)
                con.executemany("UPDATE videos SET edit_status='已导入DaVinci' WHERE id=?",[(r[-1],) for r in rows])
                con.execute("UPDATE davinci_batches SET status='IMPORTED',batch_start_frame=?,batch_end_frame=?,imported_count=?,skipped_count=?,error_message='',updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(int(result['batch_start_frame']),int(result['batch_end_frame']),int(result['imported_count']),int(result['skipped_count']),bid))
            if int(result['imported_count'])>0:
                repo.set_setting('active_batch_id',bid)
            _log(bid,'已核对导入回执并同步数据库')
        elif st.get('batch_id')==bid and st.get('request_id')==batch['request_id'] and st.get('stage')=='ERROR':
            with database.connect() as con:con.execute("UPDATE davinci_batches SET status='IMPORT_ERROR',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(st.get('detail','导入失败'),bid))
        elif not st.get('alive') and batch['status']=='IMPORTING':
            # Keep the batch frozen; next click retries the exact manifest, never a new batch.
            with database.connect() as con:con.execute("UPDATE davinci_batches SET status='IMPORT_ERROR',error_message='Bridge 连接中断；保留原批次，重新唤醒后可重试' WHERE batch_id=?",(bid,))

"""Third-stage batch preparation and recovery. Resolve remains internal Lua."""
import json
import os
import re
import sys
import uuid
from datetime import date
from pathlib import Path
from app.core import database,repository as repo
from app.services import resolve_daily as daily,resolve_batches as batches

ACTIVE=('AUTOEDIT_QUEUED','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING','WAITING_USER_REVIEW','ANALYSIS_ERROR','CUTTING_ERROR','FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR')


def ensure_schema():
    batches.ensure_schema()
    with database.connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS davinci_autoedit_runs (
          batch_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, status TEXT NOT NULL,
          payload_path TEXT NOT NULL, current INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
          error_message TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        columns={r[1] for r in con.execute('PRAGMA table_info(davinci_video_state)')}
        for column,kind in (('autoedit_status',"TEXT DEFAULT ''"),('whisper_status',"TEXT DEFAULT ''"),('match_score','REAL'),('candidate_count','INTEGER DEFAULT 0')):
            if column not in columns:con.execute(f'ALTER TABLE davinci_video_state ADD COLUMN {column} {kind}')


def current(day):
    ensure_schema()
    with database.connect() as con:
        row=con.execute('SELECT b.* FROM davinci_batches b JOIN davinci_autoedit_runs a ON a.batch_id=b.batch_id WHERE b.work_date=? AND b.status IN (%s) ORDER BY b.rowid DESC LIMIT 1'%','.join('?'*len(ACTIVE)),(day,*ACTIVE)).fetchone()
        if not row:
            preferred=repo.get_setting('active_batch_id','')
            row=con.execute("SELECT * FROM davinci_batches WHERE work_date=? AND status='IMPORTED' AND imported_count>0 ORDER BY (batch_id=?) DESC,rowid DESC LIMIT 1",(day,preferred)).fetchone()
        return dict(row) if row else None


def _atomic_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def verify_autoedit_install():
    name = 'Autoediting_V1.7_FlowStudio.lua'
    source = daily.BASE / 'davinci_autoedit_v0_5_0' / name
    installed = daily.script_dir() / name
    if not source.is_file() or not installed.is_file() or source.read_bytes() != installed.read_bytes():
        raise ValueError('DaVinci 自动剪辑脚本与当前 Studio 版本不一致。请先停止 Bridge（或重启 DaVinci），在当前版本点击“安装/更新新版 Bridge”，再唤醒 DaVinci。')


def submit(day, reanalyze=False):
    day = date.fromisoformat(day).isoformat()
    ensure_schema();daily.reconcile_rebuilt_timeline(day);sync()
    batch=current(day)
    if reanalyze:
        if not batch or batch['status']!='WAITING_USER_REVIEW':
            raise ValueError('只有已经完成一次自动剪辑、当前处于“等待人工检查”的批次才能重新识别。')
    else:
        if batch and batch['status']=='CUTTING_ERROR':
            return resume_cutting(day,batch)
        if not batch or batch['status'] not in ('IMPORTED','ANALYSIS_ERROR'):
            raise ValueError('没有可开始分析的已导入批次，或当前批次正在处理/等待人工检查。')
    state=daily.snapshot()
    if not state.get('alive') or 'START_AUTOEDIT' not in state.get('capabilities','').split(','):
        raise ValueError('请先安装第三阶段Bridge并唤醒达芬奇。')
    allowed_stages=('READY','ERROR','WAITING_USER_REVIEW') if reanalyze else ('READY','ERROR')
    if state.get('stage') not in allowed_stages or state.get('project')!='FlowStudio-'+day or state.get('timeline')!='MAIN-'+day:
        raise ValueError('请先唤醒当天主时间线。')
    verify_autoedit_install()
    from app.services.whisper_cpp import resolve_paths
    found=resolve_paths();cli,model=found['cli'],found['model']
    if not cli:raise ValueError('请在组件管理中填写可执行的 whisper.cpp 命令路径，或点击“检测 / 安装 whisper.cpp”。')
    if not model:raise ValueError('请在组件管理中填写 whisper.cpp 模型路径，或点击“检测 / 安装 whisper.cpp”。')
    runner=daily.BASE/'scripts/run_batch_whisper.py'
    if not runner.is_file():raise ValueError('Whisper运行模块缺失，请重新解压完整版本。')
    bid=batch['batch_id'];attempt=uuid.uuid4().hex
    folder=daily.bridge_root()/'v0_5_0/batches'/bid/'autoedit'/attempt
    original=daily.read_pairs(Path(batch['manifest_path']))
    with database.connect() as con:
        selected={r['video_id']:dict(r) for r in con.execute('SELECT * FROM davinci_video_state WHERE batch_id=? AND source_batch_id=? AND timeline_imported=1',(bid,bid))}
        imported={r['video_id']:dict(r) for r in con.execute('SELECT * FROM davinci_video_state WHERE batch_id=?',(bid,))}
        segments=[dict(r) for r in con.execute("SELECT id,video_id,seg_seq,foreign_text,flow_output_path FROM flow_segments WHERE NOT (seg_seq>=1000 AND foreign_text LIKE '[LEGACY_AUX]%') ORDER BY video_id,seg_seq")]
    expected_ids={int(original[f'v{i}_id']) for i in range(1,int(original['video_count'])+1)}
    if any(vid not in imported or not imported[vid]['timeline_imported'] for vid in expected_ids):
        raise ValueError('TIMELINE_CLIP_COUNT_MISMATCH: 当前任务有视频尚未完整导入，禁止导出部分音频。')
    if not selected:raise ValueError('当前批次没有新导入视频可分析。')

    payload={'batch_id':bid,'attempt_id':attempt,'task_id':attempt,'work_date':day,'project_name':batch['project_name'],'timeline_name':batch['timeline_name'],
             'whisper_cli_path':str(Path(cli).expanduser().resolve()),'whisper_model_path':str(Path(model).expanduser().resolve()),'whisper_language':str(repo.get_setting('whisper_language', 'sw')).split(' · ')[-1].strip(),
             'python_path':sys.executable,'whisper_runner':str(runner),'whisper_timeout':600,'wav_preset':'FlowStudio_WAV16',
             'reanalyze':'true' if reanalyze else 'false'}
    entries=[]
    for i in range(1,int(original['video_count'])+1):
        old=f'v{i}_';vid=int(original[old+'id'])
        if vid not in selected:continue
        parts=[r for r in segments if r['video_id']==vid]
        expected=[int(original[old+f's{j}_id']) for j in range(1,int(original[old+'segment_count'])+1)]
        if [r['id'] for r in parts]!=expected:raise ValueError(f'视频 {vid} 的片段身份已变化，不能用旧时间线继续分析。')
        text=[];task_parts=[]
        for j,part in enumerate(parts,1):
            source_path=Path(part['flow_output_path']).expanduser().resolve().as_posix() if os.name == 'nt' else str(Path(part['flow_output_path']).expanduser().resolve())
            if source_path!=original[old+f's{j}_path']:
                raise ValueError(f'视频 {vid} 的素材版本已变化，请先核对时间线。')
            spoken=(part['foreign_text'] or '').strip()
            if not spoken or re.search('[\u4e00-\u9fff]',spoken):raise ValueError(f'视频 {vid} 片段 {j} 缺少纯斯瓦西里语口播文案。')
            text.append(spoken)
            task_parts.append({'segment_id':int(part['id']),'sequence':int(part['seg_seq']),'source_path':source_path,'script':spoken})
        manuscript='\n'.join(text)
        if len(manuscript.split())<3:raise ValueError(f'视频 {vid} 的文案太短，无法安全对齐。')
        entries.append({'id':vid,'old':old,'manuscript':manuscript,'parts':task_parts,
                        'start':int(selected[vid]['timeline_start_frame']),'end':int(selected[vid]['timeline_end_frame'])})
    if len(entries)!=len(selected):raise ValueError('批次身份清单不完整。')
    if not entries:raise ValueError('当前批次没有可分析的完整视频。')

    payload['video_count']=len(entries)
    payload['expected_complete_video_count']=len(entries)
    payload['batch_start']=min(e['start'] for e in entries)
    payload['batch_end']=max(e['end'] for e in entries)
    payload['task_json_path']=str(folder/'task.json')
    payload['timeline_wav_path']=str(folder/'audio/timeline.wav')
    payload['timeline_whisper_base']=str(folder/'whisper/timeline')

    (folder/'manuscripts').mkdir(parents=True,exist_ok=True)
    task_videos=[]
    for index,entry in enumerate(entries,1):
        vid,old,manuscript=entry['id'],entry['old'],entry['manuscript']
        p=f'v{index}_';target=folder/'manuscripts'/f'video_{vid}.txt'
        target.write_text(manuscript,encoding='utf-8')
        payload.update({p+'id':vid,p+'manuscript_path':str(target),p+'start':entry['start'],p+'end':entry['end'],
                        p+'final_filename':original[old+'final_filename'],p+'output_dir':original[old+'output_dir']})
        task_videos.append({'index':index,'video_id':vid,'recipient':original.get(old+'recipient',''),'anchor':original.get(old+'host',''),
                            'timeline_start_frame':entry['start'],'timeline_end_frame':entry['end'],'script':manuscript,
                            'script_source':'Flow Studio / flow_segments.foreign_text','manuscript_path':str(target),
                            'final_filename':original[old+'final_filename'],'output_dir':original[old+'output_dir'],'segments':entry['parts']})

    task={'schema_version':1,'task_id':attempt,'batch_id':bid,'work_date':day,'project_name':batch['project_name'],'timeline_name':batch['timeline_name'],
          'language':'sw','wav_preset':'FlowStudio_WAV16','work_dir':str(folder),'timeline_wav_path':payload['timeline_wav_path'],
          'timeline_whisper_base':payload['timeline_whisper_base'],'expected_complete_video_count':len(entries),
          'batch_start_frame':payload['batch_start'],'batch_end_frame':payload['batch_end'],'text_authority':'Flow Studio','videos':task_videos}
    _atomic_json(Path(payload['task_json_path']),task)

    file=folder/'autoedit.ini';daily.atomic_pairs(file,payload)
    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        competing=con.execute('SELECT batch_id FROM davinci_batches WHERE work_date=? AND status IN (%s) AND batch_id<>?'%','.join('?'*len(batches.BUSY)),(day,*batches.BUSY,bid)).fetchone()
        if competing:raise ValueError('其他批次尚未结束，不能开始自动剪辑。')
        allowed_statuses=('WAITING_USER_REVIEW',) if reanalyze else ('IMPORTED','ANALYSIS_ERROR')
        placeholders=','.join('?'*len(allowed_statuses))
        changed=con.execute(f"UPDATE davinci_batches SET status='AUTOEDIT_QUEUED',request_id=?,error_message='' WHERE batch_id=? AND status IN ({placeholders})",(attempt,bid,*allowed_statuses)).rowcount
        if changed!=1:raise ValueError('当前批次状态已变化，请刷新。')
        con.execute("INSERT INTO davinci_autoedit_runs(batch_id,attempt_id,status,payload_path,total) VALUES(?,?,'AUTOEDIT_QUEUED',?,?) ON CONFLICT(batch_id) DO UPDATE SET attempt_id=excluded.attempt_id,status=excluded.status,payload_path=excluded.payload_path,current=0,total=excluded.total,error_message=''",(bid,attempt,str(file),len(entries)))
    try:daily.atomic_pairs(daily.bridge_root()/'v0_5_0/commands'/(attempt+'.job'),{'action':'START_AUTOEDIT','batch_id':bid,'request_id':attempt,'task_id':attempt,'payload_path':str(file),'work_date':day})
    except Exception as exc:
        with database.connect() as con:
            con.execute("UPDATE davinci_batches SET status='ANALYSIS_ERROR',error_message=? WHERE batch_id=?",(str(exc),bid))
            con.execute("UPDATE davinci_autoedit_runs SET status='ANALYSIS_ERROR',error_message=? WHERE batch_id=?",(str(exc),bid))
        raise
    detail=(f'已重新识别 {len(entries)} 个完整视频；保留当前已有切点，清除旧红/橙自动标记并重新扫描现有 V1 小片段。' if reanalyze
            else f'已开始分析 {len(entries)} 个完整视频，语言 sw；Studio 文案已绑定任务 {attempt[:8]}')
    return {'submitted':True,'batch_id':bid,'task_id':attempt,'task_json_path':str(folder/'task.json'),'detail':detail}


def reanalyze(day):
    return submit(day, reanalyze=True)


def resume_cutting(day,batch):
    state=daily.snapshot()
    if (not state.get('alive') or 'RESUME_AUTOEDIT' not in state.get('capabilities','').split(',')
        or state.get('stage') not in ('READY','ERROR') or state.get('project')!='FlowStudio-'+day
        or state.get('timeline')!='MAIN-'+day):
        raise ValueError('请先安装本版 Bridge，并唤醒对应日期的时间线，再继续未完成切刀。')
    verify_autoedit_install()
    with database.connect() as con:
        row=con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?',(batch['batch_id'],)).fetchone()
        if not row:raise ValueError('缺少原切刀任务记录。')
        row=dict(row)
    payload=Path(row['payload_path']);plan=daily.read_pairs(payload.parent/'cut_plan.ini')
    attempt=row['attempt_id'];bid=batch['batch_id']
    if plan.get('task_id')!=attempt or plan.get('batch_id')!=bid or plan.get('attempt_id')!=attempt:
        raise ValueError('切点计划与当前中断任务不一致，保留现场。')
    lock=daily.read_pairs(daily.bridge_root()/'pipeline.lock')
    if lock.get('attempt_id')!=attempt or lock.get('batch_id')!=bid or lock.get('stage')!='CUTTING_ERROR':
        raise ValueError('当前任务未处于可继续的切刀中断状态。')
    # Use a fresh queue filename, retaining the original attempt and cut plan.
    inbox=daily.bridge_root()/'v0_5_0/commands'
    for pending in inbox.glob('*.job'):
        queued=daily.read_pairs(pending)
        if queued.get('request_id')==attempt and queued.get('resume')=='true':
            raise ValueError('继续切刀请求已提交，请等待当前操作。')
    command=inbox/(uuid.uuid4().hex+'.job')
    daily.atomic_pairs(command,{'action':'START_AUTOEDIT','request_id':attempt,'task_id':attempt,
                               'batch_id':bid,'work_date':day,'payload_path':str(payload),'resume':'true'})
    return {'submitted':True,'batch_id':bid,'task_id':attempt,'detail':'已提交继续未完成切刀；先核对原素材及位置，跳过已完成切点，不重新分析。'}


def sync():
    ensure_schema()
    with database.connect() as con:rows=[dict(r) for r in con.execute("SELECT * FROM davinci_autoedit_runs WHERE status NOT IN ('COMPLETED','PROJECT_REBUILT')")]
    live=daily.snapshot()
    for row in rows:
        if row['status'] in ('FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR'):continue
        path=Path(row['payload_path']).parent/'state.ini'
        state=daily.read_pairs(path)
        status=state.get('stage') if state.get('attempt_id')==row['attempt_id'] else None
        if status not in ACTIVE:status=None
        if status and live.get('stage')=='OFFLINE' and status not in ('WAITING_USER_REVIEW','ANALYSIS_ERROR','CUTTING_ERROR','FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR'):
            status='CUTTING_ERROR' if status=='CUTTING' else 'ANALYSIS_ERROR'
            state['detail']='连接中断；保留分析及切刀日志。切刀阶段中断不能自动重跑。'
        if not status and live.get('request_id')==row['attempt_id'] and live.get('stage')=='ERROR':
            status='ANALYSIS_ERROR';state={'detail':live.get('detail','启动失败')}
        if row['status']=='CUTTING_ERROR' and status!='WAITING_USER_REVIEW' and not (state.get('resume')=='true' and status=='CUTTING'):
            status='CUTTING_ERROR';state['detail']=row['error_message']
        if not status:continue
        with database.connect() as con:
            con.execute('UPDATE davinci_autoedit_runs SET status=?,current=?,error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',(status,int(state.get('current',0)),state.get('detail',''),row['batch_id']))
            con.execute('UPDATE davinci_batches SET status=?,error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',(status,state.get('detail','') if status.endswith('ERROR') else '',row['batch_id']))
            payload=daily.read_pairs(Path(row['payload_path']))
            for i in range(1,int(payload.get('video_count',0))+1):
                vid=int(payload[f'v{i}_id']);analysis=daily.read_pairs(Path(row['payload_path']).parent/f'video_{vid}_alignment.ini')
                con.execute('UPDATE davinci_video_state SET autoedit_status=?,whisper_status=?,match_score=?,candidate_count=? WHERE batch_id=? AND video_id=?',
                            (status,'DONE' if analysis else '',float(analysis['confidence']) if analysis.get('confidence') else None,int(analysis.get('candidate_count',0)),row['batch_id'],vid))
                if status=='WAITING_USER_REVIEW':con.execute("UPDATE videos SET edit_status='待人工检查' WHERE id=?",(vid,))

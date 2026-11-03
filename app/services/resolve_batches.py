"""Phase 2 batch imports. Resolve operations execute only in internal Lua."""
from __future__ import annotations
import json
import os
import re
import time
import uuid
from datetime import date
from pathlib import Path
from app.core import database, repository as repo
from app.core.naming import final_filename
from app.services import resolve_daily as daily
from app.services.davinci_workflow import _safe_name

BUSY = ('IMPORTING','IMPORT_ERROR','AUTOEDIT_QUEUED','ANALYSIS_ERROR','CUTTING_ERROR','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING','WAITING_USER_REVIEW','FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR')
IMPORT_BLOCKING = ('IMPORTING','IMPORT_ERROR','AUTOEDIT_QUEUED','CUTTING_ERROR','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING','FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR')
CONSOLIDATABLE = ('IMPORTED','ANALYSIS_ERROR','WAITING_USER_REVIEW')


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
        DROP TRIGGER IF EXISTS protect_completed_video_status;
        CREATE TRIGGER IF NOT EXISTS protect_completed_video_status
        BEFORE UPDATE OF edit_status ON videos
        WHEN OLD.edit_status IN ('已导出', '已剪辑', '已完成')
         AND NEW.edit_status IN ('待剪辑', '等待片段')
        BEGIN
            SELECT RAISE(IGNORE);
        END;
        CREATE TRIGGER IF NOT EXISTS protect_completed_davinci_video_state
        BEFORE DELETE ON davinci_video_state
        WHEN EXISTS (
            SELECT 1 FROM videos v
            WHERE v.id = OLD.video_id
              AND v.edit_status IN ('已导出', '已剪辑', '已完成')
        )
        BEGIN
            SELECT RAISE(IGNORE);
        END;
        CREATE TRIGGER IF NOT EXISTS ignore_bogus_pending_editing_history
        BEFORE INSERT ON editing_history
        WHEN NEW.status = '待处理' AND COALESCE(NEW.job_path, '') = '' AND COALESCE(NEW.output_path, '') = ''
        BEGIN
            SELECT RAISE(IGNORE);
        END;
        ''')


def consolidate_unfinished_batches(day, timeline_name=None):
    """Merge multiple imported unfinished batches of the same (work_date, timeline_name) into one unified batch."""
    if not day:
        return None
    ensure_schema()
    from app.services import resolve_autoedit as auto
    auto.ensure_schema()
    tl_name = str(timeline_name or daily.active_timeline_name(day)).strip()
    with database.connect() as con:
        blocking = con.execute(
            'SELECT 1 FROM davinci_batches WHERE work_date=? AND status IN (%s) LIMIT 1'
            % ','.join('?' * len(IMPORT_BLOCKING)),
            (day, *IMPORT_BLOCKING),
        ).fetchone()
        if blocking:
            return None
        rows = [
            dict(r)
            for r in con.execute(
                'SELECT * FROM davinci_batches WHERE work_date=? AND timeline_name=? AND status IN (%s) ORDER BY rowid ASC'
                % ','.join('?' * len(CONSOLIDATABLE)),
                (day, tl_name, *CONSOLIDATABLE),
            )
        ]
        if not rows:
            return None
        if len(rows) == 1:
            only = rows[0]
            bid = only['batch_id']
            vstates = [
                dict(r)
                for r in con.execute(
                    'SELECT s.*, COALESCE(v.edit_status, "") AS edit_status '
                    'FROM davinci_video_state s JOIN videos v ON v.id=s.video_id '
                    'WHERE s.batch_id=? AND s.timeline_imported=1',
                    (bid,),
                )
            ]
            active_vstates = [
                v for v in vstates if v['edit_status'] not in ('已导出', '已完成', '已放弃')
            ]
            has_unedited = any(
                (v.get('autoedit_status') or '') != 'WAITING_USER_REVIEW'
                or v.get('edit_status') == '已导入DaVinci'
                for v in active_vstates
            )
            if only['status'] == 'WAITING_USER_REVIEW' and has_unedited and active_vstates:
                _snapshot_carried_autoedit(con, [only], Path(only['manifest_path']).parent)
                con.execute('BEGIN IMMEDIATE')
                con.execute(
                    "UPDATE davinci_batches SET status='IMPORTED', error_message='' WHERE batch_id=?",
                    (bid,),
                )
                con.execute('DELETE FROM davinci_autoedit_runs WHERE batch_id=?', (bid,))
            return bid

        target = rows[-1]
        target_bid = target['batch_id']
        target_dir = Path(target['manifest_path']).parent
        exported = {
            int(r['id'])
            for r in con.execute(
                "SELECT id FROM videos WHERE edit_status IN ('已导出','已完成','已放弃')"
            )
        }
        v_edit_status = {
            int(r['id']): str(r['edit_status'] or '')
            for r in con.execute('SELECT id, edit_status FROM videos')
        }
        collected_by_vid = {}
        for b in rows:
            bid = b['batch_id']
            mpath = Path(b['manifest_path'])
            m = daily.read_pairs(mpath)
            if not m:
                continue
            vstates = {
                int(r['video_id']): dict(r)
                for r in con.execute(
                    'SELECT * FROM davinci_video_state WHERE batch_id=? AND timeline_imported=1',
                    (bid,),
                )
            }
            vcount = int(m.get('video_count') or 0)
            for i in range(1, vcount + 1):
                pre = f'v{i}_'
                if (pre + 'id') not in m:
                    continue
                vid = int(m[pre + 'id'])
                if vid in exported or vid not in vstates:
                    continue
                fields = {k[len(pre):]: val for k, val in m.items() if k.startswith(pre)}
                collected_by_vid[vid] = {
                    'vid': vid,
                    'fields': fields,
                    'vstate': vstates[vid],
                    'edit_status': v_edit_status.get(vid, ''),
                    'origin_bid': bid,
                }

        if not collected_by_vid:
            return None

        _snapshot_carried_autoedit(con, rows, target_dir)

        collected = sorted(
            collected_by_vid.values(),
            key=lambda x: (int(x['vstate'].get('timeline_start_frame') or 0), int(x['vid'])),
        )
        manifest_values = {
            'action': 'IMPORT_BATCH',
            'batch_id': target_bid,
            'work_date': day,
            'video_count': len(collected),
            'project_name': target['project_name'],
            'timeline_name': target['timeline_name'],
            'group_gap_frames': 50,
        }
        min_start = min(int(x['vstate']['timeline_start_frame']) for x in collected)
        max_end = max(int(x['vstate']['timeline_end_frame']) for x in collected)
        result_values = {
            'batch_id': target_bid,
            'status': 'IMPORTED',
            'video_count': len(collected),
            'imported_count': len(collected),
            'skipped_count': 0,
            'batch_start_frame': min_start,
            'batch_end_frame': max_end,
        }
        for idx, item in enumerate(collected, 1):
            pre = f'v{idx}_'
            for suffix, val in item['fields'].items():
                manifest_values[pre + suffix] = val
            vs = item['vstate']
            result_values[pre + 'id'] = item['vid']
            result_values[pre + 'start'] = int(vs['timeline_start_frame'])
            result_values[pre + 'end'] = int(vs['timeline_end_frame'])
            result_values[pre + 'source_batch'] = target_bid

        daily.atomic_pairs(Path(target['manifest_path']), manifest_values)
        daily.atomic_pairs(target_dir / 'result.ini', result_values)
        _merge_import_logs([b['batch_id'] for b in rows], target_bid)

        has_unedited = any(
            (x['vstate'].get('autoedit_status') or '') != 'WAITING_USER_REVIEW'
            or x.get('edit_status') == '已导入DaVinci'
            for x in collected
        )
        new_status = 'IMPORTED' if has_unedited else 'WAITING_USER_REVIEW'

        all_bids = [b['batch_id'] for b in rows]
        other_bids = [b['batch_id'] for b in rows[:-1]]
        con.execute('BEGIN IMMEDIATE')
        con.execute(
            'DELETE FROM davinci_video_state WHERE batch_id IN (%s)'
            % ','.join('?' * len(all_bids)),
            all_bids,
        )
        for item in collected:
            vs = item['vstate']
            con.execute(
                'INSERT INTO davinci_video_state('
                'batch_id,video_id,timeline_imported,timeline_start_frame,timeline_end_frame,'
                'source_batch_id,autoedit_status,whisper_status,match_score,candidate_count'
                ') VALUES(?,?,1,?,?,?,?,?,?,?)',
                (
                    target_bid,
                    int(item['vid']),
                    int(vs['timeline_start_frame']),
                    int(vs['timeline_end_frame']),
                    target_bid,
                    str(vs.get('autoedit_status') or ''),
                    str(vs.get('whisper_status') or ''),
                    vs.get('match_score'),
                    int(vs.get('candidate_count') or 0),
                ),
            )
        con.execute(
            'UPDATE davinci_batches SET status=?,video_count=?,imported_count=?,skipped_count=0,'
            'batch_start_frame=?,batch_end_frame=?,error_message="",updated_at=CURRENT_TIMESTAMP '
            'WHERE batch_id=?',
            (new_status, len(collected), len(collected), min_start, max_end, target_bid),
        )
        if other_bids:
            ph = ','.join('?' * len(other_bids))
            msg = f'已自动合并至批次 {target_bid}'
            con.execute(
                f"UPDATE davinci_batches SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id IN ({ph})",
                (msg, *other_bids),
            )
            con.execute(
                f"UPDATE davinci_autoedit_runs SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id IN ({ph})",
                (msg, *other_bids),
            )
        if new_status == 'IMPORTED':
            con.execute('DELETE FROM davinci_autoedit_runs WHERE batch_id=?', (target_bid,))
    repo.set_setting('active_batch_id', target_bid)
    return target_bid


def _snapshot_carried_autoedit(con, batch_rows, target_dir: Path):
    """Persist already-completed per-video alignments and candidate cuts across merged batches."""
    carried_file = target_dir / 'carried_autoedit.json'
    carried = {}
    for b in batch_rows:
        bdir = Path(b['manifest_path']).parent
        existing_file = bdir / 'carried_autoedit.json'
        if existing_file.is_file():
            try:
                data = json.loads(existing_file.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    carried.update(data)
            except Exception:
                pass
        run = con.execute(
            'SELECT * FROM davinci_autoedit_runs WHERE batch_id=?', (b['batch_id'],)
        ).fetchone()
        if not run or not run['payload_path']:
            continue
        run_dir = Path(run['payload_path']).parent
        cp_file = run_dir / 'cut_plan.ini'
        cp = daily.read_pairs(cp_file) if cp_file.is_file() else {}
        c_by_vid = {}
        for i in range(1, int(cp.get('candidate_count') or 0) + 1):
            pre = f'c{i}_'
            vid = str(cp.get(pre + 'video_id') or '').strip()
            cs = cp.get(pre + 'start')
            ce = cp.get(pre + 'end')
            ck = cp.get(pre + 'type')
            if vid and cs and ce and ck in ('HEAD', 'TAIL'):
                c_by_vid.setdefault(vid, []).append(
                    {'start': int(cs), 'end': int(ce), 'type': ck}
                )
        for align_path in run_dir.glob('video_*_alignment.ini'):
            al = daily.read_pairs(align_path)
            vid = str(al.get('video_id') or '').strip()
            if vid and al.get('status') == 'COMPLETE':
                carried[vid] = {
                    'video_id': vid,
                    'alignment': al,
                    'candidates': c_by_vid.get(vid, []),
                }
    if carried:
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp = carried_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(carried, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(carried_file)


def _merge_import_logs(batch_ids, target_bid):
    root = daily.bridge_root() / 'logs'
    target_log = root / target_bid / 'import.log'
    target_log.parent.mkdir(parents=True, exist_ok=True)
    seen_actual = set()
    merged_lines = []
    for bid in batch_ids:
        p = root / bid / 'import.log'
        if not p.is_file():
            continue
        for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            if 'ACTUAL video_id=' in line:
                key = line.split('ACTUAL ', 1)[-1].strip()
                if key in seen_actual:
                    continue
                seen_actual.add(key)
            merged_lines.append(line)
    if merged_lines:
        target_log.write_text('\n'.join(merged_lines) + '\n', encoding='utf-8')


def latest(day, timeline_name=None):
    ensure_schema()
    tl_name = str(timeline_name or daily.active_timeline_name(day)).strip()
    consolidate_unfinished_batches(day, timeline_name=tl_name)
    with database.connect() as con:
        row=con.execute(
            "SELECT * FROM davinci_batches WHERE work_date=? AND timeline_name=? AND status!='PROJECT_REBUILT' ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (day, tl_name),
        ).fetchone()
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


def prepare_manifest(day, timeline_name=None):
    day = date.fromisoformat(day).isoformat()
    tl_name = str(timeline_name or daily.active_timeline_name(day)).strip()
    if not daily.is_valid_day_timeline(day, tl_name):
        tl_name = daily.active_timeline_name(day)
    queue=[dict(r) for r in repo.list_edit_queue(work_date=day) if r['editing_stage']=='READY_TO_EDIT']
    queue.sort(key=lambda r:(int(r['recipient_id']),int(r['host_id']),int(r['video_seq']),int(r['video_id'])))
    # One-off custom tasks are imported on their own, never mixed with the normal queue.
    from app.services import custom_task
    _custom=custom_task.custom_ids()
    if any(int(r['video_id']) in _custom for r in queue):
        queue=[r for r in queue if int(r['video_id']) in _custom]
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
            'project_name':'FlowStudio-'+day,'timeline_name':tl_name,'group_gap_frames':50}
    with database.connect() as con:
        scripts={int(r['id']):r['chinese_script'] for r in con.execute('SELECT id,chinese_script FROM videos')}
    from app.services import custom_task
    from app.core.naming import safe_piece
    c_names = custom_task.custom_names()
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
        cname = c_names.get(vid, '').strip()
        if cname:
            clean_cn = safe_piece(cname)
            # If user's custom name already starts with digits or contains numbering, or if we prefix index:
            if re.match(r'^\d+', clean_cn):
                fn = f"{clean_cn}.mp4"
            else:
                fn = f"{index:02d}-{clean_cn}.mp4"
        else:
            fn = final_filename(int(row['video_seq']),'ZB',row['recipient_name'],row['host_name'],repo.default_creator(),scripts.get(vid) or '',row['work_date'])
        exp_w, exp_h, exp_ar = daily.resolve_video_export_size(
            host_id=row.get('host_id'),
            seg_paths=[s['flow_output_path'] for s in segments],
            work_date=day,
        )
        values.update({prefix+'id':vid,prefix+'seq':row['video_seq'],prefix+'recipient':row['recipient_name'],
                       prefix+'host':row['host_name'],prefix+'segment_count':len(segments),prefix+'output_dir':str(output),
                       prefix+'final_filename':fn,
                       prefix+'aspect_ratio':exp_ar,prefix+'export_width':exp_w,prefix+'export_height':exp_h})
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


def submit(day, timeline_name=None):
    day = date.fromisoformat(day).isoformat()
    tl_name = str(timeline_name or daily.active_timeline_name(day)).strip()
    ensure_schema();daily.reconcile_rebuilt_timeline(day, timeline_name=tl_name);sync_results();consolidate_unfinished_batches(day, timeline_name=tl_name)
    st=daily.snapshot()
    if not st.get('alive') or 'IMPORT_BATCH' not in st.get('capabilities','').split(','):
        raise ValueError('请先安装本版 Bridge 并唤醒达芬奇。')
    if st.get('stage') not in ('READY','ERROR','WAITING_USER_REVIEW') or st.get('project')!='FlowStudio-'+day or st.get('timeline')!=tl_name:
        raise ValueError(f'达芬奇当前未切换到时间线「{tl_name}」，请先点击「唤醒达芬奇」打开对应时间线，或等待当前操作结束。')
    with database.connect() as con:
        active=con.execute('SELECT * FROM davinci_batches WHERE work_date=? AND status IN (%s) ORDER BY rowid DESC LIMIT 1'%','.join('?'*len(IMPORT_BLOCKING)),(day,*IMPORT_BLOCKING)).fetchone()
    if active:
        if active['status']!='IMPORT_ERROR' or active['work_date']!=day or active['timeline_name']!=tl_name:
            raise ValueError('当前批次正在执行中，请等待当前操作完成后再导入新批次。')
        manifest=Path(active['manifest_path']);values=daily.read_pairs(manifest)
        if not values:raise ValueError('原批次清单丢失，停止重试。')
        batch_id=active['batch_id']
    else:
        values=prepare_manifest(day, timeline_name=tl_name)
        if not values:
            consolidate_unfinished_batches(day, timeline_name=tl_name)
            return {'submitted':False,'detail':'当前没有新的待剪辑完整视频；已导入时间线的视频可直接点击“开始运行自动剪辑”。'}
        batch_id=values['batch_id']
        manifest=daily.bridge_root()/'v0_5_0/batches'/batch_id/'manifest.ini'
        daily.atomic_pairs(manifest,values)
        with database.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM davinci_batches WHERE work_date=? AND status IN (%s)'%','.join('?'*len(IMPORT_BLOCKING)),(day,*IMPORT_BLOCKING)).fetchone():
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
            consolidate_unfinished_batches(batch['work_date'], timeline_name=batch['timeline_name'])
        elif st.get('batch_id')==bid and st.get('request_id')==batch['request_id'] and st.get('stage')=='ERROR':
            with database.connect() as con:con.execute("UPDATE davinci_batches SET status='IMPORT_ERROR',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(st.get('detail','导入失败'),bid))
        elif batch['status']=='IMPORTING' and (st.get('stage')=='OFFLINE' or daily.heartbeat_age(st) > daily.IMPORT_DISCONNECT_SECONDS):
            # Keep the batch frozen; next click retries the exact manifest, never a new batch.
            with database.connect() as con:con.execute("UPDATE davinci_batches SET status='IMPORT_ERROR',error_message='Bridge 连接中断；保留原批次，重新唤醒后可重试' WHERE batch_id=?",(bid,))

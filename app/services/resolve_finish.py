"""Durable finish handoff; only an explicitly recoverable post-delete Ripple verification error may resume."""
from pathlib import Path
import time
import uuid
from app.core import database, repository as repo
from app.core.naming import resolve_export_filename
from app.services import resolve_daily as daily, resolve_autoedit as auto

STATES=('FINISH_QUEUED','CLEANING','CLEANING_ERROR','CLEANED_READY','PREPARING_EXPORT','RENDERING','EXPORT_ERROR','COMPLETED')
FINISH_MODES=('cleanup_only','watermark_only','export','cleanup')

def sync():
    try:
        from app.services import reexport
        reexport.sync()
    except Exception:
        pass
    auto.ensure_schema()
    with database.connect() as con:
        rows=[dict(r) for r in con.execute("SELECT a.*,b.work_date FROM davinci_autoedit_runs a JOIN davinci_batches b USING(batch_id) WHERE a.status NOT IN ('COMPLETED','PROJECT_REBUILT') AND b.status NOT IN ('COMPLETED','SKIPPED','PROJECT_REBUILT')")]
    for row in rows:
        base=Path(row['payload_path']).parent
        state=daily.read_pairs(base/'finish.ini')
        if state.get('batch_id')!=row['batch_id'] or state.get('attempt_id')!=row['attempt_id']:continue
        status=state.get('stage')
        # FINISH_BATCH may intentionally return WAITING_USER_REVIEW when one or more
        # complete videos no longer exist on V1 (for example, the user deleted them
        # for quality reasons). Those videos stay in Studio QC, but they must not keep
        # the Resolve batch open or block importing the next batch.
        review_return = status == 'WAITING_USER_REVIEW'
        if status not in STATES and not review_return:continue
        if status == 'CLEANED_READY':
            note = state.get('detail', '') or '已完成清理与水印挂载，请检查后点击「批量导出」'
            with database.connect() as con:
                con.execute(
                    "UPDATE davinci_batches SET status='WAITING_USER_REVIEW',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                    (note, row['batch_id']),
                )
                con.execute(
                    "UPDATE davinci_autoedit_runs SET status='WAITING_USER_REVIEW',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                    (note, row['batch_id']),
                )
            continue
        payload=daily.read_pairs(Path(row['payload_path']))
        exported_ids=[]
        video_ids=[]
        with database.connect() as con:
            for i in range(1,int(payload['video_count'])+1):
                vid=int(payload[f'v{i}_id']);video_ids.append(vid);out=daily.read_pairs(base/f'export_{vid}.ini')
                if out.get('status')=='COMPLETE' and out.get('video_id')==str(vid):
                    path=Path(out.get('output_path',''))
                    expected=Path(payload[f'v{i}_output_dir'])/resolve_export_filename(payload[f'v{i}_final_filename'])
                    if expected.suffix.lower()!='.mp4':expected=expected.with_name(expected.name+'.mp4')
                    if path.resolve()==expected.resolve() and path.is_file() and path.stat().st_size:
                        con.execute("UPDATE videos SET edit_status='已导出',edit_output_path=? WHERE id=?",(str(path),vid));exported_ids.append(vid)
            if review_return:
                placeholders=','.join('?'*len(video_ids))
                remaining=con.execute(
                    f"SELECT COUNT(*) FROM videos WHERE id IN ({placeholders}) AND edit_status NOT IN ('已导出','已完成')",
                    video_ids
                ).fetchone()[0] if video_ids else 0
                detail=state.get('detail','') or f'本批次导出已结束；{remaining} 个缺失视频保留在质检页面。'
                con.execute("UPDATE davinci_batches SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(detail,row['batch_id']))
                con.execute("UPDATE davinci_autoedit_runs SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(detail,row['batch_id']))
                con.execute("UPDATE davinci_video_state SET autoedit_status=CASE WHEN video_id IN (%s) THEN 'COMPLETED' ELSE 'WAITING_USER_REVIEW' END,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?" % (','.join('?'*len(exported_ids)) if exported_ids else '-1'), (*exported_ids,row['batch_id']) if exported_ids else (row['batch_id'],))
            else:
                clean_detail=daily.compact_bridge_detail(state.get('detail',''), max_len=140)
                con.execute('UPDATE davinci_batches SET status=?,error_message=? WHERE batch_id=?',(status,clean_detail,row['batch_id']))
                con.execute('UPDATE davinci_autoedit_runs SET status=?,error_message=? WHERE batch_id=?',(status,clean_detail,row['batch_id']))
        if review_return:
            # Release only this finished batch's Resolve runtime lock/queued commands.
            # The QC video rows themselves are deliberately preserved.
            batch_runtime={'batch_id':row['batch_id'],'work_date':row['work_date']}
            _archive_batch_runtime(batch_runtime,'qc_return')
            if repo.get_setting('active_batch_id','')==row['batch_id']:
                repo.set_setting('active_batch_id','')
    try:
        sync_manual_render()
    except Exception:
        pass

def _ensure_direct_export_run(batch: dict) -> dict:
    """Create a synthetic WAITING_USER_REVIEW autoedit run for an IMPORTED batch so FINISH_BATCH can export directly without running autoedit."""
    import json
    bid = batch['batch_id']
    day = batch['work_date']
    batch_dir = daily.bridge_root() / 'v0_5_0' / 'batches' / bid
    manifest = daily.read_pairs(Path(batch['manifest_path']))
    attempt_id = uuid.uuid4().hex
    attempt_dir = batch_dir / 'autoedit' / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / 'manuscripts').mkdir(parents=True, exist_ok=True)
    task_json = attempt_dir / 'task.json'
    autoedit_ini = attempt_dir / 'autoedit.ini'
    default_lang = str(repo.get_setting('whisper_language', 'sw')).split(' · ')[-1].strip() or 'sw'

    with database.connect() as con:
        vs_map = {
            int(r['video_id']): dict(r)
            for r in con.execute(
                'SELECT * FROM davinci_video_state WHERE batch_id=? AND timeline_imported=1',
                (bid,),
            ).fetchall()
        }
    m_vcount = int(manifest.get('video_count') or 0)
    export_entries = []
    for idx_m in range(1, m_vcount + 1):
        mpre = f'v{idx_m}_'
        mvid = int(manifest.get(mpre + 'id') or 0)
        if mvid not in vs_map:
            continue
        vs_item = vs_map[mvid]
        export_entries.append((mvid, mpre, int(vs_item['timeline_start_frame']), int(vs_item['timeline_end_frame'])))

    ae_payload = {
        'batch_id': bid,
        'attempt_id': attempt_id,
        'task_id': attempt_id,
        'work_date': day,
        'project_name': batch['project_name'],
        'timeline_name': batch['timeline_name'],
        'whisper_language': default_lang,
        'python_path': '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3',
        'task_json_path': str(task_json),
        'video_count': len(export_entries),
        'expected_complete_video_count': len(export_entries),
        'batch_start': min((x[2] for x in export_entries), default=90000),
        'batch_end': max((x[3] for x in export_entries), default=90000),
    }
    for out_idx, (mvid, mpre, s_fr, e_fr) in enumerate(export_entries, 1):
        p_out = f'v{out_idx}_'
        m_txt = attempt_dir / 'manuscripts' / f'video_{mvid}.txt'
        m_txt.write_text('', encoding='utf-8')
        ae_payload[p_out + 'id'] = mvid
        ae_payload[p_out + 'manuscript_path'] = str(m_txt)
        ae_payload[p_out + 'start'] = s_fr
        ae_payload[p_out + 'end'] = e_fr
        ae_payload[p_out + 'final_filename'] = manifest.get(mpre + 'final_filename', f'{out_idx:02d}-video_{mvid}.mp4')
        ae_payload[p_out + 'output_dir'] = manifest.get(mpre + 'output_dir', '')
        ae_payload[p_out + 'no_cut'] = 'true'
        ew = manifest.get(mpre + 'export_width')
        eh = manifest.get(mpre + 'export_height')
        ear = manifest.get(mpre + 'aspect_ratio')
        if not (ew and eh):
            s1 = manifest.get(mpre + 's1_path', '')
            ew, eh, ear = daily.resolve_video_export_size(seg_paths=[s1] if s1 else None, work_date=day)
        ae_payload[p_out + 'export_width'] = int(ew)
        ae_payload[p_out + 'export_height'] = int(eh)
        ae_payload[p_out + 'aspect_ratio'] = ear or ('16:9' if int(ew) > int(eh) else '9:16')

    task_json.write_text(json.dumps({
        'schema_version': 1,
        'task_id': attempt_id,
        'batch_id': bid,
        'work_date': day,
        'project_name': batch['project_name'],
        'timeline_name': batch['timeline_name'],
        'language': default_lang,
        'videos': [],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    daily.atomic_pairs(autoedit_ini, ae_payload)
    daily.atomic_pairs(attempt_dir / 'state.ini', {
        'batch_id': bid,
        'attempt_id': attempt_id,
        'task_id': attempt_id,
        'stage': 'WAITING_USER_REVIEW',
        'detail': '完整视频直通导出（不切刀模式）',
        'current': len(export_entries),
        'total': len(export_entries),
    })
    daily.atomic_pairs(attempt_dir / 'cut_plan.ini', {
        'batch_id': bid,
        'attempt_id': attempt_id,
        'task_id': attempt_id,
        'candidate_count': 0,
        'carried_candidate_count': 0,
        'reanalyze': 'false',
        'deferred_count': 0,
        'deferred_video_ids': '',
        'scope_start': ae_payload['batch_start'],
        'scope_end': ae_payload['batch_end'],
        'scope_rule': 'BATCH_MARKER_TO_TIMELINE_END',
    })
    with database.connect() as con:
        auto.ensure_schema()
        con.execute(
            "UPDATE davinci_batches SET status='WAITING_USER_REVIEW', error_message='', updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
            (bid,),
        )
        con.execute(
            "INSERT INTO davinci_autoedit_runs(batch_id,attempt_id,status,payload_path,current,total,error_message) "
            "VALUES(?,?,'WAITING_USER_REVIEW',?,?,?,'') "
            "ON CONFLICT(batch_id) DO UPDATE SET attempt_id=excluded.attempt_id,status='WAITING_USER_REVIEW',payload_path=excluded.payload_path,current=excluded.current,total=excluded.total,error_message=''",
            (bid, attempt_id, str(autoedit_ini), len(export_entries), len(export_entries)),
        )
        return dict(con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?', (bid,)).fetchone())


def submit(day, finish_mode='cleanup_only'):
    finish_mode = str(finish_mode or 'cleanup_only').strip()
    if finish_mode not in FINISH_MODES:
        raise ValueError(f'不支持的完成操作类型：{finish_mode}')
    sync();batch=auto.current(day)
    if not batch:raise ValueError('当前所选时间线没有可处理的批次。')
    state=daily.snapshot()
    if not state.get('alive') or 'FINISH_BATCH' not in state.get('capabilities','').split(','):
        raise ValueError('请停止旧 Bridge、安装本版 Bridge，然后重新唤醒。')
    if state.get('stage') not in ('READY','WAITING_USER_REVIEW','ERROR','CLEANING_ERROR') or state.get('project')!='FlowStudio-'+day or state.get('timeline')!=batch['timeline_name']:
        raise ValueError(f"达芬奇当前未切换到时间线「{batch['timeline_name']}」，请先点击「唤醒达芬奇」打开对应时间线并等待当前操作结束。")
    with database.connect() as con:
        r_obj = con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?',(batch['batch_id'],)).fetchone()
        row = dict(r_obj) if r_obj else None
    if not row:
        row = _ensure_direct_export_run(batch)
        batch['status'] = 'WAITING_USER_REVIEW'
    base=Path(row['payload_path']).parent
    previous=daily.read_pairs(base/'finish.ini')
    cleanup_started = (base / 'cleanup_intent.ini').exists()
    recoverable_cleanup_error=(
        previous.get('stage')=='CLEANING_ERROR'
        and (not cleanup_started or 'RIPPLE_RANGE_MISMATCH' in previous.get('detail',''))
    )
    if previous.get('stage')=='CLEANING':
        raise ValueError('清理仍在执行或曾在删除动作中断，已保留现场；不能重复提交。')
    if finish_mode in ('cleanup_only', 'cleanup') and previous.get('stage')=='CLEANING_ERROR' and not recoverable_cleanup_error:
        raise ValueError('清理曾中断，已保留现场；当前错误不能安全自动恢复，不能自动再次删除片段。')
    if batch['status'] not in ('IMPORTED','WAITING_USER_REVIEW','CLEANING_ERROR','EXPORT_ERROR','RENDERING','PREPARING_EXPORT'):
        raise ValueError('当前批次不能执行清理、挂载水印或导出。')
    inbox=daily.bridge_root()/'v0_5_0/commands'
    if any(daily.read_pairs(path).get('action')=='FINISH_BATCH' for path in inbox.glob('*.job')):
        raise ValueError('已有清理 / 水印 / 导出请求等待执行，请勿重复提交。')

    wm_plan_path = ''
    if finish_mode in ('cleanup_only', 'watermark_only', 'cleanup'):
        from app.services import ai_watermark
        batch_dir = daily.bridge_root() / 'v0_5_0' / 'batches' / batch['batch_id']
        wm_plan_path = str(ai_watermark.prepare_batch_watermark_plan(batch['batch_id'], batch_dir))

    sub_vids_csv = ''
    if finish_mode in ('export', 'cleanup'):
        from app.services import scripture_subtitles
        ae_pairs = daily.read_pairs(Path(row['payload_path']))
        b_vids = [
            int(ae_pairs[f'v{k}_id'])
            for k in range(1, int(ae_pairs.get('video_count') or 0) + 1)
            if str(ae_pairs.get(f'v{k}_id') or '').isdigit()
        ]
        sub_vids = scripture_subtitles.resolve_batch_subtitle_video_ids(
            batch['batch_id'], attempt_dir=base, video_ids=b_vids or None
        )
        sub_vids_csv = ','.join(str(v) for v in sub_vids)

    request=uuid.uuid4().hex
    job={
        'action':'FINISH_BATCH',
        'request_id':request,
        'batch_id':batch['batch_id'],
        'attempt_id':row['attempt_id'],
        'payload_path':row['payload_path'],
        'work_date':day,
        'finish_mode':finish_mode,
        'subtitle_video_ids':sub_vids_csv,
    }
    if wm_plan_path:
        job['watermark_plan_path'] = wm_plan_path
    # Original analysis attempt identifies durable per-video output receipts.
    daily.atomic_pairs(daily.bridge_root()/'v0_5_0/commands'/(request+'.job'),job)
    if finish_mode == 'cleanup_only':
        detail = '已提交确认清理（自动清理红/蓝标记废片并按主播挂载 AI 水印，暂不导出）'
    elif finish_mode == 'watermark_only':
        detail = '已提交添加 / 刷新 AI 水印（自动替换为最新主播绑定水印）'
    elif finish_mode == 'export':
        detail = '已提交批量导出成品视频'
    else:
        detail = '已提交清理后安全恢复 / 继续导出' if recoverable_cleanup_error else '已提交清理 / 恢复未完成导出'
    return {'submitted':True,'detail':detail,'finish_mode':finish_mode}

_MANUAL_RUNNING_BATCH = {
    'IMPORTING','AUTOEDIT_QUEUED','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING',
    'CUTTING','FINISH_QUEUED','CLEANING','PREPARING_EXPORT','RENDERING',
}
_MANUAL_RUNNING_BRIDGE = {
    'IMPORTING','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING',
    'CLEANING','PREPARING_EXPORT','RENDERING',
}


def _manual_batch(day, timeline_name=None):
    """Return the newest unfinished batch on the active timeline without inventing a new business state."""
    auto.ensure_schema()
    tl_name = str(timeline_name or daily.active_timeline_name(day)).strip()
    with database.connect() as con:
        row=con.execute(
            "SELECT * FROM davinci_batches WHERE work_date=? AND timeline_name=? "
            "AND status NOT IN ('COMPLETED','SKIPPED','PROJECT_REBUILT') "
            "ORDER BY rowid DESC LIMIT 1", (day, tl_name)
        ).fetchone()
    if not row:
        raise ValueError('当前时间线没有可结束或跳过的剪辑批次。')
    return dict(row)


def _manifest_and_ids(batch):
    manifest=daily.read_pairs(Path(batch['manifest_path']))
    if manifest.get('batch_id')!=batch['batch_id'] or manifest.get('work_date')!=batch['work_date']:
        raise ValueError('当前批次清单身份不一致，未执行手动结束。')
    try:
        count=int(manifest.get('video_count','0'))
        ids=[int(manifest[f'v{i}_id']) for i in range(1,count+1)]
    except (ValueError, KeyError):
        raise ValueError('当前批次清单不完整，未执行手动结束。')
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('当前批次视频身份无效，未执行手动结束。')
    return manifest, ids


def _archive_batch_runtime(batch, mode):
    """Archive, rather than delete, this batch's and same-date pending commands and lock."""
    root=daily.bridge_root();bid=batch['batch_id'];day=batch['work_date']
    stamp=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    archive=root/'logs'/bid/f'manual_{mode}_{stamp}'
    archive.mkdir(parents=True,exist_ok=True)

    lock_candidates=[root/'pipeline.lock', root/'v0_5_0'/'suspended'/f'pipeline_{day}.ini']
    for path in lock_candidates:
        if not path.is_file():
            continue
        lock=daily.read_pairs(path)
        lock_day=lock.get('work_date')
        if not lock_day and lock.get('batch_id'):
            m=daily.read_pairs(root/'v0_5_0'/'batches'/lock['batch_id']/'manifest.ini')
            lock_day=m.get('work_date','')
        if lock.get('batch_id')==bid or lock_day==day or not lock_day:
            path.replace(archive/path.name)

    inbox=root/'v0_5_0'/'commands'
    if inbox.is_dir():
        for path in sorted(inbox.glob('*.job')):
            job=daily.read_pairs(path)
            if job.get('batch_id')==bid or job.get('work_date')==day:
                path.replace(archive/('pending_'+path.name))
    return archive


def _existing_output_path(manifest, index, video_id, run):
    """Accept only a real, non-empty file. Never fabricate an exported output path."""
    candidates=[]
    with database.connect() as con:
        row=con.execute('SELECT edit_output_path FROM videos WHERE id=?',(video_id,)).fetchone()
        if row and row[0]: candidates.append(Path(row[0]).expanduser())
    if run:
        receipt=daily.read_pairs(Path(run['payload_path']).parent/f'export_{video_id}.ini')
        if receipt.get('status')=='COMPLETE' and receipt.get('video_id')==str(video_id) and receipt.get('output_path'):
            candidates.append(Path(receipt['output_path']).expanduser())
    prefix=f'v{index}_'
    outdir=manifest.get(prefix+'output_dir','')
    final=manifest.get(prefix+'final_filename','')
    if outdir and final:
        candidates.append(Path(outdir).expanduser()/resolve_export_filename(final))
    seen=set()
    for candidate in candidates:
        try:key=str(candidate.resolve())
        except OSError:key=str(candidate)
        if key in seen:continue
        seen.add(key)
        try:
            if candidate.is_file() and candidate.stat().st_size>0:
                return str(candidate.resolve())
        except OSError:
            pass
    return ''


def manual_close(day, mode):
    """Explicit human escape hatch for a stale/cleared Resolve batch.

    mode='complete': close the batch; verified final files become 已导出, the rest become 已剪辑.
    mode='skip': close the batch and return non-exported videos to 待剪辑.
    No media file, project, timeline, or another date's lock is deleted.
    """
    if mode not in ('complete','skip'):
        raise ValueError('无效的批次处理方式。')
    batch=_manual_batch(day)
    manifest,ids=_manifest_and_ids(batch)
    bid=batch['batch_id']
    with database.connect() as con:
        other_bids=[r[0] for r in con.execute(
            "SELECT batch_id FROM davinci_batches WHERE work_date=? AND timeline_name=? "
            "AND status NOT IN ('COMPLETED','SKIPPED','PROJECT_REBUILT') AND batch_id<>?",
            (day, batch['timeline_name'], bid)
        )]
        run=con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?',(bid,)).fetchone()
        run=dict(run) if run else None
        current={int(r['id']):dict(r) for r in con.execute(
            'SELECT id,edit_status,edit_output_path FROM videos WHERE id IN (%s)'%','.join('?'*len(ids)), ids
        )}
    if len(current)!=len(ids):
        raise ValueError('当前批次视频记录不完整，未执行手动结束。')

    archive=_archive_batch_runtime(batch,mode)
    exported=0;edited=0;requeued=0
    updates=[]
    for index,vid in enumerate(ids,1):
        row=current[vid];status=str(row.get('edit_status') or '')
        if status in ('已导出','已完成'):
            exported+=1
            continue
        if mode=='complete':
            output=_existing_output_path(manifest,index,vid,run)
            if output:
                updates.append(('已导出',output,vid));exported+=1
            else:
                updates.append(('已剪辑',row.get('edit_output_path') or '',vid));edited+=1
        else:
            updates.append(('待剪辑',row.get('edit_output_path') or '',vid));requeued+=1

    if mode=='complete':
        status='COMPLETED'
        detail=f'用户手动确认结束本批次：{exported} 个成品已确认，{edited} 个仅标记为已剪辑。'
        video_state='COMPLETED'
    else:
        status='SKIPPED'
        detail=f'用户手动跳过本批次：{requeued} 个未完成视频已回到待剪辑队列。'
        video_state='SKIPPED'

    all_bids=[bid, *other_bids]
    bid_placeholders=','.join('?'*len(all_bids))
    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if updates:
            con.executemany('UPDATE videos SET edit_status=?,edit_output_path=? WHERE id=?',updates)
            con.executemany(
                "UPDATE editing_history SET status=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=(SELECT MAX(id) FROM editing_history WHERE video_id=?)",
                [(row[0],row[2]) for row in updates]
            )
        con.execute(f'UPDATE davinci_batches SET status=?,error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id IN ({bid_placeholders})',(status,detail,*all_bids))
        # Freeze old state.ini / finish.ini recovery so a stale error cannot resurrect this batch or earlier unfinished batches of the same date.
        con.execute(f"UPDATE davinci_autoedit_runs SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id IN ({bid_placeholders})",(detail,*all_bids))
        con.execute(f'UPDATE davinci_video_state SET autoedit_status=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id IN ({bid_placeholders})',(video_state,*all_bids))

    if repo.get_setting('active_batch_id','') in all_bids:
        repo.set_setting('active_batch_id','')
    daily.atomic_pairs(daily.bridge_root()/'v0_5_0'/'batches'/bid/'manual_close.ini',{
        'batch_id':bid,'work_date':day,'mode':mode,'status':status,'detail':detail,
        'archive_path':str(archive),'closed_at':time.strftime('%Y-%m-%d %H:%M:%S'),
    })
    return {'ok':True,'batch_id':bid,'status':status,'exported':exported,'edited':edited,'requeued':requeued,'detail':detail}


_LAST_MANUAL_RENDER_SIG = None
_LAST_MANUAL_RENDER_RES: dict = {}


def _canon_export_path(raw_path: str) -> str:
    s = str(raw_path or '').strip()
    if not s:
        return ''
    p = Path(s).expanduser()
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def sync_manual_render(root=None, *, force: bool = False) -> dict:
    """Reconcile DaVinci Deliver manual render progress & completed MP4s into studio.db."""
    global _LAST_MANUAL_RENDER_SIG, _LAST_MANUAL_RENDER_RES
    b_root = Path(root) if root else daily.bridge_root()
    mr_path = b_root / 'v0_5_0' / 'manual_render.ini'
    if not mr_path.is_file():
        return {}
    mr = daily.read_pairs(mr_path)
    if not mr:
        return {}

    project_name = str(mr.get('project') or '').strip()
    timeline_name = str(mr.get('timeline') or '').strip()
    raw_active = mr.get('active') == 'true'
    try:
        age = time.time() - float(mr.get('updated_at') or 0)
    except (TypeError, ValueError):
        age = 10 ** 9
    active = bool(raw_active and age <= 35)

    sig = (
        mr.get('updated_at', ''),
        '1' if active else '0',
        mr.get('complete_count', ''),
        mr.get('rendering_count', ''),
        mr.get('queued_count', ''),
        project_name,
        timeline_name,
    )
    if not force and sig == _LAST_MANUAL_RENDER_SIG:
        return dict(_LAST_MANUAL_RENDER_RES)

    completed_job_ids: set[str] = set()
    completed_id_to_path: dict[str, str] = {}
    completed_paths: dict[str, str] = {}
    for i in range(1, int(mr.get('complete_count') or 0) + 1):
        jid = str(mr.get(f'c{i}_job_id') or '').strip()
        cpath = str(mr.get(f'c{i}_path') or '').strip()
        ckey = _canon_export_path(cpath)
        if jid:
            completed_job_ids.add(jid)
            if cpath:
                completed_id_to_path[jid] = cpath
        if ckey:
            completed_paths[ckey] = jid

    rendering_job_ids: set[str] = set()
    rendering_paths: set[str] = set()
    for i in range(1, int(mr.get('rendering_count') or 0) + 1):
        jid = str(mr.get(f'r{i}_job_id') or '').strip()
        rkey = _canon_export_path(mr.get(f'r{i}_path') or '')
        if jid:
            rendering_job_ids.add(jid)
        if rkey:
            rendering_paths.add(rkey)

    queued_job_ids: set[str] = set()
    queued_paths: set[str] = set()
    for i in range(1, int(mr.get('queued_count') or 0) + 1):
        jid = str(mr.get(f'w{i}_job_id') or '').strip()
        wkey = _canon_export_path(mr.get(f'w{i}_path') or '')
        if jid:
            queued_job_ids.add(jid)
        if wkey:
            queued_paths.add(wkey)

    auto.ensure_schema()
    with database.connect() as con:
        b_row = con.execute(
            "SELECT * FROM davinci_batches "
            "WHERE project_name=? AND timeline_name=? AND status NOT IN ('SKIPPED','PROJECT_REBUILT') "
            "ORDER BY CASE WHEN status <> 'COMPLETED' THEN 0 ELSE 1 END, rowid DESC LIMIT 1",
            (project_name, timeline_name),
        ).fetchone()
        run_row = (
            con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?', (b_row['batch_id'],)).fetchone()
            if b_row else None
        )

    reply_path = b_root / 'v0_5_0' / 'manual_render_batch.ini'
    if not b_row:
        res = {
            'batch_id': '',
            'project': project_name,
            'timeline': timeline_name,
            'batch_done': '0',
            'batch_total': '0',
            'newly_exported': '0',
            'exporting': '0',
        }
        daily.atomic_pairs(reply_path, res)
        _LAST_MANUAL_RENDER_SIG = sig
        _LAST_MANUAL_RENDER_RES = dict(res)
        return res

    batch = dict(b_row)
    bid = batch['batch_id']
    run = dict(run_row) if run_row else None
    base = Path(run['payload_path']).parent if (run and run.get('payload_path')) else None
    src_pairs = (
        daily.read_pairs(Path(run['payload_path']))
        if (run and run.get('payload_path') and Path(run['payload_path']).is_file())
        else daily.read_pairs(Path(batch['manifest_path']))
    )
    v_count = int(src_pairs.get('video_count') or 0)
    entries = []
    video_ids = []
    for i in range(1, v_count + 1):
        vid_raw = src_pairs.get(f'v{i}_id')
        if not vid_raw:
            continue
        vid = int(vid_raw)
        outdir = str(src_pairs.get(f'v{i}_output_dir') or '').strip()
        fname = str(src_pairs.get(f'v{i}_final_filename') or '').strip()
        expected = (Path(outdir).expanduser() / resolve_export_filename(fname)) if (outdir and fname) else None
        if expected and expected.suffix.lower() != '.mp4':
            expected = expected.with_name(expected.name + '.mp4')
        exp_key = _canon_export_path(str(expected)) if expected else ''
        r_path = (base / f'export_{vid}.ini') if base else None
        r_data = daily.read_pairs(r_path) if (r_path and r_path.is_file()) else {}
        video_ids.append(vid)
        entries.append((vid, expected, exp_key, r_data, r_path))

    with database.connect() as con:
        cur_videos = (
            {
                int(r['id']): dict(r)
                for r in con.execute(
                    f"SELECT id, edit_status, edit_output_path FROM videos WHERE id IN ({','.join('?' * len(video_ids))})",
                    video_ids,
                ).fetchall()
            }
            if video_ids else {}
        )

    db_updates = []
    exported_ids = []
    batch_done = 0
    newly_exported = 0
    exporting_count = 0

    for vid, expected, exp_key, receipt, r_path in entries:
        cur_v = cur_videos.get(vid)
        if not cur_v:
            continue
        cur_status = str(cur_v.get('edit_status') or '')
        cur_out = str(cur_v.get('edit_output_path') or '')
        rid = str(receipt.get('render_id') or '').strip()

        is_rendering_now = bool(
            active and ((rid and rid in rendering_job_ids) or (exp_key and exp_key in rendering_paths))
        )
        matched_jid = None
        if not is_rendering_now:
            if rid and rid in completed_job_ids:
                matched_jid = rid
            elif exp_key and exp_key in completed_paths:
                matched_jid = completed_paths[exp_key]

        receipt_complete = receipt.get('status') == 'COMPLETE' and receipt.get('video_id') == str(vid)

        if matched_jid is not None or receipt_complete:
            valid_file = None
            cand_list = []
            if matched_jid and completed_id_to_path.get(matched_jid):
                cand_list.append(Path(completed_id_to_path[matched_jid]).expanduser())
            if expected:
                cand_list.append(expected)
            if receipt.get('output_path'):
                cand_list.append(Path(receipt['output_path']).expanduser())
            for cand in cand_list:
                try:
                    if cand.is_file() and cand.stat().st_size > 0:
                        valid_file = cand.resolve()
                        break
                except OSError:
                    pass
            if valid_file is not None:
                if r_path and receipt.get('status') != 'COMPLETE':
                    updated_receipt = dict(receipt)
                    updated_receipt['video_id'] = str(vid)
                    if matched_jid or rid:
                        updated_receipt['render_id'] = matched_jid or rid
                    updated_receipt['status'] = 'COMPLETE'
                    updated_receipt['output_path'] = str(valid_file)
                    daily.atomic_pairs(r_path, updated_receipt)
                if cur_status not in ('已导出', '已完成') or cur_out != str(valid_file):
                    db_updates.append(('已导出', str(valid_file), vid))
                    if cur_status not in ('已导出', '已完成'):
                        newly_exported += 1
                batch_done += 1
                exported_ids.append(vid)
                continue

        if cur_status in ('已导出', '已完成'):
            batch_done += 1
            exported_ids.append(vid)
            continue

        in_active_queue = bool(
            active and (is_rendering_now or (rid and rid in queued_job_ids) or (exp_key and exp_key in queued_paths))
        )
        if in_active_queue:
            exporting_count += 1
            if cur_status in ('已剪辑', '待人工检查', '待导出'):
                db_updates.append(('导出中', cur_out, vid))
        else:
            if cur_status == '导出中':
                db_updates.append(('已剪辑', cur_out, vid))

    batch_total = len(entries)
    all_finished = bool(not active and batch_total > 0 and batch_done >= batch_total)

    if db_updates or (all_finished and batch['status'] != 'COMPLETED') or newly_exported > 0:
        with database.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if db_updates:
                con.executemany('UPDATE videos SET edit_status=?, edit_output_path=? WHERE id=?', db_updates)
                con.executemany(
                    "UPDATE editing_history SET status=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=(SELECT MAX(id) FROM editing_history WHERE video_id=?)",
                    [(st_val, vid_val) for st_val, _, vid_val in db_updates],
                )
            if all_finished:
                done_msg = f'✓ 已完成全部 {batch_total} 条视频渲染导出'
                con.execute(
                    "UPDATE davinci_batches SET status='COMPLETED', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                    (done_msg, bid),
                )
                con.execute(
                    "UPDATE davinci_autoedit_runs SET status='COMPLETED', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",
                    (done_msg, bid),
                )
                if exported_ids:
                    con.execute(
                        f"UPDATE davinci_video_state SET autoedit_status='COMPLETED', updated_at=CURRENT_TIMESTAMP "
                        f"WHERE batch_id=? AND video_id IN ({','.join('?' * len(exported_ids))})",
                        (bid, *exported_ids),
                    )
            elif newly_exported > 0:
                prog_msg = f'已同步达芬奇手动渲染：当前批次已导出 {batch_done} / {batch_total} 条'
                con.execute(
                    'UPDATE davinci_batches SET error_message=?, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',
                    (prog_msg, bid),
                )
                if run:
                    con.execute(
                        'UPDATE davinci_autoedit_runs SET error_message=?, updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',
                        (prog_msg, bid),
                    )

        if base and run:
            fin_path = base / 'finish.ini'
            fin_cur = daily.read_pairs(fin_path)
            if all_finished:
                daily.atomic_pairs(fin_path, {
                    'batch_id': bid,
                    'attempt_id': run['attempt_id'],
                    'stage': 'COMPLETED',
                    'detail': f'已完成全部 {batch_total} 条视频渲染导出',
                })
                lock_p = b_root / 'pipeline.lock'
                if lock_p.is_file() and daily.read_pairs(lock_p).get('batch_id') == bid:
                    lock_p.unlink(missing_ok=True)
            elif newly_exported > 0 and fin_cur.get('stage') == 'EXPORT_ERROR':
                daily.atomic_pairs(fin_path, {
                    **fin_cur,
                    'detail': f'导出未完成（当前已导出 {batch_done}/{batch_total} 条）；成功成品已保存，可继续渲染或重试导出',
                })

    res = {
        'batch_id': bid,
        'project': project_name,
        'timeline': timeline_name,
        'batch_done': str(batch_done),
        'batch_total': str(batch_total),
        'newly_exported': str(newly_exported),
        'exporting': str(exporting_count),
    }
    daily.atomic_pairs(reply_path, res)
    _LAST_MANUAL_RENDER_SIG = sig
    _LAST_MANUAL_RENDER_RES = dict(res)
    return res


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Flow Studio Resolve finish sync helper')
    parser.add_argument('--sync-manual-render', action='store_true')
    parser.add_argument('--root', default='')
    parser.add_argument('--db', default='')
    args = parser.parse_args()
    if args.db:
        database.DB_PATH = Path(args.db)
    if args.sync_manual_render:
        out = sync_manual_render(args.root or None, force=True)
        print(
            f"BATCH_SYNC batch_id={out.get('batch_id','')} "
            f"batch_done={out.get('batch_done','0')} "
            f"batch_total={out.get('batch_total','0')} "
            f"newly_exported={out.get('newly_exported','0')} "
            f"exporting={out.get('exporting','0')}"
        )



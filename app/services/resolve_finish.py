"""Durable finish handoff; only an explicitly recoverable post-delete Ripple verification error may resume."""
from pathlib import Path
import time
import uuid
from app.core import database, repository as repo
from app.core.naming import resolve_export_filename
from app.services import resolve_daily as daily, resolve_autoedit as auto

STATES=('FINISH_QUEUED','CLEANING','CLEANING_ERROR','PREPARING_EXPORT','RENDERING','EXPORT_ERROR','COMPLETED')

def sync():
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
                con.execute('UPDATE davinci_batches SET status=?,error_message=? WHERE batch_id=?',(status,state.get('detail',''),row['batch_id']))
                con.execute('UPDATE davinci_autoedit_runs SET status=?,error_message=? WHERE batch_id=?',(status,state.get('detail',''),row['batch_id']))
        if review_return:
            # Release only this finished batch's Resolve runtime lock/queued commands.
            # The QC video rows themselves are deliberately preserved.
            batch_runtime={'batch_id':row['batch_id'],'work_date':row['work_date']}
            _archive_batch_runtime(batch_runtime,'qc_return')
            if repo.get_setting('active_batch_id','')==row['batch_id']:
                repo.set_setting('active_batch_id','')

def submit(day):
    sync();batch=auto.current(day)
    if not batch:raise ValueError('所选日期没有可处理的批次。')
    state=daily.snapshot()
    if not state.get('alive') or 'FINISH_BATCH' not in state.get('capabilities','').split(','):
        raise ValueError('请停止旧 Bridge、安装本版 Bridge，然后重新唤醒。')
    if state.get('stage') not in ('READY','WAITING_USER_REVIEW','ERROR','CLEANING_ERROR') or state.get('project')!='FlowStudio-'+day or state.get('timeline')!='MAIN-'+day:
        raise ValueError('请先唤醒所选日期项目，等待当前操作结束。')
    with database.connect() as con:
        row=dict(con.execute('SELECT * FROM davinci_autoedit_runs WHERE batch_id=?',(batch['batch_id'],)).fetchone())
    base=Path(row['payload_path']).parent
    previous=daily.read_pairs(base/'finish.ini')
    cleanup_started = (base / 'cleanup_intent.ini').exists()
    recoverable_cleanup_error=(
        previous.get('stage')=='CLEANING_ERROR'
        and (not cleanup_started or 'RIPPLE_RANGE_MISMATCH' in previous.get('detail',''))
    )
    if previous.get('stage')=='CLEANING':
        raise ValueError('清理仍在执行或曾在删除动作中断，已保留现场；不能重复提交。')
    if previous.get('stage')=='CLEANING_ERROR' and not recoverable_cleanup_error:
        raise ValueError('清理曾中断，已保留现场；当前错误不能安全自动恢复，不能自动再次删除片段。')
    if batch['status'] not in ('WAITING_USER_REVIEW','CLEANING_ERROR','EXPORT_ERROR','RENDERING','PREPARING_EXPORT'):
        raise ValueError('当前批次不能清理或恢复导出。')
    inbox=daily.bridge_root()/'v0_5_0/commands'
    if any(daily.read_pairs(path).get('action')=='FINISH_BATCH' for path in inbox.glob('*.job')):
        raise ValueError('已有清理 / 导出请求等待执行，请勿重复提交。')
    request=uuid.uuid4().hex
    job={'action':'FINISH_BATCH','request_id':request,'batch_id':batch['batch_id'],'attempt_id':row['attempt_id'],'payload_path':row['payload_path'],'work_date':day}
    # Original analysis attempt identifies durable per-video output receipts.
    daily.atomic_pairs(daily.bridge_root()/'v0_5_0/commands'/(request+'.job'),job)
    detail='已提交清理后安全恢复 / 继续导出' if recoverable_cleanup_error else '已提交清理 / 恢复未完成导出'
    return {'submitted':True,'detail':detail}

_MANUAL_RUNNING_BATCH = {
    'IMPORTING','AUTOEDIT_QUEUED','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING',
    'CUTTING','FINISH_QUEUED','CLEANING','PREPARING_EXPORT','RENDERING',
}
_MANUAL_RUNNING_BRIDGE = {
    'IMPORTING','AUDIO_RENDERING','WHISPER_RUNNING','TEXT_ALIGNING','CUTTING',
    'CLEANING','PREPARING_EXPORT','RENDERING',
}


def _manual_batch(day):
    """Return the newest unfinished batch without inventing a new business state."""
    auto.ensure_schema()
    with database.connect() as con:
        row=con.execute(
            "SELECT * FROM davinci_batches WHERE work_date=? "
            "AND status NOT IN ('COMPLETED','SKIPPED','PROJECT_REBUILT') "
            "ORDER BY rowid DESC LIMIT 1", (day,)
        ).fetchone()
    if not row:
        raise ValueError('当前没有可结束或跳过的剪辑批次。')
    batch=dict(row)
    if batch['status'] in _MANUAL_RUNNING_BATCH:
        raise ValueError('当前批次仍在执行中，请等待当前 DaVinci 操作结束后再手动处理。')
    state=daily.snapshot()
    if state.get('alive') and state.get('batch_id')==batch['batch_id'] and state.get('stage') in _MANUAL_RUNNING_BRIDGE:
        raise ValueError('DaVinci 仍在执行当前批次，请等待操作结束后再手动处理。')
    return batch


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
    """Archive, rather than delete, only this batch's pending commands and lock."""
    root=daily.bridge_root();bid=batch['batch_id'];day=batch['work_date']
    stamp=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    archive=root/'logs'/bid/f'manual_{mode}_{stamp}'
    archive.mkdir(parents=True,exist_ok=True)

    lock_candidates=[root/'pipeline.lock', root/'v0_5_0'/'suspended'/f'pipeline_{day}.ini']
    for path in lock_candidates:
        if not path.is_file():
            continue
        lock=daily.read_pairs(path)
        if lock.get('batch_id')==bid:
            path.replace(archive/path.name)
        elif path.name=='pipeline.lock' and lock.get('work_date')==day and lock.get('batch_id'):
            raise ValueError('检测到同日期的另一个 DaVinci 批次运行锁，未解除任何其他批次。')

    inbox=root/'v0_5_0'/'commands'
    if inbox.is_dir():
        for path in sorted(inbox.glob('*.job')):
            job=daily.read_pairs(path)
            if job.get('batch_id')==bid:
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

    with database.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if updates:
            con.executemany('UPDATE videos SET edit_status=?,edit_output_path=? WHERE id=?',updates)
            con.executemany(
                "UPDATE editing_history SET status=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=(SELECT MAX(id) FROM editing_history WHERE video_id=?)",
                [(row[0],row[2]) for row in updates]
            )
        con.execute('UPDATE davinci_batches SET status=?,error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',(status,detail,bid))
        if run:
            # Freeze old state.ini / finish.ini recovery so a stale error cannot resurrect this batch.
            con.execute("UPDATE davinci_autoedit_runs SET status='COMPLETED',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?",(detail,bid))
        con.execute('UPDATE davinci_video_state SET autoedit_status=?,updated_at=CURRENT_TIMESTAMP WHERE batch_id=?',(video_state,bid))

    if repo.get_setting('active_batch_id','')==bid:
        repo.set_setting('active_batch_id','')
    daily.atomic_pairs(daily.bridge_root()/'v0_5_0'/'batches'/bid/'manual_close.ini',{
        'batch_id':bid,'work_date':day,'mode':mode,'status':status,'detail':detail,
        'archive_path':str(archive),'closed_at':time.strftime('%Y-%m-%d %H:%M:%S'),
    })
    return {'ok':True,'batch_id':bid,'status':status,'exported':exported,'edited':edited,'requeued':requeued,'detail':detail}


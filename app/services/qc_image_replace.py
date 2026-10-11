from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3

from app.core import database, repository as repo, work_dates
from app.core.default_prompt import DEFAULT_CORE_PROMPT
from app.core.persona import normalize, rule_text, active_action_presets
from app.services import openai_service, runtime_log
from app.services.image_assets import resolve_path


def _video_context(video_id: int, work_date=None) -> dict:
    """Read the exact writable task identity used by the replacement workflow."""
    vid = int(video_id)
    with database.connect() as con:
        video = con.execute(
            """SELECT v.id video_id,v.host_id,v.seq video_seq,v.script,v.chinese_script,v.image_path,
                      COALESCE(v.source_task_id,'') source_task_id,COALESCE(v.performance_mode,'TALKING') performance_mode,
                      COALESCE(v.prompt_template_snapshot,'') prompt_template_snapshot,
                      COALESCE(v.special_requirements,'') special_requirements,COALESCE(v.edit_status,'等待片段') edit_status,
                      h.id host_id,h.name host_name,COALESCE(h.prompt_rule,'') prompt_rule,
                      r.id recipient_id,r.name recipient_name
               FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
               WHERE v.id=?""",
            (vid,),
        ).fetchone()
        if not video:
            raise ValueError('当前完整视频任务已经不存在。')
        task_date = work_dates.recipient_work_date(con, int(video['recipient_id']))
        if work_date is not None:
            expected_date = work_dates.normalize_scope(work_date)
            if task_date != expected_date:
                raise ValueError(
                    f'当前任务属于 {task_date}，与正在编辑的日期 {expected_date} 不一致，已阻止跨日期修改。'
                )
        segments = con.execute(
            """SELECT id segment_id,seg_seq,foreign_text,prompt,ai_original_prompt,segment_rule,status,model,
                      COALESCE(generation_mode,'FRAME') generation_mode,
                      COALESCE(generation_command,'') generation_command,
                      COALESCE(flow_status,'待生成') flow_status,
                      COALESCE(flow_output_path,'') flow_output_path,
                      COALESCE(qc_status,'待质检') qc_status,
                      COALESCE(flow_retry_count,0) flow_retry_count
               FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id""",
            (vid,),
        ).fetchall()
    if not segments:
        raise ValueError('当前完整视频没有可重新生成的 Flow 片段。')
    return {
        **dict(video),
        'work_date': task_date or work_dates.LEGACY,
        'segments': [dict(row) for row in segments],
    }


def _recover_bound_image(video_id: int, stored_path: str) -> tuple[str, bool]:
    """Resolve only image sources explicitly bound to this video/task.

    Older projects can retain an image path that became stale after Finder moves or
    task-material consolidation.  Recovery is deliberately ID-bound: asset_jobs and
    the pre-GPT production link are checked, never a basename/global folder search.
    """
    raw = str(stored_path or '').strip()
    if raw:
        try:
            return str(resolve_path(raw)), False
        except Exception:
            pass

    candidates = []
    try:
        with database.connect() as con:
            rows = con.execute(
                "SELECT local_path FROM asset_jobs WHERE video_id=? AND TRIM(COALESCE(local_path,''))<>'' ORDER BY id DESC",
                (int(video_id),),
            ).fetchall()
            candidates.extend(str(row['local_path'] or '') for row in rows)
    except Exception:
        pass

    intake_db = database.DB_PATH.parent / 'pre_gpt_pipeline.sqlite3'
    if intake_db.is_file():
        try:
            uri = intake_db.resolve().as_uri() + '?mode=ro'
            with sqlite3.connect(uri, uri=True) as con:
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {'production_links','tasks'} <= tables:
                    rows = con.execute(
                        """SELECT t.matched_asset_path FROM production_links p
                           JOIN tasks t ON t.id=p.task_id
                           WHERE p.video_id=? AND TRIM(COALESCE(t.matched_asset_path,''))<>''
                           ORDER BY t.id DESC""",
                        (int(video_id),),
                    ).fetchall()
                    candidates.extend(str(row[0] or '') for row in rows)
                if {'production_links','assets'} <= tables:
                    rows = con.execute(
                        """SELECT a.local_path FROM production_links p
                           JOIN assets a ON a.matched_task_id=p.task_id
                           WHERE p.video_id=? AND TRIM(COALESCE(a.local_path,''))<>''
                           ORDER BY a.id DESC""",
                        (int(video_id),),
                    ).fetchall()
                    candidates.extend(str(row[0] or '') for row in rows)
        except Exception:
            pass

    seen = set()
    for candidate in candidates:
        candidate = str(candidate or '').strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return str(resolve_path(candidate)), True
        except Exception:
            continue
    return raw, False


def get_replacement_context(video_id: int, work_date=None) -> dict:
    context = _video_context(video_id, work_date=work_date)
    preview_path, recovered = _recover_bound_image(int(context['video_id']), str(context.get('image_path') or ''))
    context['preview_image_path'] = preview_path
    context['image_recovered'] = bool(recovered)
    context['identity'] = {
        'video_id': int(context['video_id']),
        'work_date': str(context.get('work_date') or work_dates.LEGACY),
        'host_id': int(context['host_id']),
        'recipient_id': int(context['recipient_id']),
        'video_seq': int(context['video_seq']),
        'source_task_id': str(context.get('source_task_id') or ''),
        'script': str(context.get('script') or ''),
        'chinese_script': str(context.get('chinese_script') or ''),
        'image_path': str(context.get('image_path') or ''),
        'segments': [
            {
                'segment_id': int(seg['segment_id']),
                'seg_seq': int(seg['seg_seq']),
                'foreign_text': str(seg.get('foreign_text') or ''),
            }
            for seg in context['segments']
        ],
    }
    return context


def generate_replacement_prompts(video_id: int, replacement_image: str, work_date=None) -> dict:
    """Generate with the staged image only; this function never changes task state."""
    context = get_replacement_context(video_id, work_date=work_date)
    image_path = str(resolve_path(replacement_image))
    mode = 'PRAYING' if str(context.get('performance_mode') or '').upper() == 'PRAYING' else 'TALKING'
    template = str(context.get('prompt_template_snapshot') or '').strip()
    if not template:
        key = 'praying_base_prompt' if mode == 'PRAYING' else 'talking_base_prompt'
        template = str(repo.get_setting(key, '') or '').strip()
        if not template:
            raise RuntimeError(f'{mode} 基础模板尚未设置，不能重新生成提示词。')

    persona_raw = repo.get_setting(f"host_persona_{int(context['host_id'])}_{mode.lower()}", '')
    try:
        persona = normalize(json.loads(persona_raw) if persona_raw else {}, mode)
    except Exception:
        persona = normalize({}, mode)
    host_rule = rule_text(persona, mode)
    previous_rule = str(context.get('prompt_rule') or '').strip()
    if not persona_raw and previous_rule:
        host_rule = previous_rule + '\n' + host_rule

    group = {
        'video_id': int(context['video_id']),
        'image_path': image_path,
        'host_name': str(context.get('host_name') or ''),
        'host_rule': host_rule,
        'host_id': int(context['host_id']),
        'auto_action_match': bool(persona.get('auto_action_match', True)),
        'action_presets': active_action_presets(persona, mode=mode),
        'image_rule': str(context.get('special_requirements') or ''),
        'video_seq': int(context['video_seq']),
        'performance_mode': mode,
        'template_snapshot': template,
        'segments': [
            {
                'segment_id': int(seg['segment_id']),
                'task_id': f"{int(context['video_seq']):02d}-{int(seg['seg_seq']):02d}",
                'foreign_text': str(seg.get('foreign_text') or ''),
                'segment_rule': str(seg.get('segment_rule') or ''),
            }
            for seg in context['segments']
        ],
    }
    core = repo.get_setting('core_prompt', DEFAULT_CORE_PROMPT) or DEFAULT_CORE_PROMPT
    effective_core = str(core).strip() + '\n\n【当前表演模式基础模板】\n' + template
    model = repo.get_setting('openai_model', 'gpt-5.6-luna')
    image_detail = repo.get_setting('image_detail', 'low') or 'low'
    result = openai_service.generate_prompts_for_image(
        model=model,
        core_prompt=effective_core,
        group=group,
        image_detail=image_detail,
    )
    prompts = {int(k): str(v or '').strip() for k, v in dict(result.get('prompts') or {}).items()}
    ai_prompts = {int(k): str(v or '') for k, v in dict(result.get('ai_prompts') or {}).items()}
    expected = {int(seg['segment_id']) for seg in context['segments']}
    if set(prompts) != expected or any(not prompts[sid] for sid in expected):
        raise RuntimeError('GPT 返回的提示词与当前任务片段没有严格一一对应，已阻止替换。')
    runtime_log.log('qc_image_replace_prompt_generated', video_id=int(video_id), image=image_path,
                    segments=sorted(expected), model=model)
    return {
        'context': context,
        'work_date': str(context.get('work_date') or work_dates.LEGACY),
        'selected_image': image_path,
        'prompts': prompts,
        'ai_prompts': ai_prompts,
        'model': model,
        'input_tokens': int(result.get('input_tokens') or 0),
        'cached_tokens': int(result.get('cached_tokens') or 0),
        'output_tokens': int(result.get('output_tokens') or 0),
        'cost_usd': float(result.get('cost_usd') or 0.0),
    }


def _copy_managed_image(source: str, folder: Path, prefix: str) -> Path:
    src = resolve_path(source)
    folder.mkdir(parents=True, exist_ok=True)
    stat = src.stat()
    identity = f'{src.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'
    token = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    suffix = src.suffix.lower() or '.jpg'
    dst = folder / f'{prefix}_{stamp}_{token}{suffix}'
    shutil.copy2(src, dst)
    return dst.resolve()


def _same_identity(current: dict, expected: dict) -> bool:
    scalar = ('video_id', 'work_date', 'host_id', 'recipient_id', 'video_seq', 'source_task_id', 'script', 'chinese_script', 'image_path')
    for key in scalar:
        if str(current.get(key, '')) != str(expected.get(key, '')):
            return False
    now_segments = [(int(x['segment_id']), int(x['seg_seq']), str(x.get('foreign_text') or '')) for x in current['segments']]
    old_segments = [(int(x['segment_id']), int(x['seg_seq']), str(x.get('foreign_text') or '')) for x in expected.get('segments', [])]
    return now_segments == old_segments


def commit_replacement(generated: dict, final_prompts: dict[int, str] | None = None, *, target_generation_mode=None, mode_touched=False) -> dict:
    """Replace source image through the existing REWORK chain.

    GPT regeneration is optional. Active/late old revisions are superseded by clearing their
    generation_command; workflow receipt matching therefore treats any delayed result as stale.
    """
    context = dict(generated.get('context') or {})
    expected = dict(context.get('identity') or {})
    if not expected:
        raise ValueError('缺少替换前任务身份快照，已阻止提交。')
    video_id = int(expected['video_id'])
    scope_day = work_dates.normalize_scope(generated.get('work_date') or expected.get('work_date'))
    current = get_replacement_context(video_id, work_date=scope_day)
    if not _same_identity(current, expected):
        raise ValueError('任务编号、文案或原图片在操作期间发生变化。为防止串号/串文案，本次替换已取消，请刷新后重试。')

    segment_ids = [int(seg['segment_id']) for seg in current['segments']]
    source_prompts = {int(seg['segment_id']): str(seg.get('prompt') or '').strip() for seg in current['segments']}
    prompt_map = {int(k): str(v or '').strip() for k, v in dict(final_prompts or source_prompts).items()}
    if set(prompt_map) != set(segment_ids) or any(not prompt_map[sid] for sid in segment_ids):
        raise ValueError('提示词必须与原任务片段严格一一对应，不能为空、不能增减片段。')

    allowed_edit = {'', '等待片段', '素材待齐', '等待剪辑', '待剪辑'}
    if str(current.get('edit_status') or '') not in allowed_edit:
        raise ValueError('当前完整视频已经进入 DaVinci/导出等下游流程，不能再替换源图片。')

    root = database.DB_PATH.parent / 'image_replacements' / scope_day / f'video_{video_id:06d}'
    new_path = _copy_managed_image(str(generated.get('selected_image') or ''), root / 'current', 'new')
    archived_old = ''
    old_path = str(current.get('image_path') or '')
    old_copy_source = str(current.get('preview_image_path') or old_path)
    try:
        if old_copy_source:
            archived_old = str(_copy_managed_image(old_copy_source, root / 'history', 'old'))
    except Exception:
        archived_old = ''

    generated_prompts = {int(k): str(v or '').strip() for k, v in dict(generated.get('prompts') or {}).items()}
    generated_ai_prompts = {int(k): str(v or '') for k, v in dict(generated.get('ai_prompts') or {}).items()}
    used_gpt = bool(generated_prompts)
    n=max(1,len(segment_ids))
    def split_int(total):
        total=int(total or 0); base,rem=divmod(total,n); return [base+(1 if i<rem else 0) for i in range(n)]
    input_parts=split_int(generated.get('input_tokens')); cache_parts=split_int(generated.get('cached_tokens')); output_parts=split_int(generated.get('output_tokens'))
    total_cost=float(generated.get('cost_usd') or 0.0); cost_parts=[total_cost/n]*n
    if cost_parts: cost_parts[-1]=total_cost-sum(cost_parts[:-1])
    model=str(generated.get('model') or repo.get_setting('openai_model','gpt-5.6-luna'))
    normalized_mode=repo.normalize_generation_mode(target_generation_mode) if mode_touched else None

    try:
        with database.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            db_video=con.execute("""SELECT v.id video_id,v.host_id,v.seq video_seq,v.script,v.chinese_script,v.image_path,
                COALESCE(v.source_task_id,'') source_task_id,COALESCE(v.edit_status,'等待片段') edit_status,h.recipient_id
                FROM videos v JOIN hosts h ON h.id=v.host_id WHERE v.id=?""",(video_id,)).fetchone()
            if not db_video: raise ValueError('当前完整视频任务已经不存在。')
            actual_day=work_dates.recipient_work_date(con,int(db_video['recipient_id']))
            if actual_day!=scope_day: raise ValueError(f'提交前检测到任务日期已变为 {actual_day}，当前工作日期为 {scope_day}，已阻止跨日期写入。')
            latest_segments=con.execute("""SELECT id segment_id,seg_seq,foreign_text,prompt,ai_original_prompt,model,
                COALESCE(generation_mode,'FRAME') generation_mode,COALESCE(flow_status,'待生成') flow_status,
                COALESCE(generation_command,'') generation_command,COALESCE(flow_output_path,'') flow_output_path
                FROM flow_segments WHERE video_id=? ORDER BY seg_seq,id""",(video_id,)).fetchall()
            verify={'video_id':int(db_video['video_id']),'work_date':scope_day,'host_id':int(db_video['host_id']),'recipient_id':int(db_video['recipient_id']),
                'video_seq':int(db_video['video_seq']),'source_task_id':str(db_video['source_task_id'] or ''),'script':str(db_video['script'] or ''),
                'chinese_script':str(db_video['chinese_script'] or ''),'image_path':str(db_video['image_path'] or ''),'segments':[dict(x) for x in latest_segments]}
            if not _same_identity(verify, expected): raise ValueError('提交前检测到任务身份变化，已阻止替换，避免串号或串文案。')
            if str(db_video['edit_status'] or '') not in allowed_edit: raise ValueError('当前完整视频已经进入下游处理，不能替换图片。')

            # Supersede every exact current revision, including revisions that are still in Flow.
            for seg in latest_segments:
                sid=int(seg['segment_id']); command=str(seg['generation_command'] or ''); output=str(seg['flow_output_path'] or '')
                if command: con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND command_id=?",(sid,command))
                elif output: con.execute("UPDATE flow_outputs SET qc_status='旧版本失效' WHERE segment_id=? AND output_path=?",(sid,output))

            con.execute("UPDATE videos SET image_path=?,asset_status='已准备',edit_status='等待片段' WHERE id=?",(str(new_path),video_id))
            for index,seg in enumerate(latest_segments):
                sid=int(seg['segment_id']); mode=normalized_mode or repo.normalize_generation_mode(seg['generation_mode'])
                if used_gpt:
                    original_prompt=generated_ai_prompts.get(sid) or generated_prompts.get(sid) or prompt_map[sid]
                    con.execute("""UPDATE flow_segments SET ai_original_prompt=?,prompt=?,status='已生成',model=?,input_tokens=?,cached_tokens=?,output_tokens=?,cost_usd=?,generation_mode=?,
                        prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP,generation_command='',flow_status='待生成',flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',
                        flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',qc_status='退回',qc_note='替换图片',qc_reject_reason='替换图片',qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (original_prompt,prompt_map[sid],model,input_parts[index],cache_parts[index],output_parts[index],cost_parts[index],mode,sid))
                else:
                    con.execute("""UPDATE flow_segments SET prompt=?,generation_mode=?,prompt_review_status='已提交',prompt_submitted_at=CURRENT_TIMESTAMP,
                        generation_command='',flow_status='待生成',flow_output_path='',flow_output_url='',flow_error='',flow_channel_key='R1',
                        flow_retry_count=COALESCE(flow_retry_count,0)+1,flow_submitted_at='',flow_completed_at='',qc_status='退回',qc_note='替换图片',qc_reject_reason='替换图片',qc_decided_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (prompt_map[sid],mode,sid))
                con.execute("INSERT OR REPLACE INTO flow_redo(segment_id,created_at) VALUES(?,CURRENT_TIMESTAMP)",(sid,))
                con.execute("DELETE FROM flow_recovery WHERE segment_id=?",(sid,))
                con.execute("INSERT INTO prompt_submission_history(segment_id,prompt_snapshot) VALUES(?,?)",(sid,prompt_map[sid]))
                con.execute("""INSERT INTO qc_decisions(segment_id,decision,reason,recipient_name,host_name,performance_mode,prompt_snapshot)
                    VALUES(?,?,?,?,?,?,?)""",(sid,'退回','替换图片',str(current.get('recipient_name') or ''),str(current.get('host_name') or ''),str(current.get('performance_mode') or 'TALKING'),prompt_map[sid]))
            if used_gpt:
                con.execute("INSERT INTO api_usage_log(flow_segment_id,model,input_tokens,cached_tokens,output_tokens,cost_usd) VALUES(?,?,?,?,?,?)",
                    (segment_ids[0],model,int(generated.get('input_tokens') or 0),int(generated.get('cached_tokens') or 0),int(generated.get('output_tokens') or 0),total_cost))
    except Exception:
        try: Path(new_path).unlink(missing_ok=True)
        except Exception: pass
        raise

    record={'created_at':datetime.now().isoformat(timespec='seconds'),'work_date':scope_day,'video_id':video_id,'video_seq':int(expected['video_seq']),
        'segment_ids':segment_ids,'old_image_original':old_path,'old_image_archive':archived_old,'new_image':str(new_path),'reason':'替换图片',
        'generation_mode':normalized_mode or 'PRESERVE','gpt_regenerated':used_gpt}
    try:
        root.mkdir(parents=True,exist_ok=True)
        with (root/'history.jsonl').open('a',encoding='utf-8') as fh: fh.write(json.dumps(record,ensure_ascii=False)+'\n')
    except Exception: pass
    runtime_log.log('qc_image_replaced',video_id=video_id,video_seq=int(expected['video_seq']),segments=segment_ids,new_image=str(new_path),generation_mode=record['generation_mode'],gpt_regenerated=used_gpt)
    return {'video_id':video_id,'segment_ids':segment_ids,'new_image':str(new_path),'old_image_archive':archived_old,'generation_mode':record['generation_mode'],'gpt_regenerated':used_gpt}

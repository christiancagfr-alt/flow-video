from __future__ import annotations
from pathlib import Path
import hashlib, re, time, random, unicodedata
from app.core import repository as repo
from app.services import runtime_log

VIDEO_EXTS={'.mp4','.mov','.m4v','.webm'}
_UNMATCHED_LOGGED=set()


def safe_name(value,limit=70):
    text=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','_',str(value or '').strip()).strip('. ')
    text=re.sub(r'\s+',' ',text)
    return text[:limit] or '未命名'


def ensure_defaults():
    # One-time migration: old V0.13.1 default was 4 normal + 1 fast.
    # V0.13.2 default is 7 normal + 1 fast = 8 channels, all in Browser A.
    if repo.get_setting('flow_pool_layout_v0132','')!='1':
        current=repo.channel_pool_normal_count()
        if current <= 4:
            repo.set_setting('flow_pool_normal_count','7')
        repo.set_setting('flow_browser_b_enabled', repo.get_setting('flow_browser_b_enabled','0') or '0')
        repo.set_setting('flow_pool_b_normal_count', repo.get_setting('flow_pool_b_normal_count','0') or '0')
        repo.set_setting('flow_pool_b_fast_enabled', repo.get_setting('flow_pool_b_fast_enabled','0') or '0')
        repo.set_setting('flow_dispatch_stagger_min', repo.get_setting('flow_dispatch_stagger_min','10') or '10')
        repo.set_setting('flow_dispatch_stagger_max', repo.get_setting('flow_dispatch_stagger_max','15') or '15')
        repo.set_setting('flow_pool_layout_v0132','1')
        runtime_log.log('channel_pool_migrated_v0132',normal_a=repo.channel_pool_normal_count(),browser_b=False,stagger='10-15')

    repo.ensure_channel_pool()
    root=repo.get_setting('flow_channel_download_root','').strip()
    if not root:
        root=str(Path.home()/'Downloads'/'FlowStudio_Channels')
        repo.set_setting('flow_channel_download_root',root)
    for ch in repo.list_channel_pool(enabled_only=True):
        folder=Path(root)/str(ch['download_subdir'] or ch['channel_key'])
        folder.mkdir(parents=True,exist_ok=True)
    return root

def normal_channels():
    ensure_defaults()
    now=time.time()
    return [c for c in repo.list_channel_pool(enabled_only=True) if c['role']=='normal' and repo.channel_is_usable(c,now)]


def fast_channels():
    ensure_defaults()
    now=time.time()
    return [c for c in repo.list_channel_pool(enabled_only=True) if c['role']=='fast' and repo.channel_is_usable(c,now)]


def fast_channel():
    channels=fast_channels()
    if not channels:return None
    return min(channels,key=lambda c:(repo.channel_pool_load(c['channel_key']), int(c['sort_order'] or 0)))


def browser_group(channel):
    return repo.channel_browser_group(channel['channel_key'] if channel else '')


def stagger_bounds():
    try: lo=max(1,int(repo.get_setting('flow_dispatch_stagger_min','10') or 10))
    except Exception: lo=10
    try: hi=max(1,int(repo.get_setting('flow_dispatch_stagger_max','15') or 15))
    except Exception: hi=15
    if hi<lo: lo,hi=hi,lo
    return lo,hi


def apply_random_release_schedule(jobs, now=None, minimum=None, maximum=None):
    """Random stagger *inside each browser only*.

    Browser A/B/C... run in parallel. The first channel of every browser is released
    immediately (with a tiny sub-second jitter), then that browser's own channels are
    spaced by the configured 10-15 seconds. This avoids the old global serial delay.
    """
    jobs=list(jobs or [])
    if not jobs:return jobs
    lo,hi=stagger_bounds()
    if minimum is not None: lo=max(1,int(minimum))
    if maximum is not None: hi=max(1,int(maximum))
    if hi<lo: lo,hi=hi,lo
    rng=random.SystemRandom(); base=float(now if now is not None else time.time())
    grouped={}
    for job in jobs:
        gid=str(job.get('browser_group') or repo.channel_browser_group(job.get('channel_key','')) or 'A')
        grouped.setdefault(gid,[]).append(job)
    for group_index,(gid,items) in enumerate(sorted(grouped.items())):
        # Main browser starts immediately. Additional browsers get only a tiny independent jitter
        # so browsers still run in parallel without a synchronized burst.
        cursor=base if group_index == 0 else base + rng.random()*2.0
        for index,job in enumerate(items):
            if index: cursor += rng.randint(lo,hi)
            job['release_at']=cursor
            job['release_order']=index+1
            job['release_stagger_min']=lo
            job['release_stagger_max']=hi
            job['release_scope']='browser'
            job['browser_group']=gid
    return jobs


def unique_images(tasks):
    seen=set();out=[]
    for t in tasks:
        for p in [str(t['image_path'] or ''),str(t.get('end_image_path') or '')]+[str(x) for x in (t.get('material_image_paths') or [])]:
            if p and p not in seen:
                seen.add(p);out.append(p)
    return out


def image_payload(paths):
    files=[];parts=[]
    for path in paths:
        p=Path(path)
        try:
            st=p.stat();size=int(st.st_size);mtime=int(st.st_mtime_ns)
        except OSError:
            size=-1;mtime=-1
        files.append({'path':str(path),'name':p.name,'size':size,'mtime_ns':mtime})
        parts.append(f'{p.name.lower()}|{size}|{mtime}')
    fp=hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:24]
    return files,fp


def task_stem(task, round_no=1):
    # Human-readable first, durable segment id last. One expected filename per render.
    base=f"{int(task['video_seq']):02d}-{int(task['seg_seq']):02d}-{safe_name(task['host_name'],40)}-S{int(task['segment_id']):06d}"
    retry=int(task.get('flow_retry_count',0) if hasattr(task,'get') else task['flow_retry_count'])
    if retry>0:
        base+=f"-Q{retry:02d}"
    if int(round_no)>1:
        base+=f"-R{int(round_no):02d}"
    return base


def render_stem(task, round_no=1, total_rounds=1):
    """Exact filename stem decided by Studio; plugin must use this verbatim."""
    base=task_stem(task,1)
    return f"{base}-R{int(round_no):02d}" if int(total_rounds)>1 else base


# Bound each submission wave; remaining tasks stay in the database queue.
WAVE_CAP=5


def _image_key(task):
    return unicodedata.normalize('NFC',str((task.get('image_path') if hasattr(task,'get') else task['image_path']) or '').strip())


def _image_sibling_state(keys):
    """For each image: channels that already hold it (prior dispatches) and active (in-flight) count."""
    out={k:{'channels':{},'active':0} for k in keys if k}
    if not out:return out
    try:
        from app.core.database import connect
        marks=','.join('?'*len(out))
        with connect() as con:
            rows=con.execute(f"""SELECT v.image_path, COALESCE(fs.flow_channel_key,''), COALESCE(fs.flow_status,''),
                                        COALESCE(fs.generation_command,''), fs.id
                                 FROM flow_segments fs JOIN videos v ON v.id=fs.video_id
                                 WHERE v.image_path IN ({marks})""",list(out)).fetchall()
    except Exception as exc:
        runtime_log.log('plan_image_affinity_failed',level='WARNING',error=str(exc))
        return out
    for path,ch,status,cmd,sid in rows:
        st=out.get(unicodedata.normalize('NFC',str(path or '').strip()))
        if st is None:continue
        if ch:
            st['channels'][ch]=max(st['channels'].get(ch,0),int(sid))   # most recent use wins ties
        if cmd and status in ('已准备','已提交','生成中','下载中'):
            st['active']+=1
    return out


def plan(tasks, channels=None, total_channels=None):
    """Prefer channels already holding the reference, with at most WAVE_CAP tasks
    per channel. Unassigned tasks remain queued for the next available wave.
    """
    channels=list(normal_channels() if channels is None else channels)
    if not channels:return {}
    from app.services import pause_control
    tasks=pause_control.filter_tasks(tasks)          # paused AI hosts get nothing dispatched
    loads={str(c['channel_key']):repo.channel_pool_load(c['channel_key']) for c in channels}
    sort_of={str(c['channel_key']):int(c['sort_order'] or 0) for c in channels}
    out={str(c['channel_key']):[] for c in channels}
    from app.services.local_bridge import get_bridge
    bridge = get_bridge()
    ordered=sorted(tasks,key=lambda t:(int(t['_host_priority']) if '_host_priority' in t.keys() else 0,int(t['recipient_id']),int(t['host_id']),int(t['video_seq']),int(t['seg_seq'])))

    # Pre-fetch capabilities
    channel_caps = {}
    for c in channels:
        try:
            state = bridge.channel_state(c['id'])
            caps = state.get('capabilities') or {}
            channel_caps[str(c['channel_key'])] = caps
        except:
            channel_caps[str(c['channel_key'])] = {}

    def eligible_for(task):
        task_type = task.get('TASK_TYPE', 'VIDEO')
        res=[]
        vp=None
        for c in channels:
            k = str(c['channel_key']); caps = channel_caps[k]
            if task_type == 'BROLL_VIDEO' and not caps.get('BROLL_VIDEO'): continue
            if task_type == 'BROLL_IMAGE' and not caps.get('BROLL_IMAGE'): continue
            res.append(k)
        return res

    # Group by reference image, keeping the first-appearance order of the priority sort.
    groups={}; order=[]
    for t in ordered:
        key=_image_key(t) or f"__seg_{t['segment_id']}"
        if key not in groups:groups[key]=[];order.append(key)
        groups[key].append(t)
    siblings=_image_sibling_state([k for k in order if not k.startswith('__seg_')])

    def assign(key):
        items=groups[key]; st=siblings.get(key,{'channels':{},'active':0}); n=len(items)
        elig=set(eligible_for(items[0]))
        if not elig:return
        # 1) channels already holding this image (most recent first), 2) emptiest channels.
        aff=[k for k,_ in sorted(st['channels'].items(),key=lambda kv:-kv[1]) if k in elig]
        others=sorted([k for k in elig if k not in aff],key=lambda k:(loads[k],sort_of[k]))
        candidates = aff + others
        if not candidates: return
        remaining=list(items)
        for chosen_k in candidates:
            capacity=max(0,WAVE_CAP-len(out[chosen_k]))
            take=remaining[:capacity]
            out[chosen_k].extend(take);loads[chosen_k]+=len(take)
            remaining=remaining[capacity:]
            if not remaining:break

    for key in order:assign(key)
    runtime_log.log('plan_image_grouped',groups=len(order),tasks=len(ordered),
                    assigned={k:len(v) for k,v in out.items() if v},
                    images={k:len({_image_key(t) for t in v}) for k,v in out.items() if v})
    return out


def channel_folder(channel):
    root=Path(ensure_defaults()).expanduser()
    return root/str(channel['download_subdir'] or channel['channel_key'])


def relative_download_folder(channel):
    # Chrome extension filenames are always relative to Chrome's Downloads directory.
    return f"FlowStudio_Channels/{safe_name(channel['download_subdir'] or channel['channel_key'],50)}"


def record_event(event):
    key=str(event.get('channel_key') or '')
    if not key and event.get('channel_id'):
        row=repo.get_channel_pool(channel_id=int(event['channel_id']))
        key=str(row['channel_key']) if row else ''
    if not key:return
    typ=str(event.get('type') or '')
    err=str(event.get('error') or event.get('message') or '') if 'fail' in typ or 'error' in typ else ''
    state=str(event.get('state') or '')
    friendly={
        'web_plugin_heartbeat':'🟢 标签页在线',
        'flow_page_recovering':'🟡 Flow页面恢复中',
        'flow_page_recovered':'🟢 Flow页面已恢复',
        'submission_recovery_started':'🟡 正在核对提交结果',
        'submission_recovery_pending':'🟡 后台核对提交结果',
        'submission_recovered':'🟢 已恢复原提交结果',
        'web_plugin_bound':'🟢 插件已绑定',
        'generation_batch_finished':'提交完成 · 等待渲染',
        'generation_paused':'已暂停',
        'video_download_started':'下载中',
        'video_download_completed':'下载完成 · 等待本地识别',
        'video_download_failed':'🔴 下载失败',
        'web_plugin_runtime_error':'🔴 插件运行错误',
    }.get(typ,typ)
    if typ=='generation_task_status':
        friendly={'preparing':'准备提交 · 校验图片','running':'正在提交','success':'生成中','uncertain':'🟡 提交确认中','failed':'🔴 生成失败'}.get(state,'任务状态更新')
    repo.set_channel_pool_runtime(key,status=friendly,error=err,seen=True)
    if typ in ('web_plugin_heartbeat', 'flow_account_seen') and (event.get('account_email') or event.get('credits_remaining') not in (None,'')):
        try:
            from app.services import flow_accounts
            flow_accounts.observe_page(event.get('account_email'), event.get('credits_remaining'))
        except Exception as exc:
            runtime_log.log('flow_account_observe_failed',level='WARNING',error=str(exc))
    if typ in {'web_plugin_heartbeat','web_plugin_bound','generation_batch_finished','video_download_completed'}:
        repo.set_channel_health(key,health='healthy',reset_failures=True,success=True,page_status=str(event.get('page_status') or event.get('tab_status') or ''))
    elif typ in {'web_plugin_runtime_error','generation_task_failed','video_download_failed','flow_page_unhealthy','generation_button_missing'}:
        repo.set_channel_health(key,health='degraded',failure_delta=1,page_status=str(event.get('page_status') or event.get('tab_status') or ''),success=False)
    if typ=='flow_page_recovered':
        repo.set_channel_health(key,health='healthy',page_status='complete',success=True)
    elif typ=='flow_page_recovering':
        repo.set_channel_health(key,health='recovering',page_status='recovering')
    if typ in {'upload_precheck','media_upload_started','media_upload_dispatched'}:
        repo.set_channel_pool_runtime(key,'uploading',command_id=event.get('command_id'),fingerprint=event.get('image_set_id'),total=event.get('total'),seen=True)
    elif typ in {'media_match_progress','upload_flow_progress'}:
        repo.set_channel_pool_runtime(key,'uploading',uploaded=event.get('recognized',event.get('matched',0)),total=event.get('total'),seen=True)
    elif typ in {'media_ready','upload_verified'}:
        repo.set_channel_pool_runtime(key,'verified',command_id=event.get('command_id'),fingerprint=event.get('image_set_id'),uploaded=event.get('total',event.get('matched',0)),total=event.get('total'),verified=True,error='',seen=True)
    elif typ in {'upload_stopped','upload_verification_failed','media_upload_dispatch_failed'}:
        repo.set_channel_pool_runtime(key,'failed',error=err or '上传失败',seen=True)
    if typ=='flow_unusual_activity':
        try:
            from app.services import pause_control
            secs=pause_control.cooldown_channel(key)
            repo.set_channel_pool_runtime(key,status=f'⏸ Flow 风控提示 · 冷却 {secs//60} 分钟',error=str(event.get('message') or 'Flow unusual activity'),seen=True)
        except Exception as exc:
            runtime_log.log('flow_unusual_activity_handler_failed',level='ERROR',channel=key,error=str(exc))
    runtime_log.log('plugin_event', channel=key, type=typ, command_id=event.get('command_id',''), segment_id=event.get('segment_id'), message=event.get('message',''))


def scan_downloads():
    """Lightweight local-file recovery for Flow downloads.

    The browser extension may know that a download finished without being able to
    provide a native absolute path.  Match Studio's exact expected filename in the
    configured channel folders *or* the top-level macOS Downloads folder.  No ffprobe,
    media decoding or content inspection happens here.
    """
    configured_root=Path(ensure_defaults()).expanduser()
    roots=[]
    def add_root(path, recursive_channels=False):
        try:
            p=Path(path).expanduser()
            key=str(p)
            if key not in {str(x[0]) for x in roots}:
                roots.append((p,recursive_channels))
        except Exception:
            pass
    add_root(configured_root, True)
    try:
        add_root(repo.get_setting('flow_download_root',''), True)
    except Exception:
        pass
    add_root(Path.home()/'Downloads'/'FlowStudio_Channels', True)
    # Plugin builds before v1.2 could write FlowStudio_Channels/FlowStudio_Channels/CHx; keep reading it.
    add_root(Path.home()/'Downloads'/'FlowStudio_Channels'/'FlowStudio_Channels', True)
    add_root(configured_root/'FlowStudio_Channels', True)
    add_root(Path.home()/'Downloads', False)

    # One DB read per scan. Expected filenames contain S<segment_id>, so they are
    # globally unique in normal operation even if Chrome saved a file outside CHx.
    dispatches=list(repo.list_dispatches())
    channels=list(repo.list_channel_pool(enabled_only=False))
    all_channels=list(repo.list_channel_pool(enabled_only=False))
    channel_map={str(c['channel_key']):c for c in all_channels}
    # Replaced segments reuse filenames; only command-bearing receipts may bind
    # their new output. A bare filename cannot identify a late old render.
    from app.core.database import connect
    with connect() as con:
        replaced_segments={int(r[0]) for r in con.execute("SELECT DISTINCT o.segment_id FROM flow_obsolete_segments o JOIN flow_segments fs ON fs.id=o.segment_id WHERE fs.generation_command<>''")}
    exact_by_channel={}
    exact_any={}
    latest_dispatch={}
    for d in dispatches:
        sid=int(d['segment_id'])
        if sid not in latest_dispatch or int(d['id'])>latest_dispatch[sid]:
            latest_dispatch[sid]=int(d['id'])
    for d in sorted(dispatches, key=lambda d:int(d['id'])):
        if int(d['segment_id']) in replaced_segments:
            # Recovery only: the newest dispatch of a replaced segment may bind its own exact
            # Qnn file when the browser reported a download failure (e.g. DOWNLOAD_PATH_MISMATCH)
            # although the file really exists. Older/cancelled renders still cannot bind.
            if not (str(d['status'] or '')=='failed' and int(d['id'])==latest_dispatch[int(d['segment_id'])]):
                continue
        if str(d['command_id']) != str(d['generation_command']):
            continue
        name=unicodedata.normalize('NFC',str(d['expected_filename'] or '').strip())
        if not name:
            continue
        key=str(d['channel_key'] or '')
        exact_by_channel[(key,name)]=d
        prev=exact_any.get(name)
        if prev is None or int(d['id'])>int(prev['id']):
            exact_any[name]=d

    duplicate_re=re.compile(r' \(\d+\)(?=\.[^.]+$)')
    matched=[]; seen_paths=set()
    def consider(p, channel_hint=''):
        try:
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS or p.name.endswith('.crdownload'):
                return
            st=p.stat()
            if st.st_size<=0:
                return
        except OSError:
            return
        ps=str(p)
        if ps in seen_paths:
            return
        seen_paths.add(ps)
        name=unicodedata.normalize('NFC',p.name)
        canonical=duplicate_re.sub('',name)
        d=(exact_by_channel.get((channel_hint,name)) or exact_by_channel.get((channel_hint,canonical))
           or exact_any.get(name) or exact_any.get(canonical))
        if not d:
            token=f'{channel_hint}|{name}|{st.st_size}'
            if token not in _UNMATCHED_LOGGED:
                _UNMATCHED_LOGGED.add(token)
                if len(_UNMATCHED_LOGGED)>1500:
                    _UNMATCHED_LOGGED.clear();_UNMATCHED_LOGGED.add(token)
                runtime_log.log('channel_file_unmatched',level='WARNING',channel=channel_hint,path=ps,filename=name,size=st.st_size)
            return
        # Never re-bind an already detected dispatch to the same path.
        if str(d['status'] or '')=='detected' and str(d['download_path'] or '')==ps:
            return
        # ...nor flip an already detected dispatch between duplicate copies of the same filename in
        # different folders (that re-ran acceptance and reloaded the UI on every scan).
        if str(d['status'] or '')=='detected' and str(d['download_path'] or '') and Path(str(d['download_path'])).is_file():
            return
        ch=channel_map.get(str(d['channel_key']))
        if ch is None:
            return
        matched.append((d,ch,p))

    for root,recursive_channels in roots:
        if not root.exists():
            continue
        # Direct files catch Chrome's default ~/Downloads destination.
        try:
            for p in root.iterdir():
                if p.is_file():
                    consider(p,'')
        except OSError:
            pass
        if recursive_channels:
            # Only the known channel folders are scanned; no expensive deep walk.
            for ch in channels:
                key=str(ch['channel_key']); folder=root/str(ch['download_subdir'] or key)
                if not folder.exists():
                    continue
                try:
                    for p in folder.iterdir():
                        consider(p,key)
                except OSError:
                    pass
    return matched


def available_channels(role='normal', *, work_date=None):
    """One active submission wave per channel; old renders/downloads keep their ownership."""
    from urllib.parse import urlsplit, urlunsplit
    ensure_defaults()
    recovered=repo.recover_orphaned_waiting_commands(work_date=work_date)
    if recovered.get('segments') or recovered.get('channels'):
        runtime_log.log('orphaned_waiting_tasks_self_healed',segments=recovered.get('segments',[]),channels=recovered.get('channels',[]))
    healed=repo.heal_recent_online_channels()
    if healed:
        runtime_log.log('live_idle_channels_health_restored',channels=healed)
    repo.release_finished_channel_commands()
    released=repo.release_submitted_channel_commands()
    if released:
        runtime_log.log('channel_submission_slots_self_healed',channels=released)
    channels=list(repo.list_channel_pool(enabled_only=True))
    urls={}
    for c in channels:
        raw=str(c['collection_url'] or '').strip()
        if not raw: continue
        u=urlsplit(raw)
        key=urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip('/'),u.query,''))
        urls.setdefault(key,[]).append(str(c['channel_key']))
    result=[]
    for c in channels:
        raw=str(c['collection_url'] or '').strip()
        if c['role']!=role or not raw or not repo.channel_is_usable(c) or c['task_command_id']:
            continue
        if not repo.channel_is_alive(c):
            continue   # tab not heartbeating: never hand it new work, healthy channels take it
        u=urlsplit(raw)
        key=urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip('/'),u.query,''))
        if len(urls[key])>1:
            continue
        result.append(c)
    try:
        from app.services import pause_control
        paused=pause_control.paused_channels()
        if paused:result=[c for c in result if str(c['channel_key']) not in paused]
    except Exception:
        pass
    return result


def resolve_task_image_path(task, work_date=None):
    """Readability check. An already-initialised cache wins; original is only needed for first init."""
    from app.services import flow_image_cache
    try:
        cached=flow_image_cache.resolve_for_task(task,work_date)
        if cached:return cached
    except flow_image_cache.FlowImageCacheError as exc:
        raise ValueError(f"任务 {task.get('segment_id')} 的参考图缓存异常：{exc}") from exc
    from app.services.image_assets import resolve_path
    try:
        return resolve_path(task.get('image_path') or '')
    except Exception as exc:
        raise ValueError(f"任务 {task.get('segment_id')} 的参考图无法读取：{exc}") from exc


def prepare_task_images(tasks, work_date=None):
    """Resolve each task image to its current flow_upload_images cache file.

    The original is copied only on first initialisation (see flow_image_cache);
    an existing cache file is never overwritten by the original.
    """
    from app.services import flow_image_cache as fic
    staged=[]
    for task in tasks:
        t=dict(task)
        row=fic.ensure_flow_upload_cache({'source_path':str(t.get('image_path') or '')},t,work_date)
        path=fic.resolve_flow_upload_image(row['image_id'])
        t['image_path']=str(flow_upload_alias(path))
        t['image_id']=row['image_id']
        t['cache_revision']=row.get('cache_revision')
        staged.append(t)
    return staged


_ALIAS_MEMO={}
def flow_upload_alias(cache_path):
    """Unique upload filename for Flow.

    The plugin identifies an image inside a Flow collection page by FILE NAME. Business names such as
    '02.jpg' repeat across hosts/dates, so two different images would collide on one page and a task
    could silently generate from the wrong picture. The cache keeps its human-friendly layout; what
    is handed to the plugin is a hard link (or copy) named '<stem>-<content hash>.<ext>' in a derived
    folder. The name changes whenever the picture's bytes change and never repeats for different pictures.
    """
    import os, shutil
    from app.services import flow_image_cache as fic
    src=Path(cache_path)
    st=src.stat(); memo_key=(str(src),st.st_size,st.st_mtime_ns)
    hit=_ALIAS_MEMO.get(memo_key)
    if hit and Path(hit).is_file():return Path(hit)
    h=hashlib.sha256()
    with src.open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''):h.update(chunk)
    stem=safe_name(src.stem,40) or 'img'
    folder=fic.cache_root().parent/'flow_upload_names'
    folder.mkdir(parents=True,exist_ok=True)
    alias=folder/f"{stem}-{h.hexdigest()[:16]}{src.suffix.lower()}"
    if not (alias.is_file() and alias.stat().st_size==st.st_size):
        tmp=alias.with_name(alias.name+'.tmp')
        try:tmp.unlink()
        except OSError:pass
        try:os.link(src,tmp)
        except OSError:shutil.copy2(src,tmp)
        os.replace(tmp,alias)
    if len(_ALIAS_MEMO)>2000:_ALIAS_MEMO.clear()
    _ALIAS_MEMO[memo_key]=str(alias)
    return alias


def recover_unpublished_auto_dispatches(*, work_date=None):
    """Release only provably unregistered local plans; never retry a published job."""
    import json
    from app.core.database import connect
    recovered=[]
    allowed_segments=None
    if work_date is not None:
        from app.core.work_dates import read_connection
        with read_connection(work_date) as scoped:
            allowed_segments={int(r[0]) for r in scoped.execute("SELECT id FROM flow_segments").fetchall()}
        if not allowed_segments:
            return []
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT value FROM app_settings WHERE key='flow_host_jobs_v124'").fetchone()
        try:published={str(j.get('command_id') or '') for j in json.loads(row[0] if row else '[]')}
        except (ValueError,TypeError):return []
        for ch in con.execute("SELECT channel_key,task_command_id FROM flow_channel_pool WHERE task_command_id LIKE 'auto-pool-%'").fetchall():
            cmd=ch['task_command_id']
            if cmd in published:continue
            ds=con.execute('SELECT segment_id,status,submitted_at FROM flow_dispatches WHERE command_id=?',(cmd,)).fetchall()
            if allowed_segments is not None:
                scoped_ds=[d for d in ds if int(d['segment_id']) in allowed_segments]
                # A command that has no dispatch belonging to the selected date is not
                # this date's business. Never mutate another date while browsing here.
                if not scoped_ds:
                    continue
                # Mixed-date command is treated as occupied and left untouched.
                if len(scoped_ds)!=len(ds):
                    continue
                ds=scoped_ds
            if not ds or any(d['status'] not in ('queued','planned') or d['submitted_at'] for d in ds):continue
            if any(con.execute("SELECT 1 FROM flow_segments WHERE id=? AND (generation_command<>'' OR flow_output_path<>'' OR qc_status<>'待质检')",(d['segment_id'],)).fetchone() for d in ds):continue
            if con.execute('SELECT 1 FROM flow_outputs WHERE command_id=?',(cmd,)).fetchone():continue
            if any(con.execute('SELECT 1 FROM '+table+' WHERE payload LIKE ?',('%'+cmd+'%',)).fetchone() for table in ('flow_receipts','flow_pending_downloads')):continue
            con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error='恢复未发布的本地计划；原记录保留' WHERE command_id=?",(cmd,))
            con.execute("UPDATE flow_channel_pool SET task_command_id='',upload_command_id=CASE WHEN upload_command_id=? THEN '' ELSE upload_command_id END,upload_state=CASE WHEN upload_command_id=? THEN 'idle' ELSE upload_state END WHERE channel_key=?",(cmd,cmd,ch['channel_key']))
            recovered.append(cmd)
    if recovered:runtime_log.log('unpublished_auto_plans_recovered',commands=recovered)
    return recovered


def redo_home_channel(segment_id):
    """Normal channel that last generated this segment (QC-returned work goes back there)."""
    try:
        from app.core.database import connect
        with connect() as con:
            row=con.execute("""SELECT d.channel_key FROM flow_dispatches d JOIN flow_channel_pool p ON p.channel_key=d.channel_key
                               WHERE d.segment_id=? AND p.role='normal' ORDER BY d.id DESC LIMIT 1""",(int(segment_id),)).fetchone()
        return str(row[0]) if row else ''
    except Exception as exc:
        runtime_log.log('redo_home_channel_failed',level='WARNING',segment_id=segment_id,error=str(exc))
        return ''


def channel_usable_now(key):
    """True when the channel exists, is enabled and not quarantined (it may just be busy)."""
    row=repo.get_channel_pool(channel_key=key)
    return bool(row and repo.channel_is_usable(row) and repo.channel_is_alive(row))

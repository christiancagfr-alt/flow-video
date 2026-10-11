"""Existing automatic production logic, executed by one serial background lane.
No Qt objects are referenced by this module. Date and generation count are captured
on submission; task planning, timeout rules and release scheduling are unchanged.
"""
import time
from app.services.eye_states import OPEN_EYE_PROMPT
from app.core import repository as repo, work_dates
from app.services import channel_pool, runtime_log, pipeline_orchestrator, workflow
from app.services.perf_diagnostics import measured

class StatusText:
    def __init__(self):
        self.text = ''
        self.tooltip = ''
    def setText(self, value): self.text = value
    def setToolTip(self, value): self.tooltip = value

class ProductionWorker:
    def __init__(self, bridge):
        self.bridge = bridge
        self.day = None
        self.rounds = 1
        self.auto_production_state = StatusText()
        self.dirty = False

    @measured('scheduler_tick')
    def run(self, key):
        kind, self.day, self.rounds = key
        self.dirty = False
        if self.day != work_dates.active():
            return {'day':self.day,'text':'','tooltip':'','dirty':False}
        try:
            dead_cmds=repo.failover_dead_channel_queues()
            if dead_cmds:
                self.bridge.cancel_host_commands(dead_cmds)
                runtime_log.log('dead_channel_queue_failover',level='WARNING',commands=dead_cmds)
                self.dirty=True
        except Exception as exc:
            runtime_log.log('dead_channel_failover_failed',level='ERROR',error=str(exc))
        try:
            retired=repo.retire_ancient_submitted()
            if retired:
                runtime_log.log('ancient_submitted_retired',level='WARNING',count=retired)
                self.dirty=True
        except Exception as exc:
            runtime_log.log('ancient_submitted_retire_failed',level='ERROR',error=str(exc))
        try:
            adopted=repo.adopt_orphan_outputs()
            if adopted:
                runtime_log.log('orphan_outputs_adopted',level='WARNING',segments=adopted)
                self.dirty=True
        except Exception as exc:
            runtime_log.log('orphan_output_adopt_failed',level='ERROR',error=str(exc))
        if kind == 'watchdog':
            self.bridge.ensure_running()
            pipeline_orchestrator.watchdog_tick(time.time())
        elif not self.bridge.generation_control().get('paused'):
            if kind == 'redo':
                self._dispatch_redo_ready_tasks()
            else:
                self._auto_retry_timed_out_active_commands(self.day)
                audit = repo.reconcile_selected_date_unfinished_tasks(work_date=self.day)
                self._last_auto_dispatch_audit = audit
                if audit.get('requeued') or audit.get('restored'):
                    runtime_log.log('selected_date_unfinished_reconciled',work_date=self.day,
                        unfinished=audit.get('unfinished',0),dispatchable=audit.get('dispatchable',0),
                        requeued=audit.get('requeued',[]),restored=audit.get('restored',[]))
                self._auto_reclaim_unclaimed_dispatches(self.day)
                self._auto_dispatch_ready_tasks(self.day,audit=audit)
        else:
            self.auto_production_state.setText('Ⅱ 自动生产已暂停')
        return {'day':self.day,'text':self.auto_production_state.text,
                'tooltip':self.auto_production_state.tooltip,'dirty':self.dirty}

    @staticmethod
    def _record_image_block(task, exc):
        # Keep this task queued so correcting the file allows the next tick to proceed.
        # Persist the reason so the runtime dialog can expose it before any dispatch.
        from app.core.database import connect
        with connect() as con:
            con.execute("UPDATE flow_segments SET flow_error=? WHERE id=? AND coalesce(generation_command,'')='' AND flow_status IN ('待生成','失败','下载失败')",
                        ('本地图片不可用：'+str(exc),task['segment_id']))

    @staticmethod
    def _retry_exhausted(task):
        """True for segments the timeout cap already stopped; they need a manual retry.

        Without this, status 失败 is dispatchable and the cap was undone within seconds,
        regenerating (and paying for) the same segment every timeout period.
        """
        try:
            err=str(task.get('flow_error') or '')
            return str(task.get('flow_status') or '')=='失败' and '次生成超时，已停止自动重试' in err
        except Exception:
            return False

    def _auto_retry_timed_out_active_commands(self, scope_day):
        """A delayed receipt is not permission to regenerate a paid or failed task."""
        now=time.time()
        if now-getattr(self,'_last_active_progress_scan',0)>=60:
            self._last_active_progress_scan=now
            try:self.bridge.request_progress_scan()
            except Exception as exc:runtime_log.log('progress_scan_failed',level='WARNING',error=str(exc))
        return 0

    def _auto_reclaim_unclaimed_dispatches(self, scope_day):
        """Return a released-but-never-claimed wave to the central waiting pool.

        This is deliberately narrower than timeout retry: a browser command owner or any
        submitted/download receipt blocks reclamation, and active image uploads are also
        protected.  Therefore automatic refill cannot duplicate work that may already be
        inside Flow.
        """
        try:
            threshold=max(30,int(repo.get_setting('flow_auto_reclaim_unclaimed_seconds','60') or 60))
        except Exception:
            threshold=60
        rows=list(repo.list_auto_reclaimable_unsubmitted_dispatches(now=time.time(),threshold_seconds=threshold,work_date=scope_day))
        if not rows:
            return 0
        grouped={}
        for row in rows:
            grouped.setdefault(str(row['command_id'] or ''),[]).append(int(row['id']))
        recovered=0
        for command,dispatch_ids in grouped.items():
            if not command:
                continue
            # Remove the executable bridge job first. A delayed browser pull can no longer
            # start this obsolete wave after its segments have returned to WAITING.
            try:
                self.bridge.cancel_host_commands([command])
            except Exception as exc:
                runtime_log.log('auto_refill_cancel_old_command_failed',level='WARNING',command_id=command,error=str(exc))
                continue
            moved=repo.requeue_unsubmitted_dispatches(dispatch_ids,work_date=scope_day)
            recovered+=int(moved or 0)
            if moved:
                runtime_log.log('auto_refill_unclaimed_wave_recovered',work_date=scope_day,command_id=command,dispatches=len(dispatch_ids),segments=moved)
        if recovered:
            repo.release_finished_channel_commands()
        return recovered

    def _auto_dispatch_ready_tasks(self, scope_day=None, audit=None):
        if scope_day is None:
            from app.core import work_dates as _work_dates
            scope_day=self.day
        # Automatic production must consume the GLOBAL approved queue, not the
        # recipient/host currently selected in the Flow Center UI. Otherwise a
        # prompt submitted from GPT can sit forever when another recipient/host
        # is selected on this page.
        from app.services import task_recovery
        task_recovery.restore_normal_tasks(work_date=scope_day)
        # QC-returned segments go back to the channel that generated them BEFORE new work
        # is planned, so a freed channel's next batch starts with its returned segments.
        try:
            self._dispatch_redo_ready_tasks()
        except Exception as exc:
            runtime_log.log('redo_dispatch_failed',level='ERROR',error=str(exc))
        # Repair only provably unsubmitted/orphaned local ownership before reading the
        # queue.  This makes waiting rows eligible again without touching any submitted,
        # rendering, downloading or QC-owned task.
        preconfirm=repo.recover_unconfirmed_preclick_dispatches(work_date=scope_day)
        if preconfirm.get('segments') or preconfirm.get('channels'):
            runtime_log.log('auto_dispatch_false_submitted_recovered',work_date=scope_day,segments=preconfirm.get('segments',[]),channels=preconfirm.get('channels',[]),commands=preconfirm.get('commands',[]))
        recovered=repo.recover_orphaned_waiting_commands(work_date=scope_day)
        if recovered.get('segments') or recovered.get('channels'):
            runtime_log.log('auto_dispatch_orphan_recovered',work_date=scope_day,segments=recovered.get('segments',[]),channels=recovered.get('channels',[]))
        self.bridge.request_ch2_rebalance()
        rows=[dict(t) for t in repo.list_flow_tasks(None,None,'全部', work_date=scope_day)]
        # V0.13.5.87: every 2-second scheduler pass audits production progress by AI host,
        # independent of the Flow Center's current recipient/host filter. This keeps the
        # central pool authoritative: any unfinished host with dispatchable segments will
        # be planned onto currently idle normal channels in this same pass.
        host_scan={}
        for row in rows:
            hid=int(row.get('host_id') or 0)
            if not hid: continue
            bucket=host_scan.setdefault(hid,{'host_id':hid,'host_name':str(row.get('host_name') or ''),'total':0,'complete':0,'active':0,'waiting':0})
            bucket['total']+=1
            status=str(row.get('flow_status') or '待生成')
            has_output=bool(str(row.get('flow_output_path') or '').strip())
            if status=='已完成' or has_output: bucket['complete']+=1
            elif str(row.get('generation_command') or '').strip(): bucket['active']+=1
            else: bucket['waiting']+=1
        unfinished_hosts=[v for v in host_scan.values() if v['complete']<v['total']]
        progress_sig=tuple((v['host_id'],v['complete'],v['active'],v['waiting'],v['total']) for v in sorted(unfinished_hosts,key=lambda x:x['host_id']))
        if progress_sig!=getattr(self,'_last_auto_host_progress_signature',None):
            self._last_auto_host_progress_signature=progress_sig
            runtime_log.log('auto_production_host_progress_scan',work_date=scope_day,unfinished_hosts=unfinished_hosts,
                            unfinished_host_count=len(unfinished_hosts),scan_interval_seconds=2,timeout_seconds=300)
        from app.services import host_priority
        redo_ids=workflow.redo_ids(work_date=scope_day)
        tasks=[]
        for t in rows:
            if int(t['segment_id']) in redo_ids:
                continue
            if str(t['generation_command'] or ''):
                continue
            if self._retry_exhausted(t):
                continue
            if str(t['flow_status'] or '待生成') in ('待生成','已准备'):
                tasks.append(t)
        tasks=host_priority.apply(tasks,rows,scope_day)
        if not tasks:
            if hasattr(self,'auto_production_state'):
                audit=audit or repo.reconcile_selected_date_unfinished_tasks(work_date=scope_day)
                unfinished=int(audit.get('unfinished',0) or 0)
                active=int(audit.get('active',0) or 0)
                failed=int(audit.get('failed',0) or 0)
                download_failed=int(audit.get('download_failed',0) or 0)
                if unfinished:
                    self.auto_production_state.setText(f'● {scope_day} 已检查 · 未完成 {unfinished} · 当前可派发 0')
                    self.auto_production_state.setToolTip(
                        f'当前日期已自动扫描。运行/等待结果 {active}，生成失败 {failed}，下载失败 {download_failed}。'
                        '有真实提交回执的任务不会自动重复生成。'
                    )
                else:
                    self.auto_production_state.setText(f'● {scope_day} 已检查 · 没有等待任务')
                    self.auto_production_state.setToolTip('自动调度器每 2 秒只检查当前选中日期。')
            return 0

        # Opt-in dependency check; ordinary tasks retain their original path.

        ready=[]; image_errors=[]
        for task in tasks:
            try:
                channel_pool.resolve_task_image_path(task)
                if task.get('TASK_TYPE','VIDEO')=='VIDEO':
                    from app.services import camera_aux
                    task=camera_aux.resolve(task)[0]
                ready.append(task)
            except Exception as exc:
                self._record_image_block(task,exc)
                image_errors.append(str(exc))
                runtime_log.log('auto_dispatch_image_blocked',level='ERROR',segment_id=task['segment_id'],error=str(exc))
        tasks=ready
        if image_errors and hasattr(self,'auto_production_state'):
            self.auto_production_state.setText(f'⚠ {len(image_errors)} 条图片待修复')
            self.auto_production_state.setToolTip('\n'.join(image_errors[:10]))
        if not tasks:return 0

        # Only configured normal channels participate in unattended dispatch.
        # Unconfigured slots (for example CH4-CH7 when the user only uses three
        # browser tabs) must NOT block every submitted video task.
        channel_pool.recover_unpublished_auto_dispatches(work_date=scope_day)
        healed=repo.heal_recent_online_channels()
        if healed:
            runtime_log.log('auto_dispatch_live_channel_healed',channels=healed)
        all_channels=list(channel_pool.available_channels('normal',work_date=scope_day))
        channels=[]
        seen={}
        for ch in all_channels:
            url=str(ch['collection_url'] or '').strip()
            if not url:
                continue
            norm=url.split('#',1)[0].strip().lower()
            if norm in seen:
                runtime_log.log('auto_dispatch_channel_ignored',level='WARNING',reason='duplicate_channel_url',channel=ch['channel_key'],duplicate_of=seen[norm])
                continue
            seen[norm]=str(ch['channel_key'])
            channels.append(ch)
        if not channels:
            configured=[dict(c) for c in repo.list_channel_pool(enabled_only=True) if str(c['role'])=='normal' and str(c['collection_url'] or '').strip()]
            detail=[{'channel':str(c['channel_key']),'online_age':round(time.time()-float(c['last_seen'] or 0),1) if c['last_seen'] else None,
                     'task_command_id':str(c['task_command_id'] or ''),'health':str(c['health_status'] or ''),
                     'quarantine_until':float(c['quarantine_until'] or 0)} for c in configured]
            if hasattr(self,'auto_production_state'):
                self.auto_production_state.setText(f'等待可用通道 · {len(tasks)} 条任务保留 · 已配置 {len(configured)} 个普通通道')
                self.auto_production_state.setToolTip('调度器没有发现可领取任务的普通通道；详细原因已写入运行日志。')
            runtime_log.log('auto_dispatch_waiting_for_channel',level='WARNING',reason='no_available_configured_channel',pending=len(tasks),channels=detail)
            return 0
        pressure=pipeline_orchestrator.backpressure_state()
        if pressure.get('throttled'):
            # Retaining downstream data must not silently stop authorized new work.
            # Backpressure remains advisory, matching the service's stated contract.
            runtime_log.log('auto_dispatch_backlog_advisory',level='WARNING',reason=pressure.get('reason',''))
        try:
            total_normal=len({str(c['collection_url'] or '').split('#',1)[0].strip().lower() for c in repo.list_channel_pool(enabled_only=True)
                              if str(c['role'])=='normal' and str(c['collection_url'] or '').strip() and repo.channel_is_usable(c)})
        except Exception:
            total_normal=len(channels)
        plan=channel_pool.plan(tasks,channels,total_channels=max(total_normal,len(channels))); jobs=[]; stamp=str(time.time_ns())
        try: rounds=max(1,min(4,int(self.rounds or 1)))
        except Exception: rounds=1
        for ch in channels:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks: continue
            cmd=f"auto-pool-{ch['channel_key']}-{stamp}"
            prelim=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,dispatch_tasks=True,work_date=scope_day)
            need_upload=not bool(prelim['upload_proof']['verified'])
            job=self._make_pool_job(ch,ctasks,cmd,generation_count=rounds,execute_upload=need_upload,dispatch_tasks=True,work_date=scope_day)
            jobs.append(job)
        if not jobs:
            # Never silently leave visible WAITING rows with idle channels. Record the
            # exact planner state so the next 2-second watchdog tick can self-heal.
            runtime_log.log('auto_dispatch_zero_plan',level='WARNING',work_date=scope_day,pending=len(tasks),channels=[str(c['channel_key']) for c in channels])
            if hasattr(self,'auto_production_state'):
                self.auto_production_state.setText(f'⚠ {scope_day} 有 {len(tasks)} 条等待任务 · 调度计划为空，2秒后自动重试')
            return 0
        for job in jobs:
            cmd=job['command_id'];channel_key=job['channel_key']
            repo.set_channel_pool_task_command(channel_key,cmd)
            if job['execute_upload']:
                repo.set_channel_pool_runtime(channel_key,'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            for order,t in enumerate(job['tasks'],1):
                repo.assign_flow_channel(t['segment_id'],channel_key)
                for r in range(1,rounds+1):
                    stem=channel_pool.render_stem(t,r,rounds)
                    repo.create_dispatch(t['segment_id'],channel_key,cmd,order,r,stem,stem+'.mp4','queued')
        lo,hi=channel_pool.stagger_bounds()
        jobs=channel_pool.apply_random_release_schedule(jobs,minimum=lo,maximum=hi)
        for job in jobs:
            repo.set_dispatch_release_for_command(job['command_id'],job.get('release_at') or 0)
        self.bridge.publish_host_jobs(jobs)
        if hasattr(self,'auto_production_state'):
            self.auto_production_state.setText(f"已发送 {sum(len(j['tasks']) for j in jobs)} 条到插件队列（每通道最多5条），剩余 {len(tasks)-sum(len(j['tasks']) for j in jobs)} 条等待空闲通道"+(f' · {len(image_errors)} 条图片异常' if image_errors else ''))
            self.auto_production_state.setToolTip('\n'.join(image_errors[:10]) if image_errors else '等待网页插件领取；运行中任务与历史记录保留。')
        runtime_log.log('auto_flow_dispatch',jobs=len(jobs),segments=sum(len(j['tasks']) for j in jobs))
        self.dirty = True
        return sum(len(j['tasks']) for j in jobs)

    def _pool_scope_tasks(self, redo=False):
        rid=self.recipient.currentData() if hasattr(self,'recipient') else None
        hid=self.host.currentData() if hasattr(self,'host') else None
        rows=[dict(t) for t in repo.list_flow_tasks(None if redo else rid,None if redo else hid,'全部', work_date=self.day)]
        redo_ids=workflow.redo_ids(work_date=self.day)
        if redo:
            return [t for t in rows if int(t['segment_id']) in redo_ids and t['flow_status'] in ('待生成','已准备') and not str(t['generation_command'] or '')]
        out=[]
        for t in rows:
            if int(t['segment_id']) in redo_ids: continue
            status=t['flow_status'] or '待生成'; command=str(t['generation_command'] or '')
            if command: continue
            if status in ('待生成','已准备'): out.append(t)
        return out

    def _make_pool_job(self,ch,tasks,command_id,generation_count=None,execute_upload=False,dispatch_tasks=False,retry_only=False,work_date=None):
        from app.services.text_processing import flow_timing
        tasks=channel_pool.prepare_task_images(tasks,work_date or self.day)
        from app.services import camera_aux
        tasks=[camera_aux.resolve(t)[0] if t.get('TASK_TYPE','VIDEO')=='VIDEO' else t for t in tasks]
        paths=channel_pool.unique_images(tasks)
        image_files,fp=channel_pool.image_payload(paths)
        try: rounds=int(generation_count if generation_count is not None else (self.rounds or 1))
        except Exception: rounds=1
        rounds=max(1,min(4,rounds))
        payload=[]
        for order,t in enumerate(tasks,1):
            base=channel_pool.task_stem(t,1)
            shot_match=__import__('re').search(r'\[辅助图\] (SHOT_[0-9]+):',t.get('foreign_text',''))
            shot_id = shot_match.group(1) if shot_match else ''
            broll_id = ""
            import re
            if t.get('TASK_TYPE') == 'BROLL_IMAGE':
                m = re.search(r'\[B-roll\] (.*?) for', t.get('foreign_text', ''))
                if m: broll_id = m.group(1).strip()

            if rounds>1 and base.endswith('-R01'): base=base[:-4]
            exact_names=[channel_pool.render_stem(t,r,rounds) for r in range(1,rounds+1)]
            
            final_image_path = t['image_path'] or ''

            payload.append({
                'segment_id':int(t['segment_id']), 'task_id':f"{int(t['video_seq']):02d}-{int(t['seg_seq']):02d}",
                'task_name':base, 'download_stem':base, 'download_names':exact_names, 'dispatch_order':order,
                **__import__('app.services.duration_choices',fromlist=['dispatch_timing']).dispatch_timing(t), 'dialogue':t['foreign_text'] or '', 'prompt':t['prompt'] or '', 'image_path':final_image_path,
                'generation_mode':repo.normalize_generation_mode(t['generation_mode'] if 'generation_mode' in t.keys() else 'FRAME'),
                'open_eye_prompt': OPEN_EYE_PROMPT if t.get('performance_mode') == 'TALKING' and t.get('TASK_TYPE','VIDEO')=='VIDEO' else '',
                'TASK_TYPE':t.get('TASK_TYPE', 'VIDEO'),
                'task_type':t.get('TASK_TYPE', 'VIDEO'),
                'VIDEO_ID':int(t['video_id']), 'video_id':int(t['video_id']),
                'SHOT_ID': shot_id, 'BROLL_ID': broll_id, 'shot_id':shot_id, 'broll_id':broll_id,
                'end_image_path': t.get('end_image_path',''), 'material_image_paths':list(t.get('material_image_paths') or []), 'camera_motion':t.get('camera_motion'),
                'document_number':int(t['video_seq']), 'host_id':int(t['host_id']), 'host_name':t['host_name'],
                'recipient_id':int(t['recipient_id']), 'recipient_name':t['recipient_name'],
                'video_seq':int(t['video_seq']), 'seg_seq':int(t['seg_seq']), 'flow_retry_count':int(t['flow_retry_count'] or 0)
            })
        verified=(str(ch['upload_state'] or '')=='verified' and str(ch['upload_fingerprint'] or '')==fp and (not paths or int(ch['images_uploaded'] or 0)>=len(paths)) and bool(ch['upload_verified_at']))
        footage='MIXED' if any(str(t.get('generation_mode') or 'FRAME')=='MATERIAL' for t in payload) else 'VIDEO_FRAMES'
        return {
            'work_date':str(work_date or self.day),
            'recipient_id':0,'host_id':0,'recipient_name':'通道池','host_name':str(ch['channel_key']),
            'channel_id':int(ch['id']),'channel_key':str(ch['channel_key']),'channel_role':str(ch['role']),
            'browser_group':repo.channel_browser_group(str(ch['channel_key'])),
            'collection_url':str(ch['collection_url'] or ''),'collection_name':str(ch['channel_key']),
            'download_folder':channel_pool.relative_download_folder(ch),
            'image_count':len(paths),'image_files':image_files,'image_set_id':fp,'expected_image_names':[x['name'] for x in image_files],
            'upload_batches':[paths[i:i+20] for i in range(0,len(paths),20)],
            'upload_proof':{'verified':verified,'host_id':0,'channel_id':int(ch['id']),'image_set_id':str(ch['upload_fingerprint'] or '') if verified else '',
                            'collection_url':str(ch['collection_url'] or '') if verified else '', 'upload_command_id':str(ch['upload_command_id'] or '') if verified else '',
                            'uploaded':int(ch['images_uploaded'] or 0) if verified else 0,'verified_at':str(ch['upload_verified_at'] or '') if verified else ''},
            'tasks':payload,'settings':self.plugin_settings_payload(),'footage_mode':footage,'footage_mode_label':'混合' if footage=='MIXED' else ('帧' if footage=='VIDEO_FRAMES' else '素材'),
            'generation_count':rounds,'generation_count_label':str(rounds),'open_window':False,'focus_window':False,
            'execute_upload':bool(execute_upload),'dispatch_tasks':bool(dispatch_tasks),'auto_execute':bool(dispatch_tasks),'retry_only':bool(retry_only),
            'command_id':str(command_id),'studio_upload_state':str(ch['upload_state'] or 'idle'),'studio_upload_fingerprint':str(ch['upload_fingerprint'] or '')
        }

    def plugin_settings_payload(self):
        return {
            "aspect_ratio": repo.get_setting("flow_aspect_ratio", "9:16"),
            "interval": int(repo.get_setting("flow_plugin_interval", "20") or 20),
            "intervalRandom": int(repo.get_setting("flow_plugin_interval_random", "10") or 10),
            "maxLetterFor4s": int(repo.get_setting("flow_plugin_max4", "40") or 40),
            "maxLetterFor6s": int(repo.get_setting("flow_plugin_max6", "60") or 60),
            "maxLetterFor8s": int(repo.get_setting("flow_plugin_max8", "80") or 80),
            "videoModel": repo.get_setting(
                "flow_plugin_video_model", "veo_3_1_lite_low_priority"
            ) or "veo_3_1_lite_low_priority",
            "extraFolder": "none",
            "displayTextPreview": repo.get_setting("flow_plugin_preview", "1") != "0",
            "maxHeight": 300,
            "download": repo.get_setting("flow_plugin_download", "1") != "0",
            "capturePosition": float(repo.get_setting("flow_plugin_capture", "0.95") or 0.95),
        }

    def _dispatch_redo_ready_tasks(self):
        if bool(self.bridge.generation_control().get('paused')):
            return
        from app.services import task_recovery
        task_recovery.queue_failures()
        self.notify_blocked_tasks()
        from app.services import pause_control
        pending=pause_control.filter_tasks(self._pool_scope_tasks(True))   # paused hosts wait
        pending=[t for t in pending if not self._retry_exhausted(t)]
        readable=[]
        for task in pending:
            try:
                channel_pool.resolve_task_image_path(task)
                readable.append(task)
            except Exception as exc:
                self._record_image_block(task,exc)
                now_t=time.time(); memo=getattr(self,'_redo_block_log',None)
                if memo is None: memo=self._redo_block_log={}
                if now_t-memo.get(task['segment_id'],0)>120:    # log once per 2 min, not every tick
                    memo[task['segment_id']]=now_t
                    runtime_log.log('rework_image_blocked',level='ERROR',segment_id=task['segment_id'],error=str(exc))
        pending=readable
        if not pending:return
        # Rework has priority over new work. Only channels that are alive AND idle take part;
        # offline channels are ignored; each wave uses the same bounded capacity.
        normal_avail={str(c['channel_key']):c for c in channel_pool.available_channels('normal',work_date=self.day)}
        preferred=task_recovery.preferred_channels(pending)
        plan={};chosen={};fallback=[];waiting=0
        for task in pending:
            sid=task['segment_id']
            home=str(preferred.get(sid) or '')
            row=repo.get_channel_pool(channel_key=home) if home else None
            if not row or str(row['role'])!='normal':
                home=channel_pool.redo_home_channel(sid)      # last normal channel that generated it
            if home and home in normal_avail and len(plan.get(home,[]))<channel_pool.WAVE_CAP:
                plan.setdefault(home,[]).append(task);chosen[home]=normal_avail[home]
            else:
                fallback.append(task)   # home offline/busy -> any idle online channel
        for task in fallback:
            cands=[k for k in normal_avail if len(plan.get(k,[]))<channel_pool.WAVE_CAP]
            if not cands:
                waiting+=1;continue     # every online channel is busy: join the next batch of the first one to free up
            same=[k for k in cands if any(channel_pool._image_key(x)==channel_pool._image_key(task) for x in plan.get(k,[]))]
            k=same[0] if same else min(cands,key=lambda x:len(plan.get(x,[])))
            plan.setdefault(k,[]).append(task);chosen[k]=normal_avail[k]
        if waiting:
            runtime_log.log('rework_waiting_for_free_channel',count=waiting)
        # Fill each returned batch with the remaining same-image segments (image is already on that page).
        if self.rounds in (1,'1',None) and chosen:
            try:
                used={t['segment_id'] for v in plan.values() for t in v}
                pool=[t for t in pause_control.filter_tasks(self._pool_scope_tasks(False)) if str(t.get('TASK_TYPE') or 'VIDEO')=='VIDEO' and t['segment_id'] not in used]
                for k,v in plan.items():
                    imgs={channel_pool._image_key(t) for t in v}
                    for t in pool:
                        if len(v)>=channel_pool.WAVE_CAP:break
                        if t['segment_id'] in used or channel_pool._image_key(t) not in imgs:continue
                        try:
                            channel_pool.resolve_task_image_path(t)
                        except Exception:continue
                        v.append(t);used.add(t['segment_id'])
            except Exception as exc:
                runtime_log.log('rework_fill_failed',level='WARNING',error=str(exc))
        fast=list(chosen.values())
        if not fast:return
        jobs=[];stamp=str(time.time_ns())
        for ch in fast:
            ctasks=plan.get(str(ch['channel_key']),[])
            if not ctasks:continue
            cmd=f"redo-pool-{ch['channel_key']}-{stamp}"
            prelim=self._make_pool_job(ch,ctasks,cmd,generation_count=1,dispatch_tasks=True,retry_only=True)
            need_upload=not bool(prelim['upload_proof']['verified'])
            job=self._make_pool_job(ch,ctasks,cmd,generation_count=1,execute_upload=need_upload,dispatch_tasks=True,retry_only=True)
            job['force_media_scan']=True; job['release_at']=time.time()
            repo.set_channel_pool_task_command(ch['channel_key'],cmd)
            if job['execute_upload']:
                repo.set_channel_pool_runtime(ch['channel_key'],'queued',command_id=cmd,fingerprint=job['image_set_id'],uploaded=0,total=job['image_count'],error='')
            for order,t in enumerate(ctasks,1):
                repo.assign_flow_channel(t['segment_id'],ch['channel_key'])
                stem=channel_pool.task_stem(t,1)
                repo.create_dispatch(t['segment_id'],ch['channel_key'],cmd,order,1,stem,stem+'.mp4','queued')
            jobs.append(job)
            runtime_log.log('rework_dispatched_home_channel',browser=job.get('browser_group','A'),channel=ch['channel_key'],command_id=cmd,
                            tasks=[channel_pool.task_stem(t,1) for t in ctasks],upload=need_upload)
        if jobs:
            self.bridge.publish_host_jobs(jobs)
            self.dirty = True

    def notify_blocked_tasks(self):
        # This method is called by the realtime scheduler. A modal warning dialog here
        # becomes a popup storm when delayed duplicate failure receipts arrive. Keep the
        # failure cap and manual-retry state, but acknowledge new blocked tasks silently and
        # write one aggregated runtime-log entry instead. The tasks remain visible in
        # “运行任务 / 重试”.
        from app.core.database import connect
        with connect() as con:
            rows=con.execute('SELECT segment_id FROM flow_recovery WHERE blocked=1 AND notified=0').fetchall()
            if not rows:return
            con.execute('UPDATE flow_recovery SET notified=1 WHERE blocked=1 AND notified=0')
        runtime_log.log('generation_retry_cap_reached',level='WARNING',
                        segment_ids=[int(r[0]) for r in rows],count=len(rows),
                        message='累计生成失败 3 次，已停止自动重试；请在运行任务 / 重试中人工处理')

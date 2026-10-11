"""Read-only analytics projection for Flow Studio.

This module is intentionally isolated from production mutation APIs.  Every database
connection used by the analytics layer is query-only; the UI may aggregate/cache data
in memory, but it never changes tasks, queues, channels, QC, editing or delivery state.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import math
import time

from . import database
from . import repository as repo
from .work_dates import read_connection

EDITED = {'已剪辑', '待人工检查', '待导出', '导出中', '已导出', '已完成'}
EXPORTED = {'已导出', '已完成'}
UPLOADED = {'已上传', '已交付'}
FLOW_DONE = {'已完成'}
FLOW_FAILED = {'失败', '生成失败', '下载失败', '异常'}

_CACHE = {}
_CACHE_TTL = 3600.0


def _dt(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text, text.replace('Z', '+00:00')):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y/%m/%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def _secs(a, b):
    a, b = _dt(a), _dt(b)
    if not a or not b or b < a:
        return None
    return (b - a).total_seconds()


def _mean(values):
    vals = [float(v) for v in values if v is not None and float(v) >= 0]
    return sum(vals) / len(vals) if vals else None


def _day(value):
    text = str(value or '')
    try:
        return datetime.strptime(text[:10], '%Y-%m-%d').date()
    except Exception:
        return date.today()


def _table_exists(con, name):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


@contextmanager
def _global_readonly():
    """Open the live database in SQLite query-only mode."""
    con = database.connect()
    try:
        con.execute('PRAGMA query_only=ON')
        yield con
    finally:
        con.close()


def summarize(videos, segments):
    """Legacy complete-video projection retained for existing callers/tests."""
    grouped = defaultdict(dict)
    for part in segments:
        grouped[part['video_id']][part['id']] = part
    counts = Counter(); pending = Counter(); recipients = Counter(); names = {}; reasons = defaultdict(set)
    for vid, video in {v['video_id']: v for v in videos}.items():
        parts = list(grouped[vid].values())
        every = lambda check: bool(parts) and all(check(p) for p in parts)
        flags = {
            'total': True,
            'gpt': every(lambda p: bool(str(p.get('prompt') or '').strip())),
            'submitted': every(lambda p: bool(p.get('generation_command')) and p.get('flow_status') in ('已提交','生成中','下载中','已完成','下载失败')),
            'flow': every(lambda p: p.get('flow_status') == '已完成'),
            'downloaded': every(lambda p: p.get('download_valid')),
            'passed': every(lambda p: p.get('material_valid')),
            'edited': video.get('edit_status') in EDITED,
            'delivered': video.get('upload_status') in ('已上传', '已交付'),
        }
        counts.update(k for k, value in flags.items() if value)
        rejected = [p for p in parts if p.get('qc_status') == '退回']
        if rejected:
            counts['rework'] += 1
            for p in rejected:
                reasons[p.get('qc_reject_reason') or p.get('qc_note') or '其他'].add(vid)
        if any(p.get('flow_status') in FLOW_FAILED for p in parts):
            counts['flow_error'] += 1
        stage = repo.editing_stage(video.get('edit_status') or '', flags['passed'])
        pending[stage] += 1
        if flags['delivered']:
            rid = video['recipient_id']; recipients[rid] += 1; names[rid] = video['recipient_name']
        for key, label in [('gpt','等待提示词'),('submitted','等待提交Flow'),('flow','等待Flow完成'),
                           ('downloaded','等待下载'),('passed','等待质检'),('edited','等待剪辑'),('delivered','等待交付')]:
            if not flags[key]:
                counts['wait:'+label] += 1
                break
    waits = [(k[5:], n) for k,n in counts.items() if k.startswith('wait:')]
    waits += [(label,pending[key]) for key,label in [('WAITING_MATERIAL','素材待齐'),('READY_TO_EDIT','待剪辑'),('EDITING','剪辑中'),('REVIEW','待人工检查'),('EXPORTING','导出中'),('ERROR','剪辑异常')] if pending[key]]
    return dict(counts=counts, pending=pending,
                bottleneck=max(waits, key=lambda x:x[1]) if waits else None,
                recipients=[dict(recipient_name=names[r], n=n) for r,n in recipients.most_common()],
                reasons=[dict(reason=r,n=len(ids)) for r,ids in sorted(reasons.items(),key=lambda x:-len(x[1]))[:5]])


def snapshot(work_date):
    """Existing small snapshot.  Uses only the query-only date scope."""
    with read_connection(work_date) as con:
        videos = [dict(r) for r in con.execute('''SELECT v.id video_id,v.edit_status,v.upload_status,
            r.id recipient_id,r.name recipient_name FROM videos v
            JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id''')]
        segments = repo._current_edit_segments(con, [v['video_id'] for v in videos]) if videos else []
    return summarize(videos, segments)


# Keep analytics reason labels identical to the QC page buttons.
# This is intentionally display-only normalization: it never rewrites QC history.
QC_REASON_CATEGORIES = (
    '人物/面部异常', '口型/台词问题', '动作问题', '镜头问题',
    '声音问题', '画面穿帮', '人物一致性', '其他',
)


def _reason_category(raw):
    text = str(raw or '').strip()
    if not text:
        return '其他'
    low = text.lower()

    # Exact current QC labels first, so a button reason always appears unchanged.
    exact = {label.lower(): label for label in QC_REASON_CATEGORIES}
    exact.update({
        # Legacy statistics labels from versions before the QC reason list was unified.
        '人物动作异常': '动作问题',
        '口型错误': '口型/台词问题',
        '台词错误': '口型/台词问题',
        '声音异常': '声音问题',
        '背景改变': '画面穿帮',
        '人物变形': '人物/面部异常',
        '镜头异常': '镜头问题',
        'flow生成失败': '其他',
    })
    if low in exact:
        return exact[low]

    # Compatibility for older free-text reasons.  Every result is normalized to
    # one of the eight labels shown on the QC page.
    rules = [
        ('人物一致性', ('一致性','人物变化','人物不一致','服装变化','发型变化','identity','consisten')),
        ('口型/台词问题', ('口型','唇形','嘴型','lip','台词','文案','说错','漏词','多说','少说','script','word')),
        ('动作问题', ('动作','手势','姿势','movement','gesture','motion')),
        ('镜头问题', ('镜头','运镜','构图','切镜','机位','camera','shot')),
        ('声音问题', ('声音','音频','噪音','混响','回声','audio','voice','sound')),
        ('画面穿帮', ('穿帮','背景','场景','环境改变','画面异常','background','scene')),
        ('人物/面部异常', ('面部','五官','脸崩','变形','畸形','手指','人物异常','face','deform')),
    ]
    for label, needles in rules:
        if any(n in low for n in needles):
            return label
    return '其他'


def _union_seconds(intervals, start, end):
    clipped=[]
    for a,b in intervals:
        a,b=_dt(a),_dt(b)
        if not a or not b: continue
        a=max(a,start); b=min(b,end)
        if b>a: clipped.append((a,b))
    if not clipped: return 0.0
    clipped.sort(key=lambda x:x[0])
    total=0.0; ca,cb=clipped[0]
    for a,b in clipped[1:]:
        if a<=cb:
            cb=max(cb,b)
        else:
            total+=(cb-ca).total_seconds(); ca,cb=a,b
    total+=(cb-ca).total_seconds()
    return total


def _load_day(work_date):
    """Load one work-date cohort without mutating any persistent table."""
    with read_connection(work_date) as con:
        videos=[dict(r) for r in con.execute('''SELECT v.id video_id,v.seq video_seq,v.edit_status,v.edit_output_path,
            v.upload_status,v.upload_confirm_mode,v.upload_confirmed_at,
            h.id host_id,h.name host_name,r.id recipient_id,r.name recipient_name,r.created_at recipient_created_at
            FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id''')]
        segments=[dict(r) for r in con.execute('''SELECT fs.id,fs.video_id,fs.seg_seq,fs.prompt,fs.status,fs.model,
            fs.flow_status,fs.flow_error,fs.flow_attempts,fs.flow_retry_count,fs.generation_command,
            fs.flow_submitted_at,fs.flow_completed_at,fs.qc_status,fs.qc_note,fs.qc_reject_reason,fs.qc_decided_at,
            fs.input_tokens,fs.cached_tokens,fs.output_tokens,fs.cost_usd
            FROM flow_segments fs''')]
        decisions=[dict(r) for r in con.execute('SELECT * FROM qc_decisions ORDER BY created_at,id')] if _table_exists(con,'qc_decisions') else []
        dispatches=[dict(r) for r in con.execute('SELECT * FROM flow_dispatches ORDER BY id')] if _table_exists(con,'flow_dispatches') else []
        api_rows=[dict(r) for r in con.execute('SELECT * FROM api_usage_log ORDER BY created_at,id')] if _table_exists(con,'api_usage_log') else []
        editing=[]
        if _table_exists(con,'editing_history'):
            editing=[dict(r) for r in con.execute('''SELECT e.* FROM main.editing_history e
                JOIN videos v ON v.id=e.video_id ORDER BY e.id''')]
        recovery=[]
        if _table_exists(con,'flow_recovery'):
            recovery=[dict(r) for r in con.execute('''SELECT fr.* FROM main.flow_recovery fr
                JOIN flow_segments fs ON fs.id=fr.segment_id''')]
    return videos,segments,decisions,dispatches,api_rows,editing,recovery


def _day_projection(work_date):
    videos,segments,decisions,dispatches,api_rows,editing,recovery=_load_day(work_date)
    grouped=defaultdict(list)
    for s in segments: grouped[int(s['video_id'])].append(s)
    decisions_by_segment=defaultdict(list)
    for d in decisions: decisions_by_segment[int(d['segment_id'])].append(d)
    editing_by_video=defaultdict(list)
    for e in editing: editing_by_video[int(e['video_id'])].append(e)
    api_by_video=defaultdict(list)
    seg_to_video={int(s['id']):int(s['video_id']) for s in segments}
    for a in api_rows:
        sid=a.get('flow_segment_id')
        if sid in seg_to_video: api_by_video[seg_to_video[sid]].append(a)

    counts=Counter(); backlog=Counter(); backlog_waits=defaultdict(list)
    recipient=defaultdict(lambda: {'total':0,'completed':0})
    video_rows=[]; completion_times=[]; durations=[]
    stage_duration=defaultdict(list)
    host_acc=defaultdict(lambda:{'segments':0,'decided':0,'first_pass':0,'reworks':0,'attempts':[],'durations':[],'recipient_name':''})

    for v in videos:
        vid=int(v['video_id']); parts=grouped.get(vid,[])
        every=lambda fn: bool(parts) and all(fn(p) for p in parts)
        flags={
            'task':True,
            'prompt':every(lambda p: bool(str(p.get('prompt') or '').strip())),
            'flow':every(lambda p: str(p.get('flow_status') or '') in FLOW_DONE),
            'qc':every(lambda p: str(p.get('qc_status') or '')=='通过'),
            'edit':str(v.get('edit_status') or '') in EDITED,
            'export':str(v.get('edit_status') or '') in EXPORTED or (str(v.get('edit_output_path') or '').strip() and str(v.get('edit_status') or '') not in ('等待片段','素材待齐','待剪辑','等待剪辑')),
            'upload':str(v.get('upload_status') or '') in UPLOADED,
            'delivery':str(v.get('upload_status') or '')=='已交付',
        }
        counts['total']+=1
        for k,val in flags.items():
            if val: counts[k]+=1
        rid=int(v['recipient_id']); recipient[rid]['name']=v.get('recipient_name') or '未命名'; recipient[rid]['total']+=1
        if flags['export']: recipient[rid]['completed']+=1

        edit_records=editing_by_video.get(vid,[])
        completion=None
        for e in edit_records:
            if str(e.get('status') or '') in EXPORTED:
                candidate=_dt(e.get('updated_at') or e.get('created_at'))
                if candidate and (completion is None or candidate>completion): completion=candidate
        upload_at=_dt(v.get('upload_confirmed_at'))
        if not completion and flags['export'] and upload_at:
            completion=upload_at
        if completion: completion_times.append(completion)

        created=_dt(v.get('recipient_created_at'))
        first_api=min([_dt(a.get('created_at')) for a in api_by_video.get(vid,[]) if _dt(a.get('created_at'))] or [None])
        flow_submit=min([_dt(p.get('flow_submitted_at')) for p in parts if _dt(p.get('flow_submitted_at'))] or [None])
        flow_done=max([_dt(p.get('flow_completed_at')) for p in parts if _dt(p.get('flow_completed_at'))] or [None])
        qc_done=max([_dt(p.get('qc_decided_at')) for p in parts if _dt(p.get('qc_decided_at'))] or [None])
        edit_start=min([_dt(e.get('created_at')) for e in edit_records if _dt(e.get('created_at'))] or [None])
        if created and first_api: stage_duration['提示词'].append(_secs(created,first_api))
        if first_api and flow_submit: stage_duration['等待Flow'].append(_secs(first_api,flow_submit))
        if flow_submit and flow_done: stage_duration['Flow生成'].append(_secs(flow_submit,flow_done))
        if flow_done and qc_done: stage_duration['质检'].append(_secs(flow_done,qc_done))
        if qc_done and edit_start: stage_duration['等待剪辑'].append(_secs(qc_done,edit_start))
        if edit_start and completion: stage_duration['剪辑/导出'].append(_secs(edit_start,completion))
        if completion and upload_at: stage_duration['上传'].append(_secs(completion,upload_at))
        production_start=flow_submit or first_api or created
        if production_start and completion:
            dur=_secs(production_start,completion)
            if dur is not None: durations.append(dur)

        any_rework=False; rejection_count=0
        for p in parts:
            hist=decisions_by_segment.get(int(p['id']),[])
            if hist:
                if str(hist[0].get('decision') or '')=='通过': counts['first_pass_segments']+=1
                counts['decided_segments']+=1
                rejects=sum(str(x.get('decision') or '')=='退回' for x in hist)
                rejection_count+=rejects
                if rejects: any_rework=True; counts['reworked_segments']+=1
            elif str(p.get('qc_status') or '') in ('通过','退回'):
                counts['decided_segments']+=1
                if str(p.get('qc_status'))=='通过': counts['first_pass_segments']+=1
                else: any_rework=True; rejection_count+=1; counts['reworked_segments']+=1
        if any_rework: counts['rework_videos']+=1
        if rejection_count>=3: counts['rework3_videos']+=1
        counts['rework_decisions']+=rejection_count

        # Earliest unfinished stage is the current bottleneck bucket for this video.
        chain=[('prompt','等待提示词',created),('flow','等待Flow完成',flow_submit or first_api),('qc','等待质检',flow_done),
               ('edit','等待剪辑',qc_done),('export','等待导出',edit_start or qc_done),('upload','等待上传',completion),('delivery','等待交付',upload_at)]
        for key,label,entered in chain:
            if not flags[key]:
                backlog[label]+=1
                if entered:
                    wait=max(0,(datetime.now()-entered).total_seconds()); backlog_waits[label].append(wait)
                break

        video_rows.append(dict(v,flags=flags,completion=completion,duration=( _secs(production_start,completion) if production_start and completion else None),reworks=rejection_count))

    # Per-host quality and generation statistics.
    video_completion={int(v['video_id']):v.get('duration') for v in video_rows}
    video_host={int(v['video_id']):int(v['host_id']) for v in videos}
    host_name={int(v['host_id']):(v.get('host_name') or '未命名') for v in videos}
    host_recipient={int(v['host_id']):(v.get('recipient_name') or '未命名') for v in videos}
    for s in segments:
        hid=video_host.get(int(s['video_id']))
        if hid is None: continue
        a=host_acc[hid]; a['recipient_name']=host_recipient.get(hid,'未命名'); a['segments']+=1
        hist=decisions_by_segment.get(int(s['id']),[])
        if hist:
            a['decided']+=1
            if str(hist[0].get('decision') or '')=='通过': a['first_pass']+=1
        elif str(s.get('qc_status') or '') in ('通过','退回'):
            a['decided']+=1
            if str(s.get('qc_status') or '')=='通过': a['first_pass']+=1
        a['reworks']+=sum(str(x.get('decision') or '')=='退回' for x in hist)
        a['attempts'].append(max(1,int(s.get('flow_retry_count') or 0)+1))
    for vr in video_rows:
        hid=int(vr['host_id'])
        if vr.get('duration') is not None: host_acc[hid]['durations'].append(vr['duration'])

    quality_hosts=[]
    for hid,a in host_acc.items():
        segs=a['segments']; decided=a['decided']; first=a['first_pass']
        quality_hosts.append({
            'host_id':hid,'host_name':host_name.get(hid,'未命名'),'recipient_name':a['recipient_name'],
            'segments':segs,'first_pass_rate':(first/decided if decided else None),'reworks':a['reworks'],
            'avg_attempts':_mean(a['attempts']),'avg_seconds':_mean(a['durations'])
        })
    quality_hosts.sort(key=lambda x:((x['first_pass_rate'] if x['first_pass_rate'] is not None else 1.0),-x['reworks'],x['host_name']))

    # Reason categories use every recorded QC rejection; legacy active rejects are included once.
    reason_counts=Counter()
    rejected_segments=set()
    for d in decisions:
        if str(d.get('decision') or '')=='退回':
            reason_counts[_reason_category(d.get('reason'))]+=1; rejected_segments.add(int(d['segment_id']))
    for s in segments:
        if int(s['id']) not in rejected_segments and str(s.get('qc_status') or '')=='退回':
            reason_counts[_reason_category(s.get('qc_reject_reason') or s.get('qc_note'))]+=1

    funnel=[]
    stage_defs=[('task','任务创建'),('prompt','提示词完成'),('flow','Flow生成完成'),('qc','质检通过'),('edit','自动剪辑完成'),('export','导出完成'),('upload','云端上传完成'),('delivery','最终交付')]
    prev=counts['total']
    duration_map={'prompt':'提示词','flow':'Flow生成','qc':'质检','edit':'等待剪辑','export':'剪辑/导出','upload':'上传'}
    for key,label in stage_defs:
        n=counts['total'] if key=='task' else counts[key]
        funnel.append({'key':key,'label':label,'count':n,'rate':(n/counts['total'] if counts['total'] else None),
                       'loss':max(0,prev-n) if key!='task' else 0,'avg_stay_seconds':_mean(stage_duration.get(duration_map.get(key,''),[]))})
        prev=n

    bottlenecks=[]
    for label,n in backlog.most_common():
        bottlenecks.append({'stage':label,'count':int(n),'avg_wait_seconds':_mean(backlog_waits[label])})

    recipients=[]
    for rid,a in sorted(recipient.items(), key=lambda kv:(-kv[1]['completed'],-kv[1]['total'],kv[1].get('name',''))):
        recipients.append({'recipient_id':rid,'recipient_name':a.get('name','未命名'),'completed':a['completed'],'total':a['total'],
                           'rate':(a['completed']/a['total'] if a['total'] else 0)})

    # Current automation rate is deliberately strict: final delivery, no QC rejection,
    # no Flow retry and no manual upload confirmation.
    delivered=[v for v in video_rows if v['flags']['delivery']]
    automated=0
    for v in delivered:
        parts=grouped.get(int(v['video_id']),[])
        if v['reworks']==0 and all(int(p.get('flow_retry_count') or 0)==0 for p in parts) and str(v.get('upload_confirm_mode') or '')!='manual':
            automated+=1

    # Hourly values for the selected cohort.  A completion lacking a timestamp is kept
    # in the KPI total but not forced into an arbitrary hour.
    hourly=[]
    for h in range(24): hourly.append({'hour':h,'completed':0,'flow_segments':0,'reworks':0,'durations':[]})
    for v in video_rows:
        dt=v.get('completion')
        if dt: hourly[dt.hour]['completed']+=1
        if dt and v.get('duration') is not None: hourly[dt.hour]['durations'].append(v['duration'])
    for s in segments:
        dt=_dt(s.get('flow_completed_at'))
        if dt: hourly[dt.hour]['flow_segments']+=1
    for d in decisions:
        if str(d.get('decision') or '')=='退回':
            dt=_dt(d.get('created_at'))
            if dt: hourly[dt.hour]['reworks']+=1
    for h in hourly:
        h['avg_seconds']=_mean(h.pop('durations'))

    # Flow channel dispatch history for this cohort.
    dispatch_by_channel=defaultdict(list)
    for d in dispatches: dispatch_by_channel[str(d.get('channel_key') or '未分配')].append(d)
    channels=[]
    day_start=datetime.combine(_day(work_date),datetime.min.time()); day_end=day_start+timedelta(days=1)
    now=datetime.now(); observed_end=min(now,day_end) if day_start.date()==now.date() else day_end
    observed=max(1.0,(observed_end-day_start).total_seconds())
    for key,rows in dispatch_by_channel.items():
        done=sum(str(r.get('status') or '')=='detected' for r in rows); failed=sum(str(r.get('status') or '')=='failed' for r in rows)
        active=sum(str(r.get('status') or '') in ('planned','queued','submitted','downloading') for r in rows)
        retry=sum(int(r.get('round_no') or 1)>1 for r in rows)
        durations_ch=[]; intervals=[]
        for r in rows:
            st=_dt(r.get('submitted_at') or r.get('created_at'))
            en=_dt(r.get('detected_at'))
            if st:
                if not en and str(r.get('status') or '') in ('planned','queued','submitted','downloading'): en=observed_end
                if en and en>=st: intervals.append((st,en))
            if st and _dt(r.get('detected_at')): durations_ch.append(_secs(st,r.get('detected_at')))
        util=min(1.0,_union_seconds(intervals,day_start,observed_end)/observed) if observed_end>day_start else 0.0
        channels.append({'channel_key':key,'active':active,'done':done,'failed':failed,'retries':retry,
                         'success_rate':(done/(done+failed) if done+failed else None),'avg_seconds':_mean(durations_ch),'utilization':util})
    channels.sort(key=lambda x:x['channel_key'])

    return {
        'work_date':str(work_date),'counts':dict(counts),'videos':video_rows,'segments':segments,'decisions':decisions,
        'recipients':recipients,'funnel':funnel,'bottlenecks':bottlenecks,
        'stage_durations':[{'stage':k,'seconds':_mean(v)} for k,v in stage_duration.items() if _mean(v) is not None],
        'hourly':hourly,'quality_reasons':[{'reason':k,'n':v} for k,v in reason_counts.most_common()],
        'quality_hosts':quality_hosts,'avg_video_seconds':_mean(durations),'completion_times':completion_times,
        'automation_rate':(automated/len(delivered) if delivered else None),'automated':automated,'delivered_denominator':len(delivered),
        'dispatches':dispatches,'channels_history':channels,'recovery':recovery,
    }


def _channel_runtime(day_data):
    now=time.time(); history={r['channel_key']:r for r in day_data.get('channels_history',[])}
    with _global_readonly() as con:
        if not _table_exists(con,'flow_channel_pool'): return []
        rows=[dict(r) for r in con.execute("SELECT * FROM flow_channel_pool WHERE enabled=1 ORDER BY sort_order,id")]
    result=[]
    for ch in rows:
        key=str(ch.get('channel_key') or '')
        hist=history.get(key,{})
        last_seen=float(ch.get('last_seen') or 0); online=bool(last_seen and now-last_seen<15)
        active=int(hist.get('active',0)); health=str(ch.get('health_status') or '').lower(); err=str(ch.get('last_error') or '')
        if err or health in ('failed','error','quarantined','offline'): state='异常'
        elif online and active: state='工作中'
        elif online: state='空闲'
        else: state='离线'
        result.append({**hist,'channel_key':key,'state':state,'online':online,'last_error':err,
                       'utilization':hist.get('utilization',0.0),'active':active,'done':int(hist.get('done',0)),
                       'failed':int(hist.get('failed',0)),'retries':int(hist.get('retries',0)),
                       'health_status':ch.get('health_status') or 'unknown','role':ch.get('role') or 'normal'})
    return result


def _api_snapshot(work_date):
    day=_day(work_date); day_s=day.isoformat(); month=day_s[:7]
    empty={'day_cost':0.0,'month_cost':0.0,'requests':0,'input_tokens':0,'cached_tokens':0,'output_tokens':0,
           'models':[],'sources':[],'daily_costs':[],'duplicate_calls':0}
    with _global_readonly() as con:
        if not _table_exists(con,'api_usage_log'): return empty
        rows=[dict(r) for r in con.execute("SELECT * FROM api_usage_log WHERE substr(created_at,1,10)=? ORDER BY created_at,id",(day_s,))]
        month_row=con.execute("SELECT COALESCE(SUM(cost_usd),0) c FROM api_usage_log WHERE substr(created_at,1,7)=?",(month,)).fetchone()
        model_rows=[dict(r) for r in con.execute("""SELECT model,COUNT(*) requests,COALESCE(SUM(input_tokens),0) input_tokens,
            COALESCE(SUM(cached_tokens),0) cached_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(cost_usd),0) cost_usd
            FROM api_usage_log WHERE substr(created_at,1,10)=? GROUP BY model ORDER BY cost_usd DESC""",(day_s,))]
        aiq={}
        if _table_exists(con,'ai_qc_results'):
            for r in con.execute("SELECT segment_id,cost_usd,updated_at FROM ai_qc_results"):
                aiq[int(r['segment_id'])]=(float(r['cost_usd'] or 0),_dt(r['updated_at']))
        start=day-timedelta(days=29); daily=[]
        for i in range(30):
            d=(start+timedelta(days=i)).isoformat()
            rr=con.execute("SELECT COALESCE(SUM(cost_usd),0) c FROM api_usage_log WHERE substr(created_at,1,10)=?",(d,)).fetchone()
            daily.append({'date':d,'cost':float(rr['c'] or 0)})
    sources=Counter(); source_cost=defaultdict(float); seen_by_segment=defaultdict(list); duplicates=0
    for r in rows:
        sid=r.get('flow_segment_id'); source='其他调用'
        if sid:
            sid=int(sid); when=_dt(r.get('created_at')); ai=aiq.get(sid)
            is_ai=bool(ai and abs(float(r.get('cost_usd') or 0)-ai[0])<1e-6 and (not when or not ai[1] or abs((when-ai[1]).total_seconds())<1800))
            if is_ai: source='AI质检/图片分析'
            else:
                source='提示词重新生成' if seen_by_segment[sid] else '提示词生成'
                if seen_by_segment[sid] and when:
                    prev=seen_by_segment[sid][-1]
                    if prev and abs((when-prev).total_seconds())<=90: duplicates+=1
                seen_by_segment[sid].append(when)
        sources[source]+=1; source_cost[source]+=float(r.get('cost_usd') or 0)
    total=lambda key:sum(int(r.get(key) or 0) for r in rows)
    return {
        'day_cost':sum(float(r.get('cost_usd') or 0) for r in rows),'month_cost':float(month_row['c'] or 0),'requests':len(rows),
        'input_tokens':total('input_tokens'),'cached_tokens':total('cached_tokens'),'output_tokens':total('output_tokens'),
        'models':model_rows,'sources':[{'source':k,'requests':sources[k],'cost_usd':source_cost[k]} for k,_ in sources.most_common()],
        'daily_costs':daily,'duplicate_calls':duplicates,
    }


def _system_health(work_date, day_data, channel_rows):
    counts=Counter(); auto_recovery=0; manual=0
    segs=day_data.get('segments',[])
    counts['Flow生成失败']=sum(str(s.get('flow_status') or '') in ('失败','生成失败') for s in segs)
    counts['下载失败']=sum(str(s.get('flow_status') or '')=='下载失败' for s in segs)
    counts['浏览器/通道失联']=sum(r.get('state')=='离线' for r in channel_rows)
    counts['Flow插件异常']=sum(r.get('state')=='异常' for r in channel_rows)
    videos=day_data.get('videos',[])
    counts['Drive上传失败']=sum(str(v.get('upload_status') or '')=='上传失败' for v in videos)
    for r in day_data.get('recovery',[]):
        failures=int(r.get('failures') or 0); blocked=int(r.get('blocked') or 0)
        if failures and not blocked: auto_recovery+=1
        if blocked: manual+=1
    with _global_readonly() as con:
        ds=_day(work_date).isoformat()
        if _table_exists(con,'editing_history'):
            rows=[dict(r) for r in con.execute("SELECT status FROM editing_history WHERE substr(updated_at,1,10)=?",(ds,))]
            counts['自动剪辑失败']=sum(('失败' in str(r.get('status') or '') or 'ERROR' in str(r.get('status') or '').upper()) and '导出' not in str(r.get('status') or '') for r in rows)
            counts['导出失败']=sum('导出' in str(r.get('status') or '') and ('失败' in str(r.get('status') or '') or 'ERROR' in str(r.get('status') or '').upper()) for r in rows)
        if _table_exists(con,'davinci_batches'):
            counts['DaVinci连接失败']=int(con.execute("SELECT COUNT(*) n FROM davinci_batches WHERE substr(updated_at,1,10)=? AND status LIKE '%ERROR%'",(ds,)).fetchone()['n'] or 0)
        if _table_exists(con,'pipeline_events'):
            counts['GPT API失败']=int(con.execute("""SELECT COUNT(*) n FROM pipeline_events WHERE substr(created_at,1,10)=? AND level='ERROR'
                AND (lower(message) LIKE '%gpt%' OR lower(message) LIKE '%api%' OR lower(message) LIKE '%openai%')""",(ds,)).fetchone()['n'] or 0)
    manual += counts['Drive上传失败']+counts['自动剪辑失败']+counts['导出失败']+counts['DaVinci连接失败']+counts['GPT API失败']
    total=sum(counts.values())
    return {'items':[{'name':k,'count':int(counts[k])} for k in ['Flow插件异常','浏览器/通道失联','Flow生成失败','下载失败','DaVinci连接失败','自动剪辑失败','导出失败','Drive上传失败','GPT API失败']],
            'total':int(total),'auto_recovery':int(auto_recovery),'manual':int(manual),
            'auto_recovery_rate':(auto_recovery/(auto_recovery+manual) if auto_recovery+manual else None)}


def _range_hourly(active_day, range_key, force=False):
    d=_day(active_day)
    if range_key=='昨天': days=[d-timedelta(days=1)]
    elif range_key=='近7天': days=[d-timedelta(days=i) for i in range(6,-1,-1)]
    elif range_key=='近30天': days=[d-timedelta(days=i) for i in range(29,-1,-1)]
    else: days=[d]
    agg=[{'hour':h,'completed':0,'flow_segments':0,'reworks':0,'durations':[]} for h in range(24)]
    for dd in days:
        data=_get_day(dd.isoformat(),force=force)
        for row in data['hourly']:
            h=int(row['hour']); agg[h]['completed']+=int(row.get('completed') or 0); agg[h]['flow_segments']+=int(row.get('flow_segments') or 0); agg[h]['reworks']+=int(row.get('reworks') or 0)
            if row.get('avg_seconds') is not None: agg[h]['durations'].append(float(row['avg_seconds']))
    for row in agg: row['avg_seconds']=_mean(row.pop('durations'))
    return agg, [x.isoformat() for x in days]


def _get_day(work_date, force=False):
    key=('day',str(work_date)); now=time.time()
    cached=_CACHE.get(key)
    if not force and cached and now-cached[0]<_CACHE_TTL: return cached[1]
    data=_day_projection(work_date); _CACHE[key]=(now,data); return data


def analytics_snapshot(work_date, range_key='今天', force=False):
    """Comprehensive read-only statistics payload for the five analytics tabs.

    Cache lifetime is one hour.  `force=True` is used only by the page's manual
    refresh button and still performs reads/aggregation only.
    """
    current=_get_day(work_date,force=force)
    previous=_get_day((_day(work_date)-timedelta(days=1)).isoformat(),force=force)
    hourly,range_days=_range_hourly(work_date,range_key,force=force)
    channels=_channel_runtime(current)
    c=Counter(current['counts']); pc=Counter(previous['counts'])

    decided=int(c['decided_segments']); first=int(c['first_pass_segments']); reworked=int(c['reworked_segments'])
    complete=int(c['export']); total=int(c['total'])
    completion_times=current.get('completion_times',[])
    per_hour=None
    if completion_times:
        start=min(completion_times); end=max(completion_times)
        hours=max(1.0,(end-start).total_seconds()/3600.0)
        per_hour=complete/hours
    bottleneck_change=None
    if current.get('bottlenecks'):
        stage=current['bottlenecks'][0]['stage']; history_counts=[]
        for offset in range(1,8):
            old=_get_day((_day(work_date)-timedelta(days=offset)).isoformat(),force=force)
            found=next((b['count'] for b in old.get('bottlenecks',[]) if b.get('stage')==stage),0)
            history_counts.append(found)
        avg7=sum(history_counts)/len(history_counts) if history_counts else 0
        bottleneck_change={'stage':stage,'current':current['bottlenecks'][0]['count'],'avg7':avg7,'delta':current['bottlenecks'][0]['count']-avg7}

    overview={
        'task_count':total,'completed':complete,'completion_rate':(complete/total if total else None),'videos_per_hour':per_hour,
        'first_pass_rate':(first/decided if decided else None),'rework_rate':(reworked/decided if decided else None),
        'avg_video_seconds':current.get('avg_video_seconds'),'backlog':max(0,total-complete),
        'delta':{
            'task_count':total-int(pc['total']),'completed':complete-int(pc['export']),
            'completion_rate':((complete/total)-(pc['export']/pc['total']) if total and pc['total'] else None),
        },
        'hourly':hourly,'range_days':range_days,'recipients':current['recipients'],'bottleneck':(current['bottlenecks'][0] if current['bottlenecks'] else None),'bottleneck_change':bottleneck_change,
    }

    flow_counts=Counter(r.get('state') for r in channels)
    flow_done=sum(str(s.get('flow_status') or '') in FLOW_DONE for s in current.get('segments',[]))
    flow_total_channels=len(channels)
    util_vals=[r.get('utilization') for r in channels if r.get('utilization') is not None]
    waiting_flow=sum(1 for v in current['videos'] if not v['flags']['flow'] and v['flags']['prompt'])
    idle=sum(r.get('state')=='空闲' for r in channels)
    flow_error_count=sum(str(s.get('flow_status') or '') in FLOW_FAILED for s in current['segments'])
    scheduler=[
        {'name':'中央任务池有任务但通道空闲（当前）','value':(f'{waiting_flow} 个待生成 / {idle} 个空闲' if waiting_flow and idle else '当前无异常'),'severity':'warn' if waiting_flow and idle else 'ok'},
        {'name':'空闲未领取累计时间','value':'—（现有历史未记录）','severity':'ok'},
        {'name':'任务分配失败','value':sum(int(r.get('failed') or 0) for r in channels),'severity':'bad' if any(int(r.get('failed') or 0) for r in channels) else 'ok'},
        {'name':'通道失联','value':int(flow_counts['离线']),'severity':'bad' if flow_counts['离线'] else 'ok'},
        {'name':'Flow异常','value':flow_error_count,'severity':'bad' if flow_error_count else 'ok'},
        {'name':'自动恢复次数','value':sum(1 for r in current.get('recovery',[]) if int(r.get('failures') or 0)>0 and not int(r.get('blocked') or 0)),'severity':'ok'},
    ]

    qdec=current['decisions']; q_by_segment=defaultdict(list)
    for q in qdec:q_by_segment[int(q['segment_id'])].append(q)
    second_den=sum(len(v)>=2 for v in q_by_segment.values()); second_pass=sum(len(v)>=2 and str(v[1].get('decision') or '')=='通过' for v in q_by_segment.values())
    qc_count=len(qdec) if qdec else decided
    quality={
        'qc_count':qc_count,'first_pass_rate':(first/decided if decided else None),'rework_rate':(reworked/decided if decided else None),
        'second_pass_rate':(second_pass/second_den if second_den else None),'rework3_videos':int(c['rework3_videos']),
        'avg_reworks':(c['rework_decisions']/max(1,sum(1 for v in current['videos'] if v.get('reworks') is not None and (v['reworks']>0 or v['flags']['qc']))) if (c['rework_decisions'] or c['qc']) else None),
        'reasons':current['quality_reasons'],'hosts':current['quality_hosts'],
    }

    api=_api_snapshot(work_date)
    api['avg_per_completed_video']=(api['day_cost']/complete if complete else None)
    system=_system_health(work_date,current,channels)

    return {
        'work_date':str(work_date),'range_key':range_key,'overview':overview,
        'efficiency':{'completed':complete,'videos_per_hour':per_hour,'avg_video_seconds':current.get('avg_video_seconds'),
                      'backlog':max(0,total-complete),'automation_rate':current.get('automation_rate'),
                      'funnel':current['funnel'],'bottlenecks':current['bottlenecks'][:3],'stage_durations':current['stage_durations']},
        'flow':{'total':flow_total_channels,'working':int(flow_counts['工作中']),'idle':int(flow_counts['空闲']),
                'abnormal':int(flow_counts['异常']+flow_counts['离线']),'avg_utilization':(_mean(util_vals) if util_vals else None),
                'completed_segments':flow_done,'channels':channels,'scheduler':scheduler},
        'quality':quality,'api':api,'system':system,
        'cache_seconds':int(_CACHE_TTL),
    }

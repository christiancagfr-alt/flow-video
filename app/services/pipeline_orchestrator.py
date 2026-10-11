from __future__ import annotations

import json
import time
from collections import defaultdict

from app.core import repository as repo
from app.services import runtime_log


def classify_error(message: str) -> str:
    s=(message or '').lower()
    if any(x in s for x in ('button','dom','timeout','超时','页面加载','connection','连接')): return 'L1'
    if any(x in s for x in ('tab','channel','通道','discard','crash','崩溃')): return 'L2'
    if any(x in s for x in ('face','hand','人脸','手部','台词','speech','音频','生成异常')): return 'L3'
    return 'L4'


def quarantine_unhealthy_channels(max_failures: int=3, seconds: int=180) -> list[str]:
    quarantined=[]
    now=time.time()
    for ch in repo.list_channel_pool(enabled_only=True):
        if int(ch['consecutive_failures'] or 0) >= max_failures and float(ch['quarantine_until'] or 0) < now:
            repo.set_channel_health(ch['channel_key'],health='quarantined',quarantine_until=now+seconds)
            quarantined.append(str(ch['channel_key']))
    if quarantined:
        runtime_log.log('channels_quarantined',channels=quarantined,seconds=seconds)
    return quarantined


def backpressure_state() -> dict:
    s=repo.pipeline_queue_counts()
    # Conservative first version: report/advise; do not silently stop user's production.
    qc_limit=int(repo.get_setting('backpressure_qc_limit','250') or 250)
    edit_limit=int(repo.get_setting('backpressure_edit_limit','80') or 80)
    throttled=bool(s['qc_waiting']>=qc_limit or s['edit_waiting']>=edit_limit)
    reason=''
    if s['qc_waiting']>=qc_limit: reason=f"质检积压 {s['qc_waiting']}≥{qc_limit}"
    elif s['edit_waiting']>=edit_limit: reason=f"剪辑积压 {s['edit_waiting']}≥{edit_limit}"
    return {**s,'throttled':throttled,'reason':reason}


def channel_recommendations() -> list[dict]:
    stats=repo.browser_throughput_stats()
    out=[]
    for row in stats:
        fail_rate=(row['failed']/max(row['submitted'],1)) if row['submitted'] else 0
        note='保持当前通道数'
        if row['submitted']>=20 and fail_rate>0.20: note='错误率偏高，建议减少1～2个普通通道后观察'
        elif row['submitted']>=20 and fail_rate<0.05: note='当前稳定；若Flow仍有余量，可小幅增加1个通道测试'
        out.append({**row,'fail_rate':round(fail_rate,3),'recommendation':note})
    return out


def daily_report() -> dict:
    return repo.daily_production_report()


def watchdog_tick(now=None) -> dict:
    """Non-destructive production watchdog.

    It quarantines repeatedly failing/stale channels but never moves a task that may already have
    been submitted. Stale QUEUED dispatches are only exposed as reclaimable candidates for an
    explicit reclaim operation, which first removes their bridge command.
    """
    now=float(now or time.time())
    degraded=[]
    for ch in repo.list_channel_pool(enabled_only=True):
        age=now-float(ch['last_seen'] or 0) if ch['last_seen'] else 10**9
        active=repo.channel_dispatch_summary(str(ch['channel_key'])).get('active',0)
        if active and age>90 and str(ch['health_status'] or '') not in ('quarantined','stale'):
            repo.set_channel_health(ch['channel_key'],health='stale',page_status='heartbeat_stale',failure_delta=1)
            degraded.append(str(ch['channel_key']))
    quarantined=quarantine_unhealthy_channels()
    stale=list(repo.list_stale_unsubmitted_dispatches(now=now,threshold_seconds=int(repo.get_setting('unsubmitted_reclaim_seconds','300') or 300)))
    return {'degraded':degraded,'quarantined':quarantined,'reclaimable':stale}

"""Explicit date-scoped workspaces. Reads are filtered; writes may target the selected date with identity guards."""
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import re
from . import database

LEGACY='LEGACY'
_active=None

def today(): return date.today().isoformat()
def active(): return _active or today()
def reset():
    global _active
    _active=today()
def select(value):
    global _active
    normalized=canonical(value)
    if not normalized and value!=LEGACY: raise ValueError('无效工作日期')
    _active=normalized or LEGACY
    return _active

def canonical(value):
    text=str(value or '').strip()
    match=re.match(r'^(\d{4})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})(?:日|[ T].*)?$',text)
    if match:
        try:return date(*map(int,match.groups())).isoformat()
        except ValueError:pass
    return None

def recipient_dates(con):
    """Prefer original project date, then creation time; never fall back to today."""
    dates={}
    for row in con.execute('SELECT * FROM main.recipients'):
        r=dict(row); dates[r['id']]=(LEGACY if r.get('work_date')==LEGACY else canonical(r.get('work_date')) or canonical(r.get('created_at')))
    unresolved={k for k,v in dates.items() if not v}
    if unresolved:
        for table,join in [('videos','JOIN main.hosts h ON h.id=x.host_id'),('flow_segments','JOIN main.videos v ON v.id=x.video_id JOIN main.hosts h ON h.id=v.host_id')]:
            columns={r[1] for r in con.execute(f'PRAGMA main.table_info({table})')}
            if 'created_at' in columns:
                for row in con.execute(f'SELECT h.recipient_id, MIN(x.created_at) stamp FROM main.{table} x {join} GROUP BY h.recipient_id'):
                    if row['recipient_id'] in unresolved:
                        found=canonical(row['stamp'])
                        if found: dates[row['recipient_id']]=found;unresolved.remove(row['recipient_id'])
    if unresolved:
        for row in con.execute('SELECT h.recipient_id,v.image_path FROM main.videos v JOIN main.hosts h ON h.id=v.host_id ORDER BY v.id'):
            rid=row['recipient_id']
            if rid not in unresolved or not row['image_path']:continue
            try:
                path=Path(row['image_path'])
                born=getattr(path.stat(),'st_birthtime',None) if path.is_file() else None
                if born:
                    dates[rid]=datetime.fromtimestamp(born).date().isoformat();unresolved.remove(rid)
            except (OSError,ValueError,OverflowError):pass
    return {k:v or LEGACY for k,v in dates.items()}

def normalize_scope(value):
    """Return a canonical workspace date (or LEGACY) for read/write scope checks."""
    if value == LEGACY:
        return LEGACY
    day = canonical(value)
    if not day:
        raise ValueError('无效工作日期')
    return day

def recipient_work_date(con, recipient_id):
    """Resolve one recipient to the date partition used by the workspace."""
    return recipient_dates(con).get(int(recipient_id))

def video_work_date(con, video_id):
    row = con.execute(
        "SELECT h.recipient_id FROM main.videos v JOIN main.hosts h ON h.id=v.host_id WHERE v.id=?",
        (int(video_id),),
    ).fetchone()
    if not row:
        return None
    return recipient_work_date(con, int(row['recipient_id']))

def require_recipient_work_date(recipient_id, expected_date):
    """Guard a writable action so it cannot escape the selected day partition."""
    expected = normalize_scope(expected_date)
    with database.connect() as con:
        actual = recipient_work_date(con, int(recipient_id))
    if actual is None:
        raise ValueError('当前接收人已经不存在。')
    if actual != expected:
        raise ValueError(f'当前接收人属于 {actual}，与正在编辑的日期 {expected} 不一致，已阻止跨日期修改。')
    return actual

def require_video_work_date(video_id, expected_date):
    """Guard a video write by its recipient's immutable date partition."""
    expected = normalize_scope(expected_date)
    with database.connect() as con:
        actual = video_work_date(con, int(video_id))
    if actual is None:
        raise ValueError('当前完整视频任务已经不存在。')
    if actual != expected:
        raise ValueError(f'当前任务属于 {actual}，与正在编辑的日期 {expected} 不一致，已阻止跨日期修改。')
    return actual

@contextmanager
def read_connection(work_date=None):
    con=database.connect()
    try:
        if work_date is not None:
            day=canonical(work_date) or (LEGACY if work_date==LEGACY else None)
            if day is None: raise ValueError('无效工作日期')
            ids=[int(k) for k,v in recipient_dates(con).items() if v==day]
            # Temporary views exist only on this connection. No persistent schema,
            # paths, IDs, or production rows change. Existing aggregate SQL is reused.
            members=','.join(map(str,ids)) or 'NULL'
            con.execute(f'CREATE TEMP VIEW recipients AS SELECT * FROM main.recipients WHERE id IN ({members})')
            con.execute('CREATE TEMP VIEW hosts AS SELECT * FROM main.hosts WHERE recipient_id IN (SELECT id FROM temp.recipients)')
            con.execute('CREATE TEMP VIEW videos AS SELECT * FROM main.videos WHERE host_id IN (SELECT id FROM temp.hosts)')
            con.execute('CREATE TEMP VIEW flow_segments AS SELECT * FROM main.flow_segments WHERE video_id IN (SELECT id FROM temp.videos)')
            tables={r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
            for name in ('flow_outputs','flow_redo','flow_dispatches','qc_decisions','speech_analysis','local_qc_results','ai_qc_results','api_usage_log','prompt_submission_history'):
                if name in tables:
                    key='flow_segment_id' if name=='api_usage_log' else 'segment_id'
                    con.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM main.{name} WHERE {key} IN (SELECT id FROM temp.flow_segments)')
            for name,key,parent in [('flow_channels','host_id','hosts'),('source_tasks','video_id','videos'),('asset_jobs','video_id','videos')]:
                if name in tables:con.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM main.{name} WHERE {key} IN (SELECT id FROM temp.{parent})')
            con.execute('PRAGMA query_only=ON')
        yield con
    finally:
        con.close()

def task_dates():
    with read_connection() as con:
        dates=recipient_dates(con)
        ids={r[0] for r in con.execute('SELECT DISTINCT h.recipient_id FROM videos v JOIN hosts h ON h.id=v.host_id')}
    return {dates[k] for k in ids if k in dates}


def unfinished_flow_count(work_date):
    """Count approved Flow tasks that still belong to an open production chain.

    Used only to keep an in-progress day pinned across midnight.  Completed tasks do
    not keep the old day open; failed/waiting/prepared/submitted/rendering/downloading
    work does, so automatic production cannot silently jump to a new date mid-batch.
    """
    if not work_date or work_date == LEGACY:
        return 0
    with read_connection(work_date) as con:
        row=con.execute("""SELECT COUNT(*)
            FROM flow_segments
            WHERE TRIM(COALESCE(prompt,''))<>''
              AND COALESCE(prompt_review_status,'待检查')='已提交'
              AND COALESCE(NULLIF(flow_status,''),'待生成') IN
                  ('待生成','失败','已准备','已提交','生成中','下载中','下载失败')
        """).fetchone()
    return int(row[0] or 0)


def latest_unfinished_flow_date(before_or_equal=None):
    """Latest dated workspace that still has open Flow production work.

    This is intentionally date-only and never mutates the active workspace.  It lets
    startup resume an unfinished batch from yesterday instead of defaulting to an empty
    new-day workspace and leaving the old queue stranded.
    """
    limit=canonical(before_or_equal) if before_or_equal else None
    dated=sorted((d for d in task_dates() if d and d!=LEGACY and (not limit or d<=limit)), reverse=True)
    for day in dated:
        if unfinished_flow_count(day)>0:
            return day
    return None

def channel_snapshot():
    with read_connection() as con:
        return con.execute('SELECT * FROM flow_channel_pool WHERE enabled=1 ORDER BY id').fetchall()

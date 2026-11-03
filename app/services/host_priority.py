"""Persistent, work-date scoped priority for future normal-channel allocations."""
import json
from app.core import repository as repo

FIRST_THREE_SETTING_KEY = 'flow_first_three_videos_enabled'
FIRST_VIDEOS_COUNT_KEY = 'flow_first_videos_per_host'
FIRST_VIDEOS_PER_HOST = 3


def first_three_videos_enabled() -> bool:
    raw = str(repo.get_setting(FIRST_THREE_SETTING_KEY, '0') or '0').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def set_first_three_videos_enabled(enabled: bool) -> bool:
    flag = bool(enabled)
    repo.set_setting(FIRST_THREE_SETTING_KEY, '1' if flag else '0')
    return flag


def first_videos_per_host() -> int:
    try:
        val = int(str(repo.get_setting(FIRST_VIDEOS_COUNT_KEY, str(FIRST_VIDEOS_PER_HOST)) or FIRST_VIDEOS_PER_HOST).strip())
    except (TypeError, ValueError):
        val = FIRST_VIDEOS_PER_HOST
    return max(1, min(99, val))


def set_first_videos_per_host(count: int) -> int:
    try:
        val = int(count)
    except (TypeError, ValueError):
        val = FIRST_VIDEOS_PER_HOST
    n = max(1, min(99, val))
    repo.set_setting(FIRST_VIDEOS_COUNT_KEY, str(n))
    return n


def first_video_ids_by_host(all_rows, limit: int | None = None):
    """Return {host_id: set(first `limit` distinct video_ids ordered by video_seq, video_id)}."""
    n = first_videos_per_host() if limit is None else max(1, min(99, int(limit or FIRST_VIDEOS_PER_HOST)))
    by_host = {}
    for row in all_rows or ():
        try:
            hid = int(row['host_id'])
            vid = int(row['video_id'])
            vseq = int(row['video_seq'])
        except (KeyError, TypeError, ValueError):
            continue
        if hid <= 0 or vid <= 0:
            continue
        seen = by_host.setdefault(hid, {})
        if vid not in seen or vseq < seen[vid]:
            seen[vid] = vseq
    out = {}
    for hid, vid_map in by_host.items():
        ordered_vids = [vid for vid, _ in sorted(vid_map.items(), key=lambda kv: (kv[1], kv[0]))]
        out[hid] = set(ordered_vids[:n])
    return out


def task_sort_key(t):
    if hasattr(t, 'get'):
        tier = int(t.get('_priority_tier', 1))
        prio = int(t.get('_host_priority', 0))
    else:
        keys = t.keys()
        tier = int(t['_priority_tier']) if '_priority_tier' in keys else 1
        prio = int(t['_host_priority']) if '_host_priority' in keys else 0
    return (
        tier,
        prio,
        int(t['recipient_id']),
        int(t['host_id']),
        int(t['video_seq']),
        int(t['seg_seq']),
    )


def load(day):
    try:
        values=json.loads(repo.get_setting('flow_host_priority:'+str(day), '[]'))
        return list(dict.fromkeys(int(x) for x in values if int(x)>0))
    except (ValueError, TypeError):
        return []


def save(day, hosts):
    repo.set_setting('flow_host_priority:'+str(day),json.dumps(hosts))


def toggle(day, host_id):
    hosts=load(day)
    if host_id in hosts:hosts.remove(host_id)
    else:hosts.append(host_id)
    save(day,hosts)
    return host_id in hosts


def apply(tasks, all_rows, day, first_three_override=None, first_count_override=None):
    hosts=load(day)
    unfinished={int(t['host_id']) for t in all_rows if str(t['flow_status'] or '')!='已完成'}
    retained=[h for h in hosts if h in unfinished]
    if retained!=hosts:save(day,retained)
    ranks={h:i for i,h in enumerate(retained)}
    use_first_three = first_three_videos_enabled() if first_three_override is None else bool(first_three_override)
    limit = first_videos_per_host() if first_count_override is None else max(1, min(99, int(first_count_override)))
    first3_map = first_video_ids_by_host(all_rows, limit) if use_first_three else {}
    # Only this in-memory planning copy carries priority; no plugin protocol fields.
    annotated = []
    for t in tasks:
        hid = int(t['host_id'])
        if hid in ranks:
            # Manual "优先生成" keeps 100% original behavior: rush the entire prioritized host first.
            tier = 0
            host_prio = ranks[hid]
        elif use_first_three:
            vid = int(t['video_id'])
            tier = 1 if vid in first3_map.get(hid, ()) else 2
            host_prio = len(ranks)
        else:
            tier = 1
            host_prio = len(ranks)
        annotated.append(dict(t, _priority_tier=tier, _host_priority=host_prio))
    return sorted(annotated, key=task_sort_key)

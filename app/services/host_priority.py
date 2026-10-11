"""Persistent, work-date scoped priority for future normal-channel allocations."""
import json
from app.core import repository as repo


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


def apply(tasks, all_rows, day):
    hosts=load(day)
    unfinished={int(t['host_id']) for t in all_rows if str(t['flow_status'] or '')!='已完成'}
    retained=[h for h in hosts if h in unfinished]
    if retained!=hosts:save(day,retained)
    ranks={h:i for i,h in enumerate(retained)}
    # Only this in-memory planning copy carries priority; no plugin protocol fields.
    return [dict(t, _host_priority=ranks.get(int(t['host_id']),len(ranks))) for t in tasks]

"""Per-channel and per-AI-host pause switches (Studio-side only).

Paused channel: receives no new batches (a batch already sent to the web page finishes normally).
Paused host:    none of its segments are dispatched (new or QC-returned) until resumed.
State is persisted in settings so it survives a Studio restart.
"""
import json, time
from app.core import repository as repo
from app.services import runtime_log

_CH_KEY = 'flow_paused_channels'
_HOST_KEY = 'flow_paused_hosts'
_CD_KEY = 'flow_channel_cooldowns'      # {channel: {until, last, level}} - Flow "unusual activity" circuit breaker
BASE_COOLDOWN = 20 * 60
MAX_COOLDOWN = 60 * 60


def _read(key):
    try:
        return set(json.loads(repo.get_setting(key, '[]') or '[]'))
    except Exception:
        return set()


def _write(key, values):
    repo.set_setting(key, json.dumps(sorted(values), ensure_ascii=False))


def _cooldowns():
    try:
        d = json.loads(repo.get_setting(_CD_KEY, '{}') or '{}')
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def cooldown_active(key):
    return float((_cooldowns().get(str(key)) or {}).get('until') or 0) > time.time()


def paused_channels():
    manual = {str(x) for x in _read(_CH_KEY)}
    now = time.time()
    cooling = {k for k, v in _cooldowns().items() if float((v or {}).get('until') or 0) > now}
    return manual | cooling


def manual_paused_channels():
    """Channels the user paused by hand (excludes automatic unusual-activity cooldowns)."""
    return {str(x) for x in _read(_CH_KEY)}


def recent_unusual(key, within=180):
    """True if Flow reported 'unusual activity' for this channel in the last `within` seconds."""
    return time.time() - float((_cooldowns().get(str(key)) or {}).get('last') or 0) <= within


def cooldown_channel(key, base=BASE_COOLDOWN):
    """Flow rejected a generation as unusual activity: pause the channel (20/40/60 min escalation)
    and give back the failure counts that rejection just caused (it is not a task fault)."""
    key = str(key); now = time.time(); data = _cooldowns(); rec = data.get(key) or {}
    level = int(rec.get('level') or 0) + 1 if now - float(rec.get('last') or 0) < 2 * 3600 else 1
    seconds = min(MAX_COOLDOWN, int(base) * (2 ** (level - 1)))
    data[key] = {'until': now + seconds, 'last': now, 'level': level}
    repo.set_setting(_CD_KEY, json.dumps(data))
    refunded = 0
    try:
        from app.core.database import connect
        with connect() as con:
            rows = con.execute("""SELECT a.segment_id,a.command_id FROM flow_failure_attempts a
                                  JOIN flow_segments fs ON fs.id=a.segment_id
                                  WHERE a.created_at>=? AND fs.flow_channel_key=?""", (now - 180, key)).fetchall()
            for sid, cmd in rows:
                con.execute('DELETE FROM flow_failure_attempts WHERE segment_id=? AND command_id=?', (sid, cmd))
                con.execute("""UPDATE flow_recovery SET failures=MAX(0,failures-1),
                               blocked=CASE WHEN failures-1>=3 THEN 1 ELSE 0 END WHERE segment_id=?""", (sid,))
                refunded += 1
    except Exception as exc:
        runtime_log.log('unusual_activity_refund_failed', level='WARNING', channel=key, error=str(exc))
    runtime_log.log('flow_unusual_activity_cooldown', level='WARNING', channel=key, level_no=level,
                    cooldown_seconds=seconds, refunded_failures=refunded)
    return seconds


def paused_hosts():
    out = set()
    for x in _read(_HOST_KEY):
        try: out.add(int(x))
        except Exception: pass
    return out


def channel_paused(key):
    return str(key) in paused_channels()


def host_paused(host_id):
    try: return int(host_id) in paused_hosts()
    except Exception: return False


def toggle_channel(key):
    key = str(key); cur = _read(_CH_KEY)
    now_paused = key not in paused_channels()
    if now_paused:
        cur.add(key)
    else:                                   # resume also clears an active cooldown
        cur.discard(key)
        data = _cooldowns()
        if key in data:
            data[key]['until'] = 0
            repo.set_setting(_CD_KEY, json.dumps(data))
    _write(_CH_KEY, cur)
    runtime_log.log('channel_pause_toggled', channel=key, paused=now_paused)
    return now_paused


def toggle_host(host_id):
    hid = int(host_id); cur = paused_hosts()
    now_paused = hid not in cur
    (cur.add if now_paused else cur.discard)(hid)
    _write(_HOST_KEY, cur)
    runtime_log.log('host_pause_toggled', host_id=hid, paused=now_paused)
    return now_paused


def filter_tasks(tasks):
    """Drop tasks of paused hosts."""
    hosts = paused_hosts()
    if not hosts: return list(tasks)
    out = []
    for t in tasks:
        try:
            if int(t['host_id']) in hosts: continue
        except Exception:
            pass
        out.append(t)
    return out

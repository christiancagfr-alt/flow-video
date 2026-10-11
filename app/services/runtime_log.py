from __future__ import annotations
from pathlib import Path
import json, logging, logging.handlers, threading, time

_ROOT = Path(__file__).resolve().parents[2] / 'data' / 'logs'
_PATH = _ROOT / 'flowstudio-runtime.log'
_lock = threading.Lock()
_logger = None
_sampled = {}


def _get():
    global _logger
    with _lock:
        if _logger is not None:
            return _logger
        _ROOT.mkdir(parents=True, exist_ok=True)
        lg = logging.getLogger('FlowStudioRuntime')
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        if not lg.handlers:
            h = logging.handlers.RotatingFileHandler(_PATH, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
            h.setFormatter(logging.Formatter('%(asctime)s.%(msecs)03d %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
            lg.addHandler(h)
        _logger = lg
        return lg


def log(event: str, level='INFO', **fields):
    if fields.get('type') in ('web_plugin_heartbeat','web_plugin_progress_snapshot') and level=='INFO':
        key=(event,fields.get('type'),fields.get('channel'))
        signature=tuple(str(fields.get(k)) for k in ('pending','submitted','generating','failed','downloaded','message','error'))
        now=time.monotonic()
        with _lock:
            previous=_sampled.get(key)
            if previous and previous[1]==signature and now-previous[0]<30:return
            _sampled[key]=(now,signature)
            if len(_sampled)>1000:_sampled.pop(next(iter(_sampled)))
    from app.services.redaction import redact
    payload = redact({'event': event, **fields})
    text = json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':'))
    getattr(_get(), level.lower(), _get().info)(text)


def path() -> Path:
    _get()
    return _PATH


def tail(max_chars=120000) -> str:
    _get()
    try:
        return read_tail(_PATH, max_chars)
    except Exception:
        return ''


def read_tail(file_path, max_chars=120000):
    """Bound allocations even when the on-disk log has grown very large."""
    limit = max(0, min(int(max_chars), 500000))
    if not limit:
        return ''
    try:
        with Path(file_path).open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - limit * 4))
            return stream.read(limit * 4).decode('utf-8', errors='replace')[-limit:]
    except OSError:
        return ''

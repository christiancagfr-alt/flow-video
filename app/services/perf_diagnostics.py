"""Bounded performance counters and a watchdog independent of the GUI loop.
No SQL, task payloads or local variables are captured.
"""
import functools
import sys
import threading
import time
from collections import defaultdict
from app.services import runtime_log

_lock = threading.Lock()
_stats = {}
_active = defaultdict(list)
_main_id = threading.main_thread().ident
_stop = threading.Event()
_last_beat = time.monotonic()
_started = False


def measured(category):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            started = time.monotonic()
            ident = threading.get_ident()
            name = fn.__qualname__
            with _lock:
                _active[ident].append(name)
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = (time.monotonic() - started) * 1000
                with _lock:
                    key = (category, ident == _main_id)
                    value = _stats.setdefault(key, [0, 0.0, 0.0])
                    value[0] += 1
                    value[1] += elapsed
                    value[2] = max(value[2], elapsed)
                    _active[ident].pop()
                    if not _active[ident]:
                        del _active[ident]
        return wrapped
    return decorate


def flush(elapsed):
    with _lock:
        values = dict(_stats)
        _stats.clear()
    for (category, ui), (count, total, maximum) in values.items():
        runtime_log.log('[PERF]', function=category, calls_per_sec=round(count/max(elapsed, .001), 3),
                        avg_ms=round(total/count, 3), max_ms=round(maximum, 3), UI_thread=ui)


def _watch():
    last_flush = time.monotonic()
    reported = -1
    while not _stop.wait(.05):
        now = time.monotonic()
        lag = (now - _last_beat) * 1000
        severity = next((label for limit, label in ((1000, 'FREEZE'), (500, 'SEVERE'),
                        (300, 'HIGH'), (100, 'WARNING')) if lag > limit), None)
        # One report per severity per stall, bounded even for an indefinitely blocked UI.
        rank = {'WARNING': 0, 'HIGH': 1, 'SEVERE': 2, 'FREEZE': 3}.get(severity, -1)
        if rank < 0:
            reported = -1
        elif rank > reported:
            reported = rank
            with _lock:
                executing = list(_active.get(_main_id, ()))
            frame = sys._current_frames().get(_main_id)
            stack = []
            while frame is not None and len(stack) < 12:
                stack.append(f'{frame.f_code.co_name}:{frame.f_lineno}')
                frame = frame.f_back
            runtime_log.log('[UI_WATCHDOG]', level='WARNING', severity=severity,
                            stalled_ms=round(lag), executing=executing, stack=stack)
        if now-last_flush >= 5:
            flush(now-last_flush)
            last_flush = now
    flush(max(time.monotonic()-last_flush, .001))


def start(app):
    global _started, _last_beat
    if _started:
        return
    from PySide6.QtCore import QTimer, Qt
    _started = True
    _last_beat = time.monotonic()
    def beat():
        global _last_beat
        _last_beat = time.monotonic()
    timer = QTimer(app)
    timer.setTimerType(Qt.PreciseTimer)
    timer.setInterval(25)
    timer.timeout.connect(beat)
    timer.start()
    app.aboutToQuit.connect(_stop.set)
    app._perf_timer = timer
    threading.Thread(target=_watch, name='flow-perf-watchdog', daemon=True).start()

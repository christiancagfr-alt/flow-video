"""One worker, one pending call per key, and queued Qt-thread delivery.
Manual UI transactions pause dispatch without ever waiting on Future.result().
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from PySide6.QtCore import QObject, Signal, Slot, Qt

class SerialLane(QObject):
    completed = Signal(object, object, object)
    def __init__(self, parent):
        super().__init__(parent)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='flow-production')
        self.pending = OrderedDict()
        self.manual = OrderedDict()
        self.running = False
        self.closed = False
        self.in_manual = False
        self.completed.connect(self._deliver, Qt.QueuedConnection)
        executor = self.executor
        self.destroyed.connect(lambda: executor.shutdown(wait=False, cancel_futures=True))

    def submit(self, key, function, argument, callback):
        if self.closed: return
        self.pending[key] = (function, argument, callback)
        self._pump()

    def ui_transaction(self, key, function):
        if self.closed: return
        self.manual[key] = function
        self._pump()

    def _pump(self):
        if self.running or self.closed or self.in_manual: return
        if self.manual:
            _, function = self.manual.popitem(last=False)
            self.in_manual = True
            try:
                function()
            finally:
                self.in_manual = False
                self._pump()
            return
        if not self.pending: return
        _, (function, argument, callback) = self.pending.popitem(last=False)
        self.running = True
        future = self.executor.submit(function, argument)
        def done(future):
            try: result, error = future.result(), None
            except Exception as exc: result, error = None, str(exc)
            try: self.completed.emit(callback, result, error)
            except RuntimeError: pass
        future.add_done_callback(done)

    @Slot(object, object, object)
    def _deliver(self, callback, result, error):
        # Keep running=True while callbacks execute; nested event loops cannot
        # start a second dispatch or a conflicting manual transaction.
        try:
            callback(result, error)
        finally:
            self.running = False
            self._pump()

    def close(self):
        self.closed = True
        self.pending.clear()
        self.manual.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)


def production_ui_action(function):
    """Serialize legacy manual dialogs/actions with automatic workers."""
    @wraps(function)
    def guarded(self, *args, **kwargs):
        lane = getattr(self, '_production_lane', None)
        if lane is None or lane.in_manual:
            return function(self, *args, **kwargs)
        from app.core import work_dates
        day = work_dates.active()
        def run():
            if day == work_dates.active(): function(self, *args, **kwargs)
        lane.ui_transaction(function.__name__, run)
    return guarded

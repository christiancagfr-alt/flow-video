"""One bounded read-only worker per view; GUI changes are delivered on the Qt thread."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal, Slot, Qt

class SnapshotReader(QObject):
    ready = Signal(object, object, object)
    _done = Signal(object, object, object)

    def __init__(self, parent, loader):
        super().__init__(parent)
        self.loader = loader
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='view-read')
        self.future = None
        self.pending = None
        self._done.connect(self._deliver, Qt.QueuedConnection)
        executor=self.executor
        self.destroyed.connect(lambda: executor.shutdown(wait=False, cancel_futures=True))

    def request(self, key):
        if self.future is not None:
            self.pending = key
            return
        self.future = self.executor.submit(self.loader, key)
        self.future.add_done_callback(lambda f, k=key: self._finished(k, f))

    def _finished(self, key, future):
        try:
            result, error = future.result(), None
        except Exception as exc:
            result, error = None, str(exc)
        try:
            self._done.emit(key, result, error)
        except RuntimeError:
            pass

    @Slot(object, object, object)
    def _deliver(self, key, result, error):
        self.future = None
        self.ready.emit(key, result, error)
        pending, self.pending = self.pending, None
        if pending is not None:
            self.request(pending)

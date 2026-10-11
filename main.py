from app.services.quiet_runtime import configure
configure()
import os
# Keep Qt multimedia/FFmpeg diagnostics out of the terminal during normal playback.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false;qt.multimedia.*=false")
import sys
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from app.ui.main_window import MainWindow

from PySide6.QtCore import QThread
def exception_hook(exc_type, exc_value, exc_tb):
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    from app.services.redaction import redact
    print(redact(detail), file=sys.stderr)
    try:
        if QThread.currentThread() == QApplication.instance().thread():
            QMessageBox.critical(
                None,
                "Flow Studio 发生错误",
                f"{exc_type.__name__}: {exc_value}\n\n详细错误已保存到 data/logs/runtime.log。"
            )
    except Exception:
        pass

if __name__ == "__main__":
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FlowStudio.Desktop')
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        _installer_mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'FlowStudio.Desktop.Running')
    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Flow Studio")
    from app.version import VERSION
    app.setApplicationVersion(VERSION)
    from app.services.perf_diagnostics import start
    start(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

from app.services.quiet_runtime import configure
configure()
import os
# Keep Qt multimedia/FFmpeg diagnostics out of the terminal during normal playback.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false;qt.multimedia.*=false")
import sys
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from app.ui.main_window import MainWindow

from PySide6.QtCore import QThread, QTimer
_showing_error_dialog = False
def exception_hook(exc_type, exc_value, exc_tb):
    global _showing_error_dialog
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    from app.services.redaction import redact
    print(redact(detail), file=sys.stderr)
    try:
        app_inst = QApplication.instance()
        if app_inst is not None and QThread.currentThread() == app_inst.thread() and not _showing_error_dialog:
            _showing_error_dialog = True
            msg = redact(f"{exc_type.__name__}: {exc_value}")+"\n\n详细错误已保存到 data/logs/runtime.log。"
            def _show_err():
                global _showing_error_dialog
                try:
                    QMessageBox.critical(None, "Flow Studio 发生错误", msg)
                finally:
                    _showing_error_dialog = False
            QTimer.singleShot(0, _show_err)
    except Exception:
        _showing_error_dialog = False

if __name__ == "__main__":
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FlowStudio.Desktop')
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        _installer_mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'FlowStudio.Desktop.Running')
    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    from PySide6.QtGui import QFont
    if sys.platform == "darwin":
        QFont.insertSubstitution("Sans Serif", ".AppleSystemUIFont")
        app.setFont(QFont(".AppleSystemUIFont", 13))
    else:
        default_family = app.font().family()
        if default_family and default_family != "Sans Serif":
            QFont.insertSubstitution("Sans Serif", default_family)
    app.setStyle("Fusion")
    app.setApplicationName("Flow Studio")
    from app.version import VERSION
    app.setApplicationVersion(VERSION)
    from app.services.perf_diagnostics import start
    start(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

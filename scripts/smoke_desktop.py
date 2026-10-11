"""Offline smoke test usable on all release platforms."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if sys.platform=='darwin':
    import objc, AVFoundation, AVKit, CoreMedia, AppKit
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from unittest.mock import patch
from app.services.local_bridge import FlowStudioBridge
from app.ui.main_window import MainWindow
from app.ui.update_dialog import UpdateDialog
from app.version import VERSION
app=QApplication([])
with patch.object(FlowStudioBridge,'start'):window=MainWindow()
window.show();dialog=UpdateDialog(window);dialog.show()
assert VERSION in window.windowTitle()
assert not window.windowIcon().isNull()
QTimer.singleShot(700,app.quit)
assert app.exec()==0
print('Desktop icon, version, updater dialog and UI startup passed')

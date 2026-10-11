"""Offline GUI startup and native media import smoke test."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import objc, AVFoundation, AVKit, CoreMedia, AppKit
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from unittest.mock import patch
from app.services.local_bridge import FlowStudioBridge
from app.ui.main_window import MainWindow
app=QApplication([])
with patch.object(FlowStudioBridge,'start'):
    window=MainWindow()
window.show()
QTimer.singleShot(1000,app.quit)
assert app.exec()==0
assert window.width()>0
print('macOS application startup and native media imports passed')

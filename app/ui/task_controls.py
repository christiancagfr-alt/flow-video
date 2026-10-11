
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QCheckBox, QPushButton, QComboBox, QLabel
)


class CleanComboBox(QComboBox):
    """QComboBox with a clean rounded dropdown indicator instead of macOS native square."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self.setMinimumWidth(112)
        self._arrow = QLabel("⌄", self)
        self._arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._arrow.setAlignment(Qt.AlignCenter)
        self._arrow.setObjectName("comboArrow")
        self._arrow.resize(26, 26)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrow.move(self.width() - 31, max(0, (self.height() - 26)//2))


class FillHandleButton(QPushButton):
    """Small round spreadsheet-like fill handle that can be dragged vertically."""
    drag_started = Signal(bool)
    drag_moved_global = Signal(object)
    drag_finished = Signal()

    def __init__(self, checkbox, parent=None):
        super().__init__(parent)
        self.checkbox = checkbox
        self.setObjectName("fillHandle")
        self.setFixedSize(4, 4)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("按住向下拖动，可批量复制当前勾选/取消状态")
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.grabMouse()
            self.drag_started.emit(self.checkbox.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.drag_moved_global.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.releaseMouse()
            self.drag_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CheckCell(QWidget):
    """Large checkbox + round fill handle, centered inside a table cell."""
    changed = Signal(bool)
    drag_started = Signal(bool)
    drag_moved_global = Signal(object)
    drag_finished = Signal()

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setObjectName("checkCell")
        self.setMinimumWidth(48)
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 0, 5, 0)
        row.setSpacing(4)
        row.setAlignment(Qt.AlignCenter)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("largeCheck")
        self.checkbox.setFixedSize(20, 20)
        self.checkbox.setCursor(Qt.PointingHandCursor)
        self.checkbox.setChecked(bool(checked))
        self.checkbox.stateChanged.connect(lambda state: self.changed.emit(state == Qt.Checked))

        self.handle = FillHandleButton(self.checkbox)
        self.handle.drag_started.connect(self.drag_started)
        self.handle.drag_moved_global.connect(self.drag_moved_global)
        self.handle.drag_finished.connect(self.drag_finished)

        row.addWidget(self.checkbox)
        row.addWidget(self.handle)

    def isChecked(self):
        return self.checkbox.isChecked()

    def setChecked(self, value, block=False):
        if block:
            self.checkbox.blockSignals(True)
        self.checkbox.setChecked(bool(value))
        if block:
            self.checkbox.blockSignals(False)


class GenerationModeToggle(QWidget):
    """Shared per-segment FRAME/MATERIAL selector used by GPT, Flow and QC pages."""
    modeChanged = Signal(str)

    def __init__(self, mode="FRAME", parent=None, compact=True):
        super().__init__(parent)
        self._mode = "FRAME"
        self._block = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.frame_btn = QPushButton("帧", objectName="generationModeFrame")
        self.material_btn = QPushButton("素材", objectName="generationModeMaterial")
        # Keep the two labels readable even inside a dense table cell.  The widget
        # owns its minimum width so the parent table cannot squeeze “素材” into “帧”.
        button_w = 62 if compact else 72
        self.setMinimumWidth(button_w * 2 + 4)
        for btn in (self.frame_btn, self.material_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(30 if compact else 34)
            btn.setFixedWidth(button_w)
        self.frame_btn.clicked.connect(lambda: self.setMode("FRAME", emit=True))
        self.material_btn.clicked.connect(lambda: self.setMode("MATERIAL", emit=True))
        row.addWidget(self.frame_btn)
        row.addWidget(self.material_btn)
        self.setMode(mode, emit=False)

    @staticmethod
    def normalize(mode):
        raw = str(mode or "").strip().upper()
        return "MATERIAL" if raw in {"MATERIAL", "VIDEO_REFERENCES", "素材"} else "FRAME"

    def mode(self):
        return self._mode

    def setMode(self, mode, emit=False):
        mode = self.normalize(mode)
        changed = mode != self._mode
        self._mode = mode
        self.frame_btn.setChecked(mode == "FRAME")
        self.material_btn.setChecked(mode == "MATERIAL")
        # Checked-state colors are supplied by the global LIGHT/DARK stylesheet so
        # this control always follows the current application theme.
        if emit and changed and not self._block:
            self.modeChanged.emit(mode)

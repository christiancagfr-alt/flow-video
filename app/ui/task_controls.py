
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


class _ShiftAwareCheckBox(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_modifiers = Qt.NoModifier

    def mousePressEvent(self, event):
        self.last_modifiers = event.modifiers()
        super().mousePressEvent(event)


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

        self.checkbox = _ShiftAwareCheckBox()
        self.checkbox.setObjectName("largeCheck")
        self.checkbox.setFixedSize(20, 20)
        self.checkbox.setCursor(Qt.PointingHandCursor)
        self.checkbox.setChecked(bool(checked))
        self.checkbox.stateChanged.connect(lambda _state: self.changed.emit(self.checkbox.isChecked()))

        self.handle = FillHandleButton(self.checkbox)
        self.handle.drag_started.connect(self.drag_started)
        self.handle.drag_moved_global.connect(self.drag_moved_global)
        self.handle.drag_finished.connect(self.drag_finished)

        row.addWidget(self.checkbox)
        row.addWidget(self.handle)

    def consume_modifiers(self):
        mods = getattr(self.checkbox, "last_modifiers", Qt.NoModifier)
        self.checkbox.last_modifiers = Qt.NoModifier
        return mods

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

    def __init__(self, mode="FRAME", parent=None, compact=True, video_model="", mini=False):
        super().__init__(parent)
        self._mode = "FRAME"
        self._video_model = ""
        self._compact = compact
        self._block = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.frame_btn = QPushButton("帧", objectName="generationModeFrame")
        self.material_btn = QPushButton("素材", objectName="generationModeMaterial")
        # Keep the two labels readable even inside a dense table cell.  The widget
        # owns its minimum width so the parent table cannot squeeze “素材” into “帧”.
        button_w = 48 if mini else (62 if compact else 72)
        self.setMinimumWidth(button_w * 2 + 4)
        for btn in (self.frame_btn, self.material_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            if mini:
                # Small variant for dense tables (GPT prompt center): fits inside the column.
                btn.setProperty("mini", True)
                btn.setFixedHeight(26)
            else:
                btn.setMinimumHeight(30 if compact else 34)
            btn.setFixedWidth(button_w)
        self.frame_btn.clicked.connect(lambda: self._on_user_click("FRAME"))
        self.material_btn.clicked.connect(lambda: self._on_user_click("MATERIAL"))
        if mini:
            row.addStretch(1)
        row.addWidget(self.frame_btn)
        row.addWidget(self.material_btn)
        if mini:
            row.addStretch(1)
        self.setMode(mode, emit=False, video_model=video_model)

    @staticmethod
    def normalize(mode):
        raw = str(mode or "").strip().upper()
        return "MATERIAL" if raw in {"MATERIAL", "VIDEO_REFERENCES", "素材"} else "FRAME"

    @staticmethod
    def is_omini(video_model):
        return str(video_model or "").strip().lower() in {"flow_omni", "omni", "omini", "abra", "gemini_omni"}

    def mode(self):
        return self._mode

    def videoModel(self):
        return self._video_model

    def _on_user_click(self, mode):
        had_omini = self.is_omini(self._video_model)
        self.setMode(mode, emit=True, video_model="", force_emit=had_omini)

    def setVideoModel(self, video_model):
        self._video_model = "flow_omni" if self.is_omini(video_model) else ""
        self._refresh_visuals()

    def _refresh_visuals(self):
        omini = self.is_omini(self._video_model)
        omini_style = (
            "QPushButton { background: #7C3AED; color: #FFFFFF; border: 1px solid #8B5CF6; font-weight: 700; }"
            "QPushButton:hover { background: #6D28D9; }"
        )
        if omini:
            if self._mode == "MATERIAL":
                self.frame_btn.setText("帧")
                self.frame_btn.setStyleSheet("")
                self.material_btn.setText("Omini")
                self.material_btn.setStyleSheet(omini_style)
            else:
                self.frame_btn.setText("Omini")
                self.frame_btn.setStyleSheet(omini_style)
                self.material_btn.setText("素材")
                self.material_btn.setStyleSheet("")
            self.setToolTip("当前任务已设为使用 Omini 模型生成视频（默认 8 秒）")
        else:
            self.frame_btn.setText("帧")
            self.material_btn.setText("素材")
            self.frame_btn.setStyleSheet("")
            self.material_btn.setStyleSheet("")
            self.setToolTip("")

    def setMode(self, mode, emit=False, video_model=None, force_emit=False):
        mode = self.normalize(mode)
        changed = mode != self._mode
        self._mode = mode
        if video_model is not None:
            new_vm = "flow_omni" if self.is_omini(video_model) else ""
            if new_vm != self._video_model:
                changed = True
            self._video_model = new_vm
        self.frame_btn.setChecked(mode == "FRAME")
        self.material_btn.setChecked(mode == "MATERIAL")
        self._refresh_visuals()
        # Checked-state colors are supplied by the global LIGHT/DARK stylesheet so
        # this control always follows the current application theme.
        if emit and (changed or force_emit) and not self._block:
            self.modeChanged.emit(mode)

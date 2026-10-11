from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame


class ClickableFrame(QFrame):
    """Small reusable clickable card; avoids per-instance event monkey-patching."""
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

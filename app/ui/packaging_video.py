"""Clipped video surface: no native child window above neighbouring panels."""
from PySide6.QtCore import Qt, QRectF, QSizeF
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QSizePolicy
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem


class PackagingVideoView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.KeepAspectRatio)
        scene.addItem(self.video_item)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(Qt.black)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = QSizeF(self.viewport().size())
        self.video_item.setSize(size)
        self.setSceneRect(QRectF(0, 0, size.width(), size.height()))
